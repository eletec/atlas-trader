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
import traceback
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


def _rgcfg(key: str, fallback):
    try:
        from quant.config import get_quant_cfg
        return getattr(get_quant_cfg(), key)
    except Exception:
        return fallback


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
    n_states: int        = field(default_factory=lambda: _rgcfg("hmm_n_states", 3))
    adx_threshold: float = field(default_factory=lambda: _rgcfg("hmm_adx_threshold", 25.0))
    vov_threshold: float = 0.5
    _hmm: object | None = field(default=None, init=False, repr=False)
    _trending_state: int | None = field(default=None, init=False, repr=False)
    _panic_state: int | None = field(default=None, init=False, repr=False)
    _prev_trending_state: int | None = field(default=None, init=False, repr=False)  # P1.4
    _prev_panic_state: int | None = field(default=None, init=False, repr=False)     # P1.4
    _vov_chaos_threshold: float = field(default=float("inf"), init=False, repr=False)

    def fit(self, features: pd.DataFrame) -> "RegimeDetector":
        """Entraîne sur la fenêtre TRAIN. Aucune donnée OOS ne doit transiter ici."""
        if self.use_hmm and HMM_AVAILABLE:
            return self._fit_hmm(features)
        return self._fit_threshold(features)

    def _fit_hmm(self, features: pd.DataFrame) -> "RegimeDetector":
        # Sélection conditionnelle des features HMM (Grok + GPT : 4 features si dispo)
        hmm_cols = ["log_return_1", "atr_pct"]
        extra_cols = ["adx_14", "vol_of_vol_20"]
        if all(c in features.columns for c in extra_cols):
            n_extra = min(features[c].notna().sum() for c in extra_cols)
            if n_extra >= 300:
                hmm_cols = hmm_cols + extra_cols
        self._hmm_feature_cols = hmm_cols

        x = features[hmm_cols].dropna()
        if len(x) < 200:
            logger.warning(f"Données HMM insuffisantes ({len(x)}), fallback threshold.")
            return self._fit_threshold(features)
        hmm = GaussianHMM(
            n_components=self.n_states,
            covariance_type="diag",   # A.2 : diag > full sur 2 features / 63j (GPT)
            min_covar=1e-4,            # A.2 : évite singularités de covariance
            n_iter=200,
            random_state=42,
        )
        hmm.fit(x.values)
        # Labellisation post-fit — causal : stats du TRAIN uniquement
        # covariance_type="diag" → covars_[s] est de shape (n_features,)
        try:
            # hmmlearn ≥ 0.3 stocke covars_ comme (n_states, n_features, n_features)
            # pour covariance_type="diag". Extraire la diagonale si nécessaire.
            _diag = lambda s: np.diag(np.asarray(hmm.covars_[s])) if np.asarray(hmm.covars_[s]).ndim == 2 else np.asarray(hmm.covars_[s])
            raw_variances = [float(_diag(s)[0]) for s in range(self.n_states)]
            # Clamp : variance > 0.5 sur des returns en % = état dégénéré (HMM mal convergé)
            _MAX_VAR = 0.5
            if any(v > _MAX_VAR for v in raw_variances):
                logger.warning(f"HMM état(s) dégénéré(s) détecté(s) — variances brutes: {[f'{v:.6f}' for v in raw_variances]} — clampées à {_MAX_VAR}")
            variances = [min(v, _MAX_VAR) for v in raw_variances]
            means = [float(np.asarray(hmm.means_[s]).flat[0]) for s in range(self.n_states)]
        except Exception:
            logger.error("_fit_hmm post-fit labelling FAILED:\n" + traceback.format_exc())
            raise
        stds = [np.sqrt(v) + 1e-9 for v in variances]
        sharpe_like = [abs(means[s]) / stds[s] for s in range(self.n_states)]
        # A.1 : Panic = variance max ET non-directionnel (sharpe < 0.10)
        # Évite de classer un crash directionnel baissier comme Panic → raterait les SHORTs
        # Correction : parmi les candidats Panic, préférer les états à mean négatif (vrai sell-off).
        # Quand le marché est bruité (5m, tous sharpe < 0.10), cela évite d'assigner PANIC
        # à l'état le plus haussier (variance max ≠ vrai panic si mean > 0).
        panic_candidates = [s for s in range(self.n_states) if sharpe_like[s] < 0.10]
        if panic_candidates:
            negative_mean_candidates = [s for s in panic_candidates if means[s] < 0]
            if negative_mean_candidates:
                self._panic_state = max(negative_mean_candidates, key=lambda s: variances[s])
            else:
                self._panic_state = max(panic_candidates, key=lambda s: variances[s])
        else:
            self._panic_state = int(np.argmax(variances))  # fallback : variance max
        # Trending = non-Panic avec Sharpe-like maximal
        non_panic = [s for s in range(self.n_states) if s != self._panic_state]
        self._trending_state = max(non_panic, key=lambda s: sharpe_like[s])
        # Seuil chaos vol_of_vol calibré sur le TRAIN (causal)
        if "vol_of_vol_20" in features.columns:
            vov = features["vol_of_vol_20"].dropna()
            if len(vov) > 50:
                self._vov_chaos_threshold = float(vov.quantile(0.80))
        self._hmm = hmm
        # P1.4 : détection de permutation de labels HMM entre refits consécutifs
        if self._prev_trending_state is not None:
            if (self._trending_state != self._prev_trending_state
                    or self._panic_state != self._prev_panic_state):
                logger.warning(
                    f"HMM label permutation détectée : "
                    f"trend {self._prev_trending_state}→{self._trending_state}, "
                    f"panic {self._prev_panic_state}→{self._panic_state} "
                    f"(variances={[f'{v:.6f}' for v in variances]})"
                )
        self._prev_trending_state = self._trending_state
        self._prev_panic_state = self._panic_state
        labels = {s: "RANGE" for s in range(self.n_states)}
        labels[self._trending_state] = "TREND"
        labels[self._panic_state] = "PANIC"
        logger.info(
            "HMM %d états fit OK — " % self.n_states
            + " | ".join(
                f"state{s}={labels[s]} var={variances[s]:.6f} mean={means[s]:.6f} sharpe={sharpe_like[s]:.3f}"
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
        # B.1 Gate chaos — seuil adaptatif rolling backward (3/3 IA)
        # Remplace le p80 TRAIN figé par un quantile glissant causal (2880 barres, shift(1))
        if (
            "vol_of_vol_20" in features.columns
            and self._vov_chaos_threshold < float("inf")
        ):
            vov = features["vol_of_vol_20"]
            rolling_thresh = vov.rolling(2880, min_periods=720).quantile(0.80).shift(1)
            # Fallback sur seuil TRAIN pour les premières barres sans historique suffisant
            adaptive_thresh = rolling_thresh.where(rolling_thresh.notna(), self._vov_chaos_threshold)
            chaos = vov > adaptive_thresh
            out[chaos.fillna(False)] = 0.0
        return out

    def _predict_hmm(self, features: pd.DataFrame) -> pd.Series:
        hmm_cols = getattr(self, "_hmm_feature_cols", ["log_return_1", "atr_pct"])
        x_full = features[hmm_cols]
        valid_mask = x_full.notna().all(axis=1)
        x = x_full[valid_mask]
        if len(x) == 0:
            return pd.Series(index=features.index, dtype="float64")
        # Forward filtering pur — P(state_t | obs_1:t), strictement causal (Phase 0.1)
        filtered = self._forward_filter(x.values)          # (T, n_states)
        trend_probs = filtered[:, self._trending_state]
        panic_probs = filtered[:, self._panic_state]
        # Hysteresis : évite les transitions trop rapides (GPT + Grok)
        # Seuils adaptatifs au nombre d'états : avec n états, la probabilité "neutre"
        # est 1/n. Les seuils sont calibrés par rapport à cette baseline.
        # n=3: base=0.333 → trend_hi=0.45, trend_lo=0.27, panic_hi=0.55
        # n=2: base=0.500 → trend_hi=0.62, trend_lo=0.40, panic_hi=0.62
        _base = 1.0 / max(self.n_states, 2)
        _trend_hi  = round(_base + 0.12, 3)   # seuil entrée TREND
        _trend_lo  = round(_base - 0.07, 3)   # seuil sortie TREND → RANGE
        _panic_hi  = round(_base + 0.22, 3)   # seuil entrée PANIC (plus strict)
        logger.debug(
            f"Hysteresis seuils: trend_hi={_trend_hi} trend_lo={_trend_lo} panic_hi={_panic_hi} (n_states={self.n_states})"
        )
        # États : 1.0=TREND, 0.5=RANGE (mean-reverting possible), 0.0=PANIC
        states = np.empty(len(x), dtype=float)
        prev = 0.5      # boot en RANGE (pas PANIC) — conservateur mais pas bloquant
        for i in range(len(trend_probs)):
            pp = panic_probs[i]
            tp = trend_probs[i]
            if pp > _panic_hi:
                prev = 0.0      # PANIC confirmé → pas de trading
            elif tp > _trend_hi:
                prev = 1.0      # TREND confirmé → stratégie directionnelle
            elif tp < _trend_lo:
                prev = 0.5      # RANGE confirmé → stratégie mean-reverting
            # zone [_trend_lo, _trend_hi] → inertie (maintient l'état précédent)
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
        # Probabilités d'émission log — scipy en primaire (stable, pas d'API privée).
        # covariance_type="diag" → covars_[s] shape (n_features,) = variances par feature.
        # log P(obs | state=s) = Σ_f log N(obs_f ; mean_sf, var_sf)
        from scipy.stats import norm as _norm
        log_B = np.zeros((n_samples, n_states))
        for s in range(n_states):
            # hmmlearn ≥ 0.3 stocke covars_ comme (n_states, n_features, n_features)
            # pour covariance_type="diag" — extraire la diagonale si nécessaire.
            _c = np.asarray(self._hmm.covars_[s])
            var_s  = np.diag(_c) if _c.ndim == 2 else _c   # → (n_features,)
            mean_s = self._hmm.means_[s]                    # (n_features,)
            log_B[:, s] = np.sum(
                _norm.logpdf(observations, loc=mean_s, scale=np.sqrt(var_s + 1e-300)),
                axis=1,
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
        # 3 états : 1.0=TREND, 0.5=RANGE, 0.0=PANIC
        out = pd.Series(0.5, index=features.index, dtype="float64")   # défaut = RANGE
        trending = (adx_ > self.adx_threshold) & (vov_ < self.vov_threshold)
        panic = vov_ > self._vov_chaos_threshold
        out[trending.fillna(False)] = 1.0
        out[panic.fillna(False)] = 0.0     # PANIC écrase TREND si les deux sont vrais
        # NaN sur valeurs manquantes
        out[adx_.isna() | vov_.isna()] = np.nan
        return out
