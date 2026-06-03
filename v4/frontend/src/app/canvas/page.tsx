"use client";

import { DAGCanvas } from "@/components/canvas/DAGCanvas";
import { usePriceStream } from "@/hooks/usePriceStream";
import { useDagStore } from "@/store/dagStore";

// Démarre le flux SSE pour tous les symboles présents dans les AssetDef du canvas
function PriceStreamInit() {
  const nodes = useDagStore((s) => s.nodes);
  const symbols = nodes
    .filter((n) => n.type === "AssetDef")
    .map((n) => (n.data as any)?.params?.symbol ?? "BTC/USDT")
    .filter(Boolean);

  usePriceStream(symbols.length > 0 ? symbols : ["BTC/USDT"]);
  return null;
}

export default function CanvasPage() {
  return (
    <div className="flex h-screen w-full flex-col">
      <PriceStreamInit />

      {/* Header minimal */}
      <header className="flex h-10 items-center gap-4 border-b border-canvas-border bg-canvas-node px-4 shrink-0">
        <span className="text-sm font-semibold text-white">Atlas Trader V4</span>
        <span className="text-xs text-slate-500">Canvas</span>
      </header>

      {/* Canvas plein écran */}
      <main className="flex-1 overflow-hidden">
        <DAGCanvas />
      </main>
    </div>
  );
}
