"""
v7/v7_dag.py — Atlas Trader V7 DAG (Minimum Viable).

Architecture simplifiée (consensus IA):
    Layer 1 (per asset, parallel)  → Data + Features + Regime V7
    Layer 2 (cross-asset)          → Dominance Rotation + Funding Carry + Mean Reversion
    Layer 3 (cross-asset)          → MetaAllocator
    Layer 4 (per asset)            → Risk Engine + PaperTrader

3 stratégies, 4 régimes, 1 allocateur.
Backtestable, débuggable, compréhensible.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("v7_dag")

# ── Stratégies V7 ──
from v7.strategies.funding_carry import FundingCarryEngine, CarrySignal
from v7.strategies.dominance_rotation import DominanceRotationEngine, DominanceSignal
from v7.core.meta_allocator import MetaAllocator, StrategyScore, MetaAllocation
from v7.core.regime_engine import RegimeEngineV7, RegimeDistribution

# ── Assets ──
ASSETS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
ALT_ASSETS = ["ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]


@dataclass
class AssetState:
    """État courant d'un actif."""
    symbol: str
    capital: float = 10_000
    spot_price: float = 0.0
    funding_rate: float = 0.0      # taux 8h
    adx: float = 20.0
    choppiness: float = 50.0
    atr: float = 0.01
    atr_pct: float = 0.01
    price_vs_sma50: float = 0.0
    price_vs_sma200: float = 0.0
    volume_z: float = 0.0
    regime: RegimeDistribution | None = None
    carry_signal: CarrySignal | None = None
    allocation: float = 0.0


@dataclass
class V7CycleResult:
    """Résultat d'un cycle V7 complet."""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    regime: dict = field(default_factory=dict)
    dominance: dict = field(default_factory=dict)
    allocations: dict = field(default_factory=dict)
    trades: list[dict] = field(default_factory=list)
    elapsed_s: float = 0.0
    errors: list[str] = field(default_factory=list)


