"""
v4/core/dag_executor.py — Exécuteur du DAG V4.

Prend un DAG JSON (ou dict Python équivalent), résout l'ordre topologique,
exécute les nœuds synchrones séquentiellement, lance les nœuds asynchrones
dans des threads indépendants.

Règles :
  - Acyclique strict — validation avant toute exécution
  - Ports typés — connexion incompatible = erreur à la validation, pas à l'exécution
  - Nœud en erreur = log + skip, les nœuds en aval reçoivent un fallback
  - Nœuds asynchrones (cycle_interval_s > 0) : thread daemon, écrivent dans ContextStore
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from v4.core.node import Node, NodeRunResult, NodeStatus
from v4.core.context_store import ContextRegistry

logger = logging.getLogger("v4.core.dag_executor")


@dataclass
class EdgeSpec:
    """Définit une connexion : output d'un nœud source vers input d'un nœud cible."""
    source_node: str
    source_port: str
    target_node: str
    target_port: str


class DAGValidationError(Exception):
    pass


class DAGExecutor:
    """
    Exécute un graphe de nœuds V4.

    Usage :
        executor = DAGExecutor(asset="BTC/USDT")
        executor.add_node(my_node)
        executor.add_edge("load_1", "ohlcv_5m", "feat_1", "ohlcv")
        executor.validate()
        results = executor.run_once()          # one-shot execution
        executor.run_loop()                    # daemon loop (blocking)
    """

    def __init__(self, asset: str = "", dag_name: str = "") -> None:
        self.asset = asset
        self.dag_name = dag_name
        self._nodes: dict[str, Node] = {}
        self._edges: list[EdgeSpec] = []
        self._async_threads: dict[str, threading.Thread] = {}
        self._stop_event = threading.Event()
        self._context_store = ContextRegistry.get_store(asset) if asset else ContextRegistry.global_store()

    # ------------------------------------------------------------------
    # Construction du graphe
    # ------------------------------------------------------------------

    def add_node(self, node: Node) -> None:
        if node.node_id in self._nodes:
            raise ValueError(f"Duplicate node id: {node.node_id}")
        self._nodes[node.node_id] = node

    def add_edge(
        self,
        source_node: str,
        source_port: str,
        target_node: str,
        target_port: str,
    ) -> None:
        self._edges.append(EdgeSpec(source_node, source_port, target_node, target_port))

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Valide le DAG : acyclique, nœuds référencés, ports existants."""
        self._validate_nodes_exist()
        self._validate_no_cycles()
        self._validate_ports()

    def _validate_nodes_exist(self) -> None:
        for edge in self._edges:
            for nid in (edge.source_node, edge.target_node):
                if nid not in self._nodes:
                    raise DAGValidationError(f"Edge references unknown node: {nid}")

    def _validate_no_cycles(self) -> None:
        """Kahn's algorithm — lève si cycle détecté."""
        in_degree: dict[str, int] = defaultdict(int)
        adj: dict[str, list[str]] = defaultdict(list)
        for edge in self._edges:
            adj[edge.source_node].append(edge.target_node)
            in_degree[edge.target_node] += 1
        for nid in self._nodes:
            in_degree.setdefault(nid, 0)

        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        visited = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(self._nodes):
            raise DAGValidationError("DAG contains a cycle — execution refused")

    def _validate_ports(self) -> None:
        for edge in self._edges:
            src = self._nodes[edge.source_node]
            tgt = self._nodes[edge.target_node]
            # An empty schema -> dynamic node (accepts/produces any port)
            src_ports = src.output_schema()
            tgt_ports = tgt.input_schema()
            if src_ports and edge.source_port not in src_ports:
                raise DAGValidationError(
                    f"Node {edge.source_node} has no output port '{edge.source_port}'"
                )
            if tgt_ports and edge.target_port not in tgt_ports:
                raise DAGValidationError(
                    f"Node {edge.target_node} has no input port '{edge.target_port}'"
                )

    # ------------------------------------------------------------------
    # Topological order resolution
    # ------------------------------------------------------------------

    def _topological_order(self) -> list[str]:
        in_degree: dict[str, int] = defaultdict(int)
        adj: dict[str, list[str]] = defaultdict(list)
        for edge in self._edges:
            adj[edge.source_node].append(edge.target_node)
            in_degree[edge.target_node] += 1
        for nid in self._nodes:
            in_degree.setdefault(nid, 0)

        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        order = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        return order

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_once(self) -> dict[str, NodeRunResult]:
        """
        Exécute tous les nœuds synchrones dans l'ordre topologique.
        Les nœuds asynchrones sont ignorés (ils tournent dans leurs threads).
        Retourne un dict node_id → NodeRunResult.
        """
        order = self._topological_order()
        resolved: dict[str, dict[str, Any]] = {}  # node_id → outputs
        results: dict[str, NodeRunResult] = {}

        for node_id in order:
            node = self._nodes[node_id]

            # Async nodes: skipped in run_once (handled by _run_async_node)
            if node.meta.cycle_interval_s is not None:
                continue

            inputs = self._resolve_inputs(node_id, resolved)
            result = node.execute(inputs)
            results[node_id] = result

            if result.status in (NodeStatus.DONE, NodeStatus.BYPASSED):
                resolved[node_id] = result.outputs
                # Publish into the ContextStore (key = node_id.port)
                for port, value in result.outputs.items():
                    self._context_store.set(
                        f"{node_id}.{port}", value, source=node_id
                    )
                # When the node defines a global output_key, publish that too
                output_key = node.params.get("output_key")
                if output_key and result.outputs:
                    first_val = next(iter(result.outputs.values()))
                    self._context_store.set(output_key, first_val, source=node_id)
            else:
                # Node failed: downstream nodes receive empty inputs
                resolved[node_id] = {}

        return results

    def _resolve_inputs(
        self,
        node_id: str,
        resolved: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Construit le dict d'inputs pour un nœud en résolvant ses connexions entrantes.
        Si une valeur n'est pas disponible dans resolved, tente le ContextStore.
        """
        inputs: dict[str, Any] = {}
        for edge in self._edges:
            if edge.target_node != node_id:
                continue
            source_outputs = resolved.get(edge.source_node, {})
            if edge.source_port in source_outputs:
                inputs[edge.target_port] = source_outputs[edge.source_port]
            else:
                # Fallback: read from the ContextStore (value from an async lane)
                ctx_value = self._context_store.get(
                    f"{edge.source_node}.{edge.source_port}"
                )
                inputs[edge.target_port] = ctx_value
        return inputs

    # ------------------------------------------------------------------
    # Async nodes (lanes with their own cycle)
    # ------------------------------------------------------------------

    def start_async_nodes(self) -> None:
        """Lance les threads des nœuds avec cycle_interval_s défini."""
        for node_id, node in self._nodes.items():
            if node.meta.cycle_interval_s and node_id not in self._async_threads:
                t = threading.Thread(
                    target=self._run_async_node,
                    args=(node,),
                    daemon=True,
                    name=f"async-{node_id}",
                )
                self._async_threads[node_id] = t
                t.start()
                logger.info(
                    "Started async node %s (interval=%.0fs)",
                    node_id, node.meta.cycle_interval_s,
                )

    def _run_async_node(self, node: Node) -> None:
        interval = node.meta.cycle_interval_s or 60.0
        while not self._stop_event.is_set():
            try:
                inputs = self._resolve_inputs(node.node_id, {})
                result = node.execute(inputs)
                if result.status in (NodeStatus.DONE, NodeStatus.BYPASSED):
                    for port, value in result.outputs.items():
                        self._context_store.set(
                            f"{node.node_id}.{port}", value, source=node.node_id
                        )
                    output_key = node.params.get("output_key")
                    if output_key and result.outputs:
                        first_val = next(iter(result.outputs.values()))
                        self._context_store.set(output_key, first_val, source=node.node_id)
            except Exception as exc:
                logger.exception("Async node %s error: %s", node.node_id, exc)
            self._stop_event.wait(interval)

    def stop(self) -> None:
        """Arrête proprement tous les threads async."""
        self._stop_event.set()
        for t in self._async_threads.values():
            t.join(timeout=5.0)
        logger.info("DAGExecutor stopped (asset=%s, dag=%s)", self.asset, self.dag_name)

    def run_loop(self, interval_s: float = 300.0) -> None:
        """
        Boucle principale (bloquant) : exécute run_once() toutes les interval_s secondes.
        Lance aussi les nœuds asynchrones en threads daemon.
        """
        self.validate()
        self.start_async_nodes()
        logger.info(
            "DAGExecutor loop started (asset=%s, interval=%.0fs)",
            self.asset, interval_s,
        )
        try:
            while not self._stop_event.is_set():
                t0 = time.time()
                self.run_once()
                elapsed = time.time() - t0
                wait = max(0.0, interval_s - elapsed)
                self._stop_event.wait(wait)
        finally:
            self.stop()
