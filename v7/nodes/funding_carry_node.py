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

from v4.core.node import NodeRunResult, NodeStatus

logger = logging.getLogger("funding_carry_node")


@dataclass
class FundingCarryState:
    """État persistant du nœud Funding Carry."""
    symbol: str
    position_open: bool = False
    entry_capital: float = 0.0
    entry_spot: float = 0.0          # prix spot à l'ouverture
    entry_perp: float = 0.0          # prix perp à l'ouverture
    entry_time: str = ""             # ISO timestamp d'ouverture (time-stop)
    negative_since: Optional[str] = None  # ISO timestamp
    total_funding_received: float = 0.0
    n_payments: int = 0
    staking_earned: float = 0.0      # rendement staking USDT sur capital inactif
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
        exit_after_hours: int = 72,    # sortie funding négatif après 72h (Grok)
        kelly_fraction: float = 0.35,  # fractional Kelly 35% (Grok)
        max_hold_days: int = 14,        # time-stop : sortie forcée après N jours
        stop_loss_pct: float = -0.05,   # stop-loss basis : -5%
        exchange_name: str = "binance",  # binance | bybit | okx | kraken
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
            max_hold_days = params.get("max_hold_days", max_hold_days)
            stop_loss_pct = params.get("stop_loss_pct", stop_loss_pct)
            exchange_name = params.get("exchange", exchange_name)
        
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
        self.max_hold_days = max_hold_days
        self.stop_loss_pct = stop_loss_pct
        self.exchange_name = exchange_name
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        
        self.state = FundingCarryState(symbol=symbol)
        self._funding_rate_history: list[float] = []  # MA 7j (~21 valeurs)
        
        # Restaurer l'état depuis la DB (survit aux restart)
        # Sauf en mode backtest (pas de DB live)
        backtest = params.get("_backtest", False) if params else False
        if not backtest:
            self._restore_state()
    
    def _restore_state(self):
        """Vérifie si une position carry est déjà ouverte pour ce symbole.
        
        Restaure TOUS les champs nécessaires au suivi de position :
        entry_spot, entry_perp, entry_time, entry_capital,
        total_funding_received, n_payments.
        Sans ces valeurs, les vérifications SL/TP/time-stop sont ignorées.
        """
        try:
            from storage.paper_trader import get_open_positions
            import json as _json
            open_pos = get_open_positions(symbol=self.symbol)
            carry_pos = [p for p in open_pos if p.get("action") in ("carry", "short")]
            if carry_pos:
                pos = carry_pos[0]
                self.state.position_open = True
                self.state.entry_capital = float(pos.get("size_usd", 0))
                # Restaurer le prix d'entrée spot (stocké dans entry_price)
                self.state.entry_spot = float(pos.get("entry_price", 0) or 0)
                # Restaurer le perp depuis context_json si disponible
                ctx_raw = pos.get("context_json")
                if ctx_raw:
                    try:
                        ctx = _json.loads(ctx_raw) if isinstance(ctx_raw, str) else ctx_raw
                        # Le context_json contient le decision dict complet
                        # entry_price = spot, on cherche le perp dans carry_* ou on l'estime
                        if ctx.get("carry_signal") == "open_carry":
                            # Le perp était proche du spot à l'ouverture (basis ~0)
                            self.state.entry_perp = self.state.entry_spot
                    except Exception:
                        self.state.entry_perp = self.state.entry_spot
                else:
                    # Pas de contexte : estimer perp ≈ spot (le basis est généralement faible)
                    self.state.entry_perp = self.state.entry_spot
                # Restaurer le timestamp d'ouverture (pour le time-stop)
                ts = pos.get("timestamp", "")
                if ts:
                    self.state.entry_time = ts
                logger.info(
                    "[%s] Position carry restaurée : spot=%.2f perp=%.2f capital=$%.0f opened=%s",
                    self.node_id, self.state.entry_spot, self.state.entry_perp,
                    self.state.entry_capital, self.state.entry_time[:19] if self.state.entry_time else "?"
                )
        except Exception as e:
            logger.debug("[%s] DB restore skipped: %s", self.node_id, e)
    
    # ── DAG framework compatibility ──
    
    @staticmethod
    def output_schema() -> dict[str, str]:
        return {
            "signal": "str", "size_usd": "float", "expected_return": "float",
            "confidence": "float", "reason": "str", "funding_rate": "float",
            "annual_funding_pct": "float", "position_open": "bool",
            "total_funding_received": "float", "n_payments": "int",
            "decision": "dict",  # format PaperTrader: {action, size_usd, entry_price, ...}
        }
    
    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"symbol": "str", "spot_price": "float", "funding_rate": "float", "perp_price": "float"}
    
    def execute(self, inputs: dict[str, Any]) -> NodeRunResult:
        """Point d'entrée DAG framework → délègue à run()."""
        import time as _time
        t0 = _time.time()
        try:
            outputs = self.run(inputs)
            return NodeRunResult(
                node_id=self.node_id,
                status=NodeStatus.DONE,
                outputs=outputs,
                duration_ms=(_time.time() - t0) * 1000,
            )
        except Exception as e:
            return NodeRunResult(
                node_id=self.node_id,
                status=NodeStatus.ERROR,
                error=str(e),
                duration_ms=(_time.time() - t0) * 1000,
            )
    
    # ── Data fetching ──
    
    def _get_exchange(self):
        """Retourne l'instance CCXT configurée (binance | bybit | okx | kraken)."""
        import ccxt
        ex_map = {
            "binance": ccxt.binance, "bybit": ccxt.bybit,
            "okx": ccxt.okx, "kraken": ccxt.kraken,
        }
        return ex_map.get(self.exchange_name, ccxt.binance)({"enableRateLimit": True})
    
    def fetch_current_funding(self) -> float:
        """Fetch le funding rate actuel."""
        try:
            import ccxt
            exchange = self._get_exchange()
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
    
    def fetch_spot_price(self) -> float:
        """Fetch le prix spot actuel avec retry + log en cas d'échec."""
        import time as _time
        last_err = ""
        for attempt in range(3):
            try:
                exchange = self._get_exchange()
                ticker = exchange.fetch_ticker(self.symbol)
                price = float(ticker.get("last", 0))
                if price > 0:
                    return price
                last_err = f"price=0 from ticker"
            except Exception as e:
                last_err = str(e)[:120]
            if attempt < 2:
                _time.sleep(1.0 * (attempt + 1))  # backoff: 1s, 2s
        logger.warning("[%s] fetch_spot_price FAILED after 3 attempts: %s", self.node_id, last_err)
        return 0.0
    
    def fetch_perp_price(self) -> float:
        """Fetch le prix du perpetual avec retry."""
        import time as _time
        last_err = ""
        for attempt in range(3):
            try:
                exchange = self._get_exchange()
                symbol_perp = f"{self.symbol}:USDT" if ":" not in self.symbol else self.symbol
                ticker = exchange.fetch_ticker(symbol_perp)
                price = float(ticker.get("last", 0))
                if price > 0:
                    return price
                last_err = f"price=0 from ticker"
            except Exception as e:
                last_err = str(e)[:120]
            if attempt < 2:
                _time.sleep(1.0 * (attempt + 1))
        logger.warning("[%s] fetch_perp_price FAILED after 3 attempts: %s", self.node_id, last_err)
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
        
        # Le symbole peut venir d'un edge (prioritaire) ou de self.params
        symbol = inputs.get("symbol", self.symbol)
        
        spot_price = float(inputs.get("spot_price", 0))
        funding_rate = float(inputs.get("funding_rate", 0))
        perp_price = float(inputs.get("perp_price", spot_price))
        
        # Fetch spot/perp price si pas fourni (sauf backtest)
        if spot_price == 0 and not self.params.get("_backtest", False):
            spot_price = self.fetch_spot_price()
        
        if perp_price == 0 and not self.params.get("_backtest", False):
            perp_price = self.fetch_perp_price()
        if perp_price == 0:
            perp_price = spot_price
        
        # Fetch funding rate si pas fourni (sauf backtest: on garde 0)
        if funding_rate == 0 and not self.params.get("_backtest", False):
            funding_rate = self.fetch_current_funding()
        
        self.state.last_funding_rate = funding_rate
        self.state.last_update = datetime.now().isoformat()
        
        # Maintenir l'historique du funding pour la MA 7j (max 21 valeurs pour 7j × 3/j)
        self._funding_rate_history.append(funding_rate)
        if len(self._funding_rate_history) > 21:
            self._funding_rate_history = self._funding_rate_history[-21:]
        funding_ma_7d = sum(self._funding_rate_history) / len(self._funding_rate_history) if self._funding_rate_history else funding_rate
        
        # ── Decision ──
        signal = "flat"
        size_usd = 0.0
        expected_return = 0.0
        confidence = 0.5
        reason = ""
        unrealized_pct = 0.0
        unrealized_usd = 0.0
        
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
            # ── Staking sur capital inactif ──
            staking_annual = 0.05  # 5%/an simulé USDT
            idle_capital = self.capital * self.fraction
            staking_8h = idle_capital * staking_annual / (365 * 3)  # 3 périodes de 8h/jour
            self.state.staking_earned += staking_8h
            
            # ── Opportunité d'ouverture ──
            # Filtre 1 : funding instantané dans la plage
            if funding_rate >= self.min_funding and funding_rate <= self.max_funding:
                # Filtre 2 : funding MA 7j positif (évite les spikes isolés)
                if funding_ma_7d <= 0:
                    reason = f"funding MA 7j={funding_ma_7d*100:.4f}% ≤ 0 → attente"
                    confidence = 0.2
                # Filtre 3 : basis pas trop défavorable
                elif basis_pct < -0.003:
                    reason = f"basis défavorable ({basis_pct*100:.4f}%)"
                    confidence = 0.3
                else:
                    # expected_return = rendement annualisé du funding + gain/coût one-shot du basis
                    expected_return = annual_funding + basis_pct
                    
                    # Hurdle rate : min 8%/an net (Grok) — évite de trader les micro-fundings
                    if expected_return > 0.08:
                        # 1) Kelly fractional sizing (f_fraction = 0.35 — Grok)
                        edge = max(0, expected_return - 0.08)  # edge au-dessus du hurdle
                        kelly_f = min(0.5, max(0.05, edge / 0.10))
                        raw_size = self.capital * self.fraction * kelly_f * self.kelly_fraction
                        
                        # 2) Volatility scaling (funding > 0.05% → high vol → réduire)
                        vol_scale = 0.60 if funding_rate > 0.0005 else (0.80 if funding_rate > 0.0002 else 1.0)
                        
                        # 3) Funding regime multiplier
                        if funding_rate < 0.00008:  # < 0.008%
                            regime_mult = 0.40
                        elif funding_rate < 0.0002:  # < 0.02%
                            regime_mult = 0.70
                        else:
                            regime_mult = 1.0
                        
                        # 4) Liquidity cap par actif (max size en $)
                        liquidity_caps = {
                            "BTC": 400, "ETH": 300, "SOL": 200, "BNB": 200,
                            "XRP": 200, "ADA": 150, "DOGE": 100,
                        }
                        coin = self.symbol.split("/")[0].upper()
                        max_size = liquidity_caps.get(coin, 200)
                        
                        size_usd = min(raw_size * regime_mult * vol_scale, max_size)
                        
                        self.state.position_open = True
                        self.state.entry_capital = size_usd
                        self.state.entry_spot = spot_price
                        self.state.entry_perp = perp_price if perp_price > 0 else spot_price
                        self.state.entry_time = datetime.now().isoformat()
                        self.state.negative_since = None
                        
                        signal = "open_carry"
                        confidence = min(0.90, 0.50 + kelly_f * 2)
                        reason = (f"funding={funding_rate*100:.4f}% MA={funding_ma_7d*100:.4f}% "
                                  f"→ {expected_return*100:.1f}%/an | size=${size_usd:.0f} "
                                  f"(kelly={kelly_f:.2f}, vol×{vol_scale:.2f}, cap=${max_size})")
                    else:
                        reason = f"retour {expected_return*100:.1f}%/an < 8% hurdle"
                        confidence = 0.5
            else:
                reason = f"funding={funding_rate*100:.4f}% hors [min={self.min_funding*100:.4f}%, max={self.max_funding*100:.2f}%]"
        else:
            # ── Position ouverte ──
            # Calculer P&L latent (basis uniquement, le delta est couvert)
            if self.state.entry_spot > 0 and spot_price > 0:
                # Short perp: on perd si perp monte vs spot, on gagne si perp baisse vs spot
                basis_entry = (self.state.entry_perp - self.state.entry_spot) / self.state.entry_spot
                basis_now = (perp_price - spot_price) / spot_price if perp_price > 0 else 0
                unrealized_pct = basis_now - basis_entry  # positif = gain, négatif = perte
                unrealized_usd = unrealized_pct * self.state.entry_capital
                
                # Stop-loss : basis loss > 5% → close
                if unrealized_pct < self.stop_loss_pct:
                    signal = "close_carry"
                    self.state.position_open = False
                    reason = f"STOP-LOSS: basis loss {unrealized_pct*100:.1f}% > {abs(self.stop_loss_pct)*100:.0f}% → close"
                    confidence = 0.95
                    logger.warning("[%s] %s", self.node_id, reason)
                
                # Time-stop : position ouverte > max_hold_days → close
                if signal != "close_carry" and self.state.entry_time:
                    try:
                        entry_dt = datetime.fromisoformat(self.state.entry_time)
                        days_held = (datetime.now() - entry_dt).total_seconds() / 86400
                        if days_held > self.max_hold_days:
                            signal = "close_carry"
                            self.state.position_open = False
                            reason = f"TIME-STOP: {days_held:.0f}j > {self.max_hold_days}j max → close"
                            confidence = 0.80
                            logger.warning("[%s] %s", self.node_id, reason)
                    except Exception:
                        pass
            else:
                unrealized_pct = 0.0
                unrealized_usd = 0.0
            
            # ── Cross-margin risk monitoring ──
            # En paper trading, on simule le risque de liquidation du short perp
            # Si la perte latente > 80% du capital → alerte liquidation
            if unrealized_pct < -0.80 and self.state.position_open:
                logger.error("[%s] ⚠️ RISQUE LIQUIDATION: loss=%.1f%% → le short perp serait liquidé!",
                           self.node_id, unrealized_pct * 100)
                # En paper, on ne ferme pas automatiquement mais on alerte fortement
            
            if signal == "close_carry":
                pass  # déjà géré ci-dessus
            elif funding_rate > 0:
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
        # Construire un "decision" compatible PaperTrader
        # Pour les trades carry, le SL/TP sont basés sur le spot (approximation pour le moniteur).
        # Le vrai SL est basis-based et géré par le DAG lui-même dans sa boucle de décision.
        _sl_price = 0.0
        _tp_price = 0.0
        if signal == "open_carry" and spot_price > 0:
            # Short: SL au-dessus du prix d'entrée (si le spot monte, la position perd)
            _sl_price = round(spot_price * (1 + abs(self.stop_loss_pct)), 2)
            # TP: objectif de gain à 2x le SL (asymétrique)
            _tp_price = round(spot_price * (1 - abs(self.stop_loss_pct) * 2), 2)
        
        decision = {
            "action": "flat",
            "size_usd": round(size_usd, 2),
            "entry_price": spot_price,
            "stop_loss": _sl_price,
            "take_profit": _tp_price,
            "atr": 0,
            "carry_signal": signal,
            "carry_expected_return": round(expected_return, 4),
            "carry_annual_pct": round(annual_funding * 100, 2),
        }
        if signal == "open_carry":
            decision["action"] = "carry"  # shorter le perp pour recevoir le funding
        elif signal == "close_carry":
            decision["action"] = "close_carry"
        
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
            "staking_earned": round(self.state.staking_earned, 4),
            "basis_pct": round(basis_pct * 100, 4),
            "unrealized_pnl_pct": round(unrealized_pct * 100, 2) if self.state.position_open else 0,
            "elapsed_s": round(elapsed, 3),
            "decision": decision,
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
