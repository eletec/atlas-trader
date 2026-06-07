/**
 * v4/frontend/src/components/canvas/DAGCanvas.tsx
 *
 * Canvas React Flow avec :
 *   - Bandeau top fixe (titre + statut + Run/Schedule/Stop/Reset + toggle palette)
 *   - Palette rétractable (bouton ☰ Nœuds dans le bandeau)
 *   - Canvas plein écran, marges minimales, Controls + MiniMap en bas
 *   - Menu contextuel (clic droit → ajouter nœud)
 *   - NodeEditor en panneau droit
 */
"use client";

import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useDagStore } from "@/store/dagStore";
import { useDagRunner } from "@/hooks/useDagRunner";
import { nodeTypes } from "@/components/nodes/nodeTypes";
import { NodePalette } from "./NodePalette";
import { NodeEditor } from "./NodeEditor";
import { useState, useEffect, useCallback } from "react";
import { getDefaultNodes, getDefaultEdges } from "@/lib/defaultDag";

// ── Menu contextuel ─────────────────────────────────────────────────────────
const CTX_NODES = [
  { type: "AssetDef",          label: "💰 Asset",          cat: "Actif" },
  { type: "LoadMultiTF",       label: "📊 Load Data",      cat: "Données" },
  { type: "ComputeFeatures",   label: "🔢 Features",       cat: "Features" },
  { type: "Normalize",         label: "📐 Normalize",      cat: "Features" },
  { type: "RegimeHMM",         label: "📈 Regime HMM",     cat: "Régime" },
  { type: "TrendFilter",       label: "📉 Trend 4h",       cat: "Filtres" },
  { type: "SignalLogReg",      label: "🎯 Signal ML",      cat: "Signal" },
  { type: "SignalConstant",    label: "📌 Signal Fixe",    cat: "Signal" },
  { type: "DirectionGate",     label: "🚦 Gate",           cat: "Filtres" },
  { type: "RiskATR",           label: "🛡️ Risk ATR",       cat: "Risque" },
  { type: "LLMNode",           label: "🤖 LLM AI",         cat: "IA" },
  { type: "PaperTrader",       label: "📋 Paper Trade",    cat: "Sortie" },
  { type: "AlertOnly",         label: "🔔 Alert Only",     cat: "Sortie" },
  { type: "RecordDecision",    label: "💾 Record DB",      cat: "Sortie" },
];

