#!/usr/bin/env python
"""
tools/optimize_v5.py — Optimiseur V5 MetaGate multi-actif.

Teste des combinaisons de paramètres sur tous les actifs avec gate_mode="meta".
Produit les meilleurs profils par actif et met à jour asset_profiles.yaml.

Usage :
    docker exec atlas-v4-api python src/tools/optimize_v5.py
    docker exec atlas-v4-api python src/tools/optimize_v5.py --asset BTC/USDT --days 60

Output :
    /app/data/optimize_v5_results.csv  — toutes les combinaisons testées
    config/asset_profiles.yaml         — mis à jour avec les meilleurs profils
"""
from __future__ import annotations

import csv
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("optimize_v5")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.backtest_v4 import run_backtest_v4

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
DAYS = 180

# ── Grille V5 MetaGate ──
# (meta_threshold, sl_mult, tp_mult, exit_strat, exit_atr, min_dist, fraction)
PARAM_GRID = [
    # ── Seuil 0.10 (permissif) ──
    (0.10, 2.0, 4.0, "chandelier", 3.0, 0.5, 0.03),
    (0.10, 3.0, 6.0, "trailing",   4.0, 1.0, 0.04),
    (0.10, 2.5, 5.0, "chandelier", 3.5, 0.5, 0.05),
    # ── Seuil 0.15 ──
    (0.15, 2.0, 4.0, "chandelier", 3.0, 0.5, 0.03),
    (0.15, 2.5, 5.0, "chandelier", 3.5, 1.0, 0.05),
    (0.15, 3.0, 6.0, "trailing",   4.0, 1.0, 0.04),
    (0.15, 2.0, 4.0, "chandelier", 3.0, 1.5, 0.05),
    # ── Seuil 0.20 ──
    (0.20, 2.0, 4.0, "chandelier", 3.0, 0.5, 0.03),
    (0.20, 2.5, 5.0, "chandelier", 3.5, 1.0, 0.05),
    (0.20, 3.0, 6.0, "trailing",   4.0, 1.0, 0.04),
    (0.20, 2.0, 4.0, "chandelier", 3.0, 1.5, 0.05),
    # ── Seuil 0.25 ──
    (0.25, 2.0, 4.0, "chandelier", 3.0, 0.5, 0.03),
    (0.25, 2.5, 5.0, "chandelier", 3.5, 1.0, 0.05),
    (0.25, 3.0, 6.0, "trailing",   4.0, 1.0, 0.04),
    # ── Seuil 0.30 (conservateur) ──
    (0.30, 2.0, 4.0, "chandelier", 3.0, 0.5, 0.03),
    (0.30, 2.5, 5.0, "chandelier", 3.5, 1.0, 0.05),
    (0.30, 3.0, 6.0, "trailing",   4.0, 1.5, 0.04),
]


def score(r) -> float:
    """Score composite : Sharpe × (1 - maxDD) × log(1 + n_trades)."""
    import math
    if r.n_trades == 0:
        return -999
    dd_penalty = max(0, 1 - r.max_drawdown_pct / 100.0)
    freq_bonus = math.log(1 + r.n_trades)
    return r.sharpe * dd_penalty * freq_bonus


