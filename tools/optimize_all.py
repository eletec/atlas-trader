#!/usr/bin/env python
"""
tools/optimize_all.py — Optimiseur automatique multi-actif, multi-horizon.

Teste des combinaisons de paramètres sur tous les symboles, sur 60j et max j.
Produit un CSV de synthèse + les meilleurs profils par actif.

Usage :
    docker exec atlas-v4-api python tools/optimize_all.py

Output :
    storage/optimize_results.csv     — toutes les combinaisons testées
    config/asset_profiles.yaml       — mis à jour avec les meilleurs profils
"""
from __future__ import annotations

import csv
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("optimize_all")

# Ajouter le workspace au PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.backtest_v4 import run_backtest_v4

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
HORIZONS = [60, 180]  # jours

# Grille de paramètres à tester
PARAM_GRID = [
    # (p_up, p_dn, fusion_th, sl_mult, tp_mult, exit_strat, exit_atr, min_dist)
    (0.55, 0.45, 0.15, 2.0, 4.0, "chandelier", 3.0, 0.5),
    (0.52, 0.48, 0.15, 2.5, 5.0, "chandelier", 3.5, 1.0),
    (0.52, 0.48, 0.15, 3.0, 6.0, "trailing",   4.0, 0.5),
    (0.51, 0.49, 0.10, 2.5, 5.0, "trailing",   3.5, 0.5),
    (0.55, 0.45, 0.30, 2.0, 4.0, "chandelier", 3.0, 0.5),
    (0.52, 0.48, 0.30, 3.0, 6.0, "trailing",   4.0, 0.5),
    (0.51, 0.49, 0.30, 2.0, 4.0, "chandelier", 3.0, 0.5),
    (0.51, 0.49, 0.10, 3.0, 6.0, "trailing",   4.0, 1.0),
]


def score(r) -> float:
    """Score composite : Sharpe × (1 - maxDD) × log(1 + n_trades)."""
    import math
    if r.n_trades == 0:
        return -999
    dd_penalty = max(0, 1 - r.max_drawdown_pct / 100.0)
    freq_bonus = math.log(1 + r.n_trades)
    return r.sharpe * dd_penalty * freq_bonus


def main():
    out_path = Path("/app/data/optimize_results.csv") if os.path.exists("/app/data") else Path("storage/optimize_results.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    all_results = []
    start_time = time.time()

    for symbol in SYMBOLS:
        for days in HORIZONS:
            logger.info("=" * 60)
            logger.info("%s — %dj", symbol, days)
            for p_up, p_dn, fth, sl, tp, estrat, exit_atr, min_dist in PARAM_GRID:
                try:
                    r = run_backtest_v4(
                        symbol=symbol, days=days, capital=10_000,
                        risk_pct=1.0, sl_mult=sl, tp_mult=tp, fraction=0.02,
                        exit_strategy=estrat, exit_atr_mult=exit_atr, min_atr_dist=min_dist,
                        gate_mode="fusion", fusion_threshold=fth,
                        p_up_threshold=p_up, p_dn_threshold=p_dn,
                    )
                    s = score(r)
                    row = {
                        "symbol": symbol, "days": days,
                        "p_up": p_up, "p_dn": p_dn, "fusion_th": fth,
                        "sl_mult": sl, "tp_mult": tp,
                        "exit_strat": estrat, "exit_atr": exit_atr, "min_dist": min_dist,
                        "pnl": round(r.total_pnl, 2), "pnl_pct": round(r.total_pnl_pct, 2),
                        "win_rate": round(r.win_rate, 1), "sharpe": round(r.sharpe, 2),
                        "max_dd": round(r.max_drawdown_pct, 2), "n_trades": r.n_trades,
                        "score": round(s, 2),
                    }
                    all_results.append(row)
                    logger.info(
                        "  %s sl=%.1f tp=%.1f %s atr=%.1f → %d trades sharpe=%.2f pnl=$%.0f score=%.2f",
                        estrat, sl, tp, estrat, exit_atr, r.n_trades, r.sharpe, r.total_pnl, s,
                    )
                except Exception as e:
                    logger.warning("  SKIP %s %dj: %s", symbol, days, e)

    # ── Sauvegarde CSV ──
    all_results.sort(key=lambda x: x["score"], reverse=True)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=all_results[0].keys())
        w.writeheader()
        w.writerows(all_results)
    logger.info("Résultats sauvegardés: %s (%d lignes)", out_path, len(all_results))

    # ── Meilleur profil par actif (60j) ──
    logger.info("\n" + "=" * 60)
    logger.info("MEILLEURS PROFILS PAR ACTIF (60j)")
    for symbol in SYMBOLS:
        best = [r for r in all_results if r["symbol"] == symbol and r["days"] == 60]
        if not best:
            continue
        best.sort(key=lambda x: x["score"], reverse=True)
        b = best[0]
        logger.info(
            "  %s: p_up=%.2f p_dn=%.2f fusion=%.2f SL=%.1f TP=%.1f %s atr=%.1f "
            "→ %d trades sharpe=%.2f pnl=$%.0f",
            symbol, b["p_up"], b["p_dn"], b["fusion_th"],
            b["sl_mult"], b["tp_mult"], b["exit_strat"], b["exit_atr"],
            b["n_trades"], b["sharpe"], b["pnl"],
        )

    elapsed = time.time() - start_time
    logger.info("Optimisation terminée en %.0f min", elapsed / 60)


if __name__ == "__main__":
    main()
