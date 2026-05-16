"""
quant/regime.py — Détecteur de régime à 2 états (trending / mean-reverting).

Critique IA convergente : un HMM 4 états avec Baum-Welch smoothing introduit du
look-ahead massif. Solution :
1. Entraîner le HMM 2 états sur la fenêtre TRAIN uniquement (gel des params).
2. À l'inférence, utiliser le FILTERING (forward-only), JAMAIS le smoothing.
3. Si hmmlearn n'est pas disponible, fallback robuste sur (ADX + vol_of_vol).

Sortie : Série binaire indexée comme l'input — 1 = trending, 0 = mean-reverting.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger("quant.regime")

try:
    from hmmlearn.hmm import GaussianHMM

    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False
    logger.warning("hmmlearn indisponible — fallback ADX+vol_of_vol activé.")


@dataclass
class RegimeDetector:
    """Détecteur de régime 2 états.

    Mode HMM (préféré) :
        - Features d'entrée : log_return absolu, atr_pct
        - 2 états gaussiens, transition appris sur TRAIN
        - Inférence : filtering pur (`hmm.predict` séquentiel barre par barre)

    Mode fallback (si hmmlearn KO) :
        - Trending = (ADX > seuil_adx) ET (vol_of_vol < seuil_vov)
        - Seuils calibrés sur quantile 60% du TRAIN
    """

    use_hmm: bool = True
    adx_threshold: float = 25.0
    vov_threshold: float = 0.5
    _hmm: object | None = field(default=None, init=False, repr=False)
    _trending_state: int | None = field(default=None, init=False, repr=False)

    def fit(self, features: pd.DataFrame) -> "RegimeDetector":
        """Entraîne sur la fenêtre TRAIN. Aucune donnée OOS ne doit transiter ici."""
        if self.use_hmm and HMM_AVAILABLE:
            return self._fit_hmm(features)
        return self._fit_threshold(features)

    def _fit_hmm(self, features: pd.DataFrame) -> "RegimeDetector":
        x = features[["log_return_1", "atr_pct"]].dropna()
        if len(x) < 200:
            logger.warning(f"Données HMM insuffisantes ({len(x)}), fallback threshold.")
            return self._fit_threshold(features)
        hmm = GaussianHMM(
            n_components=2,
            covariance_type="full",
            n_iter=200,
            random_state=42,
        )
        hmm.fit(x.values)
        # Identifie le régime "trending" comme celui à plus forte variance de log_return_1
        var_state_0 = float(hmm.covars_[0][0, 0])
        var_state_1 = float(hmm.covars_[1][0, 0])
        self._trending_state = 0 if var_state_0 > var_state_1 else 1
        self._hmm = hmm
        logger.info(
            f"HMM fit OK — trending=state{self._trending_state} "
            f"(var0={var_state_0:.6f}, var1={var_state_1:.6f})"
        )
        return self

    def _fit_threshold(self, features: pd.DataFrame) -> "RegimeDetector":
        self.use_hmm = False
        adx_vals = features["adx_14"].dropna()
        vov_vals = features["vol_of_vol_20"].dropna()
        if len(adx_vals) > 50:
            self.adx_threshold = float(adx_vals.quantile(0.60))
        if len(vov_vals) > 50:
            self.vov_threshold = float(vov_vals.quantile(0.60))
        logger.info(
            f"Fallback threshold: adx>{self.adx_threshold:.2f} & vov<{self.vov_threshold:.4f}"
        )
        return self

    def predict(self, features: pd.DataFrame) -> pd.Series:
        """Prédit le régime barre par barre en mode FILTERING (causal strict).

        Returns:
            Série binaire (1 = trending, 0 = mean-reverting), index aligné.
        """
        if self.use_hmm and self._hmm is not None:
            return self._predict_hmm(features)
        return self._predict_threshold(features)

    def _predict_hmm(self, features: pd.DataFrame) -> pd.Series:
        x_full = features[["log_return_1", "atr_pct"]]
        valid_mask = x_full.notna().all(axis=1)
        x = x_full[valid_mask]
        if len(x) == 0:
            return pd.Series(index=features.index, dtype="float64")
        # FILTERING : on prédit la séquence d'états la plus probable de manière
        # causale. hmm.predict utilise Viterbi qui regarde toute la séquence —
        # on doit donc l'appliquer de manière incrémentale.
        states = np.empty(len(x), dtype=int)
        for i in range(1, len(x) + 1):
            seq = x.iloc[:i].values
            # Optimisation : ne refaire le forward que sur les 500 dernières barres
            # (les états plus anciens sont stabilisés)
            if i > 500:
                seq = seq[-500:]
            states[i - 1] = self._hmm.predict(seq)[-1]
        is_trending = (states == self._trending_state).astype(float)
        out = pd.Series(index=features.index, dtype="float64")
        out.loc[x.index] = is_trending
        return out

    def _predict_threshold(self, features: pd.DataFrame) -> pd.Series:
        adx_ = features["adx_14"]
        vov_ = features["vol_of_vol_20"]
        trending = ((adx_ > self.adx_threshold) & (vov_ < self.vov_threshold)).astype(float)
        # Masque les zones où les features ne sont pas définies
        trending = trending.where(adx_.notna() & vov_.notna())
        return trending
