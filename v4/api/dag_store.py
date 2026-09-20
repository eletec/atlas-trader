"""
v4/api/dag_store.py — JSON persistence for DAGs.

Stores the DAGSpecs in /app/data/dags.json.
- On boot, loads the persisted DAGs
- On schedule, saves the DAG
- On stop, removes the DAG from the store
- Fallback: if no DAG has ever been saved, uses the default V7 ones
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from v4.api.models import DAGSpec

logger = logging.getLogger("v4.api.dag_store")

DEFAULT_STORE_PATH = "/app/data/dags.json"


def _store_path() -> Path:
    """Path of the persistence file."""
    env = os.environ.get("DAG_STORE_PATH", DEFAULT_STORE_PATH)
    return Path(env)


def load_all() -> list[DAGSpec]:
    """Load every persisted DAG. Returns [] when the file is missing/empty."""
    path = _store_path()
    if not path.exists():
        logger.info("dag_store: %s not found, no persisted DAGs", path)
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return []
        data = json.loads(raw)
        dags = [DAGSpec(**d) for d in data]
        logger.info("dag_store: %d DAG(s) loaded from %s", len(dags), path)
        return dags
    except Exception as exc:
        logger.warning("dag_store: read error %s: %s", path, exc)
        return []


def save_all(dags: list[DAGSpec]) -> None:
    """Save the full DAG list (overwrites the file)."""
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [d.model_dump() for d in dags]
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("dag_store: %d DAG(s) saved to %s", len(dags), path)


def upsert(dag: DAGSpec) -> None:
    """Add or update a DAG in the store."""
    dags = load_all()
    replaced = False
    for i, d in enumerate(dags):
        if d.dag_id == dag.dag_id:
            dags[i] = dag
            replaced = True
            break
    if not replaced:
        dags.append(dag)
    save_all(dags)


def remove(dag_id: str) -> bool:
    """Remove a DAG from the store. Returns True when found/removed."""
    dags = load_all()
    new_dags = [d for d in dags if d.dag_id != dag_id]
    if len(new_dags) == len(dags):
        return False
    save_all(new_dags)
    return True


def get_defaults() -> list[DAGSpec]:
    """Default DAGs — DISABLED (replaced by run_carry_cycle.py, 25/07/2026).
    
    DeepSeek/GPT audit: the DAG infrastructure is oversized for funding carry.
    A single 8h-cron script replaces the 29 DAGs. See v7/run_carry_cycle.py.
    
    Returns an empty list — DAGs are no longer created automatically.
    """
    return []
