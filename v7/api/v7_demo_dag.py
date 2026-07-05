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


def _carry_defaults():
    """Lit les paramètres carry depuis asset_profiles.yaml → v7_carry_defaults."""
    try:
        import yaml, os
        path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "asset_profiles.yaml")
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("v7_carry_defaults", {})
    except Exception:
        return {}


def _make_v7_dag(dag_id: str, symbol: str, capital: float = CAPITAL_PER_ASSET) -> DAGSpec:
    """Fabrique un DAG V7: AssetDef → FundingCarry → PaperTrader + Record + LLM."""
    pfx = symbol.split("/")[0].lower()[:3]
    cd = _carry_defaults()

    nodes = [
        NodeSpec(id=f"{pfx}_asset", type="AssetDef",
                 params={"symbol": symbol, "exchange": "binance",
                          "capital_usd": capital, "fraction": cd.get("fraction", 0.80),
                          "max_positions": 3}),
        # V7 Funding Carry (params depuis asset_profiles.yaml → v7_carry_defaults)
        NodeSpec(id=f"{pfx}_carry", type="FundingCarryNode",
                 params={"symbol": symbol, "capital": capital,
                          "fraction": cd.get("fraction", 0.80),
                          "min_funding": cd.get("min_funding", 0.00001),
                          "max_funding": cd.get("max_funding", 0.003),
                          "exit_after_hours": cd.get("exit_after_hours", 72),
                          "kelly_fraction": cd.get("kelly_fraction", 0.35),
                          "max_hold_days": cd.get("max_hold_days", 21),
                          "stop_loss_pct": cd.get("stop_loss_pct", -0.045),
                          "max_portfolio_dd_pct": cd.get("max_portfolio_dd_pct", 0.20)}),
        # PaperTrader — exécute le signal carry (max 1 position par actif)
        NodeSpec(id=f"{pfx}_paper", type="PaperTrader",
                 params={"symbol": symbol, "dag_id": dag_id, "max_positions": 1}),
        NodeSpec(id=f"{pfx}_record", type="RecordDecision",
                 params={"db_path": "/app/data/v4.db", "symbol": symbol, "dag_id": dag_id}),
        # LLM AI Analyst (analyse async de la décision carry)
        NodeSpec(id=f"{pfx}_llm", type="LLMNode",
                 params={"model": "deepseek-chat", "temperature": 0.3,
                          "max_tokens": 256, "async_mode": True,
                          "dag_id": dag_id,
                          "system_prompt": "You are a crypto funding-rate analyst. Analyze the carry trade decision.",
                          "user_prompt": "Decision: {decision} | Funding rate: {funding_rate} | Annual: {annual_funding_pct} | Signal: {signal} | Size: ${size_usd} | Expected return: {expected_return}"}),
    ]

    edges = [
        EdgeSpec(source_node=f"{pfx}_asset", source_port="symbol",
                 target_node=f"{pfx}_carry", target_port="symbol"),
        EdgeSpec(source_node=f"{pfx}_asset", source_port="symbol",
                 target_node=f"{pfx}_paper", target_port="symbol"),
        # Carry → PaperTrader (execution)
        EdgeSpec(source_node=f"{pfx}_carry", source_port="decision",
                 target_node=f"{pfx}_paper", target_port="decision"),
        # Carry → Record (logging) — avec trade_id pour lien
        EdgeSpec(source_node=f"{pfx}_carry", source_port="decision",
                 target_node=f"{pfx}_record", target_port="decision"),
        EdgeSpec(source_node=f"{pfx}_paper", source_port="trade_result",
                 target_node=f"{pfx}_record", target_port="trade_result"),
        # Carry → LLM (AI analysis)
        EdgeSpec(source_node=f"{pfx}_carry", source_port="decision",
                 target_node=f"{pfx}_llm", target_port="decision"),
        EdgeSpec(source_node=f"{pfx}_carry", source_port="funding_rate",
                 target_node=f"{pfx}_llm", target_port="funding_rate"),
        EdgeSpec(source_node=f"{pfx}_carry", source_port="annual_funding_pct",
                 target_node=f"{pfx}_llm", target_port="annual_funding_pct"),
        EdgeSpec(source_node=f"{pfx}_carry", source_port="signal",
                 target_node=f"{pfx}_llm", target_port="signal"),
        EdgeSpec(source_node=f"{pfx}_carry", source_port="size_usd",
                 target_node=f"{pfx}_llm", target_port="size_usd"),
        EdgeSpec(source_node=f"{pfx}_carry", source_port="expected_return",
                 target_node=f"{pfx}_llm", target_port="expected_return"),
    ]

    return DAGSpec(dag_id=dag_id, asset=symbol, nodes=nodes, edges=edges)


# ── DAGs pré-construits ──
V7_DAGS = [
    _make_v7_dag(f"v7_{sym.split('/')[0].lower()}", sym)
    for sym in SYMBOLS
]
