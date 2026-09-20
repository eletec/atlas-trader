"""
v4/nodes/quant/direction_gate.py — DirectionGate node

Two modes:
  1. VETO (default) — blocks signals contrary to the trend (binary)
  2. FUSION — weighted multi-factor scoring (signal + trend + AI + crosstf + regime)

VETO mode (fusion=False):
  Connected to TrendFilter → blocks SHORT when trend=bullish, LONG when trend=bearish
  Without TrendFilter → forces LONG-only or SHORT-only depending on params

FUSION mode (fusion=True):
  Combine SignalXGB, TrendFilter, DebateNode, CrossTFArb, RegimePassthrough
  into a continuous score [-1, +1]. Decision at the ±threshold.
"""
from __future__ import annotations

from typing import Any

from v4.core.node import Node


class DirectionGate(Node):
    """
    Directional gate.

    Inputs (mode veto) :
        signal    (str — "long" | "short" | "flat")
        trend     (str — optionnel, "bullish" | "bearish" | "neutral")

    Additional inputs (fusion mode):
        prob_up         (float — XGBoost probability of an up move [0,1])
        debate_signal   (str   — debate verdict: "bullish"|"bearish"|"neutral")
        debate_conf     (float — debate confidence [0,1])
        crosstf_signal  (str   — CrossTF signal: "long"|"short"|"flat")
        crosstf_conf    (float — CrossTF confidence [0,1])
        regime          (str   — "TREND" | "CHOP")

    Outputs :
        signal    (str — "long" | "short" | "flat")
        blocked   (bool — True when the signal was blocked)
        reason    (str — reason for the block or score)
        score     (float — fusion score [-1, 1], 0 in veto mode)

    Params (mode veto) :
        allow_long   : bool
        allow_short  : bool
        invert_trend : bool

    Params (mode fusion) :
        fusion      : bool — enables the weighted scoring (default False)
        w_xgb       : float — XGBoost weight (default 0.50)
        w_trend     : float — TrendFilter weight (default 0.25)
        w_debate    : float — AI Debate weight (default 0.10)
        w_crosstf   : float — CrossTF microstructure weight (default 0.10)
        w_regime    : float — Regime weight (default 0.05)
        threshold   : float — decision threshold (default 0.30)
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
        # FUSION MODE - weighted multi-factor scoring
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

            # -- AI debate (10%) - read from the async cache (no edge, it is cyclical) --
            debate_signal = inputs.get("debate_signal", "")
            debate_conf = float(inputs.get("debate_conf", 0.0))
            # When not connected, try to read the async cache directly
            if not debate_signal:
                try:
                    from v4.core.async_tasks import get_result
                    dag_id = self.params.get("dag_id", "")
                    # Derive the debate node_id from the {pfx}_debate convention
                    debate_node = self.node_id.replace("_gate", "_debate") if self.node_id.endswith("_gate") else ""
                    if debate_node:
                        cache_key = f"debate_{dag_id}_{debate_node}"
                        cached = get_result(cache_key)
                        if cached and "error" not in cached:
                            debate_signal = cached.get("decision", "")
                            debate_conf = float(cached.get("confidence", 0.5))
                except Exception:
                    pass
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

            # ── Regime (5%) + Adaptation ──
            regime = inputs.get("regime", "")
            if isinstance(regime, str):
                r = regime.upper()
                if r == "TREND":
                    score += w_regime * 0.5
                elif r == "CHOP":
                    # CHOP = do not trade (block all new trades)
                    return {"signal": "flat", "blocked": True,
                            "reason": f"regime=CHOP (no new trades)", "score": 0.0}

            # ── Regime-aware threshold adaptation ──
            _threshold = threshold
            if isinstance(regime, str) and regime.upper() == "RANGE":
                _threshold = threshold + 0.10  # more selective in a range

            score = max(-1.0, min(1.0, score))

            if score > _threshold:
                return {"signal": "long", "blocked": False,
                        "reason": f"fusion={score:.2f}", "score": round(score, 4)}
            elif score < -_threshold:
                return {"signal": "short", "blocked": False,
                        "reason": f"fusion={score:.2f}", "score": round(score, 4)}
            else:
                return {"signal": "flat", "blocked": True,
                        "reason": f"fusion={score:.2f} < ±{_threshold}", "score": round(score, 4)}

        # ═══════════════════════════════════════════════════════════════
        # VETO MODE - existing behaviour (unchanged)
        # ═══════════════════════════════════════════════════════════════
        allow_long   = bool(self.params.get("allow_long", True))
        allow_short  = bool(self.params.get("allow_short", True))
        invert_trend = bool(self.params.get("invert_trend", False))

        # -- Mode 1: trend connected (takes priority) --
        if trend:
            if invert_trend:
                # Bearish market: only SHORT is allowed when trend=bearish
                if trend == "bearish" and signal == "long":
                    return {"signal": "flat", "blocked": True, "score": 0.0,
                            "reason": f"trend_veto: trend={trend}, signal={signal} blocked (invert)"}
                if trend == "bullish" and signal == "short":
                    return {"signal": "flat", "blocked": True, "score": 0.0,
                            "reason": f"trend_veto: trend={trend}, signal={signal} blocked (invert)"}
            else:
                # Standard mode: block a signal that goes against the trend
                if trend == "bullish" and signal == "short":
                    return {"signal": "flat", "blocked": True, "score": 0.0,
                            "reason": f"trend_veto: 4h bullish -> SHORT blocked"}
                if trend == "bearish" and signal == "long":
                    return {"signal": "flat", "blocked": True, "score": 0.0,
                            "reason": f"trend_veto: 4h bearish -> LONG blocked"}

            return {"signal": signal, "blocked": False, "reason": "", "score": 0.0}

        # ── Mode 2: params allow_* (no trend) ────────────────────────────
        if signal == "long" and not allow_long:
            return {"signal": "flat", "blocked": True, "score": 0.0,
                    "reason": "direction_gate: LONG disabled (allow_long=False)"}
        if signal == "short" and not allow_short:
            return {"signal": "flat", "blocked": True, "score": 0.0,
                    "reason": "direction_gate: SHORT disabled (allow_short=False)"}

        return {"signal": signal, "blocked": False, "reason": "", "score": 0.0}