def optimize_symbol(symbol: str, days: int) -> list[dict]:
    """Teste toutes les combinaisons pour un symbole donné."""
    results = []
    pfx = symbol.split("/")[0].lower()[:3]
    logger.info("=== Optimizing %s (%d days, %d combos) ===", symbol, days, len(PARAM_GRID))

    for meta_th, sl, tp, estrat, eatr, mdist, frac in PARAM_GRID:
        try:
            r = run_backtest_v4(
                symbol=symbol,
                days=days,
                capital=10_000,
                risk_pct=1.0,
                sl_mult=sl,
                tp_mult=tp,
                fraction=frac,
                exit_strategy=estrat,
                exit_atr_mult=eatr,
                min_atr_dist=mdist,
                gate_mode="meta",
                fusion_threshold=meta_th,
                p_up_threshold=0.52,
                p_dn_threshold=0.48,
            )
            s = score(r)
            results.append({
                "symbol": symbol,
                "meta_th": meta_th,
                "sl_mult": sl,
                "tp_mult": tp,
                "fraction": frac,
                "exit_strat": estrat,
                "exit_atr": eatr,
                "min_dist": mdist,
                "pnl": round(r.total_pnl, 2),
                "pnl_pct": round(r.total_pnl_pct, 2),
                "win_rate": round(r.win_rate, 1),
                "sharpe": round(r.sharpe, 2),
                "max_dd": round(r.max_drawdown_pct, 2),
                "n_trades": r.n_trades,
                "score": round(s, 2),
            })
            logger.info("  th=%.2f sl=%.1f tp=%.1f %s → PnL=$%.0f Sharpe=%.2f DD=%.1f%% trades=%d score=%.2f",
                        meta_th, sl, tp, estrat, r.total_pnl, r.sharpe,
                        r.max_drawdown_pct, r.n_trades, s)
        except Exception as e:
            logger.warning("  SKIP th=%.2f sl=%.1f: %s", meta_th, sl, e)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def update_profiles(best_per_symbol: dict[str, dict]):
    """Met à jour asset_profiles.yaml avec les meilleurs paramètres."""
    try:
        import yaml

        profile_path = Path(os.environ.get("ASSET_PROFILES_PATH",
                           "/app/src/config/asset_profiles.yaml"))
        if not profile_path.parent.exists():
            profile_path = Path(__file__).resolve().parent.parent / "config" / "asset_profiles.yaml"

        # Charger existant
        existing = {}
        if profile_path.exists():
            with open(profile_path) as fh:
                existing = yaml.safe_load(fh) or {}

        # Mettre à jour
        for symbol, cfg in best_per_symbol.items():
            existing[symbol] = {
                **(existing.get(symbol, {})),
                "p_up": 0.52,
                "p_dn": 0.48,
                "fusion_th": cfg["meta_th"],
                "sl_mult": cfg["sl_mult"],
                "tp_mult": cfg["tp_mult"],
                "fraction": cfg["fraction"],
                "exit_strat": cfg["exit_strat"],
                "exit_atr": cfg["exit_atr"],
                "max_pos": existing.get(symbol, {}).get("max_pos", 3),
            }

        with open(profile_path, "w") as fh:
            yaml.safe_dump(existing, fh, allow_unicode=True, default_flow_style=False)
        logger.info("Profiles updated: %s", profile_path)
    except Exception as e:
        logger.warning("Could not update profiles: %s", e)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="V5 MetaGate optimizer")
    parser.add_argument("--asset", type=str, default=None)
    parser.add_argument("--days", type=int, default=DAYS)
    parser.add_argument("--no-save", action="store_true", help="Don't update profiles")
    args = parser.parse_args()

    symbols = [args.asset] if args.asset else SYMBOLS
    days = args.days

    out_path = Path("/app/data/optimize_v5_results.csv") if Path("/app/data").exists() else Path("storage/optimize_v5_results.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    all_results = []
    best_per_symbol = {}
    start = time.time()

    for symbol in symbols:
        results = optimize_symbol(symbol, days)
        all_results.extend(results)

        if results:
            best = results[0]
            best_per_symbol[symbol] = best
            logger.info("BEST %s: th=%.2f sl=%.1f tp=%.1f %s → PnL=$%.0f Sharpe=%.2f trades=%d",
                        symbol, best["meta_th"], best["sl_mult"], best["tp_mult"],
                        best["exit_strat"], best["pnl"], best["sharpe"], best["n_trades"])

    # ── Sauvegarde CSV ──
    if all_results:
        with open(out_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=all_results[0].keys())
            writer.writeheader()
            writer.writerows(all_results)
        logger.info("Results saved: %s (%d rows)", out_path, len(all_results))

    # ── Mise à jour asset_profiles.yaml ──
    if best_per_symbol and not args.no_save:
        update_profiles(best_per_symbol)

    # ── Synthèse ──
    elapsed = time.time() - start
    print("\n" + "=" * 90)
    print(f"Optimisation V5 terminée — {len(symbols)} actifs, {len(all_results)} combos, {elapsed:.0f}s")
    print("=" * 90)
    print(f"{'Symbol':<12} {'Th':>6} {'SL':>5} {'TP':>5} {'Exit':>12} {'ATR':>5} {'Frac':>6} {'PnL':>10} {'Sharpe':>8} {'DD':>7} {'Trades':>7}")
    print("-" * 90)
    for symbol, best in sorted(best_per_symbol.items()):
        print(f"{symbol:<12} {best['meta_th']:>6.2f} {best['sl_mult']:>5.1f} {best['tp_mult']:>5.1f} "
              f"{best['exit_strat']:>12} {best['exit_atr']:>5.1f} {best['fraction']:>6.2f} "
              f"${best['pnl']:>9.0f} {best['sharpe']:>8.2f} {best['max_dd']:>6.1f}% {best['n_trades']:>7}")
    print("=" * 90)


if __name__ == "__main__":
    main()
