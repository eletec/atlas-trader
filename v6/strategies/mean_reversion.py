"""
v6/strategies/mean_reversion.py — V6 Mean-Reversion Strategy for RANGE regime.

Activée automatiquement quand le RegimeDetector détecte RANGE.
Utilise RSI + Bollinger Bands + sizing réduit (30% vs trend).
Complémentaire au trend-following principal.

Recommandé par Gemini, DeepSeek, Claude, Kimi.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("v6.strategies.mean_reversion")


class MeanReversionSignal:
    """
    Signal mean-reversion pour marché en range.
    
    Logique :
    - LONG si RSI < 30 ET prix proche bande de Bollinger inférieure
    - SHORT si RSI > 70 ET prix proche bande de Bollinger supérieure
    - Sizing réduit (30% du trend-following)
    - TP fixe (0.5-1.0× ATR), pas de trailing
    - Time-stop plus court (12h au lieu de 48h)
    """

    def __init__(self, params: dict[str, Any] | None = None):
        self.params = params or {}
        self.rsi_period = int(self.params.get("rsi_period", 14))
        self.rsi_oversold = float(self.params.get("rsi_oversold", 30))
        self.rsi_overbought = float(self.params.get("rsi_overbought", 70))
        self.bb_period = int(self.params.get("bb_period", 20))
        self.bb_std = float(self.params.get("bb_std", 2.0))
        self.tp_atr_mult = float(self.params.get("tp_atr_mult", 1.0))
        self.size_fraction = float(self.params.get("size_fraction", 0.015))  # 1.5% du capital
        self.time_stop_hours = float(self.params.get("time_stop_hours", 12))

    def compute_signal(self, ohlcv_5m: pd.DataFrame) -> dict[str, Any]:
        """
        Calcule le signal mean-reversion à partir d'OHLCV 5m.
        
        Retourne : {signal, prob, confidence, entry_price, sl, tp, reason}
        """
        close = ohlcv_5m["close"]
        
        if len(close) < max(self.rsi_period, self.bb_period) + 5:
            return {"signal": "flat", "reason": "not_enough_data"}

        # RSI
        rsi = self._compute_rsi(close, self.rsi_period)
        
        # Bollinger Bands
        sma = close.rolling(self.bb_period, min_periods=self.bb_period).mean()
        std = close.rolling(self.bb_period, min_periods=self.bb_period).std()
        bb_upper = sma + self.bb_std * std
        bb_lower = sma - self.bb_std * std

        current_close = float(close.iloc[-1])
        current_rsi = float(rsi.iloc[-1])
        current_bb_lower = float(bb_lower.iloc[-1])
        current_bb_upper = float(bb_upper.iloc[-1])

        if pd.isna(current_rsi) or pd.isna(current_bb_lower):
            return {"signal": "flat", "reason": "indicator_nan"}

        # ATR pour SL/TP
        atr = self._compute_atr(ohlcv_5m)
        current_atr = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else current_close * 0.005

        # ── Signal LONG (mean-reversion haussière) ──
        if current_rsi <= self.rsi_oversold and current_close <= current_bb_lower * 1.01:
            confidence = min(1.0, (self.rsi_oversold - current_rsi) / 20.0 + 
                                       (current_bb_lower - current_close) / (current_atr + 1e-6) * 0.1)
            return {
                "signal": "long",
                "prob": 1.0 - current_rsi / 100.0,
                "confidence": round(confidence, 3),
                "entry_price": current_close,
                "sl": round(current_close - 1.5 * current_atr, 4),
                "tp": round(current_close + self.tp_atr_mult * current_atr, 4),
                "reason": f"mean_reversion_oversold_rsi={current_rsi:.0f}",
            }

        # ── Signal SHORT (mean-reversion baissière) ──
        if current_rsi >= self.rsi_overbought and current_close >= current_bb_upper * 0.99:
            confidence = min(1.0, (current_rsi - self.rsi_overbought) / 20.0 +
                                       (current_close - current_bb_upper) / (current_atr + 1e-6) * 0.1)
            return {
                "signal": "short",
                "prob": current_rsi / 100.0,
                "confidence": round(confidence, 3),
                "entry_price": current_close,
                "sl": round(current_close + 1.5 * current_atr, 4),
                "tp": round(current_close - self.tp_atr_mult * current_atr, 4),
                "reason": f"mean_reversion_overbought_rsi={current_rsi:.0f}",
            }

        return {"signal": "flat", "reason": "no_extreme"}

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
        loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
        rs = gain / (loss + 1e-9)
        return 100.0 * (1.0 - 1.0 / (1.0 + rs))

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high, low, close = df["high"], df["low"], df["close"]
        tr = pd.concat([high - low, (high - close.shift()).abs(),
                        (low - close.shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(period, min_periods=period).mean()


class MeanReversionExit:
    """Gestion de sortie spécifique au mean-reversion."""

    def __init__(self, params: dict[str, Any] | None = None):
        self.params = params or {}
        self.tp_atr_mult = float(self.params.get("tp_atr_mult", 1.0))
        self.sl_atr_mult = float(self.params.get("sl_atr_mult", 1.5))
        self.time_stop_hours = float(self.params.get("time_stop_hours", 12))

    def check_exit(self, position: dict, current_bar: pd.Series, atr: float) -> dict | None:
        """
        Vérifie si la position doit être clôturée.
        Retourne le dict de clôture ou None si on garde.
        """
        action = position.get("action", "long")
        entry = float(position.get("entry", 0))
        sl = float(position.get("sl", 0))
        tp = float(position.get("tp", 0))
        current = float(current_bar["close"])

        if action == "long":
            if current <= sl or current_bar["low"] <= sl:
                return {"action": "close", "reason": "sl_hit", "price": sl}
            if current >= tp or current_bar["high"] >= tp:
                return {"action": "close", "reason": "tp_hit", "price": tp}
        else:
            if current >= sl or current_bar["high"] >= sl:
                return {"action": "close", "reason": "sl_hit", "price": sl}
            if current <= tp or current_bar["low"] <= tp:
                return {"action": "close", "reason": "tp_hit", "price": tp}

        return None  # pas de clôture
