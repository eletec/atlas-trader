#!/usr/bin/env python3
"""
run_grid_search.py — Recherche exhaustive des paramètres optimaux.

Teste des combinaisons de paramètres clés et affiche un classement
par profit factor décroissant. Résultats sauvegardés dans grid_results.csv.

Usage (sur GX10) :
    docker exec atlas-trader-gx10 python3 /app/run_grid_search.py
    docker exec atlas-trader-gx10 python3 /app/run_grid_search.py --symbol BTC/USDT --quick
    docker exec atlas-trader-gx10 python3 /app/run_grid_search.py --top 30

Notes :
- Cache OHLCV par (symbol, days, tf) — fetch une seule fois par combinaison unique.
- Résultats écrits progressivement dans /app/grid_results.csv.
- Interruptible (Ctrl+C) : les résultats déjà calculés sont sauvegardés.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.WARNING,  # silencer le pipeline pour ne voir que les résultats
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("grid_search")
logging.getLogger("zeitgeist.quant.pipeline").setLevel(logging.WARNING)
logging.getLogger("quant.backtest").setLevel(logging.WARNING)
logging.getLogger("backtest.runner").setLevel(logging.WARNING)

# ── Grille de paramètres ──────────────────────────────────────────────────

# Grille complète (~200 combinaisons)
GRID_FULL: dict[str, list] = {
    "days":        [60, 90, 120, 180],
    "train_frac":  [0.30, 0.40, 0.50, 0.60],
    "horizon":     [1, 2, 4, 8],
    "sl_mult":     [1.0, 1.5, 2.0, 2.5],
    "tp_mult":     [1.5, 2.0, 2.5, 3.5],   # filtré: tp > sl obligatoire
    "p_up":        [0.52, 0.54, 0.56],
    "p_dn":        [0.44, 0.46, 0.48],
}

# Grille rapide (~60 combinaisons, 10 min sur GX10)
GRID_QUICK: dict[str, list] = {
    "days":        [60, 90, 120],
    "train_frac":  [0.30, 0.50],
    "horizon":     [1, 4, 8],
    "sl_mult":     [1.0, 1.5, 2.5],
    "tp_mult":     [1.5, 2.0, 3.5],
    "p_up":        [0.52, 0.54],
    "p_dn":        [0.46, 0.48],
}

CSV_COLUMNS = [
    "symbol", "days", "train_frac", "horizon", "sl_mult", "tp_mult",
    "p_up", "p_dn", "n_trades", "n_long", "n_short",
    "win_rate", "pf", "pnl", "sharpe", "max_dd", "elapsed_s",
]


@dataclass
class RunResult:
    symbol: str
    days: int
    train_frac: float
    horizon: int
    sl_mult: float
    tp_mult: float
    p_up: float
    p_dn: float
    n_trades: int
    n_long: int
    n_short: int
    win_rate: float
    pf: float
    pnl: float
    sharpe: float
    max_dd: float
    elapsed_s: float


def _build_combinations(grid: dict[str, list]) -> list[dict]:
    """Génère toutes les combinaisons valides (tp_mult > sl_mult)."""
    keys = list(grid.keys())
    combos = []
    for vals in itertools.product(*[grid[k] for k in keys]):
        params = dict(zip(keys, vals))
        # Filtre : TP doit être > SL (R:R > 1.0 requis sinon espérance négative)
        if params["tp_mult"] <= params["sl_mult"]:
            continue
        # Filtre : p_up > p_dn (logique)
        if params["p_up"] <= params["p_dn"]:
            continue
        combos.append(params)
    return combos


def _run_one(
    symbol: str,
    ohlcv_df: "pd.DataFrame",
    params: dict,
) -> RunResult | None:
    """Exécute le pipeline V2 pour un jeu de paramètres donné."""
    import numpy as np
    import pandas as pd
    import quant.config as _qcfg_mod
    from quant.config import get_quant_cfg
    from quant.pipeline import PipelineConfig, run_pipeline

    t0 = time.perf_counter()

    # ── Même traitement que sim_engine.py : timestamp → DatetimeIndex ────
    ohlcv = ohlcv_df.copy()
    if "timestamp" in ohlcv.columns and not isinstance(ohlcv.index, pd.DatetimeIndex):
        ohlcv = ohlcv.set_index(pd.DatetimeIndex(ohlcv["timestamp"]))
    elif not isinstance(ohlcv.index, pd.DatetimeIndex):
        logger.warning("OHLCV sans DatetimeIndex — ignoré")
        return None

    # Override QuantConfig
    qcfg = get_quant_cfg(reload=True)
    qcfg.horizon_bars         = params["horizon"]
    qcfg.stop_loss_atr_mult   = params["sl_mult"]
    qcfg.take_profit_atr_mult = params["tp_mult"]
    qcfg.p_up_threshold       = params["p_up"]
    qcfg.p_dn_threshold       = params["p_dn"]
    qcfg.walk_fwd_every       = 0   # désactivé dans la grille
    qcfg.use_barrier_label    = False
    _qcfg_mod._CACHE = qcfg

    n_total = len(ohlcv)
    split   = int(n_total * params["train_frac"])
    train_idx = ohlcv.index[:split]
    test_idx  = ohlcv.index[split:]

    if len(train_idx) < 200 or len(test_idx) < 50:
        return None

    cfg = PipelineConfig()
    cfg.p_up_threshold = params["p_up"]
    cfg.p_dn_threshold = params["p_dn"]
    cfg.horizon_bars   = params["horizon"]

    try:
        arts = run_pipeline(ohlcv, train_idx, test_idx, cfg)
    except Exception as exc:
        logger.debug(f"run_pipeline échec: {exc}")
        return None

    bt = arts.backtest
    trades = bt.trades
    if not trades:
        return None

    n_long  = sum(1 for t in trades if t.side == "long")
    n_short = sum(1 for t in trades if t.side == "short")
    elapsed = time.perf_counter() - t0

    return RunResult(
        symbol=symbol,
        days=params["days"],
        train_frac=params["train_frac"],
        horizon=params["horizon"],
        sl_mult=params["sl_mult"],
        tp_mult=params["tp_mult"],
        p_up=params["p_up"],
        p_dn=params["p_dn"],
        n_trades=len(trades),
        n_long=n_long,
        n_short=n_short,
        win_rate=bt.metrics.get("win_rate", 0.0),
        pf=bt.metrics.get("profit_factor", 0.0),
        pnl=bt.metrics.get("total_return", 0.0) * 10_000,
        sharpe=bt.metrics.get("sharpe", 0.0),
        max_dd=bt.metrics.get("max_dd", 0.0),
        elapsed_s=elapsed,
    )


def _fetch_ohlcv_cached(
    symbol: str,
    timeframe: str,
    days: int,
    cache: dict,
    force: bool = False,
) -> "pd.DataFrame | None":
    key = (symbol, timeframe, days)
    if key in cache and not force:
        return cache[key]

    from backtest.data_fetcher import fetch_ohlcv
    try:
        df = fetch_ohlcv(symbol, timeframe=timeframe, days=days, force_refresh=False)
        if df.empty:
            return None
        cache[key] = df
        return df
    except Exception as exc:
        logger.warning(f"fetch_ohlcv {symbol} {days}j {timeframe}: {exc}")
        return None


def _print_top(results: list[RunResult], top: int = 20) -> None:
    sorted_r = sorted(results, key=lambda r: r.pf, reverse=True)[:top]
    print(f"\n{'='*110}")
    print(f"TOP {top} CONFIGURATIONS PAR PROFIT FACTOR")
    print(f"{'='*110}")
    header = (
        f"{'#':>3} {'SYM':<10} {'days':>5} {'tr%':>4} {'h':>3} "
        f"{'SL':>4} {'TP':>4} {'p_up':>5} {'p_dn':>5} "
        f"{'N':>5} {'L':>4} {'S':>4} {'Win%':>6} {'PF':>6} "
        f"{'P&L$':>9} {'Sharpe':>7}"
    )
    print(header)
    print("-" * 110)
    for i, r in enumerate(sorted_r, 1):
        pnl_s = f"{r.pnl:+.0f}"
        flag = " ✓" if r.pf > 1.0 else ""
        print(
            f"{i:>3} {r.symbol:<10} {r.days:>5} {r.train_frac*100:>3.0f}% {r.horizon:>3} "
            f"{r.sl_mult:>4.1f} {r.tp_mult:>4.1f} {r.p_up:>5.2f} {r.p_dn:>5.2f} "
            f"{r.n_trades:>5} {r.n_long:>4} {r.n_short:>4} {r.win_rate*100:>5.1f}% {r.pf:>6.3f} "
            f"{pnl_s:>9} {r.sharpe:>7.2f}{flag}"
        )
    print("=" * 110)
    positive = [r for r in results if r.pf > 1.0]
    print(f"\nConfigs PF>1.0 : {len(positive)} / {len(results)}")
    if positive:
        best = max(positive, key=lambda r: r.pf)
        print(f"Meilleure config : {best}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Grid search paramétrique Atlas Trader V2")
    parser.add_argument("--symbol", default="BTC/USDT", help="Symbole à tester (défaut: BTC/USDT)")
    parser.add_argument("--symbols", nargs="+", default=None, help="Plusieurs symboles (override --symbol)")
    parser.add_argument("--timeframe", default="1h", help="Timeframe (défaut: 1h)")
    parser.add_argument("--quick", action="store_true", help="Grille réduite (~60 combos, ~10 min)")
    parser.add_argument("--top", type=int, default=25, help="Afficher les N meilleures configs (défaut: 25)")
    parser.add_argument("--output", default="/app/grid_results.csv", help="Fichier CSV de sortie")
    parser.add_argument("--min-trades", type=int, default=30, help="Ignorer configs avec < N trades")
    args = parser.parse_args()

    symbols = args.symbols or [args.symbol]
    grid = GRID_QUICK if args.quick else GRID_FULL
    combos = _build_combinations(grid)

    print(f"Grid search — {len(symbols)} symbole(s) × {len(combos)} combinaisons = {len(symbols)*len(combos)} runs")
    print(f"Timeframe: {args.timeframe} | Grille: {'QUICK' if args.quick else 'FULL'}")
    print(f"Résultats → {args.output}\n")

    results: list[RunResult] = []
    ohlcv_cache: dict = {}
    total_runs = len(symbols) * len(combos)
    done = 0

    output_path = Path(args.output)
    csv_file = output_path.open("w", newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
    writer.writeheader()

    try:
        for symbol in symbols:
            for params in combos:
                done += 1
                ohlcv = _fetch_ohlcv_cached(symbol, args.timeframe, params["days"], ohlcv_cache)
                if ohlcv is None:
                    print(f"[{done}/{total_runs}] SKIP {symbol} {params['days']}j — pas de données")
                    continue

                result = _run_one(symbol, ohlcv, params)

                if result is None or result.n_trades < args.min_trades:
                    pf_str = "—"
                    status = "skip"
                else:
                    results.append(result)
                    pf_str = f"{result.pf:.3f}"
                    status = "✓" if result.pf > 1.0 else " "
                    writer.writerow({
                        "symbol":     result.symbol,
                        "days":       result.days,
                        "train_frac": result.train_frac,
                        "horizon":    result.horizon,
                        "sl_mult":    result.sl_mult,
                        "tp_mult":    result.tp_mult,
                        "p_up":       result.p_up,
                        "p_dn":       result.p_dn,
                        "n_trades":   result.n_trades,
                        "n_long":     result.n_long,
                        "n_short":    result.n_short,
                        "win_rate":   f"{result.win_rate:.4f}",
                        "pf":         f"{result.pf:.4f}",
                        "pnl":        f"{result.pnl:.2f}",
                        "sharpe":     f"{result.sharpe:.4f}",
                        "max_dd":     f"{result.max_dd:.4f}",
                        "elapsed_s":  f"{result.elapsed_s:.2f}",
                    })
                    csv_file.flush()

                pct = done / total_runs * 100
                bar_len = 30
                filled = int(bar_len * done // total_runs)
                bar = "█" * filled + "░" * (bar_len - filled)
                eta_s = ""
                if results:
                    avg_t = sum(r.elapsed_s for r in results) / len(results)
                    rem = (total_runs - done) * avg_t
                    eta_s = f" ETA {rem/60:.0f}min"

                print(
                    f"\r[{bar}] {pct:5.1f}% {done}/{total_runs} | "
                    f"{symbol} d={params['days']} tf={params['train_frac']:.0%} "
                    f"h={params['horizon']} sl={params['sl_mult']} tp={params['tp_mult']} "
                    f"→ PF={pf_str} {status}{eta_s}",
                    end="", flush=True,
                )

    except KeyboardInterrupt:
        print("\n\nInterrompu — affichage des résultats partiels")
    finally:
        csv_file.close()

    print()
    if results:
        _print_top(results, top=args.top)
        print(f"\nCSV complet : {args.output}")
    else:
        print("Aucun résultat valide obtenu.")


if __name__ == "__main__":
    main()
