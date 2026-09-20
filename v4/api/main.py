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
    allow_methods=["GET", "POST", "DELETE"],  # restreint : pas de PUT/PATCH/OPTIONS inutiles
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
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
    
    # 0) Initialise the DB (logs tables, dag_logs, etc.) before any dashboard access
    try:
        from storage.database import init_db
        init_db()
        logger.info("Database initialized")
    except Exception as exc:
        logger.warning("DB init failed (non-bloquant): %s", exc)
    
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


@app.post("/carry/run")
async def carry_run() -> dict:
    """Déclenche un cycle Funding Carry immédiatement (non bloquant).

    Le cycle tourne dans un thread daemon ; son avancement est visible via
    `/dag/logs` (onglet Live Monitor du dashboard). L'anti-concurrence
    (flock) empêche tout chevauchement avec le cycle périodique de 8h.
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
    return {"ok": True, "message": "Cycle carry lancé en arrière-plan"}


@app.post("/carry/reload-config")
async def carry_reload_config() -> dict:
    """Recharge carry_assets.yaml côté API.

    Le dashboard écrit ce fichier, mais le process API en garde une copie en
    cache : activer/désactiver un actif n'avait donc aucun effet avant un
    redémarrage du container. Cet endpoint vide le cache, remonte la nouvelle
    liste d'actifs et démarre les tickers prix des actifs ajoutés.
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
        errors.append(f"module prices indisponible: {exc}")

    logging.getLogger("v4.api.main").info(
        "Config rechargée — %d actifs actifs | tickers: %d | erreurs: %d",
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
