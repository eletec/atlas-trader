"""
v7/nodes/funding_carry_node.py — DAG Node: Funding Carry V7.

Nœud compatible avec le framework DAG V4/V5/V6.
Fetch le funding rate, exécute FundingCarryEngine, produit un signal.

Intégration:
    Depuis demo_dag.py → ajouter FundingCarryNode dans le pipeline
    Output: signal carry (open/close/flat) + expected_return + size
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("funding_carry_node")


@dataclass
class FundingCarryState:
    """État persistant du nœud Funding Carry."""
    symbol: str
    position_open: bool = False
    entry_capital: float = 0.0
    negative_since: Optional[str] = None  # ISO timestamp
    total_funding_received: float = 0.0
    n_payments: int = 0
    last_funding_rate: float = 0.0
    last_signal: str = "flat"
    last_update: str = ""


class FundingCarryNode:
    """Nœud DAG pour le funding carry.
    
    Compatible avec le framework DAG Atlas.
    Implémente l'interface minimale: run(inputs), execute(inputs), output_schema().
    
    Usage dans un DAG:
        node = FundingCarryNode(node_id="btc_carry", symbol="BTC/USDT", capital=5000)
        outputs = node.run({"spot_price": 67000})
    """

    def __init__(
        self,
        node_id: str = "funding_carry",
        symbol: str = "BTC/USDT",
        capital: float = 10_000,
        fraction: float = 0.50,
        min_funding: float = 0.00005,
        max_funding: float = 0.003,
        exit_after_hours: int = 48,
        kelly_fraction: float = 0.5,
        fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        params: dict | None = None,
        meta: object = None,  # DAG framework NodeMeta
    ):
        # Si appelé via DAG framework (params dict), extraire les valeurs
        if params is not None:
            symbol = params.get("symbol", symbol)
            capital = params.get("capital", capital)
            fraction = params.get("fraction", fraction)
            min_funding = params.get("min_funding", min_funding)
            max_funding = params.get("max_funding", max_funding)
            exit_after_hours = params.get("exit_after_hours", exit_after_hours)
        
        self.node_id = node_id
        self.params = params or {}       # DAG framework
        self.meta = meta                 # DAG framework
        self.symbol = symbol
        self.capital = capital
        self.fraction = fraction
        self.min_funding = min_funding
        self.max_funding = max_funding
        self.exit_after_hours = exit_after_hours
        self.kelly_fraction = kelly_fraction
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        
        self.state = FundingCarryState(symbol=symbol)
        self._funding_cache: list[dict] = []  # historique récent
    
    # ── DAG framework compatibility ──
    
    @staticmethod
    def output_schema() -> dict[str, str]:
        return {
            "signal": "str", "size_usd": "float", "expected_return": "float",
            "confidence": "float", "reason": "str", "funding_rate": "float",
            "annual_funding_pct": "float", "position_open": "bool",
            "total_funding_received": "float", "n_payments": "int",
        }
    
    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"spot_price": "float", "funding_rate": "float", "perp_price": "float"}
    
    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Point d'entrée DAG framework → délègue à run()."""
        import time as _time
        t0 = _time.time()
        outputs = self.run(inputs)
        outputs["_duration_ms"] = (_time.time() - t0) * 1000
        return outputs
    
    # ── Data fetching ──
    
    def fetch_current_funding(self) -> float:
        """Fetch le funding rate actuel depuis Binance."""
        try:
            import ccxt
            exchange = ccxt.binance({"enableRateLimit": True})
            symbol_perp = f"{self.symbol}:USDT"
            rates = exchange.fetch_funding_rates([symbol_perp])
            if rates and symbol_perp in rates:
                return float(rates[symbol_perp]["fundingRate"])
        except Exception as e:
            logger.warning("Funding fetch failed for %s: %s", self.symbol, e)
        
        # Fallback: Binance public API
        try:
            import requests
            symbol_clean = self.symbol.replace("/", "")
            resp = requests.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": symbol_clean},
                timeout=10,
            )
            data = resp.json()
            return float(data.get("lastFundingRate", 0))
        except Exception:
            return 0.0
    
    # ── Decision logic ──
    
    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Exécute le nœud Funding Carry.
        
        Args:
            inputs: dict avec:
                - spot_price (float): prix spot actuel
                - funding_rate (float, optional): override le fetch auto
                - perp_price (float, optional): prix du perpetual
        
        Returns:
            dict avec signal, size_usd, expected_return, confidence, reason
        """
        t0 = time.time()
        
        spot_price = float(inputs.get("spot_price", 0))
        funding_rate = float(inputs.get("funding_rate", 0))
        perp_price = float(inputs.get("perp_price", spot_price))
        
        # Fetch funding rate si pas fourni
        if funding_rate == 0:
            funding_rate = self.fetch_current_funding()
        
        self.state.last_funding_rate = funding_rate
        self.state.last_update = datetime.now().isoformat()
        
        # ── Decision ──
        signal = "flat"
        size_usd = 0.0
        expected_return = 0.0
        confidence = 0.5
        reason = ""
        
        # Annualiser
        periods_per_year = 365 * 24 / 8
        annual_funding = funding_rate * periods_per_year
        
        # Basis check
        if perp_price > 0:
            basis_pct = (perp_price - spot_price) / spot_price
            basis_annual = basis_pct * periods_per_year
        else:
            basis_pct = 0.0
            basis_annual = 0.0
        
        if not self.state.position_open:
            # ── Opportunité d'ouverture ──
            if funding_rate >= self.min_funding and funding_rate <= self.max_funding:
                # Vérifier que le basis n'est pas trop défavorable
                if basis_pct > funding_rate * 3:
                    reason = f"basis défavorable ({basis_pct*100:.4f}% > funding×3)"
                    confidence = 0.3
                else:
                    expected_return = annual_funding - abs(basis_annual)
                    
                    if expected_return > 0.02:  # 2% annualisé minimum
                        # Kelly sizing dynamique
                        edge = expected_return
                        kelly_f = min(0.5, max(0.05, edge / 0.10))
                        size_usd = self.capital * self.fraction * kelly_f * self.kelly_fraction
                        
                        self.state.position_open = True
                        self.state.entry_capital = size_usd
                        self.state.negative_since = None
                        
                        signal = "open_carry"
                        confidence = min(0.90, 0.50 + kelly_f * 2)
                        reason = f"funding={funding_rate*100:.4f}% → {expected_return*100:.1f}%/an | size=${size_usd:.0f}"
                    else:
                        reason = f"retour {expected_return*100:.1f}%/an < 2% min"
                        confidence = 0.5
            else:
                reason = f"funding={funding_rate*100:.4f}% hors [min={self.min_funding*100:.4f}%, max={self.max_funding*100:.2f}%]"
        else:
            # ── Position ouverte ──
            if funding_rate > 0:
                # Recevoir funding
                payment = self.state.entry_capital * funding_rate
                self.state.total_funding_received += payment
                self.state.n_payments += 1
                signal = "flat"
                reason = f"carry actif | funding reçu={self.state.total_funding_received:.4f} ({self.state.n_payments} paiements)"
                confidence = 0.70
            elif funding_rate < 0:
                # Funding négatif → timer
                now = datetime.now()
                if self.state.negative_since is None:
                    self.state.negative_since = now.isoformat()
                
                try:
                    neg_start = datetime.fromisoformat(self.state.negative_since)
                    hours_neg = (now - neg_start).total_seconds() / 3600
                except Exception:
                    hours_neg = 0
                
                if hours_neg > self.exit_after_hours:
                    # Fermer
                    signal = "close_carry"
                    self.state.position_open = False
                    reason = f"funding négatif > {self.exit_after_hours}h → close"
                    confidence = 0.85
                else:
                    signal = "flat"
                    reason = f"funding négatif depuis {hours_neg:.0f}h (max {self.exit_after_hours}h)"
                    confidence = 0.50
            else:
                self.state.negative_since = None
        
        elapsed = time.time() - t0
        
        # ── Output ──
        outputs = {
            "signal": signal,
            "size_usd": round(size_usd, 2),
            "expected_return": round(expected_return, 4),
            "confidence": round(confidence, 2),
            "reason": reason,
            "funding_rate": funding_rate,
            "annual_funding_pct": round(annual_funding * 100, 2),
            "position_open": self.state.position_open,
            "total_funding_received": round(self.state.total_funding_received, 4),
            "n_payments": self.state.n_payments,
            "basis_pct": round(basis_pct * 100, 4),
            "elapsed_s": round(elapsed, 3),
        }
        
        logger.debug("[%s] signal=%s funding=%.6f size=$%.0f reason=%s",
                     self.node_id, signal, funding_rate, size_usd, reason)
        
        return outputs
    
    def reset(self):
        """Réinitialise l'état (pour backtest)."""
        self.state = FundingCarryState(symbol=self.symbol)
        self._funding_cache = []


# ── Test ──
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    
    node = FundingCarryNode(symbol="BTC/USDT", capital=10_000)
    
    # Simuler un signal d'ouverture
    result = node.run({
        "spot_price": 67000,
        "funding_rate": 0.0001,  # 0.01%
        "perp_price": 67005,
    })
    print(f"Signal: {result['signal']} | Size: ${result['size_usd']:.0f} | "
          f"Expected: {result['expected_return']*100:.1f}%/an | {result['reason']}")
    
    # Simuler paiement de funding
    result2 = node.run({
        "spot_price": 67100,
        "funding_rate": 0.0001,
    })
    print(f"Signal: {result2['signal']} | Funding reçu: {result2['total_funding_received']:.6f}")
    
    # Simuler funding négatif
    node.state.negative_since = (datetime.now() - timedelta(hours=50)).isoformat()
    result3 = node.run({
        "spot_price": 66800,
        "funding_rate": -0.00005,
    })
    print(f"Signal: {result3['signal']} | {result3['reason']}")
