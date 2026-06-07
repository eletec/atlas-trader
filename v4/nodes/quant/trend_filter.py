"""
v4/nodes/quant/trend_filter.py — Nœud TrendFilter

Calcule la tendance directionnelle depuis l'OHLCV 1h (resample 4h).
Méthode : SMA20 vs SMA50 sur barres 4h — équivalent standalone du
trend_4h_veto de la V3, mais en nœud réutilisable.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from v4.core.node import Node


class TrendFilter(Node):
    """
    Calcule la tendance de fond (4h) à partir de l'OHLCV 1h.

    Inputs  :
        ohlcv_1h  (DataFrame — OHLCV 1h)

    Outputs :
        trend     (str    — "bullish" | "bearish" | "neutral")
        sma20     (float  — valeur SMA20 4h)
        sma50     (float  — valeur SMA50 4h)
        slope     (float  — pente normalisée (sma20 - sma50) / sma50)

    Params :
        timeframe_resample : str   — période de resample (défaut "4h")
        sma_fast           : int   — SMA rapide (défaut 20)
        sma_slow           : int   — SMA lente (défaut 50)
        min_bars           : int   — barres 4h minimum (défaut 50)
    """

    @property
    def node_type(self) -> str:
        return "TrendFilter"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"ohlcv_1h": "DataFrame"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"trend": "str", "sma20": "float", "sma50": "float", "slope": "float"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        ohlcv_1h: pd.DataFrame = inputs["ohlcv_1h"]

        tf          = self.params.get("timeframe_resample", "4h")
        sma_fast    = self.params.get("sma_fast", 20)
        sma_slow    = self.params.get("sma_slow", 50)
        min_bars    = self.params.get("min_bars", 50)

        if ohlcv_1h is None or len(ohlcv_1h) < 20:
            return {"trend": "neutral", "sma20": 0.0, "sma50": 0.0, "slope": 0.0}

        close_4h = ohlcv_1h["close"].resample(tf).last().dropna()

        if len(close_4h) < min_bars:
            return {"trend": "neutral", "sma20": 0.0, "sma50": 0.0, "slope": 0.0}

        sma20_val = float(close_4h.rolling(sma_fast, min_periods=sma_fast).mean().iloc[-1])
        sma50_val = float(close_4h.rolling(sma_slow, min_periods=sma_slow).mean().iloc[-1])

        if pd.isna(sma20_val) or pd.isna(sma50_val) or sma50_val == 0.0:
            return {"trend": "neutral", "sma20": sma20_val, "sma50": sma50_val, "slope": 0.0}

        slope = (sma20_val - sma50_val) / sma50_val

        if sma20_val > sma50_val:
            trend = "bullish"
        elif sma20_val < sma50_val:
            trend = "bearish"
        else:
            trend = "neutral"

        return {"trend": trend, "sma20": sma20_val, "sma50": sma50_val, "slope": round(slope, 6)}
