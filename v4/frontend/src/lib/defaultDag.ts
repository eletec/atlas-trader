/**
 * v4/frontend/src/lib/defaultDag.ts
 *
 * DAG démo par défaut — pipeline quant unifié, XGBoost décide long/short/flat.
 *
 * Layout : colonnes espacées de 280px.
 */
import type { Node as RFNode, Edge as RFEdge } from "@xyflow/react";

const COL_W = 280;

// Positions par colonne (x)
const X = [0, 1, 2, 3, 4, 5, 6, 7, 8].map((i) => 50 + i * COL_W);
const Y_TOP = 50;

interface NodeSpec {
  id: string;
  type: string;
  x: number;
  y: number;
  label: string;
  params: Record<string, unknown>;
  inputPorts: string[];
  outputPorts: string[];
}

function makeNode(spec: NodeSpec): RFNode {
  return {
    id: spec.id,
    type: spec.type,
    position: { x: spec.x, y: spec.y },
    data: {
      label: spec.label,
      nodeType: spec.type,
      inputPorts: spec.inputPorts,
      outputPorts: spec.outputPorts,
      params: spec.params,
    },
  };
}

const NODES_SPEC: NodeSpec[] = [
  // ═══════════════════════════════════════════════════════════════
  // Pipeline Quant unifié — XGBoost décide long/short/flat
  // ═══════════════════════════════════════════════════════════════

  // Col 0 : Actif
  {
    id: "btc_asset", type: "AssetDef", x: X[0], y: Y_TOP, label: "BTC/USDT",
    params: { symbol: "BTC/USDT", exchange: "binance", capital_usd: 10000, fraction: 0.02, max_positions: 3, keywords: ["bitcoin"] },
    inputPorts: [], outputPorts: ["symbol", "exchange", "capital", "fraction", "max_positions"],
  },

  // Col 1 : Données
  {
    id: "btc_data", type: "LoadMultiTF", x: X[1], y: Y_TOP, label: "Load 5m + 1h",
    params: { symbol: "BTC/USDT", days_5m: 90, days_1h: 100, exchange: "binance" },
    inputPorts: ["symbol"], outputPorts: ["ohlcv_5m", "ohlcv_1h"],
  },

  // Col 2 : Features
  {
    id: "btc_features", type: "ComputeFeatures", x: X[2], y: Y_TOP, label: "Compute Features",
    params: {}, inputPorts: ["ohlcv"], outputPorts: ["features"],
  },

  // Col 3 : Normalisation
  {
    id: "btc_norm", type: "Normalize", x: X[3], y: Y_TOP, label: "Normalize",
    params: { window: 500 }, inputPorts: ["features"], outputPorts: ["features_norm", "features_all"],
  },

  // Col 4 : Régime + Tendance (parallèle)
  {
    id: "btc_regime", type: "RegimeHMM", x: X[4], y: Y_TOP - 60, label: "Regime HMM",
    params: { n_states: 3 }, inputPorts: ["features_all"], outputPorts: ["regime", "regime_state"],
  },
  {
    id: "btc_trend", type: "TrendFilter", x: X[4], y: Y_TOP + 60, label: "Trend 4h (SMA20/50)",
    params: { timeframe_resample: "4h", sma_fast: 20, sma_slow: 50 },
    inputPorts: ["ohlcv_1h"], outputPorts: ["trend", "sma20", "sma50", "slope"],
  },

  // Col 5 : Signal
  {
    id: "btc_signal", type: "SignalLogReg", x: X[5], y: Y_TOP, label: "Signal LogReg",
    params: { calibrate: true, train_fraction: 0.70, horizon_bars: 48, p_up_threshold: 0.55, p_dn_threshold: 0.45 },
    inputPorts: ["features_all", "regime"], outputPorts: ["signal", "prob_up", "reason"],
  },

  // Col 6 : Gate — MetaGate V5 (LogisticRegression apprise)
  {
    id: "btc_gate", type: "MetaGate", x: X[6], y: Y_TOP, label: "MetaGate V5",
    params: { threshold: 0.20, model_path: "/app/data/models/meta_btc.pkl" },
    inputPorts: ["signal", "prob_up", "trend", "debate_signal", "debate_conf", "crosstf_signal", "crosstf_conf", "regime"],
    outputPorts: ["signal", "blocked", "reason", "score"],
  },

  // Col 7 : Risk
  {
    id: "btc_risk", type: "RiskATR", x: X[7], y: Y_TOP, label: "Risk ATR (2:1)",
    params: { sl_mult: 2.0, tp_mult: 4.0, fraction: 0.005, capital: 10000 },
    inputPorts: ["signal", "ohlcv_1h", "capital"], outputPorts: ["decision"],
  },

  // Col 8 : Sorties (2 nœuds parallèles)
  {
    id: "btc_paper", type: "PaperTrader", x: X[8], y: Y_TOP - 60, label: "Paper Trader",
    params: {}, inputPorts: ["decision", "symbol"], outputPorts: ["trade_result"],
  },
  {
    id: "btc_record", type: "RecordDecision", x: X[8], y: Y_TOP + 60, label: "Record DB",
    params: { db_path: "/app/storage/v4_decisions.db" }, inputPorts: ["decision"], outputPorts: [],
  },

  // ═══════════════════════════════════════════════════════════════
  // LANE 3 — Analyse IA (LLM)
  // ═══════════════════════════════════════════════════════════════
  {
    id: "ai_analyst", type: "LLMNode", x: X[8], y: Y_TOP + 160, label: "AI Analyst",
    params: {
      system_prompt: "You are a crypto trading analyst. Respond in JSON with keys: sentiment (bullish/bearish/neutral), confidence (0-100), reason (short).",
      user_prompt: "Market data: {inputs}",
      model: "phi4:latest",
      temperature: 0.3,
      max_tokens: 256,
    },
    inputPorts: ["decision", "regime", "trend"], outputPorts: ["response", "parsed", "tokens_used", "model", "duration_ms"],
  },
];

