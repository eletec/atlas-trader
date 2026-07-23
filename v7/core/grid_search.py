"""
v7/core/grid_search.py — Grid search des paramètres Funding Carry par backtest.

Teste des combinaisons de paramètres pour trouver le meilleur rendement ajusté au risque.

Usage:
    docker exec atlas-v4-api python -B /app/src/v7/core/grid_search.py --symbol ALL --days 365
    docker exec atlas-v4-api python -B /app/src/v7/core/grid_search.py --symbol BTC/USDT --days 365
"""

from __future__ import annotations

import argparse
import itertools
import logging
import sys
import time
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from v7.core.asset_config import get_active_assets, get_all_assets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("grid_search")

# Grille de paramètres à tester (18 combinaisons par actif × ~3s = ~1min/actif)
PARAM_GRID = {
    "min_funding":    [0.00001, 0.00005, 0.0001],   # 0.001%, 0.005%, 0.01%
    "max_hold_days":  [7, 14, 30],
    "fraction":       [0.30, 0.50],
}

# Métrique à optimiser : "sharpe", "pnl", "sortino", "calmar"
OBJECTIVE = "sharpe"


def run_backtest(symbol: str, days: int, capital: float, params: dict) -> dict:
    """Lance un backtest avec les parametres donnes (utilise backtest_v7_node.backtest_asset)."""
    from v7.backtest_v7_node import backtest_asset
    return backtest_asset(symbol, days, capital, params_override=params)


def grid_search_symbol(symbol: str, days: int, capital: float) -> dict:
    """Grid search pour un actif. Retourne les meilleurs params."""
    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    best_score = -999
    best_result = None
    results = []

    total_combos = 1
    for v in values:
        total_combos *= len(v)
    logger.info("%s: %d combinaisons...", symbol, total_combos)

    for combo in itertools.product(*values):
        params = dict(zip(keys, combo))
        r = run_backtest(symbol, days, capital, params)

        if "error" in r:
            continue

        score = r.get(OBJECTIVE, 0)
        results.append({"params": params, "score": score, "pnl": r["pnl"], "trades": r["trades"]})

        if score > best_score:
            best_score = score
            best_result = r

    # Trier par score décroissant
    results.sort(key=lambda x: x["score"], reverse=True)

    if best_result:
        logger.info("%s: best Sharpe=%.2f PnL=$%.2f trades=%d params=%s",
                    symbol, best_result["sharpe"], best_result["pnl"],
                    best_result["trades"], best_result.get("params", {}))
    else:
        logger.warning("%s: aucun résultat valide", symbol)

    return {
        "symbol": symbol,
        "best": best_result,
        "top5": results[:5],
        "total_tested": len(results),
    }


def main():
    parser = argparse.ArgumentParser(description="Grid search Funding Carry params")
    parser.add_argument("--symbol", default="ALL", help="Symbole ou ALL/ACTIVE")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--capital", type=float, default=2000)
    parser.add_argument("--output", default="/app/data/grid_search_results.yaml")
    args = parser.parse_args()

    if args.symbol == "ALL":
        symbols = get_all_assets()
    elif args.symbol == "ACTIVE":
        symbols = get_active_assets()
    else:
        symbols = [args.symbol]

    logger.info("Grid search: %d actifs, %d jours, $%.0f/asset", len(symbols), args.days, args.capital)

    all_results = {}
    t0 = time.time()

    for sym in symbols:
        r = grid_search_symbol(sym, args.days, args.capital)
        all_results[sym] = r

    elapsed = time.time() - t0

    # Sauvegarder
    with open(args.output, "w") as f:
        yaml.dump(all_results, f, allow_unicode=True, default_flow_style=False)

    # Résumé
    print(f"\n{'='*80}")
    print(f"Grid search terminé — {len(symbols)} actifs — {elapsed:.0f}s")
    print(f"Résultats : {args.output}")
    for sym, r in all_results.items():
        best = r.get("best")
        if best and "error" not in best:
            p = best.get("params", {})
            print(f"  {sym:<12} Sharpe={best['sharpe']:>6.2f} PnL=${best['pnl']:>8.2f} "
                  f"Trades={best['trades']:>2d} Params={p}")


if __name__ == "__main__":
    main()
