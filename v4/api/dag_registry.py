"""
v4/api/dag_registry.py — Registre global des DAGs actifs.

Gère le cycle de vie des DAGExecutor en mémoire :
  - DAGs one-shot : créés, exécutés, résultats stockés, détruits
  - DAGs schedulés : créés, boucle dans thread daemon, statut et résultats persistés
  - Buffer de logs circulaire (derniers 200 événements)

Thread-safe. Pas de persistance sur disque (volontaire pour la V4.0).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from v4.core.dag_executor import DAGExecutor
from v4.core.node import Node, NodeRunResult

logger = logging.getLogger("v4.api.dag_registry")

## Circular log buffer (shared across all DAGs)
_LOG_BUFFER: deque[dict] = deque(maxlen=200)
_LOG_LOCK = threading.Lock()


def _emit_log(level: str, dag_id: str, message: str, node_id: str = "") -> None:
    """Append an entry to the circular log buffer + persist it in the DB."""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "level": level,
        "dag_id": dag_id,
        "node_id": node_id,
        "message": message,
    }
    with _LOG_LOCK:
        _LOG_BUFFER.append(entry)
    logger.info("[%s] %s%s: %s", dag_id, f"{node_id} " if node_id else "", level, message)

    # DB persistence (best-effort, must not block the DAG)
    try:
        import sqlite3
        db_path = "/app/data/v4.db"
        with sqlite3.connect(db_path, timeout=2) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dag_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT, level TEXT, dag_id TEXT, node_id TEXT, message TEXT
                )
            """)
            conn.execute(
                "INSERT INTO dag_logs (ts, level, dag_id, node_id, message) VALUES (?,?,?,?,?)",
                (entry["ts"], level, dag_id, node_id, message),
            )
            conn.commit()
    except Exception:
        pass  # silent - the in-memory logs remain available


def get_logs(n: int = 50) -> list[dict]:
    """Return the last N logs."""
    with _LOG_LOCK:
        return list(_LOG_BUFFER)[-n:]


@dataclass
class DAGEntry:
    dag_id: str
    asset: str
    executor: DAGExecutor
    running: bool = False
    cycle_s: float | None = None
    last_run_at: float | None = None
    last_results: dict[str, NodeRunResult] = field(default_factory=dict)
    _thread: threading.Thread | None = field(default=None, repr=False)


class DAGRegistry:
    """Singleton - access through DAGRegistry.instance()."""

    _instance: "DAGRegistry | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._dags: dict[str, DAGEntry] = {}
        self._mu = threading.Lock()

    @classmethod
    def instance(cls) -> "DAGRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Build a DAGExecutor from a DAGSpec
    # ------------------------------------------------------------------

    def _build_executor(self, dag_spec: "DAGSpec") -> DAGExecutor:  # noqa: F821
        """Instantiate the nodes from the registry and build the DAGExecutor."""
        from v4.nodes import NODE_REGISTRY
        from v4.core.node import NodeMeta

        executor = DAGExecutor(asset=dag_spec.asset, dag_name=dag_spec.dag_id)

        for ns in dag_spec.nodes:
            node_cls = NODE_REGISTRY.get(ns.type)
            if node_cls is None:
                raise ValueError(f"Unknown node type: {ns.type!r}")

            meta = NodeMeta(
                x=ns.position.get("x", 0),
                y=ns.position.get("y", 0),
                label=ns.meta.get("label", ""),
                group=ns.meta.get("group", ""),
                bypass=ns.meta.get("bypass", False),
                cycle_interval_s=ns.meta.get("cycle_interval_s"),
            )
            node = node_cls(node_id=ns.id, params=ns.params, meta=meta)
            executor.add_node(node)

        for edge in dag_spec.edges:
            executor.add_edge(
                edge.source_node, edge.source_port,
                edge.target_node, edge.target_port,
            )

        executor.validate()
        return executor

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def run_once(self, dag_spec: "DAGSpec") -> dict[str, NodeRunResult]:
        """Run a DAG once and return the results. Without persistence."""
        _emit_log("INFO", dag_spec.dag_id, f"▶ {dag_spec.asset} — starting")
        executor = self._build_executor(dag_spec)
        results = executor.run_once()
        done = sum(1 for r in results.values() if r.status.value == "done")
        errors = sum(1 for r in results.values() if r.status.value == "error")
        for nid, r in results.items():
            _emit_log("INFO" if r.status.value == "done" else "ERROR",
                      dag_spec.dag_id, _summarize_node(nid, r), node_id=nid)
        _emit_log("INFO", dag_spec.dag_id, f"✓ Complete: {done}/{len(results)} OK, {errors} errors")
        return results

    def schedule(self, dag_spec: "DAGSpec", cycle_s: float) -> str:
        """Start a DAG in a loop. Returns dag_id."""
        dag_id = dag_spec.dag_id

        with self._mu:
            if dag_id in self._dags and self._dags[dag_id].running:
                logger.warning("DAG %s already running — stopping then restarting", dag_id)
                self.stop(dag_id)

            executor = self._build_executor(dag_spec)
            entry = DAGEntry(
                dag_id=dag_id,
                asset=dag_spec.asset,
                executor=executor,
                running=True,
                cycle_s=cycle_s,
            )
            self._dags[dag_id] = entry

        thread = threading.Thread(
            target=self._loop,
            args=(dag_id, cycle_s),
            name=f"dag-{dag_id}",
            daemon=True,
        )
        with self._mu:
            self._dags[dag_id]._thread = thread
        thread.start()
        logger.info("DAG %s scheduled (cycle=%.1fs)", dag_id, cycle_s)
        return dag_id

    def stop(self, dag_id: str) -> bool:
        """Stop a scheduled DAG. Returns True if found."""
        with self._mu:
            entry = self._dags.get(dag_id)
            if entry is None:
                return False
            entry.running = False
            entry.executor.stop()
        return True

    def remove(self, dag_id: str) -> bool:
        """Stop and remove a DAG from the registry. Returns True if found."""
        with self._mu:
            entry = self._dags.pop(dag_id, None)
            if entry is None:
                return False
            entry.running = False
            entry.executor.stop()
        return True

    def status(self, dag_id: str | None = None) -> list[DAGEntry]:
        """Return the status of one DAG or of every DAG."""
        with self._mu:
            if dag_id is not None:
                entry = self._dags.get(dag_id)
                return [entry] if entry else []
            return list(self._dags.values())

    # ------------------------------------------------------------------
    # Inner loop
    # ------------------------------------------------------------------

    def _loop(self, dag_id: str, cycle_s: float) -> None:
        _emit_log("INFO", dag_id, f"Loop started (cycle={cycle_s}s)")
        while True:
            with self._mu:
                entry = self._dags.get(dag_id)
                if entry is None or not entry.running:
                    break

            try:
                results = entry.executor.run_once()
                with self._mu:
                    if dag_id in self._dags:
                        self._dags[dag_id].last_run_at = time.time()
                        self._dags[dag_id].last_results = results
                done = sum(1 for r in results.values() if r.status.value == "done")
                errors = sum(1 for r in results.values() if r.status.value == "error")
                for nid, r in results.items():
                    _emit_log("INFO" if r.status.value == "done" else "ERROR",
                              dag_id, _summarize_node(nid, r), node_id=nid)
                _emit_log("INFO", dag_id, f"✓ Cycle complete: {done}/{len(results)} OK, {errors} errors")
            except Exception:
                _emit_log("ERROR", dag_id, "Error in loop")
                logger.exception("DAG %s — loop error", dag_id)

            time.sleep(cycle_s)

        _emit_log("INFO", dag_id, "Loop stopped")
        logger.info("DAG %s — loop ended", dag_id)


