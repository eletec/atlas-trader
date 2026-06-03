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
  const status = result?.status ?? "idle";
  const inputPorts = nodeData.inputPorts ?? [];
  const outputPorts = nodeData.outputPorts ?? [];

  return (
    <div
      className={cn(
        "min-w-[180px] rounded-lg border bg-canvas-node text-xs shadow-lg",
        selected ? "border-canvas-accent" : "border-canvas-border",
        nodeData.bypass && "opacity-60"
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-canvas-border px-3 py-2">
        <span className={cn("h-2 w-2 rounded-full shrink-0", STATUS_COLOR[status])} />
        <span className="font-semibold text-white truncate">
          {nodeData.label || nodeData.nodeType || id}
        </span>
        <span className="ml-auto text-slate-500 text-[10px] shrink-0">
          {nodeData.nodeType}
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
