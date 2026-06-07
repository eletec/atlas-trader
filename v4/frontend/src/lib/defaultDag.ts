/**
 * v4/frontend/src/lib/defaultDag.ts
 *
 * DAG démo par défaut — utilise TOUS les nœuds V4 dans 2 lanes.
 *
 * Lane 1 (LONG) : pipeline quant complet avec TrendFilter + DirectionGate auto
 * Lane 2 (SHORT forcé) : SignalConstant + DirectionGate SHORT-only + AlertOnly
 *
 * Layout : colonnes espacées de 280px, lanes espacées de 200px.
 */
import type { Node as RFNode, Edge as RFEdge } from "@xyflow/react";

const COL_W = 280;
const ROW_H = 200;

// Positions par colonne (x) et lane (y)
const X = [0, 1, 2, 3, 4, 5, 6, 7, 8].map((i) => 50 + i * COL_W);
const Y_TOP = 50;
const Y_BOT = Y_TOP + ROW_H;

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
  // LANE 1 — Pipeline Quant complet (LONG autorisé, SHORT filtré)
  // ═══════════════════════════════════════════════════════════════

  // Col 0 : Actif
  {
    id: "btc_asset", type: "AssetDef", x: X[0], y: Y_TOP, label: "BTC/USDT",
    params: { symbol: "BTC/USDT", exchange: "binance", capital_usd: 10000, fraction: 0.02, keywords: ["bitcoin"] },
    inputPorts: [], outputPorts: ["symbol", "exchange", "capital", "fraction"],
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

  // Col 6 : DirectionGate (auto — suit le TrendFilter)
  {
    id: "btc_gate", type: "DirectionGate", x: X[6], y: Y_TOP, label: "Gate AUTO (TrendFilter)",
    params: { allow_long: true, allow_short: true },
    inputPorts: ["signal", "trend"], outputPorts: ["signal", "blocked", "reason"],
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
  // LANE 2 — SHORT forcé (démo SignalConstant + DirectionGate)
  // ═══════════════════════════════════════════════════════════════

  // Col 5 : Signal fixe SHORT
  {
    id: "short_signal", type: "SignalConstant", x: X[5], y: Y_BOT, label: "SHORT Forcé",
    params: { signal: "short" }, inputPorts: [], outputPorts: ["signal", "prob_up"],
  },

  // Col 6 : Gate SHORT-only
  {
    id: "short_gate", type: "DirectionGate", x: X[6], y: Y_BOT, label: "Gate SHORT-only",
    params: { allow_long: false, allow_short: true },
    inputPorts: ["signal", "trend"], outputPorts: ["signal", "blocked", "reason"],
  },

  // Col 7 : Risk SHORT
  {
    id: "short_risk", type: "RiskATR", x: X[7], y: Y_BOT, label: "Risk ATR (3:1 SHORT)",
    params: { sl_mult: 3.0, tp_mult: 6.0, fraction: 0.003, capital: 10000 },
    inputPorts: ["signal", "ohlcv_1h", "capital"], outputPorts: ["decision"],
  },

  // Col 8 : Alerte
  {
    id: "short_alert", type: "AlertOnly", x: X[8], y: Y_BOT, label: "Alert (Telegram)",
    params: { channels: ["log", "telegram"] }, inputPorts: ["decision"], outputPorts: [],
  },
];

const EDGES_SPEC: Array<{ src: string; dst: string; srcPort?: string; dstPort?: string }> = [
  // ── Lane 1 : Pipeline complet ──────────────────────────────────
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

  // ── Lane 2 : SHORT forcé ──────────────────────────────────────
  // SignalConstant → Gate SHORT
  { src: "short_signal", dst: "short_gate", srcPort: "signal", dstPort: "signal" },

  // Gate → Risk
  { src: "short_gate", dst: "short_risk", srcPort: "signal", dstPort: "signal" },
  { src: "btc_data", dst: "short_risk", srcPort: "ohlcv_1h", dstPort: "ohlcv_1h" },
  { src: "btc_asset", dst: "short_risk", srcPort: "capital", dstPort: "capital" },

  // Risk → Alerte
  { src: "short_risk", dst: "short_alert", srcPort: "decision", dstPort: "decision" },
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
