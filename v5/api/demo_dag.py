"""
v5/api/demo_dag.py — DAGs démo V5 avec MetaGate + CircuitBreaker.

Remplace DirectionGate (fusion) par MetaGate (LogisticRegression apprise).
Ajoute CircuitBreaker entre RiskATR et PaperTrader.
Ajoute PortfolioRisk pour contrôle d'exposition inter-actifs.
"""
from __future__ import annotations
from v4.api.models import DAGSpec, NodeSpec, EdgeSpec
import os


def _make_dag(dag_id: str, symbol: str, intensity: str = "balanced") -> DAGSpec:
    """Fabrique un DAG V5 pour un symbole donné."""
    pfx = symbol.split("/")[0].lower()[:3]

    # ── Presets ──
    PRESETS = {
        "conservative": dict(p_up=0.55, p_dn=0.45, meta_th=0.30, sl_mult=2.0, tp_mult=4.0,
                             max_pos=1, exit_strat="chandelier", exit_atr=3.0),
        "balanced": dict(p_up=0.52, p_dn=0.48, meta_th=0.20, sl_mult=2.5, tp_mult=5.0,
                         max_pos=3, exit_strat="chandelier", exit_atr=3.0),
        "aggressive": dict(p_up=0.51, p_dn=0.49, meta_th=0.10, sl_mult=3.0, tp_mult=6.0,
                           max_pos=5, exit_strat="trailing", exit_atr=4.0),
    }
    p = dict(PRESETS.get(intensity, PRESETS["balanced"]))

    # ── Override par actif ──
    try:
        import yaml
        _profile_path = os.environ.get("ASSET_PROFILES_PATH", "/app/src/config/asset_profiles.yaml")
        if os.path.exists(_profile_path):
            with open(_profile_path) as fh:
                profiles = yaml.safe_load(fh) or {}
            if symbol in profiles:
                for k in ("p_up", "p_dn", "fusion_th", "sl_mult", "tp_mult",
                          "max_pos", "exit_strat", "exit_atr", "fraction"):
                    if k in profiles[symbol]:
                        p[k] = profiles[symbol][k]
                        if k == "fusion_th":
                            p["meta_th"] = profiles[symbol][k]
    except Exception:
        pass

    # ── Modèle MetaGate pickle path ──
    model_path = f"/app/data/models/meta_{pfx}.pkl"

    nodes = [
        NodeSpec(id=f"{pfx}_asset", type="AssetDef",
                 params={"symbol": symbol, "exchange": "binance",
                          "capital_usd": 10000, "fraction": p.get("fraction", 0.05),
                          "max_positions": p["max_pos"]}),
        NodeSpec(id=f"{pfx}_data", type="LoadMultiTF",
                 params={"symbol": symbol, "days_5m": 90, "days_1h": 100,
                          "exchange": "binance"}),
        NodeSpec(id=f"{pfx}_crosstf", type="CrossTFArb",
                 params={"mode": "divergence", "momentum_5m": 6,
                          "momentum_1h": 4, "threshold": 0.15,
                          "strong_threshold": 0.40}),
        NodeSpec(id=f"{pfx}_posmgr", type="PositionManager",
                 params={"symbol": symbol, "exit_strategy": p["exit_strat"],
                          "atr_mult": p["exit_atr"], "trail_mult": 0.5,
                          "min_atr_dist": 0.5, "chandelier_lookback": 12}),
        NodeSpec(id=f"{pfx}_features", type="ComputeFeatures", params={}),
        NodeSpec(id=f"{pfx}_norm", type="Normalize", params={"window": 500}),
        NodeSpec(id=f"{pfx}_regime", type="RegimeDetector",
                 params={"adx_period": 14, "chop_period": 14,
                          "trend_threshold": 25, "range_threshold": 20,
                          "chop_threshold": 61.8}),
        NodeSpec(id=f"{pfx}_trend", type="TrendFilter",
                 params={"timeframe_resample": "4h", "sma_fast": 20, "sma_slow": 50}),
        NodeSpec(id=f"{pfx}_signal", type="SignalXGB",
                 params={"calibrate": True, "train_fraction": 0.70,
                          "horizon_bars": 48, "p_up_threshold": p["p_up"],
                          "p_dn_threshold": p["p_dn"], "retrain_cycle": 120,
                          "max_depth": 5, "n_estimators": 100, "lag_features": 3}),
        # ── V5: MetaGate remplace DirectionGate ──
        NodeSpec(id=f"{pfx}_gate", type="MetaGate",
                 params={"threshold": p["meta_th"], "model_path": model_path}),
        NodeSpec(id=f"{pfx}_risk", type="RiskATR",
                 params={"sl_mult": p["sl_mult"], "tp_mult": p["tp_mult"],
                          "fraction": p.get("fraction", 0.05),
                          "risk_pct": 1.0, "capital": 10000}),
        # ── V5: CircuitBreaker entre RiskATR et PaperTrader ──
        NodeSpec(id=f"{pfx}_breaker", type="CircuitBreaker",
                 params={"dd_warn_pct": -3.0, "dd_kill_pct": -5.0}),
        # ── V5: PortfolioRisk contrôle exposition inter-actifs ──
        NodeSpec(id=f"{pfx}_pfrisk", type="PortfolioRisk",
                 params={"max_cluster_pct": 30.0, "max_total_pct": 150.0,
                          "capital": 10000}),
        NodeSpec(id=f"{pfx}_paper", type="PaperTrader",
                 params={"symbol": symbol, "dag_id": dag_id}),
        NodeSpec(id=f"{pfx}_record", type="RecordDecision",
                 params={"db_path": "/app/data/v4_decisions.db"}),
        NodeSpec(id=f"{pfx}_reflect", type="ReflectionNode",
                 params={"max_lessons": 5, "min_pnl_abs": 1.0}),
        NodeSpec(id=f"{pfx}_ai", type="LLMNode",
                 params={"dag_id": dag_id, "async_mode": True,
                          "system_prompt": "You are a crypto trading analyst.",
                          "user_prompt": "{reflections}\n\nMarket: {inputs}",
                          "temperature": 0.3, "max_tokens": 512, "timeout_s": 60}),
        NodeSpec(id=f"{pfx}_debate", type="DebateNode",
                 params={"dag_id": dag_id, "async_mode": True,
                          "temperature": 0.4, "max_tokens": 512, "timeout_s": 90}),
    ]

    edges = [
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
        EdgeSpec(source_node=f"{pfx}_data", source_port="ohlcv_1h",
                 target_node=f"{pfx}_regime", target_port="ohlcv_1h"),
        EdgeSpec(source_node=f"{pfx}_data", source_port="ohlcv_1h",
                 target_node=f"{pfx}_trend", target_port="ohlcv_1h"),
        EdgeSpec(source_node=f"{pfx}_regime", source_port="regime",
                 target_node=f"{pfx}_signal", target_port="regime"),
        # ── Signal → MetaGate ──
        EdgeSpec(source_node=f"{pfx}_signal", source_port="signal",
                 target_node=f"{pfx}_gate", target_port="signal"),
        EdgeSpec(source_node=f"{pfx}_signal", source_port="prob_up",
                 target_node=f"{pfx}_gate", target_port="prob_up"),
        EdgeSpec(source_node=f"{pfx}_trend", source_port="trend",
                 target_node=f"{pfx}_gate", target_port="trend"),
        EdgeSpec(source_node=f"{pfx}_crosstf", source_port="signal",
                 target_node=f"{pfx}_gate", target_port="crosstf_signal"),
        EdgeSpec(source_node=f"{pfx}_crosstf", source_port="confidence",
                 target_node=f"{pfx}_gate", target_port="crosstf_conf"),
        EdgeSpec(source_node=f"{pfx}_regime", source_port="regime",
                 target_node=f"{pfx}_gate", target_port="regime"),
        # ── MetaGate → RiskATR ──
        EdgeSpec(source_node=f"{pfx}_gate", source_port="signal",
                 target_node=f"{pfx}_risk", target_port="signal"),
        EdgeSpec(source_node=f"{pfx}_data", source_port="ohlcv_1h",
                 target_node=f"{pfx}_risk", target_port="ohlcv_1h"),
        EdgeSpec(source_node=f"{pfx}_asset", source_port="capital",
                 target_node=f"{pfx}_risk", target_port="capital"),
        # ── RiskATR → CircuitBreaker → PortfolioRisk → PaperTrader ──
        EdgeSpec(source_node=f"{pfx}_risk", source_port="decision",
                 target_node=f"{pfx}_breaker", target_port="decision"),
        EdgeSpec(source_node=f"{pfx}_breaker", source_port="decision",
                 target_node=f"{pfx}_pfrisk", target_port="decision"),
        EdgeSpec(source_node=f"{pfx}_asset", source_port="symbol",
                 target_node=f"{pfx}_pfrisk", target_port="symbol"),
        EdgeSpec(source_node=f"{pfx}_pfrisk", source_port="decision",
                 target_node=f"{pfx}_paper", target_port="decision"),
        EdgeSpec(source_node=f"{pfx}_asset", source_port="symbol",
                 target_node=f"{pfx}_paper", target_port="symbol"),
        EdgeSpec(source_node=f"{pfx}_asset", source_port="max_positions",
                 target_node=f"{pfx}_paper", target_port="max_positions"),
        EdgeSpec(source_node=f"{pfx}_risk", source_port="decision",
                 target_node=f"{pfx}_record", target_port="decision"),
        # ── AI ──
        EdgeSpec(source_node=f"{pfx}_risk", source_port="decision",
                 target_node=f"{pfx}_ai", target_port="decision"),
        EdgeSpec(source_node=f"{pfx}_regime", source_port="regime",
                 target_node=f"{pfx}_ai", target_port="regime"),
        EdgeSpec(source_node=f"{pfx}_trend", source_port="trend",
                 target_node=f"{pfx}_ai", target_port="trend"),
        EdgeSpec(source_node=f"{pfx}_crosstf", source_port="signal",
                 target_node=f"{pfx}_ai", target_port="cross_tf_signal"),
        EdgeSpec(source_node=f"{pfx}_reflect", source_port="lessons",
                 target_node=f"{pfx}_ai", target_port="lessons"),
        # ── Débat ──
        EdgeSpec(source_node=f"{pfx}_risk", source_port="decision",
                 target_node=f"{pfx}_debate", target_port="decision"),
        EdgeSpec(source_node=f"{pfx}_regime", source_port="regime",
                 target_node=f"{pfx}_debate", target_port="regime"),
        EdgeSpec(source_node=f"{pfx}_trend", source_port="trend",
                 target_node=f"{pfx}_debate", target_port="trend"),
        EdgeSpec(source_node=f"{pfx}_crosstf", source_port="signal",
                 target_node=f"{pfx}_debate", target_port="cross_tf_signal"),
        EdgeSpec(source_node=f"{pfx}_reflect", source_port="lessons",
                 target_node=f"{pfx}_debate", target_port="lessons"),
    ]

    return DAGSpec(dag_id=dag_id, asset=symbol, nodes=nodes, edges=edges)


# ── DAGs par actif (V5) ──
_V5_INTENSITY = os.environ.get("V5_INTENSITY", "balanced")
DEMO_V5   = _make_dag("demo_v5",   "BTC/USDT", intensity=_V5_INTENSITY)
DEMO_ETH  = _make_dag("demo_eth",  "ETH/USDT", intensity=_V5_INTENSITY)
DEMO_SOL  = _make_dag("demo_sol",  "SOL/USDT", intensity=_V5_INTENSITY)
DEMO_BNB  = _make_dag("demo_bnb",  "BNB/USDT", intensity=_V5_INTENSITY)
DEMO_XRP  = _make_dag("demo_xrp",  "XRP/USDT", intensity=_V5_INTENSITY)
DEMO_ADA  = _make_dag("demo_ada",  "ADA/USDT", intensity=_V5_INTENSITY)
DEMO_DOGE = _make_dag("demo_doge", "DOGE/USDT", intensity=_V5_INTENSITY)
# Alias backward-compat
DEMO_DAG = DEMO_V5
