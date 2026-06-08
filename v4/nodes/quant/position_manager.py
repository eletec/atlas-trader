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

import numpy as np

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

        # ── Volatility-adaptive : élargir SL en haute volatilité ──
        vol_factor = 1.0
        vol_lookback = int(self.params.get("vol_lookback", 50))
        vol_threshold = float(self.params.get("vol_threshold", 1.5))
        vol_multiplier = float(self.params.get("vol_multiplier", 1.5))
        if len(ohlcv_atr) >= vol_lookback:
            atr_series = (ohlcv_atr["high"] - ohlcv_atr["low"]).rolling(atr_period).mean()
            atr_ma = float(atr_series.rolling(vol_lookback).mean().iloc[-1])
            if not np.isnan(atr_ma) and atr_ma > 0 and atr > atr_ma * vol_threshold:
                vol_factor = vol_multiplier
                logger.info("High volatility: ATR=%.2f > %.1fx MA(%.2f) → SL x%.1f", atr, vol_threshold, atr_ma, vol_factor)

        # Appliquer le facteur de volatilité aux paramètres de sortie
        min_atr_dist = float(self.params.get("min_atr_dist", 1.0))
        _exit_mult = atr_mult * vol_factor
        _min_dist = min_atr_dist * vol_factor

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
                new_sl = self._calc_chandelier_sl(ohlcv_ch, action, atr, lookback, _exit_mult)
            else:
                new_sl = self._calc_trailing_sl(current_close, action, atr, _exit_mult)

            logger.info(
                "posmgr [%s] %s %s: entry=%.2f cur_sl=%.2f new_sl=%.2f atr=%.2f vol=%.1f",
                symbol, trade_id, action, entry, current_sl, new_sl, atr, vol_factor,
            )

            # Le SL ne doit jamais reculer (LONG: monte, SHORT: descend)
            # + distance minimale de breathing room (_min_dist × ATR)
            if action == "long":
                new_sl = max(new_sl, current_sl, 0.01) if current_sl > 0 else max(new_sl, 0.01)
                new_sl = min(new_sl, entry - _min_dist * atr)  # breathing room
                hit_raw = current_sl > 0 and current_low <= current_sl
            else:
                if current_sl > 0:
                    new_sl = min(new_sl, current_sl)
                if entry > 0:
                    new_sl = max(new_sl, entry + _min_dist * atr)
                hit_raw = current_sl > 0 and current_high >= current_sl

            # ── Multi-TF filter : ne fermer que si la tendance 1h confirme ──
            use_multi_tf = bool(self.params.get("use_multi_tf", True))
            hit = hit_raw
            if hit_raw and use_multi_tf and ohlcv_1h is not None and len(ohlcv_1h) >= 55:
                close_1h = ohlcv_1h["close"]
                sma20 = float(close_1h.rolling(20).mean().iloc[-1])
                sma50 = float(close_1h.rolling(50).mean().iloc[-1])
                trend_1h = "bullish" if sma20 > sma50 else "bearish"
                # Ne fermer un SHORT que si la tendance 1h passe bullish
                # Ne fermer un LONG que si la tendance 1h passe bearish
                if action == "short" and trend_1h != "bullish":
                    hit = False
                    logger.info("posmgr multi-TF: SL hit but 1h trend still %s → HOLD", trend_1h)
                elif action == "long" and trend_1h != "bearish":
                    hit = False
                    logger.info("posmgr multi-TF: SL hit but 1h trend still %s → HOLD", trend_1h)

            # ── Percent giveback : tracker le gain max ──
            giveback_pct = float(self.params.get("giveback_pct", 0.0))
            if giveback_pct > 0 and not hit:
                if action == "long":
                    max_favorable = max(entry, current_close)  # simplifié: best = max(entry, current)
                    giveback_sl = max_favorable - (max_favorable - entry) * (giveback_pct / 100.0)
                    if current_low <= giveback_sl and current_sl > 0:
                        hit = True
                        new_sl = giveback_sl
                        logger.info("posmgr giveback: gave back %.1f%% → CLOSE", giveback_pct)
                else:
                    max_favorable = min(entry, current_close)
                    giveback_sl = max_favorable + (entry - max_favorable) * (giveback_pct / 100.0)
                    if current_high >= giveback_sl and current_sl > 0:
                        hit = True
                        new_sl = giveback_sl
                        logger.info("posmgr giveback: gave back %.1f%% → CLOSE", giveback_pct)

            if hit:
                close_price = current_sl
                if action == "long":
                    pnl = (close_price - entry) / entry * float(pos.get("size_usd", 0))
                else:
                    pnl = (entry - close_price) / entry * float(pos.get("size_usd", 0))

                # Raison détaillée pour les logs
                reason_parts = [strategy]
                if use_multi_tf:
                    reason_parts.append("multiTF")
                if giveback_pct > 0:
                    reason_parts.append(f"giveback{giveback_pct:.0f}%")
                if vol_factor > 1.0:
                    reason_parts.append(f"vol{vol_factor:.1f}x")
                reason = "+".join(reason_parts)

                close_position(trade_id, close_price, round(pnl, 4), reason)
                closed_this_cycle.append({
                    "trade_id": trade_id, "symbol": symbol, "action": action,
                    "entry_price": entry, "close_price": close_price,
                    "pnl_usd": round(pnl, 4), "reason": reason,
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
