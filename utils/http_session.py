"""
utils/http_session.py — Session requests partagée (P5).
Évite la création d'une nouvelle connexion TCP à chaque requête HTTP.
Pool de connexions + retry automatique avec backoff.
"""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_SESSION: requests.Session | None = None


def get_http_session() -> requests.Session:
    """Return the shared requests session (read-safe singleton)."""
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=2,
                backoff_factor=0.3,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(["GET"]),
            ),
            pool_connections=10,
            pool_maxsize=20,
        )
        _SESSION.mount("https://", adapter)
        _SESSION.mount("http://", adapter)
        _SESSION.headers.update({"User-Agent": "AtlasTrader/1.0"})
    return _SESSION
