"use client";

import Link from "next/link";
import { useTranslation, LanguageSwitcher } from "@/i18n";

export default function HomePage() {
  const { t } = useTranslation();

  const navItems = [
    { href: "/dashboard", key: "nav.dashboard", descKey: "nav.dashboard.desc" },
    { href: "/canvas", key: "nav.canvas", descKey: "nav.canvas.desc" },
    { href: "/monitoring", key: "nav.monitoring", descKey: "nav.monitoring.desc" },
    { href: "/trades", key: "nav.trades", descKey: "nav.trades.desc" },
    { href: "/arena", key: "nav.arena", descKey: "nav.arena.desc" },
    { href: "/assets", key: "nav.assets", descKey: "nav.assets.desc" },
    { href: "/admin", key: "nav.admin", descKey: "nav.admin.desc" },
  ];

  return (
    <main className="flex h-screen flex-col items-center justify-center gap-8 bg-canvas-bg">
      <div className="absolute top-4 right-4">
        <LanguageSwitcher />
      </div>
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight text-white">
          {t("app.title")}
        </h1>
        <p className="mt-2 text-slate-400">{t("app.tagline")}</p>
      </div>

      <nav className="grid grid-cols-2 gap-4 md:grid-cols-3">
        {navItems.map(({ href, key, descKey }) => (
          <Link
            key={href}
            href={href}
            className="group rounded-lg border border-canvas-border bg-canvas-node px-6 py-4 
                       hover:border-canvas-accent transition-colors"
          >
            <div className="font-semibold text-white group-hover:text-canvas-accent">{t(key)}</div>
            <div className="mt-1 text-sm text-slate-400">{t(descKey)}</div>
          </Link>
        ))}
      </nav>
    </main>
  );
}
