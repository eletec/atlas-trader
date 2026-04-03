"""
agents/broad_web_crawler.py — Crawl thématique via Tavily + Firecrawl.
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger("zeitgeist.crawler")


class BroadWebCrawler:
    """Crawl les thèmes macro via Tavily ou Firecrawl."""

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        crawler_cfg = cfg.get("crawler", {})
        self.provider: str = crawler_cfg.get("provider", "tavily")
        self.fallback: str = crawler_cfg.get("fallback_provider", "serpapi")
        self.n_themes: int = crawler_cfg.get("n_themes", 10)
        self.max_pages: int = crawler_cfg.get("max_pages_per_theme", 10)
        self.templates: list = crawler_cfg.get("templates", [])
        self.timeout: int = crawler_cfg.get("request_timeout_seconds", 15)
        self.llm_model: str = crawler_cfg.get("llm_summarizer_model",
                                                "claude-3-5-haiku-20241022")

    def crawl_themes(self, asset: str = "BTC/USDT") -> list[dict]:
        """Crawle tous les thèmes configurés et retourne les documents bruts."""
        year = datetime.utcnow().year
        docs = []

        for template in self.templates[:self.n_themes]:
            # S7: rejette les templates contenant des patterns d'IP privée (SSRF)
            _t_lower = template.lower()
            if any(p in _t_lower for p in ("localhost", "127.0.", "192.168.", "10.", "172.16.", "file://", "gopher://")):
                logger.warning(f"Template rejeté (SSRF potentiel): {template[:80]}")
                continue
            query = template.replace("{asset}", asset.split("/")[0]).replace("{year}", str(year))
            try:
                results = self._search(query)
                if results:
                    docs.append({"theme": query, "results": results})
            except Exception as exc:
                logger.warning(f"Thème '{query}' échoué: {exc}")

        logger.info(f"Crawler: {len(docs)} thèmes récupérés")
        return docs

    def _search(self, query: str) -> list[dict]:
        """Recherche via le provider configuré."""
        if self.provider == "claude_web_search":
            return self._search_claude_web(query)
        elif self.provider == "tavily":
            return self._search_tavily(query)
        elif self.provider == "firecrawl":
            return self._search_firecrawl(query)
        elif self.provider == "duckduckgo":
            return self._search_duckduckgo(query)
        return self._search_fallback(query)

    def _search_claude_web(self, query: str) -> list[dict]:
        """
        CA1 — Recherche via Claude WebSearchTool (BetaWebSearchTool20250305).
        Claude effectue lui-meme la recherche et synthetise les resultats.
        Necessite anthropic>=0.40 et acces au beta 'web-search-2025-03-05'.
        Cout : ~$0.01-0.03 par requete.
        Provider : 'claude_web_search' dans settings.yaml crawler.provider
        """
        try:
            import anthropic
            client = anthropic.Anthropic()
            response = client.beta.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=2048,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{
                    "role": "user",
                    "content": (
                        f"Recherche et synthetise les informations les plus importantes "
                        f"sur ce sujet pour un trader BTC/USDT : '{query}'. "
                        "Reponds avec un resume factuel de 2-3 paragraphes des sources les plus recentes."
                    ),
                }],
                betas=["web-search-2025-03-05"],
            )
            # Extraire le texte de la reponse finale (pas les tool_use blocks)
            text_parts = [
                block.text for block in response.content
                if hasattr(block, "text") and block.text
            ]
            summary = " ".join(text_parts).strip()
            if summary:
                return [{"title": query, "content": summary[:2000], "url": "", "score": 0.9}]
        except Exception as exc:
            logger.warning(f"Claude WebSearch echoue sur '{query}': {exc}")
            # Fallback DuckDuckGo
            return self._search_duckduckgo(query)
        return []

    def _search_duckduckgo(self, query: str) -> list[dict]:
        """Recherche DuckDuckGo — gratuit, sans clé API."""
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
            return [
                {"title": r.get("title", ""), "content": r.get("body", "")[:1000],
                 "url": r.get("href", ""), "score": 0.5}
                for r in results
            ]
        except Exception as exc:
            logger.warning(f"DuckDuckGo échoué: {exc}")
            return []

    def _search_tavily(self, query: str) -> list[dict]:
        from utils.config import get_env
        from tavily import TavilyClient
        client = TavilyClient(api_key=get_env("TAVILY_API_KEY"))
        response = client.search(query, max_results=5, search_depth="basic")
        return [
            {"title": r.get("title", ""), "content": r.get("content", "")[:1000],
             "url": r.get("url", ""), "score": r.get("score", 0)}
            for r in response.get("results", [])
        ]

    def _search_firecrawl(self, query: str) -> list[dict]:
        from utils.config import get_env
        from firecrawl import FirecrawlApp
        app = FirecrawlApp(api_key=get_env("FIRECRAWL_API_KEY"))
        response = app.search(query, params={"limit": 5})
        return [
            {"title": r.get("title", ""), "content": r.get("markdown", "")[:1000],
             "url": r.get("url", ""), "score": 0.5}
            for r in (response.get("data") or [])
        ]

    def _search_fallback(self, query: str) -> list[dict]:
        """Recherche simple via SerpAPI."""
        try:
            from utils.config import get_env
            import requests
            api_key = get_env("SERPAPI_API_KEY", required=False)
            if not api_key:
                return []
            resp = requests.get(
                "https://serpapi.com/search",
                params={"q": query, "api_key": api_key, "num": 5},
                timeout=self.timeout
            )
            results = resp.json().get("organic_results", [])
            return [
                {"title": r.get("title", ""), "content": r.get("snippet", ""),
                 "url": r.get("link", ""), "score": 0.3}
                for r in results
            ]
        except Exception as exc:
            logger.error(f"Fallback search échoué: {exc}")
            return []
