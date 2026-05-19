"""
quant/backtest.py — Backtest engine vectoriel avec coûts réalistes.

Hypothèses :
- Exécution à l'open de la bougie t+1 après signal généré en clôture de t.
- Frais taker 0.05% par côté (config Binance VIP 0).
- Slippage modélisé en option (ex. 0.02% supplémentaire).
- Gestion d'une position à la fois (mono-asset, pas de pyramiding).
- SL/TP touchés à l'intra-bar : on suppose un ordre d'événements basé sur la
  proximité à l'open (modèle pessimiste = SL avant TP si les deux sont touchés
  dans la même bougie).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from quant.risk import Position, RiskManager
from quant.strategy import Action

logger = logging.getLogger("quant.backtest")


@dataclass
class Trade:
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    side: str
    entry_price: float
    exit_price: float
    size_units: float
    pnl_pct: float
    pnl_abs: float
    exit_reason: str


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade]
    metrics: dict
    n_bars: int

    def to_summary(self) -> str:
        lines = [
            f"Barres traitées      : {self.n_bars}",
            f"Trades exécutés      : {len(self.trades)}",
            f"Rendement total      : {self.metrics['total_return']:.2%}",
            f"Sharpe annualisé     : {self.metrics['sharpe']:.2f}",
            f"Max drawdown         : {self.metrics['max_dd']:.2%}",
            f"Win rate             : {self.metrics['win_rate']:.2%}",
            f"Profit factor        : {self.metrics['profit_factor']:.2f}",
            f"Avg trade pnl%       : {self.metrics['avg_trade_pnl']:.4%}",
        ]
        return "\n".join(lines)


@dataclass
class Backtester:
    initial_capital: float = 10_000.0
    fee_rate: float = 0.0005          # 0.05% par côté
    slippage_rate: float = 0.0002     # 0.02% par côté
    risk_manager: RiskManager = field(default_factory=RiskManager)
    bars_per_year: int = 0  # 0 = auto-inféré depuis l'index des données (5m→105120, 15m→35040…)

    def run(
        self,
        ohlcv: pd.DataFrame,
        signals: pd.Series,
        atr_series: pd.Series,
    ) -> BacktestResult:
        """Exécute le backtest.

        Args:
            ohlcv: DataFrame OHLCV
            signals: Série d'Action alignée sur ohlcv (signal calculé à la close de t)
            atr_series: ATR alignée (utilisé pour SL/TP à l'entrée)
        """
        idx = ohlcv.index
        # Inférer bars_per_year depuis la fréquence réelle des données
        _bpy = self.bars_per_year
        if _bpy <= 0 and len(idx) >= 2:
            bar_sec = (idx[1] - idx[0]).total_seconds()
            if bar_sec > 0:
                _bpy = int(365 * 24 * 3600 / bar_sec)
        if _bpy <= 0:
            _bpy = 365 * 24 * 12  # fallback 5min
        equity = self.initial_capital
        equity_curve = pd.Series(index=idx, dtype="float64")
        trades: list[Trade] = []
        position: Position | None = None
        entry_ts: pd.Timestamp | None = None

        # Compteurs de diagnostic
        _diag = {"short_sig": 0, "long_sig": 0,
                 "short_blocked_pos": 0, "short_flip_ok": 0, "short_flip_atr_nan": 0, "short_flip_paused": 0,
                 "short_entry_ok": 0, "short_entry_paused": 0, "short_entry_atr_nan": 0}

        for i in range(len(idx) - 1):
            ts = idx[i]
            next_ts = idx[i + 1]
            equity_curve.iloc[i] = equity

            bar_next = ohlcv.iloc[i + 1]
            high = float(bar_next["high"])
            low = float(bar_next["low"])
            open_next = float(bar_next["open"])

            # Lire le signal de la barre courante (utilisé pour entrée ET flip)
            action = signals.iloc[i] if i < len(signals) else Action.FLAT
            if action == Action.SHORT:
                _diag["short_sig"] += 1
            elif action == Action.LONG:
                _diag["long_sig"] += 1

            # Gestion position ouverte sur la bougie suivante
            flip_side: str | None = None  # côté de la position à ouvrir après flip
            if position is not None:
                position = self.risk_manager.update_trailing(position, high if position.side == "long" else low)
                exit_reason: str | None = None
                exit_price: float | None = None

                # Modèle pessimiste : SL avant TP si les deux sont touchés
                if position.side == "long":
                    if low <= position.stop_loss:
                        exit_reason = "stop_loss"
                        exit_price = position.stop_loss
                    elif high >= position.take_profit:
                        exit_reason = "take_profit"
                        exit_price = position.take_profit
                else:
                    if high >= position.stop_loss:
                        exit_reason = "stop_loss"
                        exit_price = position.stop_loss
                    elif low <= position.take_profit:
                        exit_reason = "take_profit"
                        exit_price = position.take_profit

                # Position flip : signal inverse fort → sortir + inverser à l'open suivant
                if exit_reason is None:
                    if position.side == "long" and action == Action.SHORT:
                        exit_reason = "flip"
                        exit_price = open_next
                        flip_side = "short"
                    elif position.side == "short" and action == Action.LONG:
                        exit_reason = "flip"
                        exit_price = open_next
                        flip_side = "long"
                elif action == Action.SHORT and position.side == "long":
                    # SL/TP déjà déclenché au même bar → SHORT bloqué
                    _diag["short_blocked_pos"] += 1

                if exit_reason is not None and exit_price is not None:
                    pnl_pct, pnl_abs = self._close_position(position, exit_price)
                    # Kill-switch : DD portefeuille (net/capital), pas position-relative.
                    # Position-relative (net/notional) ≈ -5-7% par SL BTC → KS sur 2 pertes.
                    # Portfolio-relative ≈ -0.75% par SL → KS sur ~10 pertes consécutives.
                    ks_pnl_pct = pnl_abs / equity if equity > 0 else pnl_pct
                    equity += pnl_abs
                    trades.append(
                        Trade(
                            entry_ts=entry_ts,
                            exit_ts=next_ts,
                            side=position.side,
                            entry_price=position.entry_price,
                            exit_price=exit_price,
                            size_units=position.size_units,
                            pnl_pct=pnl_pct,
                            pnl_abs=pnl_abs,
                            exit_reason=exit_reason,
                        )
                    )
                    self.risk_manager.record_trade_pnl_pct(ks_pnl_pct, next_ts.timestamp())
                    position = None
                    entry_ts = None

                    # Ouvrir immédiatement la position inverse (flip) au même open_next
                    if flip_side and not self.risk_manager.is_paused(next_ts.timestamp()):
                        atr_val_flip = float(atr_series.iloc[i]) if i < len(atr_series) else np.nan
                        if np.isfinite(atr_val_flip) and atr_val_flip > 0:
                            slipped_flip = open_next * (1 + self.slippage_rate) if flip_side == "long" else open_next * (1 - self.slippage_rate)
                            try:
                                position = self.risk_manager.compute_position(
                                    side=flip_side,
                                    entry_price=slipped_flip,
                                    atr_value=atr_val_flip,
                                    capital=equity,
                                )
                                entry_ts = next_ts
                                equity -= position.size_units * slipped_flip * self.fee_rate
                                logger.debug(f"Flip {flip_side} @ {slipped_flip:.4f} (equity={equity:.2f})")
                                if flip_side == "short":
                                    _diag["short_flip_ok"] += 1
                            except ValueError as exc:
                                logger.debug(f"Skip flip {flip_side}: {exc}")
                        else:
                            if flip_side == "short":
                                _diag["short_flip_atr_nan"] += 1
                    elif flip_side == "short":
                        _diag["short_flip_paused"] += 1

            # Pas de pyramiding : nouveau signal traité seulement si flat
            if position is None and not self.risk_manager.is_paused(next_ts.timestamp()):
                if action in (Action.LONG, Action.SHORT):
                    atr_val = float(atr_series.iloc[i]) if i < len(atr_series) else np.nan
                    if np.isfinite(atr_val) and atr_val > 0:
                        side = "long" if action == Action.LONG else "short"
                        # Entrée à l'open suivante avec slippage et fee
                        slipped_entry = open_next * (1 + self.slippage_rate) if side == "long" else open_next * (1 - self.slippage_rate)
                        try:
                            position = self.risk_manager.compute_position(
                                side=side,
                                entry_price=slipped_entry,
                                atr_value=atr_val,
                                capital=equity,
                            )
                            entry_ts = next_ts
                            # Frais d'entrée
                            equity -= position.size_units * slipped_entry * self.fee_rate
                            if side == "short":
                                _diag["short_entry_ok"] += 1
                        except ValueError as exc:
                            logger.debug(f"Skip entrée: {exc}")
                    elif action == Action.SHORT:
                        _diag["short_entry_atr_nan"] += 1
            elif action == Action.SHORT and position is None:
                _diag["short_entry_paused"] += 1

        # Log diagnostic des signaux SHORT
        if _diag["short_sig"] > 0:
            logger.info(
                f"[Diag SHORT] signaux={_diag['short_sig']} | "
                f"entrée_ok={_diag['short_entry_ok']} flip_ok={_diag['short_flip_ok']} | "
                f"bloqué_pos={_diag['short_blocked_pos']} flip_atr_nan={_diag['short_flip_atr_nan']} "
                f"flip_paused={_diag['short_flip_paused']} entrée_paused={_diag['short_entry_paused']} "
                f"entrée_atr_nan={_diag['short_entry_atr_nan']}"
            )

        # Clôturer la position ouverte en fin de test (mark-to-market)
        if position is not None and entry_ts is not None:
            last_close = float(ohlcv.iloc[-1]["close"])
            pnl_pct, pnl_abs = self._close_position(position, last_close)
            equity += pnl_abs
            trades.append(Trade(
                entry_ts=entry_ts,
                exit_ts=idx[-1],
                side=position.side,
                entry_price=position.entry_price,
                exit_price=last_close,
                size_units=position.size_units,
                pnl_pct=pnl_pct,
                pnl_abs=pnl_abs,
                exit_reason="end_of_test",
            ))
            logger.debug(f"Fin de test : position {position.side} clôturée @ {last_close:.4f} (pnl={pnl_abs:+.2f})")
            position = None

        # Marque à market la dernière bougie
        equity_curve.iloc[-1] = equity
        equity_curve = equity_curve.ffill()

        metrics = self._compute_metrics(equity_curve, trades, _bpy)
        return BacktestResult(
            equity_curve=equity_curve,
            trades=trades,
            metrics=metrics,
            n_bars=len(idx),
        )

    def _close_position(self, pos: Position, exit_price: float) -> tuple[float, float]:
        """Retourne (pnl_pct, pnl_abs) en tenant compte des frais de sortie."""
        slipped_exit = (
            exit_price * (1 - self.slippage_rate)
            if pos.side == "long"
            else exit_price * (1 + self.slippage_rate)
        )
        if pos.side == "long":
            gross = (slipped_exit - pos.entry_price) * pos.size_units
        else:
            gross = (pos.entry_price - slipped_exit) * pos.size_units
        fees = pos.size_units * slipped_exit * self.fee_rate
        net = gross - fees
        notional = pos.entry_price * pos.size_units
        pnl_pct = net / notional if notional > 0 else 0.0
        return pnl_pct, net

    def _compute_metrics(
        self, equity_curve: pd.Series, trades: list[Trade], bars_per_year: int = 0
    ) -> dict:
        equity = equity_curve.dropna()
        if len(equity) < 2:
            return {
                "total_return": 0.0,
                "sharpe": 0.0,
                "max_dd": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "avg_trade_pnl": 0.0,
            }
        rets = equity.pct_change().dropna()
        total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
        _bpy = bars_per_year if bars_per_year > 0 else (self.bars_per_year if self.bars_per_year > 0 else 365 * 24 * 12)
        sharpe = (
            float(rets.mean() / rets.std() * np.sqrt(_bpy))
            if rets.std() > 0
            else 0.0
        )
        cummax = equity.cummax()
        dd = (equity - cummax) / cummax
        max_dd = float(dd.min())

        pnls = [t.pnl_pct for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        win_rate = len(wins) / len(pnls) if pnls else 0.0
        profit_factor = (
            sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float("inf") if wins else 0.0
        )
        avg_trade_pnl = float(np.mean(pnls)) if pnls else 0.0

        return {
            "total_return": total_return,
            "sharpe": sharpe,
            "max_dd": max_dd,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_trade_pnl": avg_trade_pnl,
        }


def buy_and_hold(ohlcv: pd.DataFrame, initial_capital: float = 10_000.0) -> BacktestResult:
    """Baseline B&H : achète à open[0], vend à close[-1]."""
    equity = initial_capital
    entry_price = float(ohlcv["open"].iloc[0])
    units = equity / entry_price
    equity_curve = ohlcv["close"] * units
    equity_curve.iloc[0] = equity
    exit_price = float(ohlcv["close"].iloc[-1])
    pnl_pct = exit_price / entry_price - 1.0
    pnl_abs = pnl_pct * equity
    trades = [
        Trade(
            entry_ts=ohlcv.index[0],
            exit_ts=ohlcv.index[-1],
            side="long",
            entry_price=entry_price,
            exit_price=exit_price,
            size_units=units,
            pnl_pct=pnl_pct,
            pnl_abs=pnl_abs,
            exit_reason="end_of_data",
        )
    ]
    bt = Backtester(initial_capital=initial_capital)
    metrics = bt._compute_metrics(equity_curve, trades)
    return BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        metrics=metrics,
        n_bars=len(ohlcv),
    )
