"""
graph/workflow_daily.py — Pipeline daily pour FX/métaux (XAU, XAG, WTI, EUR/USD, GBP/USD).

Différences clés vs workflow.py (crypto 5m) :
  - timeframe = "1d"
  - Features : quant/features_daily.py (pas de volume, pas d'intraday)
  - Exécution : une seule fois par jour à daily_execution_hour_utc (défaut 18h UTC)
  - Historique : 5 ans (1825 jours)
  - Normalisation rolling 252 jours (1 an boursier)
  - Horizon 5 barres (1 semaine de trading)
  - Filtre tendance : SMA20 vs SMA50 DAILY (pas 1h)
  - Pas de filtre volume (données yfinance FX/métaux sans volume fiable)

Ticker mapping yfinance :
  XAU/USD → GC=F    XAG/USD → SI=F    WTI/USD → CL=F
  EUR/USD → EURUSD=X    GBP/USD → GBPUSD=X
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("zeitgeist.quant.workflow_daily")

from quant.data_loader import fetch_history
from quant.features_daily import (
    DAILY_FEATURE_COLS,
    DAILY_NORM_COLS,
    compute_features_daily,
    make_target_direction_daily,
)
from quant.normalization import normalize_features
from quant.pipeline import PipelineConfig
from quant.regime import RegimeDetector
from quant.risk import Position, RiskManager, RiskParams
from quant.signal_model import SignalModel
from quant.strategy import Action, decide


def _dcfg():
    try:
        from quant.config import get_quant_cfg
        return get_quant_cfg()
    except Exception:
        return None


def _dattr(key, fallback):
    return getattr(_dcfg(), key, fallback)


# ─── Runner ───────────────────────────────────────────────────────────────────

class DailyRunner:
    """Gère l'état continu du pipeline daily entre les cycles quotidiens.

    Instancié une fois par actif daily au démarrage du daemon.
    `step()` ne prend une décision qu'une fois par jour (guard date).
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.timeframe = "1d"

        # Paramètres lus depuis config
        cfg = _dcfg()
        self.history_days:      int   = getattr(cfg, "daily_history_days",          1825)
        self.horizon_bars:      int   = getattr(cfg, "daily_horizon_bars",             5)
        self.norm_window_days:  int   = getattr(cfg, "daily_norm_window_days",       252)
        self.train_fraction:    float = getattr(cfg, "train_fraction",              0.70)
        self.refit_interval_s:  int   = getattr(cfg, "daily_refit_interval_days",      7) * 86400
        self.p_up_threshold:    float = getattr(cfg, "daily_p_up_threshold",        0.57)
        self.p_dn_threshold:    float = getattr(cfg, "daily_p_dn_threshold",        0.43)

        # Per-asset capital override
        try:
            from utils.config import load_settings as _ls
            _cfg = _ls()
            _ac = _cfg.get("quant", {}).get("asset_config", {}).get(symbol, {})
            self._capital = float(
                _ac.get("capital_usd")
                or _cfg.get("exchange", {}).get("paper_capital_usd", 5_000.0)
            )
        except Exception:
            self._capital = 5_000.0

        self._ohlcv:            pd.DataFrame | None = None
        self._regime:           RegimeDetector | None = None
        self._model:            SignalModel | None = None
        self._last_fit_ts:      float = 0.0
        self._active_feat_cols: list  = []
        self._position:         Position | None = None
        self._position_entry_ts: str | None = None
        self._last_decision_date: str | None = None   # YYYY-MM-DD : anti-double décision
        self._risk_manager = RiskManager(RiskParams(
            stop_loss_atr_mult=_dattr("stop_loss_atr_mult", 2.5),
            take_profit_atr_mult=_dattr("take_profit_atr_mult", 3.5),
            trailing_activation_atr=_dattr("trailing_activation_atr", 1.5),
            trailing_distance_atr=_dattr("trailing_distance_atr", 1.5),
            fraction_per_trade=_dattr("fraction_per_trade", 0.0075),
        ))
        self._peak_capital = self._capital
        self._n_trades = 0
        self._wins = 0

    # ── Refit ─────────────────────────────────────────────────────────────────

    def ensure_fitted(self) -> None:
        now = time.time()
        if self._regime is None or (now - self._last_fit_ts) > self.refit_interval_s:
            self._refit()

    def _refit(self) -> None:
        logger.info(f"[daily] Refit — fetch {self.history_days}j {self.symbol} 1d")
        try:
            ohlcv = fetch_history(
                symbol=self.symbol, timeframe="1d",
                days=self.history_days, cache=True,
            )
        except Exception as exc:
            logger.error(f"[daily] fetch_history failed: {exc}")
            if self._ohlcv is None:
                raise
            ohlcv = self._ohlcv

        # Nettoyage : supprimer barres weekend vides (yfinance en produit parfois)
        ohlcv = ohlcv.dropna(subset=["close"])
        ohlcv = ohlcv[ohlcv["close"] > 0]

        if len(ohlcv) < 300:
            logger.error(f"[daily] Historique insuffisant ({len(ohlcv)} barres) — refit abandonné.")
            return

        self._ohlcv = ohlcv
        split = int(len(ohlcv) * self.train_fraction)
        train_idx = ohlcv.index[:split]

        feats_raw  = compute_features_daily(ohlcv)
        norm_window = self.norm_window_days   # 1 barre/jour → window_bars = window_days
        feats_norm = normalize_features(feats_raw, window=norm_window, columns=DAILY_NORM_COLS)
        feats_all  = pd.concat([feats_raw, feats_norm], axis=1)

        # Régime : utilise fallback ADX (use_hmm=False — daily suffisamment stable)
        self._regime = RegimeDetector(use_hmm=False).fit(feats_all.loc[train_idx])

        # Signal model
        y = make_target_direction_daily(ohlcv, horizon=self.horizon_bars)
        warmup_cutoff = feats_all.index[min(norm_window + 20, len(feats_all) - 1)]
        train_sm_idx  = train_idx[train_idx >= warmup_cutoff]

        # Feature cols disponibles (certaines peuvent être absentes si historique court)
        avail_cols = [c for c in DAILY_FEATURE_COLS if c in feats_all.columns]
        X_train = feats_all.loc[train_sm_idx, avail_cols]
        nan_cols = [c for c in X_train.columns if X_train[c].isna().all()]
        if nan_cols:
            logger.warning(f"[daily] {len(nan_cols)} feature(s) 100% NaN ignorée(s): {nan_cols}")
            X_train = X_train.drop(columns=nan_cols)
        self._active_feat_cols = list(X_train.columns)
        y_train = y.loc[train_sm_idx]
        valid = X_train.notna().all(axis=1) & y_train.notna()

        if valid.sum() < 50:
            logger.warning(f"[daily] Données insuffisantes pour SignalModel ({valid.sum()} lignes valides).")
            self._model = None
        elif y_train.loc[valid].nunique() < 2:
            logger.warning("[daily] y_train mono-classe — SignalModel désactivé.")
            self._model = None
        else:
            try:
                self._model = SignalModel(feature_cols=self._active_feat_cols).fit(
                    X_train.loc[valid], y_train.loc[valid]
                )
                logger.info(f"[daily] SignalModel fitté — {valid.sum()} exemples train")
            except Exception as exc:
                logger.error(f"[daily] SignalModel fit failed: {exc}")
                self._model = None

        self._last_fit_ts = time.time()
        self._feats_all = feats_all   # cache pour step()
        logger.info(f"[daily] Refit OK — {split} barres train | {len(ohlcv)-split} OOS")

    # ── Step ──────────────────────────────────────────────────────────────────

    def step(self, trigger: str = "scheduled") -> dict:
        """Exécute un cycle quotidien.

        Returns:
            dict avec keys: asset, action, reason, prob_up, regime, capital,
                           position_side, close_price, atr_14, sl_price, tp_price,
                           realized_pnl
        """
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Guard : une seule décision par jour UTC
        if self._last_decision_date == today_str and trigger != "force":
            logger.debug(f"[daily] {self.symbol} — décision déjà prise aujourd'hui ({today_str}), skip.")
            return self._state_dict("hold", "already_decided_today")

        self.ensure_fitted()

        if self._ohlcv is None or len(self._ohlcv) < 50:
            return self._state_dict("flat", "historique_insuffisant")

        # Rafraîchir la dernière barre
        try:
            new_bars = fetch_history(
                symbol=self.symbol, timeframe="1d", days=5, cache=False
            )
            new_bars = new_bars.dropna(subset=["close"])
            new_bars = new_bars[new_bars["close"] > 0]
            if not new_bars.empty:
                combined = pd.concat([self._ohlcv, new_bars])
                combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                self._ohlcv = combined
        except Exception as exc:
            logger.warning(f"[daily] Refresh dernière barre failed: {exc}")

        ohlcv = self._ohlcv
        feats_raw  = compute_features_daily(ohlcv)
        feats_norm = normalize_features(feats_raw, window=self.norm_window_days, columns=DAILY_NORM_COLS)
        feats_all  = pd.concat([feats_raw, feats_norm], axis=1)

        # Régime
        regime_series = self._regime.predict(feats_all) if self._regime else pd.Series([np.nan])
        regime_val    = regime_series.iloc[-1] if len(regime_series) else np.nan
        regime_trending = bool(regime_val == 1.0) if pd.notna(regime_val) else False

        # Signal P(up)
        prob_up: float | None = None
        if self._model is not None and self._active_feat_cols:
            avail = [c for c in self._active_feat_cols if c in feats_all.columns]
            try:
                ps = self._model.predict_proba(feats_all[avail])
                v  = ps.iloc[-1]
                prob_up = float(v) if pd.notna(v) else None
            except Exception as exc:
                logger.warning(f"[daily] predict_proba failed: {exc}")

        # Décision de base
        decision = decide(
            probability_up=prob_up,
            regime_trending=regime_trending,
            upper_threshold=self.p_up_threshold,
            lower_threshold=self.p_dn_threshold,
        )

        latest_bar  = ohlcv.iloc[-1]
        close_price = float(latest_bar["close"])
        atr_raw     = feats_raw["atr_14"].iloc[-1]
        atr_14      = float(atr_raw) if pd.notna(atr_raw) else None

        # ── Filtre tendance daily (SMA20 vs SMA50 sur barres daily) ───────────
        trend_veto = False
        sma20 = ohlcv["close"].rolling(20).mean().iloc[-1]
        sma50 = ohlcv["close"].rolling(50).mean().iloc[-1]
        if pd.notna(sma20) and pd.notna(sma50):
            if decision.action == Action.LONG  and sma20 < sma50:
                trend_veto = True
            if decision.action == Action.SHORT and sma20 > sma50:
                trend_veto = True
        if trend_veto:
            logger.info(f"[daily] {self.symbol} trend_veto SMA20/SMA50 — {decision.action} bloqué")
            from quant.strategy import Decision
            decision = Decision(action=Action.FLAT, reason="trend_daily_veto")

        # ── Gestion position existante ────────────────────────────────────────
        realized_pnl = None
        pre_close_position = self._position

        if self._position is not None:
            self._position = self._risk_manager.update_trailing(self._position, close_price)
            exit_signal = self._risk_manager.should_exit(self._position, close_price)

            if exit_signal or (
                decision.action == Action.LONG  and self._position.side == "short"
            ) or (
                decision.action == Action.SHORT and self._position.side == "long"
            ):
                realized_pnl = self._risk_manager.realized_pnl(self._position, close_price)
                logger.info(
                    f"[daily] {self.symbol} EXIT {self._position.side} @ {close_price:.4f} "
                    f"pnl={realized_pnl:+.2f}"
                )
                self._capital += realized_pnl
                self._n_trades += 1
                if realized_pnl > 0:
                    self._wins += 1
                self._position = None
                self._position_entry_ts = None
                if not exit_signal:
                    # On vient juste de fermer pour retourner → re-appliquer la décision
                    pass

        # ── Ouverture nouvelle position ───────────────────────────────────────
        sl_price = tp_price = position_size_usd = None
        if self._position is None and decision.action in (Action.LONG, Action.SHORT):
            if atr_14 and atr_14 > 0:
                pos = self._risk_manager.compute_position(
                    action=decision.action.value,
                    entry_price=close_price,
                    atr=atr_14,
                    capital=self._capital,
                )
                if pos is not None:
                    self._position = pos
                    self._position_entry_ts = today_str
                    sl_price = pos.sl_price
                    tp_price = pos.tp_price
                    position_size_usd = pos.size_usd
                    logger.info(
                        f"[daily] {self.symbol} OPEN {decision.action.value} @ {close_price:.4f} "
                        f"SL={sl_price:.4f} TP={tp_price:.4f} size=${position_size_usd:.0f}"
                    )
            else:
                logger.warning(f"[daily] {self.symbol} ATR=0/NaN — ouverture annulée")
                from quant.strategy import Decision
                decision = Decision(action=Action.FLAT, reason="atr_zero")

        # ── Persist ───────────────────────────────────────────────────────────
        self._last_decision_date = today_str
        self._peak_capital = max(self._peak_capital, self._capital)

        regime_label = (
            "TREND" if regime_trending else
            "RANGE" if regime_val == 0.5 else
            "PANIC"
        ) if pd.notna(regime_val) else "UNKNOWN"

        result = {
            "asset":             self.symbol,
            "ts":                datetime.now(timezone.utc).isoformat(),
            "bar_ts":            str(ohlcv.index[-1]),
            "action":            decision.action.value,
            "reason":            decision.reason,
            "prob_up":           prob_up,
            "regime":            regime_label,
            "capital":           self._capital,
            "position_side":     self._position.side if self._position else None,
            "close_price":       close_price,
            "atr_14":            atr_14,
            "sl_price":          sl_price or (self._position.sl_price if self._position else None),
            "tp_price":          tp_price or (self._position.tp_price if self._position else None),
            "position_size_usd": position_size_usd,
            "realized_pnl":      realized_pnl,
            "pipeline":          "daily",
        }

        self._persist(result)
        return result

    # ── Persist SQLite ────────────────────────────────────────────────────────

    def _persist(self, r: dict) -> None:
        try:
            from storage.database import get_db_path
            import sqlite3
            db_path = get_db_path()
            with sqlite3.connect(db_path) as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO v2_decisions
                        (ts, asset, bar_ts, close_price, regime, prob_up, action, reason,
                         atr_14, sl_price, tp_price, capital, position_size_usd, realized_pnl)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    r["ts"], r["asset"], r["bar_ts"], r["close_price"],
                    r["regime"], r["prob_up"], r["action"], r["reason"],
                    r["atr_14"], r["sl_price"], r["tp_price"],
                    r["capital"], r["position_size_usd"], r["realized_pnl"],
                ))
                conn.execute("""
                    INSERT OR REPLACE INTO v2_equity (ts, asset, equity, action, close_price)
                    VALUES (?,?,?,?,?)
                """, (r["ts"], r["asset"], r["capital"], r["action"], r["close_price"]))
                conn.commit()
        except Exception as exc:
            logger.warning(f"[daily] persist failed: {exc}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _state_dict(self, action: str, reason: str) -> dict:
        return {
            "asset": self.symbol, "action": action, "reason": reason,
            "prob_up": None, "regime": "UNKNOWN", "capital": self._capital,
            "position_side": self._position.side if self._position else None,
            "close_price": None, "atr_14": None,
            "sl_price": None, "tp_price": None,
            "position_size_usd": None, "realized_pnl": None,
            "pipeline": "daily",
        }


# ─── Registry global des runners ─────────────────────────────────────────────

_DAILY_RUNNERS: dict[str, DailyRunner] = {}


def get_daily_runner(symbol: str) -> DailyRunner:
    """Retourne (ou crée) le DailyRunner singleton pour un actif."""
    if symbol not in _DAILY_RUNNERS:
        _DAILY_RUNNERS[symbol] = DailyRunner(symbol)
    return _DAILY_RUNNERS[symbol]


def run_daily_cycle(asset: str, trigger: str = "scheduled") -> dict:
    """Point d'entrée unique appelé par la boucle daemon pour les actifs daily."""
    runner = get_daily_runner(asset)
    return runner.step(trigger=trigger)


def get_daily_active_assets() -> list[str]:
    """Retourne la liste des actifs daily depuis la config."""
    try:
        from utils.config import load_settings
        cfg = load_settings()
        assets = cfg.get("quant", {}).get("daily_active_assets", [])
        return [str(a) for a in assets if a]
    except Exception:
        return []


def should_run_daily(execution_hour_utc: int = 18) -> bool:
    """Retourne True si l'heure courante UTC est dans la fenêtre d'exécution daily.

    Fenêtre : [execution_hour_utc, execution_hour_utc + 1[
    Typiquement 18h-19h UTC = après clôture NYSE (16h30 ET).
    """
    now_utc = datetime.now(timezone.utc)
    return now_utc.hour == execution_hour_utc
