/**
 * v4/frontend/src/components/canvas/DAGCanvas.tsx
 *
 * Canvas principal React Flow avec :
 *   - Fond grille sombre
 *   - Contrôles zoom / minimap
 *   - Barre d'outils (Run / Schedule / Stop / Reset)
 *   - Statut global (running, dernière exécution)
 */
"use client";

import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useDagStore } from "@/store/dagStore";
import { useDagRunner } from "@/hooks/useDagRunner";
import { nodeTypes } from "@/components/nodes/nodeTypes";
import { NodePalette } from "./NodePalette";
import { useState, useEffect } from "react";
import { getDefaultNodes, getDefaultEdges } from "@/lib/defaultDag";

export function DAGCanvas() {
  const {
    nodes, edges,
    onNodesChange, onEdgesChange, onConnect,
    isRunning,
    results,
    reset,
    setNodes,
    setEdges,
    setDagId,
  } = useDagStore();

  const { runOnce, schedule, stopDag } = useDagRunner();
  const [cycleS, setCycleS] = useState(300);
  const [error, setError] = useState<string | null>(null);

  // Auto-load du DAG démo par défaut si le canvas est vide
  useEffect(() => {
    if (nodes.length === 0) {
      setNodes(getDefaultNodes());
      setEdges(getDefaultEdges());
      setDagId("demo_v4");
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const doneCount = Object.values(results).filter((r) => r.status === "done").length;
  const errorCount = Object.values(results).filter((r) => r.status === "error").length;

  const handleReset = () => {
    setNodes(getDefaultNodes());
    setEdges(getDefaultEdges());
    setDagId("demo_v4");
    reset();
  };

  const handleRun = async () => {
    setError(null);
    try {
      await runOnce();
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="h-full w-full relative">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        fitView
        deleteKeyCode="Delete"
        className="bg-canvas-bg"
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#1e2130" />
        <Controls className="fill-slate-400 stroke-canvas-border" />
        <MiniMap
          nodeColor="#1a1d2e"
          maskColor="rgba(15,17,23,0.8)"
          className="border border-canvas-border rounded"
        />

        {/* Palette latérale */}
        <Panel position="top-left">
          <NodePalette />
        </Panel>

        {/* Barre d'outils */}
        <Panel position="top-right">
          <div className="flex items-center gap-2 rounded-lg border border-canvas-border bg-canvas-node px-3 py-2 shadow-lg">
            {/* Statut */}
            <div className="text-xs text-slate-400 mr-2">
              {isRunning ? (
                <span className="text-canvas-warning animate-pulse">● Running…</span>
              ) : Object.keys(results).length > 0 ? (
                <span>
                  <span className="text-canvas-success">{doneCount} ✓</span>
                  {errorCount > 0 && (
                    <span className="text-canvas-danger ml-2">{errorCount} ✗</span>
                  )}
                </span>
              ) : (
                <span className="text-slate-500">Prêt</span>
              )}
            </div>

            <button
              onClick={handleRun}
              disabled={isRunning}
              className="rounded bg-canvas-accent px-3 py-1 text-xs font-semibold text-white 
                         hover:bg-indigo-500 disabled:opacity-50 transition-colors"
            >
              ▶ Run
            </button>

            <div className="flex items-center gap-1">
              <input
                type="number"
                value={cycleS}
                onChange={(e) => setCycleS(Number(e.target.value))}
                className="w-14 rounded border border-canvas-border bg-canvas-bg px-1 py-1 text-xs text-slate-300"
                min={5}
              />
              <button
                onClick={() => schedule(cycleS)}
                className="rounded border border-canvas-border px-3 py-1 text-xs text-slate-300
                           hover:border-canvas-accent hover:text-white transition-colors"
              >
                ⏱ Schedule
              </button>
            </div>

            <button
              onClick={stopDag}
              className="rounded border border-canvas-border px-3 py-1 text-xs text-slate-300
                         hover:border-canvas-danger hover:text-canvas-danger transition-colors"
            >
              ■ Stop
            </button>

            <button
              onClick={handleReset}
              className="rounded border border-canvas-border px-2 py-1 text-xs text-slate-500
                         hover:text-canvas-danger transition-colors"
              title="Réinitialiser le canvas"
            >
              ✕
            </button>
          </div>
          {error && (
            <div className="mt-2 rounded border border-canvas-danger bg-red-950 px-3 py-1 text-xs text-canvas-danger">
              {error}
            </div>
          )}
        </Panel>
      </ReactFlow>
    </div>
  );
}
