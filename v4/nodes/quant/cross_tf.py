"""
v4/nodes/quant/cross_tf.py — Nœud CrossTFArb (Cross-Timeframe Repricing)

Détecte le lag de repricing entre 5m et 1h pour capturer un edge microstructure.
Principe : quand le timeframe rapide (5m) bouge avant le lent (1h),
une fenêtre d'opportunité s'ouvre avant que le marché ne corrige.

Stratégies :
  - "divergence" : 5m bearish + 1h encore bullish → short (et vice-versa)
  - "confirmation" : les 2 TFs alignés → signal plus fort
  - "reversal" : 5m change de direction, 1h pas encore → signal de sortie

Sortie :
  - signal       : str   — "long" | "short" | "flat"
  - confidence   : float — force du signal [0, 1]
  - tf_divergence: float — degré de désalignement 5m/1h [-1, 1]
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from v4.core.node import Node

logger = logging.getLogger("v4.nodes.quant.cross_tf")


class CrossTFArb(Node):
    """
    Détecte les opportunités de microstructure cross-timeframe.

    Inputs :
        ohlcv_5m : DataFrame — OHLCV 5 minutes
        ohlcv_1h : DataFrame — OHLCV 1 heure

    Outputs :
        signal        : str   — "long" | "short" | "flat"
        confidence    : float — [0, 1]
        tf_divergence : float — mesure du lag [-1, 1]

    Params :
        mode           : str   — "divergence" (défaut) | "confirmation" | "reversal"
        momentum_5m    : int   — barres pour momentum 5m (défaut: 6 = 30 min)
        momentum_1h    : int   — barres pour momentum 1h (défaut: 4 = 4h)
        threshold      : float — seuil de déclenchement (défaut: 0.15 = 0.15%)
        strong_threshold: float — seuil fort (défaut: 0.40 = 0.40%)
        volume_filter  : bool  — exiger volume 5m > moyenne (défaut: True)
        atr_filter      : bool  — exiger range 5m > ATR/3 (défaut: True)
    """

    @property
    def node_type(self) -> str:
        return "CrossTFArb"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"ohlcv_5m": "DataFrame", "ohlcv_1h": "DataFrame"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"signal": "str", "confidence": "float", "tf_divergence": "float"}

    def _momentum(self, ohlcv: pd.DataFrame, n: int) -> float:
        """Calcule le momentum en % sur N barres : (close[-1] - close[-N]) / close[-N] * 100."""
        if ohlcv is None or len(ohlcv) < n + 1:
            return 0.0
        closes = ohlcv["close"]
        c_now = float(closes.iloc[-1])
        c_n = float(closes.iloc[-(n + 1)])
        if c_n <= 0:
            return 0.0
        return (c_now - c_n) / c_n * 100.0

    def _rolling_momentum(self, ohlcv: pd.DataFrame, n: int) -> pd.Series:
        """Série de momentum glissant sur N barres (en %)."""
        if ohlcv is None or len(ohlcv) < n + 1:
            return pd.Series(dtype=float)
        closes = ohlcv["close"]
        return (closes - closes.shift(n)) / closes.shift(n) * 100.0

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        ohlcv_5m: pd.DataFrame = inputs.get("ohlcv_5m")
        ohlcv_1h: pd.DataFrame = inputs.get("ohlcv_1h")

        # -- Input validation --
        if ohlcv_5m is None or not hasattr(ohlcv_5m, "iloc") or len(ohlcv_5m) < 20:
            return {"signal": "flat", "confidence": 0.0, "tf_divergence": 0.0,
                    "reason": "insufficient_5m_data"}
        if ohlcv_1h is None or not hasattr(ohlcv_1h, "iloc") or len(ohlcv_1h) < 8:
            return {"signal": "flat", "confidence": 0.0, "tf_divergence": 0.0,
                    "reason": "insufficient_1h_data"}

        # -- Parameters --
        mode = self.params.get("mode", "divergence")
        mom_n_5m = int(self.params.get("momentum_5m", 6))      # 30 min
        mom_n_1h = int(self.params.get("momentum_1h", 4))      # 4h
        threshold = float(self.params.get("threshold", 0.15))   # %
        strong_threshold = float(self.params.get("strong_threshold", 0.40))
        volume_filter = bool(self.params.get("volume_filter", True))
        atr_filter = bool(self.params.get("atr_filter", True))

        # -- Momentum computation --
        mom_5m = self._momentum(ohlcv_5m, mom_n_5m)  # % over 30 min
        mom_1h = self._momentum(ohlcv_1h, mom_n_1h)  # % over 4h

        # -- Divergence = 5m - 1h: positive means 5m is more bullish than 1h --
        divergence = mom_5m - mom_1h  # en points de %

        # ── Filtre volume 5m ──
        vol_ok = True
        if volume_filter:
            vol_recent = float(ohlcv_5m["volume"].iloc[-1])
            vol_ma = float(ohlcv_5m["volume"].iloc[-20:].mean())
            vol_ok = vol_recent >= vol_ma * 0.5
            if not vol_ok:
                logger.debug("CrossTF: volume 5m faible (%.0f < 0.5×MA %.0f)", vol_recent, vol_ma)

        # -- ATR filter (real range > ATR/3) --
        atr_ok = True
        if atr_filter and len(ohlcv_5m) >= 15:
            tr_5m = pd.concat([
                ohlcv_5m["high"] - ohlcv_5m["low"],
                (ohlcv_5m["high"] - ohlcv_5m["close"].shift()).abs(),
                (ohlcv_5m["low"] - ohlcv_5m["close"].shift()).abs(),
            ], axis=1).max(axis=1)
            atr_14 = float(tr_5m.rolling(14).mean().iloc[-1])
            current_range = float(ohlcv_5m["high"].iloc[-1] - ohlcv_5m["low"].iloc[-1])
            atr_ok = current_range >= atr_14 / 3.0 if atr_14 > 0 else True
            if not atr_ok:
                logger.debug("CrossTF: range 5m faible (%.4f < ATR/3=%.4f)", current_range, atr_14 / 3.0)

        # -- Decision depending on the mode --
        signal = "flat"
        confidence = 0.0

        if mode == "divergence":
            # La 5m diverge de la 1h : la 5m lead, la 1h va suivre
            # 5m bearish + 1h bullish (ou neutre) → short (5m anticipe baisse)
            # 5m bullish + 1h bearish (ou neutre) → long  (5m anticipe hausse)
            abs_div = abs(divergence)

            if mom_5m < -threshold and mom_1h > -threshold * 0.3 and vol_ok and atr_ok:
                # 5m clearly bearish, 1h not yet -> short
                signal = "short"
                confidence = min(abs_div / strong_threshold, 1.0)
                logger.info(
                    "CrossTF DIVERGENCE SHORT: 5m=%.2f%% 1h=%.2f%% div=%.2f conf=%.2f",
                    mom_5m, mom_1h, divergence, confidence,
                )
            elif mom_5m > threshold and mom_1h < threshold * 0.3 and vol_ok and atr_ok:
                # 5m clearly bullish, 1h not yet -> long
                signal = "long"
                confidence = min(abs_div / strong_threshold, 1.0)
                logger.info(
                    "CrossTF DIVERGENCE LONG: 5m=%.2f%% 1h=%.2f%% div=%.2f conf=%.2f",
                    mom_5m, mom_1h, divergence, confidence,
                )

        elif mode == "confirmation":
            # Both timeframes must align for a strong signal
            if mom_5m > threshold and mom_1h > threshold * 0.5:
                signal = "long"
                confidence = min((mom_5m + mom_1h) / (2 * strong_threshold), 1.0)
            elif mom_5m < -threshold and mom_1h < -threshold * 0.5:
                signal = "short"
                confidence = min(abs(mom_5m + mom_1h) / (2 * strong_threshold), 1.0)

        elif mode == "reversal":
            # 5m changed direction, 1h not yet -> exit/counter-trade signal
            mom_5m_prev = self._momentum(ohlcv_5m.iloc[:-mom_n_5m], mom_n_5m) if len(ohlcv_5m) > mom_n_5m * 2 else 0.0
            reversed_up = mom_5m > threshold and mom_5m_prev < -threshold * 0.5
            reversed_dn = mom_5m < -threshold and mom_5m_prev > threshold * 0.5

            if reversed_up and mom_1h < threshold * 0.3:
                signal = "long"
                confidence = 0.6
                logger.info("CrossTF REVERSAL LONG: 5m flipped bullish (prev=%.2f now=%.2f)", mom_5m_prev, mom_5m)
            elif reversed_dn and mom_1h > -threshold * 0.3:
                signal = "short"
                confidence = 0.6
                logger.info("CrossTF REVERSAL SHORT: 5m flipped bearish (prev=%.2f now=%.2f)", mom_5m_prev, mom_5m)

        # -- Normalise the divergence into [-1, 1] --
        tf_divergence = float(np.clip(divergence / (strong_threshold * 2), -1.0, 1.0))

        return {
            "signal": signal,
            "confidence": round(confidence, 4),
            "tf_divergence": round(tf_divergence, 4),
            "mom_5m_pct": round(mom_5m, 4),
            "mom_1h_pct": round(mom_1h, 4),
        }