class V7DAG:
    """Orchestrateur V7 — connecte les stratégies, l'allocateur et le risk engine.
    
    Cycle:
    1. Fetch data (OHLCV, funding rate, BTC dominance)
    2. Detect regime per asset (RegimeEngineV7)
    3. Run strategies (Funding Carry, Dominance Rotation)
    4. MetaAllocator → allocation capital
    5. Risk Engine → sizing + SL/TP
    6. PaperTrader → execution simulée
    """

    def __init__(self, capital: float = 10_000):
        self.capital = capital
        self.regime_engine = RegimeEngineV7()
        self.dominance_engine = DominanceRotationEngine(capital=capital)
        self.meta_allocator = MetaAllocator(capital=capital)
        
        # Un FundingCarryEngine par actif
        self.carry_engines: dict[str, FundingCarryEngine] = {
            sym: FundingCarryEngine(symbol=sym, capital=capital / len(ASSETS))
            for sym in ASSETS
        }
        
        self.states: dict[str, AssetState] = {
            sym: AssetState(symbol=sym, capital=capital / len(ASSETS))
            for sym in ASSETS
        }
        
        self._btc_dominance: float = 48.0  # % (sera mis à jour)
        self._cycle_count: int = 0
    
    # ── Layer 1: Data + Features + Regime ──
    
    def update_btc_dominance(self, value: float):
        """Met à jour la dominance BTC (source: CoinGecko API)."""
        self._btc_dominance = value
    
    def update_asset_data(
        self,
        symbol: str,
        spot_price: float,
        funding_rate: float = 0.0,
        adx: float = 20.0,
        choppiness: float = 50.0,
        atr: float = 0.01,
        atr_pct: float = 0.01,
        price_vs_sma50: float = 0.0,
        price_vs_sma200: float = 0.0,
        volume_z: float = 0.0,
    ):
        """Met à jour les features d'un actif (depuis le pipeline data V6)."""
        state = self.states.get(symbol)
        if not state:
            return
        state.spot_price = spot_price
        state.funding_rate = funding_rate
        state.adx = adx
        state.choppiness = choppiness
        state.atr = atr
        state.atr_pct = atr_pct
        state.price_vs_sma50 = price_vs_sma50
        state.price_vs_sma200 = price_vs_sma200
        state.volume_z = volume_z
    
    # ── Layer 2: Regime Detection ──
    
    def detect_regimes(self) -> dict[str, RegimeDistribution]:
        """Détecte le régime pour chaque actif."""
        regimes = {}
        for sym, state in self.states.items():
            if state.spot_price <= 0:
                continue
            dist = self.regime_engine.detect(
                adx=state.adx,
                choppiness=state.choppiness,
                atr=state.atr,
                atr_pct=state.atr_pct,
                price_vs_sma50=state.price_vs_sma50,
                price_vs_sma200=state.price_vs_sma200,
                volume_z=state.volume_z,
            )
            state.regime = dist
            regimes[sym] = dist
        return regimes
    
    # ── Layer 3: Strategies ──
    
    def run_strategies(self) -> dict[str, list[StrategyScore]]:
        """Exécute toutes les stratégies et collecte les signaux normalisés.
        
        Returns: {asset_symbol: [StrategyScore, ...]}
        """
        strategy_scores: dict[str, list[StrategyScore]] = {sym: [] for sym in ASSETS}
        
        # ── Dominance Rotation (cross-asset) ──
        dom_signal = self.dominance_engine.evaluate(
            btc_dominance=self._btc_dominance,
        )
        
        # Appliquer l'allocation dominance aux actifs
        for sym in ASSETS:
            if sym == "BTC/USDT":
                dom_score = dom_signal.allocation_btc - 0.5  # centré sur 0
            else:
                dom_score = dom_signal.allocation_alts / len(ALT_ASSETS) - 0.1
            
            strategy_scores[sym].append(StrategyScore(
                name="dominance_rotation",
                score=max(-1.0, min(1.0, dom_score * 2)),
                confidence=dom_signal.confidence,
                expected_return=0.08 if dom_signal.action != "flat" else 0.0,
            ))
        
        # ── Funding Carry (per asset) ──
        for sym in ASSETS:
            state = self.states[sym]
            engine = self.carry_engines[sym]
            carry_signal = engine.evaluate(
                funding_rate=state.funding_rate,
                spot_price=state.spot_price,
            )
            state.carry_signal = carry_signal
            
            strategy_scores[sym].append(StrategyScore(
                name="funding_carry",
                score=0.7 if carry_signal.action == "open_carry" else 0.0,
                confidence=carry_signal.confidence,
                expected_return=carry_signal.expected_return,
            ))
        
        return strategy_scores
    
    # ── Layer 4: Meta Allocation ──
    
    def allocate(self, strategy_scores: dict[str, list[StrategyScore]]) -> dict[str, MetaAllocation]:
        """Alloue le capital entre stratégies pour chaque actif."""
        allocations = {}
        for sym, scores in strategy_scores.items():
            state = self.states[sym]
            regime = state.regime.dominant if state.regime else "TREND"
            
            result = self.meta_allocator.allocate(strategies=scores, regime=regime)
            state.allocation = result.total_exposure
            allocations[sym] = result
        
        return allocations
    
    # ── Full Cycle ──
    
    def run_cycle(
        self,
        btc_dominance: float = 48.0,
        asset_data: dict[str, dict] | None = None,
    ) -> V7CycleResult:
        """Exécute un cycle complet V7.
        
        Args:
            btc_dominance: dominance BTC en %
            asset_data: {symbol: {spot_price, funding_rate, adx, ...}}
        """
        t0 = time.time()
        result = V7CycleResult()
        self._cycle_count += 1
        
        try:
            # 1. Update data
            self.update_btc_dominance(btc_dominance)
            if asset_data:
                for sym, data in asset_data.items():
                    self.update_asset_data(sym, **data)
            
            # 2. Detect regimes
            regimes = self.detect_regimes()
            result.regime = {
                sym: {"dominant": r.dominant, "confidence": r.confidence}
                for sym, r in regimes.items()
            }
            
            # 3. Run strategies
            strategy_scores = self.run_strategies()
            
            # 4. Meta Allocation
            allocations = self.allocate(strategy_scores)
            result.allocations = {
                sym: {
                    "total_exposure": a.total_exposure,
                    "risk_level": a.risk_level,
                    "strategies": [
                        {"name": al.strategy, "weight": al.weight, "size_usd": al.size_usd}
                        for al in a.allocations
                    ],
                }
                for sym, a in allocations.items()
            }
            
            # 5. Dominance signal
            dom_signal = self.dominance_engine.evaluate(self._btc_dominance)
            result.dominance = {
                "btcd": self._btc_dominance,
                "trend": dom_signal.btcd_trend,
                "action": dom_signal.action,
                "alloc_btc": dom_signal.allocation_btc,
                "alloc_alts": dom_signal.allocation_alts,
            }
            
        except Exception as e:
            result.errors.append(str(e))
            logger.error("V7 cycle error: %s", e)
        
        result.elapsed_s = time.time() - t0
        return result


# ── Test ──
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    
    dag = V7DAG(capital=70_000)
    
    # Simuler un cycle avec des données mock
    mock_data = {}
    for sym in ASSETS:
        mock_data[sym] = {
            "spot_price": 67000 if "BTC" in sym else 3500 if "ETH" in sym else 150,
            "funding_rate": 0.0001,
            "adx": 32,
            "choppiness": 35,
            "atr": 0.02,
            "atr_pct": 0.015,
            "price_vs_sma50": 0.05,
            "price_vs_sma200": 0.12,
            "volume_z": 1.2,
        }
    
    result = dag.run_cycle(btc_dominance=48.5, asset_data=mock_data)
    
    print(f"\n=== V7 Cycle #{dag._cycle_count} === ({result.elapsed_s:.3f}s)")
    print(f"Dominance: BTCD={result.dominance['btcd']}% → {result.dominance['action']}")
    print(f"Régimes:")
    for sym, r in result.regime.items():
        print(f"  {sym}: {r['dominant']} (conf={r['confidence']})")
    print(f"Allocations:")
    for sym, a in result.allocations.items():
        if a["strategies"]:
            strats = ", ".join(f"{s['name']}={s['weight']:.2f}" for s in a["strategies"])
            print(f"  {sym}: exposure={a['total_exposure']:.2f} risk={a['risk_level']} [{strats}]")
    if result.errors:
        print(f"Errors: {result.errors}")
