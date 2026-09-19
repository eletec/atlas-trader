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

from v7.core.asset_config import get_active_assets, get_all_assets, normalize_symbol

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("grid_search")

# Grille de paramètres — Pass 1 (coarse) + Pass 2 (fine autour du meilleur)
# NOTE (GPT audit, 25/07/2026): economic_hurdle n'est PAS optimisé — c'est un calcul
# de coût du capital (SOFR + primes), pas un paramètre de trading. Le grid search
# optimise uniquement les paramètres qui relèvent de la stratégie.
COARSE_GRID = {
    "min_funding":    [0.0001, 0.0002, 0.0003, 0.0005],  # 0.01% → 0.05%/8h (11% → 55%/an)
    "max_hold_days":  [30, 45, 60],                   # aligné avec les zones (DERISK/CLOSE)
    "fraction":       [0.30, 0.50],
    # economic_hurdle n'est plus dans la grille — fixé à 0.05 (coût du capital)
}

def refine_grid(best_params: dict) -> dict[str, list]:
    """Genere une grille fine autour des meilleurs parametres."""
    mf = best_params.get("min_funding", 0.00005)
    hold = best_params.get("max_hold_days", 30)
    frac = best_params.get("fraction", 0.50)
    
    return {
        "min_funding":    sorted(set([max(0.00005, mf * 0.5), mf, min(0.001, mf * 2)])),
        "max_hold_days":  sorted(set([max(7, hold - 10), hold, min(90, hold + 15)])),
        "fraction":       sorted(set([max(0.10, round(frac - 0.15, 2)), frac, min(1.0, round(frac + 0.15, 2))])),
        # economic_hurdle retiré — n'est pas un paramètre à optimiser
    }

# Métrique à optimiser : "sharpe", "pnl", "sortino", "calmar"
OBJECTIVE = "sharpe"


def run_backtest(symbol: str, days: int, capital: float, params: dict) -> dict:
    """Lance un backtest avec les parametres donnes (utilise backtest_v7_node.backtest_asset)."""
    from v7.backtest_v7_node import backtest_asset
    return backtest_asset(symbol, days, capital, params_override=params)


def grid_search_symbol(symbol: str, days: int, capital: float, passes: int = 2) -> dict:
    """Grid search en entonnoir (coarse → fine) pour un actif."""
    grid = COARSE_GRID
    best_result = None
    all_results = []

    for pn in range(1, passes + 1):
        keys = list(grid.keys())
        values = list(grid.values())
        total_combos = 1
        for v in values:
            total_combos *= len(v)
        logger.info("%s pass %d/%d: %d combos...", symbol, pn, passes, total_combos)

        best_score = -999.0
        pass_best = None

        for combo in itertools.product(*values):
            params = dict(zip(keys, combo))
            r = run_backtest(symbol, days, capital, params)

            if "error" in r:
                continue

            score = r.get(OBJECTIVE, 0)
            pnl = r.get("pnl", 0)
            all_results.append({"pass": pn, "params": params, "score": score, "pnl": pnl, "trades": r["trades"]})

            best_pnl = pass_best.get("pnl", -999) if pass_best else -999
            if score > best_score or (score == best_score and pnl > best_pnl):
                best_score = score
                pass_best = r
                r["params"] = params  # injecter les params dans le resultat

        if pass_best:
            logger.info("%s pass %d: best Sharpe=%.2f PnL=$%.2f trades=%d params=%s",
                        symbol, pn, pass_best.get("sharpe", 0), pass_best.get("pnl", 0),
                        pass_best.get("trades", 0), pass_best.get("params", {}))
            best_result = pass_best
            # Raffiner la grille pour le prochain passage
            if pn < passes:
                grid = refine_grid(pass_best.get("params", {}))
        else:
            logger.warning("%s pass %d: aucun resultat", symbol, pn)
            break

    # Dedup + tri
    seen = set()
    unique = []
    for r in all_results:
        key = str(r["params"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    unique.sort(key=lambda x: (x["score"], x["pnl"]), reverse=True)

    return {
        "symbol": symbol,
        "best": best_result,
        "top5": unique[:5],
        "total_tested": len(all_results),
        "passes": passes,
    }


def main():
    parser = argparse.ArgumentParser(description="Grid search Funding Carry params")
    parser.add_argument("--symbol", default="ALL",
                        help="Symbole (BTC, BTC/USDT, BTC,ETH) ou ALL/ACTIVE")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--capital", type=float, default=2000)
    parser.add_argument("--passes", type=int, default=2, help="Nombre de passes (1=coarse, 2=coarse+fine)")
    parser.add_argument("--output", default="/app/data/grid_search_results.yaml")
    args = parser.parse_args()

    if args.symbol == "ALL":
        symbols = get_all_assets()
    elif args.symbol == "ACTIVE":
        symbols = get_active_assets()
    else:
        symbols = [normalize_symbol(s) for s in args.symbol.split(",") if s.strip()]

    logger.info("Grid search: %d actifs, %d jours, $%.0f/asset", len(symbols), args.days, args.capital)

    all_results = {}
    t0 = time.time()

    for sym in symbols:
        r = grid_search_symbol(sym, args.days, args.capital, passes=args.passes)
        all_results[sym] = r

    elapsed = time.time() - t0

    # Sauvegarder
    with open(args.output, "w") as f:
        yaml.dump(all_results, f, allow_unicode=True, default_flow_style=False)

    # Résumé
    print(f"\n{'='*80}")
    print(f"Grid search termine — {len(symbols)} actifs, {args.passes} passes — {elapsed:.0f}s")
    print(f"Résultats : {args.output}")
    for sym, r in all_results.items():
        best = r.get("best")
        if best and "error" not in best:
            p = best.get("params", {})
            print(f"  {sym:<12} Sharpe={best['sharpe']:>6.2f} PnL=${best['pnl']:>8.2f} "
                  f"Trades={best['trades']:>2d} Params={p}")


if __name__ == "__main__":
    main()
