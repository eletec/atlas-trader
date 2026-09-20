"""
v4/nodes/quant/compute_features.py — ComputeFeatures + Normalize nodes

V4 wrappers around quant.features and quant.normalization.
Does not modify these modules.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from v4.core.node import Node


class ComputeFeatures(Node):
    """
    Computes the technical features from the OHLCV.

    Inputs  : ohlcv (DataFrame 5m)
    Outputs : features (DataFrame — raw, non-normalised columns)

    Params :
        feature_set : "full" | "light"  (default "full" — uses the DEFAULT_FEATURE_COLS of V3)
    """

    @property
    def node_type(self) -> str:
        return "ComputeFeatures"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"ohlcv": "DataFrame"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"features": "DataFrame"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from quant.features import compute_features

        ohlcv: pd.DataFrame = inputs["ohlcv"]
        features = compute_features(ohlcv)
        # Preserve the close column for downstream nodes (SignalLogReg)
        features["close"] = ohlcv["close"]
        return {"features": features}


class Normalize(Node):
    """
    Normalises the features with a rolling quantile (V3 method).

    Inputs  : features (raw DataFrame), ohlcv (optional — to rebuild when needed)
    Outputs : features_norm (normalised DataFrame), features_all (raw + normalised concatenated)

    Params :
        norm_window : int   — rolling window in bars (default 30 days × 288 bars/d = 8640)
        method      : str   — "quantile" only for now
    """

    _NORM_COLS = [
        "log_return_1", "log_return_4", "log_return_24", "log_return_96",
        "rsi_14", "macd_hist", "ema_cross", "roc_12",
        "atr_pct", "adx_14", "dist_ma50", "volume_z_20", "vol_of_vol_20",
        "vwap_dist_20", "bb_pct_b", "obv_proxy_20",
    ]

    @property
    def node_type(self) -> str:
        return "Normalize"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"features": "DataFrame"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"features_norm": "DataFrame", "features_all": "DataFrame"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from quant.normalization import normalize_features

        features: pd.DataFrame = inputs["features"]
        # Priority: norm_window > window (legacy DAG compatibility) > default 500
        norm_window = int(
            self.params.get("norm_window")
            or self.params.get("window", 500)
        )

        features_norm = normalize_features(
            features,
            window=norm_window,
            columns=self._NORM_COLS,
        )
        features_all = pd.concat([features, features_norm], axis=1)
        return {"features_norm": features_norm, "features_all": features_all}
