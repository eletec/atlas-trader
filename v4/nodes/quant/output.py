"""
v4/nodes/quant/output.py — Nœuds PaperTrader + AlertOnly + RecordDecision

Wrappers V4 des nœuds de sortie.
PaperTrader délègue à storage.paper_trader (V3) sans le modifier.
"""
from __future__ import annotations

import logging
from typing import Any

from v4.core.node import Node

logger = logging.getLogger("v4.nodes.quant.output")


class PaperTrader(Node):
    """
    Exécute la décision en paper trading (testnet ou DB locale).

    Inputs  :
        decision  (dict  — sortie de RiskATR)
        symbol    (str   — optionnel, surchargé par params)

    Outputs :
        trade_result (dict — {status, trade_id, pnl_usd})

    Params :
        symbol    : str   — paire ex. "BTC/USDT"
        capital   : float — capital total en USD
        testnet   : bool  — toujours True par défaut (invariant de sécurité)
    """

    @property
    def node_type(self) -> str:
        return "PaperTrader"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"decision": "dict", "symbol": "str", "max_positions": "int"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"trade_result": "dict"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        # testnet is an invariant - never overridden to False from the UI
        testnet = True  # noqa: non configurable

        decision: dict = inputs.get("decision", {})
        symbol: str    = inputs.get("symbol") or self.params.get("symbol", "BTC/USDT")
        action: str    = decision.get("action", "flat")

        if action == "flat":
            return {"trade_result": {"status": "flat", "symbol": symbol}}

        # ── Actions de fermeture (close_carry, close, close_long, close_short) ──
        if action in ("close_carry", "close", "close_long", "close_short"):
            try:
                from storage.paper_trader import get_open_positions, close_position
                open_positions = get_open_positions(symbol=symbol)
                if not open_positions:
                    logger.info("PaperTrader [%s] close_carry: no open position", symbol)
                    return {"trade_result": {"status": "no_position", "symbol": symbol}}
                # Close the first open position (or all of them)
                closed = []
                for pos in open_positions:
                    trade_id = pos["trade_id"]
                    pnl_usd = float(pos.get("pnl_usd", 0) or 0)
                    close_price = decision.get("entry_price", 0) or decision.get("close_price", 0)
                    if close_price <= 0:
                        # Fallback: fetch spot price
                        try:
                            import ccxt
                            ex = ccxt.binance()
                            ticker = ex.fetch_ticker(symbol)
                            close_price = float(ticker.get("last", 0))
                        except Exception:
                            close_price = float(pos.get("entry_price", 0))
                    # Compute the P&L
                    pos_action = pos.get("action", "long")
                    entry = float(pos.get("entry_price", 0))
                    size = float(pos.get("size_usd", 0))
                    if pos_action in ("short", "carry"):
                        pnl = (entry - close_price) / entry * size
                    else:
                        pnl = (close_price - entry) / entry * size
                    ok = close_position(trade_id, close_price, round(pnl, 4),
                                        f"signal_{action}")
                    if ok:
                        closed.append(trade_id)
                        logger.info("PaperTrader [%s] CLOSE %s @ %.2f pnl=$%.2f (%s)",
                                   symbol, trade_id, close_price, pnl, action)
                return {"trade_result": {"status": "closed", "symbol": symbol,
                                          "closed_ids": closed, "close_price": close_price}}
            except ImportError:
                logger.warning("PaperTrader [%s] close_carry: storage.paper_trader unavailable", symbol)
                return {"trade_result": {"status": "error", "symbol": symbol, "reason": "storage unavailable"}}

        # -- Concurrent position limit (pyramiding control) --
        # Priority: AssetDef input > DAG params > default 1
        max_positions = int(inputs.get("max_positions") or self.params.get("max_positions", 1))
        if max_positions > 0:
            try:
                from storage.paper_trader import get_open_positions
                open_count = len(get_open_positions(symbol=symbol))
                if open_count >= max_positions:
                    logger.info(
                        "PaperTrader [%s] skip %s: %d/%d positions déjà ouvertes",
                        symbol, action, open_count, max_positions,
                    )
                    return {"trade_result": {"status": "skipped", "symbol": symbol,
                                              "reason": f"max_positions={max_positions} reached ({open_count} open)"}}
            except Exception:
                pass  # si la DB n'est pas dispo, on continue sans limite

        entry_price = decision.get("entry_price", 0)
        stop_loss   = decision.get("stop_loss", 0)
        take_profit = decision.get("take_profit", 0)
        size_usd    = decision.get("size_usd", 0)
        size_units  = decision.get("size_units", 0)
        atr         = decision.get("atr", 0)

        logger.info(
            "PaperTrader [%s] %s @ %.4f  SL=%.4f  TP=%.4f  size=%.2f$",
            symbol, action, entry_price, stop_loss, take_profit, size_usd,
        )

        # Persistance en BDD via storage/paper_trader.py
        dag_id = self.params.get("dag_id", "demo_v4")
        try:
            from storage.paper_trader import persist_trade
            trade_id = persist_trade(
                symbol=symbol,
                action=action,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                size_usd=size_usd,
                size_units=size_units,
                atr=atr,
                testnet=testnet,
                dag_id=dag_id,
                context=decision,  # full traceability of the decision context
            )
            return {"trade_result": {"status": "opened", "trade_id": trade_id, "symbol": symbol,
                                      "action": action, "entry_price": entry_price}}
        except ImportError:
            logger.warning("storage.paper_trader not available — trade log-only")
            return {"trade_result": {"status": "logged_only", "decision": decision}}


