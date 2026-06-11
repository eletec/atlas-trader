import Link from "next/link";

export default function HomePage() {
  return (
    <main className="flex h-screen flex-col items-center justify-center gap-8 bg-canvas-bg">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight text-white">
          Atlas Trader <span className="text-canvas-accent">V5</span>
        </h1>
        <p className="mt-2 text-slate-400">Moteur DAG · Plugins IA · Canvas libre</p>
      </div>

      <nav className="grid grid-cols-2 gap-4 md:grid-cols-3">
        {[
          { href: "/dashboard", label: "📡 Dashboard", desc: "Prix & P&L temps réel" },
          { href: "/canvas", label: "Canvas", desc: "Éditeur de DAG" },
          { href: "/monitoring", label: "Monitoring", desc: "Performance live" },
          { href: "/trades", label: "Trades", desc: "Journal paper trading" },
          { href: "/arena", label: "Arena", desc: "Comparaison de stratégies" },
          { href: "/assets", label: "Actifs", desc: "Gestion des AssetDef" },
          { href: "/admin", label: "Admin", desc: "Configuration système" },
        ].map(({ href, label, desc }) => (
          <Link
            key={href}
            href={href}
            className="group rounded-lg border border-canvas-border bg-canvas-node px-6 py-4 
                       hover:border-canvas-accent transition-colors"
          >
            <div className="font-semibold text-white group-hover:text-canvas-accent">{label}</div>
            <div className="mt-1 text-sm text-slate-400">{desc}</div>
          </Link>
        ))}
      </nav>
    </main>
  );
}
