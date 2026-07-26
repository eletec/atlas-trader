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
# Ticker WS Binance via ccxt.pro
# ------------------------------------------------------------------

_ws_tasks: dict[str, asyncio.Task] = {}


async def _run_ticker(symbol: str) -> None:
    """Lance REST polling + WS en parallèle. REST = baseline fiable (3s). WS = bonus réactif.

    Stratégie (26/07/2026) : lancer REST immédiatement, tenter WS en parallèle.
    Si WS fonctionne → tant mieux (prix plus rapides). Si WS échoue → REST déjà actif.
    """
    # Démarrer REST immédiatement (fiable, fonctionne même avec 24 actifs)
    rest_task = asyncio.create_task(_poll_ticker_rest(symbol, interval_s=3.0))

    # Tenter le WebSocket en parallèle (plus réactif si dispo)
    try:
        import ccxt.pro as ccxtpro
        exchange = ccxtpro.binance({"newUpdates": True})
        logger.info("WS ticker started for %s", symbol)
        while True:
            try:
                ticker = await asyncio.wait_for(exchange.watch_ticker(symbol), timeout=10)
                price = ticker.get("last") or ticker.get("close")
                if price:
                    PriceStore.instance().update(symbol, float(price))
            except asyncio.TimeoutError:
                logger.debug("WS timeout (%s) — REST covers, retrying WS", symbol)
                await asyncio.sleep(5)
            except Exception as exc:
                logger.debug("WS error (%s): %s — REST covers, retrying WS", symbol, str(exc)[:100])
                await asyncio.sleep(10)
    except ImportError:
        logger.debug("ccxt.pro not available for %s — REST-only mode", symbol)
        # REST déjà actif, rien à faire — attendre indéfiniment
        await asyncio.Event().wait()
    except Exception as exc:
        logger.warning("WS setup failed for %s: %s — REST-only mode", symbol, str(exc)[:100])
        await asyncio.Event().wait()
    finally:
        rest_task.cancel()
        try:
            await rest_task
        except asyncio.CancelledError:
            pass


async def _poll_ticker_rest(symbol: str, interval_s: float = 3.0) -> None:
    """REST polling — fiable pour prix temps réel dashboard."""
    import ccxt
    exchange = ccxt.binance()
    logger.info("REST poller started for %s (interval=%ss)", symbol, interval_s)
    while True:
        try:
            ticker = exchange.fetch_ticker(symbol)
            price = ticker.get("last") or ticker.get("close")
            if price:
                PriceStore.instance().update(symbol, float(price))
            else:
                logger.warning("REST poll for %s: no price in ticker", symbol)
        except Exception as exc:
            logger.warning("REST poll error (%s): %s", symbol, str(exc)[:200])
        await asyncio.sleep(interval_s)


def ensure_ticker(symbol: str) -> None:
    """Lance le ticker (REST + WS) pour `symbol` s'il n'est pas déjà actif."""
    if symbol not in _ws_tasks or _ws_tasks[symbol].done():
        loop = asyncio.get_event_loop()
        _ws_tasks[symbol] = loop.create_task(_run_ticker(symbol))


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
