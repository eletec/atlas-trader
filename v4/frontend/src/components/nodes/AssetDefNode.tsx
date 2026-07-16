/**
 * v4/frontend/src/components/nodes/AssetDefNode.tsx
 *
 * Nœud AssetDef — affiche le symbole + prix en temps réel.
 * Nœud racine du canvas, 1 seule sortie : symbol.
 */
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";
import { PriceTicker } from "@/components/ui/PriceTicker";
import { useTranslation } from "@/i18n";
import { useDagStore } from "@/store/dagStore";

interface AssetDefData {
  label?: string;
  params?: {
    symbol?: string;
    exchange?: string;
    capital_usd?: number;
    fraction?: number;
  };
  outputPorts?: string[];
}

export const AssetDefNode = memo(function AssetDefNode({ id, data, selected }: NodeProps) {
  const { t } = useTranslation();
  const d = data as AssetDefData;
  const symbol = d.params?.symbol ?? "BTC/USDT";
  const exchange = d.params?.exchange ?? "binance";
  const capital = d.params?.capital_usd ?? 10000;
  const outputPorts = d.outputPorts ?? ["symbol"];
  const allEdges = useDagStore((s) => s.edges);
  const connectedOutputs = new Set(allEdges.filter((e: any) => e.source === id).map((e: any) => e.sourceHandle));

  // Layout fixe : header(~31px) + details(8+56px) + port-row/2(~8px) ≈ 103px
  const PORT_TOP = 103;

  return (
    <div
      className={cn(
        "relative min-w-[200px] rounded-lg border bg-canvas-node shadow-lg",
        selected ? "border-canvas-accent" : "border-indigo-700"
      )}
    >
      {/* Poignée output — enfant direct, ancrée sur le conteneur relative */}
      {outputPorts.map((port) => (
        <Handle
          key={port}
          type="source"
          position={Position.Right}
          id={port}
          style={{ top: PORT_TOP }}
          className={connectedOutputs.has(port) ? "!bg-emerald-400 !border-emerald-300" : ""}
        />
      ))}

      {/* Header */}
      <div className="flex items-center gap-2 border-b border-canvas-border px-3 py-2 bg-indigo-950 rounded-t-lg">
        <span className="h-2 w-2 rounded-full bg-canvas-accent shrink-0" />
        <span className="font-bold text-white text-sm">{symbol}</span>
        <span className="ml-auto text-slate-500 text-[10px]">AssetDef</span>
      </div>

      {/* Détails */}
      <div className="px-3 py-2 space-y-1 text-xs">
        <div className="flex justify-between">
          <span className="text-slate-400">{t("node.priceLive")}</span>
          <PriceTicker symbol={symbol} className="font-bold" />
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">{t("node.exchange")}</span>
          <span className="text-slate-300 font-mono">{exchange}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">{t("node.capital")}</span>
          <span className="text-slate-300 font-mono">${capital.toLocaleString()}</span>
        </div>
      </div>

      {/* Port label */}
      <div className="px-3 pb-2 flex justify-end">
        {outputPorts.map((port) => (
          <span
            key={port}
            className={cn("text-[10px]", connectedOutputs.has(port) ? "text-emerald-400 font-medium" : "text-slate-500")}
          >
            {port} ↗
          </span>
        ))}
      </div>
    </div>
  );
});
