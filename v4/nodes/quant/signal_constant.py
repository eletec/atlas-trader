"""
v4/nodes/quant/signal_constant.py — Nœud SignalConstant

Émet un signal fixe configurable. Utile pour :
  - Backtest : forcer LONG ou SHORT constant pour valider le pipeline
  - Lane forcée : une lane SHORT-only à côté d'une lane signal normal
  - Test / dry-run : bypasser tout le pipeline amont
"""
from __future__ import annotations

from typing import Any

from v4.core.node import Node


class SignalConstant(Node):
    """
    Nœud sans entrée — émet le signal défini dans les params.

    Inputs  : aucun

    Outputs :
        signal  (str — "long" | "short" | "flat")
        prob_up (float — 1.0 pour long, 0.0 pour short, 0.5 pour flat)

    Params :
        signal  : str — valeur du signal (défaut "flat")
        prob_up : float — probabilité associée (défaut 0.5, auto-déduite si omis)
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
