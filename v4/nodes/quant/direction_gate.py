"""
v4/nodes/quant/direction_gate.py — Nœud DirectionGate

Deux modes :
  1. VETO (défaut) — bloque les signaux contraires à la tendance (binaire)
  2. FUSION — scoring pondéré multi-facteurs (signal + trend + IA + crosstf + regime)

Mode VETO (fusion=False) :
  Connecté à TrendFilter → bloque SHORT si trend=bullish, LONG si trend=bearish
  Sans TrendFilter → force LONG-only ou SHORT-only selon params

Mode FUSION (fusion=True) :
  Combine SignalXGB, TrendFilter, DebateNode, CrossTFArb, RegimePassthrough
  en un score continu [-1, +1]. Décision au seuil ±threshold.
"""
from __future__ import annotations

from typing import Any

from v4.core.node import Node


class DirectionGate(Node):
    """
    Gate directionnel.

    Inputs (mode veto) :
        signal    (str — "long" | "short" | "flat")
        trend     (str — optionnel, "bullish" | "bearish" | "neutral")

    Inputs additionnels (mode fusion) :
        prob_up         (float — probabilité hausse XGBoost [0,1])
        debate_signal   (str   — verdict du débat : "bullish"|"bearish"|"neutral")
        debate_conf     (float — confiance du débat [0,1])
        crosstf_signal  (str   — signal CrossTF : "long"|"short"|"flat")
        crosstf_conf    (float — confiance CrossTF [0,1])
        regime          (str   — "TREND" | "CHOP")

    Outputs :
        signal    (str — "long" | "short" | "flat")
        blocked   (bool — True si le signal a été bloqué)
        reason    (str — raison du blocage ou score)
        score     (float — score fusion [-1, 1], 0 en mode veto)

    Params (mode veto) :
        allow_long   : bool
        allow_short  : bool
        invert_trend : bool

    Params (mode fusion) :
        fusion      : bool — active le scoring pondéré (défaut False)
        w_xgb       : float — poids XGBoost (défaut 0.50)
        w_trend     : float — poids TrendFilter (défaut 0.25)
        w_debate    : float — poids IA Débat (défaut 0.10)
        w_crosstf   : float — poids CrossTF microstructure (défaut 0.10)
        w_regime    : float — poids Régime (défaut 0.05)
        threshold   : float — seuil de décision (défaut 0.30)
    """

    @property
    def node_type(self) -> str:
        return "DirectionGate"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {
            "signal": "str", "trend": "str",
            "prob_up": "float",
            "debate_signal": "str", "debate_conf": "float",
            "crosstf_signal": "str", "crosstf_conf": "float",
            "regime": "str",
        }

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"signal": "str", "blocked": "bool", "reason": "str", "score": "float"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        signal: str = inputs.get("signal", "flat")
        trend: str  = inputs.get("trend", "")

        if signal == "flat":
            return {"signal": "flat", "blocked": False, "reason": "", "score": 0.0}

        # ═══════════════════════════════════════════════════════════════
        # MODE FUSION — scoring pondéré multi-facteurs
        # ═══════════════════════════════════════════════════════════════
        if bool(self.params.get("fusion", False)):
            w_xgb     = float(self.params.get("w_xgb", 0.50))
            w_trend   = float(self.params.get("w_trend", 0.25))
            w_debate  = float(self.params.get("w_debate", 0.10))
            w_crosstf = float(self.params.get("w_crosstf", 0.10))
            w_regime  = float(self.params.get("w_regime", 0.05))
            threshold = float(self.params.get("threshold", 0.30))

            score = 0.0

            # ── XGBoost (50%) ──
            prob_up = float(inputs.get("prob_up", 0.5))
            if signal == "long":
                score += w_xgb * prob_up
            elif signal == "short":
                score -= w_xgb * (1.0 - prob_up)

            # ── TrendFilter (25%) ──
            if trend == "bullish":
                score += w_trend
            elif trend == "bearish":
                score -= w_trend

            # ── Débat IA (10%) — depuis cache async ──
            debate_signal = inputs.get("debate_signal", "")
            debate_conf = float(inputs.get("debate_conf", 0.5))
            if debate_signal == "bullish":
                score += w_debate * debate_conf
            elif debate_signal == "bearish":
                score -= w_debate * debate_conf

            # ── CrossTF microstructure (10%) ──
            crosstf_signal = inputs.get("crosstf_signal", "")
            crosstf_conf = float(inputs.get("crosstf_conf", 0.5))
            if crosstf_signal == "long":
                score += w_crosstf * crosstf_conf
            elif crosstf_signal == "short":
                score -= w_crosstf * crosstf_conf

            # ── Regime (5%) ──
            regime = inputs.get("regime", "")
            if isinstance(regime, str) and regime.upper() == "TREND":
                score += w_regime * 0.5

            score = max(-1.0, min(1.0, score))

            if score > threshold:
                return {"signal": "long", "blocked": False,
                        "reason": f"fusion={score:.2f}", "score": round(score, 4)}
            elif score < -threshold:
                return {"signal": "short", "blocked": False,
                        "reason": f"fusion={score:.2f}", "score": round(score, 4)}
            else:
                return {"signal": "flat", "blocked": True,
                        "reason": f"fusion={score:.2f} < ±{threshold}", "score": round(score, 4)}

        # ═══════════════════════════════════════════════════════════════
        # MODE VETO — comportement existant (inchangé)
        # ═══════════════════════════════════════════════════════════════
        allow_long   = bool(self.params.get("allow_long", True))
        allow_short  = bool(self.params.get("allow_short", True))
        invert_trend = bool(self.params.get("invert_trend", False))

        # ── Mode 1 : trend connecté (prioritaire) ─────────────────────────
        if trend:
            if invert_trend:
                # Marché baissier : seul SHORT est autorisé si trend=bearish
                if trend == "bearish" and signal == "long":
                    return {"signal": "flat", "blocked": True, "score": 0.0,
                            "reason": f"trend_veto: trend={trend}, signal={signal} blocked (invert)"}
                if trend == "bullish" and signal == "short":
                    return {"signal": "flat", "blocked": True, "score": 0.0,
                            "reason": f"trend_veto: trend={trend}, signal={signal} blocked (invert)"}
            else:
                # Mode standard : bloquer signal contraire à la tendance
                if trend == "bullish" and signal == "short":
                    return {"signal": "flat", "blocked": True, "score": 0.0,
                            "reason": f"trend_veto: 4h bullish → SHORT bloqué"}
                if trend == "bearish" and signal == "long":
                    return {"signal": "flat", "blocked": True, "score": 0.0,
                            "reason": f"trend_veto: 4h bearish → LONG bloqué"}

            return {"signal": signal, "blocked": False, "reason": "", "score": 0.0}

        # ── Mode 2 : params allow_* (pas de trend) ────────────────────────
        if signal == "long" and not allow_long:
            return {"signal": "flat", "blocked": True, "score": 0.0,
                    "reason": "direction_gate: LONG désactivé (allow_long=False)"}
        if signal == "short" and not allow_short:
            return {"signal": "flat", "blocked": True, "score": 0.0,
                    "reason": "direction_gate: SHORT désactivé (allow_short=False)"}

        return {"signal": signal, "blocked": False, "reason": "", "score": 0.0}
