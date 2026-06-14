"""
v7/strategies/dominance_rotation.py — Bitcoin Dominance Rotation Strategy V7.

Utilise la dominance BTC (BTCD) pour alterner entre BTC et altcoins.
- BTCD en hausse → capital vers BTC (flight to safety)
- BTCD en baisse → capital vers alts (risk-on, alt season)

Données: CoinGecko API gratuite (BTC dominance globale).
Signal: SMA crossover sur BTCD + confirmation volume.

Usage:
    from v7.strategies.dominance_rotation import DominanceRotationEngine
    engine = DominanceRotationEngine(capital=10000)
    signal = engine.evaluate(btc_dominance=48.5, btc_price=67000)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger("dominance_rotation")


@dataclass
class DominanceSignal:
    action: str  # "alloc_btc" | "alloc_alts" | "flat"
    btc_dominance: float
    btcd_trend: str  # "rising" | "falling" | "neutral"
    allocation_btc: float  # 0-1, fraction du capital vers BTC
    allocation_alts: float  # 0-1, fraction vers alts
    confidence: float
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class DominanceRotationEngine:
    """Détecte les phases de dominance BTC et alloue le capital en conséquence.
    
    Stratégie:
    - BTCD > SMA(50j) → trend haussière → 70% BTC, 30% alts
    - BTCD < SMA(50j) → trend baissière → 30% BTC, 70% alts
    - BTCD extrême (>70%) → reversal probable → 90% alts
    - BTCD bas (<38%) → support historique → 90% BTC
    
    L'allocation est lissée (pas de switch brutal) pour éviter les whipsaws.
    """

    # Seuils historiques BTC dominance (2018-2026)
    BTCD_EXTREME_HIGH = 70.0  # alt season imminent
    BTCD_EXTREME_LOW = 38.0   # BTC undervalued vs alts
    BTCD_NEUTRAL = 50.0       # pivot

    def __init__(
        self,
        capital: float = 10_000,
        sma_period: int = 50,         # SMA jours pour tendance BTCD
        fraction_btc: float = 0.60,   # allocation BTC quand BTCD ↑
        fraction_alts: float = 0.60,  # allocation alts quand BTCD ↓
        min_confidence: float = 0.55, # seuil minimum pour agir
    ):
        self.capital = capital
        self.sma_period = sma_period
        self.fraction_btc = fraction_btc
        self.fraction_alts = fraction_alts
        self.min_confidence = min_confidence
        
        # Historique BTCD pour SMA
        self._btcd_history: list[float] = []
    
    def evaluate(
        self,
        btc_dominance: float,          # % dominance BTC (ex: 48.5)
        btc_price: float = 0,
        btc_volume_24h: float = 0,
    ) -> DominanceSignal:
        """Évalue le signal de rotation."""
        
        self._btcd_history.append(btc_dominance)
        if len(self._btcd_history) > self.sma_period * 2:
            self._btcd_history = self._btcd_history[-self.sma_period * 2:]
        
        # SMA
        lookback = min(len(self._btcd_history), self.sma_period)
        btcd_sma = sum(self._btcd_history[-lookback:]) / lookback if lookback > 0 else btc_dominance
        
        # Tendance
        if btc_dominance > btcd_sma * 1.02:
            btcd_trend = "rising"
        elif btc_dominance < btcd_sma * 0.98:
            btcd_trend = "falling"
        else:
            btcd_trend = "neutral"
        
        # ── Règles d'allocation ──
        
        # Extrême haut: BTCD > 70% → alts vont pump
        if btc_dominance > self.BTCD_EXTREME_HIGH:
            return DominanceSignal(
                action="alloc_alts",
                btc_dominance=btc_dominance,
                btcd_trend=btcd_trend,
                allocation_btc=0.10,
                allocation_alts=0.90,
                confidence=0.85,
                reason=f"BTCD extrême haut ({btc_dominance:.1f}% > {self.BTCD_EXTREME_HIGH}%) → alts",
            )
        
        # Extrême bas: BTCD < 38% → BTC sous-évalué
        if btc_dominance < self.BTCD_EXTREME_LOW:
            return DominanceSignal(
                action="alloc_btc",
                btc_dominance=btc_dominance,
                btcd_trend=btcd_trend,
                allocation_btc=0.90,
                allocation_alts=0.10,
                confidence=0.85,
                reason=f"BTCD extrême bas ({btc_dominance:.1f}% < {self.BTCD_EXTREME_LOW}%) → BTC",
            )
        
        # Trend haussière: BTCD ↑ → BTC domine
        if btcd_trend == "rising":
            confidence = min(0.80, 0.50 + (btc_dominance - btcd_sma) / btcd_sma * 10)
            return DominanceSignal(
                action="alloc_btc",
                btc_dominance=btc_dominance,
                btcd_trend=btcd_trend,
                allocation_btc=self.fraction_btc,
                allocation_alts=1.0 - self.fraction_btc,
                confidence=round(confidence, 2),
                reason=f"BTCD ↑ ({btc_dominance:.1f}% > SMA{lookback} {btcd_sma:.1f}%) → BTC {self.fraction_btc*100:.0f}%",
            )
        
        # Trend baissière: BTCD ↓ → alt season
        if btcd_trend == "falling":
            confidence = min(0.80, 0.50 + (btcd_sma - btc_dominance) / btcd_sma * 10)
            return DominanceSignal(
                action="alloc_alts",
                btc_dominance=btc_dominance,
                btcd_trend=btcd_trend,
                allocation_btc=1.0 - self.fraction_alts,
                allocation_alts=self.fraction_alts,
                confidence=round(confidence, 2),
                reason=f"BTCD ↓ ({btc_dominance:.1f}% < SMA{lookback} {btcd_sma:.1f}%) → alts {self.fraction_alts*100:.0f}%",
            )
        
        # Neutre
        return DominanceSignal(
            action="flat",
            btc_dominance=btc_dominance,
            btcd_trend=btcd_trend,
            allocation_btc=0.50,
            allocation_alts=0.50,
            confidence=0.50,
            reason=f"BTCD neutre ({btc_dominance:.1f}% ≈ SMA {btcd_sma:.1f}%)",
        )


# ── Test ──
if __name__ == "__main__":
    engine = DominanceRotationEngine(capital=10_000)
    
    # Alt season
    sig1 = engine.evaluate(btc_dominance=42.0)
    print(f"BTCD 42%: {sig1}")
    
    # BTC dominance rising
    sig2 = engine.evaluate(btc_dominance=55.0)
    print(f"BTCD 55%: {sig2}")
    
    # Extreme high
    for _ in range(50):
        engine.evaluate(btc_dominance=48.0)
    sig3 = engine.evaluate(btc_dominance=72.0)
    print(f"BTCD 72%: {sig3}")
