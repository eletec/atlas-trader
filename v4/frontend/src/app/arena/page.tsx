"use client";

import { useTranslation } from "@/i18n";

/**
 * Page Arena — Comparaison de DAGs / stratégies.
 */
export default function ArenaPage() {
  const { t } = useTranslation();
  const features = [
    t("arena.feature1"), t("arena.feature2"), t("arena.feature3"), t("arena.feature4")
  ];
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-canvas-bg">
      <div className="rounded-lg border border-canvas-border bg-canvas-node px-8 py-10 text-center max-w-md">
        <div className="text-4xl mb-4">⚔️</div>
        <h1 className="text-2xl font-bold text-white mb-2">{t("arena.title")}</h1>
        <p className="text-slate-400 text-sm mb-4">
          {t("arena.description")}
        </p>
        <p className="text-xs text-slate-500">
          {t("arena.status")}
        </p>
        <div className="mt-6 grid grid-cols-2 gap-2 text-xs text-slate-400">
          {features.map((f) => (
            <div key={f} className="rounded border border-canvas-border px-2 py-1.5 text-left">
              ○ {f}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
