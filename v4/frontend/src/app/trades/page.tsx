/**
 * Page Trades — journal des trades paper trading.
 * Lit les résultats du PaperTrader depuis le dernier run DAG.
 */
"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Trade {
  trade_id: string;
  symbol: string;
  action: string;
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  size_usd?: number;
  size_units?: number;
  atr?: number;
  ts: string;
  status: string;
  reason?: string;
}

export default function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchTrades() {
      try {
        // Récupère le statut de tous les DAGs pour extraire les trades PaperTrader
        const resp = await fetch(`${API_URL}/dag/status`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const dags = await resp.json();

        const allTrades: Trade[] = [];
        for (const dag of dags) {
          const results = dag.last_results || {};
          // Cherche les nœuds PaperTrader et RiskATR qui ont produit une décision
          for (const [nodeId, result] of Object.entries(results) as [string, any][]) {
            if (result.status !== "done") continue;
            const outputs = result.outputs || {};

            // PaperTrader → extraire trade_result
            if (outputs.trade_result && outputs.trade_result.action && outputs.trade_result.action !== "flat") {
              const tr = outputs.trade_result;
              allTrades.push({
                trade_id: `${dag.dag_id}_${nodeId}`,
                symbol: tr.symbol || dag.asset || "BTC/USDT",
                action: tr.action || "?",
                entry_price: tr.entry_price,
                stop_loss: tr.stop_loss,
                take_profit: tr.take_profit,
                size_usd: tr.size_usd,
                size_units: tr.size_units,
                ts: dag.last_run_at ? new Date(dag.last_run_at * 1000).toISOString() : "",
                status: tr.status || "open",
                reason: tr.reason || "",
              });
            }

            // RiskATR → extraire decision (si pas déjà traité par PaperTrader)
            if (outputs.decision && outputs.decision.action && outputs.decision.action !== "flat") {
              const dec = outputs.decision;
              const alreadyAdded = allTrades.some(t => t.trade_id === `${dag.dag_id}_${nodeId}`);
              if (!alreadyAdded) {
                allTrades.push({
                  trade_id: `${dag.dag_id}_${nodeId}`,
                  symbol: dag.asset || "BTC/USDT",
                  action: dec.action,
                  entry_price: dec.entry_price,
                  stop_loss: dec.stop_loss,
                  take_profit: dec.take_profit,
                  size_usd: dec.size_usd,
                  size_units: dec.size_units,
                  atr: dec.atr,
                  ts: dag.last_run_at ? new Date(dag.last_run_at * 1000).toISOString() : "",
                  status: "open",
                  reason: dec.reason || "",
                });
              }
            }
          }
        }
        setTrades(allTrades);
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    }
    fetchTrades();
    const iv = setInterval(fetchTrades, 15_000); // refresh toutes les 15s
    return () => clearInterval(iv);
  }, []);

  if (loading) return <div className="p-8 text-slate-400 text-sm">Chargement…</div>;
  if (error) return <div className="p-8 text-red-400 text-sm">Erreur : {error}</div>;

  return (
    <div className="min-h-screen bg-canvas-bg p-6">
      <h1 className="mb-6 text-2xl font-bold text-white">Journal des trades</h1>
      <p className="mb-4 text-xs text-slate-500">Mode : paper trading (testnet uniquement)</p>

      {loading ? (
        <p className="text-slate-400">Chargement…</p>
      ) : trades.length === 0 ? (
        <p className="text-slate-500">Aucun trade enregistré.</p>
      ) : (
        <div className="overflow-auto rounded-lg border border-canvas-border">
          <table className="w-full text-xs">
            <thead className="bg-canvas-grid text-slate-400">
              <tr>
                {["ID", "Symbole", "Action", "Entry", "SL", "TP", "Taille $", "Date", "Statut"].map((h) => (
                  <th key={h} className="px-4 py-2 text-left">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => (
                <tr key={t.trade_id ?? i} className="border-t border-canvas-border text-slate-300">
                  <td className="px-4 py-2 font-mono text-slate-500">{t.trade_id?.slice(0, 8)}</td>
                  <td className="px-4 py-2 font-semibold">{t.symbol}</td>
                  <td className={`px-4 py-2 font-semibold ${t.action === "long" ? "text-canvas-success" : "text-canvas-danger"}`}>
                    {t.action?.toUpperCase()}
                  </td>
                  <td className="px-4 py-2 font-mono">{t.entry_price?.toLocaleString()}</td>
                  <td className="px-4 py-2 font-mono text-canvas-danger">{t.stop_loss?.toLocaleString()}</td>
                  <td className="px-4 py-2 font-mono text-canvas-success">{t.take_profit?.toLocaleString()}</td>
                  <td className="px-4 py-2">${t.size_usd?.toLocaleString()}</td>
                  <td className="px-4 py-2 text-slate-500">
                    {t.ts ? new Date(t.ts).toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-2">
                    <span className={t.status === "open" ? "text-canvas-warning" : "text-slate-500"}>
                      {t.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
