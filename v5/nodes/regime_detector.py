"""
v5/nodes/regime_detector.py — Regime Detector V5.

Remplace RegimePassthrough. Détecte 3 régimes :
  - TREND : ADX > 25 et Choppiness < 50
  - RANGE : ADX < 20 ou Choppiness > 61.8
  - CHOP  : sinon (transition)

Adaptation automatique dans DirectionGate / MetaGate selon le régime.

Inputs  : ohlcv_1h (DataFrame)
Outputs : regime (str), adx (float), chop (float), atr_pct (float)

Params :
    adx_period        : int — période ADX (défaut: 14)
    chop_period       : int — période Choppiness (défaut: 14)
    trend_threshold   : float — ADX minimum pour TREND (défaut: 25)
    range_threshold   : float — ADX maximum pour RANGE (défaut: 20)
    chop_threshold    : float — Choppiness minimum pour RANGE (défaut: 61.8)
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from v4.core.node import Node

logger = logging.getLogger("v5.nodes.regime_detector")


class RegimeDetector(Node):
    """Détection de régime de marché : TREND / CHOP / RANGE."""

    @property
    def node_type(self) -> str:
        return "RegimeDetector"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"ohlcv_1h": "DataFrame"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"regime": "str", "adx": "float", "chop": "float", "atr_pct": "float"}

    @staticmethod
    def compute_adx(high, low, close, period=14):
        """Average Directional Index."""
        dm_plus = high.diff()
        dm_minus = -low.diff()
        dm_plus[dm_plus < 0] = 0
        dm_minus[dm_minus < 0] = 0

        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)

        atr = tr.rolling(period).mean()
        di_plus = 100 * (dm_plus.rolling(period).mean() / atr)
        di_minus = 100 * (dm_minus.rolling(period).mean() / atr)
        dx = 100 * ((di_plus - di_minus).abs() / (di_plus + di_minus))
        adx = dx.rolling(period).mean()
        return float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0.0

    @staticmethod
    def compute_choppiness(high, low, close, period=14):
        """Choppiness Index — 100 = range, 0 = trend."""
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr_sum = tr.rolling(period).sum()
        highest = high.rolling(period).max()
        lowest = low.rolling(period).min()
        chop = 100 * np.log10(atr_sum / (highest - lowest)) / np.log10(period)
        return float(chop.iloc[-1]) if not pd.isna(chop.iloc[-1]) else 50.0

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        ohlcv_1h = inputs.get("ohlcv_1h")
        if ohlcv_1h is None or len(ohlcv_1h) < 50:
            return {"regime": "TREND", "adx": 0.0, "chop": 50.0, "atr_pct": 0.0}

        high = ohlcv_1h["high"]
        low = ohlcv_1h["low"]
        close = ohlcv_1h["close"]

        adx_period = int(self.params.get("adx_period", 14))
        chop_period = int(self.params.get("chop_period", 14))
        trend_th = float(self.params.get("trend_threshold", 25))
        range_th = float(self.params.get("range_threshold", 20))
        chop_th = float(self.params.get("chop_threshold", 61.8))

        adx = self.compute_adx(high, low, close, adx_period)
        chop = self.compute_choppiness(high, low, close, chop_period)

        # ATR% pour sizing
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr_val = float(tr.rolling(14).mean().iloc[-1])
        atr_pct = round(atr_val / float(close.iloc[-1]) * 100, 4) if close.iloc[-1] > 0 else 0.0

        # ── Classification ──
        if adx > trend_th and chop < chop_th:
            regime = "TREND"
        elif adx < range_th or chop > chop_th:
            regime = "CHOP"
        else:
            regime = "RANGE"

        logger.info(
            "RegimeDetector: %s (ADX=%.1f, CHOP=%.1f, ATR=%.2f%%)",
            regime, adx, chop, atr_pct,
        )

        return {
            "regime": regime,
            "adx": round(adx, 2),
            "chop": round(chop, 2),
            "atr_pct": atr_pct,
        }
