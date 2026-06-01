"""
graph/workflow.py — Orchestration V2 (quant pur, sans LLM dans la boucle de décision)

Remplace le workflow LangGraph V1 (multi-agents, scoring, debate).

Architecture V2 :
    run_cycle()  ←  main.py (daemon, toutes les 15min)
         │
         ▼
    LiveRunner.step()
         │
         ├─ [init / refit hebdo] fetch_history → fit RegimeDetector + SignalModel
         │
         ├─ fetch dernier OHLCV (1 barre ccxt)
         ├─ compute_features (causal)
         ├─ normalize_features (rolling quantile backward)
         ├─ regime.predict (filtering causal)
         ├─ model.predict_proba (logistic + Platt)
         ├─ decide (arbre régime × P(up))
         ├─ risk.compute_position (si entrée)
         └─ write_v2_state + append_v2_equity (DB)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("zeitgeist.quant.workflow")

from quant.data_loader import fetch_history, fetch_ohlcv
from quant.features import compute_features, make_target_direction
from quant.normalization import normalize_features
from quant.pipeline import DEFAULT_FEATURE_COLS, PipelineConfig
from quant.regime import RegimeDetector
from quant.risk import Position, RiskManager, RiskParams
from quant.signal_model import SignalModel
from quant.strategy import Action, decide, decide_range


def _wf_qcfg():
    try:
        from quant.config import get_quant_cfg
        return get_quant_cfg()
    except Exception:
        return None


def _wf_attr(key, fallback):
    return getattr(_wf_qcfg(), key, fallback)


# Lus au runtime depuis settings.yaml via get_quant_cfg()
def _DEFAULT_SYMBOL()     -> str:   return _wf_attr("symbol",         "BTC/USDT")
def _DEFAULT_TF()         -> str:   return _wf_attr("timeframe",      "5m")
def _HISTORY_DAYS()       -> int:   return _wf_attr("history_days",   90)
def _TRAIN_FRACTION()     -> float: return _wf_attr("train_fraction", 0.70)
def _REFIT_INTERVAL_S()   -> int:   return _wf_attr("refit_interval_days", 7) * 86400

def _MAX_HISTORY_BARS()   -> int:
    tf = _DEFAULT_TF()
    bpd = {"1m": 1440, "3m": 480, "5m": 288, "15m": 96, "1h": 24, "4h": 6, "1d": 1}.get(tf, 288)
    return _HISTORY_DAYS() * bpd

# Durée en secondes par barre selon le timeframe
_TF_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
               "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}


class LiveRunner:
    """Gère l état continu du pipeline V2 entre les cycles."""

    def __init__(self, symbol="BTC/USDT", timeframe="5m", history_days=90,
                 train_fraction=0.70, config=None, refit_interval_s=None):
        self.symbol = symbol
        self.timeframe = timeframe
        self.history_days = history_days
        self.train_fraction = train_fraction
        self.cfg = config or PipelineConfig(use_hmm=False)
        self._refit_interval_s = refit_interval_s if refit_interval_s is not None else _REFIT_INTERVAL_S()
        self._ohlcv = None
        self._regime = None
        self._model = None
        self._last_fit_ts = 0.0
        self._model_fit_at = None
        self._feats_cache: pd.DataFrame | None = None  # cache feats_all post-refit
        self._feats_cache_ohlcv_len: int = 0            # len(ohlcv) when cache was built
        self._active_feature_cols: list = list(self.cfg.feature_cols)  # updated after refit (NaN cols dropped)
        self._position = None
        self._position_entry_ts = None
        self._position_is_range: bool = False   # P1.1 : trailing RANGE vs TREND
        self._ohlcv_1h = None          # D.1 : données 1h pour filtre multi-TF
        self._risk_manager = RiskManager(RiskParams())
        self._risk_manager_range: RiskManager | None = None   # initialisé après chargement config
        try:
            from utils.config import load_settings as _ls_wf
            _cfg_wf = _ls_wf()
            # Priorité : quant.asset_config.<symbol>.capital_usd > exchange.paper_capital_usd
            _ac_wf = _cfg_wf.get("quant", {}).get("asset_config", {}).get(self.symbol, {})
            self._capital = float(
                _ac_wf.get("capital_usd")
                or _cfg_wf.get("exchange", {}).get("paper_capital_usd", 10_000.0)
            )
        except Exception:
            self._capital = 10_000.0
        self._n_trades = 0
        self._wins = 0
        self._peak_capital = self._capital

    def ensure_fitted(self):  # noqa: C901
        now = time.time()
        # Refit si : jamais fitté | interval hebdo dépassé | SignalModel absent (retry 1h)
        _model_retry = (self._model is None
                        and self._regime is not None
                        and (now - self._last_fit_ts) > 3600)
        if self._regime is None or _model_retry or (now - self._last_fit_ts) > self._refit_interval_s:
            if _model_retry:
                # Recharger asset_config pour appliquer le bon timeframe avant le retry
                try:
                    from utils.config import load_settings
                    _qc = load_settings().get("quant", {})
                    _ac = _qc.get("asset_config", {}).get(self.symbol, {})
                    if _ac:
                        _new_tf = str(_ac.get("timeframe", self.timeframe))
                        _new_hd = int(_ac.get("history_days", self.history_days))
                        if _new_tf != self.timeframe or _new_hd != self.history_days:
                            logger.info(f"[config] _model_retry {self.symbol}: "
                                        f"timeframe {self.timeframe}→{_new_tf}, "
                                        f"history {self.history_days}→{_new_hd}")
                            self.timeframe = _new_tf
                            self.history_days = _new_hd
                            # Recalculer norm_window pour le nouveau timeframe
                            from quant.config import bars_per_day as _bpd2
                            _new_nw = int(_qc.get("norm_window_days", 30)) * _bpd2(_new_tf)
                            if _new_nw != self.cfg.norm_window:
                                logger.info(f"[config] _model_retry {self.symbol}: norm_window {self.cfg.norm_window}→{_new_nw}")
                                self.cfg.norm_window = _new_nw
                except Exception as exc:
                    logger.warning(f"[config] _model_retry reload failed: {exc}")
            self._refit()

    def _refit(self):
        logger.info(f"LiveRunner refit — fetch {self.history_days}d {self.symbol} {self.timeframe}")
        try:
            ohlcv = fetch_history(symbol=self.symbol, timeframe=self.timeframe,
                                  days=self.history_days, cache=True)
        except Exception as exc:
            logger.error(f"Fetch history failed: {exc}")
            if self._ohlcv is None:
                raise
            ohlcv = self._ohlcv
        if len(ohlcv) < 200:
            logger.error(f"Historique insuffisant ({len(ohlcv)} barres).")
            return
        self._ohlcv = ohlcv
        split = int(len(ohlcv) * self.train_fraction)
        train_idx = ohlcv.index[:split]
        feats_raw = compute_features(ohlcv)
        feats_norm = normalize_features(
            feats_raw, window=self.cfg.norm_window,
            columns=["log_return_1", "log_return_4", "log_return_24", "log_return_96",
                     "rsi_14", "macd_hist", "ema_cross", "roc_12",
                     "atr_pct", "adx_14", "dist_ma50", "volume_z_20", "vol_of_vol_20",
                     "vwap_dist_20", "bb_pct_b", "obv_proxy_20"],
        )
        feats_all = pd.concat([feats_raw, feats_norm], axis=1)
        self._feats_cache = feats_all
        self._feats_cache_ohlcv_len = len(ohlcv)
        self._regime = RegimeDetector(use_hmm=self.cfg.use_hmm).fit(feats_all.loc[train_idx])
        y = make_target_direction(ohlcv, horizon=self.cfg.horizon_bars)
        # B.3 Warmup : exclure les premières norm_window barres pour SignalModel
        # (quantile-normalisation instable sur les premières barres — 3/3 IA)
        warmup_cutoff = feats_all.index[min(self.cfg.norm_window, len(feats_all) - 1)]
        train_sm_idx = train_idx[train_idx >= warmup_cutoff]
        X_train = feats_all.loc[train_sm_idx, list(self.cfg.feature_cols)]
        # Drop colonnes 100% NaN (ex: volume_z_20_q pour métaux/forex sans données de volume)
        _nan_cols = [c for c in X_train.columns if X_train[c].isna().all()]
        if _nan_cols:
            logger.warning(f"_refit: {len(_nan_cols)} feature(s) 100% NaN ignorée(s): {_nan_cols}")
            X_train = X_train.drop(columns=_nan_cols)
            self._active_feature_cols = [c for c in self.cfg.feature_cols if c not in _nan_cols]
        else:
            self._active_feature_cols = list(self.cfg.feature_cols)
        y_train = y.loc[train_sm_idx]
        valid = X_train.notna().all(axis=1) & y_train.notna()
        if valid.sum() < 100:
            logger.warning("Données insuffisantes pour SignalModel — P(up)=0.5 fixe.")
            self._model = None
        elif y_train.loc[valid].nunique() < 2:
            logger.warning(
                f"SignalModel: y_train a une seule classe "
                f"({y_train.loc[valid].unique()}) — signal directionnel indisponible."
            )
            self._model = None
        else:
            try:
                _sm_cfg = self.cfg.__dict__ if hasattr(self.cfg, '__dict__') else {}
                _sm_C       = float(getattr(self.cfg, 'signal_model_C',       5.0))
                _sm_cvfolds = int(getattr(self.cfg, 'signal_model_cv_folds',  3))
                _sm_calib   = bool(getattr(self.cfg, 'signal_model_calibrate', True))
                self._model = SignalModel(
                    feature_cols=list(self._active_feature_cols),
                    C=_sm_C,
                    cv_folds=_sm_cvfolds,
                    use_calibration=_sm_calib,
                ).fit(X_train.loc[valid], y_train.loc[valid])
            except Exception as exc:
                logger.error(f"SignalModel fit failed: {exc}")
                self._model = None
        self._last_fit_ts = time.time()
        self._model_fit_at = datetime.utcnow().isoformat()
        # D.1 Fetch données 1h pour filtre multi-timeframe (Grok + GPT + DeepSeek)
        try:
            ohlcv_1h = fetch_history(symbol=self.symbol, timeframe="1h",
                                     days=self.history_days + 10, cache=True)
            self._ohlcv_1h = ohlcv_1h
            logger.info(f"Données 1h chargées : {len(ohlcv_1h)} barres")
        except Exception as exc:
            logger.warning(f"Fetch 1h history failed: {exc} — filtre 1h désactivé")
            self._ohlcv_1h = None
        logger.info(f"Refit OK — {split} barres train | {len(ohlcv)-split} test")

    def _append_latest_bar(self):
        # Fetch assez de barres pour couvrir les éventuels gaps si le cycle
        # tourne moins souvent que le timeframe (ex: 15m cycle + 5m TF).
        tf_secs = _TF_SECONDS.get(self.timeframe, 300)
        limit = max(3, 1800 // tf_secs + 2)  # couvre ~30 min de gaps
        try:
            new = fetch_ohlcv(symbol=self.symbol, timeframe=self.timeframe, limit=limit)
        except Exception as exc:
            logger.warning(f"Fetch latest bar failed: {exc}")
            return False
        if new.empty or self._ohlcv is None:
            return False
        if len(new) >= 2:
            new = new.iloc[:-1]  # drop barre en cours de formation
        combined = pd.concat([self._ohlcv, new])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        if len(combined) > _MAX_HISTORY_BARS():
            combined = combined.iloc[-_MAX_HISTORY_BARS():]
        is_new = len(combined) > len(self._ohlcv)
        self._ohlcv = combined
        # D.1 Mise à jour des données 1h (glissement de la fenêtre)
        if self._ohlcv_1h is not None:
            try:
                new_1h = fetch_ohlcv(symbol=self.symbol, timeframe="1h", limit=3)
                if not new_1h.empty and len(new_1h) >= 2:
                    new_1h = new_1h.iloc[:-1]
                combined_1h = pd.concat([self._ohlcv_1h, new_1h])
                combined_1h = combined_1h[~combined_1h.index.duplicated(keep="last")].sort_index()
                if len(combined_1h) > 2000:
                    combined_1h = combined_1h.iloc[-2000:]
                self._ohlcv_1h = combined_1h
            except Exception:
                pass
        return is_new

    def step(self, trigger="scheduled"):
        t0 = time.time()
        self.ensure_fitted()
        self._append_latest_bar()
        ohlcv = self._ohlcv
        if ohlcv is None or len(ohlcv) < 50:
            return self._empty_state(trigger, "historique_insuffisant")

        n_new_bars = len(ohlcv) - self._feats_cache_ohlcv_len
        _norm_cols = ["log_return_1", "log_return_4", "log_return_24", "log_return_96",
                      "rsi_14", "macd_hist", "ema_cross", "roc_12",
                      "atr_pct", "adx_14", "dist_ma50", "volume_z_20", "vol_of_vol_20",
                      "vwap_dist_20", "bb_pct_b", "obv_proxy_20"]
        if (self._feats_cache is not None
                and 0 < n_new_bars <= 3
                and len(self._feats_cache) >= self.cfg.norm_window):
            # Incremental update: recompute only for the new tail bars.
            # ATR/ADX need ~50 bars of context; norm needs norm_window bars of context.
            _ctx = self.cfg.norm_window + 60
            ohlcv_tail = ohlcv.iloc[-_ctx:]
            feats_raw_tail = compute_features(ohlcv_tail)
            feats_norm_tail = normalize_features(
                feats_raw_tail, window=self.cfg.norm_window, columns=_norm_cols)
            feats_tail = pd.concat([feats_raw_tail, feats_norm_tail], axis=1)
            # Merge: drop the tail of the cache that overlaps and append new rows
            new_idx = feats_tail.index[-n_new_bars:]
            feats_all = pd.concat([
                self._feats_cache[~self._feats_cache.index.isin(new_idx)],
                feats_tail.loc[new_idx],
            ])
            feats_raw = feats_all[[c for c in feats_all.columns if not c.endswith("_q")]]
        else:
            feats_raw = compute_features(ohlcv)
            feats_norm = normalize_features(
                feats_raw, window=self.cfg.norm_window, columns=_norm_cols)
            feats_all = pd.concat([feats_raw, feats_norm], axis=1)
        self._feats_cache = feats_all
        self._feats_cache_ohlcv_len = len(ohlcv)

        regime_series = self._regime.predict(feats_all) if self._regime else pd.Series([np.nan])
        regime_val = regime_series.iloc[-1] if len(regime_series) else np.nan
        regime_trending = bool(regime_val == 1.0) if pd.notna(regime_val) else False
        regime_ranging  = bool(regime_val == 0.5) if pd.notna(regime_val) else False

        prob_up = None
        if self._model is not None:
            try:
                ps = self._model.predict_proba(feats_all[self._active_feature_cols])
                v = ps.iloc[-1]
                prob_up = float(v) if pd.notna(v) else None
            except Exception:
                prob_up = None

        decision = decide(
            probability_up=prob_up,
            regime_trending=regime_trending,
            upper_threshold=self.cfg.p_up_threshold,
            lower_threshold=self.cfg.p_dn_threshold,
        )

        # Stratégie mean-reverting en régime RANGE
        # Désactivée si range_enabled: false (consensus 3 IA : R:R=1.0 = EV négative après frais)
        _qcfg_range = _wf_qcfg()
        _range_enabled = getattr(_qcfg_range, "range_enabled", True)
        if decision.action == Action.FLAT and regime_ranging and _range_enabled:
            qcfg = _wf_qcfg()
            _bb_raw  = feats_raw["bb_pct_b"].iloc[-1]   if "bb_pct_b"    in feats_raw.columns else None
            _vwap_raw= feats_raw["vwap_dist_20"].iloc[-1] if "vwap_dist_20" in feats_raw.columns else None
            bb_pb    = float(_bb_raw.item()   if hasattr(_bb_raw,  'item') else _bb_raw)   if _bb_raw   is not None else None
            vwap_d   = float(_vwap_raw.item() if hasattr(_vwap_raw,'item') else _vwap_raw) if _vwap_raw is not None else None
            decision = decide_range(
                bb_pct_b=bb_pb  if bb_pb   is not None and not np.isnan(bb_pb)   else None,
                vwap_dist=vwap_d if vwap_d is not None and not np.isnan(vwap_d) else None,
                prob_up=prob_up,
                bb_long_threshold=getattr(qcfg, "range_bb_long_threshold",  0.10),
                bb_short_threshold=getattr(qcfg, "range_bb_short_threshold", 0.90),
                vwap_conf=getattr(qcfg, "range_vwap_conf", 0.30),
            )

        latest_bar = ohlcv.iloc[-1]
        bar_ts = str(ohlcv.index[-1])
        _close_raw = latest_bar["close"]
        close_price = float(_close_raw.item() if hasattr(_close_raw, 'item') else _close_raw)
        atr_raw = feats_raw["atr_14"].iloc[-1]
        _atr_scalar = atr_raw.item() if hasattr(atr_raw, 'item') else atr_raw
        atr_14 = float(_atr_scalar) if pd.notna(_atr_scalar) else None

        # ATR 1h pour SL/TP — horizon=48×5m=4h, utiliser ATR sur barres 1h
        # évite le mismatch ATR-5m (trop serré) vs prédiction 4h
        atr_1h = None
        if self._ohlcv_1h is not None and len(self._ohlcv_1h) >= 15:
            try:
                h1 = self._ohlcv_1h
                hl = h1["high"] - h1["low"]
                hc = (h1["high"] - h1["close"].shift(1)).abs()
                lc = (h1["low"]  - h1["close"].shift(1)).abs()
                tr_1h = pd.concat([hl, hc, lc], axis=1).max(axis=1)
                atr_1h = float(tr_1h.rolling(14, min_periods=5).mean().iloc[-1])
                if not pd.notna(atr_1h) or atr_1h <= 0:
                    atr_1h = None
            except Exception:
                atr_1h = None
        # Fallback : ATR 5m × sqrt(12) ≈ ATR 1h si données 1h indisponibles
        atr_for_risk = atr_1h if atr_1h else (atr_14 * (12 ** 0.5) if atr_14 else None)

        # ── Gestion position existante ────────────────────────────────────────
        trade_result = None
        pre_close_position = self._position
        if self._position is not None:
            _trail_mgr = (
                self._risk_manager_range
                if self._position_is_range and self._risk_manager_range
                else self._risk_manager
            )
            self._position = _trail_mgr.update_trailing(self._position, close_price)
            exit_signal = self._risk_manager.should_exit(self._position, close_price)
            # Time-based exit conditionnel : 8 barres max ET trade en perte (B.2 — 3/3 IA)
            # Si le trade est gagnant, le laisser courir (TP/SL gèrent la sortie)
            if not exit_signal and self._position_entry_ts:
                try:
                    # Durée d'une barre en secondes (dynamique selon self.timeframe)
                    bar_secs = _TF_SECONDS.get(self.timeframe, 300)
                    elapsed_bars = int(
                        (ohlcv.index[-1] - pd.Timestamp(self._position_entry_ts)).total_seconds() // bar_secs
                    )
                    if elapsed_bars >= 8:
                        if self._position.side == "long":
                            unrealized = (close_price - self._position.entry_price) / self._position.entry_price
                        else:
                            unrealized = (self._position.entry_price - close_price) / self._position.entry_price
                        if unrealized <= 0.0:
                            exit_signal = "time_exit_8bars_loss"
                except Exception:
                    pass
            if exit_signal:
                trade_result = self._close_position(close_price, exit_signal)
                self._position = None
                self._position_is_range = False   # P1.1 : reset après fermeture

        # ── Filtre multi-timeframe 1h (D.1 — 3/3 IA) ─────────────────────────────
        # Veto si tendance horaire contra-directionnelle : SMA20 vs SMA50 sur 1h
        # Appliqué à TOUS les signaux : trend ET range (mean-reversion sur tendance
        # baissière = continuer à perdre → filtre directionnel obligatoire)
        _is_range_signal = decision.reason.startswith("range_mean_revert")
        trend_1h_veto = False
        if decision.action in (Action.LONG, Action.SHORT) and self._ohlcv_1h is not None and len(self._ohlcv_1h) >= 50:
            c1h = self._ohlcv_1h["close"]
            sma20_1h = c1h.rolling(20, min_periods=20).mean().iloc[-1]
            sma50_1h = c1h.rolling(50, min_periods=50).mean().iloc[-1]
            if pd.notna(sma20_1h) and pd.notna(sma50_1h):
                trend_1h_up = bool(sma20_1h > sma50_1h)
                if decision.action == Action.LONG and not trend_1h_up:
                    trend_1h_veto = True   # LONG rejeté : tendance 1h baissière (trend ET range)
                elif decision.action == Action.SHORT and trend_1h_up:
                    trend_1h_veto = True   # SHORT rejeté : tendance 1h haussière (trend ET range)

        # ── Nouvelle entrée ───────────────────────────────────────────────────
        # Filtre volume : n'entrer que si volume >= 70% de la médiane des 20 dernières barres
        # Appliqué à tous les actifs crypto (volume Binance fiable pour les perps)
        _CRYPTO_ASSETS = {
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
            "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
        }
        vol_ratio = 1.0
        if self.symbol in _CRYPTO_ASSETS and len(ohlcv) >= 21:
            vol_med = float(ohlcv["volume"].iloc[-21:-1].median())
            vol_ratio = float(ohlcv["volume"].iloc[-1]) / (vol_med + 1e-9)
        # ── Filtre corrélation crypto (consensus Grok + GPT + DeepSeek) ──────────────
        # Crypto perps corrélation >0.80 en phase de marché — limiter à 3 positions
        # simultanées dans la même direction pour réduire le risque de concentration.
        _crypto_corr_veto = False
        _MAX_CORR_POSITIONS = 3   # au-delà de 3 cryptos longs/shorts = concentration excessive
        if self.symbol in _CRYPTO_ASSETS and decision.action in (Action.LONG, Action.SHORT):
            _open_same_dir = sum(
                1 for _sym, _r in _runners.items()
                if _sym != self.symbol
                and _sym in _CRYPTO_ASSETS
                and _r._position is not None
                and _r._position.side == decision.action.value
            )
            if _open_same_dir >= _MAX_CORR_POSITIONS:
                _crypto_corr_veto = True
                logger.info(
                    f"[{self.symbol}] crypto corr veto — "
                    f"{decision.action.value.upper()} bloqué : {_open_same_dir} positions corrélées déjà ouvertes"
                )

        _entry_opened_this_cycle = False
        if (self._position is None
                and trigger != "monitor"          # pas d'entrée en mode monitoring
                and not self._risk_manager.is_paused(time.time())
                and decision.action in (Action.LONG, Action.SHORT)
                and atr_14 and atr_14 > 0
                and atr_for_risk and atr_for_risk > 0
                and vol_ratio >= 0.70
                and not trend_1h_veto            # D.1 filtre 1h
                and not _crypto_corr_veto):      # B — filtre corrélation crypto
            side = decision.action.value
            is_range_trade = decision.reason.startswith("range_mean_revert")
            # Utiliser le RiskManager range (SL/TP/fraction réduits) pour les trades mean-reverting
            risk_mgr = self._risk_manager_range if (is_range_trade and self._risk_manager_range) else self._risk_manager
            try:
                pos = risk_mgr.compute_position(
                    side=side, entry_price=close_price,
                    atr_value=atr_for_risk, capital=self._capital,
                )
                self._capital -= pos.size_units * close_price * 0.0005
                self._position = pos
                self._position_entry_ts = bar_ts
                self._position_is_range = is_range_trade   # P1.1 : trailing correct
                self._n_trades += 1
                _entry_opened_this_cycle = True
                mode_label = "RANGE-MR" if is_range_trade else "TREND"
                logger.info(f"ENTRÉE {side.upper()} [{mode_label}] @ {close_price:.2f} | SL={pos.stop_loss:.2f} TP={pos.take_profit:.2f}")
            except Exception as exc:
                logger.warning(f"Entrée ignorée: {exc}")

        pos = self._position
        # Cycle de maintenance : position déjà ouverte, pas de nouvelle entrée, pas de sortie
        # → stocker action='hold' pour ne pas polluer le tableau des trades du dashboard
        _persist_action = decision.action.value
        if (pos is not None and not _entry_opened_this_cycle and trade_result is None):
            _persist_action = "hold"
        elif (not _entry_opened_this_cycle and pos is None
              and decision.action in (Action.LONG, Action.SHORT)):
            # Signal généré mais entrée bloquée par un filtre (1h veto, vol, corr, range_disabled)
            # Ne pas stocker "long"/"short" : aucune position ouverte → dashboard trompeur
            _persist_action = "flat"
        self._persist(
            asset=self.symbol, bar_ts=bar_ts, close_price=close_price,
            regime=round(float(regime_val.item() if hasattr(regime_val, 'item') else regime_val)*2)/2.0 if pd.notna(regime_val) else None,
            prob_up=prob_up, action=_persist_action, reason=decision.reason,
            atr_14=atr_14, position_side=pos.side if pos else None,
            entry_price=pos.entry_price if pos else None,
            sl_price=pos.stop_loss if pos else None,
            tp_price=pos.take_profit if pos else None,
            position_size_usd=(trade_result.get("position_size_usd") if trade_result else None)
                or ((pre_close_position.entry_price * pre_close_position.size_units) if pre_close_position else None)
                or ((pos.entry_price * pos.size_units) if pos else None),
            realized_pnl=trade_result.get("pnl_abs") if trade_result else None,
        )

        cycle_ms = int((time.time() - t0) * 1000)
        regime_label = "TREND" if regime_trending else ("RANGE" if regime_ranging else "PANIC")
        logger.info(
            f"[V2] {bar_ts[:16]} | {regime_label} | "
            f"P(up)={f'{prob_up:.3f}' if prob_up is not None else 'N/A'} | "
            f"{decision.action.value.upper()}({decision.reason}) | capital={self._capital:.0f}$ | {cycle_ms}ms"
        )
        return {
            "cycle_id": f"v2_{int(time.time())}",
            "timestamp": datetime.utcnow().isoformat(),
            "asset": self.symbol,
            "bar_ts": bar_ts,
            "close_price": close_price,
            "regime_trending": regime_trending,
            "regime": round(float(regime_val.item() if hasattr(regime_val, 'item') else regime_val)*2)/2.0 if pd.notna(regime_val) else None,
            "prob_up": round(prob_up, 4) if prob_up is not None else None,
            "action": decision.action.value,
            "reason": decision.reason,
            "atr_14": atr_14,
            "position": {
                "side": pos.side, "entry_price": pos.entry_price,
                "sl": pos.stop_loss, "tp": pos.take_profit,
            } if pos else None,
            "trade_result": trade_result,
            "capital": round(self._capital, 2),
            "n_trades": self._n_trades,
            "cycle_duration_ms": cycle_ms,
            "errors": [],
        }

    def _close_position(self, price, reason):
        pos = self._position
        if pos is None:
            return {}
        position_size_usd = pos.entry_price * pos.size_units
        if pos.side == "long":
            gross = (price - pos.entry_price) * pos.size_units
        else:
            gross = (pos.entry_price - price) * pos.size_units
        fees = pos.size_units * price * 0.0005
        net = gross - fees
        _capital_before = self._capital   # capture avant maj pour KS portfolio-relatif
        self._capital += net
        self._peak_capital = max(self._peak_capital, self._capital)
        pnl_pct = net / (pos.entry_price * pos.size_units)   # position-relative (display)
        ks_pnl_pct = net / _capital_before if _capital_before > 0 else pnl_pct  # portfolio-relative (KS)
        if net > 0:
            self._wins += 1
        self._position_entry_ts = None   # reset après fermeture
        self._risk_manager.record_trade_pnl_pct(ks_pnl_pct, time.time())
        logger.info(f"SORTIE {reason} @ {price:.2f} | PnL={net:+.2f}$ ({pnl_pct:+.2%})")
        return {"exit_price": price, "pnl_abs": round(net, 2),
            "pnl_pct": round(pnl_pct, 4), "exit_reason": reason,
            "entry_price": pos.entry_price, "position_size_usd": round(position_size_usd, 2),
            "side": pos.side}

    def _persist(self, **kwargs):
        try:
            from storage.database import write_v2_state, append_v2_equity, get_connection
            from datetime import datetime as _dt
            write_v2_state(
                asset=kwargs["asset"],
                bar_ts=kwargs["bar_ts"],
                close_price=kwargs["close_price"],
                regime=kwargs.get("regime"),
                prob_up=kwargs.get("prob_up"),
                action=kwargs["action"],
                reason=kwargs["reason"],
                atr_14=kwargs.get("atr_14"),
                position_side=kwargs.get("position_side"),
                entry_price=kwargs.get("entry_price"),
                sl_price=kwargs.get("sl_price"),
                tp_price=kwargs.get("tp_price"),
                capital=round(self._capital, 2),
                model_fit_at=self._model_fit_at,
            )
            append_v2_equity(ts=kwargs["bar_ts"], asset=kwargs["asset"],
                             equity=round(self._capital, 2), action=kwargs["action"],
                             close_price=kwargs["close_price"])
            # Ligne par-actif dans v2_state (id basé sur hash) — pour Direction V2 multi-asset
            _asset = kwargs["asset"]
            _asset_id = abs(hash(_asset)) % 999_900 + 100
            with get_connection() as _conn:
                _conn.execute(
                    """
                    INSERT INTO v2_state
                        (id, updated_at, asset, bar_ts, close_price, regime, prob_up,
                         action, reason, atr_14, capital, model_fit_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        updated_at=excluded.updated_at, asset=excluded.asset,
                        bar_ts=excluded.bar_ts, close_price=excluded.close_price,
                        regime=excluded.regime, prob_up=excluded.prob_up,
                        action=excluded.action, reason=excluded.reason,
                        atr_14=excluded.atr_14, capital=excluded.capital,
                        model_fit_at=excluded.model_fit_at
                    """,
                    (_asset_id, _dt.utcnow().isoformat(), _asset,
                     kwargs.get("bar_ts"), kwargs.get("close_price"),
                     kwargs.get("regime"), kwargs.get("prob_up"),
                     kwargs.get("action"), kwargs.get("reason"),
                     kwargs.get("atr_14"), round(self._capital, 2), self._model_fit_at)
                )
                _conn.commit()
                # v2_decisions : historique complet par cycle
                _conn.execute("""
                    CREATE TABLE IF NOT EXISTS v2_decisions (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts           TEXT    NOT NULL,
                        asset        TEXT    NOT NULL,
                        bar_ts       TEXT,
                        close_price  REAL,
                        regime       TEXT,
                        prob_up      REAL,
                        action       TEXT,
                        reason       TEXT,
                        atr_14       REAL,
                        sl_price     REAL,
                        tp_price     REAL,
                        capital      REAL,
                        model_fit_at TEXT,
                        position_size_usd REAL,
                        realized_pnl REAL
                    )
                """)
                _v2_cols = {row[1] for row in _conn.execute("PRAGMA table_info(v2_decisions)")}
                if "position_size_usd" not in _v2_cols:
                    _conn.execute("ALTER TABLE v2_decisions ADD COLUMN position_size_usd REAL")
                if "realized_pnl" not in _v2_cols:
                    _conn.execute("ALTER TABLE v2_decisions ADD COLUMN realized_pnl REAL")
                _regime_int = kwargs.get("regime")
                _regime_txt = "TREND" if _regime_int == 1.0 else ("PANIC" if _regime_int == 0.0 else "RANGE")
                _conn.execute(
                    """INSERT INTO v2_decisions
                       (ts, asset, bar_ts, close_price, regime, prob_up, action, reason,
                        atr_14, sl_price, tp_price, capital, model_fit_at,
                        position_size_usd, realized_pnl)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (_dt.utcnow().isoformat(), _asset,
                     kwargs.get("bar_ts"), kwargs.get("close_price"),
                     _regime_txt, kwargs.get("prob_up"),
                     kwargs.get("action"), kwargs.get("reason"),
                     kwargs.get("atr_14"),
                     kwargs.get("sl_price"), kwargs.get("tp_price"),
                     round(self._capital, 2), self._model_fit_at,
                     kwargs.get("position_size_usd"), kwargs.get("realized_pnl"))
                )
                _conn.commit()
        except Exception as exc:
            logger.warning(f"Persist V2 state failed: {exc}")

    def _empty_state(self, trigger, reason):
        return {"cycle_id": f"v2_{int(time.time())}", "timestamp": datetime.utcnow().isoformat(),
                "asset": self.symbol, "action": "flat", "reason": reason,
                "errors": [reason], "trigger": trigger}

    @property
    def win_rate(self):
        return self._wins / self._n_trades if self._n_trades else 0.0

    @property
    def drawdown_pct(self):
        return (self._capital - self._peak_capital) / self._peak_capital if self._peak_capital else 0.0


