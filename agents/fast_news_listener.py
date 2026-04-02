"""
agents/fast_news_listener.py — Collecte RSS + NewsAPI + CryptoPanic + Reddit.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("zeitgeist.fast_news")

# Fichier de persistance pour le timestamp NewsAPI (survit aux redémarrages)
_NEWSAPI_STATE_FILE = Path(os.getenv("STORAGE_DIR", "/app/storage")) / "newsapi_state.json"
_NEWSAPI_MIN_INTERVAL_HOURS = 24   # 1 appel/jour max — quota gratuit préservé
_NEWSAPI_BLACKOUT_HOURS = 72       # après 2 x 429 consécutifs → pause 3 jours
_NEWSAPI_LOCK = threading.Lock()   # évite la race condition multi-threads
_cryptopanic_last_call: datetime | None = None
_CRYPTOPANIC_MIN_INTERVAL_MINUTES = 15  # évite le rate-limit en mode fast-monitor


def _newsapi_load_state() -> dict:
    """Lit l'état persisté du NewsAPI."""
    try:
        if _NEWSAPI_STATE_FILE.exists():
            return json.loads(_NEWSAPI_STATE_FILE.read_text())
    except Exception:
        pass
    return {}


def _newsapi_save_state(state: dict) -> None:
    """Persiste l'état du NewsAPI."""
    try:
        _NEWSAPI_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _NEWSAPI_STATE_FILE.write_text(json.dumps(state))
    except Exception as exc:
        logger.debug(f"NewsAPI state save échoué: {exc}")


# Compat alias pour code existant
def _newsapi_load_last_call() -> datetime | None:
    ts = _newsapi_load_state().get("last_call")
    return datetime.fromisoformat(ts) if ts else None


def _newsapi_save_last_call(ts: datetime) -> None:
    state = _newsapi_load_state()
    state["last_call"] = ts.isoformat()
    _newsapi_save_state(state)


