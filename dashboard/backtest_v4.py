"""
dashboard/backtest_v4.py — Backtest engine V4 pour le dashboard.

Utilise les VRAIS nœuds DAG (LogReg, RiskATR, PositionManager, etc.)
pour simuler le comportement réel sur données historiques.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("dashboard.backtest_v4")


@dataclass
class BTTrade:
    timestamp: str
    symbol: str
    action: str
    entry_price: float
    exit_price: float
    pnl_usd: float
    pnl_pct: float
    exit_reason: str
    bars_held: int


@dataclass
class BTResult:
    symbol: str
    start: str
    end: str
    initial_capital: float
    final_capital: float
    total_pnl: float
    total_pnl_pct: float
    n_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    max_drawdown_pct: float
    sharpe: float
    trades: list[BTTrade] = field(default_factory=list)


def run_backtest_v4(
    symbol: str = "BTC/USDT",
    days: int = 60,
    capital: float = 10_000,
    risk_pct: float = 1.0,
    sl_mult: float = 2.0,
    tp_mult: float = 4.0,
    fraction: float = 0.02,
    exit_strategy: str = "chandelier",
    exit_atr_mult: float = 3.0,
    min_atr_dist: float = 1.0,
) -> BTResult:
    """Backtest V4 avec les vrais nœuds DAG."""
    from quant.data_loader import fetch_history

    logger.info("Backtest %s: chargement %dj...", symbol, days)
    df_5m = fetch_history(symbol, "5m", days=days)
    df_1h = fetch_history(symbol, "1h", days=days)
    if df_5m.empty or df_1h.empty:
        raise ValueError(f"Pas de données pour {symbol}")

    trades: list[BTTrade] = []
    position: dict | None = None
    equity_curve: list[float] = [capital]
    current_capital = capital

    atr_period = 14
    ch_lookback = 22
    min_bars = 200  # minimum pour le signal LogReg
    cycle_interval = 12  # bars 5m = 1h par cycle

    logger.info("Backtest %s: %d barres 5m, min=%d", symbol, len(df_5m), min_bars)

    # ── Boucle principale : exit check chaque barre, signal chaque cycle ──
    last_signal = "flat"
    last_prob_up = 0.5
    last_confidence = 0.0

    for i in range(min_bars, len(df_5m) - 1):
        ohlcv_5m_win = df_5m.iloc[:i + 1]
        bar_5m = df_5m.iloc[i + 1]  # barre "suivante" pour exécution
        ohlcv_1h_win = df_1h[df_1h.index <= ohlcv_5m_win.index[-1]]

        if len(ohlcv_1h_win) < atr_period:
            continue

        # ── ATR 1h (recalculé chaque barre pour exit précis) ──
        close_1h = ohlcv_1h_win["close"]
        high_1h = ohlcv_1h_win["high"]
        low_1h = ohlcv_1h_win["low"]
        tr = pd.concat([
            high_1h - low_1h,
            (high_1h - close_1h.shift()).abs(),
            (low_1h - close_1h.shift()).abs(),
        ], axis=1).max(axis=1)
        atr_1h = float(tr.rolling(14).mean().iloc[-1])
        if np.isnan(atr_1h) or atr_1h <= 0:
            continue

        entry_price = float(ohlcv_5m_win["close"].iloc[-1])
        current_high = float(bar_5m["high"])
        current_low = float(bar_5m["low"])

        # ── Position Manager (exit) — vérifié CHAQUE barre ──
        if position:
            pos_sl = position["sl"]
            pos_action = position["action"]
            pos_entry = position["entry"]
            pos_size = position["size_usd"]

            if exit_strategy == "chandelier":
                recent = ohlcv_1h_win.iloc[-ch_lookback:]
                if pos_action == "long":
                    new_sl = float(recent["high"].max()) - exit_atr_mult * atr_1h
                    new_sl = min(new_sl, pos_entry - min_atr_dist * atr_1h)
                else:
                    new_sl = float(recent["low"].min()) + exit_atr_mult * atr_1h
                    new_sl = max(new_sl, pos_entry + min_atr_dist * atr_1h)
            else:
                if pos_action == "long":
                    new_sl = entry_price - exit_atr_mult * atr_1h
                    new_sl = min(new_sl, pos_entry - min_atr_dist * atr_1h)
                else:
                    new_sl = entry_price + exit_atr_mult * atr_1h
                    new_sl = max(new_sl, pos_entry + min_atr_dist * atr_1h)

            if pos_action == "long":
                new_sl = max(new_sl, pos_sl)
            else:
                new_sl = min(new_sl, pos_sl) if pos_sl > 0 else new_sl
            position["sl"] = new_sl

            hit = False
            close_price = 0.0
            if pos_action == "long" and current_low <= pos_sl:
                hit = True
                close_price = pos_sl
            elif pos_action == "short" and current_high >= pos_sl:
                hit = True
                close_price = pos_sl

            if hit:
                pnl_pct = (close_price - pos_entry) / pos_entry if pos_action == "long" else (pos_entry - close_price) / pos_entry
                pnl_usd = pos_size * pnl_pct
                current_capital += pnl_usd
                trades.append(BTTrade(
                    timestamp=str(bar_5m.name),
                    symbol=symbol, action=pos_action,
                    entry_price=pos_entry, exit_price=close_price,
                    pnl_usd=round(pnl_usd, 4), pnl_pct=round(pnl_pct * 100, 4),
                    exit_reason=exit_strategy, bars_held=i - position["entry_bar"],
                ))
                position = None
                equity_curve.append(current_capital)
                continue

        # ── Signal — calculé uniquement au début de chaque cycle ──
        is_cycle = ((i - min_bars) % cycle_interval == 0)
        if is_cycle and position is None:
            signal, prob_up, confidence = "flat", 0.5, 0.0
            try:
                signal, prob_up, confidence = _compute_signal_xgb(ohlcv_5m_win, ohlcv_1h_win, symbol)
            except Exception as exc1:
                logger.debug("XGB+LogReg cascade failed: %s — trying LogReg directly", exc1)
                try:
                    s, p = _compute_signal_v4(ohlcv_5m_win, ohlcv_1h_win, symbol)
                    signal, prob_up, confidence = s, p, 0.0
                except Exception as exc2:
                    logger.debug("LogReg direct failed: %s — fallback SMA", exc2)
                    # Fallback ultime: SMA crossover
                    signal = _compute_signal_sma(ohlcv_1h_win)
                    prob_up = 0.5
                    confidence = 0.0
            trend = _compute_trend_v4(ohlcv_1h_win)

            # ── Direction Gate ──
            if signal == "long" and trend == "bearish":
                logger.debug("Direction Gate: long blocked by bearish trend")
                signal = "flat"
            elif signal == "short" and trend == "bullish":
                logger.debug("Direction Gate: short blocked by bullish trend")
                signal = "flat"

            last_signal = signal
            last_prob_up = prob_up
            last_confidence = confidence

            logger.debug(
                "Signal cycle i=%d: sig=%s prob=%.3f conf=%.3f trend=%s | 1h_bars=%d",
                i, signal, prob_up, confidence, trend, len(ohlcv_1h_win),
            )

            # ── Ouverture ──
            if signal != "flat" and position is None:
                # Entrée à l'open de la barre suivante
                entry_exec = float(bar_5m["open"])
                risk_per_unit = (sl_mult * atr_1h) / entry_exec if entry_exec > 0 else 0.01
                max_risk = current_capital * (risk_pct / 100.0)
                risk_based = max_risk / risk_per_unit if risk_per_unit > 0 else current_capital * fraction
                size_usd = min(risk_based, current_capital * fraction)
                size_usd = max(size_usd, 10.0)

                if signal == "long":
                    sl = entry_exec - sl_mult * atr_1h
                else:
                    sl = entry_exec + sl_mult * atr_1h

                position = {
                    "action": signal, "entry": entry_exec, "sl": sl,
                    "tp": 0, "size_usd": size_usd, "entry_bar": i,
                }

    # ── Clôture fin de test (mark-to-market) ──
    if position is not None:
        close_price = float(df_5m["close"].iloc[-1])
        pos_action = position["action"]
        pos_entry = position["entry"]
        pos_size = position["size_usd"]
        pnl_pct = (close_price - pos_entry) / pos_entry if pos_action == "long" else (pos_entry - close_price) / pos_entry
        pnl_usd = pos_size * pnl_pct
        current_capital += pnl_usd
        trades.append(BTTrade(
            timestamp=str(df_5m.index[-1]),
            symbol=symbol, action=pos_action,
            entry_price=pos_entry, exit_price=close_price,
            pnl_usd=round(pnl_usd, 4), pnl_pct=round(pnl_pct * 100, 4),
            exit_reason="end_of_test", bars_held=len(df_5m) - position["entry_bar"],
        ))
        position = None
        equity_curve.append(current_capital)

    # ── Métriques ──
    return _compute_metrics(trades, equity_curve, capital, current_capital, symbol, df_5m)


def _compute_signal_xgb(ohlcv_5m, ohlcv_1h, symbol) -> tuple[str, float, float]:
    """Calcule le signal avec XGBoost (meilleur que LogReg)."""
    try:
        from quant.features import compute_features
        import xgboost as xgb

        features = compute_features(ohlcv_5m)
        if features is None or len(features) < 100:
            return "flat", 0.5, 0.0

        df = features.select_dtypes(include=[np.number]).dropna()
        # Ajouter le close price depuis ohlcv_5m (aligné sur l'index de features)
        close_price = ohlcv_5m["close"].reindex(df.index)
        df["_close"] = close_price
        df = df.dropna()
        if len(df) < 100:
            return "flat", 0.5, 0.0

        # Ajouter lags
        n_lags = 3
        feat_cols = [c for c in df.columns if c != "_close"]
        for lag in range(1, n_lags + 1):
            for col in feat_cols:
                df[f"{col}_lag{lag}"] = df[col].shift(lag)
        df = df.dropna()

        # Cible basée sur le VRAI close price
        future = df["_close"].shift(-48)
        target = (future > df["_close"]).astype(int)

        # Features sans la colonne _close ni future
        X_cols = [c for c in df.columns if c not in ("_close",)]
        split = int(len(df) * 0.70)
        train_f = df[X_cols].iloc[:split]
        train_t = target.iloc[:split].dropna()
        train_f = train_f.iloc[:len(train_t)]

        if len(train_t) < 50:
            return "flat", 0.5, 0.0

        model = xgb.XGBClassifier(
            n_estimators=100, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            objective="binary:logistic", verbosity=0, random_state=42,
        )
        model.fit(train_f.values, train_t.values)

        last = df[X_cols].iloc[-1:]
        proba = model.predict_proba(last.values)[0]
        prob_up = float(proba[1]) if len(proba) > 1 else float(proba[0])
        confidence = abs(prob_up - 0.5) * 2.0

        if prob_up >= 0.55:
            return "long", prob_up, confidence
        elif prob_up <= 0.45:
            return "short", prob_up, confidence
        return "flat", prob_up, confidence

    except Exception as e:
        logger.debug("XGB signal failed (%s), trying LogReg fallback", e)
        signal, prob = _compute_signal_v4(ohlcv_5m, ohlcv_1h, symbol)
        return signal, prob, 0.0


def _compute_signal_v4(ohlcv_5m, ohlcv_1h, symbol) -> tuple[str, float]:
    """Calcule le signal avec le VRAI LogReg (pas SMA)."""
    try:
        from quant.features import compute_features
        from quant.signal_model import SignalModel

        features = compute_features(ohlcv_5m)
        if features is None or len(features) < 100:
            return "flat", 0.5

        # Ne garder que les colonnes numériques (raw features, pas _q)
        feats_num = features.select_dtypes(include=[np.number])
        # Exclure les colonnes non-informatives ou redondantes
        exclude = ["donchian_high_20", "donchian_low_20", "breakout_up", "breakout_dn"]
        feat_cols = [c for c in feats_num.columns if c not in exclude]
        if len(feat_cols) < 3:
            return "flat", 0.5

        # Entraînement walk-forward
        split = int(len(feats_num) * 0.70)
        train = feats_num.iloc[:split]
        if train.empty:
            return "flat", 0.5

        model = SignalModel(
            feature_cols=feat_cols,
            use_calibration=True,
        )
        target = (ohlcv_5m["close"].shift(-48) > ohlcv_5m["close"]).astype(int)
        target = target.loc[train.index]

        valid_idx = train.index.intersection(target.dropna().index)
        if len(valid_idx) < 50:
            return "flat", 0.5

        train_f = train.loc[valid_idx]
        target_f = target.loc[valid_idx]

        model.fit(train_f, target_f)

        last = feats_num.iloc[-1:]
        # Aligner les colonnes sur celles du train
        common_cols = [c for c in feat_cols if c in last.columns]
        if len(common_cols) < 3:
            return "flat", 0.5

        prob_up = float(model.predict_proba(last[common_cols]))
        prob_up = float(prob_up)

        if prob_up >= 0.55:
            return "long", prob_up
        elif prob_up <= 0.45:
            return "short", prob_up
        return "flat", prob_up

    except Exception as e:
        logger.warning("Signal V4 failed: %s", e)
        return "flat", 0.5


def _compute_signal_sma(ohlcv_1h) -> str:
    """Fallback ultime: signal basé sur SMA crossover."""
    try:
        if len(ohlcv_1h) < 55:
            return "flat"
        close = ohlcv_1h["close"]
        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1])
        if sma20 > sma50:
            return "long"
        elif sma20 < sma50:
            return "short"
        return "flat"
    except Exception:
        return "flat"


def _compute_trend_v4(ohlcv_1h) -> str:
    """Trend filter (SMA 20/50 sur 1h)."""
    try:
        if len(ohlcv_1h) < 55:
            return "neutral"
        close = ohlcv_1h["close"]
        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1])
        if sma20 > sma50:
            return "bullish"
        return "bearish"
    except Exception:
        return "neutral"


def _compute_metrics(trades, equity, capital, final_cap, symbol, df) -> BTResult:
    n = len(trades)
    if n == 0:
        return BTResult(symbol=symbol, start=str(df.index[0]), end=str(df.index[-1]),
                        initial_capital=capital, final_capital=final_cap,
                        total_pnl=0, total_pnl_pct=0, n_trades=0,
                        win_rate=0, avg_win=0, avg_loss=0,
                        max_drawdown_pct=0, sharpe=0)

    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    win_rate = len(wins) / n * 100
    avg_win = sum(t.pnl_usd for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.pnl_usd for t in losses) / len(losses) if losses else 0

    eq = pd.Series(equity)
    rolling_max = eq.cummax()
    dd = (eq - rolling_max) / rolling_max * 100
    max_dd = abs(float(dd.min()))

    returns = pd.Series(equity).pct_change().dropna()
    sharpe = float(returns.mean() / returns.std() * np.sqrt(252 * 78)) if returns.std() > 0 else 0

    total_pnl = final_cap - capital
    return BTResult(
        symbol=symbol, start=str(df.index[0]), end=str(df.index[-1]),
        initial_capital=capital, final_capital=round(final_cap, 2),
        total_pnl=round(total_pnl, 2), total_pnl_pct=round(total_pnl / capital * 100, 2),
        n_trades=n, win_rate=round(win_rate, 1),
        avg_win=round(avg_win, 2), avg_loss=round(avg_loss, 2),
        max_drawdown_pct=round(max_dd, 2), sharpe=round(sharpe, 2),
        trades=trades,
    )


def optimize_params(
    symbol: str = "BTC/USDT",
    days: int = 30,
    capital: float = 10_000,
) -> list[dict]:
    """Grid search rapide pour trouver les meilleurs paramètres.

    Retourne une liste de configs triée par score (Sharpe × (1 - maxDD%)).
    """
    results = []
    param_grid = [
        # (sl_mult, tp_mult, fraction, risk_pct, exit_atr, min_dist, exit_strat)
        (2.0, 4.0, 0.02, 1.0, 3.0, 1.0, "chandelier"),
        (3.0, 6.0, 0.03, 1.0, 4.0, 1.5, "chandelier"),
        (2.0, 4.0, 0.02, 1.5, 3.0, 1.0, "trailing"),
        (2.5, 5.0, 0.025, 1.0, 3.5, 1.5, "chandelier"),
        (3.0, 6.0, 0.03, 1.5, 4.0, 2.0, "trailing"),
        (1.5, 3.0, 0.015, 1.0, 2.5, 1.0, "chandelier"),
        (3.0, 6.0, 0.04, 1.0, 4.0, 1.5, "chandelier"),
        (2.0, 4.0, 0.02, 2.0, 3.0, 1.5, "chandelier"),
    ]

    for sl, tp, frac, rpct, exit_atr, min_dist, estrat in param_grid:
        try:
            r = run_backtest_v4(
                symbol=symbol, days=days, capital=capital,
                risk_pct=rpct, sl_mult=sl, tp_mult=tp, fraction=frac,
                exit_strategy=estrat, exit_atr_mult=exit_atr, min_atr_dist=min_dist,
            )
            # Score composite : Sharpe pondéré par survie (1 - maxDD)
            score = r.sharpe * max(0, 1 - r.max_drawdown_pct / 100.0) if r.n_trades > 0 else -999
            results.append({
                "sl_mult": sl, "tp_mult": tp, "fraction": frac, "risk_pct": rpct,
                "exit_atr": exit_atr, "min_dist": min_dist, "exit_strat": estrat,
                "pnl": r.total_pnl, "pnl_pct": r.total_pnl_pct, "win_rate": r.win_rate,
                "sharpe": r.sharpe, "max_dd": r.max_drawdown_pct, "n_trades": r.n_trades,
                "score": round(score, 2),
            })
        except Exception as e:
            logger.warning("Optimize failed for config: %s", e)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results