const EDGES_SPEC: Array<{ src: string; dst: string; srcPort?: string; dstPort?: string }> = [
  // ── Pipeline unifié ─────────────────────────────────────────
  { src: "btc_asset", dst: "btc_data", srcPort: "symbol", dstPort: "symbol" },

  // Data → Features
  { src: "btc_data", dst: "btc_features", srcPort: "ohlcv_5m", dstPort: "ohlcv" },

  // Features → Norm
  { src: "btc_features", dst: "btc_norm", srcPort: "features", dstPort: "features" },

  // Norm → Regime
  { src: "btc_norm", dst: "btc_regime", srcPort: "features_all", dstPort: "features_all" },

  // Data → Trend (ohlcv_1h pour resample 4h)
  { src: "btc_data", dst: "btc_trend", srcPort: "ohlcv_1h", dstPort: "ohlcv_1h" },

  // Norm → Signal
  { src: "btc_norm", dst: "btc_signal", srcPort: "features_all", dstPort: "features_all" },
  { src: "btc_regime", dst: "btc_signal", srcPort: "regime", dstPort: "regime" },

  // Signal + Trend → Gate
  { src: "btc_signal", dst: "btc_gate", srcPort: "signal", dstPort: "signal" },
  { src: "btc_trend", dst: "btc_gate", srcPort: "trend", dstPort: "trend" },

  // Gate → Risk
  { src: "btc_gate", dst: "btc_risk", srcPort: "signal", dstPort: "signal" },
  { src: "btc_data", dst: "btc_risk", srcPort: "ohlcv_1h", dstPort: "ohlcv_1h" },
  { src: "btc_asset", dst: "btc_risk", srcPort: "capital", dstPort: "capital" },

  // Risk → Sorties
  { src: "btc_risk", dst: "btc_paper", srcPort: "decision", dstPort: "decision" },
  { src: "btc_asset", dst: "btc_paper", srcPort: "symbol", dstPort: "symbol" },
  { src: "btc_risk", dst: "btc_record", srcPort: "decision", dstPort: "decision" },

  // ── Lane 3 : AI Analyst ────────────────────────────────────────
  { src: "btc_risk", dst: "ai_analyst", srcPort: "decision", dstPort: "decision" },
  { src: "btc_regime", dst: "ai_analyst", srcPort: "regime", dstPort: "regime" },
  { src: "btc_trend", dst: "ai_analyst", srcPort: "trend", dstPort: "trend" },
];

export function getDefaultNodes(): RFNode[] {
  return NODES_SPEC.map(makeNode);
}

export function getDefaultEdges(): RFEdge[] {
  return EDGES_SPEC.map((e, i) => ({
    id: `e_${e.src}_${e.dst}_${i}`,
    source: e.src,
    target: e.dst,
    sourceHandle: e.srcPort ?? undefined,
    targetHandle: e.dstPort ?? undefined,
    animated: false,
    style: { stroke: "#2e3352", strokeWidth: 2 },
  }));
}

export function clearDefaultDag() {
  if (typeof window !== "undefined") {
    localStorage.removeItem("atlas_v4_dag");
  }
}
