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

# CORS : permet le frontend Next.js en dev (localhost:3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://atlas-v4-frontend:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dag_router, prefix="/dag", tags=["dag"])
app.include_router(prices_router, prefix="/prices", tags=["prices"])


@app.on_event("startup")
async def _auto_schedule_demo():
    """Démarre automatiquement le DAG démo et les tickers prix au boot."""
    # 1) DAG démo
    try:
        from v4.api.demo_dag import DEMO_DAG
        from v4.api.dag_registry import DAGRegistry
        registry = DAGRegistry.instance()
        if "demo_v4" not in {e.dag_id for e in registry.status()}:
            registry.schedule(DEMO_DAG, cycle_s=300)
            logging.getLogger("v4.api.main").info("DAG démo 'demo_v4' schedulé (cycle=300s)")
    except Exception as exc:
        logging.getLogger("v4.api.main").warning(f"DAG démo non schedulé : {exc}")

    # 2) Tickers prix (Binance WS) pour les symboles par défaut
    try:
        from v4.api.routes.prices import ensure_ticker
        for sym in ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]:
            ensure_ticker(sym)
        logging.getLogger("v4.api.main").info("Tickers prix démarrés (BTC, ETH, SOL, BNB)")
    except Exception as exc:
        logging.getLogger("v4.api.main").warning(f"Tickers prix non démarrés : {exc}")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "4.0.0"}