# ------------------------------------------------------------------
## Helper: node summary for the logs
# ------------------------------------------------------------------

def _summarize_node(nid: str, r: "NodeRunResult") -> str:
    """Compact summary of a node result for the logs."""
    dur_s = r.duration_ms / 1000
    status = r.status.value
    if status == "error":
        return f"✗ {nid} ({dur_s:.1f}s) — {str(r.error)[:80]}"
    if not r.outputs:
        return f"✓ {nid} ({dur_s:.1f}s)"
    out = r.outputs
    parts = []
    if "signal" in out:
        parts.append(f"signal={out['signal']}")
    if "trend" in out:
        parts.append(f"trend={out['trend']}")
    if "prob_up" in out:
        parts.append(f"prob={float(out['prob_up']):.2f}")
    if "reason" in out and out.get("signal") == "flat":
        parts.append(str(out["reason"])[:50])
    if "decision" in out:
        d = out["decision"]
        if hasattr(d, "get"):
            act = d.get("action", "?")
            prc = d.get("entry_price", 0)
            parts.append(f"{act}" + (f" @ ${prc:,.0f}" if prc else ""))
    if "trade_result" in out:
        tr = out["trade_result"]
        if hasattr(tr, "get"):
            parts.append(f"trade={tr.get('status','?')}")
    if "closed" in out:
        closed = out["closed"]
        if isinstance(closed, list):
            if closed:
                details = ", ".join(
                    f"{c.get('action','?')} {c.get('reason','?')} pnl=${c.get('pnl_usd',0):.2f}"
                    for c in closed
                )
                parts.append(f"CLOSED {len(closed)}: {details}")
            else:
                parts.append("no closes")
    if "open_positions" in out:
        n_open = len(out["open_positions"]) if isinstance(out["open_positions"], list) else 0
        if n_open > 0:
            parts.append(f"{n_open} open")
    if "atr" in out:
        parts.append(f"ATR={out['atr']}")
    if "strategy" in out:
        parts.append(f"strat={out['strategy']}")
    if "regime" in out:
        rv = out["regime"]
        if hasattr(rv, "iloc"):
            rv = str(rv.iloc[0]) if len(rv) > 0 else "?"
        parts.append(f"regime={rv}")
    if "response" in out:
        # AI analysis moved to the back-office - stop logging the placeholder
        resp = str(out["response"])[:60]
        if resp and "⏳" not in resp and "pending" not in str(out.get("parsed", {})):
            parts.append("AI: " + resp)
    detail = " | ".join(parts) if parts else f"{len(out)} output(s)"
    return f"✓ {nid} ({dur_s:.1f}s) — {detail}"
