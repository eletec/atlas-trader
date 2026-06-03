"""
v4/nodes/quant/compute_features.py — Nœuds ComputeFeatures + Normalize

Wrappers V4 autour de quant.features et quant.normalization.
Ne modifie pas ces modules.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from v4.core.node import Node


class ComputeFeatures(Node):
    """
    Calcule les features techniques à partir des OHLCV.

    Inputs  : ohlcv (DataFrame 5m)
    Outputs : features (DataFrame — colonnes brutes non normalisées)

    Params :
        feature_set : "full" | "light"  (défaut "full" — utilise DEFAULT_FEATURE_COLS de V3)
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
        return {"features": features}


class Normalize(Node):
    """
    Normalise les features avec rolling quantile (méthode V3).

    Inputs  : features (DataFrame brut), ohlcv (optionnel — pour reconstruire si besoin)
    Outputs : features_norm (DataFrame normalisé), features_all (brut + normalisé concaténé)

    Params :
        norm_window : int   — fenêtre rolling en barres (défaut 30 jours × 288 barres/j = 8640)
        method      : str   — "quantile" uniquement pour l'instant
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
        norm_window = self.params.get("norm_window", 8640)

        features_norm = normalize_features(
            features,
            window=norm_window,
            columns=self._NORM_COLS,
        )
        features_all = pd.concat([features, features_norm], axis=1)
        return {"features_norm": features_norm, "features_all": features_all}
