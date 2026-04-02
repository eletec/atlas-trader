"""
agents/air_du_temps_builder.py — Construction du document AirDuTemps.
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger("zeitgeist.air_du_temps")


class AirDuTempsBuilder:
    """Consolide les sources crawler + news en un document AirDuTemps."""

    def build(self, crawler_docs: list[dict], news_items: list[dict]) -> dict:
        """Construit l'AirDuTemps complet depuis les sources."""
        themes = [doc.get("theme", "") for doc in crawler_docs]
        all_content = []

        for doc in crawler_docs:
            for result in doc.get("results", [])[:3]:
                content = result.get("content", "").strip()
                if content:
                    all_content.append(f"[{doc['theme']}] {content}")

        # Ajouter les top news
        for news in news_items[:10]:
            summary = news.get("summary", "").strip()
            if summary:
                all_content.append(f"[NEWS] {news.get('title', '')} — {summary}")

        full_text = "\n\n".join(all_content)[:4000]

        return {
            "themes": themes[:8],
            "full_text": full_text,
            "key_signals": self._extract_signals(full_text),
            "generated_at": datetime.utcnow().isoformat(),
            "sources_count": len(crawler_docs) + len(news_items),
        }

    def build_from_news_only(self, news_items: list[dict]) -> dict:
        """Mode dégradé : construit depuis les news uniquement."""
        texts = [
            f"{n.get('title', '')} — {n.get('summary', '')}"
            for n in news_items[:20]
        ]
        return {
            "themes": ["news_only"],
            "full_text": "\n".join(texts)[:2000],
            "key_signals": self._extract_signals(" ".join(texts)),
            "generated_at": datetime.utcnow().isoformat(),
            "sources_count": len(news_items),
        }

    @staticmethod
    def _extract_signals(text: str) -> list[str]:
        """Extrait des signaux clés simples depuis le texte."""
        signal_words = {
            "bullish": ["rally", "surge", "adoption", "breakout", "record", "bull"],
            "bearish": ["crash", "ban", "regulation", "dump", "panic", "sell-off"],
            "macro": ["inflation", "fed", "interest rate", "recession", "gdp"],
            "crypto": ["bitcoin", "ethereum", "defi", "etf", "halving", "institutional"],
        }
        signals = []
        text_lower = text.lower()
        for category, words in signal_words.items():
            count = sum(1 for w in words if w in text_lower)
            if count >= 2:
                signals.append(f"{category}:{count}")
        return signals[:5]
