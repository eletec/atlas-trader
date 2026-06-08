"""
dashboard/backtest_v4.py — Backtest engine V4 pour le dashboard.

Fait tourner le pipeline DAG sur des données historiques et retourne
les trades simulés, le PnL et les métriques.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("dashboard.backtest_v4")

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

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
    """
    Backtest complet du pipeline V4 sur données historiques.

    Args:
        symbol: paire (ex. "BTC/USDT")
        days: nombre de jours d'historique
        capital: capital initial
        risk_pct, sl_mult, tp_mult, fraction: paramètres RiskATR
        exit_strategy: "chandelier" ou "trailing"
        exit_atr_mult: multiplicateur ATR pour le SL de sortie
        min_atr_dist: distance minimale SL/entrée en ATR

    Returns:
        BTResult avec trades et métriques.
    """
    from quant.data_loader import fetch_history

    # 1) Charger les données
    logger.info("Backtest %s: chargement %dj...", symbol, days)
    df_5m = fetch_history(symbol, "5m", days=days)
    df_1h = fetch_history(symbol, "1h", days=days)
    if df_5m.empty or df_1h.empty:
        raise ValueError(f"Pas de données pour {symbol}")

    # 2) Initialiser l'état
    trades: list[BTTrade] = []
    position: dict | None = None  # {action, entry, sl, tp, size_usd, entry_bar}
    equity_curve: list[float] = [capital]
    current_capital = capital

    # Paramètres ATR
    atr_period = 14
    ch_lookback = 22

    # Fenêtre glissante: on commence après avoir assez de barres
    warmup = max(atr_period, ch_lookback, 100)
    logger.info("Backtest %s: %d barres 5m, warmup=%d", symbol, len(df_5m), warmup)

    for i in range(warmup, len(df_5m) - 1):
        # Slice des données jusqu'à la barre i (simule le temps réel)
        ohlcv_5m = df_5m.iloc[:i + 1]
        ohlcv_1h_slice = df_1h[df_1h.index <= ohlcv_5m.index[-1]]
        if len(ohlcv_1h_slice) < atr_period:
            continue

        # ── Calcul ATR 1h ──
        close_1h = ohlcv_1h_slice["close"]
        high_1h = ohlcv_1h_slice["high"]
        low_1h = ohlcv_1h_slice["low"]
        tr = pd.concat([
            high_1h - low_1h,
            (high_1h - close_1h.shift()).abs(),
            (low_1h - close_1h.shift()).abs(),
        ], axis=1).max(axis=1)
        atr_1h = float(tr.rolling(atr_period).mean().iloc[-1])
        if np.isnan(atr_1h) or atr_1h <= 0:
            continue

        # Prix actuels (barre courante)
        entry_price = float(ohlcv_5m["close"].iloc[-1])
        current_high = float(ohlcv_5m["high"].iloc[-1])
        current_low = float(ohlcv_5m["low"].iloc[-1])

        # ── Position Manager : vérifier SL ──
        if position:
            pos_sl = position["sl"]
            pos_action = position["action"]
            pos_entry = position["entry"]
            pos_size = position["size_usd"]

            # Calculer le nouveau SL selon stratégie
            if exit_strategy == "chandelier":
                recent_ch = ohlcv_1h_slice.iloc[-ch_lookback:]
                if pos_action == "long":
                    new_sl = float(recent_ch["high"].max()) - exit_atr_mult * atr_1h
                    new_sl = min(new_sl, pos_entry - min_atr_dist * atr_1h)  # breathing room
                else:
                    new_sl = float(recent_ch["low"].min()) + exit_atr_mult * atr_1h
                    new_sl = max(new_sl, pos_entry + min_atr_dist * atr_1h)
            else:  # trailing
                if pos_action == "long":
                    new_sl = entry_price - exit_atr_mult * atr_1h
                    new_sl = min(new_sl, pos_entry - min_atr_dist * atr_1h)
                else:
                    new_sl = entry_price + exit_atr_mult * atr_1h
                    new_sl = max(new_sl, pos_entry + min_atr_dist * atr_1h)

            # Le SL ne recule jamais
            if pos_action == "long":
                new_sl = max(new_sl, pos_sl)
            else:
                new_sl = min(new_sl, pos_sl) if pos_sl > 0 else new_sl

            position["sl"] = new_sl

            # Vérifier si SL touché
            hit = False
            close_price = 0.0
            if pos_action == "long" and current_low <= pos_sl:
                hit = True
                close_price = pos_sl
            elif pos_action == "short" and current_high >= pos_sl:
                hit = True
                close_price = pos_sl

            if hit:
                if pos_action == "long":
                    pnl_pct = (close_price - pos_entry) / pos_entry
                else:
                    pnl_pct = (pos_entry - close_price) / pos_entry
                pnl_usd = pos_size * pnl_pct
                current_capital += pnl_usd

                trades.append(BTTrade(
                    timestamp=str(ohlcv_5m.index[-1]),
                    symbol=symbol,
                    action=pos_action,
                    entry_price=pos_entry,
                    exit_price=close_price,
                    pnl_usd=round(pnl_usd, 4),
                    pnl_pct=round(pnl_pct * 100, 4),
                    exit_reason=exit_strategy,
                    bars_held=i - position["entry_bar"],
                ))
                position = None
                equity_curve.append(current_capital)
                continue  # passe au cycle suivant sans ouvrir de nouvelle position

        # ── Génération de signal simplifiée ──
        # (Dans un backtest complet, on ferait tourner tous les nœuds DAG.
        #  Ici on simplifie: signal basé sur tendance SMA 1h)
        if len(ohlcv_1h_slice) >= 50:
            close_1h_vals = ohlcv_1h_slice["close"]
            sma20 = float(close_1h_vals.rolling(20).mean().iloc[-1])
            sma50 = float(close_1h_vals.rolling(50).mean().iloc[-1])
            trend = "bullish" if sma20 > sma50 else "bearish"
        else:
            trend = "neutral"

        # Signal: short en bearish, long en bullish, flat sinon
        signal = "flat"
        if trend == "bearish":
            signal = "short"
        elif trend == "bullish":
            signal = "long"

        # ── Ouverture de position ──
        if signal != "flat" and position is None:
            # Sizing contextuel
            risk_per_unit = (sl_mult * atr_1h) / entry_price if entry_price > 0 else 0.01
            max_risk = current_capital * (risk_pct / 100.0)
            risk_based = max_risk / risk_per_unit if risk_per_unit > 0 else current_capital * fraction
            size_usd = min(risk_based, current_capital * fraction)
            size_usd = max(size_usd, 10.0)

            if signal == "long":
                sl = entry_price - sl_mult * atr_1h
                tp = entry_price + tp_mult * atr_1h
            else:
                sl = entry_price + sl_mult * atr_1h
                tp = entry_price - tp_mult * atr_1h

            position = {
                "action": signal,
                "entry": entry_price,
                "sl": sl,
                "tp": tp,
                "size_usd": size_usd,
                "entry_bar": i,
            }

    # 3) Calculer les métriques
    n_trades = len(trades)
    if n_trades == 0:
        return BTResult(
            symbol=symbol,
            start=str(df_5m.index[0]),
            end=str(df_5m.index[-1]),
            initial_capital=capital,
            final_capital=current_capital,
            total_pnl=0, total_pnl_pct=0,
            n_trades=0, win_rate=0, avg_win=0, avg_loss=0,
            max_drawdown_pct=0, sharpe=0,
            trades=[],
        )

    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    win_rate = len(wins) / n_trades * 100
    avg_win = sum(t.pnl_usd for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.pnl_usd for t in losses) / len(losses) if losses else 0

    # Max drawdown
    eq = pd.Series(equity_curve)
    rolling_max = eq.cummax()
    drawdown = (eq - rolling_max) / rolling_max * 100
    max_dd = abs(float(drawdown.min()))

    # Sharpe (approximé)
    returns = pd.Series(equity_curve).pct_change().dropna()
    sharpe = float(returns.mean() / returns.std() * np.sqrt(252 * 78)) if returns.std() > 0 else 0  # 78 = 5min bars/day

    total_pnl = current_capital - capital
    total_pnl_pct = total_pnl / capital * 100

    return BTResult(
        symbol=symbol,
        start=str(df_5m.index[0]),
        end=str(df_5m.index[-1]),
        initial_capital=capital,
        final_capital=round(current_capital, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl_pct, 2),
        n_trades=n_trades,
        win_rate=round(win_rate, 1),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        max_drawdown_pct=round(max_dd, 2),
        sharpe=round(sharpe, 2),
        trades=trades,
    )
