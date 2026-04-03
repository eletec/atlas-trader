"""
agents/fear_greed_agent.py — Fear & Greed Index (alternative.me) + On-chain signals.
API gratuite, sans clé, mise à jour quotidienne.
Score 0-100 : 0 = peur extrême, 100 = avidité extrême.
Signal contrarien : peur extrême → opportunité d'achat.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("zeitgeist.fear_greed")


class FearGreedAgent:
    """Agent Fear & Greed — signal contrarien basé sur l'indice alternative.me."""

    def analyze(self, state: dict) -> dict:
        try:
            from utils.http_session import get_http_session
            resp = get_http_session().get(
                "https://api.alternative.me/fng/?limit=3&format=json",
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if not data:
                return self._fallback("données vides")

            current = data[0]
            fng_value = int(current.get("value", 50))
            fng_label = current.get("value_classification", "Neutral")

            # Signal contrarien : peur → bullish, avidité → bearish
            # Score trader = inverse de la peur (achat quand peur extrême)
            if fng_value <= 25:
                # Peur extrême → signal d'achat fort (contrarien)
                trader_score = 75 + (25 - fng_value)  # 75-100
                signal = "BULLISH"
            elif fng_value <= 45:
                # Peur → légèrement haussier
                trader_score = 55 + (45 - fng_value) / 2  # 55-65
                signal = "BULLISH"
            elif fng_value <= 55:
                # Neutre
                trader_score = 50.0
                signal = "NEUTRAL"
            elif fng_value <= 75:
                # Avidité → légèrement baissier
                trader_score = 45 - (fng_value - 55) / 2  # 35-45
                signal = "BEARISH"
            else:
                # Avidité extrême → signal de vente (contrarien)
                trader_score = max(20, 40 - (fng_value - 75))  # 20-40
                signal = "BEARISH"

            # Tendance sur 3 jours si disponible
            trend = ""
            if len(data) >= 3:
                prev = int(data[2].get("value", fng_value))
                diff = fng_value - prev
                trend = f" (tendance: {'↑' if diff > 0 else '↓'}{abs(diff):+d} sur 3j)"

            summary = (
                f"Fear & Greed Index: {fng_value}/100 — {fng_label}{trend}. "
                f"Signal contrarien: {'ACHAT (peur extrême)' if signal == 'BULLISH' else 'VENTE (avidité extrême)' if signal == 'BEARISH' else 'NEUTRE'}"
            )

            logger.info(f"Fear&Greed: {fng_value} ({fng_label}) → trader_score={trader_score:.0f} [{signal}]")

            return {
                "agent_name": "fear_greed",
                "score": round(trader_score, 1),
                "signal": signal,
                "summary": summary,
                "confidence": 0.75,
                "raw_fng": fng_value,
            }

        except Exception as exc:
            logger.warning(f"FearGreedAgent échoué: {exc}")
            return self._fallback(str(exc))

    @staticmethod
    def _fallback(reason: str) -> dict:
        return {
            "agent_name": "fear_greed",
            "score": 50.0,
            "signal": "NEUTRAL",
            "summary": f"Fear & Greed indisponible: {reason}",
            "confidence": 0.0,
        }
