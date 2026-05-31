"""
quant/signal_model_v3.py — Mixture-of-Experts par régime HMM (V3).

Architecture :
  - Un LogReg indépendant entraîné sur chaque état HMM du TRAIN
  - À l'inférence : routing par état prédit → expert correspondant prédit P(up)
  - Fallback : si un état a < min_samples_per_regime samples → expert global (V2)

Avantage vs V2 (un seul modèle global) :
  - Chaque expert apprend les features pertinentes DANS son régime
  - Le modèle "trending_down" ne pollue pas le modèle "ranging"
  - Généralisabilité cross-fenêtre améliorée

Sortie : pd.Series P(up) ∈ [0,1] identique à SignalModel.predict_proba().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

from quant.signal_model import SignalModel

logger = logging.getLogger("zeitgeist.quant.signal_model_v3")

MIN_SAMPLES_PER_REGIME = 105  # Juste au-dessus du seuil interne SignalModel (100)
MIN_TOTAL_FOR_SPLIT   = 300   # En dessous → V3 inutile, on garde l'expert global


@dataclass
class MixtureSignalModel:
    """Mixture-of-Experts : un SignalModel par état de régime HMM.

    Usage identique à SignalModel :
        model = MixtureSignalModel(feature_cols=cols).fit(X_train, y_train, regime_train)
        proba  = model.predict_proba(X_all, regime_all)
    """

    feature_cols: Sequence[str]
    use_calibration: bool = True
    use_lgb: bool = False
    C: float = 1.0
    cv_folds: int = 5

    _experts: dict[float, SignalModel] = field(default_factory=dict, init=False, repr=False)
    _global_fallback: SignalModel | None = field(default=None, init=False, repr=False)
    _regime_counts: dict[float, int] = field(default_factory=dict, init=False, repr=False)

    def _make_expert(self) -> SignalModel:
        # Pas de calibration Platt par expert : trop peu de samples par régime
        # (~1/3 du train total) → TimeSeriesSplit instable. La calibration globale
        # est assurée par l'expert global (fallback).
        return SignalModel(
            feature_cols=self.feature_cols,
            use_calibration=False,   # désactivé intentionnellement par régime
            use_lgb=self.use_lgb,
            C=self.C,
            cv_folds=self.cv_folds,
        )

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        regime: pd.Series,
    ) -> "MixtureSignalModel":
        """Entraîne un expert par état de régime.

        Args:
            X: features normalisées sur train_idx
            y: labels binaires 0/1 sur train_idx
            regime: série de régimes (0.0=panic, 0.5=range, 1.0=trend) sur train_idx
        """
        # Expert global (fallback)
        try:
            self._global_fallback = self._make_expert().fit(X, y)
            logger.info(f"MixtureSignalModel: expert global fitté sur {len(y)} échantillons")
        except Exception as exc:
            logger.warning(f"Expert global échec: {exc}")

        # Si train trop petit pour splitter, pas d'experts par régime
        if len(y) < MIN_TOTAL_FOR_SPLIT:
            logger.info(
                f"MixtureSignalModel: train={len(y)} < {MIN_TOTAL_FOR_SPLIT} "
                f"→ expert global uniquement (pas de split par régime)"
            )
            print(f"  [V3] global-only (train={len(y)} < {MIN_TOTAL_FOR_SPLIT})", flush=True)
            return self

        # Expert par régime
        states = regime.dropna().unique()
        for state in sorted(states):
            mask_state = (regime == state) & X[list(self.feature_cols)].notna().all(axis=1) & y.notna()
            n = mask_state.sum()
            self._regime_counts[state] = int(n)

            if n < MIN_SAMPLES_PER_REGIME:
                logger.info(
                    f"  Régime {state:.1f}: {n} samples < {MIN_SAMPLES_PER_REGIME} "
                    f"→ utilisera fallback global"
                )
                continue

            try:
                expert = self._make_expert().fit(X.loc[mask_state], y.loc[mask_state])
                self._experts[state] = expert
                logger.info(f"  Régime {state:.1f}: expert fitté sur {n} samples ✓")
            except Exception as exc:
                logger.warning(f"  Régime {state:.1f}: fit échoué ({exc}) → fallback global")

        logger.info(
            f"MixtureSignalModel: {len(self._experts)}/{len(states)} experts actifs "
            f"| régimes: {self._regime_counts}"
        )
        # Affiche sur stdout une seule fois par état d'experts distinct
        _active = {f"{s:.2f}": n for s, n in self._regime_counts.items()}
        _ok     = [f"{s:.2f}" for s in self._experts]
        _summary = f"experts={_ok} counts={_active}"
        if not hasattr(MixtureSignalModel, '_last_summary') or MixtureSignalModel._last_summary != _summary:
            MixtureSignalModel._last_summary = _summary  # type: ignore[attr-defined]
            print(f"  [V3] {_summary}", flush=True)
        return self

    def predict_proba(
        self,
        X: pd.DataFrame,
        regime: pd.Series,
    ) -> pd.Series:
        """Route chaque barre vers son expert de régime → P(up).

        Args:
            X: features sur l'index complet (train + test)
            regime: série de régimes sur le même index
        """
        out = pd.Series(np.nan, index=X.index, dtype="float64")

        states = regime.dropna().unique()
        for state in states:
            mask_state = regime == state
            if not mask_state.any():
                continue

            expert = self._experts.get(state, self._global_fallback)
            if expert is None:
                logger.warning(f"Aucun expert pour régime {state:.1f} et pas de fallback")
                continue

            try:
                proba = expert.predict_proba(X.loc[mask_state])
                out.loc[mask_state] = proba
            except Exception as exc:
                logger.warning(f"predict_proba régime {state:.1f}: {exc}")
                if self._global_fallback is not None:
                    out.loc[mask_state] = self._global_fallback.predict_proba(X.loc[mask_state])

        # Barres sans régime → fallback global
        no_regime = regime.isna()
        if no_regime.any() and self._global_fallback is not None:
            out.loc[no_regime] = self._global_fallback.predict_proba(X.loc[no_regime])

        return out
