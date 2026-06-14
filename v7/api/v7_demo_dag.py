"""
v7/api/v7_demo_dag.py — V7 Minimal DAG (Funding Carry only).

Remplace le DAG directionnel V6 (16 nœuds, 0 edge) par un DAG V7 léger.
Par actif: AssetDef → LoadData → FundingCarry → Record

Usage (dans main.py):
    from v7.api.v7_demo_dag import V7_DAGS
    for dag in V7_DAGS:
        registry.schedule(dag, cycle_s=28800)  # 8h
"""
from __future__ import annotations
from v4.api.models import DAGSpec, NodeSpec, EdgeSpec

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
CAPITAL_PER_ASSET = 2_000  # $2K par actif en carry


def _make_v7_dag(dag_id: str, symbol: str, capital: float = CAPITAL_PER_ASSET) -> DAGSpec:
    """Fabrique un DAG V7 minimal: Data → Carry → Record."""
    pfx = symbol.split("/")[0].lower()[:3]

    nodes = [
        NodeSpec(id=f"{pfx}_asset", type="AssetDef",
                 params={"symbol": symbol, "exchange": "binance",
                          "capital_usd": capital, "fraction": 0.80,
                          "max_positions": 3}),
        NodeSpec(id=f"{pfx}_data", type="LoadMultiTF",
                 params={"symbol": symbol, "days_5m": 30, "days_1h": 90,
                          "exchange": "binance"}),
        # V7 Funding Carry
        NodeSpec(id=f"{pfx}_carry", type="FundingCarryNode",
                 params={"symbol": symbol, "capital": capital,
                          "fraction": 0.80, "min_funding": 0.00001,
                          "exit_after_hours": 168}),
        # PaperTrader — exécute le signal carry
        NodeSpec(id=f"{pfx}_paper", type="PaperTrader",
                 params={"symbol": symbol, "dag_id": dag_id}),
        NodeSpec(id=f"{pfx}_record", type="RecordDecision",
                 params={"db_path": "/app/data/v4.db"}),
    ]

    edges = [
        EdgeSpec(source_node=f"{pfx}_asset", source_port="symbol",
                 target_node=f"{pfx}_data", target_port="symbol"),
        EdgeSpec(source_node=f"{pfx}_asset", source_port="symbol",
                 target_node=f"{pfx}_paper", target_port="symbol"),
        EdgeSpec(source_node=f"{pfx}_asset", source_port="max_positions",
                 target_node=f"{pfx}_paper", target_port="max_positions"),
        # Carry → PaperTrader (execution)
        EdgeSpec(source_node=f"{pfx}_carry", source_port="decision",
                 target_node=f"{pfx}_paper", target_port="decision"),
        # Carry → Record (logging)
        EdgeSpec(source_node=f"{pfx}_carry", source_port="decision",
                 target_node=f"{pfx}_record", target_port="decision"),
    ]

    return DAGSpec(dag_id=dag_id, nodes=nodes, edges=edges)


# ── DAGs pré-construits ──
V7_DAGS = [
    _make_v7_dag(f"v7_{sym.split('/')[0].lower()}", sym)
    for sym in SYMBOLS
]
