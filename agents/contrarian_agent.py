"""
agents/contrarian_agent.py — Detection des extremes de sentiment (contrarian).
Utilise le ratio Long/Short Open Interest Binance Futures au lieu du Fear & Greed
(evite le doublon avec FearGreedAgent qui appelle deja alternative.me/fng).
"""
from __future__ import annotations
import logging

logger = logging.getLogger("zeitgeist.contrarian")


class ContrarianAgent:
    """
    Detecte les extremes de positionnement pour signaler des inversions potentielles.
    Utilise le Long/Short Account Ratio Binance Futures (API publique, sans cle).
    """

    def analyze(self, state: dict) -> dict:
        """Retourne une analyse contrarian basee sur le ratio long/short."""
        ls_ratio = self._get_long_short_ratio()
        score = 50.0
        signals = []

        if ls_ratio is not None:
            if ls_ratio > 1.5:
                # Trop de longs : risque de liquidation en cascade -> signal BEARISH
                score = 28
                signals.append(
                    f"Longs surexeposes (L/S={ls_ratio:.2f}) — risque de liquidation en cascade"
                )
            elif ls_ratio > 1.2:
                score = 38
                signals.append(f"Longs dominants (L/S={ls_ratio:.2f}) — prudence")
            elif ls_ratio < 0.7:
                # Trop de shorts : short squeeze probable -> signal BULLISH
                score = 75
                signals.append(
                    f"Shorts surexeposes (L/S={ls_ratio:.2f}) — short squeeze probable"
                )
            elif ls_ratio < 0.85:
                score = 62
                signals.append(f"Shorts dominants (L/S={ls_ratio:.2f}) — pression haussiere")
            else:
                score = 50
                signals.append(f"Ratio long/short equilibre (L/S={ls_ratio:.2f})")
        else:
            # Fallback : Fear & Greed si Binance injoignable
            fg = self._get_fear_greed_fallback()
            if fg is not None:
                if fg <= 20:
                    score = 75
                    signals.append(f"Fear & Greed extreme peur ({fg}) — signal ACHAT")
                elif fg >= 80:
                    score = 25
                    signals.append(f"Fear & Greed euphorie ({fg}) — signal VENTE")
                else:
                    score = 50
                    signals.append(f"Fear & Greed neutre ({fg})")
            else:
                signals.append("Donnees de positionnement indisponibles")

        signal = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
        logger.debug(f"Contrarian score={score:.0f} ls_ratio={ls_ratio}")
        return {
            "agent_name": "contrarian",
            "score": round(score, 1),
            "signal": signal,
            "summary": " | ".join(signals) if signals else "Positionnement neutre",
            "confidence": 0.65 if ls_ratio is not None else 0.4,
            "long_short_ratio": ls_ratio,
        }

    @staticmethod
    def _get_long_short_ratio(symbol: str = "BTCUSDT") -> float | None:
        """
        Long/Short Account Ratio depuis Binance Futures (API publique, sans cle API).
        Retourne ls_ratio = long_ratio / short_ratio.
        """
        try:
            from utils.http_session import get_http_session
            resp = get_http_session().get(
                "https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
                params={"symbol": symbol, "period": "1h", "limit": 3},
                timeout=6,
            )
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, list):
                latest = data[0]
                long_ratio = float(latest.get("longAccount", 0.5))
                short_ratio = float(latest.get("shortAccount", 0.5))
                if short_ratio > 0:
                    return round(long_ratio / short_ratio, 3)
        except Exception as exc:
            logger.debug(f"Binance L/S ratio indisponible: {exc}")
        return None

    @staticmethod
    def _get_fear_greed_fallback() -> int | None:
        """Fallback Fear & Greed si l'API Binance est indisponible."""
        try:
            from utils.http_session import get_http_session
            resp = get_http_session().get(
                "https://api.alternative.me/fng/?limit=1",
                timeout=5,
            )
            data = resp.json()
            return int(data["data"][0]["value"])
        except Exception:
            return None
