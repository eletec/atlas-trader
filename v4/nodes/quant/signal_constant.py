"""
v4/nodes/quant/signal_constant.py — SignalConstant node

Emits a fixed, configurable signal. Useful for:
  - Backtest: force a constant LONG or SHORT to validate the pipeline
  - Forced lane: a SHORT-only lane next to a normal signal lane
  - Test / dry-run: bypass the whole upstream pipeline
"""
from __future__ import annotations

from typing import Any

from v4.core.node import Node


class SignalConstant(Node):
    """
    Node without input — emits the signal defined in the params.

    Inputs  : none

    Outputs :
        signal  (str — "long" | "short" | "flat")
        prob_up (float — 1.0 for long, 0.0 for short, 0.5 for flat)

    Params :
        signal  : str — signal value (default "flat")
        prob_up : float — associated probability (default 0.5, auto-derived when omitted)
    """

    @property
    def node_type(self) -> str:
        return "SignalConstant"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"signal": "str", "prob_up": "float"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        signal = self.params.get("signal", "flat")

        prob_up = self.params.get("prob_up", None)
        if prob_up is None:
            prob_up = {"long": 1.0, "short": 0.0, "flat": 0.5}.get(signal, 0.5)
        else:
            prob_up = float(prob_up)

        return {"signal": signal, "prob_up": prob_up}
