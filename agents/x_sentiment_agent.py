"""
agents/x_sentiment_agent.py — Analyse du sentiment des news via Claude Haiku.
Remplace VADER par un LLM conscient du vocabulaire crypto (rekt, ath, hodl...).
Cout estime : ~$0.001/cycle x 96 cycles/jour = ~$0.10/jour.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("zeitgeist.x_sentiment")


class XSentimentAgent:
    """Analyse le sentiment des news via Claude Haiku (ou fallback lexical)."""

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        self._llm_cfg = cfg.get("llm", {})

    def analyze(self, state: dict) -> dict:
        """Retourne un score de sentiment base sur les news."""
        news_items = state.get("news_items", [])
        if not news_items:
            return {
                "agent_name": "x_sentiment",
                "score": 50.0,
                "signal": "NEUTRAL",
                "summary": "Aucune news disponible pour l'analyse sentiment",
                "confidence": 0.1,
            }

        items = news_items[:20]
        try:
            result = self._analyze_with_llm(items)
        except Exception as exc:
            logger.warning(f"LLM sentiment fallback (lexical): {exc}")
            result = self._analyze_lexical(items)

        logger.debug(
            f"Sentiment score={result['score']:.0f} signal={result['signal']} "
            f"confidence={result['confidence']:.2f}"
        )
        return result

    def _analyze_with_llm(self, news_items: list[dict]) -> dict:
        """Appel Claude Haiku pour une analyse sentiment consciente du contexte crypto."""
        titles = "\n".join(
            f"- {n.get('title', '')}" for n in news_items if n.get("title")
        )
        n = len(news_items)
        prompt = (
            f"Analyse le sentiment de ces {n} titres de news crypto/Bitcoin.\n\n"
            f"{titles}\n\n"
            "Reponds en JSON strict :\n"
            '{"score": <0-100>, "signal": "BULLISH"|"NEUTRAL"|"BEARISH", '
            '"dominant_themes": ["..."], "confidence": <0.0-1.0>}\n\n'
            "Score : 0=tres baissier, 50=neutre, 100=tres haussier. "
            "Tiens compte du vocabulaire crypto (rekt=bearish, ath=bullish, hodl=neutre, etc.)"
        )

        provider = self._llm_cfg.get("provider", "anthropic")

        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
        else:
            # Fallback DeepSeek / OpenAI-compatible
            from openai import OpenAI
            base_url = None
            api_key_env = "OPENAI_API_KEY"
            model = self._llm_cfg.get("model", "gpt-4o-mini")
            if provider == "deepseek":
                base_url = "https://api.deepseek.com/v1"
                api_key_env = "DEEPSEEK_API_KEY"
                model = "deepseek-chat"
            import os
            client = OpenAI(api_key=os.environ.get(api_key_env, ""), base_url=base_url)
            resp = client.chat.completions.create(
                model=model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content.strip()

        # Extraire le JSON (le LLM peut parfois ajouter du texte avant/apres)
        json_start = raw.find("{")
        json_end = raw.rfind("}") + 1
        data = json.loads(raw[json_start:json_end])

        score = float(data.get("score", 50))
        signal = str(data.get("signal", "NEUTRAL")).upper()
        if signal not in ("BULLISH", "BEARISH", "NEUTRAL"):
            signal = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
        themes = data.get("dominant_themes", [])
        confidence = float(data.get("confidence", 0.7))

        return {
            "agent_name": "x_sentiment",
            "score": round(score, 1),
            "signal": signal,
            "summary": (
                f"LLM sentiment {signal} ({score:.0f}/100) — "
                f"themes: {', '.join(str(t) for t in themes[:3])}"
            ),
            "confidence": round(confidence, 2),
        }

    @staticmethod
    def _analyze_lexical(news_items: list[dict]) -> dict:
        """Fallback lexical si le LLM est indisponible."""
        positive = ["bull", "rally", "growth", "gain", "pump", "ath", "adoption", "etf"]
        negative = ["bear", "crash", "loss", "dump", "fear", "hack", "ban", "rekt"]
        scores = []
        for item in news_items:
            text = (item.get("title", "") + " " + item.get("summary", "")).lower()
            pos = sum(1 for w in positive if w in text)
            neg = sum(1 for w in negative if w in text)
            total = pos + neg + 1
            scores.append((pos - neg) / total)

        mean = sum(scores) / len(scores) if scores else 0.0
        normalized = round((mean + 1) / 2 * 100, 1)
        signal = "BULLISH" if normalized > 60 else ("BEARISH" if normalized < 40 else "NEUTRAL")
        return {
            "agent_name": "x_sentiment",
            "score": normalized,
            "signal": signal,
            "summary": f"Lexical sentiment {signal} ({normalized:.0f}/100) sur {len(scores)} articles",
            "confidence": round(min(0.5, len(scores) / 20), 2),
        }