class FastNewsListener:
    """Collecte les news depuis RSS, CryptoPanic, Reddit et NewsAPI."""

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        news_cfg = cfg.get("news", {})
        self.keywords = news_cfg.get("keywords_per_asset", {})
        self.rss_sources = news_cfg.get("sources_rss", [])
        self.max_items = news_cfg.get("max_items_per_cycle", 30)
        self.threshold = news_cfg.get("relevance_score_threshold", 0.4)
        self.nitter_accounts = news_cfg.get("sources_nitter", [
            "saylor", "BitcoinMagazine", "whale_alert", "woonomic", "CryptoHayes",
            "RayDalio", "zerohedge", "LynAldenContact", "WuBlockchain", "colin_wu_",
        ])
        self.reddit_subs = news_cfg.get("sources_reddit", ["Bitcoin", "CryptoCurrency", "btc"])
        cp_cfg = news_cfg.get("cryptopanic", {})
        self.cryptopanic_enabled = cp_cfg.get("enabled", True)
        self.cryptopanic_max = int(cp_cfg.get("max_items", 15))

    def fetch_all(self, asset: str = "BTC/USDT") -> list[dict]:
        """Collecte toutes les sources et retourne une liste dédupliquée."""
        all_items = []

        # RSS (sources configurées + sources crypto fixes)
        for rss_url in self.rss_sources:
            try:
                items = self._fetch_rss(rss_url)
                all_items.extend(items)
                logger.info(f"RSS {rss_url.split('/')[2]}: {len(items)} articles")
            except Exception as exc:
                logger.warning(f"RSS {rss_url} échoué: {exc}")

        # CryptoPanic et NewsAPI gérés plus bas avec cache rate-limit

        # Reddit RSS — subreddits configurés
        for subreddit in self.reddit_subs:
            try:
                items = self._fetch_rss(f"https://www.reddit.com/r/{subreddit}/hot.rss")
                all_items.extend(items)
                logger.info(f"Reddit r/{subreddit}: {len(items)} posts")
            except Exception as exc:
                logger.warning(f"Reddit r/{subreddit} échoué: {exc}")

        # Nitter RSS — comptes X configurés (instances publiques)
        for account in self.nitter_accounts:
            try:
                items = self._fetch_rss(f"https://nitter.net/{account}/rss")
                all_items.extend(items)
                logger.info(f"Nitter @{account}: {len(items)} tweets")
            except Exception as exc:
                logger.debug(f"Nitter @{account} échoué: {exc}")

        # CryptoPanic — rate-limit : 1 appel / 15min max
        # (le fast_monitor_loop appelle fetch_all toutes les 60s → cache obligatoire)
        global _cryptopanic_last_call
        now = datetime.utcnow()
        if self.cryptopanic_enabled:
            cp_ok = (
                _cryptopanic_last_call is None
                or (now - _cryptopanic_last_call).total_seconds() > _CRYPTOPANIC_MIN_INTERVAL_MINUTES * 60
            )
            if cp_ok:
                try:
                    items = self._fetch_cryptopanic()
                    all_items.extend(items)
                    _cryptopanic_last_call = now
                    logger.info(f"CryptoPanic: {len(items)} articles")
                except Exception as exc:
                    logger.warning(f"CryptoPanic échoué: {exc}")
            else:
                remaining = int(_CRYPTOPANIC_MIN_INTERVAL_MINUTES * 60 - (now - _cryptopanic_last_call).total_seconds())
                logger.debug(f"CryptoPanic ignoré (cache actif, {remaining}s restantes)")

        # NewsAPI — plan gratuit limité
        # Lock multi-thread + compteur 429 consécutifs → blackout auto
        with _NEWSAPI_LOCK:
            state = _newsapi_load_state()
            last_call_ts = state.get("last_call")
            consecutive_429 = int(state.get("consecutive_429", 0))
            last_call = datetime.fromisoformat(last_call_ts) if last_call_ts else None

            # Calcul de l'intervalle requis : blackout si trop de 429
            required_hours = _NEWSAPI_BLACKOUT_HOURS if consecutive_429 >= 2 else _NEWSAPI_MIN_INTERVAL_HOURS
            newsapi_ok = last_call is None or (now - last_call).total_seconds() > required_hours * 3600

            if not newsapi_ok:
                remaining_h = required_hours - (now - last_call).total_seconds() / 3600
                if consecutive_429 >= 2:
                    logger.debug(f"NewsAPI en blackout ({consecutive_429} x 429) — encore {remaining_h:.1f}h")
                else:
                    logger.debug(f"NewsAPI ignoré (intervalle {required_hours}h) — encore {remaining_h:.1f}h")
            else:
                try:
                    items = self._fetch_newsapi(asset)
                    if items:
                        all_items.extend(items)
                    state["last_call"] = now.isoformat()
                    state["consecutive_429"] = 0
                    _newsapi_save_state(state)
                    logger.info(f"NewsAPI: {len(items)} articles")
                except Exception as exc:
                    logger.warning(f"NewsAPI échoué: {exc}")
                    if "429" in str(exc):
                        consecutive_429 += 1
                        state["last_call"] = now.isoformat()
                        state["consecutive_429"] = consecutive_429
                        _newsapi_save_state(state)
                        if consecutive_429 >= 2:
                            logger.warning(
                                f"NewsAPI: {consecutive_429} x 429 consécutifs — "
                                f"blackout {_NEWSAPI_BLACKOUT_HOURS}h activé"
                            )
                    else:
                        state["last_call"] = now.isoformat()
                        _newsapi_save_state(state)

        # Déduplication par URL
        seen_urls = set()
        unique = []
        for item in all_items:
            url = item.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                unique.append(item)

        # Scoring et filtrage
        keywords = self.keywords.get(asset, [])
        scored = [
            {**item, "relevance_score": self._score(item, keywords)}
            for item in unique
        ]
        filtered = [
            i for i in scored if i["relevance_score"] >= self.threshold
        ]
        filtered.sort(key=lambda x: x["relevance_score"], reverse=True)

        result = filtered[:self.max_items]
        logger.info(f"{len(result)} news pertinentes collectées (/{len(unique)} totales)")
        return result

    def _fetch_cryptopanic(self) -> list[dict]:
        """CryptoPanic public feed — gratuit, sans clé API."""
        import requests
        response = requests.get(
            "https://cryptopanic.com/api/free/v1/posts/",
            params={"auth_token": "free", "currencies": "BTC", "kind": "news"},
            timeout=10,
            headers={"User-Agent": "AtlasTrader/1.0"}
        )
        if response.status_code != 200:
            return []
        results = response.json().get("results", [])
        items = []
        for r in results[:15]:
            items.append({
                "title": r.get("title", ""),
                "source": r.get("source", {}).get("title", "CryptoPanic"),
                "url": r.get("url", ""),
                "published_at": r.get("published_at", ""),
                "summary": r.get("title", "")[:500],
                "relevance_score": 0.0,
            })
        return items

    def _fetch_rss(self, url: str) -> list[dict]:
        import feedparser
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:10]:
            published = entry.get("published", datetime.utcnow().isoformat())
            items.append({
                "title": entry.get("title", ""),
                "source": feed.feed.get("title", url),
                "url": entry.get("link", ""),
                "published_at": str(published),
                "summary": entry.get("summary", "")[:500],
                "relevance_score": 0.0,
            })
        return items

    def _fetch_newsapi(self, asset: str) -> list[dict]:
        from utils.config import get_env
        import requests
        api_key = get_env("NEWSAPI_KEY", required=False)
        if not api_key:
            return []
        keywords = self.keywords.get(asset, ["bitcoin"])
        q = " OR ".join(keywords[:3])
        response = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": q, "apiKey": api_key,
                "sortBy": "publishedAt", "pageSize": 20,
                "language": "en",
                "from": (datetime.utcnow() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S"),
            },
            timeout=10
        )
        if response.status_code == 429:
            raise Exception(f"429 Too Many Requests (quota NewsAPI dépassé)")
        response.raise_for_status()
        articles = response.json().get("articles", [])
        return [
            {
                "title": a.get("title", ""),
                "source": a.get("source", {}).get("name", "NewsAPI"),
                "url": a.get("url", ""),
                "published_at": a.get("publishedAt", ""),
                "summary": a.get("description", "")[:500],
                "relevance_score": 0.0,
            }
            for a in articles
        ]

    @staticmethod
    def _score(item: dict, keywords: list[str]) -> float:
        """Score de pertinence basé sur la présence des mots-clés."""
        text = (item.get("title", "") + " " + item.get("summary", "")).lower()
        if not text.strip():
            return 0.0
        matches = sum(1 for kw in keywords if kw.lower() in text)
        return min(1.0, matches / max(len(keywords), 1) * 2)
