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
        return {"ohlcv_5m": "DataFrame", "ohlcv_1h": "DataFrame"}

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

        from v4.nodes.config_loader import load_v4_config
        _cfg = load_v4_config(symbol, "exit", {
            "strategy": "chandelier", "atr_mult": 3.0, "atr_period": 14,
            "chandelier_lookback": 22,
        })
        strategy = self.params.get("exit_strategy", _cfg["strategy"])
        atr_mult = float(self.params.get("atr_mult") or self.params.get("trail_atr", _cfg["atr_mult"]))
        atr_period = int(self.params.get("atr_period", _cfg["atr_period"]))
        lookback = int(self.params.get("chandelier_lookback", _cfg["chandelier_lookback"]))
        ohlcv_5m = inputs.get("ohlcv_5m")
        ohlcv_1h = inputs.get("ohlcv_1h")  # utilisé pour ATR + chandelier (timeframe plus large)

        from storage.paper_trader import get_open_positions, close_position, update_stop_loss

        positions = get_open_positions(symbol=symbol)
        if not positions:
            return {"closed": [], "open_positions": []}

        # Utiliser 1h pour l'ATR (plus représentatif), fallback 5m
        ohlcv_atr = ohlcv_1h if ohlcv_1h is not None and hasattr(ohlcv_1h, "iloc") and len(ohlcv_1h) >= atr_period else ohlcv_5m
        ohlcv_ch = ohlcv_1h if ohlcv_1h is not None and hasattr(ohlcv_1h, "iloc") and len(ohlcv_1h) >= lookback else ohlcv_5m

        if ohlcv_5m is None or not hasattr(ohlcv_5m, "iloc") or len(ohlcv_5m) < 2:
            logger.warning("PositionManager: pas assez d'OHLCV 5m")
            return {"closed": [], "open_positions": positions}

        if ohlcv_atr is None or len(ohlcv_atr) < atr_period:
            logger.warning("PositionManager: pas assez d'OHLCV pour ATR")
            return {"closed": [], "open_positions": positions}

        # ATR sur timeframe 1h
        recent_atr = ohlcv_atr.iloc[-atr_period:]
        atr = float((recent_atr["high"] - recent_atr["low"]).mean()) if len(recent_atr) >= 2 else 1.0
        if atr <= 0:
            atr = 1.0

        # Prix actuels (5m pour détection intra-barre)
        current_high = float(ohlcv_5m["high"].iloc[-1])
        current_low = float(ohlcv_5m["low"].iloc[-1])
        current_close = float(ohlcv_5m["close"].iloc[-1])

        closed_this_cycle: list[dict] = []
        still_open: list[dict] = []

        for pos in positions:
            trade_id = pos["trade_id"]
            action = pos.get("action", "long")
            entry = float(pos.get("entry_price", 0))
            current_sl = float(pos.get("stop_loss", 0))

            # ── Calcul du nouveau SL selon la stratégie ──
            if strategy == "chandelier":
                new_sl = self._calc_chandelier_sl(ohlcv_ch, action, atr, lookback, atr_mult)
            else:
                new_sl = self._calc_trailing_sl(current_close, action, atr, atr_mult)

            logger.info(
                "posmgr [%s] %s %s: entry=%.2f cur_sl=%.2f new_sl=%.2f atr=%.2f",
                symbol, trade_id, action, entry, current_sl, new_sl, atr,
            )

            # Le SL ne doit jamais reculer (LONG: monte, SHORT: descend)
            # + distance minimale de breathing room (min_atr_dist × ATR)
            min_atr_dist = float(self.params.get("min_atr_dist", 1.0))
            if action == "long":
                new_sl = max(new_sl, current_sl, 0.01) if current_sl > 0 else max(new_sl, 0.01)
                new_sl = min(new_sl, entry - min_atr_dist * atr)  # breathing room
                hit = current_sl > 0 and current_low <= current_sl
            else:
                if current_sl > 0:
                    new_sl = min(new_sl, current_sl)
                # Le SL garde au moins min_atr_dist × ATR de breathing room
                if entry > 0:
                    new_sl = max(new_sl, entry + min_atr_dist * atr)
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
                    ok = update_stop_loss(trade_id, round(new_sl, 4))
                    logger.info(
                        "SL trail [%s] %s %s: %.2f -> %.2f (ok=%s)",
                        strategy, trade_id, action, current_sl, new_sl, ok,
                    )
                still_open.append({**pos, "stop_loss": new_sl, "strategy": strategy})

        return {
            "closed": closed_this_cycle,
            "open_positions": still_open,
            "atr": round(atr, 4),
            "strategy": strategy,
        }
