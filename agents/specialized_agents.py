"""
agents/fundamental_agent.py + contrarian_agent.py + x_sentiment_agent.py
Agents d'analyse spécialisés — stubs complets et fonctionnels.
"""
from __future__ import annotations
import logging

# Chaque agent est dans son propre fichier par convention,
# mais regroupés ici pour la lisibilité du prototype.


####################################################################
# FUNDAMENTAL AGENT
####################################################################
# agents/fundamental_agent.py

logger_fund = logging.getLogger("zeitgeist.fundamental")


class FundamentalAgent:
    """Analyse les fondamentaux on-chain et macro-économiques."""

    def analyze(self, state: dict) -> dict:
        """Retourne une analyse fondamentale basée sur les indicateurs disponibles."""
        indicators = state.get("market_indicators", {}) or {}
        score = 50.0
        signals = []

        # --- 1. Funding rate (coût des longs/shorts) ---
        funding = indicators.get("funding_rate", 0)
        if funding < -0.005:
            score += 15
            signals.append(f"Funding négatif ({funding:.4f}) — shorts surexposés")
        elif funding < 0:
            score += 5
            signals.append(f"Funding légèrement négatif ({funding:.4f})")
        elif funding > 0.02:
            score -= 15
            signals.append(f"Funding élevé ({funding:.4f}) — longs surexposés")
        elif funding > 0.005:
            score -= 5
            signals.append(f"Funding modéré ({funding:.4f})")

        # --- 2. RSI (momentum) ---
        rsi = indicators.get("rsi_14", 50)
        if rsi <= 30:
            score += 15
            signals.append(f"RSI survente ({rsi:.0f})")
        elif rsi <= 40:
            score += 8
            signals.append(f"RSI bas ({rsi:.0f})")
        elif rsi >= 70:
            score -= 15
            signals.append(f"RSI surachat ({rsi:.0f})")
        elif rsi >= 60:
            score -= 5
            signals.append(f"RSI élevé ({rsi:.0f})")

        # --- 3. MACD momentum ---
        macd = indicators.get("macd", 0)
        macd_signal = indicators.get("macd_signal", 0)
        if macd and macd_signal:
            macd_diff = macd - macd_signal
            if macd_diff > 0 and macd > 0:
                score += 8
                signals.append(f"MACD haussier ({macd:.2f}>{macd_signal:.2f})")
            elif macd_diff < 0 and macd < 0:
                score -= 8
                signals.append(f"MACD baissier ({macd:.2f}<{macd_signal:.2f})")

        # --- 4. Position par rapport à MA50 ---
        price = indicators.get("price", 0)
        ma_50 = indicators.get("ma_50", 0)
        if price and ma_50:
            pct_from_ma50 = (price - ma_50) / ma_50 * 100
            if pct_from_ma50 > 5:
                score -= 5
                signals.append(f"Prix +{pct_from_ma50:.1f}% au-dessus MA50")
            elif pct_from_ma50 > 0:
                score += 5
                signals.append(f"Prix au-dessus MA50 (+{pct_from_ma50:.1f}%)")
            elif pct_from_ma50 > -5:
                score -= 5
                signals.append(f"Prix sous MA50 ({pct_from_ma50:.1f}%)")
            else:
                score -= 10
                signals.append(f"Prix {pct_from_ma50:.1f}% sous MA50")

        # --- 5. Bollinger Bands (volatilité + position) ---
        bb_upper = indicators.get("bb_upper", 0)
        bb_lower = indicators.get("bb_lower", 0)
        if price and bb_upper and bb_lower and bb_upper > bb_lower:
            bb_pos = (price - bb_lower) / (bb_upper - bb_lower)
            if bb_pos < 0.15:
                score += 8
                signals.append(f"Prix proche bande basse BB ({bb_pos:.0%})")
            elif bb_pos > 0.85:
                score -= 8
                signals.append(f"Prix proche bande haute BB ({bb_pos:.0%})")

        # --- 6. Volume 24h ---
        volume = indicators.get("volume_24h", 0)
        if volume > 3e9:
            score += 5
            signals.append(f"Volume très élevé ({volume/1e9:.1f}B$)")
        elif volume > 1.5e9:
            score += 3
            signals.append(f"Volume solide ({volume/1e9:.1f}B$)")

        score = max(0, min(100, score))
        signal = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")

        logger_fund.debug(f"Fundamental score={score:.0f} signals={signals}")
        return {
            "agent_name": "fundamental",
            "score": round(score, 1),
            "signal": signal,
            "summary": " | ".join(signals) if signals else "Fondamentaux neutres",
            "confidence": 0.7,
        }


