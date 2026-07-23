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
    """Lance un backtest rapide avec les paramètres donnés."""
    from v7.nodes.funding_carry_node import FundingCarryNode
    from v7.backtest_v7_node import fetch_prices, fetch_funding_history
    import pandas as pd

    # Fetch données
    spot_df = fetch_prices(symbol, days, is_perp=False)
    perp_df = fetch_prices(symbol, days, is_perp=True)
    funding_df = fetch_funding_history(symbol, days)

    if spot_df.empty or funding_df.empty:
        return {"error": "no data"}

    # Merge
    if not perp_df.empty:
        combined = funding_df.join(spot_df.rename(columns={"spot_price": "spot_raw"}), how="left")
        combined = combined.join(perp_df.rename(columns={"perp_price": "perp_raw"}), how="left")
        combined["spot_price"] = combined["spot_raw"].ffill().fillna(1000)
        combined["perp_price"] = combined["perp_raw"].ffill().fillna(combined["spot_price"])
    else:
        combined = funding_df.copy()
        combined["spot_price"] = 1000.0
        combined["perp_price"] = 1000.0

    if combined.empty:
        return {"error": "no merged data"}

    # Ajuster perp pour contrats à multiplicateur
    base = symbol.split("/")[0]
    MULT = {"PEPE": 1000, "SHIB": 1000, "BONK": 1000, "FLOKI": 1000, "LUNC": 1000}
    contract_mult = MULT.get(base, 1)

    node = FundingCarryNode(
        node_id=f"gs_{symbol.split('/')[0].lower()}",
        symbol=symbol,
        capital=capital,
        fraction=params.get("fraction", 0.50),
        min_funding=params.get("min_funding", 0.00005),
        max_funding=0.003,
        exit_after_hours=72,
        max_hold_days=params.get("max_hold_days", 14),
        stop_loss_pct=-0.05,
        params={"_backtest": True},
    )

    trades = []
    total_funding = 0.0
    total_fees = 0.0
    nav_history = []
    prev_nav = capital

    for ts, row in combined.iterrows():
        fr = float(row["funding_rate"])
        spot_price = float(row["spot_price"])
        perp_price = float(row["perp_price"]) / contract_mult

        result = node.run({
            "symbol": symbol,
            "spot_price": spot_price,
            "funding_rate": fr,
            "perp_price": perp_price,
        })

        signal = result.get("signal", "flat")
        size_usd = result.get("size_usd", 0)
        total_funding = max(total_funding, result.get("total_funding_received", 0) or 0)
        position_open = result.get("position_open", False)

        cost_this_step = 0.0
        if signal == "open_carry" and size_usd > 0:
            cost_this_step = size_usd * 0.0012
            total_fees += cost_this_step

        if signal in ("open_carry", "close_carry") and size_usd > 0:
            trades.append({"date": str(ts), "signal": signal, "size": size_usd,
                           "funding": fr, "cost": cost_this_step})

        staking_daily = prev_nav * (0.05 / 365)
        nav = prev_nav + staking_daily
        if signal == "open_carry" and size_usd > 0:
            pass
        elif signal == "close_carry":
            realized = result.get("realized_pnl", 0) or 0
            nav += realized - cost_this_step

        funding_earned = total_funding
        nav = capital + funding_earned - total_fees + staking_daily * len(nav_history)
        nav_history.append((ts, nav))
        prev_nav = nav

    staking = node.state.staking_earned if hasattr(node, 'state') else 0
    total_pnl = total_funding + (staking or 0) - total_fees

    # Métriques
    if len(nav_history) > 2 and len(trades) > 0:
        nav_df = pd.DataFrame(nav_history, columns=["ts", "nav"]).set_index("ts")
        nav_df["return"] = nav_df["nav"].pct_change().fillna(0)
        nav_returns = nav_df["return"].dropna()
        if len(nav_returns) > 10 and nav_returns.std() > 0:
            sharpe = float(nav_returns.mean() / nav_returns.std() * np.sqrt(365 * 3))
        else:
            sharpe = 0.0
        nav_df["peak"] = nav_df["nav"].cummax()
        nav_df["dd"] = (nav_df["nav"] - nav_df["peak"]) / nav_df["peak"] * 100
        max_dd = float(nav_df["dd"].min())
    else:
        sharpe = 0.0
        max_dd = 0.0

    return {
        "symbol": symbol, "trades": len(trades), "pnl": round(total_pnl, 2),
        "sharpe": round(sharpe, 2), "max_dd": round(max_dd, 2),
        "funding": round(total_funding, 4), "fees": round(total_fees, 2),
        "params": params,
    }


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
