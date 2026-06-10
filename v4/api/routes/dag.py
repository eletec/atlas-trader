"""
v4/api/routes/dag.py — Routes CRUD pour les DAGs.

POST /dag/run           — exécute une fois, retourne les résultats
POST /dag/schedule      — démarre en boucle
DELETE /dag/{dag_id}    — arrête un DAG schedulé
GET  /dag/status        — statut de tous les DAGs
GET  /dag/{dag_id}/status
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from v4.api.dag_registry import DAGRegistry, get_logs
from v4.api.models import (
    DAGStatusOut,
    NodeResultOut,
    RunDAGRequest,
    RunDAGResponse,
    ScheduleDAGRequest,
)

router = APIRouter()
logger = logging.getLogger("v4.api.routes.dag")


def _node_result_to_out(node_id: str, result) -> NodeResultOut:
    return NodeResultOut(
        node_id=node_id,
        status=result.status.value,
        outputs={k: _serialize(v) for k, v in result.outputs.items()},
        error=result.error,
        duration_ms=result.duration_ms,
        ai_used=result.ai_used,
    )


def _serialize(value):
    """Convertit les types non-JSON-serializable (DataFrame, ndarray…) en primitives."""
    try:
        import pandas as pd
        import numpy as np

        if isinstance(value, pd.DataFrame):
            return value.tail(5).to_dict(orient="records")
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
    except ImportError:
        pass
    return value


@router.post("/run", response_model=RunDAGResponse)
async def run_dag(body: RunDAGRequest):
    """Exécute le DAG une seule fois et retourne les résultats immédiats."""
    try:
        results = DAGRegistry.instance().run_once(body.dag)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erreur run_dag")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RunDAGResponse(
        dag_id=body.dag.dag_id,
        results={nid: _node_result_to_out(nid, r) for nid, r in results.items()},
    )


@router.post("/schedule")
async def schedule_dag(body: ScheduleDAGRequest):
    """Démarre un DAG en boucle périodique (daemon thread)."""
    try:
        dag_id = DAGRegistry.instance().schedule(body.dag, body.cycle_s)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erreur schedule_dag")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"dag_id": dag_id, "status": "scheduled", "cycle_s": body.cycle_s}


@router.delete("/{dag_id}")
async def stop_dag(dag_id: str):
    found = DAGRegistry.instance().stop(dag_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"DAG '{dag_id}' non trouvé")
    return {"dag_id": dag_id, "status": "stopped"}


@router.post("/restart-demo")
async def restart_demo_dags():
    """Redémarre les 7 DAGs démo (après un reset par exemple)."""
    from v4.api.demo_dag import DEMO_DAG, DEMO_ETH, DEMO_SOL, DEMO_BNB, DEMO_XRP, DEMO_ADA, DEMO_DOGE

    registry = DAGRegistry.instance()
    restarted = []
    for dag in (DEMO_DAG, DEMO_ETH, DEMO_SOL, DEMO_BNB, DEMO_XRP, DEMO_ADA, DEMO_DOGE):
        try:
            # Forcer l'arrêt si déjà en cours, puis redémarrer
            registry.stop(dag.dag_id)
            registry.schedule(dag, cycle_s=300)
            restarted.append(dag.dag_id)
        except Exception as exc:
            logger.warning("Échec redémarrage %s: %s", dag.dag_id, exc)

    return {"restarted": restarted, "count": len(restarted)}


@router.get("/status", response_model=list[DAGStatusOut])
async def all_dag_status():
    return _entries_to_out(DAGRegistry.instance().status())


@router.get("/logs")
async def dag_logs(n: int = 50):
    """Retourne les N derniers logs d'exécution des DAGs."""
    return get_logs(n)


@router.get("/{dag_id}/status", response_model=DAGStatusOut)
async def dag_status(dag_id: str):
    entries = DAGRegistry.instance().status(dag_id)
    if not entries:
        raise HTTPException(status_code=404, detail=f"DAG '{dag_id}' non trouvé")
    return _entries_to_out(entries)[0]


def _entries_to_out(entries) -> list[DAGStatusOut]:
    out = []
    for e in entries:
        out.append(DAGStatusOut(
            dag_id=e.dag_id,
            asset=e.asset,
            running=e.running,
            cycle_s=e.cycle_s,
            last_run_at=e.last_run_at,
            last_results={
                nid: _node_result_to_out(nid, r)
                for nid, r in e.last_results.items()
            },
        ))
    return out
