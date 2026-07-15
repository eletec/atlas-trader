"""
scripts/reconcile.py — Réconciliation DB Atlas ↔ marché (CCXT).

Compare les positions enregistrées dans v4_trades avec :
  - Les prix spot/perf actuels via CCXT
  - Le P&L réel calculé (deux jambes pour le carry)
  - Les frais estimés

Usage:
    docker exec atlas-v4-api python /app/src/scripts/reconcile.py
    docker exec atlas-v4-api python /app/src/scripts/reconcile.py --fix  # corrige les écarts
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reconcile")


def fetch_market_prices(symbols: list[str]) -> dict[str, dict]:
    """Fetch spot + perp prices pour les symboles donnés."""
    prices = {}
    try:
        import ccxt
        exchange = ccxt.binance({"enableRateLimit": True})
        for sym in symbols:
            try:
                ticker = exchange.fetch_ticker(sym)
                spot = float(ticker.get("last", 0))
                # Perp
                sym_perp = f"{sym}:USDT" if ":" not in sym else sym
                try:
                    perp_ticker = exchange.fetch_ticker(sym_perp)
                    perp = float(perp_ticker.get("last", 0))
                except Exception:
                    perp = spot
                prices[sym] = {"spot": spot, "perp": perp, "basis": (perp - spot) / spot if spot > 0 else 0}
            except Exception as e:
                logger.warning("  Prix indisponible pour %s: %s", sym, e)
    except ImportError:
        logger.error("CCXT non disponible")
    return prices


def reconcile_positions(fix: bool = False) -> dict:
    """Compare les positions Atlas avec la réalité marché."""
    try:
        from storage.paper_trader import get_open_positions, get_v4_trades, close_position
    except ImportError:
        logger.error("storage.paper_trader indisponible")
        return {"error": "storage unavailable"}

    positions = get_open_positions()
    all_trades = get_v4_trades(n=500)
    
    if not positions:
        logger.info("✅ Aucune position ouverte — rien à réconcilier.")
        return {"open": 0, "closed_total": len(all_trades), "discrepancies": []}

    symbols = list(set(p.get("symbol", "") for p in positions if p.get("symbol")))
    market = fetch_market_prices(symbols)

    report = {
        "open": len(positions),
        "closed_total": len([t for t in all_trades if t.get("status") == "closed"]),
        "discrepancies": [],
        "ok_count": 0,
    }

    logger.info("Réconciliation de %d positions ouvertes...", len(positions))
    logger.info("")

    for pos in positions:
        trade_id = pos.get("trade_id", "?")
        symbol = pos.get("symbol", "?")
        action = pos.get("action", "?")
        entry = float(pos.get("entry_price", 0) or 0)
        size = float(pos.get("size_usd", 0) or 0)
        sl = float(pos.get("stop_loss", 0) or 0)
        tp = float(pos.get("take_profit", 0) or 0)

        mkt = market.get(symbol, {})
        spot = mkt.get("spot", 0)
        perp = mkt.get("perp", 0)
        basis = mkt.get("basis", 0)

        # P&L spot (simple short)
        if action in ("short", "carry") and spot > 0 and entry > 0:
            spot_pnl = (entry - spot) / entry * size
        elif spot > 0 and entry > 0:
            spot_pnl = (spot - entry) / entry * size
        else:
            spot_pnl = 0

        # P&L basis (carry uniquement)
        basis_pnl = 0.0
        if action == "carry" and perp > 0 and spot > 0 and entry > 0:
            # Extraire entry_perp du context_json
            entry_perp = entry  # fallback
            try:
                import json as _j
                ctx_raw = pos.get("context_json")
                if ctx_raw:
                    ctx = _j.loads(ctx_raw) if isinstance(ctx_raw, str) else ctx_raw
                    entry_perp = float(ctx.get("entry_perp_price", entry))
            except Exception:
                pass
            entry_basis = (entry_perp - entry) / entry if entry > 0 else 0
            basis_pnl = (basis - entry_basis) * size

        # Frais estimés
        fees_est = size * 0.0007 * 2  # 7bps × 2 jambes (entrée)

        # Synthèse
        net_pnl = spot_pnl if action != "carry" else basis_pnl  # carry = basis P&L
        status = "⚠️  PERTE" if net_pnl < -size * 0.05 else ("✅ OK" if net_pnl >= 0 else "⚡ SURVEILLER")

        logger.info(
            "%-4s %-10s %-6s entry=%-10s size=$%-5s spot=%-10s perp=%-10s "
            "spot_pnl=$%-7s basis_pnl=$%-7s net=$%-7s %s",
            trade_id[:4], symbol, action.upper(),
            f"${entry:,.2f}" if entry else "?",
            f"{size:,.0f}",
            f"${spot:,.2f}" if spot else "?",
            f"${perp:,.2f}" if perp else "?",
            f"{spot_pnl:+,.2f}",
            f"{basis_pnl:+,.2f}" if action == "carry" else "—",
            f"{net_pnl:+,.2f}",
            status,
        )

        if net_pnl < -size * 0.05:
            report["discrepancies"].append({
                "trade_id": trade_id, "symbol": symbol,
                "net_pnl": round(net_pnl, 2),
                "status": "LOSS > 5%",
            })
        else:
            report["ok_count"] += 1

    logger.info("")
    logger.info("═" * 60)
    logger.info("RÉSULTAT : %d OK, %d écarts détectés",
               report["ok_count"], len(report["discrepancies"]))

    if report["discrepancies"] and fix:
        logger.info("")
        logger.info("🔧 Mode --fix : fermeture des positions en écart...")
        for d in report["discrepancies"]:
            try:
                mkt_price = market.get(d["symbol"], {}).get("spot", 0)
                close_position(d["trade_id"], mkt_price, d["net_pnl"], "reconcile_fix")
                logger.info("  Fermé %s @ %.2f pnl=$%.2f", d["trade_id"], mkt_price, d["net_pnl"])
            except Exception as e:
                logger.error("  Échec fermeture %s: %s", d["trade_id"], e)

    return report


def main():
    parser = argparse.ArgumentParser(description="Réconciliation DB Atlas ↔ marché")
    parser.add_argument("--fix", action="store_true", help="Fermer les positions en écart")
    args = parser.parse_args()

    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║   V7.1 RECONCILIATION — DB Atlas ↔ CCXT Market          ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    logger.info("")

    report = reconcile_positions(fix=args.fix)

    if report.get("error"):
        logger.error("❌ %s", report["error"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
