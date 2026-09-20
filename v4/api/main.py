"""
v4/api/main.py — FastAPI entry point for Atlas V4.

Routes:
  POST /dag/run           — runs a DAG once
  POST /dag/schedule      — starts a DAG in a loop (async)
  DELETE /dag/{dag_id}    — stops a scheduled DAG
  GET  /dag/status        — status of every active DAG
  GET  /dag/{dag_id}/status — status of a specific DAG
  GET  /prices/stream     — SSE stream of real-time prices
  GET  /health            — healthcheck
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from v4.api.routes.dag import router as dag_router
from v4.api.routes.prices import router as prices_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)

app = FastAPI(
    title="Atlas Trader V4",
    version="4.0.0",
    description="Algorithmic trading API — DAG engine + AI plugins",
)

## CORS: allows the Streamlit dashboard in local/dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8502",
        "http://atlas-v4-frontend:3000",
        "http://192.168.1.80:3000",
        "http://192.168.1.80:8502",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],  # restricted: no needless PUT/PATCH/OPTIONS
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

app.include_router(dag_router, prefix="/dag", tags=["dag"])
app.include_router(prices_router, prefix="/prices", tags=["prices"])

# V7 — Live P&L widget
from v7.api.live_pnl import router as live_pnl_router
app.include_router(live_pnl_router, prefix="/v7", tags=["v7"])


@app.on_event("startup")
async def _auto_schedule_carry():
    """Start the V7 Funding Carry cycle at boot (DeepSeek/GPT audit, 25/07/2026).
    
    Replaces the old 29-DAG system with a single script.
    The PositionMonitor and the price tickers stay active.
    """
    import threading
    logger = logging.getLogger("v4.api.main")
    
    # 0) Initialise the DB (logs tables, dag_logs, etc.) before any dashboard access
    try:
        from storage.database import init_db
        init_db()
        logger.info("Database initialized")
    except Exception as exc:
        logger.warning("DB init failed (non-blocking): %s", exc)
    
    # 1) Carry cycle - background thread every 8h
    def _carry_loop():
        import time
        from v7.run_carry_cycle import run_cycle
        logger.info("V7 Carry cycle thread started (interval=8h)")
        while True:
            try:
                run_cycle()
            except Exception as exc:
                logger.error("Carry cycle error: %s", exc)
            time.sleep(28800)  # 8h
    
    t = threading.Thread(target=_carry_loop, daemon=True, name="carry-cycle")
    t.start()
    logger.info("V7 Carry cycle scheduled (28800s)")

    # 2) Price tickers (REST polling with a WS fallback) - staggered start
    try:
        from v4.api.routes.prices import ensure_ticker
        from v7.core.asset_config import get_active_assets
        active = get_active_assets()
        if not active:
            active = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
        for i, sym in enumerate(active):
            ensure_ticker(sym)
            if i < len(active) - 1:
                await asyncio.sleep(0.3)  # stagger to avoid Binance rate limits
        logger.info("Price tickers started (%d assets)", len(active))
    except Exception as exc:
        logger.warning(f"Price tickers failed to start: {exc}")

    # 3) Position Monitor — continuous SL/TP/time-stop monitoring
    try:
        from v7.position_monitor import start_monitor
        start_monitor()
        logger.info("PositionMonitor started")
    except Exception as exc:
        logger.warning(f"PositionMonitor failed to start: {exc}")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "5.0.0"}


@app.post("/carry/run")
async def carry_run() -> dict:
    """Trigger a Funding Carry cycle immediately (non-blocking).

    The cycle runs in a daemon thread; its progress is visible via
    `/dag/logs` (Live Monitor tab of the dashboard). The anti-concurrency
    flock prevents any overlap with the 8h periodic cycle.
    """
    import threading

    def _run():
        try:
            from v7.run_carry_cycle import run_cycle
            summary = run_cycle()
            logging.getLogger("v4.api.main").info("Manual carry cycle done: %s", summary)
        except Exception as e:
            logging.getLogger("v4.api.main").error("Manual carry cycle failed: %s", e)

    threading.Thread(target=_run, daemon=True, name="carry-run-manual").start()
    return {"ok": True, "message": "Carry cycle launched in the background"}


@app.post("/carry/reload-config")
async def carry_reload_config() -> dict:
    """Reload carry_assets.yaml on the API side.

    The dashboard writes this file, but the API process keeps a cached copy:
    enabling/disabling an asset therefore had no effect until the container
    was restarted. This endpoint clears the cache, reloads the new asset
    list and starts the price tickers for the added assets.
    """
    from v7.core.asset_config import reload_config, get_active_assets

    cfg = reload_config()
    active = get_active_assets()

    tickers_ok, errors = 0, []
    try:
        from v4.api.routes.prices import ensure_ticker
        for sym in active:
            try:
                ensure_ticker(sym)
                tickers_ok += 1
            except Exception as exc:
                errors.append(f"{sym}: {exc}")
    except Exception as exc:
        errors.append(f"prices module unavailable: {exc}")

    logging.getLogger("v4.api.main").info(
        "Config reloaded - %d active assets | tickers: %d | errors: %d",
        len(active), tickers_ok, len(errors),
    )
    return {
        "ok": True,
        "n_assets": len(active),
        "active_assets": active,
        "tickers_ready": tickers_ok,
        "errors": errors,
        "global": cfg.get("global", {}),
    }
