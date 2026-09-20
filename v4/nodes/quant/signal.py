"""
v4/nodes/quant/signal.py — SignalLogReg node

V4 wrapper around quant.signal_model.SignalModel + quant.strategy.decide.
Trains the model on the history and predicts P(up) on the last bar.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from v4.core.node import Node


class SignalLogReg(Node):
    """
    Trains a LogReg (+ optional Platt calibration) on the history
    and predicts P(up) on the last bar.

    Inputs  :
        features_all  (DataFrame — raw + norm concatenated)
        regime        (str — "TREND" | "RANGE" | "PANIC")

    Outputs :
        signal        (str  — "long" | "short" | "flat")
        prob_up       (float — P(up) ∈ [0, 1])
        reason        (str  — reason for the decision)

    Params :
        calibrate       : bool  — Platt calibration (default True)
        train_fraction  : float — training fraction (default 0.70)
        horizon_bars    : int   — target horizon in bars (default 48 = 4h at 5m)
        p_up_threshold  : float — LONG threshold (default 0.55)
        p_dn_threshold  : float — SHORT threshold (default 0.45)
    """

    @property
    def node_type(self) -> str:
        return "SignalLogReg"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"features_all": "DataFrame", "regime": "str"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"signal": "str", "prob_up": "float", "reason": "str"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        import traceback, logging
        _log = logging.getLogger("v4.nodes.quant.signal")
        try:
            return self._run_impl(inputs)
        except Exception as exc:
            _log.error("SignalLogReg failed: %s\n%s", exc, traceback.format_exc())
            return {"signal": "flat", "prob_up": 0.5, "reason": f"error:{exc}"}

    def _run_impl(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from quant.features import make_target_direction
        from quant.pipeline import DEFAULT_FEATURE_COLS, PipelineConfig
        from quant.signal_model import SignalModel
        from quant.strategy import Action, decide
        from v4.nodes.config_loader import load_v4_config

        features_all: pd.DataFrame = inputs["features_all"]
        regime: str = inputs.get("regime", "TREND")

        symbol = self.params.get("symbol", "")
        _cfg = load_v4_config(symbol, "signal", {
            "calibrate": True, "train_fraction": 0.70, "horizon_bars": 48,
            "p_up_threshold": 0.50, "p_dn_threshold": 0.50,
        })
        calibrate      = self.params.get("calibrate", _cfg["calibrate"])
        train_fraction = self.params.get("train_fraction", _cfg["train_fraction"])
        horizon_bars   = self.params.get("horizon_bars", _cfg["horizon_bars"])
        p_up_thresh    = self.params.get("p_up_threshold", _cfg["p_up_threshold"])
        p_dn_thresh    = self.params.get("p_dn_threshold", _cfg["p_dn_threshold"])

        feature_cols = list(DEFAULT_FEATURE_COLS)
        split = int(len(features_all) * train_fraction)
        train_idx = features_all.index[:split]

        # Directional target
        # make_target_direction expects an ohlcv — we rebuild it from features_all
        # when the close column is unavailable we cannot predict
        if "close" not in features_all.columns:
            return {"signal": "flat", "prob_up": 0.5, "reason": "no_close_column"}

        # Make sure close is a Series (not a DataFrame when columns are duplicated)
        close_series = features_all["close"]
        if isinstance(close_series, pd.DataFrame):
            close_series = close_series.iloc[:, 0]
        ohlcv_proxy = close_series.to_frame("close")
        y = make_target_direction(ohlcv_proxy, horizon=horizon_bars)

        model = SignalModel(
            feature_cols=feature_cols,
            use_calibration=calibrate,
        )
        available_cols = [c for c in feature_cols if c in features_all.columns]
        try:
            model.fit(features_all.loc[train_idx, available_cols + ["close"]], y.loc[train_idx])
        except ValueError as e:
            return {"signal": "flat", "prob_up": 0.5, "reason": f"fit_failed:{e}"}

        prob_up_series = model.predict_proba(features_all.iloc[[-1]][available_cols])
        prob_up = float(prob_up_series.iloc[0]) if prob_up_series is not None and len(prob_up_series) > 0 else 0.5

        regime_trending = regime == "TREND"
        decision = decide(
            probability_up=prob_up,
            regime_trending=regime_trending,
            upper_threshold=p_up_thresh,
            lower_threshold=p_dn_thresh,
        )

        return {
            "signal": decision.action.value,
            "prob_up": prob_up,
            "reason": decision.reason,
        }
