"""
v4/api/models.py — Pydantic models partagés entre routes.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# DAG
# ------------------------------------------------------------------

class NodeSpec(BaseModel):
    """Definition of one node in a JSON DAG."""
    id: str
    type: str                                  # ex: "LoadMultiTF"
    params: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})
    meta: dict[str, Any] = Field(default_factory=dict)


class EdgeSpec(BaseModel):
    source_node: str
    source_port: str
    target_node: str
    target_port: str


class DAGSpec(BaseModel):
    """Full payload describing a graph."""
    dag_id: str
    asset: str = ""
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]
    cycle_s: float | None = None     # None = one-shot, >0 = auto loop


class RunDAGRequest(BaseModel):
    dag: DAGSpec


class ScheduleDAGRequest(BaseModel):
    dag: DAGSpec
    cycle_s: float = Field(gt=0, description="Repeat interval in seconds")


# ------------------------------------------------------------------
## Results
# ------------------------------------------------------------------

class NodeResultOut(BaseModel):
    node_id: str
    status: str
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0
    ai_used: bool = False


class RunDAGResponse(BaseModel):
    dag_id: str
    results: dict[str, NodeResultOut]


class DAGStatusOut(BaseModel):
    dag_id: str
    asset: str
    running: bool
    cycle_s: float | None
    last_run_at: float | None     # timestamp unix
    last_results: dict[str, NodeResultOut] = Field(default_factory=dict)
