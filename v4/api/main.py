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


@app.on_event("startup")
async def _auto_schedule_demo():
    """Démarre automatiquement le DAG démo et les tickers prix au boot."""
    # 1) DAGs démo (BTC, ETH, SOL, BNB, XRP)
    try:
        from v4.api.demo_dag import DEMO_DAG, DEMO_ETH, DEMO_SOL, DEMO_BNB, DEMO_XRP
        from v4.api.dag_registry import DAGRegistry
        registry = DAGRegistry.instance()
        existing_ids = {e.dag_id for e in registry.status()}
        for dag in (DEMO_DAG, DEMO_ETH, DEMO_SOL, DEMO_BNB, DEMO_XRP):
            if dag.dag_id not in existing_ids:
                registry.schedule(dag, cycle_s=300)
                logging.getLogger("v4.api.main").info("DAG '%s' schedulé (cycle=300s)", dag.dag_id)
    except Exception as exc:
        logging.getLogger("v4.api.main").warning(f"DAGs démo non schedulés : {exc}")

    # 2) Tickers prix (Binance WS) pour les symboles par défaut
    try:
        from v4.api.routes.prices import ensure_ticker
        for sym in ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]:
            ensure_ticker(sym)
        logging.getLogger("v4.api.main").info("Tickers prix démarrés (BTC, ETH, SOL, BNB, XRP)")
    except Exception as exc:
        logging.getLogger("v4.api.main").warning(f"Tickers prix non démarrés : {exc}")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "4.0.0"}
