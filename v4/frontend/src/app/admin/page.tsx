/**
 * Page Admin — Configuration système (3 vues : Globale, Par actif, Transverses).
 */
"use client";

import { useState } from "react";
import { useTranslation } from "@/i18n";

type View = "global" | "asset" | "transverse";

export default function AdminPage() {
  const { t } = useTranslation();
  const [view, setView] = useState<View>("global");

  return (
    <div className="min-h-screen bg-canvas-bg p-6">
      <h1 className="mb-6 text-2xl font-bold text-white">{t("admin.title")}</h1>

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
            {v === "global" ? t("admin.tab.global") : v === "asset" ? t("admin.tab.perAsset") : t("admin.tab.transverse")}
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
  const { t } = useTranslation();
  return (
    <div className="space-y-4 text-xs">
      <h2 className="text-sm font-semibold text-slate-300">{t("admin.globalConfig")}</h2>
      <div className="rounded-lg border border-canvas-border bg-canvas-node p-4 max-w-md space-y-2">
        {[
          [t("admin.env"), "Docker"],
          [t("admin.apiBackend"), "http://atlas-v4-api:8000"],
          [t("admin.ollama"), "http://atlas-v4-ollama:11434"],
          [t("admin.aiModel"), "phi4:latest"],
          [t("admin.aiTimeout"), "10"],
          [t("admin.testnet"), t("admin.testnetValue")],
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
  const { t } = useTranslation();
  return (
    <div className="text-xs space-y-4">
      <h2 className="text-sm font-semibold text-slate-300">{t("admin.perAssetConfig")}</h2>
      <p className="text-slate-500">
        {t("admin.perAssetDesc1")}<strong className="text-white">AssetDef</strong> {t("admin.perAssetDesc2")}
        <a href="/assets" className="text-canvas-accent hover:underline">
          /assets
        </a>{" "}
        {t("admin.perAssetDesc3")}
      </p>
    </div>
  );
}

function TransverseView() {
  const { t } = useTranslation();
  return (
    <div className="text-xs space-y-4">
      <h2 className="text-sm font-semibold text-slate-300">{t("admin.transverseTitle")}</h2>
      <p className="text-slate-500 mb-4">
        {t("admin.transverseDesc1")}<code className="text-white">cycle_interval_s &gt; 0</code> {t("admin.transverseDesc2")}
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
