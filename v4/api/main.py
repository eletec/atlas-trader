"""
v4/api/main.py — Point d'entrée FastAPI pour Atlas V4.

Routes :
  POST /dag/run           — exécute un DAG une fois
  POST /dag/schedule      — démarre un DAG en boucle (async)
  DELETE /dag/{dag_id}    — arrête un DAG schedulé
  GET  /dag/status        — statut de tous les DAGs actifs
  GET  /dag/{dag_id}/status — statut d'un DAG spécifique
  GET  /prices/stream     — flux SSE des prix en temps réel
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
    description="API de trading algorithmique — moteur DAG + plugins IA",
)

# CORS : permet le frontend Next.js et le dashboard Streamlit, en local et via IP
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
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dag_router, prefix="/dag", tags=["dag"])
app.include_router(prices_router, prefix="/prices", tags=["prices"])

# V7 — Live P&L widget
from v7.api.live_pnl import router as live_pnl_router
app.include_router(live_pnl_router, prefix="/v7", tags=["v7"])


@app.on_event("startup")
async def _auto_schedule_carry():
    """Démarre le cycle Funding Carry V7 au boot (DeepSeek/GPT audit, 25/07/2026).
    
    Remplace l'ancien système de 29 DAGs par un script unique.
    Le PositionMonitor et les tickers prix restent actifs.
    """
    import threading
    logger = logging.getLogger("v4.api.main")
    
    # 1) Carry cycle — thread background toutes les 8h
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

    # 2) Tickers prix (Binance WS) pour les actifs actifs
    try:
        from v4.api.routes.prices import ensure_ticker
        from v7.core.asset_config import get_active_assets
        active = get_active_assets()
        if not active:
            active = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
        for sym in active:
            ensure_ticker(sym)
        logger.info("Price tickers started (%d assets)", len(active))
    except Exception as exc:
        logger.warning(f"Price tickers failed to start: {exc}")

    # 3) Position Monitor — surveillance continue des SL/TP/time-stop
    try:
        from v7.position_monitor import start_monitor
        start_monitor()
        logger.info("PositionMonitor started")
    except Exception as exc:
        logger.warning(f"PositionMonitor failed to start: {exc}")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "5.0.0"}


@app.post("/optimize/v5")
async def optimize_v5(days: int = 180):
    """Lance l'optimiseur V5 MetaGate en arrière-plan."""
    import subprocess, sys, uuid, threading
    task_id = str(uuid.uuid4())[:8]

    def _run():
        try:
            subprocess.run(
                [sys.executable, "/app/src/tools/optimize_v5.py", "--days", str(days)],
                capture_output=True, text=True, timeout=3600,
            )
        except Exception as e:
            logging.getLogger("v4.api.main").warning("Optimize V5 failed: %s", e)

    threading.Thread(target=_run, daemon=True, name=f"opt_v5_{task_id}").start()
    return {"ok": True, "task_id": task_id, "message": "Optimisation V5 lancée"}
