"""
quant/risk.py — Gestion du risque & sizing.

Règles consensus 5 IA :
- Sizing : 1.5% du capital par trade (fixe, pas de Kelly fractionnaire chaotique).
- Stop-loss : 2.5 × ATR (en valeur absolue depuis l'entry).
- Take-profit : 3.0 × ATR (R:R ≈ 1.2).
- Trailing stop : actif après +1×ATR, recule de 1×ATR du plus haut/bas.
- Kill-switch : pause de 7 jours si DD hebdo > 8%.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("zeitgeist.quant.risk")


@dataclass
class RiskParams:
    fraction_per_trade: float = 0.015     # 1.5% du capital
    stop_loss_atr_mult: float = 2.5
    take_profit_atr_mult: float = 3.0
    trailing_activation_atr: float = 1.0
    trailing_distance_atr: float = 1.0
    weekly_dd_kill_switch: float = 0.08   # 8% DD/sem → pause
    kill_switch_pause_days: int = 7


@dataclass
class Position:
    side: str           # "long" | "short"
    entry_price: float
    atr_at_entry: float
    size_units: float
    stop_loss: float
    take_profit: float
    trailing_active: bool = False
    extreme_price: float = 0.0   # high atteint (long) ou low atteint (short)


class RiskManager:
    """Calcule sizing/SL/TP et gère trailing stop & kill-switch."""

    def __init__(self, params: RiskParams | None = None):
        self.params = params or RiskParams()
        self._weekly_pnl_pct: float = 0.0
        self._pause_until: float = 0.0    # timestamp epoch

    def compute_position(
        self, side: str, entry_price: float, atr_value: float, capital: float
    ) -> Position:
        risk_amount = capital * self.params.fraction_per_trade
        stop_distance = self.params.stop_loss_atr_mult * atr_value
        if stop_distance <= 0:
            raise ValueError(f"ATR invalide: {atr_value}")
        size_units = risk_amount / stop_distance
        if side == "long":
            sl = entry_price - stop_distance
            tp = entry_price + self.params.take_profit_atr_mult * atr_value
        elif side == "short":
            sl = entry_price + stop_distance
            tp = entry_price - self.params.take_profit_atr_mult * atr_value
        else:
            raise ValueError(f"side inconnu: {side}")
        return Position(
            side=side,
            entry_price=entry_price,
            atr_at_entry=atr_value,
            size_units=size_units,
            stop_loss=sl,
            take_profit=tp,
            extreme_price=entry_price,
        )

    def update_trailing(self, pos: Position, current_price: float) -> Position:
        """Met à jour trailing stop si activé."""
        atr_ = pos.atr_at_entry
        if pos.side == "long":
            if current_price > pos.extreme_price:
                pos.extreme_price = current_price
            if not pos.trailing_active and (
                current_price >= pos.entry_price + self.params.trailing_activation_atr * atr_
            ):
                pos.trailing_active = True
            if pos.trailing_active:
                new_sl = pos.extreme_price - self.params.trailing_distance_atr * atr_
                pos.stop_loss = max(pos.stop_loss, new_sl)
        else:
            if current_price < pos.extreme_price or pos.extreme_price == pos.entry_price:
                pos.extreme_price = current_price
            if not pos.trailing_active and (
                current_price <= pos.entry_price - self.params.trailing_activation_atr * atr_
            ):
                pos.trailing_active = True
            if pos.trailing_active:
                new_sl = pos.extreme_price + self.params.trailing_distance_atr * atr_
                pos.stop_loss = min(pos.stop_loss, new_sl)
        return pos

    def should_exit(self, pos: Position, current_price: float) -> str | None:
        if pos.side == "long":
            if current_price <= pos.stop_loss:
                return "stop_loss"
            if current_price >= pos.take_profit:
                return "take_profit"
        else:
            if current_price >= pos.stop_loss:
                return "stop_loss"
            if current_price <= pos.take_profit:
                return "take_profit"
        return None

    # ---- Kill-switch ----
    def record_trade_pnl_pct(self, pnl_pct: float, now_ts: float) -> None:
        self._weekly_pnl_pct += pnl_pct
        if self._weekly_pnl_pct <= -self.params.weekly_dd_kill_switch:
            self._pause_until = now_ts + self.params.kill_switch_pause_days * 86400
            logger.warning(
                f"KILL-SWITCH activé : DD hebdo={self._weekly_pnl_pct:.2%}, "
                f"pause {self.params.kill_switch_pause_days}j."
            )

    def reset_weekly_pnl(self) -> None:
        self._weekly_pnl_pct = 0.0

    def is_paused(self, now_ts: float) -> bool:
        return now_ts < self._pause_until
