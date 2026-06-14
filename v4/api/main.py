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
    """Démarre automatiquement les DAGs au boot."""
    from v4.api.dag_registry import DAGRegistry
    registry = DAGRegistry.instance()
    existing_ids = {e.dag_id for e in registry.status()}
    
    # 1) V7 DAGs Funding Carry — stratégie principale (affiche dans le dashboard)
    try:
        from v7.api.v7_demo_dag import V7_DAGS
        for dag in V7_DAGS:
            if dag.dag_id not in existing_ids:
                registry.schedule(dag, cycle_s=28800)
                logging.getLogger("v4.api.main").info("V7 DAG '%s' schedulé (carry, $2000)", dag.dag_id)
    except Exception as exc:
        logging.getLogger("v4.api.main").warning(f"DAGs V7 non schedulés : {exc}")
    
    # 2) V5 DAGs directionnels — désactivés (monitoring uniquement si besoin)
    # Note: V5 est remplacé par V7. Décommenter ci-dessous pour réactiver le monitoring.
    # try:
    #     from v5.api.demo_dag import DEMO_DAG, DEMO_ETH, DEMO_SOL, DEMO_BNB, DEMO_XRP, DEMO_ADA, DEMO_DOGE
    #     for dag in (...) 

    # 2) Tickers prix (Binance WS) pour les symboles par défaut
    try:
        from v4.api.routes.prices import ensure_ticker
        for sym in ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]:
            ensure_ticker(sym)
        logging.getLogger("v4.api.main").info("Tickers prix démarrés (7 actifs)")
    except Exception as exc:
        logging.getLogger("v4.api.main").warning(f"Tickers prix non démarrés : {exc}")

    # 3) V7 Funding Carry Scheduler (cycle 8h)
    try:
        from v7.live_carry import FundingCarryScheduler
        import asyncio, json, sqlite3, os
        carry = FundingCarryScheduler(capital_per_asset=2000)
        DB_PATH = os.environ.get("V4_DB_PATH", "/app/data/v4.db")
        
        async def carry_loop():
            while True:
                try:
                    results = carry.run_cycle()
                    summary = carry.get_summary()
                    
                    # Écrire les positions carry dans la DB dashboard
                    try:
                        db = sqlite3.connect(DB_PATH)
                        for r in results:
                            if r["signal"] in ("open_carry", "close_carry"):
                                db.execute(
                                    "INSERT INTO v4_trades (timestamp, symbol, action, entry_price, size_usd, pnl_usd, exit_reason) VALUES (?,?,?,?,?,?,?)",
                                    (datetime.now().isoformat(), r["symbol"],
                                     "CARRY_OPEN" if r["signal"] == "open_carry" else "CARRY_CLOSE",
                                     r["funding_rate"], r["size_usd"], 0.0,
                                     f"V7 carry | funding={r['annual_funding_pct']:.1f}%/an")
                                )
                        db.commit()
                        db.close()
                    except Exception:
                        pass
                    
                    if summary["active_carries"] > 0:
                        logging.getLogger("v4.api.main").info(
                            "V7 Carry: %d positions | size=$%.0f | funding=$%.4f",
                            summary["active_carries"], summary["total_size_usd"],
                            summary["total_funding_received"])
                except Exception as exc:
                    logging.getLogger("v4.api.main").warning("V7 Carry error: %s", exc)
                await asyncio.sleep(8 * 3600)  # 8h
        
        asyncio.create_task(carry_loop())
        logging.getLogger("v4.api.main").info("V7 Funding Carry scheduler démarré (cycle=8h)")
    except Exception as exc:
        logging.getLogger("v4.api.main").warning(f"V7 Carry non démarré : {exc}")


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
