"""
v4/nodes/quant/direction_gate.py — Nœud DirectionGate

Filtre directionnel configurable : bloque les signaux contraires à la
tendance de fond (ou à une direction autorisée explicite).

Utilisable de deux façons :
  1. Connecté à un TrendFilter → bloque SHORT si trend=bullish,
     bloque LONG si trend=bearish (mode auto, params allow_long/allow_short ignorés)
  2. Sans TrendFilter → force LONG-only (allow_long=True) ou SHORT-only
     (allow_short=True) selon les params.

Invariant V4 : n'altère jamais le signal d'entrée, ne fait que le bloquer
              en le remplaçant par "flat" si interdit.
"""
from __future__ import annotations

from typing import Any

from v4.core.node import Node


class DirectionGate(Node):
    """
    Gate directionnel — bloque les signaux contraires.
    Priorité : trend input > params allow_*.

    Inputs  :
        signal    (str — "long" | "short" | "flat")
        trend     (str — optionnel, "bullish" | "bearish" | "neutral")

    Outputs :
        signal    (str — "long" | "short" | "flat")
        blocked   (bool — True si le signal a été bloqué)
        reason    (str — raison du blocage si blocked)

    Params :
        allow_long   : bool — autorise les LONG (défaut True)
        allow_short  : bool — autorise les SHORT (défaut True)
        invert_trend : bool — inverse la logique trend (bearish → autorise SHORT
                              seulement) pour les marchés baissiers (défaut False)
    """

    @property
    def node_type(self) -> str:
        return "DirectionGate"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"signal": "str", "trend": "str"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"signal": "str", "blocked": "bool", "reason": "str"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        signal: str = inputs.get("signal", "flat")
        trend: str  = inputs.get("trend", "")

        allow_long   = bool(self.params.get("allow_long", True))
        allow_short  = bool(self.params.get("allow_short", True))
        invert_trend = bool(self.params.get("invert_trend", False))

        if signal == "flat":
            return {"signal": "flat", "blocked": False, "reason": ""}

        # ── Mode 1 : trend connecté (prioritaire) ─────────────────────────
        if trend:
            if invert_trend:
                # Marché baissier : seul SHORT est autorisé si trend=bearish
                if trend == "bearish" and signal == "long":
                    return {"signal": "flat", "blocked": True,
                            "reason": f"trend_veto: trend={trend}, signal={signal} blocked (invert)"}
                if trend == "bullish" and signal == "short":
                    return {"signal": "flat", "blocked": True,
                            "reason": f"trend_veto: trend={trend}, signal={signal} blocked (invert)"}
            else:
                # Mode standard : bloquer signal contraire à la tendance
                if trend == "bullish" and signal == "short":
                    return {"signal": "flat", "blocked": True,
                            "reason": f"trend_veto: 4h bullish → SHORT bloqué"}
                if trend == "bearish" and signal == "long":
                    return {"signal": "flat", "blocked": True,
                            "reason": f"trend_veto: 4h bearish → LONG bloqué"}

            return {"signal": signal, "blocked": False, "reason": ""}

        # ── Mode 2 : params allow_* (pas de trend) ────────────────────────
        if signal == "long" and not allow_long:
            return {"signal": "flat", "blocked": True,
                    "reason": "direction_gate: LONG désactivé (allow_long=False)"}
        if signal == "short" and not allow_short:
            return {"signal": "flat", "blocked": True,
                    "reason": "direction_gate: SHORT désactivé (allow_short=False)"}

        return {"signal": signal, "blocked": False, "reason": ""}
