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
  MetaGate:          { border: "border-rose-500/50",   header: "bg-rose-500/10",   dot: "bg-rose-400" },
  CircuitBreaker:    { border: "border-red-600/50",    header: "bg-red-600/10",    dot: "bg-red-500" },
  PortfolioRisk:     { border: "border-amber-600/50",  header: "bg-amber-600/10",  dot: "bg-amber-500" },
  RegimeDetector:    { border: "border-purple-500/50", header: "bg-purple-500/10", dot: "bg-purple-400" },
  SignalXGB:         { border: "border-pink-500/50",   header: "bg-pink-500/10",   dot: "bg-pink-400" },
  CrossTFArb:        { border: "border-teal-500/50",   header: "bg-teal-500/10",   dot: "bg-teal-400" },
  DebateNode:        { border: "border-violet-500/50", header: "bg-violet-500/10", dot: "bg-violet-400" },
  PositionManager:   { border: "border-emerald-500/50",header: "bg-emerald-500/10",dot: "bg-emerald-400" },
  ReflectionNode:    { border: "border-sky-500/50",    header: "bg-sky-500/10",    dot: "bg-sky-400" },
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

  // Le dot reflète le statut (prioritaire sur la couleur de type)
  const dotColor = status !== "idle" ? STATUS_COLOR[status] : colors.dot;
  // Fond et bordure selon le résultat
  const statusBg = status === "done" ? "bg-green-950/30" : status === "error" ? "bg-red-950/30" : status === "running" ? "bg-amber-950/20" : "";
  const statusBorder = status === "done" ? "border-green-500/60" : status === "error" ? "border-red-500/60" : status === "running" ? "border-amber-500/40" : "";
  // Badge texte
  const statusLabel = status === "done" ? "✓ OK" : status === "error" ? "✗ ERR" : status === "running" ? "● RUN" : "";

  return (
    <div
      className={cn(
        "min-w-[180px] rounded-lg border-2 bg-canvas-node text-xs shadow-lg cursor-pointer transition-all duration-300",
        selected ? "border-canvas-accent ring-1 ring-canvas-accent/30 scale-[1.02]" : statusBorder || colors.border,
        statusBg,
        nodeData.bypass && "opacity-60"
      )}
      onClick={() => selectNode(id)}
    >
      {/* Header */}
      <div className={cn("flex items-center gap-2 border-b border-canvas-border px-3 py-2 rounded-t-lg", colors.header)}>
        <span className={cn("h-3 w-3 rounded-full shrink-0 transition-colors duration-300", dotColor, status === "running" && "animate-pulse")} title={status} />
        <span className="font-semibold text-white truncate">
          {nodeData.label || nodeType || id}
        </span>
        {statusLabel && (
          <span className={cn(
            "ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded shrink-0",
            status === "done" && "bg-green-600/30 text-green-400",
            status === "error" && "bg-red-600/30 text-red-400",
            status === "running" && "bg-amber-600/30 text-amber-400 animate-pulse"
          )}>
            {statusLabel}
          </span>
        )}
        <span className="text-slate-500 text-[10px] shrink-0">
          {nodeType}
        </span>
      </div>

      {/* Ports */}
      <div className="relative px-3 py-2 flex gap-4">
        {/* Inputs */}
        <div className="flex flex-col gap-1 items-start">
          {inputPorts.map((port) => (
            <div key={port} className="relative flex items-center gap-1 text-slate-400">
              <Handle
                type="target"
                position={Position.Left}
                id={port}
                style={{ top: "50%", left: "-5px", transform: "translateY(-50%)", position: "absolute" }}
              />
              <span className="text-[10px]">{port}</span>
            </div>
          ))}
        </div>

        {/* Outputs */}
        <div className="flex flex-col gap-1 items-end ml-auto">
          {outputPorts.map((port) => (
            <div key={port} className="relative flex items-center gap-1 text-slate-400">
              <span className="text-[10px]">{port}</span>
              <Handle
                type="source"
                position={Position.Right}
                id={port}
                style={{ top: "50%", right: "-5px", transform: "translateY(-50%)", position: "absolute" }}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Résultat */}
      {result?.status === "error" && result.error && (
        <div className="border-t border-canvas-danger/40 bg-red-950/30 px-3 py-1.5 text-[10px] text-canvas-danger truncate rounded-b-lg">
          ✗ {result.error}
        </div>
      )}
      {result?.status === "done" && (
        <div className="border-t border-canvas-success/30 bg-green-950/20 px-3 py-1.5 text-[10px] text-canvas-success rounded-b-lg">
          ✓ {result.duration_ms.toFixed(0)}ms
          {result.ai_used && <span className="ml-1">· ⚡ AI</span>}
          {result.outputs && Object.keys(result.outputs).length > 0 && (
            <span className="ml-1 text-slate-500">
              · {Object.entries(result.outputs).slice(0, 2).map(([k, v]) =>
                `${k}=${typeof v === 'number' ? (v as number).toFixed(2) : String(v).slice(0, 12)}`
              ).join(", ")}
            </span>
          )}
        </div>
      )}
      {result?.status === "running" && (
        <div className="border-t border-canvas-warning/30 bg-amber-950/20 px-3 py-1.5 text-[10px] text-canvas-warning animate-pulse rounded-b-lg">
          ● En cours…
        </div>
      )}
    </div>
  );
});
