"""
v4/core/node.py — Base interface for all nodes of the V4 DAG.

Each node exposes two independent planes:
  - QUANT plane : run(inputs) → outputs  (synchronous, always active)
  - AI plane    : ai_run(context) → AIOutput  (asynchronous, optional, timeout + fallback)

A node does not know its neighbours — it receives named inputs and produces named outputs.
Dependency resolution is handled by the DAGExecutor.
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
    """Node metadata: canvas position, label, group (lane)."""
    x: float = 0.0
    y: float = 0.0
    label: str = ""
    group: str = ""                  # lane name (cosmetic only)
    bypass: bool = False             # when True: passes input -> output without processing
    cycle_interval_s: float | None = None  # None = synchronous, >0 = periodic async


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
    Base interface of all V4 nodes.

    Subclass and implement:
      - input_schema()  : dict {port_name: type_str}
      - output_schema() : dict {port_name: type_str}
      - run(inputs)     : dict of the outputs

    Optionnel :
      - ai_plugin       : AIPlugin instance attached to this node
      - ai_blend_weight : weight of the AI output in the final blend (0.0 = AI ignored)
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
    # To be implemented in every concrete node
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def node_type(self) -> str:
        """Node type identifier, e.g. 'LoadMultiTF'."""

    @staticmethod
    @abstractmethod
    def input_schema() -> dict[str, str]:
        """Input port -> expected type. E.g. {'ohlcv': 'DataFrame'}."""

    @staticmethod
    @abstractmethod
    def output_schema() -> dict[str, str]:
        """Output port → produced type. E.g. {'features': 'DataFrame'}."""

    @abstractmethod
    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Synchronous execution. Receives the resolved inputs, returns the outputs."""

    # ------------------------------------------------------------------
    # Shared logic (bypass, AI blend, status)
    # ------------------------------------------------------------------

    def execute(self, inputs: dict[str, Any]) -> NodeRunResult:
        """Entry point called by the DAGExecutor."""
        import time

        if self.meta.bypass:
            self.status = NodeStatus.BYPASSED
            # Passes the first input straight through to the output
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

            # AI blend when a plugin is connected
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
        """Try the AI blend with a timeout. Silent fallback on error."""
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
        """Partial serialisation for the DAG JSON (without outputs)."""
        return {
            "id": self.node_id,
            "type": self.node_type,
            "position": {"x": self.meta.x, "y": self.meta.y},
            "params": self.params,
            "bypass": self.meta.bypass,
            "cycle_interval_s": self.meta.cycle_interval_s,
        }
