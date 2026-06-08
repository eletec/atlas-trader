"""
v4/nodes/quant/position_manager.py — PositionManager node.

Stratégies de sortie supportées (param `exit_strategy`) :

  - "chandelier" (défaut) : Chandelier Exit — le SL s'accroche au plus haut/bas
    des N dernières barres, moins K×ATR. Laisse respirer le trade.

  - "trailing" : Trailing stop — le SL suit le prix à K×ATR de distance.
    Plus réactif, mais sort plus vite.

Pas de TP fixe — on laisse courir tant que la tendance est favorable.
"""
from __future__ import annotations

import logging
from typing import Any

from v4.core.node import Node

logger = logging.getLogger("v4.nodes.quant.position_manager")


class PositionManager(Node):
    """
    Gère la sortie des positions avec stratégie configurable.

    Params :
        symbol              : str   — paire (ex. "BTC/USDT")
        exit_strategy       : str   — "chandelier" (défaut) ou "trailing"
        atr_mult            : float — multiplicateur ATR (défaut: 3.0)
        atr_period          : int   — périodes ATR (défaut: 14)
        chandelier_lookback : int   — barres pour le chandelier (défaut: 22)
        trail_atr           : float — alias pour atr_mult (compat)
    """

    @property
    def node_type(self) -> str:
        return "PositionManager"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"ohlcv_5m": "DataFrame"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"closed": "list", "open_positions": "list"}

    def _calc_chandelier_sl(
        self, ohlcv, action: str, atr: float, lookback: int, atr_mult: float
    ) -> float:
        """Chandelier Exit : SL basé sur le plus haut/bas des N barres."""
        recent = ohlcv.iloc[-lookback:]
        if action == "long":
            highest = float(recent["high"].max())
            return highest - atr_mult * atr
        else:
            lowest = float(recent["low"].min())
            return lowest + atr_mult * atr

    def _calc_trailing_sl(
        self, price: float, action: str, atr: float, atr_mult: float
    ) -> float:
        """Trailing stop : SL = prix ± K×ATR."""
        if action == "long":
            return price - atr_mult * atr
        else:
            return price + atr_mult * atr

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        symbol = self.params.get("symbol", "BTC/USDT")
        strategy = self.params.get("exit_strategy", "chandelier")
        atr_mult = float(self.params.get("atr_mult") or self.params.get("trail_atr", 3.0))
        atr_period = int(self.params.get("atr_period", 14))
        lookback = int(self.params.get("chandelier_lookback", 22))
        ohlcv = inputs.get("ohlcv_5m")

        from storage.paper_trader import get_open_positions, close_position, update_stop_loss

        positions = get_open_positions(symbol=symbol)
        if not positions:
            return {"closed": [], "open_positions": []}

        if ohlcv is None or not hasattr(ohlcv, "iloc") or len(ohlcv) < max(atr_period, lookback):
            logger.warning("PositionManager: pas assez d'OHLCV (%s barres)", len(ohlcv) if ohlcv is not None else 0)
            return {"closed": [], "open_positions": positions}

        # ATR
        recent_atr = ohlcv.iloc[-atr_period:]
        atr = float((recent_atr["high"] - recent_atr["low"]).mean()) if len(recent_atr) >= 2 else 1.0
        if atr <= 0:
            atr = 1.0

        # Prix actuels
        current_high = float(ohlcv["high"].iloc[-1])
        current_low = float(ohlcv["low"].iloc[-1])
        current_close = float(ohlcv["close"].iloc[-1])

        closed_this_cycle: list[dict] = []
        still_open: list[dict] = []

        for pos in positions:
            trade_id = pos["trade_id"]
            action = pos.get("action", "long")
            entry = float(pos.get("entry_price", 0))
            current_sl = float(pos.get("stop_loss", 0))

            # ── Calcul du nouveau SL selon la stratégie ──
            if strategy == "chandelier":
                new_sl = self._calc_chandelier_sl(ohlcv, action, atr, lookback, atr_mult)
            else:
                new_sl = self._calc_trailing_sl(current_close, action, atr, atr_mult)

            # Le SL ne doit jamais reculer (LONG: monte, SHORT: descend)
            if action == "long":
                new_sl = max(new_sl, current_sl, 0.01) if current_sl > 0 else max(new_sl, 0.01)
                # Check SL touché : le low de la barre passe sous le SL
                hit = current_sl > 0 and current_low <= current_sl
            else:
                if current_sl > 0:
                    new_sl = min(new_sl, current_sl)
                # Check SL touché : le high de la barre passe au-dessus du SL
                hit = current_sl > 0 and current_high >= current_sl

            if hit:
                close_price = current_sl
                if action == "long":
                    pnl = (close_price - entry) / entry * float(pos.get("size_usd", 0))
                else:
                    pnl = (entry - close_price) / entry * float(pos.get("size_usd", 0))

                close_position(trade_id, close_price, round(pnl, 4), strategy)
                closed_this_cycle.append({
                    "trade_id": trade_id, "symbol": symbol, "action": action,
                    "entry_price": entry, "close_price": close_price,
                    "pnl_usd": round(pnl, 4), "reason": strategy,
                    "strategy": strategy,
                })
                logger.info(
                    "CLOSE [%s] %s %s @ %.2f→%.2f pnl=$%.2f",
                    strategy, trade_id, action, entry, close_price, pnl,
                )
            else:
                # Mise à jour du SL si amélioré
                if (action == "long" and new_sl > current_sl) or \
                   (action == "short" and (new_sl < current_sl or current_sl == 0)):
                    update_stop_loss(trade_id, round(new_sl, 4))
                still_open.append({**pos, "stop_loss": new_sl, "strategy": strategy})

        return {
            "closed": closed_this_cycle,
            "open_positions": still_open,
            "atr": round(atr, 4),
            "strategy": strategy,
        }
