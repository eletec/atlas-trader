"""
utils/notifier.py — Systeme d'alertes Telegram / Discord.

Configuration dans settings.yaml :
  logging:
    telegram_enabled: true
    telegram_token: "BOT_TOKEN"          # ou env var TELEGRAM_BOT_TOKEN
    telegram_chat_id: "CHAT_ID"          # ou env var TELEGRAM_CHAT_ID
    discord_enabled: true
    discord_webhook_url: "WEBHOOK_URL"   # ou env var DISCORD_WEBHOOK_URL
    alert_score_threshold: 85

Usage :
  from utils.notifier import get_notifier
  notifier = get_notifier()
  if notifier:
      notifier.notify_decision(decision, score)
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("zeitgeist.notifier")


class TelegramNotifier:
    """Notificateur Telegram via bot token."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id

    def notify(self, message: str) -> None:
        """Envoie un message Telegram."""
        try:
            from utils.http_session import get_http_session
            resp = get_http_session().post(
                self._url,
                json={"chat_id": self._chat_id, "text": message, "parse_mode": "HTML"},
                timeout=8,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning(f"Telegram notify echoue: {exc}")

    def notify_decision(self, decision: dict, score: float) -> None:
        """Formate et envoie une notification de decision de trading."""
        action = decision.get("action", "HOLD")
        emoji = "&#x1F7E2;" if action == "BUY" else ("&#x1F534;" if action == "SELL" else "&#x1F7E1;")
        entry = decision.get("entry_price", 0)
        sl = decision.get("sl_price", 0)
        tp = decision.get("tp_price", 0)
        size = decision.get("position_size_usd", 0)
        asset = decision.get("asset", "BTC/USDT")

        msg = (
            f"{emoji} <b>{action} {asset}</b>\n"
            f"Score : {score:.0f}/100\n"
            f"Entree : ${entry:,.0f}\n"
        )
        if sl:
            msg += f"SL : ${sl:,.0f} | TP : ${tp:,.0f}\n"
        if size:
            msg += f"Taille : ${size:.0f}"
        self.notify(msg)


class DiscordNotifier:
    """Notificateur Discord via webhook."""

    def __init__(self, webhook_url: str) -> None:
        self._url = webhook_url

    def notify(self, message: str) -> None:
        """Envoie un message Discord."""
        try:
            from utils.http_session import get_http_session
            resp = get_http_session().post(
                self._url,
                json={"content": message},
                timeout=8,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning(f"Discord notify echoue: {exc}")

    def notify_decision(self, decision: dict, score: float) -> None:
        """Formate et envoie une notification de decision de trading."""
        action = decision.get("action", "HOLD")
        emoji = ":green_circle:" if action == "BUY" else (":red_circle:" if action == "SELL" else ":yellow_circle:")
        entry = decision.get("entry_price", 0)
        sl = decision.get("sl_price", 0)
        tp = decision.get("tp_price", 0)
        size = decision.get("position_size_usd", 0)
        asset = decision.get("asset", "BTC/USDT")

        msg = (
            f"{emoji} **{action} {asset}**\n"
            f"Score : {score:.0f}/100\n"
            f"Entree : ${entry:,.0f}\n"
        )
        if sl:
            msg += f"SL : ${sl:,.0f} | TP : ${tp:,.0f}\n"
        if size:
            msg += f"Taille : ${size:.0f}"
        self.notify(msg)


class CompositeNotifier:
    """Notificateur composite : Telegram + Discord."""

    def __init__(self, notifiers: list[Any]) -> None:
        self._notifiers = notifiers

    def notify(self, message: str) -> None:
        for n in self._notifiers:
            n.notify(message)

    def notify_decision(self, decision: dict, score: float) -> None:
        for n in self._notifiers:
            n.notify_decision(decision, score)


_notifier_instance: Any | None = None
_notifier_loaded: bool = False


def get_notifier() -> CompositeNotifier | None:
    """
    Retourne le notificateur global (singleton) configure depuis settings.yaml.
    Retourne None si toutes les notifications sont desactivees.
    """
    global _notifier_instance, _notifier_loaded
    if _notifier_loaded:
        return _notifier_instance

    try:
        from utils.config import load_settings
        cfg = load_settings()
        log_cfg = cfg.get("logging", {})
        notifiers = []

        # --- Telegram ---
        if log_cfg.get("telegram_enabled", False):
            token = (
                os.environ.get("TELEGRAM_BOT_TOKEN")
                or log_cfg.get("telegram_token", "")
            )
            chat_id = (
                os.environ.get("TELEGRAM_CHAT_ID")
                or str(log_cfg.get("telegram_chat_id", ""))
            )
            if token and chat_id:
                notifiers.append(TelegramNotifier(token=token, chat_id=chat_id))
                logger.info("Telegram notifications activees")
            else:
                logger.warning(
                    "telegram_enabled=true mais TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID manquants"
                )

        # --- Discord ---
        if log_cfg.get("discord_enabled", False):
            webhook = (
                os.environ.get("DISCORD_WEBHOOK_URL")
                or log_cfg.get("discord_webhook_url", "")
            )
            if webhook:
                notifiers.append(DiscordNotifier(webhook_url=webhook))
                logger.info("Discord notifications activees")
            else:
                logger.warning(
                    "discord_enabled=true mais DISCORD_WEBHOOK_URL manquant"
                )

        _notifier_instance = CompositeNotifier(notifiers) if notifiers else None
    except Exception as exc:
        logger.error(f"Erreur initialisation notifier: {exc}")
        _notifier_instance = None

    _notifier_loaded = True
    return _notifier_instance


def should_notify(score: float) -> bool:
    """Retourne True si le score depasse le seuil d'alerte configure."""
    try:
        from utils.config import load_settings
        cfg = load_settings()
        threshold = cfg.get("logging", {}).get("alert_score_threshold", 85)
        return score >= threshold or score <= (100 - threshold)
    except Exception:
        return score >= 85 or score <= 15
