/**
 * v4/frontend/src/components/canvas/NodeEditor.tsx
 *
 * Panneau latéral d'édition des paramètres d'un nœud sélectionné.
 * Affiche tous les params sous forme de champs editables.
 * Supporte ajout/suppression de params + reset aux valeurs par défaut.
 */
"use client";

import { useDagStore } from "@/store/dagStore";
import { useCallback, useState } from "react";

const TYPE_DEFAULTS: Record<string, Record<string, unknown>> = {
  AssetDef: { symbol: "BTC/USDT", exchange: "binance", capital_usd: 10000, fraction: 0.02 },
  LoadMultiTF: { symbol: "BTC/USDT", days_5m: 90, days_1h: 100, exchange: "binance" },
  ComputeFeatures: {},
  Normalize: { window: 500 },
  RegimeHMM: { n_states: 3 },
  RegimePassthrough: { regime: "TREND" },
  TrendFilter: { timeframe_resample: "4h", sma_fast: 20, sma_slow: 50, min_bars: 50 },
  SignalLogReg: { calibrate: true, train_fraction: 0.70, horizon_bars: 48, p_up_threshold: 0.55, p_dn_threshold: 0.45 },
  SignalConstant: { signal: "flat", prob_up: 0.5 },
  DirectionGate: { allow_long: true, allow_short: true, invert_trend: false },
  RiskATR: { sl_mult: 2.0, tp_mult: 4.0, fraction: 0.005, capital: 10000 },
  PaperTrader: { symbol: "BTC/USDT", dag_id: "demo_v4" },
  AlertOnly: { channels: ["log"] },
  RecordDecision: { db_path: "/app/data/v4_decisions.db" },
  LLMNode: { model: "phi4:latest", system_prompt: "You are a trading analyst.", user_prompt: "Market data: {inputs}", temperature: 0.3, max_tokens: 256, timeout_s: 120 },
};

function inferType(value: unknown): "string" | "number" | "boolean" | "array" {
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return "number";
  if (Array.isArray(value)) return "array";
  return "string";
}

