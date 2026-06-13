"""
v5/nodes/meta_gate.py — MetaGate V5.

Remplace la fusion à poids fixes par LogisticRegression entraînée.
Modèle sauvegardé en pickle, chargé par le DAG live.
Sans modèle → fallback simple (XGB + Trend).
Support DualMemory (anchor + adapter online) si use_dual_memory=True.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from v4.core.node import Node
from v5.core.dual_memory import DualMemoryModel

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
        return {"signal": "str", "blocked": "bool", "reason": "str", "score": "float",
                "regime_adapted": "bool", "size_multiplier": "float"}

    def __init__(self, node_id: str = "", params: dict | None = None, **kwargs):
        super().__init__(node_id=node_id, params=params, **kwargs)
        self._model = None
        self._dual_memory: DualMemoryModel | None = None
        self._use_dual = bool(self.params.get("use_dual_memory", True))
        self._regime_adapter = None  # V6: lazy init

    def _load_dual_memory(self) -> bool:
        """Charge ou crée le DualMemory (anchor + adapter online)."""
        if self._dual_memory is not None:
            return True
        try:
            anchor_path = self.params.get("anchor_model_path",
                           self.params.get("model_path", "").replace("meta_", "anchor_"))
            self._dual_memory = DualMemoryModel(
                anchor_model_path=anchor_path,
                adapter_lr=float(self.params.get("adapter_lr", 0.01)),
                adapter_reg=float(self.params.get("adapter_reg", 1.0)),
                anchor_weight=float(self.params.get("anchor_weight", 0.70)),
                drift_threshold=float(self.params.get("drift_threshold", 0.15)),
            )
            logger.info("MetaGate [%s] DualMemory ready (anchor=%s)",
                        self.node_id, self._dual_memory.ready)
            return True
        except Exception as e:
            logger.warning("MetaGate DualMemory init failed: %s", e)
            return False

    def _load_model(self) -> bool:
        path = self.params.get("model_path", "")
        if not path:
            logger.warning("MetaGate [%s] no model_path in params", self.node_id)
            return False
        if not Path(path).exists():
            logger.warning("MetaGate [%s] model not found: %s", self.node_id, path)
            return False
        try:
            self._model = pickle.loads(Path(path).read_bytes())
            logger.info("MetaGate [%s] model loaded: %s", self.node_id, path)
            return True
        except Exception as e:
            logger.warning("MetaGate [%s] load failed: %s", self.node_id, e)
            return False

    def _encode(self, inputs: dict) -> list[float]:
        prob_up = float(inputs.get("prob_up", 0.5))
        trend = inputs.get("trend", "")
        regime = str(inputs.get("regime", ""))
        # 6 features alignées avec train_meta_gate.py:
        # [prob_up, trend_bull, trend_bear, regime_TREND, regime_RANGE, regime_CHOP]
        return [
            prob_up,
            1.0 if trend == "bullish" else 0.0,
            1.0 if trend == "bearish" else 0.0,
            1.0 if regime.upper() == "TREND" else 0.0,
            1.0 if regime.upper() == "RANGE" else 0.0,
            1.0 if regime.upper() == "CHOP" else 0.0,
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
        regime = str(inputs.get("regime", "TREND"))
        threshold = float(self.params.get("threshold", 0.20))
        
        if signal == "flat":
            return {"signal": "flat", "blocked": False, "reason": "", "score": 0.0,
                    "regime_adapted": False, "size_multiplier": 1.0}

        # ── V5: DualMemory prioritaire ──
        score = None
        result = None
        
        if self._use_dual:
            if self._dual_memory is None:
                self._load_dual_memory()
            if self._dual_memory is not None and self._dual_memory.ready:
                try:
                    features = self._encode(inputs)
                    score = self._dual_memory.predict(features)
                except Exception as e:
                    logger.warning("MetaGate DualMemory predict: %s", e)

        # ── Fallback: pickle model ──
        if score is None:
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
                except Exception as e:
                    logger.warning("MetaGate predict: %s", e)

        # ── Fallback ultime ──
        if score is None:
            return self._fallback(inputs, threshold)

        # ── V6: RegimeAdapter — adapte le seuil et le sizing au régime ──
        regime_adapted = False
        size_mult = 1.0
        
        try:
            from v6.core.regime_adapter import RegimeAdapter
            if self._regime_adapter is None:
                self._regime_adapter = RegimeAdapter()
            self._regime_adapter.current_regime = regime
            
            if self._regime_adapter.should_block_entries():
                logger.info("MetaGate [%s]: régime=%s → BLOCKED (no entries)", self.node_id, regime)
                return {"signal": "flat", "blocked": True, 
                        "reason": f"regime={regime} (no new trades)", "score": round(score, 4),
                        "regime_adapted": True, "size_multiplier": 0.0}
            
            # Adapter le seuil au régime
            adapted = self._regime_adapter.adapt_params({"threshold": threshold})
            threshold = adapted["meta_threshold"]
            size_mult = adapted["size_multiplier"]
            
            if size_mult != 1.0 or threshold != float(self.params.get("threshold", 0.20)):
                regime_adapted = True
                logger.info("MetaGate [%s]: régime=%s → th=%.2f size=%.0f%%", 
                           self.node_id, regime, threshold, size_mult * 100)
        except ImportError:
            pass  # V6 non disponible, comportement V5 standard
        
        # ── Décision finale ──
        prefix = "dm" if self._use_dual and self._dual_memory and self._dual_memory.ready else "meta"
        if score > threshold:
            return {"signal": "long", "blocked": False,
                    "reason": f"{prefix}={score:.2f}", "score": round(score, 4),
                    "regime_adapted": regime_adapted, "size_multiplier": size_mult}
        elif score < -threshold:
            return {"signal": "short", "blocked": False,
                    "reason": f"{prefix}={score:.2f}", "score": round(score, 4),
                    "regime_adapted": regime_adapted, "size_multiplier": size_mult}
        return {"signal": "flat", "blocked": True,
                "reason": f"{prefix}={score:.2f}", "score": round(score, 4),
                "regime_adapted": regime_adapted, "size_multiplier": size_mult}
