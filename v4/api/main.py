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
async def _auto_schedule_demo():
    """Démarre automatiquement les DAGs au boot (persistés ou défaut)."""
    from v4.api.dag_registry import DAGRegistry
    from v4.api.dag_store import load_all, get_defaults, save_all
    
    registry = DAGRegistry.instance()
    logger = logging.getLogger("v4.api.main")
    
    # 1) Charger les DAGs persistés
    persisted = load_all()
    persisted_ids = {d.dag_id for d in persisted}
    
    # 2) Déterminer les DAGs souhaités (depuis carry_assets.yaml)
    desired_dags = get_defaults()  # V7_DAGS — lit get_active_assets()
    desired_ids = {d.dag_id for d in desired_dags}
    
    # 3) Réconcilier : ajouter les nouveaux, retirer les anciens
    dags_to_schedule: list = []
    
    for dag in desired_dags:
        if dag.dag_id not in persisted_ids:
            logger.info("New asset activated — adding DAG '%s'", dag.dag_id)
        dags_to_schedule.append(dag)
    
    removed = persisted_ids - desired_ids
    if removed:
        logger.info("Assets deactivated — removing DAGs: %s", removed)
    
    # Sauver la nouvelle liste (écrase l'ancienne)
    save_all(dags_to_schedule)
    
    # 4) Scheduler tous les DAGs souhaités
    existing_ids = {e.dag_id for e in registry.status()}
    for dag in dags_to_schedule:
        if dag.dag_id not in existing_ids:
            cycle = getattr(dag, "cycle_s", None) or 28800
            registry.schedule(dag, cycle_s=cycle)
            logger.info("DAG '%s' scheduled (cycle=%ds)", dag.dag_id, cycle)
    
    # Arrêter les DAGs qui ne sont plus dans la config
    for sid in existing_ids:
        if sid not in desired_ids:
            registry.stop(sid)
            logger.info("DAG '%s' stopped (asset deactivated)", sid)
    
    # 2) V5 DAGs directionnels — désactivés (monitoring uniquement si besoin)
    # Note: V5 est remplacé par V7. Décommenter ci-dessous pour réactiver le monitoring.
    # try:
    #     from v5.api.demo_dag import DEMO_DAG, DEMO_ETH, DEMO_SOL, DEMO_BNB, DEMO_XRP, DEMO_ADA, DEMO_DOGE
    #     for dag in (...) 

    # Tickers prix (Binance WS) pour les actifs actifs
    try:
        from v4.api.routes.prices import ensure_ticker
        from v7.core.asset_config import get_active_assets
        active = get_active_assets()
        if not active:
            active = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
        for sym in active:
            ensure_ticker(sym)
        logging.getLogger("v4.api.main").info("Tickers prix démarrés (%d actifs)", len(active))
    except Exception as exc:
        logging.getLogger("v4.api.main").warning(f"Tickers prix non démarrés : {exc}")

    # 3) V7 Funding Carry Scheduler — DÉSACTIVÉ (remplacé par les DAGs V7 #1)
    # Le scheduler était redondant avec les DAGs et créait des doublons.

    # 4) Position Monitor — surveillance continue des SL/TP/time-stop
    try:
        from v7.position_monitor import start_monitor
        start_monitor()
        logging.getLogger("v4.api.main").info("PositionMonitor démarré")
    except Exception as exc:
        logging.getLogger("v4.api.main").warning(f"PositionMonitor non démarré : {exc}")


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
