"""
v4/core/async_tasks.py — Background dispatcher for AI tasks.

Lets the AI nodes (LLMNode, DebateNode) start their calls
in fire-and-forget mode. The DAG cycle does not wait for the answer —
the result is stored and available on the next cycle.

Thread-safe. Uses a ThreadPoolExecutor.
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
    """Run `fn()` in the background. The result is available through get_result(key)."""
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
    """Fetch the result of the last async call for this key, or None."""
    with _cache_lock:
        return _cache.get(key)


def is_pending(key: str) -> bool:
    """Check whether a task is running for this key."""
    with _pending_lock:
        fut = _pending.get(key)
        return fut is not None and not fut.done()


def clear_cache():
    """Clear the cache (useful on reset)."""
    with _cache_lock:
        _cache.clear()
    with _pending_lock:
        _pending.clear()
