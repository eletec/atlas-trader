/**
 * v4/frontend/src/lib/defaultDag.ts
 *
 * V7 DAG — Funding Carry (Risk Premium Harvesting).
 * 5 nœuds par actif : AssetDef → LoadData → FundingCarry → PaperTrader → Record.
 */

import type { Node as RFNode, Edge as RFEdge } from "@xyflow/react";

const COL_W = 280;
const X = [0, 1, 2, 3, 4].map((i) => 50 + i * COL_W);
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
  // V7 Pipeline — Funding Carry (Risk Premium Harvesting)
  // ═══════════════════════════════════════════════════════════════

  // Col 0 : Actif
  {
    id: "btc_asset", type: "AssetDef", x: X[0], y: Y_TOP, label: "BTC/USDT",
    params: { symbol: "BTC/USDT", exchange: "binance", capital_usd: 2000, fraction: 0.80, max_positions: 3 },
    inputPorts: [], outputPorts: ["symbol", "exchange", "capital", "fraction", "max_positions"],
  },

  // Col 1 : Données
  {
    id: "btc_data", type: "LoadMultiTF", x: X[1], y: Y_TOP, label: "Load 5m + 1h",
    params: { symbol: "BTC/USDT", days_5m: 30, days_1h: 90, exchange: "binance" },
    inputPorts: ["symbol"], outputPorts: ["ohlcv_5m", "ohlcv_1h"],
  },

  // Col 2 : Funding Carry (stratégie principale V7)
  {
    id: "btc_carry", type: "FundingCarryNode", x: X[2], y: Y_TOP, label: "Funding Carry V7",
    params: { symbol: "BTC/USDT", capital: 2000, fraction: 0.80, min_funding: 0.00001, exit_after_hours: 168 },
    inputPorts: ["spot_price", "funding_rate", "perp_price"], outputPorts: ["signal", "decision", "size_usd", "expected_return", "confidence", "funding_rate", "annual_funding_pct", "position_open"],
  },

  // Col 3 : PaperTrader
  {
    id: "btc_paper", type: "PaperTrader", x: X[3], y: Y_TOP, label: "Paper Trader",
    params: {}, inputPorts: ["decision", "symbol", "max_positions"], outputPorts: ["trade_result"],
  },

  // Col 4 : Record DB + AI Analyst
  {
    id: "btc_record", type: "RecordDecision", x: X[4], y: Y_TOP - 60, label: "Record DB",
    params: { db_path: "/app/data/v4.db" }, inputPorts: ["decision"], outputPorts: [],
  },
  {
    id: "ai_analyst", type: "LLMNode", x: X[4], y: Y_TOP + 60, label: "AI Analyst",
    params: { model: "deepseek", temperature: 0.3, max_tokens: 256 },
    inputPorts: ["decision", "funding_rate", "annual_funding_pct"], outputPorts: ["response", "parsed"],
  },
];

const EDGES_SPEC: Array<{ src: string; dst: string; srcPort?: string; dstPort?: string }> = [
  { src: "btc_asset", dst: "btc_data", srcPort: "symbol", dstPort: "symbol" },
  { src: "btc_data", dst: "btc_carry", srcPort: "ohlcv_5m", dstPort: "spot_price" },
  { src: "btc_asset", dst: "btc_paper", srcPort: "symbol", dstPort: "symbol" },
  { src: "btc_asset", dst: "btc_paper", srcPort: "max_positions", dstPort: "max_positions" },
  { src: "btc_carry", dst: "btc_paper", srcPort: "decision", dstPort: "decision" },
  { src: "btc_carry", dst: "btc_record", srcPort: "decision", dstPort: "decision" },
  { src: "btc_carry", dst: "ai_analyst", srcPort: "annual_funding_pct", dstPort: "funding_rate" },
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
