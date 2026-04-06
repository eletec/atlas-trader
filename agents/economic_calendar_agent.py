"""
agents/economic_calendar_agent.py — Agent calendrier économique.

Sources (sans clé API) :
  - Investing.com RSS        : événements forex/macro (via feedparser)
  - FXStreet RSS             : calendrier économique
  - Fed/BCE communiqués RSS  : décisions taux directeurs

Pertinent pour : XAU/USD, EUR/USD, GBP/USD, USD/JPY

L'agent retourne :
  - score d'impact anticipé [0-100] : 50=neutre, >60=bullish macro (→ haussier actif)
  - liste des événements J-2 / J+2 avec impact (High/Medium/Low)
  - analyse du sentiment autour des événements à venir
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("zeitgeist.economic_calendar")

_TIMEOUT = 10

# Mots-clés d'événements par pertinence pour l'or/forex
_HIGH_IMPACT_KEYWORDS = [
    "nonfarm", "nfp", "cpi", "inflation", "fed", "fomc", "rate decision",
    "interest rate", "ecb", "bce", "boj", "boe", "gdp", "unemployment",
    "retail sales", "pmi",
]
_GOLD_BEARISH_EVENTS = ["rate hike", "hawkish", "taper", "balance sheet reduction"]
_GOLD_BULLISH_EVENTS = ["rate cut", "dovish", "quantitative easing", "qe", "stimulus"]


class EconomicCalendarAgent:
    """
    Agent de calendrier économique macro.
    Filtre les événements high-impact dans J-2/J+2 et estime leur
    impact directionnel sur l'actif.
    """

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        self._llm_cfg = cfg.get("llm", {})

    def analyze(self, state: dict) -> dict:
        asset = state.get("asset", "XAU/USD")
        air = state.get("air_du_temps") or {}

        try:
            events = self._fetch_upcoming_events()
            if not events:
                return self._neutral("Aucun événement macro détecté dans la fenêtre J-2/J+2")

            rule_result = self._rule_based(events, asset)
            llm_result = self._analyze_with_llm(events, asset, air)
            blended = round(llm_result["score"] * 0.7 + rule_result["score"] * 0.3, 1)
            return {
                "agent_name": "economic_calendar",
                "score": blended,
                "signal": (
                    "BULLISH" if blended > 60
                    else ("BEARISH" if blended < 40 else "NEUTRAL")
                ),
                "summary": llm_result["summary"],
                "confidence": round(
                    llm_result["confidence"] * 0.7 + rule_result["confidence"] * 0.3, 2
                ),
                "upcoming_events": events[:5],
            }
        except Exception as exc:
            logger.warning(f"EconomicCalendarAgent fallback: {exc}")
            return self._neutral(f"Calendrier indisponible : {exc}")

    # ------------------------------------------------------------------ #
    #  Event collection                                                    #
    # ------------------------------------------------------------------ #

    def _fetch_upcoming_events(self) -> list[dict]:
        """
        Collecte les événements depuis les flux RSS économiques.
        Retourne une liste de dicts {title, source, date, impact}.
        """
        import feedparser

        sources = [
            # FXStreet calendrier économique RSS
            ("https://rss.fxstreet.com/fxs-new-economic-calendar-high.xml", "fxstreet-high"),
            # Reuters RSS macro (économique)
            ("https://feeds.reuters.com/reuters/businessNews", "reuters"),
            # ECB press releases
            ("https://www.ecb.europa.eu/rss/press.html", "ecb"),
        ]

        events: list[dict] = []
        now = datetime.now(timezone.utc)
        window_past = now - timedelta(days=2)
        window_future = now + timedelta(days=2)

        for url, source_name in sources:
            try:
                feed = feedparser.parse(url)
                for entry in (feed.entries or [])[:20]:
                    title = str(entry.get("title", "")).strip()
                    if not title:
                        continue

                    # Tenter de parser la date
                    pub = entry.get("published_parsed") or entry.get("updated_parsed")
                    if pub:
                        dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    else:
                        dt = now

                    if not (window_past <= dt <= window_future):
                        continue

                    title_lower = title.lower()
                    impact = "low"
                    if any(kw in title_lower for kw in _HIGH_IMPACT_KEYWORDS):
                        impact = "high"

                    events.append({
                        "title": title,
                        "source": source_name,
                        "date": dt.strftime("%Y-%m-%d %H:%M"),
                        "impact": impact,
                    })
            except Exception as exc:
                logger.debug(f"Calendrier {url}: {exc}")

        # Déduplique par titre approché
        seen: set[str] = set()
        unique: list[dict] = []
        for e in events:
            key = e["title"][:60].lower()
            if key not in seen:
                seen.add(key)
                unique.append(e)

        # Tri par impact (high en premier) puis par date
        unique.sort(key=lambda e: (0 if e["impact"] == "high" else 1, e["date"]))
        return unique

    # ------------------------------------------------------------------ #
    #  Rule-based                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _rule_based(events: list[dict], asset: str) -> dict:
        """Estimation basique de l'impact macro sur l'actif."""
        score = 50.0
        high_events = [e for e in events if e["impact"] == "high"]

        if not high_events:
            return {"score": 50.0, "confidence": 0.3}

        # Pour XAU : événements hawkish = bearish, dovish = bullish
        for e in high_events:
            title_lower = e["title"].lower()
            if asset in ("XAU/USD",):
                if any(kw in title_lower for kw in _GOLD_BEARISH_EVENTS):
                    score -= 12
                elif any(kw in title_lower for kw in _GOLD_BULLISH_EVENTS):
                    score += 12
                # CPI élevé = bullish or (inflation hedge)
                if "cpi" in title_lower or "inflation" in title_lower:
                    score += 5
                if "rate decision" in title_lower or "fomc" in title_lower:
                    score -= 5  # incertitude Fed = léger négatif
            elif asset in ("EUR/USD",):
                if "ecb" in title_lower and "rate" in title_lower:
                    score += 5  # décisions BCE favorables EUR

        score = max(0.0, min(100.0, score))
        return {"score": round(score, 1), "confidence": 0.5}

    # ------------------------------------------------------------------ #
    #  LLM analysis                                                        #
    # ------------------------------------------------------------------ #

    def _analyze_with_llm(self, events: list[dict], asset: str, air: dict) -> dict:
        events_text = "\n".join(
            f"- [{e['impact'].upper()}] {e['title']} ({e['date']}, {e['source']})"
            for e in events[:8]
        )
        air_summary = (air.get("summary", "N/A") or "N/A")[:300]

        prompt = (
            f"You are a macro analyst specialized in {asset}.\n\n"
            f"Upcoming macro events (±2 days):\n{events_text}\n\n"
            f"General context:\n{air_summary}\n\n"
            f"Assess the likely directional impact on {asset} from these events. "
            f"Give a conviction score [0-100] for going LONG right now.\n\n"
            "Respond in strict JSON:\n"
            '{"score": <0-100>, "signal": "BULLISH"|"NEUTRAL"|"BEARISH", '
            '"summary": "<2-3 sentences max>", "confidence": <0.0-1.0>}'
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
                model=model, max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content.strip()

        json_start = raw.find("{")
        json_end = raw.rfind("}") + 1
        d = json.loads(raw[json_start:json_end])
        score = float(d.get("score", 50))
        signal = str(d.get("signal", "NEUTRAL")).upper()
        if signal not in ("BULLISH", "BEARISH", "NEUTRAL"):
            signal = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
        return {
            "score": round(score, 1),
            "signal": signal,
            "summary": str(d.get("summary", "Analyse calendrier macro LLM")),
            "confidence": float(d.get("confidence", 0.6)),
        }

    @staticmethod
    def _neutral(reason: str) -> dict:
        return {
            "agent_name": "economic_calendar",
            "score": 50.0,
            "signal": "NEUTRAL",
            "summary": reason,
            "confidence": 0.2,
            "upcoming_events": [],
        }
