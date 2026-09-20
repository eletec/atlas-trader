"""
v4/nodes/quant/signal_xgb.py — Nœud SignalXGB (XGBoost).

Remplace SignalLogReg avec un classifier XGBoost + feature engineering avancé.
Walk-forward : réentraînement périodique sur les données récentes.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from v4.core.node import Node

logger = logging.getLogger("v4.nodes.quant.signal_xgb")


class SignalXGB(Node):
    """
    Signal directionnel basé sur XGBoost classifier.

    Inputs :
        features_all  (DataFrame) — features normalisées
        regime        (str)       — régime de marché (optionnel)

    Outputs :
        signal        (str)  — "long" | "short" | "flat"
        prob_up       (float) — probabilité hausse [0, 1]
        prob_dn       (float) — probabilité baisse [0, 1]
        confidence    (float) — confiance du signal [0, 1]

    Params (priorité: DAG > settings.yaml) :
        p_up_threshold   : float — seuil proba LONG (défaut 0.55)
        p_dn_threshold   : float — seuil proba SHORT (défaut 0.45)
        train_fraction   : float — fraction entraînement (défaut 0.70)
        horizon_bars     : int   — horizon de prédiction (défaut 48)
        retrain_cycle    : int   — cycles entre réentraînements (défaut 120 = 10h)
        max_depth        : int   — profondeur max XGBoost (défaut 5)
        n_estimators     : int   — nombre d'arbres (défaut 100)
        lag_features     : int   — nombre de lags à ajouter (défaut 3)
    """

    _model: Any = None
    _last_train_bar: int = 0
    _cycle_count: int = 0

    @property
    def node_type(self) -> str:
        return "SignalXGB"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"features_all": "DataFrame", "regime": "str"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"signal": "str", "prob_up": "float", "prob_dn": "float", "confidence": "float"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._run_impl(inputs)
        except Exception as exc:
            logger.error("SignalXGB failed: %s", exc)
            return {"signal": "flat", "prob_up": 0.5, "prob_dn": 0.5, "confidence": 0.0}

    def _run_impl(self, inputs: dict[str, Any]) -> dict[str, Any]:
        features_all: pd.DataFrame = inputs["features_all"]
        regime: str = inputs.get("regime", "TREND")

        from v4.nodes.config_loader import load_v4_config

        symbol = self.params.get("symbol", "")
        _cfg = load_v4_config(symbol, "signal", {
            "calibrate": True, "train_fraction": 0.70, "horizon_bars": 48,
            "p_up_threshold": 0.55, "p_dn_threshold": 0.45,
        })

        p_up_thresh = float(self.params.get("p_up_threshold", _cfg.get("p_up_threshold", 0.55)))
        p_dn_thresh = float(self.params.get("p_dn_threshold", _cfg.get("p_dn_threshold", 0.45)))
        train_fraction = float(self.params.get("train_fraction", _cfg.get("train_fraction", 0.70)))
        horizon_bars = int(self.params.get("horizon_bars", _cfg.get("horizon_bars", 48)))
        retrain_cycle = int(self.params.get("retrain_cycle", 120))
        max_depth = int(self.params.get("max_depth", 5))
        n_estimators = int(self.params.get("n_estimators", 100))
        n_lags = int(self.params.get("lag_features", 3))

        if features_all is None or len(features_all) < 100:
            return {"signal": "flat", "prob_up": 0.5, "prob_dn": 0.5, "confidence": 0.0}

        # ── Feature engineering ──
        df = features_all.copy()

        # Add the lags
        for lag in range(1, n_lags + 1):
            for col in df.columns:
                if col not in ("close", "regime"):
                    df[f"{col}_lag{lag}"] = df[col].shift(lag)

        # Numeric columns only
        df = df.select_dtypes(include=[np.number])
        df = df.dropna()

        if len(df) < 100:
            return {"signal": "flat", "prob_up": 0.5, "prob_dn": 0.5, "confidence": 0.0}

        # -- Retraining --
        self._cycle_count += 1
        need_retrain = (self._model is None or
                        self._cycle_count % retrain_cycle == 0 or
                        len(df) > self._last_train_bar + retrain_cycle * 2)

        if need_retrain:
            try:
                import xgboost as xgb

                split = int(len(df) * train_fraction)
                train_df = df.iloc[:split]
                if len(train_df) < 50:
                    return {"signal": "flat", "prob_up": 0.5, "prob_dn": 0.5, "confidence": 0.0}

                # Cible : direction future
                close_col = "close" if "close" in df.columns else df.columns[0]
                future_close = df[close_col].shift(-horizon_bars)
                target = (future_close > df[close_col]).astype(int)

                train_target = target.iloc[:split].dropna()
                train_features = train_df.iloc[:len(train_target)]

                if len(train_target) < 50:
                    return {"signal": "flat", "prob_up": 0.5, "prob_dn": 0.5, "confidence": 0.0}

                self._model = xgb.XGBClassifier(
                    n_estimators=n_estimators,
                    max_depth=max_depth,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    objective="binary:logistic",
                    eval_metric="logloss",
                    random_state=42,
                    verbosity=0,
                )
                self._model.fit(train_features.values, train_target.values)
                self._last_train_bar = len(df)
                logger.info(
                    "SignalXGB trained on %d samples, %d features, accuracy=%.3f",
                    len(train_target), len(train_features.columns),
                    self._model.score(train_features.values, train_target.values),
                )
            except Exception as e:
                logger.warning("SignalXGB training failed: %s", e)
                if self._model is None:
                    return {"signal": "flat", "prob_up": 0.5, "prob_dn": 0.5, "confidence": 0.0}

        # -- Prediction --
        if self._model is None:
            return {"signal": "flat", "prob_up": 0.5, "prob_dn": 0.5, "confidence": 0.0}

        last_row = df.iloc[-1:].select_dtypes(include=[np.number])
        # Align the columns with the training set
        expected_features = self._model.get_booster().feature_names
        if expected_features:
            for f in expected_features:
                if f not in last_row.columns:
                    last_row[f] = 0.0
            last_row = last_row[expected_features]

        proba = self._model.predict_proba(last_row.values)[0]
        prob_up = float(proba[1]) if len(proba) > 1 else float(proba[0])
        prob_dn = 1.0 - prob_up
        confidence = abs(prob_up - 0.5) * 2.0  # 0 = uncertain, 1 = very confident

        if prob_up >= p_up_thresh:
            signal = "long"
        elif prob_up <= p_dn_thresh:
            signal = "short"
        else:
            signal = "flat"

        return {
            "signal": signal,
            "prob_up": round(prob_up, 4),
            "prob_dn": round(prob_dn, 4),
            "confidence": round(confidence, 4),
        }
