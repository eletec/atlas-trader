"""
v4/nodes/quant/trend_filter.py — TrendFilter node

Computes the directional trend from the 1h OHLCV (4h resample).
Method: SMA20 vs SMA50 on 4h bars — standalone equivalent of the
trend_4h_veto of V3, but as a reusable node.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from v4.core.node import Node


class TrendFilter(Node):
    """
    Computes the background trend (4h) from the 1h OHLCV.

    Inputs  :
        ohlcv_1h  (DataFrame — OHLCV 1h)

    Outputs :
        trend     (str    — "bullish" | "bearish" | "neutral")
        sma20     (float  — SMA20 4h value)
        sma50     (float  — SMA50 4h value)
        slope     (float  — normalised slope (sma20 - sma50) / sma50)

    Params :
        timeframe_resample : str   — resample period (default "4h")
        sma_fast           : int   — fast SMA (default 20)
        sma_slow           : int   — slow SMA (default 50)
        min_bars           : int   — minimum 4h bars (default 50)
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
        from v4.nodes.config_loader import load_v4_config

        ohlcv_1h: pd.DataFrame = inputs["ohlcv_1h"]
        symbol = self.params.get("symbol", "")

        _cfg = load_v4_config(symbol, "trend", {
            "timeframe_resample": "4h", "sma_fast": 20, "sma_slow": 50,
        })
        tf          = self.params.get("timeframe_resample", _cfg["timeframe_resample"])
        sma_fast    = self.params.get("sma_fast", _cfg["sma_fast"])
        sma_slow    = self.params.get("sma_slow", _cfg["sma_slow"])
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
