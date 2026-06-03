"""
v4/core/node.py — Interface de base pour tous les nœuds du DAG V4.

Chaque nœud expose deux plans indépendants :
  - Plan QUANT  : run(inputs) → outputs  (synchrone, toujours actif)
  - Plan IA     : ai_run(context) → AIOutput  (asynchrone, optionnel, timeout + fallback)

Un nœud ne connaît pas ses voisins — il reçoit des inputs nommés et produit des outputs nommés.
La résolution des dépendances est gérée par le DAGExecutor.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("v4.core.node")


class NodeStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    BYPASSED = "bypassed"
    STALE = "stale"


@dataclass
class NodeMeta:
    """Métadonnées d'un nœud : position canvas, label, groupe (lane)."""
    x: float = 0.0
    y: float = 0.0
    label: str = ""
    group: str = ""                  # nom de la lane (cosmétique uniquement)
    bypass: bool = False             # si True : passe input → output sans traitement
    cycle_interval_s: float | None = None  # None = synchrone, >0 = async périodique


@dataclass
class NodeRunResult:
    node_id: str
    status: NodeStatus
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0
    ai_used: bool = False


class Node(ABC):
    """
    Interface de base de tous les nœuds V4.

    Sous-classer et implémenter :
      - input_schema()  : dict {port_name: type_str}
      - output_schema() : dict {port_name: type_str}
      - run(inputs)     : dict des outputs

    Optionnel :
      - ai_plugin       : instance AIPlugin branchée sur ce nœud
      - ai_blend_weight : poids de l'output IA dans le blend final (0.0 = IA ignorée)
    """

    def __init__(
        self,
        node_id: str,
        params: dict[str, Any] | None = None,
        meta: NodeMeta | None = None,
    ) -> None:
        self.node_id = node_id
        self.params: dict[str, Any] = params or {}
        self.meta: NodeMeta = meta or NodeMeta()
        self.ai_plugin: AIPlugin | None = None
        self.ai_blend_weight: float = 0.0
        self.status: NodeStatus = NodeStatus.IDLE
        self._last_outputs: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # À implémenter dans chaque nœud concret
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def node_type(self) -> str:
        """Identifiant du type de nœud, ex: 'LoadMultiTF'."""

    @staticmethod
    @abstractmethod
    def input_schema() -> dict[str, str]:
        """Port d'entrée → type attendu. Ex: {'ohlcv': 'DataFrame'}."""

    @staticmethod
    @abstractmethod
    def output_schema() -> dict[str, str]:
        """Port de sortie → type produit. Ex: {'features': 'DataFrame'}."""

    @abstractmethod
    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Exécution synchrone. Reçoit les inputs résolus, retourne les outputs."""

    # ------------------------------------------------------------------
    # Logique commune (bypass, AI blend, statut)
    # ------------------------------------------------------------------

    def execute(self, inputs: dict[str, Any]) -> NodeRunResult:
        """Point d'entrée appelé par le DAGExecutor."""
        import time

        if self.meta.bypass:
            self.status = NodeStatus.BYPASSED
            # Passe le premier input directement en output
            passthrough = next(iter(inputs.values()), None)
            first_out = next(iter(self.output_schema().keys()), "output")
            outputs = {first_out: passthrough}
            self._last_outputs = outputs
            return NodeRunResult(
                node_id=self.node_id,
                status=NodeStatus.BYPASSED,
                outputs=outputs,
            )

        t0 = time.perf_counter()
        try:
            self.status = NodeStatus.RUNNING
            outputs = self.run(inputs)

            # Blend IA si plugin connecté
            if self.ai_plugin and self.ai_blend_weight > 0:
                outputs = self._apply_ai_blend(inputs, outputs)

            self.status = NodeStatus.DONE
            self._last_outputs = outputs
            duration_ms = (time.perf_counter() - t0) * 1000
            return NodeRunResult(
                node_id=self.node_id,
                status=NodeStatus.DONE,
                outputs=outputs,
                duration_ms=duration_ms,
                ai_used=self.ai_plugin is not None and self.ai_blend_weight > 0,
            )

        except Exception as exc:
            self.status = NodeStatus.ERROR
            logger.exception("Node %s failed: %s", self.node_id, exc)
            return NodeRunResult(
                node_id=self.node_id,
                status=NodeStatus.ERROR,
                error=str(exc),
            )

    def _apply_ai_blend(
        self, inputs: dict[str, Any], quant_outputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Tente le blend IA avec timeout. Fallback silencieux sur erreur."""
        if self.ai_plugin is None:
            return quant_outputs
        try:
            ai_result = self.ai_plugin.run_with_timeout(
                node_id=self.node_id,
                node_type=self.node_type,
                inputs=inputs,
                quant_outputs=quant_outputs,
                params=self.params,
            )
            return self.ai_plugin.blend(quant_outputs, ai_result, self.ai_blend_weight)
        except Exception as exc:
            logger.warning(
                "Node %s: AI plugin failed (fallback to quant): %s", self.node_id, exc
            )
            return quant_outputs

    def to_dict(self) -> dict[str, Any]:
        """Sérialisation partielle pour le DAG JSON (sans outputs)."""
        return {
            "id": self.node_id,
            "type": self.node_type,
            "position": {"x": self.meta.x, "y": self.meta.y},
            "params": self.params,
            "bypass": self.meta.bypass,
            "cycle_interval_s": self.meta.cycle_interval_s,
        }
