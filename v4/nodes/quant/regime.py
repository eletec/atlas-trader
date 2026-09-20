"""
v4/nodes/quant/regime.py — RegimeHMM + RegimePassthrough nodes

V4 wrappers around quant.regime.RegimeDetector.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from v4.core.node import Node


class RegimeHMM(Node):
    """
    Detects the market regime via GaussianHMM (or ADX/VoV fallback).

    Inputs  : features_all (DataFrame — raw + norm concatenation)
    Outputs : regime (str — "TREND" | "RANGE" | "PANIC")
              regime_state (int — raw HMM state)

    Params :
        n_states        : int   — number of HMM states (default 3)
        use_hmm         : bool  — True = GaussianHMM, False = ADX/VoV fallback (default True)
        train_fraction  : float — training fraction (default 0.70)
    """

    @property
    def node_type(self) -> str:
        return "RegimeHMM"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"features_all": "DataFrame"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"regime": "str", "regime_state": "int"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from quant.pipeline import PipelineConfig
        from quant.regime import RegimeDetector

        features_all: pd.DataFrame = inputs["features_all"]
        use_hmm        = self.params.get("use_hmm", True)
        train_fraction = self.params.get("train_fraction", 0.70)

        cfg = PipelineConfig(use_hmm=use_hmm)
        split = int(len(features_all) * train_fraction)
        train_idx = features_all.index[:split]

        detector = RegimeDetector(use_hmm=cfg.use_hmm).fit(features_all.loc[train_idx])
        regime_label = detector.predict(features_all.iloc[[-1]])
        regime_state = int(detector._last_state) if hasattr(detector, "_last_state") else 0

        return {"regime": str(regime_label), "regime_state": regime_state}


class RegimePassthrough(Node):
    """
    Fixed-value replacement node — useful to simulate V2 (no HMM).

    Params :
        regime : "TREND" | "RANGE" | "PANIC"  (default "TREND")
    """

    @property
    def node_type(self) -> str:
        return "RegimePassthrough"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"regime": "str", "regime_state": "int"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        regime = self.params.get("regime", "TREND")
        return {"regime": regime, "regime_state": 0}
