"""
agents/central_bank_agent.py — Agent Banques Centrales (BCE, Fed, BOE, BOJ…).

Collecte et analyse :
  - Derniers communiqués de presse officiels (RSS + web scraping léger)
  - Décisions de taux récentes
  - Orientations de politique monétaire (forward guidance)
  - Minutes/PV des réunions

Sources :
  - BCE : ecb.europa.eu/rss/press.html
  - Fed : federalreserve.gov/feeds/press_all.xml
  - BOE : bankofengland.co.uk/rss/publications
  - BOJ : boj.or.jp (RSS si disponible)

Retourne : score de biais de politique monétaire [0-100]
  50 = neutre, >60 = dovish (→ bullish EUR/USD), <40 = hawkish (→ bearish EUR/USD)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("zeitgeist.central_bank")

# Banques centrales et leurs flux RSS
_CB_FEEDS = {
    "ECB": "https://www.ecb.europa.eu/rss/press.html",
    "FED": "https://www.federalreserve.gov/feeds/press_all.xml",
    "BOE": "https://www.bankofengland.co.uk/rss/publications",
}

# Mots-clés de ton dovish (haussier EUR/USD car Fed moins agressif)
_DOVISH_KEYWORDS = [
    "cut", "ease", "easing", "accommodation", "dovish", "stimulus", "support",
    "inflation below target", "pause", "hold", "slower", "gradual",
]
# Mots-clés hawkish (baissier EUR/USD car Fed agressif → USD fort)
_HAWKISH_KEYWORDS = [
    "hike", "raise", "tightening", "hawkish", "restrictive", "above target",
    "reduce balance sheet", "quantitative tightening", "qt", "higher for longer",
]


class CentralBankAgent:
    """
    Analyse les communiqués des banques centrales et leur impact sur le Forex.
    Interface identique à analyze() → retourne un dict d'agent.
    """

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        self._llm_cfg = cfg.get("llm", {})

    def analyze(self, state: dict) -> dict:
        asset = state.get("asset", "EUR/USD")
        air = state.get("air_du_temps") or {}

        try:
            feed_items = self._fetch_cb_communications(asset)
            if not feed_items:
                return self._neutral("Aucun communiqué de banque centrale récent détecté")

            rule_result = self._rule_based(feed_items, asset)
            llm_result = self._analyze_with_llm(feed_items, asset, air)
            blended = round(llm_result["score"] * 0.7 + rule_result["score"] * 0.3, 1)
            return {
                "agent_name": "central_bank",
                "score": blended,
                "signal": (
                    "BULLISH" if blended > 60
                    else ("BEARISH" if blended < 40 else "NEUTRAL")
                ),
                "summary": llm_result["summary"],
                "confidence": round(
                    llm_result["confidence"] * 0.7 + rule_result["confidence"] * 0.3, 2
                ),
                "cb_items": feed_items[:3],
            }
        except Exception as exc:
            logger.warning(f"CentralBankAgent fallback: {exc}")
            return self._neutral(f"Erreur collecte CB : {exc}")

    # ------------------------------------------------------------------ #
    #  Data collection                                                     #
    # ------------------------------------------------------------------ #

    def _fetch_cb_communications(self, asset: str) -> list[dict]:
        """
        Sélectionne les banques centrales pertinentes selon l'actif,
        puis collecte leurs 5 dernières communications (J-14).
        """
        import feedparser

        # Sélectionner les CB pertinentes
        if "EUR" in asset:
            cbs = {"ECB": _CB_FEEDS["ECB"], "FED": _CB_FEEDS["FED"]}
        elif "GBP" in asset:
            cbs = {"BOE": _CB_FEEDS.get("BOE", ""), "FED": _CB_FEEDS["FED"]}
        elif "JPY" in asset:
            cbs = {"BOJ": "https://www.boj.or.jp/en/rss/index.htm", "FED": _CB_FEEDS["FED"]}
        else:
            cbs = {"FED": _CB_FEEDS["FED"]}

        items: list[dict] = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=14)

        for cb_name, url in cbs.items():
            if not url:
                continue
            try:
                feed = feedparser.parse(url)
                for entry in (feed.entries or [])[:10]:
                    title = str(entry.get("title", "")).strip()
                    if not title:
                        continue
                    pub = entry.get("published_parsed") or entry.get("updated_parsed")
                    dt = datetime(*pub[:6], tzinfo=timezone.utc) if pub else now
                    if dt < cutoff:
                        continue
                    summary = str(entry.get("summary", ""))[:300]
                    items.append({
                        "cb": cb_name,
                        "title": title,
                        "summary": summary,
                        "date": dt.strftime("%Y-%m-%d"),
                    })
            except Exception as exc:
                logger.debug(f"CB {cb_name} feed {url}: {exc}")

        # Trier par date décroissante
        items.sort(key=lambda x: x["date"], reverse=True)
        return items[:10]

    # ------------------------------------------------------------------ #
    #  Rule-based                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _rule_based(items: list[dict], asset: str) -> dict:
        """Scoring par comptage de mots-clés hawkish/dovish."""
        if not items:
            return {"score": 50.0, "confidence": 0.2}

        hawk_count = 0
        dove_count = 0
        for item in items:
            text = (item["title"] + " " + item["summary"]).lower()
            hawk_count += sum(1 for kw in _HAWKISH_KEYWORDS if kw in text)
            dove_count += sum(1 for kw in _DOVISH_KEYWORDS if kw in text)

        total = hawk_count + dove_count
        if total == 0:
            return {"score": 50.0, "confidence": 0.3}

        # Pour EUR/USD :
        #   dovish FED + hawkish ECB → bullish EUR (score > 60)
        #   hawkish FED + dovish ECB → bearish EUR (score < 40)
        # Ici on simplifie : tone global dovish = bullish EUR/USD
        dove_ratio = dove_count / total
        score = 30 + dove_ratio * 40  # 30 (hawkish) → 70 (dovish)
        return {"score": round(score, 1), "confidence": min(0.7, 0.3 + total * 0.05)}

    # ------------------------------------------------------------------ #
    #  LLM analysis                                                        #
    # ------------------------------------------------------------------ #

    def _analyze_with_llm(
        self, items: list[dict], asset: str, air: dict
    ) -> dict:
        items_text = "\n".join(
            f"- [{item['cb']} {item['date']}] {item['title']}"
            for item in items[:6]
        )
        air_summary = (air.get("summary", "N/A") or "N/A")[:300]
        base, quote = asset.split("/") if "/" in asset else (asset, "USD")

        prompt = (
            f"You are a central bank expert analyzing impact on {asset}.\n\n"
            f"Recent central bank communications (last 14 days):\n{items_text}\n\n"
            f"Global context:\n{air_summary}\n\n"
            f"Assess the aggregate monetary policy stance and its directional impact on {asset}. "
            f"BULLISH means {base} strengthens vs {quote} (e.g. ECB hawkish + Fed dovish). "
            f"Give conviction score [0-100].\n\n"
            "Respond in strict JSON:\n"
            '{"score": <0-100>, "signal": "BULLISH"|"NEUTRAL"|"BEARISH", '
            '"summary": "<2-3 sentences max>", "confidence": <0.0-1.0>}'
        )

        provider = self._llm_cfg.get("provider", "anthropic")
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(timeout=60.0)
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
            client = OpenAI(api_key=os.environ.get(api_key_env, ""), base_url=base_url, timeout=60)
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
            "summary": str(d.get("summary", "Analyse banques centrales LLM")),
            "confidence": float(d.get("confidence", 0.65)),
        }

    @staticmethod
    def _neutral(reason: str) -> dict:
        return {
            "agent_name": "central_bank",
            "score": 50.0,
            "signal": "NEUTRAL",
            "summary": reason,
            "confidence": 0.2,
        }
