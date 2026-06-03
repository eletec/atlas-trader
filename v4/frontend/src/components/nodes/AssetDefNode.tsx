/**
 * v4/frontend/src/components/nodes/AssetDefNode.tsx
 *
 * Nœud AssetDef — affiche le symbole + prix en temps réel.
 * Nœud racine du canvas, pas d'inputs.
 */
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";
import { PriceTicker } from "@/components/ui/PriceTicker";

interface AssetDefData {
  label?: string;
  params?: {
    symbol?: string;
    exchange?: string;
    capital_usd?: number;
    fraction?: number;
  };
}

export const AssetDefNode = memo(function AssetDefNode({ id, data, selected }: NodeProps) {
  const d = data as AssetDefData;
  const symbol = d.params?.symbol ?? "BTC/USDT";
  const exchange = d.params?.exchange ?? "binance";
  const capital = d.params?.capital_usd ?? 10000;

  return (
    <div
      className={cn(
        "min-w-[200px] rounded-lg border bg-canvas-node shadow-lg",
        selected ? "border-canvas-accent" : "border-indigo-700"
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-canvas-border px-3 py-2 bg-indigo-950 rounded-t-lg">
        <span className="h-2 w-2 rounded-full bg-canvas-accent shrink-0" />
        <span className="font-bold text-white text-sm">{symbol}</span>
        <span className="ml-auto text-slate-500 text-[10px]">AssetDef</span>
      </div>

      {/* Détails */}
      <div className="px-3 py-2 space-y-1 text-xs">
        <div className="flex justify-between">
          <span className="text-slate-400">Prix live</span>
          <PriceTicker symbol={symbol} className="font-bold" />
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Exchange</span>
          <span className="text-slate-300 font-mono">{exchange}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Capital</span>
          <span className="text-slate-300 font-mono">${capital.toLocaleString()}</span>
        </div>
      </div>

      {/* Output handles */}
      {["symbol", "exchange", "capital", "fraction", "fee_rate"].map((port, i) => (
        <Handle
          key={port}
          type="source"
          position={Position.Right}
          id={port}
          style={{ top: `${56 + i * 20}px`, right: "-5px", position: "absolute" }}
        />
      ))}
    </div>
  );
});
