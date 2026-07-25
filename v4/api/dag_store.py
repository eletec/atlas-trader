"""
v4/api/dag_store.py — Persistance JSON des DAGs.

Stocke les DAGSpecs dans /app/data/dags.json.
- Au boot, charge les DAGs persistés
- Au schedule, sauvegarde le DAG
- Au stop, retire le DAG du store
- Fallback: si aucun DAG n'a jamais été sauvegardé, utilise les V7 par défaut
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
    """Chemin du fichier de persistance."""
    env = os.environ.get("DAG_STORE_PATH", DEFAULT_STORE_PATH)
    return Path(env)


def load_all() -> list[DAGSpec]:
    """Charge tous les DAGs persistés. Retourne [] si fichier absent/vide."""
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
        logger.warning("dag_store: erreur lecture %s: %s", path, exc)
        return []


def save_all(dags: list[DAGSpec]) -> None:
    """Sauvegarde la liste complète des DAGs (écrase le fichier)."""
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [d.model_dump() for d in dags]
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("dag_store: %d DAG(s) saved to %s", len(dags), path)


def upsert(dag: DAGSpec) -> None:
    """Ajoute ou met à jour un DAG dans le store."""
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
    """Retire un DAG du store. Retourne True si trouvé/supprimé."""
    dags = load_all()
    new_dags = [d for d in dags if d.dag_id != dag_id]
    if len(new_dags) == len(dags):
        return False
    save_all(new_dags)
    return True


def get_defaults() -> list[DAGSpec]:
    """DAGs par défaut — DÉSACTIVÉ (remplacé par run_carry_cycle.py, 25/07/2026).
    
    DeepSeek/GPT audit: l'infrastructure DAG est surdimensionnée pour le funding carry.
    Un script unique cron 8h remplace les 29 DAGs. Voir v7/run_carry_cycle.py.
    
    Retourne une liste vide — les DAGs ne sont plus créés automatiquement.
    """
    return []
