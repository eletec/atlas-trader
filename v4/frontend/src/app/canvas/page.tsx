"use client";

import { useEffect } from "react";
import { DAGCanvas } from "@/components/canvas/DAGCanvas";
import { usePriceStream } from "@/hooks/usePriceStream";
import { useDagStore } from "@/store/dagStore";
import { useDagRegistry } from "@/store/dagRegistry";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Synchronise la liste des DAGs avec l'API (v7 — dynamique depuis carry_assets.yaml)
function DAGRegistrySync() {
  const dags = useDagRegistry((s) => s.dags);
  const activeId = useDagRegistry((s) => s.activeId);
  const setActive = useDagRegistry((s) => s.setActive);
  const hydrated = useDagRegistry((s) => (s as any)._hydrated);

  useEffect(() => {
    if (!hydrated) return;

    fetch(`${API_BASE}/dag/status`)
      .then((r) => r.json())
      .then((apiDags: Array<{ dag_id: string; asset: string }>) => {
        if (!apiDags || apiDags.length === 0) return;

        const now = Date.now();
        const existingIds = new Set(dags.map((d) => d.id));
        const newDags: Array<{ id: string; name: string; createdAt: number }> = [];

        for (const ad of apiDags) {
          const id = ad.dag_id.replace("v7_", "") === "btc" ? "default" : ad.dag_id.replace("v7_", "");
          if (!existingIds.has(id)) {
            newDags.push({ id, name: ad.asset || id.toUpperCase(), createdAt: now });
          }
        }

        if (newDags.length > 0) {
          // Ajouter les nouveaux DAGs au registre (via un appel setState)
          useDagRegistry.setState((s) => ({
            dags: [...s.dags, ...newDags],
          }));
          // Si l'actif courant n'est plus valide, basculer sur le premier
          const allIds = new Set([...dags.map((d) => d.id), ...newDags.map((d) => d.id)]);
          if (!allIds.has(activeId) && dags.length > 0) {
            setActive(dags[0].id);
          }
        }
      })
      .catch(() => {
        // API injoignable → utiliser le localStorage existant (7 anciens DAGs)
      });
  }, [hydrated]);

  return null;
}

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
      <DAGRegistrySync />
      <PriceStreamInit />
      <DAGCanvas />
    </div>
  );
}
