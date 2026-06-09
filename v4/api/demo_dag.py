"""
v4/api/demo_dag.py — DAGs démo auto-démarrés au boot de l'API.

Un DAG par actif, tous construits par _make_dag().
Modifier _make_dag() = modifier TOUS les DAGs.
"""
from __future__ import annotations
from v4.api.models import DAGSpec, NodeSpec, EdgeSpec


def _make_dag(dag_id: str, symbol: str) -> DAGSpec:
    """Fabrique un DAG complet pour un symbole donné.

    Les nœuds sont préfixés par les 3 premières lettres du symbole
    (ex: btc_asset, eth_data, sol_signal...).
    """
    pfx = symbol.split("/")[0].lower()[:3]  # "btc", "eth", "sol", "bnb", "xrp"

    nodes = [
        # ── Colonne 0 : Définition de l'actif ──
        NodeSpec(id=f"{pfx}_asset", type="AssetDef",
                 params={"symbol": symbol, "exchange": "binance",
                          "capital_usd": 10000, "fraction": 0.02}),
        # ── Colonne 1 : Données OHLCV ──
        NodeSpec(id=f"{pfx}_data", type="LoadMultiTF",
                 params={"symbol": symbol, "days_5m": 90, "days_1h": 100,
                          "exchange": "binance"}),
        # ── Colonne 1b : Cross-TF Repricing (microstructure) ──
        NodeSpec(id=f"{pfx}_crosstf", type="CrossTFArb",
                 params={"mode": "divergence", "momentum_5m": 6,
                          "momentum_1h": 4, "threshold": 0.15,
                          "strong_threshold": 0.40}),
        # ── Colonne 1c : Position Manager (trailing exit) ──
        NodeSpec(id=f"{pfx}_posmgr", type="PositionManager",
                 params={"symbol": symbol, "exit_strategy": "trailing",
                          "atr_mult": 3.0, "trail_mult": 0.5,
                          "min_atr_dist": 0.5, "chandelier_lookback": 12}),
        # ── Colonne 2 : Features techniques ──
        NodeSpec(id=f"{pfx}_features", type="ComputeFeatures", params={}),
        # ── Colonne 3 : Normalisation ──
        NodeSpec(id=f"{pfx}_norm", type="Normalize", params={"window": 500}),
        # ── Colonne 4 : Régime (toujours TREND en mode agressif) ──
        NodeSpec(id=f"{pfx}_regime", type="RegimePassthrough",
                 params={"regime": "TREND"}),
        # ── Colonne 4b : Tendance SMA ──
        NodeSpec(id=f"{pfx}_trend", type="TrendFilter",
                 params={"timeframe_resample": "4h", "sma_fast": 20,
                          "sma_slow": 50}),
        # ── Colonne 5 : Signal XGBoost ──
        NodeSpec(id=f"{pfx}_signal", type="SignalXGB",
                 params={"calibrate": True, "train_fraction": 0.70,
                          "horizon_bars": 48, "p_up_threshold": 0.55,
                          "p_dn_threshold": 0.45, "retrain_cycle": 120,
                          "max_depth": 5, "n_estimators": 100,
                          "lag_features": 3}),
        # ── Colonne 6 : Gate directionnel ──
        NodeSpec(id=f"{pfx}_gate", type="DirectionGate",
                 params={"allow_long": True, "allow_short": True}),
        # ── Colonne 7 : Risk ATR ──
        NodeSpec(id=f"{pfx}_risk", type="RiskATR",
                 params={"sl_mult": 2.0, "tp_mult": 4.0, "fraction": 0.02,
                          "risk_pct": 1.0, "capital": 10000}),
        # ── Colonne 8 : PaperTrader LONG ──
        NodeSpec(id=f"{pfx}_paper", type="PaperTrader",
                 params={"symbol": symbol, "dag_id": dag_id}),
        # ── Colonne 8b : Record DB ──
        NodeSpec(id=f"{pfx}_record", type="RecordDecision",
                 params={"db_path": "/app/data/v4_decisions.db"}),
        # ── Colonne 9 : AI Analyst ──
        NodeSpec(id=f"{pfx}_ai", type="LLMNode",
                 params={"system_prompt": "You are a crypto trading analyst.",
                          "user_prompt": "Market: {inputs}",
                          "temperature": 0.3,
                          "max_tokens": 512, "timeout_s": 60}),

        # ═══ Lane SHORT forcée (démo) ═══
        NodeSpec(id=f"{pfx}_short_sig", type="SignalConstant",
                 params={"signal": "short"}),
        NodeSpec(id=f"{pfx}_short_gate", type="DirectionGate",
                 params={"allow_long": False, "allow_short": True}),
        NodeSpec(id=f"{pfx}_short_risk", type="RiskATR",
                 params={"sl_mult": 3.0, "tp_mult": 6.0, "fraction": 0.015,
                          "risk_pct": 1.0, "capital": 10000}),
        NodeSpec(id=f"{pfx}_short_paper", type="PaperTrader",
                 params={"symbol": symbol, "dag_id": dag_id}),
        NodeSpec(id=f"{pfx}_short_alert", type="AlertOnly",
                 params={"channels": ["log"]}),
    ]

    edges = [
        # ── Lane LONG ──
        EdgeSpec(source_node=f"{pfx}_asset", source_port="symbol",
                 target_node=f"{pfx}_data", target_port="symbol"),
        EdgeSpec(source_node=f"{pfx}_data", source_port="ohlcv_5m",
                 target_node=f"{pfx}_features", target_port="ohlcv"),
        EdgeSpec(source_node=f"{pfx}_data", source_port="ohlcv_5m",
                 target_node=f"{pfx}_crosstf", target_port="ohlcv_5m"),
        EdgeSpec(source_node=f"{pfx}_data", source_port="ohlcv_1h",
                 target_node=f"{pfx}_crosstf", target_port="ohlcv_1h"),
        EdgeSpec(source_node=f"{pfx}_data", source_port="ohlcv_5m",
                 target_node=f"{pfx}_posmgr", target_port="ohlcv_5m"),
        EdgeSpec(source_node=f"{pfx}_data", source_port="ohlcv_1h",
                 target_node=f"{pfx}_posmgr", target_port="ohlcv_1h"),
        EdgeSpec(source_node=f"{pfx}_features", source_port="features",
                 target_node=f"{pfx}_norm", target_port="features"),
        EdgeSpec(source_node=f"{pfx}_norm", source_port="features_all",
                 target_node=f"{pfx}_signal", target_port="features_all"),
        EdgeSpec(source_node=f"{pfx}_norm", source_port="features_all",
                 target_node=f"{pfx}_regime", target_port="features_all"),
        EdgeSpec(source_node=f"{pfx}_data", source_port="ohlcv_1h",
                 target_node=f"{pfx}_trend", target_port="ohlcv_1h"),
        EdgeSpec(source_node=f"{pfx}_regime", source_port="regime",
                 target_node=f"{pfx}_signal", target_port="regime"),
        EdgeSpec(source_node=f"{pfx}_signal", source_port="signal",
                 target_node=f"{pfx}_gate", target_port="signal"),
        EdgeSpec(source_node=f"{pfx}_trend", source_port="trend",
                 target_node=f"{pfx}_gate", target_port="trend"),
        EdgeSpec(source_node=f"{pfx}_gate", source_port="signal",
                 target_node=f"{pfx}_risk", target_port="signal"),
        EdgeSpec(source_node=f"{pfx}_data", source_port="ohlcv_1h",
                 target_node=f"{pfx}_risk", target_port="ohlcv_1h"),
        EdgeSpec(source_node=f"{pfx}_asset", source_port="capital",
                 target_node=f"{pfx}_risk", target_port="capital"),
        EdgeSpec(source_node=f"{pfx}_risk", source_port="decision",
                 target_node=f"{pfx}_paper", target_port="decision"),
        EdgeSpec(source_node=f"{pfx}_asset", source_port="symbol",
                 target_node=f"{pfx}_paper", target_port="symbol"),
        EdgeSpec(source_node=f"{pfx}_risk", source_port="decision",
                 target_node=f"{pfx}_record", target_port="decision"),
        # ── Lane SHORT ──
        EdgeSpec(source_node=f"{pfx}_data", source_port="ohlcv_1h",
                 target_node=f"{pfx}_short_risk", target_port="ohlcv_1h"),
        EdgeSpec(source_node=f"{pfx}_asset", source_port="capital",
                 target_node=f"{pfx}_short_risk", target_port="capital"),
        EdgeSpec(source_node=f"{pfx}_short_sig", source_port="signal",
                 target_node=f"{pfx}_short_gate", target_port="signal"),
        EdgeSpec(source_node=f"{pfx}_trend", source_port="trend",
                 target_node=f"{pfx}_short_gate", target_port="trend"),
        EdgeSpec(source_node=f"{pfx}_short_gate", source_port="signal",
                 target_node=f"{pfx}_short_risk", target_port="signal"),
        EdgeSpec(source_node=f"{pfx}_short_risk", source_port="decision",
                 target_node=f"{pfx}_short_paper", target_port="decision"),
        EdgeSpec(source_node=f"{pfx}_asset", source_port="symbol",
                 target_node=f"{pfx}_short_paper", target_port="symbol"),
        EdgeSpec(source_node=f"{pfx}_short_risk", source_port="decision",
                 target_node=f"{pfx}_short_alert", target_port="decision"),
        # ── AI Analyst ──
        EdgeSpec(source_node=f"{pfx}_risk", source_port="decision",
                 target_node=f"{pfx}_ai", target_port="decision"),
        EdgeSpec(source_node=f"{pfx}_regime", source_port="regime",
                 target_node=f"{pfx}_ai", target_port="regime"),
        EdgeSpec(source_node=f"{pfx}_trend", source_port="trend",
                 target_node=f"{pfx}_ai", target_port="trend"),
        EdgeSpec(source_node=f"{pfx}_crosstf", source_port="signal",
                 target_node=f"{pfx}_ai", target_port="cross_tf_signal"),
    ]

    return DAGSpec(dag_id=dag_id, asset=symbol, nodes=nodes, edges=edges)


# ── DAGs par actif ──────────────────────────────────────────────────────────
DEMO_DAG  = _make_dag("demo_v4",  "BTC/USDT")
DEMO_ETH  = _make_dag("demo_eth", "ETH/USDT")
DEMO_SOL  = _make_dag("demo_sol", "SOL/USDT")
DEMO_BNB  = _make_dag("demo_bnb", "BNB/USDT")
DEMO_XRP  = _make_dag("demo_xrp", "XRP/USDT")