# ===========================================================
# REGISTRE PAR ACTIF + API PUBLIQUE
# ===========================================================

_runners: dict[str, "LiveRunner"] = {}


def _load_asset_v2_config(asset: str) -> dict:
    """Charge la section v2_risk: du fichier config/assets/{slug}.yaml.

    Retourne un dict vide si le fichier n'existe pas ou si v2_risk est absent.
    Permet de surcharger les params risk par actif sans toucher settings.yaml.
    """
    slug = asset.replace("/", "_")
    from pathlib import Path
    import yaml as _yaml
    path = Path(__file__).parent.parent / "config" / "assets" / f"{slug}.yaml"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = _yaml.safe_load(f) or {}
        return data.get("v2_risk", {})
    except Exception as exc:
        logger.warning(f"Erreur lecture config assets/{slug}.yaml: {exc}")
        return {}


def _runner_fingerprint(qcfg: dict) -> tuple:
    """Empreinte des paramètres structurels — changement → recréation du runner."""
    return (
        qcfg.get("timeframe", _DEFAULT_TF()),
        int(qcfg.get("history_days", _HISTORY_DAYS())),
        bool(qcfg.get("use_hmm", False)),
        int(qcfg.get("horizon_bars", 4)),
        float(qcfg.get("train_fraction", _TRAIN_FRACTION())),
    )