####################################################################
# CONTRARIAN AGENT
####################################################################
# agents/contrarian_agent.py

logger_ctr = logging.getLogger("zeitgeist.contrarian")


class ContrarianAgent:
    """
    Détecte les extrêmes de sentiment pour signaler des inversions potentielles.
    Fear & Greed Index + long/short ratio.
    """

    def analyze(self, state: dict) -> dict:
        """Retourne une analyse contrarian."""
        fear_greed = self._get_fear_greed()
        score = 50.0
        signals = []

        if fear_greed is not None:
            if fear_greed <= 20:
                score = 75  # extrême peur → signal haussier contrarian
                signals.append(f"Fear & Greed extrême peur ({fear_greed}) → signal ACHAT")
            elif fear_greed >= 80:
                score = 25  # extrême euphorie → signal baissier contrarian
                signals.append(f"Fear & Greed euphorie ({fear_greed}) → signal VENTE")
            else:
                score = 50
                signals.append(f"Fear & Greed neutre ({fear_greed})")

        signal = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
        logger_ctr.debug(f"Contrarian score={score:.0f}")
        return {
            "agent_name": "contrarian",
            "score": round(score, 1),
            "signal": signal,
            "summary": " | ".join(signals) if signals else "Sentiment neutre",
            "confidence": 0.5,
            "fear_greed_index": fear_greed,
        }

    @staticmethod
    def _get_fear_greed() -> int | None:
        """Récupère le Fear & Greed Index depuis l'API Alternative.me."""
        try:
            import requests
            resp = requests.get(
                "https://api.alternative.me/fng/?limit=1",
                timeout=5
            )
            data = resp.json()
            return int(data["data"][0]["value"])
        except Exception:
            return None


####################################################################
# X SENTIMENT AGENT
####################################################################
# agents/x_sentiment_agent.py

logger_sent = logging.getLogger("zeitgeist.x_sentiment")


class XSentimentAgent:
    """Analyse le sentiment des news via scoring VADER."""

    def analyze(self, state: dict) -> dict:
        """Retourne un score de sentiment basé sur les news."""
        news_items = state.get("news_items", [])
        if not news_items:
            return {
                "agent_name": "x_sentiment",
                "score": 50.0,
                "signal": "NEUTRAL",
                "summary": "Aucune news disponible pour l'analyse sentiment",
                "confidence": 0.1,
            }

        scores = []
        for item in news_items[:20]:
            text = item.get("title", "") + " " + item.get("summary", "")
            s = self._vader_score(text)
            scores.append(s)

        mean_compound = sum(scores) / len(scores)
        # Normaliser de [-1, 1] vers [0, 100]
        normalized = (mean_compound + 1) / 2 * 100

        signal = "BULLISH" if normalized > 60 else ("BEARISH" if normalized < 40 else "NEUTRAL")
        logger_sent.debug(f"Sentiment score={normalized:.0f} ({len(scores)} articles)")
        return {
            "agent_name": "x_sentiment",
            "score": round(normalized, 1),
            "signal": signal,
            "summary": (
                f"Sentiment moyen: {mean_compound:+.3f} sur {len(scores)} articles "
                f"({'positif' if mean_compound > 0.05 else 'négatif' if mean_compound < -0.05 else 'neutre'})"
            ),
            "confidence": min(0.7, len(scores) / 20),
        }

    @staticmethod
    def _vader_score(text: str) -> float:
        """Score VADER compound [-1, 1]."""
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            return SentimentIntensityAnalyzer().polarity_scores(text)["compound"]
        except ImportError:
            # Fallback: scoring basé sur mots-clés simples
            positive = ["bull", "rally", "growth", "up", "gain", "positive", "pump"]
            negative = ["bear", "crash", "down", "loss", "negative", "dump", "fear"]
            text_lower = text.lower()
            pos = sum(1 for w in positive if w in text_lower)
            neg = sum(1 for w in negative if w in text_lower)
            total = pos + neg + 1
            return (pos - neg) / total
