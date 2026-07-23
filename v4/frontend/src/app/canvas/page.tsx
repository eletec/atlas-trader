"use client";

import { useEffect } from "react";
import { DAGCanvas } from "@/components/canvas/DAGCanvas";
import { usePriceStream } from "@/hooks/usePriceStream";
import { useDagStore } from "@/store/dagStore";
import { useDagRegistry } from "@/store/dagRegistry";

// Construit l'URL de l'API à partir du hostname courant (fonctionne de n'importe quel client)
function getApiBase(): string {
  if (typeof window === "undefined") return "";
  const host = window.location.hostname;
  return `http://${host}:8000`;
}

// Synchronise la liste des DAGs avec l'API (lecture dynamique de carry_assets.yaml)
function DAGRegistrySync() {
  const dags = useDagRegistry((s) => s.dags);
  const activeId = useDagRegistry((s) => s.activeId);
  const setActive = useDagRegistry((s) => s.setActive);

  useEffect(() => {
    const apiBase = getApiBase();
    if (!apiBase) return;

    fetch(`${apiBase}/dag/status`)
      .then((r) => r.json())
      .then((apiDags: Array<{ dag_id: string; asset: string }>) => {
        if (!apiDags || apiDags.length === 0) return;

        const now = Date.now();
        const existingIds = new Set(dags.map((d) => d.id));
        const newDags: Array<{ id: string; name: string; createdAt: number }> = [];
        const allApiIds: string[] = [];

        for (const ad of apiDags) {
          // v7_btc → "default" (compat historique), les autres → id sans prefixe
          const id = ad.dag_id === "v7_btc" || ad.dag_id === "v7_default"
            ? "default"
            : ad.dag_id.replace(/^v7_/, "");
          allApiIds.push(id);
          if (!existingIds.has(id)) {
            newDags.push({ id, name: ad.asset || ad.dag_id, createdAt: now });
          }
        }

        // Ajouter les nouveaux, retirer ceux qui n'existent plus dans l'API
        useDagRegistry.setState((s) => {
          const kept = s.dags.filter((d) => allApiIds.includes(d.id));
          const added = newDags.filter((nd) => !kept.find((k) => k.id === nd.id));
          const merged = [...kept, ...added];
          // Si l'actif courant a disparu, basculer sur le premier
          const newActive = merged.find((d) => d.id === s.activeId)
            ? s.activeId
            : merged[0]?.id || "default";
          return { dags: merged, activeId: newActive };
        });
      })
      .catch(() => {
        // API injoignable → garder le localStorage existant (ne rien faire)
      });
  }, []); // exécuté une seule fois au mount

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
