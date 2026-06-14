"""
v7/core/regime_engine.py — Regime Engine V7.

Extension du RegimeDetector V6 (3 régimes → 6 régimes).
Utilise les features existantes (ADX, Choppiness, ATR, correlation, volume)
pour produire des probabilités de régime (pas des labels binaires).

Régimes:
    BULL_EXPANSION   — ADX ↑, prix > SMA, volume ↑, corrélation ↓
    BULL_EXHAUSTION  — ADX ↓, prix > SMA, volume ↓, divergence
    BEAR_EXPANSION   — ADX ↑, prix < SMA, volume ↑, corrélation ↑
    BEAR_RALLY       — ADX ↓, prix < SMA, volume ↓, rebound
    VOLATILITY_CRUSH — ATR ↓, Choppiness ↑, range étroit
    PANIC            — ATR extrême, corrélation → 1, volume spike

Sortie: dict[str, float] — probabilité par régime (somme = 1)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

logger = logging.getLogger("regime_engine_v7")


@dataclass
class RegimeDistribution:
    probabilities: dict[str, float]  # ex: {"bull_expansion": 0.45, "bear_expansion": 0.15, ...}
    dominant: str                     # régime le plus probable
    confidence: float                 # confiance dans le régime dominant
    volatility_regime: str            # "low" | "normal" | "high" | "extreme"
    correlation_regime: str           # "low" | "normal" | "high"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class RegimeEngineV7:
    """Détecteur de régime probabiliste à 6 états."""

    # Seuils (calibrés sur historique crypto 2023-2026)
    ADX_TREND = 25.0
    ADX_STRONG = 35.0
    CHOPPINESS_RANGE = 50.0
    CHOPPINESS_CHOP = 65.0
    ATR_PERCENTILE_HIGH = 0.80
    ATR_PERCENTILE_EXTREME = 0.95
    VOLUME_PERCENTILE_HIGH = 0.75

    def __init__(self, atr_lookback: int = 100):
        self.atr_lookback = atr_lookback
        self._atr_history: list[float] = []

    def detect(
        self,
        adx: float,
        choppiness: float,
        atr: float,
        atr_pct: float,
        price_vs_sma50: float,   # >0 = au-dessus, <0 = en-dessous
        price_vs_sma200: float,
        volume_z: float,
        corr_btc: float = 0.85,
    ) -> RegimeDistribution:
        """Détecte le régime de marché à partir des features."""
        
        # Mettre à jour l'historique ATR
        self._atr_history.append(atr)
        if len(self._atr_history) > self.atr_lookback:
            self._atr_history = self._atr_history[-self.atr_lookback:]
        
        atr_percentile = (np.searchsorted(np.sort(self._atr_history), atr) / len(self._atr_history)
                          if len(self._atr_history) > 10 else 0.5)
        
        # ── Scores bruts par régime ──
        scores = {}
        
        # BULL_EXPANSION: tendance haussière forte, volume normal/élevé
        trend_up = 1.0 if price_vs_sma50 > 0 else 0.0
        trend_strong = min(1.0, adx / self.ADX_STRONG)
        scores["bull_expansion"] = (
            trend_up * 0.4 +
            trend_strong * 0.3 +
            (1.0 - min(1.0, choppiness / 100)) * 0.2 +
            min(1.0, max(0.0, volume_z / 2.0)) * 0.1
        )
        
        # BULL_EXHAUSTION: trend haussière qui s'essouffle
        scores["bull_exhaustion"] = (
            trend_up * 0.3 +
            (1.0 - trend_strong) * 0.3 +
            (choppiness / 100) * 0.2 +
            max(0.0, -volume_z / 2.0) * 0.2
        )
        
        # BEAR_EXPANSION: tendance baissière forte
        trend_down = 1.0 if price_vs_sma50 < 0 else 0.0
        scores["bear_expansion"] = (
            trend_down * 0.4 +
            trend_strong * 0.3 +
            (1.0 - min(1.0, choppiness / 100)) * 0.1 +
            min(1.0, max(0.0, volume_z / 2.0)) * 0.1 +
            min(1.0, corr_btc) * 0.1  # corrélation élevée en bear
        )
        
        # BEAR_RALLY: rebond dans tendance baissière
        scores["bear_rally"] = (
            trend_down * 0.2 +
            (1.0 - trend_strong) * 0.3 +
            max(0.0, price_vs_sma50) / 10 * 0.3 +  # petit rebond
            max(0.0, -volume_z / 2.0) * 0.2
        )
        
        # VOLATILITY_CRUSH: range, vol basse
        scores["vol_crush"] = (
            (1.0 - trend_strong) * 0.3 +
            (choppiness / 100) * 0.3 +
            (1.0 - min(1.0, atr_percentile)) * 0.3 +
            max(0.0, -abs(volume_z) / 2.0) * 0.1
        )
        
        # PANIC: vol extrême, corrélation → 1
        atr_extreme = 1.0 if atr_percentile > self.ATR_PERCENTILE_EXTREME else atr_percentile
        scores["panic"] = (
            atr_extreme * 0.5 +
            min(1.0, corr_btc) * 0.3 +
            min(1.0, max(0.0, volume_z / 3.0)) * 0.2
        )
        
        # ── Softmax → probabilités ──
        score_values = np.array(list(scores.values()))
        exp_scores = np.exp(score_values * 3)  # température = 1/3 pour accentuer
        probs = exp_scores / exp_scores.sum()
        
        probabilities = {
            name: round(float(p), 4)
            for name, p in zip(scores.keys(), probs)
        }
        
        dominant = max(probabilities, key=probabilities.get)
        confidence = probabilities[dominant]
        
        # Volatilité regime
        if atr_percentile > self.ATR_PERCENTILE_EXTREME:
            vol_regime = "extreme"
        elif atr_percentile > self.ATR_PERCENTILE_HIGH:
            vol_regime = "high"
        elif atr_percentile < 0.20:
            vol_regime = "low"
        else:
            vol_regime = "normal"
        
        # Corrélation regime
        if corr_btc > 0.90:
            corr_regime = "high"
        elif corr_btc < 0.50:
            corr_regime = "low"
        else:
            corr_regime = "normal"
        
        return RegimeDistribution(
            probabilities=probabilities,
            dominant=dominant,
            confidence=round(confidence, 3),
            volatility_regime=vol_regime,
            correlation_regime=corr_regime,
        )
    
    def to_legacy_regime(self, dist: RegimeDistribution) -> str:
        """Convertit en régime V6 (TREND/RANGE/CHOP) pour rétrocompatibilité."""
        dom = dist.dominant
        if dom in ("bull_expansion", "bear_expansion"):
            return "TREND"
        elif dom in ("bull_exhaustion", "bear_rally", "vol_crush"):
            return "RANGE"
        elif dom == "panic":
            return "CHOP"
        return "TREND"


# ── Test ──
if __name__ == "__main__":
    engine = RegimeEngineV7()
    
    # Scénario: bull market
    dist1 = engine.detect(
        adx=32, choppiness=35, atr=0.02, atr_pct=0.015,
        price_vs_sma50=0.05, price_vs_sma200=0.12,
        volume_z=1.2, corr_btc=0.75,
    )
    print(f"Bull: dominant={dist1.dominant} conf={dist1.confidence}")
    print(f"  Probs: {dist1.probabilities}")
    
    # Scénario: panic
    dist2 = engine.detect(
        adx=45, choppiness=20, atr=0.08, atr_pct=0.06,
        price_vs_sma50=-0.15, price_vs_sma200=-0.20,
        volume_z=3.5, corr_btc=0.95,
    )
    print(f"Panic: dominant={dist2.dominant} conf={dist2.confidence}")
    
    # Scénario: range
    dist3 = engine.detect(
        adx=18, choppiness=62, atr=0.01, atr_pct=0.008,
        price_vs_sma50=0.01, price_vs_sma200=0.03,
        volume_z=-0.5, corr_btc=0.60,
    )
    print(f"Range: dominant={dist3.dominant} conf={dist3.confidence}")
