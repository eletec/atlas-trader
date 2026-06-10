"""
v5/nodes/meta_gate.py — MetaGate V5.

Remplace la fusion à poids fixes par LogisticRegression entraînée.
Modèle sauvegardé en pickle, chargé par le DAG live.
Sans modèle → fallback simple (XGB + Trend).
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from v4.core.node import Node

logger = logging.getLogger("v5.nodes.meta_gate")


class MetaGate(Node):
    """Gate appris — charge un modèle pickle, sinon fallback."""

    @property
    def node_type(self) -> str:
        return "MetaGate"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {
            "signal": "str", "prob_up": "float", "trend": "str",
            "debate_signal": "str", "debate_conf": "float",
            "crosstf_signal": "str", "crosstf_conf": "float",
            "regime": "str",
        }

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"signal": "str", "blocked": "bool", "reason": "str", "score": "float"}

    def __init__(self, node_id: str = "", params: dict | None = None, **kwargs):
        super().__init__(node_id=node_id, params=params, **kwargs)
        self._model = None

    def _load_model(self) -> bool:
        path = self.params.get("model_path", "")
        if not path or not Path(path).exists():
            return False
        try:
            self._model = pickle.loads(Path(path).read_bytes())
            logger.info("MetaGate [%s] model loaded: %s", self.node_id, path)
            return True
        except Exception as e:
            logger.warning("MetaGate load failed: %s", e)
            return False

    def _encode(self, inputs: dict) -> list[float]:
        prob_up = float(inputs.get("prob_up", 0.5))
        trend = inputs.get("trend", "")
        db_sig = inputs.get("debate_signal", "")
        db_conf = float(inputs.get("debate_conf", 0.5))
        ct_sig = inputs.get("crosstf_signal", "")
        ct_conf = float(inputs.get("crosstf_conf", 0.5))
        regime = str(inputs.get("regime", ""))
        return [
            prob_up,
            1.0 if trend == "bullish" else 0.0,
            1.0 if trend == "bearish" else 0.0,
            1.0 if db_sig == "bullish" else 0.0,
            1.0 if db_sig == "bearish" else 0.0,
            db_conf,
            1.0 if ct_sig == "long" else 0.0,
            1.0 if ct_sig == "short" else 0.0,
            ct_conf,
            1.0 if regime.upper() == "TREND" else 0.0,
        ]

    def _fallback(self, inputs: dict, threshold: float) -> dict:
        signal = inputs.get("signal", "flat")
        trend = inputs.get("trend", "")
        prob_up = float(inputs.get("prob_up", 0.5))
        score = 0.0
        if signal == "long":
            score += 0.55 * prob_up
        elif signal == "short":
            score -= 0.55 * (1.0 - prob_up)
        if trend == "bullish":
            score += 0.35
        elif trend == "bearish":
            score -= 0.35
        score = max(-1.0, min(1.0, score))
        if score > threshold:
            return {"signal": "long", "blocked": False, "reason": f"fb={score:.2f}", "score": round(score, 4)}
        elif score < -threshold:
            return {"signal": "short", "blocked": False, "reason": f"fb={score:.2f}", "score": round(score, 4)}
        return {"signal": "flat", "blocked": True, "reason": f"fb={score:.2f}", "score": round(score, 4)}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        signal = inputs.get("signal", "flat")
        if signal == "flat":
            return {"signal": "flat", "blocked": False, "reason": "", "score": 0.0}

        threshold = float(self.params.get("threshold", 0.30))

        if self._model is None:
            self._load_model()

        if self._model is not None:
            try:
                X = np.array([self._encode(inputs)], dtype=np.float64)
                proba = self._model.predict_proba(X)[0]
                classes = list(self._model.classes_)
                p_long = proba[classes.index(1)] if 1 in classes else 0.33
                p_short = proba[classes.index(2)] if 2 in classes else 0.33
                score = p_long - p_short
                if score > threshold:
                    return {"signal": "long", "blocked": False, "reason": f"meta={score:.2f}", "score": round(score, 4)}
                elif score < -threshold:
                    return {"signal": "short", "blocked": False, "reason": f"meta={score:.2f}", "score": round(score, 4)}
                else:
                    return {"signal": "flat", "blocked": True, "reason": f"meta={score:.2f}", "score": round(score, 4)}
            except Exception as e:
                logger.warning("MetaGate predict: %s", e)

        return self._fallback(inputs, threshold)
