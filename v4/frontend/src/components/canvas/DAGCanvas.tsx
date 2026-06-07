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
import { useDagRegistry, saveDAG, loadDAG } from "@/store/dagRegistry";
import { useDagRunner } from "@/hooks/useDagRunner";
import type { Node as RFNode, Edge as RFEdge } from "@xyflow/react";
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
    isRunning, results, reset, setNodes, setEdges, setDagId, setRunning,
  } = useDagStore();

  const { runOnce, schedule, stopDag } = useDagRunner();
  const [cycleS, setCycleS] = useState(300);
  const [error, setError] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [showDagMenu, setShowDagMenu] = useState(false);
  const [newDagName, setNewDagName] = useState("");
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameName, setRenameName] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [runStart, setRunStart] = useState<number | null>(null);  // timestamp de début du run
  const [elapsed, setElapsed] = useState(0);

  const { dags, activeId, setActive, create, rename, remove, ensureDefault } = useDagRegistry();

  // Hydratation zustand
  useEffect(() => {
    const unsub = useDagStore.persist.onFinishHydration(() => setHydrated(true));
    if (useDagStore.persist.hasHydrated()) setHydrated(true);
    return () => unsub();
  }, []);

  // DAG par défaut
  useEffect(() => {
    if (hydrated) {
      ensureDefault();
      if (nodes.length === 0) {
        setNodes(getDefaultNodes());
        setEdges(getDefaultEdges());
        setDagId("default");
      }
    }
  }, [hydrated]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sauvegarder le DAG actif dans le registre à chaque modification
  useEffect(() => {
    if (hydrated && activeId) {
      saveDAG(activeId, { nodes, edges, asset: "BTC/USDT" });
    }
  }, [nodes, edges, activeId, hydrated]);

  // Fermer ctx menu au clic
  useEffect(() => {
    const close = () => setCtxMenu(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, []);

  const doneCount   = Object.values(results).filter((r) => r.status === "done").length;
  const errorCount  = Object.values(results).filter((r) => r.status === "error").length;

  const handleReset = () => {
    setConfirmReset(true);
  };
  const doReset = () => {
    setNodes(getDefaultNodes());
    setEdges(getDefaultEdges());
    setDagId("default");
    reset();
    setConfirmReset(false);
  };

  const handleSwitchDag = (id: string) => {
    setActive(id);
    const data = loadDAG(id);
    if (data) {
      setNodes(data.nodes as RFNode[]);
      setEdges(data.edges as RFEdge[]);
      setDagId(id);
      reset();
    }
    setShowDagMenu(false);
  };

  const handleCreateDag = () => {
    const name = newDagName.trim() || `Flow ${dags.length + 1}`;
    const entry = create(name);
    // Sauvegarder un DAG vide pour le nouveau flow
    saveDAG(entry.id, { nodes: [], edges: [], asset: "BTC/USDT" });
    handleSwitchDag(entry.id);
    setNewDagName("");
    setShowDagMenu(false);
  };

  const handleDeleteDag = (id: string) => {
    if (dags.length <= 1) return; // Garder au moins 1 DAG
    if (id === activeId) {
      const next = dags.find((d) => d.id !== id);
      if (next) handleSwitchDag(next.id);
    }
    remove(id);
  };
  const handleRun = async () => {
    setError(null);
    setRunStart(Date.now());
    setElapsed(0);
    try { await runOnce(); setFeedback(`✓ Terminé en ${elapsed}s`); }
    catch (e: any) { setError(e.message); }
    setTimeout(() => setFeedback(null), 3000);
    setRunStart(null);
  };

  // Tick du chrono pendant le run
  useEffect(() => {
    if (!runStart) return;
    const iv = setInterval(() => setElapsed(Math.round((Date.now() - runStart) / 1000)), 1000);
    return () => clearInterval(iv);
  }, [runStart]);

  const handleSchedule = async () => {
    setError(null);
    setFeedback(`⏱ Envoi schedule ${cycleS}s…`);
    try {
      await schedule(cycleS);
      setRunning(true);
      setFeedback(`⏱ Schedulé toutes les ${cycleS}s`);
    } catch (e: any) { setError(e.message); setFeedback(null); }
    setTimeout(() => setFeedback(null), 3000);
  };

  const handleStop = async () => {
    setError(null);
    setFeedback("■ Arrêt en cours…");
    try {
      await stopDag();
      setRunning(false);
      setFeedback("■ Arrêté");
    } catch (e: any) { setError(e.message); setFeedback(null); }
    setTimeout(() => setFeedback(null), 2000);
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
          <MiniMap nodeColor="#1a1d2e" maskColor="rgba(15,17,23,0.85)"
            className="border border-canvas-border rounded" position="bottom-right"
            style={{ bottom: 8, right: 52, width: 120, height: 80 }} />
          <Controls className="fill-slate-500 stroke-canvas-border" position="bottom-right"
            style={{ bottom: 8, right: 8 }} />
        </ReactFlow>
      </div>

      {/* ═══════════ OVERLAY CONTROLS (centré en haut) ═══════════ */}
      <div className="absolute top-2 left-1/2 -translate-x-1/2 z-10 flex items-center gap-1.5 rounded-lg border border-canvas-border/60 bg-canvas-node/80 backdrop-blur px-2 py-1 shadow-lg">
        {/* ── DAG Selector ─────────────────────────────────── */}
        <div className="relative">
          <button
            onClick={() => setShowDagMenu(!showDagMenu)}
            className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium text-slate-300 hover:text-white transition-colors"
            title="Flows"
          >
            <span className="text-canvas-accent">📁</span>
            <span className="max-w-[80px] truncate">{dags.find((d) => d.id === activeId)?.name ?? "Flow"}</span>
            <span className="text-slate-600 text-[8px]">▼</span>
          </button>

          {showDagMenu && (
            <>
              <div className="fixed inset-0 z-50" onClick={() => setShowDagMenu(false)} />
              <div className="absolute top-full left-0 mt-1 w-52 rounded-lg border border-canvas-border bg-canvas-node shadow-2xl py-1 z-50">
                <div className="px-2 py-1 text-[9px] font-semibold text-slate-500 uppercase">Flows</div>

                {dags.map((d) => (
                  <div key={d.id} className={`flex items-center group ${d.id === activeId ? "bg-canvas-accent/10" : ""}`}>
                    {renameId === d.id ? (
                      <input
                        autoFocus
                        value={renameName}
                        onChange={(e) => setRenameName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") { rename(d.id, renameName); setRenameId(null); }
                          if (e.key === "Escape") setRenameId(null);
                        }}
                        onBlur={() => { if (renameId) { rename(d.id, renameName); setRenameId(null); } }}
                        className="flex-1 bg-canvas-bg border border-canvas-accent rounded px-1 py-0.5 text-[10px] text-white mx-1"
                      />
                    ) : (
                      <button
                        onClick={() => handleSwitchDag(d.id)}
                        className="flex-1 text-left px-2 py-1 text-[11px] text-slate-300 hover:text-white truncate"
                      >
                        {d.name}
                      </button>
                    )}
                    {d.id === activeId && <span className="text-[8px] text-canvas-accent mr-1">●</span>}
                    <button
                      onClick={() => { setRenameId(d.id); setRenameName(d.name); }}
                      className="text-[10px] text-slate-600 hover:text-white px-1 opacity-0 group-hover:opacity-100"
                      title="Renommer"
                    >
                      ✎
                    </button>
                    <button
                      onClick={() => handleDeleteDag(d.id)}
                      className="text-[10px] text-slate-600 hover:text-canvas-danger px-1 opacity-0 group-hover:opacity-100"
                      title="Supprimer"
                    >
                      ✕
                    </button>
                  </div>
                ))}

                <div className="border-t border-canvas-border mt-1 pt-1 px-2 flex gap-1">
                  <input
                    value={newDagName}
                    onChange={(e) => setNewDagName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleCreateDag()}
                    placeholder="Nouveau flow..."
                    className="flex-1 bg-canvas-bg border border-canvas-border rounded px-1 py-0.5 text-[10px] text-white"
                  />
                  <button onClick={handleCreateDag}
                    className="rounded bg-canvas-accent px-2 py-0.5 text-[10px] font-semibold text-white hover:bg-indigo-500">
                    +
                  </button>
                </div>
              </div>
            </>
          )}
        </div>

        <span className="w-px h-3 bg-canvas-border/60" />

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

        <button onClick={handleSchedule}
          className="rounded border border-canvas-border/60 px-1.5 py-0.5 text-[10px] text-slate-400 hover:border-canvas-accent hover:text-white"
          title="Ordonnancer">
          ⏱
        </button>

        <button onClick={handleStop}
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
          {runStart ? (
            <span className="text-canvas-warning animate-pulse">● {elapsed}s</span>
          ) : isRunning ? (
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

      {/* Feedback toast (succès) */}
      {feedback && (
        <div className="absolute top-2 right-2 z-10 rounded border border-canvas-accent/40 bg-canvas-node/95 px-3 py-1.5 text-[11px] text-white shadow-lg animate-pulse">
          {feedback}
        </div>
      )}

      {/* ═══════════ CONFIRMATION RESET ═══════════ */}
      {confirmReset && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="rounded-xl border border-canvas-border bg-canvas-node p-6 shadow-2xl text-center max-w-xs">
            <div className="text-3xl mb-3">⚠️</div>
            <p className="text-sm text-white font-semibold mb-1">Réinitialiser le canvas ?</p>
            <p className="text-[11px] text-slate-400 mb-4">
              Tous les nœuds et connexions seront remplacés par le DAG démo par défaut.
              Cette action est irréversible.
            </p>
            <div className="flex gap-2 justify-center">
              <button onClick={() => setConfirmReset(false)}
                className="rounded border border-canvas-border px-4 py-1.5 text-xs text-slate-300 hover:text-white transition-colors">
                Annuler
              </button>
              <button onClick={doReset}
                className="rounded bg-canvas-danger px-4 py-1.5 text-xs font-semibold text-white hover:bg-red-600 transition-colors">
                Tout réinitialiser
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Éditeur params (droite) — fixed pour ne pas être clippé */}
      <div className="fixed right-0 top-0 bottom-0 z-20" style={{ maxWidth: "min(288px, 100vw)" }}>
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
