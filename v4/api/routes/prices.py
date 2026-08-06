"""
v4/api/routes/prices.py — Route SSE pour le flux de prix en temps réel.

GET /prices/stream — Server-Sent Events
  Paramètre query: symbols (csv) ex: "BTC/USDT,ETH/USDT"

Flux d'événements :
  event: price
  data: {"symbol": "BTC/USDT", "price": 67432.5, "ts": 1717430000.0}

Architecture :
  Binance WebSocket (ccxt.pro) → asyncio → PriceStore → SSE → EventSource
  Le flux est partagé entre tous les clients connectés (un seul WS par symbole).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()
logger = logging.getLogger("v4.api.routes.prices")


# ------------------------------------------------------------------
# PriceStore — cache en mémoire, mis à jour par le ticker WS
# ------------------------------------------------------------------

class PriceStore:
    """Stocke le dernier prix connu pour chaque symbole."""

    _instance: "PriceStore | None" = None

    def __init__(self) -> None:
        self._prices: dict[str, dict] = {}
        self._listeners: list[asyncio.Queue] = []

    @classmethod
    def instance(cls) -> "PriceStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def update(self, symbol: str, price: float, ts: float | None = None) -> None:
        record = {"symbol": symbol, "price": price, "ts": ts or time.time()}
        self._prices[symbol] = record
        # Notifie tous les listeners SSE
        dead = []
        for q in self._listeners:
            try:
                q.put_nowait(record)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._listeners.remove(q)

    def get(self, symbol: str) -> dict | None:
        return self._prices.get(symbol)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._listeners.remove(q)
        except ValueError:
            pass

    def snapshot(self) -> list[dict]:
        return list(self._prices.values())


# ------------------------------------------------------------------
# Consolidated price poller — 1 task pour tous les actifs (pas 48)
# ------------------------------------------------------------------

_ws_tasks: dict[str, asyncio.Task] = {}
_poller_task: asyncio.Task | None = None
_active_symbols: set[str] = set()

# Shared REST exchange — une seule instance
_rest_exchange = None
_rest_exchange_lock = asyncio.Lock()

async def _get_rest_exchange():
    global _rest_exchange
    if _rest_exchange is None:
        async with _rest_exchange_lock:
            if _rest_exchange is None:
                import ccxt
                _rest_exchange = ccxt.binance({"enableRateLimit": True})
    return _rest_exchange


async def _poll_all_rest() -> None:
    """Polling REST consolidé : itère tous les actifs en boucle (économie mémoire ×24)."""
    exchange = await _get_rest_exchange()
    loop = asyncio.get_running_loop()
    logger.info("Consolidated REST poller started (%d symbols)", len(_active_symbols))
    failures: dict[str, int] = {}
    while True:
        symbols = sorted(_active_symbols)  # snapshot
        if not symbols:
            await asyncio.sleep(5)
            continue
        for symbol in symbols:
            try:
                ticker = await loop.run_in_executor(None, exchange.fetch_ticker, symbol)
                price = ticker.get("last") or ticker.get("close")
                if price:
                    PriceStore.instance().update(symbol, float(price))
                    failures[symbol] = 0
            except Exception:
                failures[symbol] = failures.get(symbol, 0) + 1
            await asyncio.sleep(0.1)  # 100ms entre chaque symbole (pas de rate-limit)
        # Pause entre les cycles : 3s / nombre d'actifs ≈ 3s de fraîcheur
        await asyncio.sleep(3.0)


def ensure_ticker(symbol: str) -> None:
    """Ajoute un symbole au poller consolidé (plus de tâche par actif)."""
    global _poller_task
    _active_symbols.add(symbol)
    if _poller_task is None or _poller_task.done():
        _poller_task = asyncio.get_event_loop().create_task(_poll_all_rest())


# ------------------------------------------------------------------
# Endpoint SSE
# ------------------------------------------------------------------

async def _sse_generator(symbols: list[str]) -> AsyncGenerator[str, None]:
    store = PriceStore.instance()

    # Démarrer les tickers
    for sym in symbols:
        ensure_ticker(sym)

    # Envoyer le snapshot initial pour chaque symbole connu
    for sym in symbols:
        rec = store.get(sym)
        if rec:
            yield f"event: price\ndata: {json.dumps(rec)}\n\n"

    # S'abonner aux mises à jour en continu
    q = store.subscribe()
    try:
        while True:
            try:
                record = await asyncio.wait_for(q.get(), timeout=30.0)
                if record["symbol"] in symbols:
                    yield f"event: price\ndata: {json.dumps(record)}\n\n"
            except asyncio.TimeoutError:
                # Keepalive : commentaire SSE pour garder la connexion ouverte
                yield ": keepalive\n\n"
    except (GeneratorExit, asyncio.CancelledError):
        pass
    finally:
        store.unsubscribe(q)


@router.get("/stream")
async def price_stream(symbols: str = "BTC/USDT"):
    """
    Flux SSE des prix.
    ?symbols=BTC/USDT,ETH/USDT,SOL/USDT
    """
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        sym_list = ["BTC/USDT"]

    return StreamingResponse(
        _sse_generator(sym_list),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/snapshot")
async def price_snapshot(symbols: str = ""):
    """Retourne le dernier prix connu pour chaque symbole (pas SSE)."""
    store = PriceStore.instance()
    if symbols:
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        return {s: store.get(s) for s in sym_list}
    return {r["symbol"]: r for r in store.snapshot()}
