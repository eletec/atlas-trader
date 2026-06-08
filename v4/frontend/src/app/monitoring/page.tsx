/**
 * Page Monitoring — Vue Globale (tous les DAGs actifs + prix live).
 */
"use client";

import { useEffect, useState } from "react";
import { PriceTicker } from "@/components/ui/PriceTicker";
import { usePriceStream } from "@/hooks/usePriceStream";
import { usePriceStore } from "@/store/priceStore";
import { cn } from "@/lib/utils";
import { useMemo } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function PriceStreamInit({ symbols }: { symbols: string[] }) {
  usePriceStream(symbols);
  return null;
}

interface DAGStatus {
  dag_id: string;
  asset: string;
  running: boolean;
  cycle_s: number | null;
  last_run_at: number | null;
  last_results: Record<string, { status: string; duration_ms: number }>;
}

interface LogEntry {
  ts: string;
  level: string;
  dag_id: string;
  node_id: string;
  message: string;
}

export default function MonitoringPage() {
  const [dags, setDags] = useState<DAGStatus[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const connected = usePriceStore((s) => s.connected);

  // Actifs dynamiques depuis les DAGs actifs
  const trackedSymbols = useMemo(() => {
    const assets = dags.map((d) => d.asset).filter(Boolean);
    return assets.length > 0 ? assets : ["BTC/USDT"];
  }, [dags]);

  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API_URL}/dag/status`);
        if (r.ok) setDags(await r.json());
      } catch { /* ignore */ }
    };
    poll();
    const id = setInterval(poll, 5_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const pollLogs = async () => {
      try {
        const r = await fetch(`${API_URL}/dag/logs?n=100`);
        if (r.ok) setLogs(await r.json());
      } catch { /* ignore */ }
    };
    pollLogs();
    const id = setInterval(pollLogs, 5_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="min-h-screen bg-canvas-bg p-6">
      <PriceStreamInit symbols={trackedSymbols} />

      <h1 className="mb-6 text-2xl font-bold text-white">Monitoring</h1>

      {/* Prix live */}
      <section className="mb-8">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
          Prix live{" "}
          <span className={connected ? "text-canvas-success" : "text-canvas-danger"}>
            {connected ? "● connecté" : "● déconnecté"}
          </span>
        </h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {trackedSymbols.map((sym) => (
            <div
              key={sym}
              className="rounded-lg border border-canvas-border bg-canvas-node px-4 py-3"
            >
              <div className="text-xs text-slate-400">{sym}</div>
              <PriceTicker symbol={sym} className="mt-1 text-lg font-bold" />
            </div>
          ))}
        </div>
      </section>

      {/* DAGs actifs */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
          DAGs actifs
        </h2>
        {dags.length === 0 ? (
          <p className="text-slate-500">Aucun DAG en cours.</p>
        ) : (
          <div className="overflow-auto rounded-lg border border-canvas-border">
            <table className="w-full text-xs">
              <thead className="bg-canvas-grid text-slate-400">
                <tr>
                  {["DAG ID", "Actif", "Statut", "Cycle (s)", "Dernier run", "Résultats"].map((h) => (
                    <th key={h} className="px-4 py-2 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dags.map((d) => {
                  const doneCount = Object.values(d.last_results).filter((r) => r.status === "done").length;
                  const errCount = Object.values(d.last_results).filter((r) => r.status === "error").length;
                  return (
                    <tr key={d.dag_id} className="border-t border-canvas-border text-slate-300">
                      <td className="px-4 py-2 font-mono">{d.dag_id}</td>
                      <td className="px-4 py-2">{d.asset}</td>
                      <td className="px-4 py-2">
                        <span className={d.running ? "text-canvas-success" : "text-slate-500"}>
                          {d.running ? "● actif" : "○ arrêté"}
                        </span>
                      </td>
                      <td className="px-4 py-2">{d.cycle_s ?? "—"}</td>
                      <td className="px-4 py-2">
                        {d.last_run_at
                          ? new Date(d.last_run_at * 1000).toLocaleTimeString()
                          : "—"}
                      </td>
                      <td className="px-4 py-2">
                        <span className="text-canvas-success">{doneCount} ✓</span>
                        {errCount > 0 && (
                          <span className="text-canvas-danger ml-2">{errCount} ✗</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Logs d'exécution */}
      <section className="mt-8">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
          Logs V4
        </h2>
        {logs.length === 0 ? (
          <p className="text-slate-500 text-xs">Aucun log. Lancez ▶ Run ou ⏱ Sched.</p>
        ) : (
          <div className="overflow-auto rounded-lg border border-canvas-border bg-canvas-node max-h-80">
            <div className="font-mono text-[11px] leading-relaxed">
              {logs.map((l, i) => (
                <div key={i} className="flex gap-2 px-3 py-1 border-b border-canvas-border/30 hover:bg-slate-800/30">
                  <span className="text-slate-600 shrink-0 w-[72px]">{l.ts?.slice(11, 19) || ""}</span>
                  <span className={cn(
                    "shrink-0 w-10 font-semibold",
                    l.level === "ERROR" ? "text-canvas-danger" : l.level === "WARNING" ? "text-amber-400" : "text-slate-500"
                  )}>{l.level}</span>
                  <span className="text-slate-500 shrink-0 w-20 truncate">{l.dag_id}</span>
                  <span className="text-slate-300">{l.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
