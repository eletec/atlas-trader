"""
v4/nodes/quant/position_manager.py — PositionManager node.

À chaque cycle, pour chaque position ouverte :
  1. Calcule un trailing stop (ATR au-dessus du prix pour SHORT, en-dessous pour LONG)
  2. Si le trailing SL est touché → CLOSE
  3. Sinon, met à jour le SL dans la DB (le SL "suit" le prix)

Le trade reste ouvert tant que la tendance est favorable.
Pas de TP fixe — on laisse courir.
"""
from __future__ import annotations

import logging
from typing import Any

from v4.core.node import Node

logger = logging.getLogger("v4.nodes.quant.position_manager")


class PositionManager(Node):
    """
    Trailing stop sur positions ouvertes.

    Inputs :
        ohlcv_5m  (DataFrame) — OHLCV récent

    Outputs :
        closed         (list[dict]) — positions fermées ce cycle
        open_positions (list[dict]) — positions encore ouvertes (SL mis à jour)

    Params :
        symbol       : str   — paire (ex. "BTC/USDT")
        trail_atr    : float — multiplicateur ATR pour le trailing SL (défaut: 2.0)
        atr_period   : int   — périodes pour l'ATR (défaut: 14)
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

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        symbol = self.params.get("symbol", "BTC/USDT")
        trail_mult = float(self.params.get("trail_atr", 2.0))
        atr_period = int(self.params.get("atr_period", 14))
        ohlcv = inputs.get("ohlcv_5m")

        from storage.paper_trader import get_open_positions, close_position, update_stop_loss

        positions = get_open_positions(symbol=symbol)
        if not positions:
            return {"closed": [], "open_positions": []}

        if ohlcv is None or not hasattr(ohlcv, "iloc") or len(ohlcv) < 2:
            logger.warning("PositionManager: pas assez d'OHLCV")
            return {"closed": [], "open_positions": positions}

        # ATR récent (simple: range moyen des N dernières bougies)
        recent = ohlcv.iloc[-atr_period:]
        atr = float((recent["high"] - recent["low"]).mean()) if len(recent) >= 2 else 1.0
        if atr <= 0:
            atr = 1.0

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

            if action == "long":
                # Trailing SL LONG = prix actuel - trail_atr × ATR (le SL monte)
                new_sl = current_close - trail_mult * atr
                # Le SL ne redescend jamais, et doit être > 0
                new_sl = max(new_sl, current_sl, 0.01)

                # Check si le SL actuel est touché
                if current_sl > 0 and current_low <= current_sl:
                    pnl = (current_sl - entry) / entry * float(pos.get("size_usd", 0))
                    close_position(trade_id, current_sl, round(pnl, 4), "trailing_sl")
                    closed_this_cycle.append({
                        "trade_id": trade_id, "symbol": symbol, "action": action,
                        "entry_price": entry, "close_price": current_sl,
                        "pnl_usd": round(pnl, 4), "reason": "trailing_sl",
                    })
                else:
                    # Met à jour le SL (trail)
                    if new_sl > current_sl:
                        update_stop_loss(trade_id, round(new_sl, 4))
                    still_open.append({**pos, "stop_loss": max(new_sl, current_sl)})

            else:  # short
                # Trailing SL SHORT = prix actuel + trail_atr × ATR (le SL descend)
                new_sl = current_close + trail_mult * atr
                # Le SL ne remonte jamais
                if current_sl > 0:
                    new_sl = min(new_sl, current_sl)

                # Check si le SL actuel est touché
                if current_sl > 0 and current_high >= current_sl:
                    pnl = (entry - current_sl) / entry * float(pos.get("size_usd", 0))
                    close_position(trade_id, current_sl, round(pnl, 4), "trailing_sl")
                    closed_this_cycle.append({
                        "trade_id": trade_id, "symbol": symbol, "action": action,
                        "entry_price": entry, "close_price": current_sl,
                        "pnl_usd": round(pnl, 4), "reason": "trailing_sl",
                    })
                else:
                    # Met à jour le SL (trail)
                    if new_sl < current_sl or current_sl == 0:
                        update_stop_loss(trade_id, round(new_sl, 4))
                    still_open.append({**pos, "stop_loss": new_sl if new_sl < current_sl else current_sl})

        return {
            "closed": closed_this_cycle,
            "open_positions": still_open,
        }
