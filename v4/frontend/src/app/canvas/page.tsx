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
    <div className="h-screen w-full bg-canvas-bg">
      <PriceStreamInit />
      <DAGCanvas />
    </div>
  );
}
