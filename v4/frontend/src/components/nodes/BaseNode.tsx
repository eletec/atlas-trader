/**
 * v4/frontend/src/components/nodes/BaseNode.tsx
 *
 * Nœud de base partagé par tous les types de nœuds du canvas.
 * Affiche : titre, type, statut, ports d'entrée/sortie, résultat.
 */
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";
import { useDagStore } from "@/store/dagStore";

const STATUS_COLOR: Record<string, string> = {
  done: "bg-canvas-success",
  error: "bg-canvas-danger",
  running: "bg-canvas-warning animate-pulse",
  bypassed: "bg-slate-500",
  idle: "bg-slate-600",
  stale: "bg-amber-700",
};

// Couleurs par catégorie de nœud (bordure + header)
const TYPE_COLORS: Record<string, { border: string; header: string; dot: string }> = {
  AssetDef:          { border: "border-amber-500/50",  header: "bg-amber-500/10",  dot: "bg-amber-400" },
  LoadMultiTF:       { border: "border-cyan-500/50",   header: "bg-cyan-500/10",   dot: "bg-cyan-400" },
  ComputeFeatures:   { border: "border-indigo-500/50", header: "bg-indigo-500/10", dot: "bg-indigo-400" },
  Normalize:         { border: "border-indigo-500/50", header: "bg-indigo-500/10", dot: "bg-indigo-400" },
  RegimeHMM:         { border: "border-purple-500/50", header: "bg-purple-500/10", dot: "bg-purple-400" },
  RegimePassthrough: { border: "border-purple-500/50", header: "bg-purple-500/10", dot: "bg-purple-400" },
  TrendFilter:       { border: "border-teal-500/50",   header: "bg-teal-500/10",   dot: "bg-teal-400" },
  SignalLogReg:      { border: "border-pink-500/50",   header: "bg-pink-500/10",   dot: "bg-pink-400" },
  SignalConstant:    { border: "border-pink-500/50",   header: "bg-pink-500/10",   dot: "bg-pink-400" },
  DirectionGate:     { border: "border-orange-500/50", header: "bg-orange-500/10", dot: "bg-orange-400" },
  RiskATR:           { border: "border-red-500/50",    header: "bg-red-500/10",    dot: "bg-red-400" },
  PaperTrader:       { border: "border-green-500/50",  header: "bg-green-500/10",  dot: "bg-green-400" },
  AlertOnly:         { border: "border-yellow-500/50", header: "bg-yellow-500/10", dot: "bg-yellow-400" },
  RecordDecision:    { border: "border-blue-500/50",   header: "bg-blue-500/10",   dot: "bg-blue-400" },
  LLMNode:           { border: "border-violet-500/50", header: "bg-violet-500/10", dot: "bg-violet-400" },
};

interface NodeData {
  label?: string;
  nodeType?: string;
  params?: Record<string, unknown>;
  inputPorts?: string[];
  outputPorts?: string[];
  bypass?: boolean;
  cycleIntervalS?: number | null;
}

export const BaseNode = memo(function BaseNode({ id, data, selected }: NodeProps) {
  const nodeData = data as NodeData;
  const result = useDagStore((s) => s.results[id]);
  const selectNode = useDagStore((s) => s.selectNode);
  const status = result?.status ?? "idle";
  const inputPorts = nodeData.inputPorts ?? [];
  const outputPorts = nodeData.outputPorts ?? [];
  const nodeType = (nodeData.nodeType ?? "default") as string;
  const colors = TYPE_COLORS[nodeType] ?? { border: "border-canvas-border", header: "bg-slate-800/50", dot: "bg-slate-500" };

  return (
    <div
      className={cn(
        "min-w-[180px] rounded-lg border bg-canvas-node text-xs shadow-lg cursor-pointer transition-shadow",
        selected ? "border-canvas-accent ring-1 ring-canvas-accent/30" : colors.border,
        nodeData.bypass && "opacity-60"
      )}
      onClick={() => selectNode(id)}
    >
      {/* Header */}
      <div className={cn("flex items-center gap-2 border-b border-canvas-border px-3 py-2 rounded-t-lg", colors.header)}>
        <span className={cn("h-2 w-2 rounded-full shrink-0", colors.dot || STATUS_COLOR[status])} />
        <span className="font-semibold text-white truncate">
          {nodeData.label || nodeType || id}
        </span>
        <span className="ml-auto text-slate-500 text-[10px] shrink-0">
          {nodeType}
        </span>
      </div>

      {/* Ports */}
      <div className="relative px-3 py-2 flex gap-4">
        {/* Inputs */}
        <div className="flex flex-col gap-1 items-start">
          {inputPorts.map((port, i) => (
            <div key={port} className="flex items-center gap-1 text-slate-400">
              <Handle
                type="target"
                position={Position.Left}
                id={port}
                style={{ top: `${28 + i * 20}px`, left: "-5px", position: "absolute" }}
              />
              <span className="text-[10px]">{port}</span>
            </div>
          ))}
        </div>

        {/* Outputs */}
        <div className="flex flex-col gap-1 items-end ml-auto">
          {outputPorts.map((port, i) => (
            <div key={port} className="flex items-center gap-1 text-slate-400">
              <span className="text-[10px]">{port}</span>
              <Handle
                type="source"
                position={Position.Right}
                id={port}
                style={{ top: `${28 + i * 20}px`, right: "-5px", position: "absolute" }}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Résultat */}
      {result?.status === "error" && result.error && (
        <div className="border-t border-canvas-border px-3 py-1 text-[10px] text-canvas-danger truncate">
          ✗ {result.error}
        </div>
      )}
      {result?.status === "done" && (
        <div className="border-t border-canvas-border px-3 py-1 text-[10px] text-slate-400">
          {result.duration_ms.toFixed(0)}ms
          {result.ai_used && (
            <span className="ml-2 text-canvas-accent">⚡ AI</span>
          )}
        </div>
      )}
    </div>
  );
});
