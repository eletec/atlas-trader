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

logger = logging.getLogger("zeitgeist.quant.regime")

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
    n_states: int = 3                    # 3 états : Trending / Ranging / Panic
    adx_threshold: float = 25.0
    vov_threshold: float = 0.5
    _hmm: object | None = field(default=None, init=False, repr=False)
    _trending_state: int | None = field(default=None, init=False, repr=False)
    _panic_state: int | None = field(default=None, init=False, repr=False)
    _vov_chaos_threshold: float = field(default=float("inf"), init=False, repr=False)

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
            n_components=self.n_states,
            covariance_type="full",
            n_iter=200,
            random_state=42,
        )
        hmm.fit(x.values)
        # Labellisation post-fit — causal : stats du TRAIN uniquement
        variances = [float(hmm.covars_[s][0, 0]) for s in range(self.n_states)]
        means = [float(hmm.means_[s][0]) for s in range(self.n_states)]
        stds = [np.sqrt(v) + 1e-9 for v in variances]
        # Panic = état à variance maximale (mouvements extrêmes non directionnels)
        self._panic_state = int(np.argmax(variances))
        # Trending = parmi les états restants, Sharpe |mean|/std le plus élevé
        non_panic = [s for s in range(self.n_states) if s != self._panic_state]
        sharpes = [abs(means[s]) / stds[s] for s in non_panic]
        self._trending_state = non_panic[int(np.argmax(sharpes))]
        # Seuil chaos vol_of_vol calibré sur le TRAIN (causal)
        if "vol_of_vol_20" in features.columns:
            vov = features["vol_of_vol_20"].dropna()
            if len(vov) > 50:
                self._vov_chaos_threshold = float(vov.quantile(0.80))
        self._hmm = hmm
        labels = {s: "RANGE" for s in range(self.n_states)}
        labels[self._trending_state] = "TREND"
        labels[self._panic_state] = "PANIC"
        logger.info(
            "HMM %d états fit OK — " % self.n_states
            + " | ".join(
                f"state{s}={labels[s]} var={variances[s]:.6f} mean={means[s]:.6f}"
                for s in range(self.n_states)
            )
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
            self._vov_chaos_threshold = float(vov_vals.quantile(0.80))
        logger.info(
            f"Fallback threshold: adx>{self.adx_threshold:.2f} & vov<{self.vov_threshold:.4f} "
            f"chaos>{self._vov_chaos_threshold:.4f}"
        )
        return self

    def predict(self, features: pd.DataFrame) -> pd.Series:
        """Prédit le régime — forward filtering strict, hysteresis, gate vol_of_vol.

        Returns:
            Série float (1.0 = trending, 0.0 = mean-reverting/ranging/panic), index aligné.
        """
        if self.use_hmm and self._hmm is not None:
            out = self._predict_hmm(features)
        else:
            out = self._predict_threshold(features)
        # Gate chaos : force 0.0 si vol_of_vol dépasse le seuil calibré sur TRAIN (Phase 1.1)
        if (
            "vol_of_vol_20" in features.columns
            and self._vov_chaos_threshold < float("inf")
        ):
            chaos = features["vol_of_vol_20"] > self._vov_chaos_threshold
            out[chaos.fillna(False)] = 0.0
        return out

    def _predict_hmm(self, features: pd.DataFrame) -> pd.Series:
        x_full = features[["log_return_1", "atr_pct"]]
        valid_mask = x_full.notna().all(axis=1)
        x = x_full[valid_mask]
        if len(x) == 0:
            return pd.Series(index=features.index, dtype="float64")
        # Forward filtering pur — P(state_t | obs_1:t), strictement causal (Phase 0.1)
        filtered = self._forward_filter(x.values)          # (T, n_states)
        trend_probs = filtered[:, self._trending_state]
        panic_probs = filtered[:, self._panic_state]
        # Hysteresis : évite les transitions trop rapides (GPT + Grok)
        states = np.empty(len(x), dtype=float)
        prev = 0.0
        for i in range(len(trend_probs)):
            pp = panic_probs[i]
            tp = trend_probs[i]
            if pp > 0.60:
                prev = 0.0      # panic → force mean-reverting
            elif tp > 0.65:
                prev = 1.0      # trending confirmé
            elif tp < 0.35:
                prev = 0.0      # ranging confirmé
            # zone [0.35, 0.65] → maintient l'état précédent (inertie)
            states[i] = prev
        out = pd.Series(np.nan, index=features.index, dtype="float64")
        out.loc[valid_mask] = states
        return out

    def _forward_filter(self, observations: np.ndarray) -> np.ndarray:
        """Algorithme forward (filtering) — P(state_t | obs_1:t) strictement causal.

        Implémentation manuelle : évite le lissage Baum-Welch de score_samples().
        Complexité : O(T × n_states²) — linéaire en T.
        """
        n_samples = len(observations)
        n_states = self._hmm.n_components
        # Probabilités d'émission via hmmlearn interne, avec fallback scipy
        try:
            log_B = self._hmm._compute_log_likelihood(observations)  # (T, n_states)
        except AttributeError:
            from scipy.stats import multivariate_normal
            log_B = np.zeros((n_samples, n_states))
            for s in range(n_states):
                log_B[:, s] = multivariate_normal.logpdf(
                    observations,
                    mean=self._hmm.means_[s],
                    cov=self._hmm.covars_[s],
                )
        log_A = np.log(self._hmm.transmat_ + 1e-300)   # (n_states, n_states)
        # α_0 : distribution filtrée initiale
        log_alpha = np.log(self._hmm.startprob_ + 1e-300) + log_B[0]
        _m = log_alpha.max()
        log_alpha -= _m + np.log(np.exp(log_alpha - _m).sum())
        posteriors = np.zeros((n_samples, n_states))
        posteriors[0] = np.exp(log_alpha)
        for t in range(1, n_samples):
            # Prédiction : Σ_i α_{t-1}(i) × A[i,j] pour chaque j
            tmp = log_alpha[:, None] + log_A      # (n_states, n_states)
            _m = tmp.max(axis=0)
            log_alpha = _m + np.log(np.exp(tmp - _m).sum(axis=0))
            # Mise à jour : × émission
            log_alpha += log_B[t]
            # Normalisation log-domain
            _m = log_alpha.max()
            log_alpha -= _m + np.log(np.exp(log_alpha - _m).sum())
            posteriors[t] = np.exp(log_alpha)
        return posteriors

    def _predict_threshold(self, features: pd.DataFrame) -> pd.Series:
        adx_ = features["adx_14"]
        vov_ = features["vol_of_vol_20"]
        trending = ((adx_ > self.adx_threshold) & (vov_ < self.vov_threshold)).astype(float)
        # Masque les zones où les features ne sont pas définies
        trending = trending.where(adx_.notna() & vov_.notna())
        return trending
