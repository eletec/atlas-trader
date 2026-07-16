/**
 * Page Dashboard — Vue temps réel (prix, P&L, DAGs).
 * Remplace le dashboard Streamlit pour le monitoring live.
 */
"use client";

import { useEffect, useState, useMemo, useRef } from "react";
import { PriceTicker } from "@/components/ui/PriceTicker";
import { usePriceStream } from "@/hooks/usePriceStream";
import { usePriceStore } from "@/store/priceStore";
import { cn } from "@/lib/utils";
import { getApiUrl } from "@/lib/api-url";
import { useTranslation, LanguageSwitcher } from "@/i18n";

const API_URL = getApiUrl();
const SYMBOL_ICONS: Record<string, string> = {
  "BTC/USDT": "₿", "ETH/USDT": "⟠", "BNB/USDT": "🔶",
  "SOL/USDT": "◎", "XRP/USDT": "✕",
};

// ── Types ──────────────────────────────────────────────────────────────────
interface DAGStatus {
  dag_id: string; asset: string; running: boolean;
  cycle_s: number | null; last_run_at: number | null;
  last_results: Record<string, { status: string; duration_ms: number; outputs?: Record<string, unknown> }>;
}

interface TradeRecord {
  trade_id: string; symbol: string; action: string;
  entry_price: number; stop_loss: number; status: string; pnl_usd: number;
}

// ── Helpers ────────────────────────────────────────────────────────────────
function fmtPrice(p: number | null | undefined): string {
  if (p == null) return "—";
  if (p >= 1000) return "$" + p.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (p >= 1) return "$" + p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return "$" + p.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
}

function fmtPct(v: number): string { return (v >= 0 ? "+" : "") + v.toFixed(2) + "%"; }

// ── Component: PriceStreamInit ─────────────────────────────────────────────
function PriceStreamInit({ symbols }: { symbols: string[] }) {
  usePriceStream(symbols);
  return null;
}

