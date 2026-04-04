"""
agents/market_regime_agent.py — Détection de régime de marché.

Utilise deux approches complémentaires sur les données OHLCV 15min :
  1. HMM (Hidden Markov Model) — détecte les régimes cachés Low/High Volatility
     et les probabilités de transition entre états.
  2. Features déterministes — classifie le régime en :
       TRENDING_UP | TRENDING_DOWN | SIDEWAYS | HIGH_VOLATILITY

Le régime détecté est injecté dans le state LangGraph et utilisé par le
CoordinatorAgent pour ajuster les poids des agents dynamiquement :
  - TRENDING   → ↑ TimesFM, ↑ Contrarian
  - SIDEWAYS   → ↑ Fear&Greed, ↓ TimesFM
  - HIGH_VOL   → ↓ position size signal, ↑ seuil de conviction

Dépendances : numpy (déjà présent), hmmlearn, scikit-learn (déjà dans requirements)
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger("zeitgeist.regime")

# Régimes possibles
REGIME_TRENDING_UP   = "TRENDING_UP"
REGIME_TRENDING_DOWN = "TRENDING_DOWN"
REGIME_SIDEWAYS      = "SIDEWAYS"
REGIME_HIGH_VOL      = "HIGH_VOLATILITY"
REGIME_UNKNOWN       = "UNKNOWN"


class MarketRegimeAgent:
    """
    Détecte le régime de marché courant à partir des données OHLCV.

    Retourne un dict compatible AgentAnalysis + champs supplémentaires :
        regime      : str   — TRENDING_UP / TRENDING_DOWN / SIDEWAYS / HIGH_VOLATILITY
        hmm_state   : int   — état HMM (0=low_vol, 1=high_vol)
        hmm_prob    : float — probabilité d'être dans l'état courant
        transition_prob : float — probabilité de changer d'état au prochain cycle
        features    : dict  — valeurs brutes des features utilisées
    """

    MIN_CANDLES = 60  # minimum pour un HMM fiable

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        regime_cfg = cfg.get("market_regime", {})
        self._n_hmm_states  = int(regime_cfg.get("n_hmm_states", 2))
        self._vol_window    = int(regime_cfg.get("vol_window", 20))
        self._trend_window  = int(regime_cfg.get("trend_window", 50))
        self._adx_period    = int(regime_cfg.get("adx_period", 14))

    # ------------------------------------------------------------------
    # Interface principale
    # ------------------------------------------------------------------

    def analyze(self, state: dict) -> dict:
        """Point d'entrée — compatible avec le pipeline d'agents."""
        try:
            closes, highs, lows, volumes = self._extract_ohlcv(state)
            if closes is None or len(closes) < self.MIN_CANDLES:
                return self._fallback("insufficient data")

            features = self._compute_features(closes, highs, lows, volumes)
            regime   = self._classify_regime(features)
            hmm_res  = self._run_hmm(closes, highs, lows)

            # Score 0-100 : BULLISH si UP, BEARISH si DOWN, ~50 sinon
            if regime == REGIME_TRENDING_UP:
                score, signal = 72.0, "BULLISH"
            elif regime == REGIME_TRENDING_DOWN:
                score, signal = 30.0, "BEARISH"
            elif regime == REGIME_HIGH_VOL:
                score, signal = 45.0, "NEUTRAL"
            else:  # SIDEWAYS
                score, signal = 50.0, "NEUTRAL"

            summary = (
                f"Regime: {regime} | "
                f"ADX={features['adx']:.1f} "
                f"(DI+={features['di_plus']:.1f}/DI-={features['di_minus']:.1f}) | "
                f"Vol={features['rel_volatility']:.2f}x ({features['vol_abs_annualized']:.0f}% ann.) | "
                f"HMM state={hmm_res['state']} "
                f"(p={hmm_res['state_prob']:.0%})"
            )

            # Direction pressure : DI+ vs DI- pour l'UI
            di_p = features["di_plus"]
            di_m = features["di_minus"]
            di_diff = di_p - di_m
            if di_diff > 10:
                direction_pressure = "Strong bullish pressure"
            elif di_diff > 4:
                direction_pressure = "Moderate bullish bias"
            elif di_diff < -10:
                direction_pressure = "Strong bearish pressure"
            elif di_diff < -4:
                direction_pressure = "Moderate bearish bias"
            else:
                direction_pressure = "No clear direction"

            logger.info(f"MarketRegime: {summary}")

            return {
                "agent_name":        "market_regime",
                "score":             score,
                "signal":            signal,
                "summary":           summary,
                "confidence":        round(hmm_res["state_prob"], 2),
                # Champs extra (utilisés par CoordinatorAgent + Dashboard)
                "regime":            regime,
                "hmm_state":         hmm_res["state"],
                "hmm_state_label":   hmm_res["label"],
                "hmm_prob":          hmm_res["state_prob"],
                "hmm_posteriors":    hmm_res.get("all_posteriors", {}),
                "transition_prob":   hmm_res["transition_prob"],
                "direction_pressure": direction_pressure,
                "features":          features,
            }

        except Exception as exc:
            logger.warning(f"MarketRegimeAgent error: {exc}")
            return self._fallback(str(exc))

    # ------------------------------------------------------------------
    # Feature engineering
    # ------------------------------------------------------------------

    def _compute_features(
        self,
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        volumes: np.ndarray,
    ) -> dict:
        vw = self._vol_window
        tw = self._trend_window

        # --- Rendements log ---
        returns = np.diff(np.log(closes))

        # --- Volatilité relative ---
        vol_recent  = float(np.std(returns[-vw:]))
        vol_long    = float(np.std(returns[-tw:])) if len(returns) >= tw else vol_recent
        rel_vol     = vol_recent / vol_long if vol_long > 0 else 1.0

        # --- Momentum (price-based) ---
        momentum_20  = float((closes[-1] - closes[-20]) / closes[-20]) if len(closes) >= 20 else 0.0
        momentum_50  = float((closes[-1] - closes[-min(tw, len(closes))]) / closes[-min(tw, len(closes))]) if len(closes) >= 10 else 0.0

        # --- SMA trend filter ---
        sma_fast = float(np.mean(closes[-20:]))
        sma_slow = float(np.mean(closes[-tw:])) if len(closes) >= tw else sma_fast
        sma_gap  = (sma_fast - sma_slow) / sma_slow if sma_slow > 0 else 0.0

        # --- ADX (Average Directional Index) + DI+ / DI- ---
        adx, di_plus_val, di_minus_val = self._compute_adx_with_di(highs, lows, closes, self._adx_period)

        # --- Volume momentum ---
        vol_mom = float(np.mean(volumes[-5:])) / float(np.mean(volumes[-20:])) if len(volumes) >= 20 and np.mean(volumes[-20:]) > 0 else 1.0

        # --- Bollinger Band width (mesure de compression/expansion) ---
        bb_std  = float(np.std(closes[-20:]))
        bb_mid  = float(np.mean(closes[-20:]))
        bb_width = (4 * bb_std / bb_mid) if bb_mid > 0 else 0.0  # (upper - lower) / mid

        # --- Volatilité absolue annualisée (std returns × sqrt(35040) pour 15min) ---
        vol_abs_annualized = float(np.std(returns[-vw:])) * (35040 ** 0.5)  # ~188 périodes/an

        return {
            "rel_volatility":  round(rel_vol, 4),
            "vol_abs_annualized": round(vol_abs_annualized * 100, 1),  # en %
            "momentum_20":     round(momentum_20, 4),
            "momentum_50":     round(momentum_50, 4),
            "sma_gap":         round(sma_gap, 4),
            "adx":             round(adx, 2),
            "di_plus":         round(di_plus_val, 2),
            "di_minus":        round(di_minus_val, 2),
            "volume_momentum": round(vol_mom, 3),
            "bb_width":        round(bb_width, 4),
            "current_price":   round(float(closes[-1]), 2),
        }

    @staticmethod
    def _compute_adx(highs, lows, closes, period=14) -> float:
        """ADX classique — retourne le scalaire final."""
        arr = MarketRegimeAgent._compute_adx_array(highs, lows, closes, period)
        valid = arr[~np.isnan(arr)]
        return float(valid[-1]) if len(valid) > 0 else 0.0

    @staticmethod
    def _compute_adx_with_di(
        highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14
    ) -> tuple[float, float, float]:
        """Retourne (adx, DI+, DI−) — scalaires pour le dernier point."""
        if len(highs) < period + 2:
            return 0.0, 0.0, 0.0
        try:
            up_moves   = np.diff(highs)
            down_moves = -np.diff(lows)
            dm_plus  = np.where((up_moves > down_moves) & (up_moves > 0), up_moves, 0.0)
            dm_minus = np.where((down_moves > up_moves) & (down_moves > 0), down_moves, 0.0)
            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))
            )

            def smooth(a, p):
                r = [np.mean(a[:p])]
                for v in a[p:]:
                    r.append(r[-1] - r[-1] / p + v)
                return np.array(r)

            atr_s = smooth(tr, period)
            dmp_s = smooth(dm_plus, period)
            dmm_s = smooth(dm_minus, period)
            safe  = np.where(atr_s > 0, atr_s, 1e-9)
            di_p  = 100 * dmp_s / safe
            di_m  = 100 * dmm_s / safe
            dx    = 100 * np.abs(di_p - di_m) / np.where((di_p + di_m) > 0, (di_p + di_m), 1e-9)
            adx_v = smooth(dx, period)
            return float(adx_v[-1]), float(di_p[-1]), float(di_m[-1])
        except Exception:
            return 0.0, 0.0, 0.0

    @staticmethod
    def _compute_adx_array(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        period: int = 14,
    ) -> np.ndarray:
        """ADX classique — retourne le tableau complet aligné sur closes (np.nan aux débuts)."""
        if len(highs) < period + 2:
            return np.full(len(closes), np.nan)
        try:
            up_moves   = np.diff(highs)
            down_moves = -np.diff(lows)

            dm_plus  = np.where((up_moves > down_moves) & (up_moves > 0), up_moves,  0.0)
            dm_minus = np.where((down_moves > up_moves) & (down_moves > 0), down_moves, 0.0)

            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(
                    np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:]  - closes[:-1]),
                )
            )

            def smooth(arr, p):
                # Wilder's SMMA — used for +DM, −DM, TR (raw values; scale cancels in DI ratio)
                result = [np.mean(arr[:p])]
                for v in arr[p:]:
                    result.append(result[-1] - result[-1] / p + v)
                return np.array(result)

            def smooth_adx(arr, p):
                # True EMA (alpha=1/p) — DX is in [0–100]; SMMA would diverge to p×DX
                result = [np.mean(arr[:p])]
                for v in arr[p:]:
                    result.append(result[-1] * (p - 1) / p + v / p)
                return np.array(result)

            atr_s   = smooth(tr, period)
            dmp_s   = smooth(dm_plus,  period)
            dmm_s   = smooth(dm_minus, period)

            di_plus  = 100 * dmp_s / np.where(atr_s > 0, atr_s, 1e-9)
            di_minus = 100 * dmm_s / np.where(atr_s > 0, atr_s, 1e-9)

            dx = 100 * np.abs(di_plus - di_minus) / np.where((di_plus + di_minus) > 0, (di_plus + di_minus), 1e-9)
            adx_vals = smooth_adx(dx, period)

            # Aligner sur closes : NaN pour les premières entrées non calculables
            result = np.full(len(closes), np.nan)
            n_valid = len(adx_vals)
            result[len(closes) - n_valid:] = adx_vals
            return result
        except Exception:
            return np.full(len(closes), np.nan)

    # ------------------------------------------------------------------
    # Classification déterministe
    # ------------------------------------------------------------------

    def _classify_regime(self, f: dict) -> str:
        """
        Règles de classification par priorité :
          1. TRENDING si ADX > 30 ET momentum directionnel clair (≥2 signaux)
             → un ADX très élevé avec direction confirme un trend fort, pas juste de la volatilité
          2. HIGH_VOLATILITY si vol relative > 2.0 OU bb_width > 0.08 (choc sans direction)
          3. TRENDING si ADX > 18 + momentum cohérent
          4. SIDEWAYS sinon
        """
        di_spread = f["di_plus"] - f["di_minus"]
        bull_signals = sum([
            f["momentum_20"] > 0.01,
            f["momentum_50"] > 0.02,
            f["sma_gap"]     > 0.005,
            di_spread > 5,       # DI+ nettement au-dessus de DI-
        ])
        bear_signals = sum([
            f["momentum_20"] < -0.01,
            f["momentum_50"] < -0.02,
            f["sma_gap"]     < -0.005,
            di_spread < -5,      # DI- nettement au-dessus de DI+
        ])

        # 1. ADX très élevé (>30) avec direction claire → TRENDING prime sur HIGH_VOL
        if f["adx"] > 30:
            if bull_signals >= 2:
                return REGIME_TRENDING_UP
            if bear_signals >= 2:
                return REGIME_TRENDING_DOWN
            # ADX > 30 sans direction nette = blow-off / choc violent
            return REGIME_HIGH_VOL

        # 2. Choc de volatilité sans trend directionnel
        if f["rel_volatility"] > 2.0 or f["bb_width"] > 0.08:
            # Même en high vol, si momentum est clair on préfère classer en TRENDING
            if bull_signals >= 2:
                return REGIME_TRENDING_UP
            if bear_signals >= 2:
                return REGIME_TRENDING_DOWN
            return REGIME_HIGH_VOL

        # 3. Tendance forte (ADX 18-30)
        if f["adx"] > 18:
            if bull_signals >= 2:
                return REGIME_TRENDING_UP
            if bear_signals >= 2:
                return REGIME_TRENDING_DOWN
            # ADX élevé mais direction mixte → high vol
            return REGIME_HIGH_VOL

        # 4. Tendance modérée (ADX 12-18)
        if f["adx"] > 12:
            if f["momentum_20"] > 0.005 and f["sma_gap"] > 0:
                return REGIME_TRENDING_UP
            if f["momentum_20"] < -0.005 and f["sma_gap"] < 0:
                return REGIME_TRENDING_DOWN

        # 5. Sideways par défaut
        return REGIME_SIDEWAYS

    # ------------------------------------------------------------------
    # HMM
    # ------------------------------------------------------------------

    def _run_hmm(
        self,
        closes: np.ndarray,
        highs: "np.ndarray | None" = None,
        lows:  "np.ndarray | None" = None,
    ) -> dict:
        """
        Gaussian HMM à n_hmm_states états (Low/[Med/]High Volatility).
        3 features : returns + volatilité rolling + ADX (vraie TR si highs/lows dispo).
        covariance_type="full" pour capturer les corrélations inter-features.
        """
        try:
            from hmmlearn.hmm import GaussianHMM

            returns = np.diff(np.log(closes))
            if len(returns) < self.MIN_CANDLES:
                raise ValueError("not enough data")

            r = returns

            # Feature 2 : volatilité rolling
            vw = self._vol_window
            vol = np.array([
                np.std(r[max(0, i - vw):i + 1])
                for i in range(len(r))
            ])

            # Feature 3 : ADX vectorisé — utilise vraies highs/lows si disponibles
            # (passes closes[1:] as both when missing → TR=0; always provide highs/lows)
            h = highs[1:] if highs is not None else closes[1:]
            l = lows[1:]  if lows  is not None else closes[1:]
            adx_arr = self._compute_adx_array(h, l, closes[1:], self._adx_period)

            X = np.column_stack((
                r,
                np.nan_to_num(vol,     nan=0.0),
                np.nan_to_num(adx_arr, nan=25.0),
            ))

            model = GaussianHMM(
                n_components=self._n_hmm_states,
                covariance_type="full",
                n_iter=200,
                random_state=42,
            )
            model.fit(X)

            states      = model.predict(X)
            posteriors  = model.predict_proba(X)
            current_state = int(states[-1])
            state_prob    = float(posteriors[-1, current_state])

            # Labels dynamiques : trier les états par variance du return (feature 0)
            # ascending → rank 0 = Low-vol, rank 1 = [Med-vol,] rank n-1 = High-vol
            n = self._n_hmm_states
            vars_per_state = [float(model.covars_[s][0, 0]) for s in range(n)]
            sorted_states  = sorted(range(n), key=lambda s: vars_per_state[s])
            _vol_labels    = ["LOW_VOL", "MED_VOL", "HIGH_VOL"] if n == 3 else ["LOW_VOL", "HIGH_VOL"]
            state_label_map = {s: _vol_labels[rank] for rank, s in enumerate(sorted_states)}
            label = state_label_map[current_state]

            # Probabilité de changer d'état
            if n == 2:
                transition_prob = float(model.transmat_[current_state, 1 - current_state])
            else:
                transition_prob = float(1.0 - model.transmat_[current_state, current_state])

            all_posteriors = {f"state_{s}": round(float(posteriors[-1, s]), 3)
                              for s in range(n)}

            return {
                "state":           current_state,
                "label":           label,
                "state_prob":      state_prob,
                "transition_prob": transition_prob,
                "all_posteriors":  all_posteriors,
                "state_labels":    state_label_map,
            }

        except ImportError:
            logger.debug("hmmlearn non disponible — HMM ignoré")
            return {"state": 0, "label": "LOW_VOL", "state_prob": 0.5, "transition_prob": 0.2, "all_posteriors": {}, "state_labels": {}}
        except Exception as exc:
            logger.debug(f"HMM échoué: {exc}")
            return {"state": 0, "label": "LOW_VOL", "state_prob": 0.5, "transition_prob": 0.2, "all_posteriors": {}, "state_labels": {}}

    # ------------------------------------------------------------------
    # Extraction OHLCV
    # ------------------------------------------------------------------

    def _extract_ohlcv(
        self, state: dict
    ) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None, np.ndarray | None]:
        """Récupère les arrays OHLCV depuis le state ou CCXT directement."""
        indicators = state.get("market_indicators") or {}
        ohlcv_raw = indicators.get("ohlcv_raw")

        if ohlcv_raw is not None and len(ohlcv_raw) >= self.MIN_CANDLES:
            arr = np.array(ohlcv_raw)
            return arr[:, 4], arr[:, 2], arr[:, 3], arr[:, 5]

        # Fallback CCXT
        try:
            import ccxt
            exchange = ccxt.binance({"enableRateLimit": True})
            asset = state.get("asset", "BTC/USDT")
            ohlcv = exchange.fetch_ohlcv(asset, "15m", limit=200)
            arr = np.array(ohlcv)
            return arr[:, 4], arr[:, 2], arr[:, 3], arr[:, 5]
        except Exception as exc:
            logger.warning(f"MarketRegime CCXT fallback failed: {exc}")
            return None, None, None, None

    def _fallback(self, reason: str) -> dict:
        return {
            "agent_name":         "market_regime",
            "score":              50.0,
            "signal":             "NEUTRAL",
            "summary":            f"Regime unknown ({reason})",
            "confidence":         0.0,
            "regime":             REGIME_UNKNOWN,
            "hmm_state":          0,
            "hmm_state_label":    "UNKNOWN",
            "hmm_prob":           0.5,
            "hmm_posteriors":     {},
            "transition_prob":    0.2,
            "direction_pressure": "No clear direction",
            "features":           {},
        }