class AlertOnly(Node):
    """
    Publie une alerte (Telegram / Discord / log) sans exécuter de trade.

    Inputs  : decision (dict)
    Outputs : (aucun — nœud terminal)

    Params :
        channel : "log" | "telegram" | "discord"
        prefix  : str — préfixe du message (ex: "[BTC] ")
    """

    @property
    def node_type(self) -> str:
        return "AlertOnly"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"decision": "dict"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        decision = inputs.get("decision", {})
        channel  = self.params.get("channel", "log")
        prefix   = self.params.get("prefix", "")
        msg = f"{prefix}{decision}"

        if channel == "log":
            logger.info("AlertOnly: %s", msg)
        elif channel == "telegram":
            self._send_telegram(msg)
        elif channel == "discord":
            self._send_discord(msg)

        return {}

    def _send_telegram(self, msg: str) -> None:
        try:
            import httpx
            token   = self.params.get("telegram_token", "")
            chat_id = self.params.get("telegram_chat_id", "")
            if token and chat_id:
                httpx.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg},
                    timeout=5,
                )
        except Exception as exc:
            logger.warning("Telegram alert failed: %s", exc)

    def _send_discord(self, msg: str) -> None:
        try:
            import httpx
            webhook = self.params.get("discord_webhook", "")
            if webhook:
                httpx.post(webhook, json={"content": msg}, timeout=5)
        except Exception as exc:
            logger.warning("Discord alert failed: %s", exc)


class RecordDecision(Node):
    """
    Enregistre la décision dans SQLite sans exécuter de trade.
    Utile pour comparer des stratégies en shadow mode.

    Inputs  : decision (dict)
    Params  : 
        table      (str — nom de la table, défaut "shadow_decisions")
        db_path    (str — chemin DB)
        symbol     (str — actif concerné)
        dag_id     (str — DAG parent)
    """

    @property
    def node_type(self) -> str:
        return "RecordDecision"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"decision": "dict", "trade_result": "dict"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"decision_id": "int"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        import json
        import sqlite3
        import time

        decision = inputs.get("decision", {})
        trade_result = inputs.get("trade_result", {})
        table    = self.params.get("table", "shadow_decisions")
        # Safety: validate the table name (alphanumeric + underscore whitelist)
        import re as _re
        if not _re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table):
            raise ValueError(f"Invalid table name: {table!r}")
        db_path  = self.params.get("db_path", "/app/data/v4.db")
        symbol   = self.params.get("symbol", decision.get("symbol", ""))
        dag_id   = self.params.get("dag_id", "")
        # Fetch the trade_id from the PaperTrader result (trade to decision link)
        trade_id = trade_result.get("trade_id", "") or decision.get("trade_id", "")

        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} "
                    "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    " ts REAL, symbol TEXT, dag_id TEXT, trade_id TEXT, data TEXT)"
                )
                # Add the missing columns when the table already exists (migration)
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN symbol TEXT")
                except sqlite3.OperationalError:
                    pass  # column already exists
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN dag_id TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN trade_id TEXT")
                except sqlite3.OperationalError:
                    pass

                cursor = conn.execute(
                    f"INSERT INTO {table} (ts, symbol, dag_id, trade_id, data) VALUES (?, ?, ?, ?, ?)",
                    (time.time(), symbol, dag_id, trade_id, json.dumps(decision)),
                )
                decision_id = cursor.lastrowid
        except Exception as exc:
            logger.warning("RecordDecision failed: %s", exc)
            decision_id = 0

        return {"decision_id": decision_id}