export function NodeEditor() {
  const nodes = useDagStore((s) => s.nodes);
  const selectedNodeId = useDagStore((s) => s.selectedNodeId);
  const selectNode = useDagStore((s) => s.selectNode);
  const updateNodeParams = useDagStore((s) => s.updateNodeParams);

  const node = nodes.find((n) => n.id === selectedNodeId);
  const nodeData = node?.data as Record<string, unknown> | undefined;
  const params = (nodeData?.params ?? {}) as Record<string, unknown>;
  const nodeType = (nodeData?.nodeType ?? "") as string;

  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");

  const handleChange = useCallback(
    (key: string, value: unknown) => {
      if (!selectedNodeId) return;
      const next = { ...params, [key]: value };
      updateNodeParams(selectedNodeId, next);
    },
    [selectedNodeId, params, updateNodeParams]
  );

  const handleDelete = useCallback(
    (key: string) => {
      if (!selectedNodeId) return;
      const next = { ...params };
      delete next[key];
      updateNodeParams(selectedNodeId, next);
    },
    [selectedNodeId, params, updateNodeParams]
  );

  const handleAdd = () => {
    if (!selectedNodeId || !newKey.trim()) return;
    let val: unknown = newVal;
    if (newVal === "true") val = true;
    else if (newVal === "false") val = false;
    else if (/^-?\d+(\.\d+)?$/.test(newVal)) val = parseFloat(newVal);
    handleChange(newKey.trim(), val);
    setNewKey("");
    setNewVal("");
  };

  const handleReset = () => {
    if (!selectedNodeId) return;
    const defaults = TYPE_DEFAULTS[nodeType] ?? {};
    updateNodeParams(selectedNodeId, { ...defaults });
  };

  if (!node) {
    return (
      <div className="w-64 border-l border-canvas-border bg-canvas-node p-4 text-xs text-slate-500">
        <p className="text-center pt-8">Cliquez sur un nœud pour éditer ses paramètres</p>
      </div>
    );
  }

  const entries = Object.entries(params);

  return (
    <div className="w-72 border-l border-canvas-border bg-canvas-node flex flex-col" style={{ height: "100vh" }}>
      {/* Header */}
      <div className="shrink-0 border-b border-canvas-border bg-canvas-node px-3 py-2 flex items-center justify-between">
        <div>
          <span className="text-xs font-semibold text-white block">{(nodeData?.label as string) ?? selectedNodeId ?? "Node"}</span>
          <span className="text-[10px] text-slate-500">{nodeType}</span>
        </div>
        <button
          onClick={() => selectNode(null)}
          className="text-slate-500 hover:text-white text-sm px-1"
          title="Fermer"
        >
          ✕
        </button>
      </div>

      {/* Params — scrollable */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Paramètres</span>
          <button
            onClick={handleReset}
            className="text-[10px] text-slate-500 hover:text-canvas-accent"
            title="Réinitialiser aux valeurs par défaut"
          >
            ↺ Reset
          </button>
        </div>

        {entries.length === 0 && (
          <p className="text-[11px] text-slate-600 italic">Aucun paramètre</p>
        )}

        {entries.map(([key, value]) => {
          const type = inferType(value);
          return (
            <div key={key} className="flex items-start gap-1 group">
              <label className="text-[10px] text-slate-400 w-20 shrink-0 pt-1 truncate" title={key}>
                {key}
              </label>
              <div className="flex-1 min-w-0">
                {type === "boolean" ? (
                  <select
                    className="w-full bg-canvas-bg border border-canvas-border rounded px-1 py-0.5 text-[11px] text-white"
                    value={String(value)}
                    onChange={(e) => handleChange(key, e.target.value === "true")}
                  >
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : type === "number" ? (
                  <input
                    type="number"
                    step="any"
                    className="w-full bg-canvas-bg border border-canvas-border rounded px-1 py-0.5 text-[11px] text-white"
                    value={value as number}
                    onChange={(e) => handleChange(key, parseFloat(e.target.value) || 0)}
                  />
                ) : type === "array" ? (
                  <input
                    className="w-full bg-canvas-bg border border-canvas-border rounded px-1 py-0.5 text-[11px] text-white"
                    value={JSON.stringify(value)}
                    onChange={(e) => {
                      try {
                        handleChange(key, JSON.parse(e.target.value));
                      } catch {
                        handleChange(key, e.target.value);
                      }
                    }}
                  />
                ) : (
                  <input
                    className="w-full bg-canvas-bg border border-canvas-border rounded px-1 py-0.5 text-[11px] text-white"
                    value={String(value)}
                    onChange={(e) => handleChange(key, e.target.value)}
                  />
                )}
              </div>
              <button
                onClick={() => handleDelete(key)}
                className="text-[10px] text-slate-600 hover:text-canvas-danger opacity-0 group-hover:opacity-100 transition-opacity"
                title="Supprimer"
              >
                ✕
              </button>
            </div>
          );
        })}

      </div>

      {/* Ajouter un paramètre — sticky en bas */}
      <div className="shrink-0 border-t border-canvas-border bg-canvas-node p-3">
        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">+ Ajouter</span>
        <div className="flex gap-1">
          <input
            className="flex-1 min-w-0 bg-canvas-bg border border-canvas-border rounded px-1 py-1 text-[11px] text-white"
            placeholder="nom"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
          />
          <input
            className="flex-1 min-w-0 bg-canvas-bg border border-canvas-border rounded px-1 py-1 text-[11px] text-white"
            placeholder="valeur"
            value={newVal}
            onChange={(e) => setNewVal(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          />
          <button
            onClick={handleAdd}
            className="shrink-0 bg-canvas-accent text-white text-xs font-bold px-2.5 rounded hover:opacity-80 transition-opacity"
            title="Ajouter le paramètre"
          >
            +
          </button>
        </div>
      </div>
    </div>
  );
}
