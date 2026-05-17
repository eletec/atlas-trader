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
from quant.strategy import Action, decide

_DEFAULT_SYMBOL = "BTC/USDT"
_DEFAULT_TF = "5m"    # settings.yaml : timeframe 5m (loop 300s)
_HISTORY_DAYS = 90
_TRAIN_FRACTION = 0.70
_REFIT_INTERVAL_S = 7 * 86400
_MAX_HISTORY_BARS = 90 * 96

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
        self._refit_interval_s = refit_interval_s if refit_interval_s is not None else _REFIT_INTERVAL_S
        self._ohlcv = None
        self._regime = None
        self._model = None
        self._last_fit_ts = 0.0
        self._model_fit_at = None
        self._position = None
        self._position_entry_ts = None
        self._ohlcv_1h = None          # D.1 : données 1h pour filtre multi-TF
        self._risk_manager = RiskManager(RiskParams())
        self._capital = 10_000.0
        self._n_trades = 0
        self._wins = 0
        self._peak_capital = self._capital

    def ensure_fitted(self):  # noqa: C901
        now = time.time()
        if self._regime is None or (now - self._last_fit_ts) > self._refit_interval_s:
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
            columns=["log_return_1", "log_return_4", "log_return_24",
                     "atr_pct", "adx_14", "dist_ma50", "volume_z_20", "vol_of_vol_20",
                     "vwap_dist_20", "bb_pct_b", "obv_proxy_20"],
        )
        feats_all = pd.concat([feats_raw, feats_norm], axis=1)
        self._regime = RegimeDetector(use_hmm=self.cfg.use_hmm).fit(feats_all.loc[train_idx])
        y = make_target_direction(ohlcv, horizon=self.cfg.horizon_bars)
        # B.3 Warmup : exclure les premières norm_window barres pour SignalModel
        # (quantile-normalisation instable sur les premières barres — 3/3 IA)
        warmup_cutoff = feats_all.index[min(self.cfg.norm_window, len(feats_all) - 1)]
        train_sm_idx = train_idx[train_idx >= warmup_cutoff]
        X_train = feats_all.loc[train_sm_idx, list(self.cfg.feature_cols)]
        y_train = y.loc[train_sm_idx]
        valid = X_train.notna().all(axis=1) & y_train.notna()
        if valid.sum() < 100:
            logger.warning("Données insuffisantes pour SignalModel — P(up)=0.5 fixe.")
            self._model = None
        else:
            try:
                self._model = SignalModel(feature_cols=list(self.cfg.feature_cols)).fit(
                    X_train.loc[valid], y_train.loc[valid]
                )
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
        if len(combined) > _MAX_HISTORY_BARS:
            combined = combined.iloc[-_MAX_HISTORY_BARS:]
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

        feats_raw = compute_features(ohlcv)
        feats_norm = normalize_features(
            feats_raw, window=self.cfg.norm_window,
            columns=["log_return_1", "log_return_4", "log_return_24",
                     "atr_pct", "adx_14", "dist_ma50", "volume_z_20", "vol_of_vol_20",
                     "vwap_dist_20", "bb_pct_b", "obv_proxy_20"],
        )
        feats_all = pd.concat([feats_raw, feats_norm], axis=1)

        regime_series = self._regime.predict(feats_all) if self._regime else pd.Series([np.nan])
        regime_val = regime_series.iloc[-1] if len(regime_series) else np.nan
        regime_trending = bool(regime_val == 1.0) if pd.notna(regime_val) else False

        prob_up = None
        if self._model is not None:
            try:
                ps = self._model.predict_proba(feats_all[list(self.cfg.feature_cols)])
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

        latest_bar = ohlcv.iloc[-1]
        bar_ts = str(ohlcv.index[-1])
        close_price = float(latest_bar["close"])
        atr_raw = feats_raw["atr_14"].iloc[-1]
        atr_14 = float(atr_raw) if pd.notna(atr_raw) else None

        # ── Gestion position existante ────────────────────────────────────────
        trade_result = None
        if self._position is not None:
            self._position = self._risk_manager.update_trailing(self._position, close_price)
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

        # ── Filtre multi-timeframe 1h (D.1 — 3/3 IA) ─────────────────────────────
        # Veto si tendance horaire contra-directionnelle : SMA20 vs SMA50 sur 1h
        trend_1h_veto = False
        if decision.action in (Action.LONG, Action.SHORT) and self._ohlcv_1h is not None and len(self._ohlcv_1h) >= 50:
            c1h = self._ohlcv_1h["close"]
            sma20_1h = c1h.rolling(20, min_periods=20).mean().iloc[-1]
            sma50_1h = c1h.rolling(50, min_periods=50).mean().iloc[-1]
            if pd.notna(sma20_1h) and pd.notna(sma50_1h):
                trend_1h_up = bool(sma20_1h > sma50_1h)
                if decision.action == Action.LONG and not trend_1h_up:
                    trend_1h_veto = True   # signal LONG rejeté : tendance 1h baissière
                elif decision.action == Action.SHORT and trend_1h_up:
                    trend_1h_veto = True   # signal SHORT rejeté : tendance 1h hausse

        # ── Nouvelle entrée ───────────────────────────────────────────────────
        # Filtre volume : n'entrer que si volume >= 70% de la médiane des 20 dernières barres
        vol_ratio = 1.0
        if len(ohlcv) >= 21:
            vol_med = float(ohlcv["volume"].iloc[-21:-1].median())
            vol_ratio = float(ohlcv["volume"].iloc[-1]) / (vol_med + 1e-9)
        if (self._position is None
                and not self._risk_manager.is_paused(time.time())
                and decision.action in (Action.LONG, Action.SHORT)
                and atr_14 and atr_14 > 0
                and vol_ratio >= 0.70
                and not trend_1h_veto):   # D.1 filtre 1h
            side = decision.action.value
            try:
                pos = self._risk_manager.compute_position(
                    side=side, entry_price=close_price,
                    atr_value=atr_14, capital=self._capital,
                )
                self._capital -= pos.size_units * close_price * 0.0005
                self._position = pos
                self._position_entry_ts = bar_ts
                self._n_trades += 1
                logger.info(f"ENTRÉE {side.upper()} @ {close_price:.2f} | SL={pos.stop_loss:.2f} TP={pos.take_profit:.2f}")
            except Exception as exc:
                logger.warning(f"Entrée ignorée: {exc}")

        pos = self._position
        self._persist(
            asset=self.symbol, bar_ts=bar_ts, close_price=close_price,
            regime=int(regime_val) if pd.notna(regime_val) else None,
            prob_up=prob_up, action=decision.action.value, reason=decision.reason,
            atr_14=atr_14, position_side=pos.side if pos else None,
            entry_price=pos.entry_price if pos else None,
            sl_price=pos.stop_loss if pos else None,
            tp_price=pos.take_profit if pos else None,
        )

        cycle_ms = int((time.time() - t0) * 1000)
        logger.info(
            f"[V2] {bar_ts[:16]} | {'TREND' if regime_trending else 'RANG'} | "
            f"P(up)={f'{prob_up:.3f}' if prob_up is not None else 'N/A'} | "
            f"{decision.action.value.upper()} | capital={self._capital:.0f}$ | {cycle_ms}ms"
        )
        return {
            "cycle_id": f"v2_{int(time.time())}",
            "timestamp": datetime.utcnow().isoformat(),
            "asset": self.symbol,
            "bar_ts": bar_ts,
            "close_price": close_price,
            "regime_trending": regime_trending,
            "regime": int(regime_val) if pd.notna(regime_val) else None,
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
        if pos.side == "long":
            gross = (price - pos.entry_price) * pos.size_units
        else:
            gross = (pos.entry_price - price) * pos.size_units
        fees = pos.size_units * price * 0.0005
        net = gross - fees
        self._capital += net
        self._peak_capital = max(self._peak_capital, self._capital)
        pnl_pct = net / (pos.entry_price * pos.size_units)
        if net > 0:
            self._wins += 1
        self._position_entry_ts = None   # reset après fermeture
        self._risk_manager.record_trade_pnl_pct(pnl_pct, time.time())
        logger.info(f"SORTIE {reason} @ {price:.2f} | PnL={net:+.2f}$ ({pnl_pct:+.2%})")
        return {"exit_price": price, "pnl_abs": round(net, 2),
                "pnl_pct": round(pnl_pct, 4), "exit_reason": reason}

    def _persist(self, **kwargs):
        try:
            from storage.database import write_v2_state, append_v2_equity
            write_v2_state(**kwargs, capital=round(self._capital, 2),
                           model_fit_at=self._model_fit_at)
            append_v2_equity(ts=kwargs["bar_ts"], asset=kwargs["asset"],
                             equity=round(self._capital, 2), action=kwargs["action"],
                             close_price=kwargs["close_price"])
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


def _runner_fingerprint(qcfg: dict) -> tuple:
    """Empreinte des paramètres structurels — changement → recréation du runner."""
    return (
        qcfg.get("timeframe", _DEFAULT_TF),
        int(qcfg.get("history_days", _HISTORY_DAYS)),
        bool(qcfg.get("use_hmm", False)),
        int(qcfg.get("horizon_bars", 4)),
        float(qcfg.get("train_fraction", _TRAIN_FRACTION)),
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
    except Exception:
        cfg = {}
        qcfg = {}

    fp = _runner_fingerprint(qcfg)
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
            existing.cfg.p_up_threshold = float(qcfg.get("p_up_threshold", 0.58))
            existing.cfg.p_dn_threshold = float(qcfg.get("p_dn_threshold", 0.42))
            existing._refit_interval_s = int(qcfg.get("refit_interval_hours", 168)) * 3600
            return existing
        logger.info(
            f"[config] Paramètres changés pour {asset} "
            f"({existing_fp} → {fp}) — recréation du runner"
        )

    pipe_cfg = PipelineConfig(
        use_hmm=qcfg.get("use_hmm", False),
        horizon_bars=qcfg.get("horizon_bars", 4),
        p_up_threshold=float(qcfg.get("p_up_threshold", 0.58)),
        p_dn_threshold=float(qcfg.get("p_dn_threshold", 0.42)),
        initial_capital=cfg.get("exchange", {}).get("paper_capital_usd", 10_000.0),
    )
    _runners[asset] = LiveRunner(
        symbol=asset,
        timeframe=qcfg.get("timeframe", _DEFAULT_TF),
        history_days=qcfg.get("history_days", _HISTORY_DAYS),
        train_fraction=qcfg.get("train_fraction", _TRAIN_FRACTION),
        config=pipe_cfg,
        refit_interval_s=int(qcfg.get("refit_interval_hours", 168)) * 3600,
    )
    return _runners[asset]


def run_cycle(asset: str = _DEFAULT_SYMBOL, trigger: str = "scheduled") -> dict:
    """Point d'entrée principal du daemon. Appelé toutes les 15min par main.py."""
    from utils.cycle_lock import try_acquire, release as _lock_release
    acquired = try_acquire(owner=f"v2_{trigger}", asset=asset)
    try:
        runner = _get_runner(asset)
        return runner.step(trigger=trigger)
    finally:
        if acquired:
            _lock_release(asset=asset)
