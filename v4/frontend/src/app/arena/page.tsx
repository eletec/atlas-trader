/**
 * Page Arena V4.1 — Comparaison de DAGs / stratégies.
 * Placeholder V4.0 : l'arène sera implémentée en V4.1.
 */
export default function ArenaPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-canvas-bg">
      <div className="rounded-lg border border-canvas-border bg-canvas-node px-8 py-10 text-center max-w-md">
        <div className="text-4xl mb-4">⚔️</div>
        <h1 className="text-2xl font-bold text-white mb-2">Arena V4.1</h1>
        <p className="text-slate-400 text-sm mb-4">
          Comparaison de stratégies côte-à-côte sur données historiques.
        </p>
        <p className="text-xs text-slate-500">
          Disponible en V4.1 — en cours de conception.
        </p>
        <div className="mt-6 grid grid-cols-2 gap-2 text-xs text-slate-400">
          {[
            "Backtest parallèle de N DAGs",
            "Métriques : Sharpe, Drawdown, Win rate",
            "Heatmap de corrélation",
            "Export CSV / JSON",
          ].map((f) => (
            <div key={f} className="rounded border border-canvas-border px-2 py-1.5 text-left">
              ○ {f}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
