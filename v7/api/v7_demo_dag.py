"""
v7/api/v7_demo_dag.py — V7 Minimal DAG (Funding Carry only).

Remplace le DAG directionnel V6 (16 nœuds, 0 edge) par un DAG V7 léger.
Par actif: AssetDef → FundingCarry → PaperTrader + Record + LLM
Le FundingCarryNode est autonome : il fetch le funding rate et les prix en direct.

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
    """Fabrique un DAG V7: AssetDef → FundingCarry → PaperTrader + Record + LLM."""
    pfx = symbol.split("/")[0].lower()[:3]

    nodes = [
        NodeSpec(id=f"{pfx}_asset", type="AssetDef",
                 params={"symbol": symbol, "exchange": "binance",
                          "capital_usd": capital, "fraction": 0.80,
                          "max_positions": 3}),
        # V7 Funding Carry (auto-suffisant : fetch funding + prix en direct)
        NodeSpec(id=f"{pfx}_carry", type="FundingCarryNode",
                 params={"symbol": symbol, "capital": capital,
                          "fraction": 0.80, "min_funding": 0.00001,
                          "exit_after_hours": 168}),
        # PaperTrader — exécute le signal carry
        NodeSpec(id=f"{pfx}_paper", type="PaperTrader",
                 params={"symbol": symbol, "dag_id": dag_id}),
        NodeSpec(id=f"{pfx}_record", type="RecordDecision",
                 params={"db_path": "/app/data/v4.db"}),
        # LLM AI Analyst (analyse async de la décision carry)
        NodeSpec(id=f"{pfx}_llm", type="LLMNode",
                 params={"model": "deepseek", "temperature": 0.3,
                          "max_tokens": 256, "async_mode": True,
                          "system_prompt": "You are a crypto funding-rate analyst. Analyze the carry trade decision.",
                          "user_prompt": "Decision: {decision} | Funding rate: {funding_rate} | Annual: {annual_funding_pct} | Signal: {signal} | Size: ${size_usd} | Expected return: {expected_return}"}),
    ]

    edges = [
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
        # Carry → LLM (AI analysis)
        EdgeSpec(source_node=f"{pfx}_carry", source_port="decision",
                 target_node=f"{pfx}_llm", target_port="decision"),
        EdgeSpec(source_node=f"{pfx}_carry", source_port="funding_rate",
                 target_node=f"{pfx}_llm", target_port="funding_rate"),
        EdgeSpec(source_node=f"{pfx}_carry", source_port="annual_funding_pct",
                 target_node=f"{pfx}_llm", target_port="annual_funding_pct"),
    ]

    return DAGSpec(dag_id=dag_id, asset=symbol, nodes=nodes, edges=edges)


# ── DAGs pré-construits ──
V7_DAGS = [
    _make_v7_dag(f"v7_{sym.split('/')[0].lower()}", sym)
    for sym in SYMBOLS
]
