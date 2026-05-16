"""
run_v2.py — Point d'entrée V2 propre.

Usage :
    python run_v2.py smoke           # smoke test sur OHLCV synthétique
    python run_v2.py backtest        # backtest BTC/USDT 15min, 90j
    python run_v2.py walkforward     # walk-forward 6m train / 3m test
    python run_v2.py baseline        # baseline breakout pour comparaison

Aucun appel LLM, aucun WebSocket — pipeline quantitatif pur.
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from quant.data_loader import fetch_history, synthetic_ohlcv
from quant.pipeline import PipelineConfig, run_baseline, run_pipeline
from quant.validation import walk_forward_split

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("run_v2")


def cmd_smoke() -> int:
    log.info("Smoke test sur 2000 bougies synthétiques.")
    ohlcv = synthetic_ohlcv(n_bars=2000, seed=42)
    split = int(len(ohlcv) * 0.7)
    train_idx = ohlcv.index[:split]
    test_idx = ohlcv.index[split:]
    cfg = PipelineConfig(use_hmm=False)  # fallback threshold pour smoke offline
    artifacts = run_pipeline(ohlcv, train_idx, test_idx, cfg)
    log.info("=== Résultat backtest OOS ===\n" + artifacts.backtest.to_summary())
    bh = run_baseline(ohlcv.loc[test_idx])
    log.info("=== Baseline Buy-and-Hold OOS ===\n" + bh.to_summary())
    return 0


def cmd_backtest(symbol: str, days: int, timeframe: str) -> int:
    log.info(f"Téléchargement {symbol} {timeframe} sur {days} jours…")
    ohlcv = fetch_history(symbol=symbol, timeframe=timeframe, days=days)
    if len(ohlcv) < 500:
        log.error(f"Données insuffisantes ({len(ohlcv)} bougies).")
        return 1
    split = int(len(ohlcv) * 0.7)
    train_idx = ohlcv.index[:split]
    test_idx = ohlcv.index[split:]
    artifacts = run_pipeline(ohlcv, train_idx, test_idx)
    log.info("=== Backtest OOS ===\n" + artifacts.backtest.to_summary())
    bh = run_baseline(ohlcv.loc[test_idx])
    log.info("=== Buy-and-Hold OOS ===\n" + bh.to_summary())
    return 0


def cmd_walkforward(symbol: str, days: int, timeframe: str) -> int:
    log.info(f"Walk-forward {symbol} {timeframe} sur {days} jours…")
    ohlcv = fetch_history(symbol=symbol, timeframe=timeframe, days=days)
    folds = list(walk_forward_split(ohlcv.index, train_months=6, test_months=3))
    if not folds:
        log.error("Historique insuffisant pour walk-forward 6m/3m.")
        return 1
    summary_rows = []
    for k, (train_idx, test_idx) in enumerate(folds, 1):
        log.info(
            f"Fold {k}/{len(folds)}: train={len(train_idx)} test={len(test_idx)}"
        )
        artifacts = run_pipeline(ohlcv, train_idx, test_idx)
        m = artifacts.backtest.metrics
        summary_rows.append(
            {
                "fold": k,
                "train_start": train_idx.min(),
                "test_start": test_idx.min(),
                "test_end": test_idx.max(),
                "n_trades": len(artifacts.backtest.trades),
                "total_return": m["total_return"],
                "sharpe": m["sharpe"],
                "max_dd": m["max_dd"],
                "win_rate": m["win_rate"],
            }
        )
    df = pd.DataFrame(summary_rows)
    log.info("=== Walk-forward summary ===\n" + df.to_string(index=False))
    log.info(
        f"Sharpe moyen OOS: {df['sharpe'].mean():.2f} | "
        f"Rendement total moyen: {df['total_return'].mean():.2%}"
    )
    return 0


def cmd_baseline(symbol: str, days: int, timeframe: str) -> int:
    ohlcv = fetch_history(symbol=symbol, timeframe=timeframe, days=days)
    result = run_baseline(ohlcv)
    log.info("=== Baseline breakout Donchian ===\n" + result.to_summary())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas Trader V2 — quant runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("smoke")

    p_bt = sub.add_parser("backtest")
    p_bt.add_argument("--symbol", default="BTC/USDT")
    p_bt.add_argument("--days", type=int, default=90)
    p_bt.add_argument("--timeframe", default="15m")

    p_wf = sub.add_parser("walkforward")
    p_wf.add_argument("--symbol", default="BTC/USDT")
    p_wf.add_argument("--days", type=int, default=540)  # ≥18 mois pour ≥4 folds
    p_wf.add_argument("--timeframe", default="15m")

    p_bl = sub.add_parser("baseline")
    p_bl.add_argument("--symbol", default="BTC/USDT")
    p_bl.add_argument("--days", type=int, default=90)
    p_bl.add_argument("--timeframe", default="15m")

    args = parser.parse_args(argv)

    if args.cmd == "smoke":
        return cmd_smoke()
    if args.cmd == "backtest":
        return cmd_backtest(args.symbol, args.days, args.timeframe)
    if args.cmd == "walkforward":
        return cmd_walkforward(args.symbol, args.days, args.timeframe)
    if args.cmd == "baseline":
        return cmd_baseline(args.symbol, args.days, args.timeframe)
    return 1


if __name__ == "__main__":
    sys.exit(main())
