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
        return {"decision": "dict", "symbol": "str"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"trade_result": "dict"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        # testnet est un invariant — jamais overridé à False depuis l'UI
        testnet = True  # noqa: non configurable

        decision: dict = inputs.get("decision", {})
        symbol: str    = inputs.get("symbol") or self.params.get("symbol", "BTC/USDT")
        action: str    = decision.get("action", "flat")

        if action == "flat":
            return {"trade_result": {"status": "flat", "symbol": symbol}}

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
            )
            return {"trade_result": {"status": "opened", "trade_id": trade_id, "symbol": symbol,
                                      "action": action, "entry_price": entry_price}}
        except ImportError:
            logger.warning("storage.paper_trader non disponible — trade log-only")
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
    Params  : table (str — nom de la table SQLite, défaut "shadow_decisions")
    """

    @property
    def node_type(self) -> str:
        return "RecordDecision"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"decision": "dict"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        import json
        import sqlite3
        import time

        decision = inputs.get("decision", {})
        table    = self.params.get("table", "shadow_decisions")
        db_path  = self.params.get("db_path", "/app/data/v4.db")

        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} "
                    "(id INTEGER PRIMARY KEY, ts REAL, data TEXT)"
                )
                conn.execute(
                    f"INSERT INTO {table} (ts, data) VALUES (?, ?)",
                    (time.time(), json.dumps(decision)),
                )
        except Exception as exc:
            logger.warning("RecordDecision failed: %s", exc)

        return {}
