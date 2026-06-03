"""
v4/nodes/quant/risk.py — Nœud RiskATR

Wrapper V4 autour de quant.risk.RiskManager.
Calcule le sizing, SL et TP à partir de l'ATR 1h.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from v4.core.node import Node


class RiskATR(Node):
    """
    Calcule la position (size, SL, TP) basée sur l'ATR du timeframe 1h.

    Inputs  :
        signal    (str   — "long" | "short" | "flat")
        ohlcv_1h  (DataFrame — OHLCV 1h pour calcul ATR)
        capital   (float — capital disponible en USD, optionnel si dans params)

    Outputs :
        decision  (dict  — {action, size_usd, entry_price, stop_loss, take_profit, reason})

    Params :
        sl_mult   : float — multiplicateur ATR pour SL (défaut 2.0)
        tp_mult   : float — multiplicateur ATR pour TP (défaut 4.0)
        fraction  : float — fraction du capital par trade (défaut 0.005)
        capital   : float — capital en USD (défaut 10000, surchargé par input capital)
    """

    @property
    def node_type(self) -> str:
        return "RiskATR"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"signal": "str", "ohlcv_1h": "DataFrame", "capital": "float"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"decision": "dict"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from quant.risk import RiskManager, RiskParams

        signal: str    = inputs.get("signal", "flat")
        ohlcv_1h: pd.DataFrame = inputs["ohlcv_1h"]
        capital: float = float(inputs.get("capital") or self.params.get("capital", 10_000.0))

        sl_mult  = self.params.get("sl_mult", 2.0)
        tp_mult  = self.params.get("tp_mult", 4.0)
        fraction = self.params.get("fraction", 0.005)

        if signal == "flat" or ohlcv_1h is None or ohlcv_1h.empty:
            return {"decision": {"action": "flat", "reason": "signal_flat"}}

        # ATR 1h (fenêtre 14)
        high = ohlcv_1h["high"]
        low  = ohlcv_1h["low"]
        close = ohlcv_1h["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]

        entry_price = float(close.iloc[-1])
        size_usd    = capital * fraction

        if signal == "long":
            stop_loss   = entry_price - sl_mult * atr
            take_profit = entry_price + tp_mult * atr
        else:  # short
            stop_loss   = entry_price + sl_mult * atr
            take_profit = entry_price - tp_mult * atr

        size_units = size_usd / entry_price

        return {
            "decision": {
                "action":      signal,
                "entry_price": entry_price,
                "stop_loss":   round(stop_loss, 4),
                "take_profit": round(take_profit, 4),
                "size_usd":    round(size_usd, 2),
                "size_units":  round(size_units, 6),
                "atr":         round(float(atr), 4),
                "reason":      f"atr_sl{sl_mult}_tp{tp_mult}",
            }
        }
