/**
 * v4/frontend/src/components/canvas/NodePalette.tsx
 *
 * Palette de nœuds glissables vers le canvas (drag & drop).
 * Organisée par catégorie.
 */
"use client";

import { useDagStore } from "@/store/dagStore";
import type { Node as RFNode } from "@xyflow/react";

const NODE_CATALOG = [
  {
    category: "Actif",
    nodes: [
      { type: "AssetDef", label: "AssetDef", inputPorts: [], outputPorts: ["symbol", "exchange", "capital", "fraction"] },
    ],
  },
  {
    category: "Données",
    nodes: [
      { type: "LoadMultiTF", label: "Load Multi TF", inputPorts: ["symbol"], outputPorts: ["ohlcv_5m", "ohlcv_1h"] },
    ],
  },
  {
    category: "V7 — Risk Premium",
    nodes: [
      { type: "FundingCarryNode", label: "Funding Carry", inputPorts: ["spot_price", "funding_rate"], outputPorts: ["signal", "decision", "size_usd"] },
    ],
  },
  {
    category: "Exécution",
    nodes: [
      { type: "PaperTrader", label: "Paper Trader", inputPorts: ["decision", "symbol"], outputPorts: ["trade_result"] },
      { type: "RecordDecision", label: "Record DB", inputPorts: ["decision"], outputPorts: [] },
    ],
  },
  {
    category: "IA",
    nodes: [
      { type: "LLMNode", label: "LLM AI Analyst", inputPorts: ["decision"], outputPorts: ["response", "parsed"] },
    ],
  },
];
      { type: "DirectionGate", label: "Direction Gate", inputPorts: ["signal", "trend"], outputPorts: ["signal", "blocked", "reason"] },
      { type: "MetaGate", label: "MetaGate V5", inputPorts: ["signal", "prob_up", "trend", "debate_signal", "debate_conf", "crosstf_signal", "crosstf_conf", "regime"], outputPorts: ["signal", "blocked", "reason", "score"] },
      { type: "CircuitBreaker", label: "CircuitBreaker V5", inputPorts: ["decision"], outputPorts: ["decision", "blocked", "reason"] },
      { type: "PortfolioRisk", label: "PortfolioRisk V5", inputPorts: ["decision", "symbol"], outputPorts: ["decision", "blocked", "reason"] },
    ],
  },
];

let _nodeCounter = 1;

export function NodePalette({ compact = false }: { compact?: boolean }) {
  const setNodes = useDagStore((s) => s.setNodes);
  const nodes = useDagStore((s) => s.nodes);

  const addNode = (spec: (typeof NODE_CATALOG)[0]["nodes"][0]) => {
    const id = `${spec.type}_${_nodeCounter++}`;
    const newNode: RFNode = {
      id,
      type: spec.type,
      position: { x: 200 + Math.random() * 100, y: 200 + Math.random() * 100 },
      data: {
        label: spec.label,
        nodeType: spec.type,
        inputPorts: spec.inputPorts,
        outputPorts: spec.outputPorts,
        params: {},
      },
    };
    setNodes([...nodes, newNode]);
  };

  if (compact) {
    return (
      <div className="flex flex-col py-1">
        {NODE_CATALOG.map(({ category, nodes: catNodes }) => (
          <div key={category}>
            <div className="px-2.5 py-1 text-[9px] text-slate-600 uppercase tracking-wider">
              {category}
            </div>
            {catNodes.map((spec) => (
              <button
                key={spec.type}
                onClick={() => addNode(spec)}
                className="w-full px-2.5 py-1 text-left text-[11px] text-slate-400 
                           hover:bg-slate-800 hover:text-white transition-colors"
              >
                {spec.label}
              </button>
            ))}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="w-44 rounded-lg border border-canvas-border bg-canvas-node shadow-lg overflow-y-auto max-h-[80vh]">
      <div className="border-b border-canvas-border px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider">
        Nœuds
      </div>
      {NODE_CATALOG.map(({ category, nodes: catNodes }) => (
        <div key={category}>
          <div className="px-3 py-1 text-[10px] text-slate-500 uppercase tracking-wider">
            {category}
          </div>
          {catNodes.map((spec) => (
            <button
              key={spec.type}
              onClick={() => addNode(spec)}
              className="w-full px-3 py-1.5 text-left text-xs text-slate-300 
                         hover:bg-canvas-grid hover:text-white transition-colors"
            >
              {spec.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}
