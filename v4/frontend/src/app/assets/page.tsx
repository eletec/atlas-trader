/**
 * Page Assets — gestion des AssetDef (registre des actifs).
 * Affiche la liste, permet d'en ajouter / modifier (formulaire simple).
 * En V4.0 : persistance localStorage, pas encore de CRUD API.
 */
"use client";

import { useState } from "react";
import { useTranslation } from "@/i18n";

interface AssetEntry {
  symbol: string;
  exchange: string;
  capital_usd: number;
  fraction: number;
  fee_rate: number;
  max_positions: number;
  keywords: string;
}

const DEFAULT: AssetEntry = {
  symbol: "BTC/USDT",
  exchange: "binance",
  capital_usd: 10000,
  fraction: 0.005,
  fee_rate: 0.0004,
  max_positions: 3,
  keywords: "bitcoin,BTC",
};

export default function AssetsPage() {
  const { t } = useTranslation();
  const [assets, setAssets] = useState<AssetEntry[]>([DEFAULT]);
  const [editing, setEditing] = useState<AssetEntry | null>(null);
  const [form, setForm] = useState<AssetEntry>(DEFAULT);

  const save = () => {
    if (editing) {
      setAssets((prev) =>
        prev.map((a) => (a.symbol === editing.symbol ? form : a))
      );
    } else {
      setAssets((prev) => [...prev, form]);
    }
    setEditing(null);
    setForm(DEFAULT);
  };

  return (
    <div className="min-h-screen bg-canvas-bg p-6">
      <h1 className="mb-6 text-2xl font-bold text-white">{t("assets.title")}</h1>

      {/* Liste */}
      <div className="mb-6 overflow-auto rounded-lg border border-canvas-border">
        <table className="w-full text-xs">
          <thead className="bg-canvas-grid text-slate-400">
            <tr>
              {[t("assets.col.symbol"), t("assets.col.exchange"), t("assets.col.capital"), t("assets.col.fraction"), t("assets.col.maxPos"), t("assets.col.fee"), t("assets.col.keywords"), ""].map((h) => (
                <th key={h} className="px-4 py-2 text-left">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {assets.map((a) => (
              <tr key={a.symbol} className="border-t border-canvas-border text-slate-300">
                <td className="px-4 py-2 font-mono font-semibold">{a.symbol}</td>
                <td className="px-4 py-2">{a.exchange}</td>
                <td className="px-4 py-2">${a.capital_usd.toLocaleString()}</td>
                <td className="px-4 py-2">{(a.fraction * 100).toFixed(2)}%</td>
                <td className="px-4 py-2">{a.max_positions ?? 3}</td>
                <td className="px-4 py-2">{(a.fee_rate * 100).toFixed(3)}%</td>
                <td className="px-4 py-2 text-slate-500">{a.keywords}</td>
                <td className="px-4 py-2">
                  <button
                    onClick={() => { setEditing(a); setForm(a); }}
                    className="text-canvas-accent hover:underline"
                  >
                    {t("assets.edit")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Formulaire */}
      <div className="rounded-lg border border-canvas-border bg-canvas-node p-4 max-w-md">
        <h2 className="mb-4 text-sm font-semibold text-white">
          {editing ? t("assets.editTitle", { symbol: editing.symbol }) : t("assets.new")}
        </h2>
        <div className="space-y-2 text-xs">
          {(Object.keys(DEFAULT) as (keyof AssetEntry)[]).map((key) => (
            <div key={key} className="flex items-center gap-3">
              <label className="w-24 text-slate-400">{key}</label>
              <input
                value={form[key]}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    [key]: ["capital_usd", "fraction", "fee_rate"].includes(key)
                      ? Number(e.target.value)
                      : e.target.value,
                  }))
                }
                className="flex-1 rounded border border-canvas-border bg-canvas-bg px-2 py-1 text-slate-200"
              />
            </div>
          ))}
        </div>
        <div className="mt-4 flex gap-2">
          <button
            onClick={save}
            className="rounded bg-canvas-accent px-4 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500"
          >
            {t("assets.save")}
          </button>
          {editing && (
            <button
              onClick={() => { setEditing(null); setForm(DEFAULT); }}
              className="rounded border border-canvas-border px-4 py-1.5 text-xs text-slate-400 hover:text-white"
            >
              {t("assets.cancel")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
