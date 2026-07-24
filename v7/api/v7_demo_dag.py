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

def _get_symbols_and_capital():
    """Lit les actifs actifs et leurs paramètres depuis carry_assets.yaml."""
    try:
        from v7.core.asset_config import get_active_assets, get_asset_params, get_global_params
        symbols = get_active_assets()
        if not symbols:
            raise ValueError("No active assets in carry_assets.yaml")
        global_cfg = get_global_params()
        default_capital = float(global_cfg.get("total_capital", 14000)) / max(len(symbols), 1)
        return symbols, default_capital
    except Exception:
        return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"], 2_000

SYMBOLS, CAPITAL_PER_ASSET = _get_symbols_and_capital()


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


def _make_v7_dag(dag_id: str, symbol: str, capital: float | None = None) -> DAGSpec:
    """Fabrique un DAG V7: AssetDef → FundingCarry → PaperTrader + Record + LLM.
    
    Les paramètres sont lus depuis carry_assets.yaml (per-asset) avec fallback sur les defaults.
    """
    pfx = symbol.split("/")[0].lower()[:3]
    
    # Lire les params per-asset depuis carry_assets.yaml
    try:
        from v7.core.asset_config import get_asset_params
        ap = get_asset_params(symbol)
    except Exception:
        ap = {}
    
    if capital is None:
        capital = float(ap.get("capital", CAPITAL_PER_ASSET))

    nodes = [
        NodeSpec(id=f"{pfx}_asset", type="AssetDef",
                 params={"symbol": symbol, "exchange": "binance",
                          "capital_usd": capital, "fraction": ap.get("fraction", 0.80),
                          "max_positions": 3}),
        # V7 Funding Carry (params depuis carry_assets.yaml per-asset)
        NodeSpec(id=f"{pfx}_carry", type="FundingCarryNode",
                 params={"symbol": symbol, "capital": capital,
                          "fraction": ap.get("fraction", 0.50),
                          "min_funding": ap.get("min_funding", 0.00005),
                          "max_funding": ap.get("max_funding", 0.003),
                          "exit_after_hours": ap.get("exit_after_hours", 72),
                          "leverage": ap.get("leverage", 1.0),
                          "max_hold_days": ap.get("max_hold_days", 14),
                          "safety_cap": ap.get("safety_cap", 200),
                          "stress_loss_pct": ap.get("stress_loss_pct", 0.10),
                          "stop_loss_pct": ap.get("stop_loss_pct", -0.045),
                          "max_portfolio_dd_pct": ap.get("max_portfolio_dd_pct", 0.20),
                          "max_loss_pct": ap.get("max_loss_pct", -0.05)}),
        # PaperTrader — exécute le signal carry (max 1 position par actif)
        NodeSpec(id=f"{pfx}_paper", type="PaperTrader",
                 params={"symbol": symbol, "dag_id": dag_id, "max_positions": 1}),
        NodeSpec(id=f"{pfx}_record", type="RecordDecision",
                 params={"db_path": "/app/data/v4.db", "symbol": symbol, "dag_id": dag_id}),
        # LLM AI Analyst (analyse async de la décision carry — modèle rapide)
        NodeSpec(id=f"{pfx}_llm", type="LLMNode",
                 params={"use_fast": True, "temperature": 0.3,
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
    _make_v7_dag(f"v7_{sym.split('/')[0].lower()}", sym, CAPITAL_PER_ASSET)
    for sym in SYMBOLS
]
