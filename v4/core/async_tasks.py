"""
v4/core/async_tasks.py — Dispatcher de tâches IA en arrière-plan.

Permet aux nœuds IA (LLMNode, DebateNode) de lancer leurs appels
en mode fire-and-forget. Le cycle DAG n'attend pas la réponse —
le résultat est stocké et disponible au cycle suivant.

Thread-safe. Utilise ThreadPoolExecutor.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Any, Callable

logger = logging.getLogger("v4.core.async_tasks")

## Shared pool - max 10 workers to avoid saturating the LLM API
_pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="ai_async_")
_cache: dict[str, dict[str, Any]] = {}
_cache_lock = threading.Lock()
_pending: dict[str, Future] = {}
_pending_lock = threading.Lock()


def dispatch(key: str, fn: Callable[[], dict[str, Any]]) -> None:
    """Lance `fn()` en arrière-plan. Le résultat est accessible via get_result(key)."""
    def _run_and_store():
        try:
            result = fn()
            with _cache_lock:
                _cache[key] = result
            logger.info("Async task %s completed (%d keys in cache)", key, len(_cache))
        except Exception as exc:
            logger.warning("Async task %s failed: %s", key, exc)
            with _cache_lock:
                _cache[key] = {"error": str(exc), "status": "failed"}
        finally:
            with _pending_lock:
                _pending.pop(key, None)

    with _pending_lock:
        # Do not restart when already running
        if key in _pending:
            if not _pending[key].done():
                logger.info("Async task %s still pending, skipping dispatch", key)
                return  # already running, let it finish
        future = _pool.submit(_run_and_store)
        _pending[key] = future
        logger.info("Async task %s dispatched (pending=%d)", key, len(_pending))


def get_result(key: str) -> dict[str, Any] | None:
    """Récupère le résultat du dernier appel async pour cette clé, ou None."""
    with _cache_lock:
        return _cache.get(key)


def is_pending(key: str) -> bool:
    """Vérifie si une tâche est en cours pour cette clé."""
    with _pending_lock:
        fut = _pending.get(key)
        return fut is not None and not fut.done()


def clear_cache():
    """Vide le cache (utile au reset)."""
    with _cache_lock:
        _cache.clear()
    with _pending_lock:
        _pending.clear()