// ── Component: PriceCard ───────────────────────────────────────────────────
function PriceCard({ symbol, entryPrice, position }: {
  symbol: string; entryPrice: number | null; position?: { action: string; entry: number } | null;
}) {
  const record = usePriceStore((s) => s.prices[symbol]);
  const price = record?.price ?? null;
  const prevRef = useRef<number | null>(null);
  const initRef = useRef<number | null>(null);
  const [flash, setFlash] = useState<"up" | "dn" | null>(null);

  if (price !== null && initRef.current === null) initRef.current = price;
  const initPrice = initRef.current;
  const chgPct = price && initPrice ? ((price - initPrice) / initPrice) * 100 : 0;

  useEffect(() => {
    if (prevRef.current !== null && price !== null) {
      if (price > prevRef.current) { setFlash("up"); setTimeout(() => setFlash(null), 400); }
      else if (price < prevRef.current) { setFlash("dn"); setTimeout(() => setFlash(null), 400); }
    }
    if (price !== null) prevRef.current = price;
  }, [price]);

  // PnL latent
  let pnlPct = 0; let pnlLabel = "—";
  if (position && price && position.entry) {
    pnlPct = position.action === "short"
      ? ((position.entry - price) / position.entry) * 100
      : ((price - position.entry) / position.entry) * 100;
    pnlLabel = position.action.toUpperCase() + " " + (pnlPct >= 0 ? "+" : "") + pnlPct.toFixed(1) + "%";
  }

  const icon = SYMBOL_ICONS[symbol] || "◈";
  const chgColor = chgPct > 0.05 ? "text-canvas-success" : chgPct < -0.05 ? "text-canvas-danger" : "text-slate-400";
  const pnlColor = pnlPct >= 0 ? "text-canvas-success" : "text-canvas-danger";
  const arrow = chgPct > 0.05 ? "▲" : chgPct < -0.05 ? "▼" : "◆";

  return (
    <div className={cn(
      "rounded-lg border border-canvas-border bg-canvas-node px-4 py-3 text-center min-w-[140px] transition-colors",
      flash === "up" && "bg-green-900/20",
      flash === "dn" && "bg-red-900/20"
    )}>
      <div className="text-xl">{icon}</div>
      <div className="text-xs text-slate-400">{symbol}</div>
      <div className="text-xl font-bold tabular-nums mt-1">
        {price !== null ? fmtPrice(price) : "—"}
      </div>
      <div className={cn("text-xs font-semibold mt-1", chgColor)}>
        {arrow} {fmtPct(chgPct)}
      </div>
      <div className={cn("text-xs font-semibold", pnlColor)}>
        {pnlLabel}
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const { t } = useTranslation();
  const [dags, setDags] = useState<DAGStatus[]>([]);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [portfolio, setPortfolio] = useState({ capital: 10000, value: 10000, pnl: 0, pnlPct: 0, count: 0 });
  const connected = usePriceStore((s) => s.connected);

  const dagAssets = useMemo(() => {
    const assets = dags.map(d => d.asset).filter(Boolean);
    return assets.length > 0 ? assets : ["BTC/USDT"];
  }, [dags]);

  // ── Polling ────────────────────────────────────────────────────────────
  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API_URL}/dag/status`);
        if (r.ok) setDags(await r.json());
      } catch { /* */ }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API_URL}/prices/snapshot`);
        if (!r.ok) return;
        const data = await r.json();
        // Calculer le P&L portfolio à partir des trades ouverts
        let totalPnl = 0; let totalValue = 0; let openCount = 0;
        const tr: TradeRecord[] = [];
        try {
          const r2 = await fetch(`${API_URL}/dag/status`);
          if (r2.ok) {
            const ds: DAGStatus[] = await r2.json();
            for (const d of ds) {
              const pfx = d.asset.split("/")[0].toLowerCase().slice(0, 3);
              const pm = d.last_results?.[`${pfx}_posmgr`];
              if (pm?.outputs) {
                const openPos = (pm.outputs as Record<string, unknown>).open_positions as Array<Record<string, unknown>> | undefined;
                if (openPos) {
                  for (const p of openPos) {
                    const entry = p.entry_price as number;
                    const action = p.action as string;
                    const price = (data[d.asset] as Record<string, unknown>)?.price as number;
                    if (entry && price) {
                      const pnl = action === "short" ? (entry - price) / entry : (price - entry) / entry;
                      totalPnl += pnl * 150; // approximate: 150$ size
                      openCount++;
                    }
                  }
                }
              }
            }
          }
        } catch { /* */ }
        totalValue = 50000 + totalPnl; // 5 assets × 10000
        setPortfolio({ capital: 50000, value: totalValue, pnl: totalPnl, pnlPct: (totalPnl / 50000) * 100, count: openCount });
        setTrades(tr);
      } catch { /* */ }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  // ── Extraire les positions ouvertes ────────────────────────────────────
  const positions = useMemo(() => {
    const map: Record<string, { action: string; entry: number }> = {};
    for (const d of dags) {
      const pfx = d.asset.split("/")[0].toLowerCase().slice(0, 3);
      const pm = d.last_results?.[`${pfx}_posmgr`];
      if (pm?.outputs) {
        const openPos = (pm.outputs as Record<string, unknown>).open_positions as Array<Record<string, unknown>> | undefined;
        if (openPos?.[0]) {
          map[d.asset] = {
            action: (openPos[0].action as string) || "?",
            entry: (openPos[0].entry_price as number) || 0,
          };
        }
      }
    }
    return map;
  }, [dags]);

  // ── Render ─────────────────────────────────────────────────────────────
  const pnlColor = portfolio.pnl >= 0 ? "text-canvas-success" : "text-canvas-danger";

  return (
    <div className="min-h-screen bg-canvas-bg p-6">
      <PriceStreamInit symbols={dagAssets} />

      <h1 className="mb-6 text-2xl font-bold text-white">{t("dashboard.title")}</h1>
      <div className="absolute top-4 right-4"><LanguageSwitcher /></div>

      {/* ── Portfolio ── */}
      <section className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
        <div className="rounded-lg border border-canvas-border bg-canvas-node px-4 py-3">
          <div className="text-xs text-slate-400">{t("dashboard.capital")}</div>
          <div className="text-lg font-bold">${portfolio.capital.toLocaleString()}</div>
        </div>
        <div className="rounded-lg border border-canvas-border bg-canvas-node px-4 py-3">
          <div className="text-xs text-slate-400">{t("dashboard.value")}</div>
          <div className="text-lg font-bold">${portfolio.value.toLocaleString()}</div>
        </div>
        <div className="rounded-lg border border-canvas-border bg-canvas-node px-4 py-3">
          <div className="text-xs text-slate-400">{t("dashboard.pnl")}</div>
          <div className={cn("text-lg font-bold", pnlColor)}>
            ${portfolio.pnl >= 0 ? "+" : ""}{portfolio.pnl.toFixed(2)}
          </div>
          <div className={cn("text-xs", pnlColor)}>
            {portfolio.pnlPct >= 0 ? "▲" : "▼"} {portfolio.pnlPct.toFixed(2)}%
          </div>
        </div>
        <div className="rounded-lg border border-canvas-border bg-canvas-node px-4 py-3">
          <div className="text-xs text-slate-400">{t("dashboard.trades")}</div>
          <div className="text-lg font-bold">{portfolio.count}</div>
        </div>
        <div className="rounded-lg border border-canvas-border bg-canvas-node px-4 py-3">
          <div className="text-xs text-slate-400">{t("dashboard.connection")}</div>
          <div className={cn("text-lg font-bold", connected ? "text-canvas-success" : "text-canvas-danger")}>
            {connected ? t("dashboard.connected") : t("dashboard.disconnected")}
          </div>
        </div>
      </section>

      {/* ── Prix live ── */}
      <section className="mb-6">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
          {t("dashboard.livePrice")}
        </h2>
        <div className="flex flex-wrap gap-3">
          {dagAssets.map(sym => (
            <PriceCard key={sym} symbol={sym}
              entryPrice={null} position={positions[sym] || null} />
          ))}
        </div>
      </section>

      {/* ── DAG Overview ── */}
      <section className="mb-6">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
          {t("dashboard.activeDags")}
        </h2>
        {dags.length === 0 ? (
          <p className="text-slate-500">{t("dashboard.noDags")}</p>
        ) : (
          <div className="overflow-auto rounded-lg border border-canvas-border">
            <table className="w-full text-xs">
              <thead className="bg-canvas-grid text-slate-400">
                <tr>
                  {[t("dashboard.col.asset"), t("dashboard.col.signal"), t("dashboard.col.dir"), t("dashboard.col.run"), t("dashboard.col.trade"), t("dashboard.col.trend"), t("dashboard.col.status")].map(h => (
                    <th key={h} className="px-3 py-2 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dags.map(d => {
                  const pfx = d.asset.split("/")[0].toLowerCase().slice(0, 3);
                  const sn = d.last_results?.[`${pfx}_signal`]?.outputs as Record<string, unknown> | undefined;
                  const tn = d.last_results?.[`${pfx}_trend`]?.outputs as Record<string, unknown> | undefined;
                  const rk = d.last_results?.[`${pfx}_risk`]?.outputs as Record<string, unknown> | undefined;
                  const sk = d.last_results?.[`${pfx}_short_risk`]?.outputs as Record<string, unknown> | undefined;
                  const signal = (sn?.signal as string) || "—";
                  const prob = sn?.prob_up as number | undefined;
                  const trend = ((tn?.trend as string) || "—").toUpperCase();
                  const rd = rk?.decision as Record<string, unknown> | undefined;
                  const sd = sk?.decision as Record<string, unknown> | undefined;
                  const dec = rd || sd;
                  const action = dec?.action as string;
                  const ep = dec?.entry_price as number;
                  const tradeStr = action && action !== "flat" && ep
                    ? `${action.toUpperCase()} @ $${Math.round(ep)}` : "—";
                  const score = signal === "long" ? Math.round((prob ?? 0.75) * 100)
                    : signal === "short" ? Math.round((1 - (prob ?? 0.5)) * 100) : 50;
                  const icon = SYMBOL_ICONS[d.asset] || "◈";
                  const ts = d.last_run_at ? new Date(d.last_run_at * 1000).toLocaleTimeString().slice(0, 8) : "—";
                  return (
                    <tr key={d.dag_id} className="border-t border-canvas-border text-slate-300">
                      <td className="px-3 py-2">{icon} {d.asset}</td>
                      <td className={cn("px-3 py-2 font-semibold",
                        signal === "long" ? "text-canvas-success" : signal === "short" ? "text-canvas-danger" : "")}>
                        {signal}
                      </td>
                      <td className="px-3 py-2">{score}</td>
                      <td className="px-3 py-2 text-slate-500">{ts}</td>
                      <td className="px-3 py-2 text-slate-400">{tradeStr}</td>
                      <td className="px-3 py-2">{trend}</td>
                      <td className="px-3 py-2">
                        <span className={d.running ? "text-canvas-success" : "text-slate-500"}>
                          {d.running ? t("dashboard.status.active") : t("dashboard.status.stopped")}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Analyses IA ── */}
      <section className="mb-6">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
          🧠 Dernières analyses IA
        </h2>
        <div className="space-y-2">
          {dags.map(d => {
            const pfx = d.asset.split("/")[0].toLowerCase().slice(0, 3);
            const ai = d.last_results?.[`${pfx}_ai`]?.outputs as Record<string, unknown> | undefined;
            const response = ai?.response as string | undefined;
            if (!response || response.startsWith("LLM_ERROR")) return null;
            const model = (ai?.model as string) || "?";
            const dur = ((ai?.duration_ms as number) || 0) / 1000;
            const icon = SYMBOL_ICONS[d.asset] || "◈";
            return (
              <details key={d.dag_id} className="rounded-lg border border-canvas-border bg-canvas-node">
                <summary className="px-4 py-2 text-sm font-semibold cursor-pointer hover:bg-canvas-grid transition-colors">
                  {icon} {d.asset} ({model}, {dur.toFixed(1)}s)
                </summary>
                <div className="px-4 py-3 text-xs text-slate-300 whitespace-pre-wrap max-h-64 overflow-y-auto border-t border-canvas-border">
                  {response}
                </div>
              </details>
            );
          })}
        </div>
      </section>

      {/* ── Logs live ── */}
      <LogsSection />
    </div>
  );
}

// ── Logs Section ──────────────────────────────────────────────────────────
function LogsSection() {
  const [logs, setLogs] = useState<Array<{ ts: string; level: string; dag_id: string; message: string }>>([]);

  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API_URL}/dag/logs?n=30`);
        if (r.ok) setLogs(await r.json());
      } catch { /* */ }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
        ⚡ Logs temps réel
      </h2>
      {logs.length === 0 ? (
        <p className="text-slate-500 text-xs">Aucun log.</p>
      ) : (
        <div className="overflow-auto rounded-lg border border-canvas-border bg-canvas-node max-h-60">
          <div className="font-mono text-[11px] leading-relaxed">
            {logs.map((l, i) => (
              <div key={i} className="flex gap-2 px-3 py-1 border-b border-canvas-border/30 hover:bg-slate-800/30">
                <span className="text-slate-600 shrink-0 w-[72px]">{l.ts?.slice(11, 19) || ""}</span>
                <span className={cn(
                  "shrink-0 w-10 font-semibold",
                  l.level === "ERROR" ? "text-canvas-danger" : l.level === "WARNING" ? "text-amber-400" : "text-slate-500"
                )}>{l.level}</span>
                <span className="text-slate-500 shrink-0 w-20 truncate">{l.dag_id}</span>
                <span className="text-slate-300 truncate">{l.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
