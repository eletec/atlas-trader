/**
 * Page Trades — journal des trades paper trading.
 */
"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Trade {
  trade_id?: string;
  symbol?: string;
  action?: string;
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  size_usd?: number;
  ts?: number;
  status?: string;
}

export default function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // En V4.0 : données mock — la vraie route sera /api/trades
    setTrades([
      {
        trade_id: "mock-001",
        symbol: "BTC/USDT",
        action: "long",
        entry_price: 67450,
        stop_loss: 66000,
        take_profit: 72000,
        size_usd: 50,
        ts: Date.now() / 1000 - 3600,
        status: "open",
      },
    ]);
    setLoading(false);
  }, []);

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
                  <td className="px-4 py-2">${t.size_usd}</td>
                  <td className="px-4 py-2 text-slate-500">
                    {t.ts ? new Date(t.ts * 1000).toLocaleString() : "—"}
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