def _get_runner(asset: str) -> "LiveRunner":
    """Retourne (ou crée) le LiveRunner pour cet actif.

    Relit settings.yaml à chaque appel :
    - paramètres *structurels* changés (timeframe, history_days, use_hmm,
      horizon_bars, train_fraction) → recréation + refit forcé au prochain cycle
    - seuls seuils P(up)/P(dn) ou refit_interval changés → hot-reload sans recréation.
    """
    global _runners
    try:
        from utils.config import load_settings
        cfg = load_settings()
        qcfg = cfg.get("quant", {})
        _ac_debug = qcfg.get("asset_config", {})
        if not _ac_debug:
            logger.warning(f"[_get_runner] asset_config manquant dans quant (keys={list(qcfg.keys())})")
    except Exception as exc:
        logger.warning(f"[_get_runner] load_settings failed: {exc}")
        cfg = {}
        qcfg = {}

    # Merge per-asset quant overrides (timeframe, history_days)
    _asset_qcfg = qcfg.get("asset_config", {}).get(asset, {})
    _merged_qcfg = {**qcfg, **_asset_qcfg}
    fp = _runner_fingerprint(_merged_qcfg)
    existing = _runners.get(asset)

    if existing is not None:
        existing_fp = (
            existing.timeframe,
            int(existing.history_days),
            bool(existing.cfg.use_hmm),
            int(existing.cfg.horizon_bars),
            float(existing.train_fraction),
        )
        if existing_fp == fp:
            # Hot-reload des seuils et de l'intervalle refit (aucun refit requis)
            _thr_ov = qcfg.get("asset_thresholds", {}).get(asset, {})
            existing.cfg.p_up_threshold = float(_thr_ov.get("p_up_threshold", qcfg.get("p_up_threshold", 0.58)))
            existing.cfg.p_dn_threshold = float(_thr_ov.get("p_dn_threshold", qcfg.get("p_dn_threshold", 0.42)))
            existing._refit_interval_s = int(qcfg.get("refit_interval_hours", 168)) * 3600
            existing.cfg.signal_model_C = float(qcfg.get("signal_model_C", 5.0))
            existing.cfg.signal_model_cv_folds = int(qcfg.get("signal_model_cv_folds", 3))
            existing.cfg.signal_model_calibrate = bool(qcfg.get("signal_model_calibrate", True))
            # Hot-reload des paramètres risk per-asset (v2_risk) — permet aux changements
            # admin d'être pris en compte sans restart container.
            _av2 = _load_asset_v2_config(asset)
            if _av2:
                p = existing._risk_manager.params
                if "stop_loss_atr_mult"   in _av2: p.stop_loss_atr_mult   = float(_av2["stop_loss_atr_mult"])
                if "take_profit_atr_mult" in _av2: p.take_profit_atr_mult = float(_av2["take_profit_atr_mult"])
                if "fraction_per_trade"   in _av2: p.fraction_per_trade   = float(_av2["fraction_per_trade"])
            return existing
        logger.info(
            f"[config] Paramètres changés pour {asset} "
            f"({existing_fp} → {fp}) — recréation du runner"
        )

    _thr_ov = qcfg.get("asset_thresholds", {}).get(asset, {})
    # Calculer norm_window en fonction du timeframe RÉEL de l'asset (pas le global 5m)
    _asset_tf = _merged_qcfg.get("timeframe", _DEFAULT_TF())
    _norm_window_days = qcfg.get("norm_window_days", 30)
    from quant.config import bars_per_day as _bpd
    _norm_window = _norm_window_days * _bpd(_asset_tf)
    pipe_cfg = PipelineConfig(
        use_hmm=qcfg.get("use_hmm", False),
        horizon_bars=qcfg.get("horizon_bars", 4),
        norm_window=_norm_window,
        p_up_threshold=float(_thr_ov.get("p_up_threshold", qcfg.get("p_up_threshold", 0.58))),
        p_dn_threshold=float(_thr_ov.get("p_dn_threshold", qcfg.get("p_dn_threshold", 0.42))),
        initial_capital=cfg.get("exchange", {}).get("paper_capital_usd", 10_000.0),
    )
    # signal_model params — injectés via setattr pour compatibilité si champs absents du dataclass
    pipe_cfg.signal_model_C        = float(qcfg.get("signal_model_C", 5.0))
    pipe_cfg.signal_model_cv_folds = int(qcfg.get("signal_model_cv_folds", 3))
    pipe_cfg.signal_model_calibrate = bool(qcfg.get("signal_model_calibrate", False))
    runner = LiveRunner(
        symbol=asset,
        timeframe=_merged_qcfg.get("timeframe", _DEFAULT_TF()),
        history_days=_merged_qcfg.get("history_days", _HISTORY_DAYS()),
        train_fraction=_merged_qcfg.get("train_fraction", _TRAIN_FRACTION()),
        config=pipe_cfg,
        refit_interval_s=int(_merged_qcfg.get("refit_interval_hours", 168)) * 3600,
    )

    # Restaurer le capital live depuis la dernière equity persistée (si disponible)
    # pour éviter un reset à 10_000$ après restart du process/container.
    try:
        from storage.database import get_connection
        with get_connection() as _conn:
            _row = _conn.execute(
                "SELECT equity FROM v2_equity WHERE asset = ? ORDER BY id DESC LIMIT 1",
                (asset,),
            ).fetchone()
        if _row and _row["equity"] is not None:
            _restored_cap = float(_row["equity"])
            runner._capital = _restored_cap
            runner._peak_capital = max(runner._peak_capital, _restored_cap)
            logger.info(f"[state] {asset} capital restauré depuis DB: {_restored_cap:.2f}$")
    except Exception as exc:
        logger.warning(f"[state] restore capital failed for {asset}: {exc}")

    # Override des paramètres risk par actif depuis config/assets/{slug}.yaml → v2_risk:
    asset_v2 = _load_asset_v2_config(asset)
    if asset_v2:
        p = runner._risk_manager.params
        if "stop_loss_atr_mult"    in asset_v2: p.stop_loss_atr_mult    = float(asset_v2["stop_loss_atr_mult"])
        if "take_profit_atr_mult"  in asset_v2: p.take_profit_atr_mult  = float(asset_v2["take_profit_atr_mult"])
        if "fraction_per_trade"    in asset_v2: p.fraction_per_trade    = float(asset_v2["fraction_per_trade"])
        logger.info(f"[config] {asset} v2_risk override: SL×{p.stop_loss_atr_mult} TP×{p.take_profit_atr_mult} f={p.fraction_per_trade:.4f}")
        # RiskManager dédié au mode mean-reverting RANGE (SL/TP réduits)
        qc = _wf_qcfg()
        sl_r  = float(asset_v2.get("range_sl_atr_mult",   getattr(qc, "range_sl_atr_mult",   1.5)))
        tp_r  = float(asset_v2.get("range_tp_atr_mult",   getattr(qc, "range_tp_atr_mult",   1.5)))
        fmult = float(asset_v2.get("range_fraction_mult", getattr(qc, "range_fraction_mult", 0.5)))
        range_params = RiskParams(
            stop_loss_atr_mult=sl_r,
            take_profit_atr_mult=tp_r,
            fraction_per_trade=p.fraction_per_trade * fmult,
        )
        runner._risk_manager_range = RiskManager(range_params)
    else:
        # Pas de config par actif — range manager basé sur les defaults globaux
        qc = _wf_qcfg()
        base_f = runner._risk_manager.params.fraction_per_trade
        range_params = RiskParams(
            stop_loss_atr_mult=getattr(qc, "range_sl_atr_mult", 1.5),
            take_profit_atr_mult=getattr(qc, "range_tp_atr_mult", 1.5),
            fraction_per_trade=base_f * getattr(qc, "range_fraction_mult", 0.5),
        )
        runner._risk_manager_range = RiskManager(range_params)

    _runners[asset] = runner
    return _runners[asset]


def run_cycle(asset: str = "BTC/USDT", trigger: str = "scheduled") -> dict:
    """Point d'entrée principal du daemon. Appelé toutes les 15min par main.py."""
    from utils.cycle_lock import try_acquire, release as _lock_release
    acquired = try_acquire(owner=f"v2_{trigger}", asset=asset)
    if not acquired:
        logger.warning(f"[{asset}] Cycle déjà en cours — ignoré (trigger={trigger}).")
        return {
            "asset": asset, "action": "flat", "reason": "cycle_locked",
            "errors": ["cycle_locked"],
            "cycle_id": f"v2_skip_{int(time.time())}",
            "timestamp": datetime.utcnow().isoformat(),
        }
    try:
        runner = _get_runner(asset)
        return runner.step(trigger=trigger)
    finally:
        _lock_release(asset=asset)
