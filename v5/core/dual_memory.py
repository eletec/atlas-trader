"""
v5/core/dual_memory.py — Dual-Memory Learning System V5.

Anchor model (stable, 6-12 mois) + Online adapter (récent, adaptatif).
Avec PSI drift detection et ratio dynamique.

Usage :
    from v5.core.dual_memory import DualMemoryModel

    dm = DualMemoryModel(anchor_model_path="models/btc_anchor.pkl")
    score = dm.predict(features)       # ∈ [-1, +1]
    dm.update(features, outcome)       # met à jour l'adapter si pas de drift
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path

import numpy as np

logger = logging.getLogger("v5.core.dual_memory")


class DualMemoryModel:
    """
    Combine un modèle anchor (stable, ré-entraîné périodiquement)
    avec un adapter online léger (recursive least squares).
    """

    def __init__(
        self,
        anchor_model_path: str = "",
        adapter_lr: float = 0.01,
        adapter_reg: float = 1.0,
        anchor_weight: float = 0.70,
        drift_threshold: float = 0.15,
        buffer_size: int = 1000,
    ):
        # Anchor
        self._anchor = None
        self._anchor_weight = anchor_weight
        if anchor_model_path and Path(anchor_model_path).exists():
            try:
                self._anchor = pickle.loads(Path(anchor_model_path).read_bytes())
                logger.info("Anchor model loaded: %s", anchor_model_path)
            except Exception as e:
                logger.warning("Anchor load failed: %s", e)

        # Adapter (recursive least squares / FTRL)
        self._adapter_w = None  # weights, updated online
        self._adapter_lr = adapter_lr
        self._adapter_reg = adapter_reg
        self._adapter_n = 0

        # Drift detection
        self._drift_threshold = drift_threshold
        self._buffer: list[dict] = []  # {features, prediction}
        self._buffer_size = buffer_size

        # Statistics for PSI
        self._pred_history: list[float] = []

    @property
    def ready(self) -> bool:
        return self._anchor is not None or self._adapter_w is not None

    def predict(self, features: list[float]) -> float:
        """Score ∈ [-1, +1] combinant anchor + adapter."""
        if not self.ready:
            return 0.0

        x = np.array(features, dtype=np.float64)

        score = 0.0
        total_w = 0.0

        # Anchor prediction
        if self._anchor is not None and hasattr(self._anchor, "predict_proba"):
            try:
                proba = self._anchor.predict_proba(x.reshape(1, -1))[0]
                classes = list(self._anchor.classes_)
                p_long = proba[classes.index(1)] if 1 in classes else 0.33
                p_short = proba[classes.index(2)] if 2 in classes else 0.33
                anchor_score = p_long - p_short
                # Dynamic anchor weight based on drift
                drift = self._compute_drift()
                aw = max(0.50, self._anchor_weight - drift * self._anchor_weight)
                score += aw * anchor_score
                total_w += aw
            except Exception:
                pass

        # Adapter prediction
        if self._adapter_w is not None:
            try:
                adapter_score = float(np.dot(x, self._adapter_w))
                adapter_score = max(-1.0, min(1.0, adapter_score))
                aw = 1.0 - self._anchor_weight if self._anchor is not None else 1.0
                score += aw * adapter_score
                total_w += aw
            except Exception:
                pass

        if total_w > 0:
            score /= total_w

        self._pred_history.append(float(score))
        return float(score)

    def update(self, features: list[float], outcome: float):
        """
        Met à jour l'adapter avec un nouveau (features, outcome).
        outcome ∈ [-1, +1] : +1 = long gagnant, -1 = short gagnant, 0 = perdant.
        """
        x = np.array(features, dtype=np.float64).reshape(-1)
        y = float(outcome)

        # ── Drift gate : ne pas updater si distribution shift ──
        if self._compute_drift() > self._drift_threshold:
            logger.debug("DualMemory: drift %.3f > %.3f, skipping update",
                         self._compute_drift(), self._drift_threshold)
            return

        # ── Online update (recursive ridge / FTRL) ──
        if self._adapter_w is None:
            self._adapter_w = np.zeros_like(x)

        # Recursive Least Squares avec régularisation
        self._adapter_n += 1
        reg = self._adapter_reg / max(self._adapter_n, 1)
        error = y - float(np.dot(x, self._adapter_w))
        # Weighted update: plus le modèle est vieux, moins il apprend vite
        lr = self._adapter_lr / (1.0 + 0.001 * self._adapter_n)
        self._adapter_w += lr * (error * x - reg * self._adapter_w)

        # Buffer management
        self._buffer.append({"features": features, "prediction": float(np.dot(x, self._adapter_w))})
        if len(self._buffer) > self._buffer_size:
            self._buffer = self._buffer[-self._buffer_size:]

    def _compute_drift(self) -> float:
        """Population Stability Index (PSI) proxy sur les prédictions récentes."""
        if len(self._pred_history) < 50:
            return 0.0
        recent = self._pred_history[-50:]
        older = self._pred_history[-100:-50] if len(self._pred_history) >= 100 else recent
        if not older:
            return 0.0

        # PSI simplifié : distribution shift en bins
        bins = 10
        hist_recent, _ = np.histogram(recent, bins=bins, range=(-1, 1))
        hist_older, _ = np.histogram(older, bins=bins, range=(-1, 1))
        # Add small epsilon to avoid division by zero
        hist_recent = hist_recent.astype(np.float64) + 0.0001
        hist_older = hist_older.astype(np.float64) + 0.0001
        hist_recent /= hist_recent.sum()
        hist_older /= hist_older.sum()
        psi = np.sum((hist_recent - hist_older) * np.log(hist_recent / hist_older))
        return float(abs(psi))

    def get_anchor_weight(self) -> float:
        """Poids dynamique de l'anchor basé sur le drift actuel."""
        drift = self._compute_drift()
        return max(0.50, self._anchor_weight - drift * self._anchor_weight)

    def save_adapter(self, path: str) -> None:
        """Sauvegarde l'adapter pour usage futur."""
        data = {
            "w": self._adapter_w.tolist() if self._adapter_w is not None else [],
            "n": self._adapter_n,
        }
        Path(path).write_bytes(pickle.dumps(data))