export function DAGCanvas() {
  const {
    nodes, edges, onNodesChange, onEdgesChange, onConnect,
    isRunning, results, reset, setNodes, setEdges, setDagId,
  } = useDagStore();

  const { runOnce, schedule, stopDag } = useDagRunner();
  const [cycleS, setCycleS] = useState(300);
  const [error, setError] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number } | null>(null);

  // Hydratation zustand
  useEffect(() => {
    const unsub = useDagStore.persist.onFinishHydration(() => setHydrated(true));
    if (useDagStore.persist.hasHydrated()) setHydrated(true);
    return () => unsub();
  }, []);

  // DAG par défaut
  useEffect(() => {
    if (hydrated && nodes.length === 0) {
      setNodes(getDefaultNodes());
      setEdges(getDefaultEdges());
      setDagId("demo_v4");
    }
  }, [hydrated]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fermer ctx menu au clic
  useEffect(() => {
    const close = () => setCtxMenu(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, []);

  const doneCount   = Object.values(results).filter((r) => r.status === "done").length;
  const errorCount  = Object.values(results).filter((r) => r.status === "error").length;

  const handleReset = () => {
    setNodes(getDefaultNodes());
    setEdges(getDefaultEdges());
    setDagId("demo_v4");
    reset();
  };
  const handleRun = async () => {
    setError(null);
    try { await runOnce(); } catch (e: any) { setError(e.message); }
  };
  const handleCtx = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setCtxMenu({ x: e.clientX, y: e.clientY });
  }, []);
  const addNode = useCallback((spec: typeof CTX_NODES[0]) => {
    if (!ctxMenu) return;
    const id = `${spec.type}_${Date.now()}`;
    setNodes([...nodes, { id, type: spec.type,
      position: { x: ctxMenu.x - 150, y: ctxMenu.y - 80 },
      data: { label: spec.label, nodeType: spec.type, inputPorts: [], outputPorts: [], params: {} },
    }]);
    setCtxMenu(null);
  }, [ctxMenu, nodes, setNodes]);

  return (
    <div className="h-full w-full relative bg-canvas-bg">
      {/* Palette (rétractable) */}
      {showPalette && (
        <div className="absolute left-0 top-0 bottom-0 w-44 border-r border-canvas-border bg-canvas-node/95 backdrop-blur overflow-y-auto z-20">
          <div className="flex items-center justify-between px-2.5 py-1.5 border-b border-canvas-border">
            <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-wider">Palette</span>
            <button onClick={() => setShowPalette(false)} className="text-slate-500 hover:text-white text-xs">✕</button>
          </div>
          <NodePalette compact />
        </div>
      )}

      {/* Canvas */}
      <div className="h-full w-full" onContextMenu={handleCtx}>
        <ReactFlow
          nodes={nodes} edges={edges}
          onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
          nodeTypes={nodeTypes} fitView deleteKeyCode="Delete"
          className="bg-canvas-bg" proOptions={{ hideAttribution: true }}
          defaultViewport={{ x: 20, y: 20, zoom: 0.75 }}
          minZoom={0.15} maxZoom={2.5}
        >
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#161b2a" />
          <Controls className="fill-slate-500 stroke-canvas-border" position="bottom-right"
            style={{ bottom: 8, right: 8 }} />
          <MiniMap nodeColor="#1a1d2e" maskColor="rgba(15,17,23,0.85)"
            className="border border-canvas-border rounded" position="bottom-left"
            style={{ bottom: 8, left: 8, width: 120, height: 80 }} />
        </ReactFlow>
      </div>

      {/* ═══════════ OVERLAY CONTROLS (top-left) ═══════════ */}
      <div className="absolute top-2 left-2 z-10 flex items-center gap-1.5 rounded-lg border border-canvas-border/60 bg-canvas-node/80 backdrop-blur px-2 py-1 shadow-lg">
        <button
          onClick={() => setShowPalette(!showPalette)}
          className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
            showPalette ? "bg-canvas-accent text-white" : "text-slate-400 hover:text-white"
          }`}
          title="Palette de nœuds"
        >
          ☰
        </button>

        <span className="w-px h-3 bg-canvas-border/60" />

        <button onClick={handleRun} disabled={isRunning}
          className="rounded bg-canvas-accent px-2 py-0.5 text-[10px] font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
          title="Exécuter une fois">
          ▶
        </button>

        <input type="number" value={cycleS} onChange={(e) => setCycleS(Number(e.target.value))}
          className="w-10 rounded border border-canvas-border/60 bg-canvas-bg/60 px-1 py-0.5 text-[10px] text-slate-300 text-center"
          min={5} title="Intervalle (secondes)" />

        <button onClick={() => schedule(cycleS)}
          className="rounded border border-canvas-border/60 px-1.5 py-0.5 text-[10px] text-slate-400 hover:border-canvas-accent hover:text-white"
          title="Ordonnancer">
          ⏱
        </button>

        <button onClick={stopDag}
          className="rounded border border-canvas-border/60 px-1.5 py-0.5 text-[10px] text-slate-400 hover:border-canvas-danger hover:text-canvas-danger"
          title="Arrêter">
          ■
        </button>

        <button onClick={handleReset}
          className="rounded px-1 py-0.5 text-[10px] text-slate-500 hover:text-canvas-danger"
          title="Reset canvas">
          ✕
        </button>

        {/* Statut miniature */}
        <span className="w-px h-3 bg-canvas-border/60" />
        <span className="text-[9px] text-slate-500 min-w-[40px]">
          {isRunning ? (
            <span className="text-canvas-warning animate-pulse">● run</span>
          ) : Object.keys(results).length > 0 ? (
            <span>
              <span className="text-canvas-success">{doneCount}ok</span>
              {errorCount > 0 && <span className="text-canvas-danger ml-0.5">{errorCount}err</span>}
            </span>
          ) : (
            <span>{nodes.length}n</span>
          )}
        </span>
      </div>

      {/* Erreur toast */}
      {error && (
        <div className="absolute top-12 left-2 z-10 rounded border border-canvas-danger bg-red-950/90 px-2 py-1 text-[10px] text-canvas-danger shadow-lg">
          {error}
          <button onClick={() => setError(null)} className="ml-2 text-slate-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Éditeur params (droite) */}
      <div className="absolute right-0 top-0 bottom-0 z-20">
        <NodeEditor />
      </div>

      {/* ═══════════ MENU CONTEXTUEL ═══════════ */}
      {ctxMenu && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setCtxMenu(null)} />
          <div className="fixed z-50 w-44 rounded-lg border border-canvas-border bg-canvas-node shadow-2xl py-1 overflow-y-auto"
            style={{ left: ctxMenu.x, top: ctxMenu.y, maxHeight: "55vh" }}>
            <div className="px-3 py-1 text-[9px] font-semibold text-slate-500 uppercase">Ajouter</div>
            {CTX_NODES.map((n) => (
              <button key={n.type}
                className="w-full text-left px-3 py-1 text-[11px] text-slate-300 hover:bg-slate-800 hover:text-white flex items-center gap-2"
                onClick={() => addNode(n)}>
                <span className="text-[9px] text-slate-600 w-14 shrink-0">{n.cat}</span>
                <span>{n.label}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
