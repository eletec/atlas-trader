"""
quant/signal_model.py — Modèle de signal : Logistic Regression + Platt calibration.

Critique IA convergente : l'isotonic regression sur peu de données overfit.
Solution : LogisticRegression + CalibratedClassifierCV(method='sigmoid') = Platt.

Sortie : probabilité calibrée P(up) ∈ [0, 1] sur l'horizon ciblé.

Fallback : si sklearn indisponible, modèle linéaire maison + sigmoid (sans calibration).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger("zeitgeist.quant.signal_model")

try:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn unavailable — fallback to built-in logistic regression without calibration.")


@dataclass
class SignalModel:
    """Prédit P(up) à un horizon fixe à partir de features normalisées."""

    feature_cols: Sequence[str]
    use_calibration: bool = True
    use_lgb: bool = False   # E.1 : LightGBM optionnel — désactivé par défaut (GPT)
    C: float = 1.0
    cv_folds: int = 5
    _model: object | None = field(default=None, init=False, repr=False)
    _fallback_weights: np.ndarray | None = field(default=None, init=False, repr=False)
    _fallback_bias: float = field(default=0.0, init=False, repr=False)
    _fallback_mean: np.ndarray | None = field(default=None, init=False, repr=False)
    _fallback_std: np.ndarray | None = field(default=None, init=False, repr=False)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "SignalModel":
        """Entraîne sur (X, y). y ∈ {0, 1}, NaN exclus avant appel idéalement."""
        mask = X[self.feature_cols].notna().all(axis=1) & y.notna()
        Xv = X.loc[mask, list(self.feature_cols)].values
        yv = y.loc[mask].astype(int).values

        if len(yv) < 50:
            raise ValueError(f"Données insuffisantes pour fit ({len(yv)} < 50).")
        if len(np.unique(yv)) < 2:
            raise ValueError("Cible avec une seule classe — modèle dégénéré.")

        if SKLEARN_AVAILABLE:
            # E.1 LightGBM optionnel (flag use_lgb=True) — conservateur, validation OOS requise
            # GPT : risque d'overfitting silencieux sur 18k samples. Comparer en walk-forward.
            if self.use_lgb:
                try:
                    from lightgbm import LGBMClassifier
                    base = Pipeline([
                        ("lgb", LGBMClassifier(
                            n_estimators=100, max_depth=3, learning_rate=0.03,
                            num_leaves=8, min_data_in_leaf=500,
                            feature_fraction=0.5, lambda_l2=10.0,
                            verbose=-1, random_state=42,
                        )),
                    ])
                    logger.info("SignalModel : LightGBM activé (use_lgb=True)")
                except ImportError:
                    logger.warning("lightgbm non disponible — fallback LogReg")
                    self.use_lgb = False
            if not self.use_lgb:
                base = Pipeline(
                    [
                        ("scaler", StandardScaler()),
                        ("lr", LogisticRegression(C=self.C, max_iter=500, solver="liblinear")),
                    ]
                )
            if self.use_calibration:
                # TimeSeriesSplit : évite le leakage KFold sur séries temporelles (GPT)
                tscv = TimeSeriesSplit(n_splits=min(self.cv_folds, 5))
                self._model = CalibratedClassifierCV(
                    base, method="sigmoid", cv=tscv
                )
            else:
                self._model = base
            self._model.fit(Xv, yv)
            logger.info(f"SignalModel sklearn fit OK on {len(yv)} samples.")
        else:
            self._fit_fallback(Xv, yv)
            logger.info(f"SignalModel fallback fit OK on {len(yv)} samples.")
        return self

    def _fit_fallback(self, X: np.ndarray, y: np.ndarray) -> None:
        # Gradient descent simple sur log-loss avec L2
        self._fallback_mean = X.mean(axis=0)
        self._fallback_std = X.std(axis=0) + 1e-9
        Xs = (X - self._fallback_mean) / self._fallback_std

        n, d = Xs.shape
        w = np.zeros(d)
        b = 0.0
        lr = 0.05
        l2 = 1.0 / max(self.C, 1e-6)
        for _ in range(2000):
            z = Xs @ w + b
            p = 1.0 / (1.0 + np.exp(-z))
            grad_w = Xs.T @ (p - y) / n + l2 * w / n
            grad_b = float((p - y).mean())
            w -= lr * grad_w
            b -= lr * grad_b
        self._fallback_weights = w
        self._fallback_bias = b

    def predict_proba(self, X: pd.DataFrame) -> pd.Series:
        """Retourne P(up) ∈ [0, 1] indexé comme X."""
        mask = X[list(self.feature_cols)].notna().all(axis=1)
        Xv = X.loc[mask, list(self.feature_cols)].values
        out = pd.Series(index=X.index, dtype="float64")
        if len(Xv) == 0:
            return out
        if SKLEARN_AVAILABLE and self._model is not None:
            proba = self._model.predict_proba(Xv)[:, 1]
        elif self._fallback_weights is not None:
            Xs = (Xv - self._fallback_mean) / self._fallback_std
            z = Xs @ self._fallback_weights + self._fallback_bias
            proba = 1.0 / (1.0 + np.exp(-z))
        else:
            raise RuntimeError("Modèle non entraîné.")
        out.loc[mask] = proba
        return out
