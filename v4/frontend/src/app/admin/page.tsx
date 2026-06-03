/**
 * Page Admin — Configuration système (3 vues : Globale, Par actif, Transverses).
 */
"use client";

import { useState } from "react";

type View = "global" | "asset" | "transverse";

export default function AdminPage() {
  const [view, setView] = useState<View>("global");

  return (
    <div className="min-h-screen bg-canvas-bg p-6">
      <h1 className="mb-6 text-2xl font-bold text-white">Administration</h1>

      {/* Onglets */}
      <div className="mb-6 flex gap-2 border-b border-canvas-border">
        {(["global", "asset", "transverse"] as View[]).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`px-4 py-2 text-sm capitalize transition-colors border-b-2 -mb-px ${
              view === v
                ? "border-canvas-accent text-white"
                : "border-transparent text-slate-400 hover:text-white"
            }`}
          >
            {v === "global" ? "Vue globale" : v === "asset" ? "Par actif" : "Transverses"}
          </button>
        ))}
      </div>

      {/* Contenu */}
      {view === "global" && <GlobalView />}
      {view === "asset" && <AssetView />}
      {view === "transverse" && <TransverseView />}
    </div>
  );
}

function GlobalView() {
  return (
    <div className="space-y-4 text-xs">
      <h2 className="text-sm font-semibold text-slate-300">Configuration globale</h2>
      <div className="rounded-lg border border-canvas-border bg-canvas-node p-4 max-w-md space-y-2">
        {[
          ["Environnement", "Docker local (v4-dev)"],
          ["API backend", "http://atlas-v4-api:8000"],
          ["Ollama", "http://atlas-v4-ollama:11434"],
          ["Modèle IA", "phi4:latest"],
          ["Timeout IA (s)", "10"],
          ["Testnet", "Oui (invariant)"],
        ].map(([k, v]) => (
          <div key={k} className="flex justify-between">
            <span className="text-slate-400">{k}</span>
            <span className="text-slate-200 font-mono">{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AssetView() {
  return (
    <div className="text-xs space-y-4">
      <h2 className="text-sm font-semibold text-slate-300">Configuration par actif</h2>
      <p className="text-slate-500">
        Les paramètres par actif sont définis dans les nœuds <strong className="text-white">AssetDef</strong> sur le canvas.
        Naviguez vers{" "}
        <a href="/assets" className="text-canvas-accent hover:underline">
          /assets
        </a>{" "}
        pour gérer le registre.
      </p>
    </div>
  );
}

function TransverseView() {
  return (
    <div className="text-xs space-y-4">
      <h2 className="text-sm font-semibold text-slate-300">Lanes transverses</h2>
      <p className="text-slate-500 mb-4">
        Les lanes transverses (sentiment, macro…) sont des nœuds asynchrones avec{" "}
        <code className="text-white">cycle_interval_s &gt; 0</code> qui écrivent dans le ContextStore global.
      </p>
      <div className="rounded-lg border border-canvas-border bg-canvas-node p-4 max-w-md space-y-2">
        {[
          ["ContextStore global", "clé __global__"],
          ["Isolation", "Par actif + global"],
          ["Staleness max", "Configurable par nœud"],
        ].map(([k, v]) => (
          <div key={k} className="flex justify-between">
            <span className="text-slate-400">{k}</span>
            <span className="text-slate-200 font-mono">{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
