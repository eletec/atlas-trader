"""
backtest/runner.py — Orchestrateur principal du BacktestRunner.

Usage :
    cd zeitgeist-trader
    python -m backtest.runner                          # run standard
    python -m backtest.runner --sweep                  # optimisation des paramètres
    python -m backtest.runner --symbols BTC/USDT ETH/USDT --days 365
    python -m backtest.runner --sweep --output out.html

Options :
    --symbols      : liste d'actifs (défaut: BTC/USDT ETH/USDT SOL/USDT)
    --days         : profondeur historique (défaut: 730 = 2 ans)
    --timeframe    : granularité OHLCV (défaut: 15m)
    --sweep        : active l'optimisation paramétrique
    --output       : nom du fichier HTML de rapport (défaut: backtest_report.html)
    --db           : chemin SQLite résultats (défaut: backtest/backtest_results.sqlite)
    --no-cache     : force le re-téléchargement des données
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import sqlite3
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Path setup ─────────────────────────────────────────────────────────────
_BACKTEST_DIR = Path(__file__).resolve().parent
_APP_ROOT = str(_BACKTEST_DIR.parent)
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from backtest.data_fetcher import (
    fetch_ohlcv,
    fetch_fear_greed_history,
    fetch_funding_history,
)
from backtest.sim_engine import SimEngine, SimTrade

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backtest.runner")

# ── Paramètres par défaut ─────────────────────────────────────────────────

DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
DEFAULT_DAYS = 730
DEFAULT_TIMEFRAME = "15m"
DEFAULT_DB = _BACKTEST_DIR / "backtest_results.sqlite"
DEFAULT_REPORT = _BACKTEST_DIR / "backtest_report.html"

# Grille de sweep (optimisation paramétrique)
SWEEP_GRID: dict[str, list] = {
    "buy_threshold":    [58, 62, 65, 68, 72],
    "exit_threshold":   [40, 43, 46, 50],
    "atr_multiplier_sl": [1.5, 2.0, 2.5],
    "atr_multiplier_tp": [2.5, 3.0, 4.0],
}


# ── Stockage SQLite ────────────────────────────────────────────────────────

def init_db(db_path: Path) -> sqlite3.Connection:
    """Crée (ou ouvre) la DB de résultats de backtest."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_runs (
            run_id        TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            symbols       TEXT NOT NULL,
            days          INTEGER,
            timeframe     TEXT,
            config_json   TEXT,
            PRIMARY KEY (run_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id        TEXT NOT NULL,
            cycle_id      TEXT,
            timestamp     TEXT,
            asset         TEXT,
            action        TEXT,
            score         REAL,
            entry_price   REAL,
            sl_price      REAL,
            tp_price      REAL,
            position_size REAL,
            atr           REAL,
            regime        TEXT,
            result_24h    REAL,
            agent_scores  TEXT,
            score_breakdown TEXT,
            FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_metrics (
            run_id        TEXT NOT NULL,
            asset         TEXT NOT NULL,
            total_cycles  INTEGER,
            n_buy         INTEGER,
            n_sell        INTEGER,
            n_hold        INTEGER,
            win_rate      REAL,
            total_pnl     REAL,
            sharpe        REAL,
            max_drawdown  REAL,
            profit_factor REAL,
            buy_threshold REAL,
            exit_threshold REAL,
            PRIMARY KEY (run_id, asset),
            FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
        )
    """)
    conn.commit()
    return conn


def save_run(conn: sqlite3.Connection, run_id: str, symbols: list[str], days: int, timeframe: str, config: dict) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO backtest_runs VALUES (?,?,?,?,?,?)",
        (run_id, datetime.now(timezone.utc).isoformat(), json.dumps(symbols), days, timeframe, json.dumps(config)),
    )
    conn.commit()


def save_trades(conn: sqlite3.Connection, run_id: str, trades: list[SimTrade]) -> None:
    rows = []
    for t in trades:
        rows.append((
            run_id, t.cycle_id, t.timestamp.isoformat(), t.asset,
            t.action, t.score, t.entry_price, t.sl_price, t.tp_price,
            t.position_size_usd, t.atr, t.regime, t.result_24h,
            json.dumps(t.agent_scores), json.dumps(t.score_breakdown),
        ))
    conn.executemany(
        """INSERT INTO backtest_trades
           (run_id,cycle_id,timestamp,asset,action,score,entry_price,sl_price,tp_price,
            position_size,atr,regime,result_24h,agent_scores,score_breakdown)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()


def save_metrics(conn: sqlite3.Connection, run_id: str, asset: str, metrics: dict, config: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO backtest_metrics
           (run_id,asset,total_cycles,n_buy,n_sell,n_hold,win_rate,
            total_pnl,sharpe,max_drawdown,profit_factor,buy_threshold,exit_threshold)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run_id, asset,
            metrics["total_cycles"], metrics["n_buy"], metrics["n_sell"], metrics["n_hold"],
            metrics["win_rate"], metrics["total_pnl"], metrics["sharpe"],
            metrics["max_drawdown"], metrics["profit_factor"],
            config.get("buy_threshold", 62), config.get("exit_threshold", 45),
        ),
    )
    conn.commit()


# ── Calcul des métriques ─────────────────────────────────────────────────

def compute_metrics(trades: list[SimTrade]) -> dict:
    active = [t for t in trades if t.action in ("BUY", "SELL") and t.result_24h is not None]
    n_buy = sum(1 for t in trades if t.action == "BUY")
    n_sell = sum(1 for t in trades if t.action == "SELL")
    n_hold = sum(1 for t in trades if t.action == "HOLD")

    if not active:
        return {
            "total_cycles": len(trades), "n_buy": n_buy, "n_sell": n_sell, "n_hold": n_hold,
            "win_rate": 0.0, "total_pnl": 0.0, "sharpe": 0.0,
            "max_drawdown": 0.0, "profit_factor": 0.0,
        }

    pnls = [t.result_24h for t in active]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / len(active)
    total_pnl = sum(pnls)

    # Sharpe ratio annualisé (basé sur les cycles)
    import numpy as np
    pnl_arr = np.array(pnls)
    mean_pnl = float(np.mean(pnl_arr))
    std_pnl = float(np.std(pnl_arr)) if len(pnl_arr) > 1 else 1.0
    cycles_per_year = 365 * 4  # 4 cycles/jour en moyenne
    sharpe = (mean_pnl / std_pnl * (cycles_per_year ** 0.5)) if std_pnl > 0 else 0.0

    # Max drawdown (sur le P&L cumulé)
    cum_pnl = list(itertools.accumulate(pnls))
    peak = cum_pnl[0]
    max_dd = 0.0
    for v in cum_pnl:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd

    # Profit factor
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 1.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return {
        "total_cycles": len(trades),
        "n_buy": n_buy, "n_sell": n_sell, "n_hold": n_hold,
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 2),
        "profit_factor": round(profit_factor, 4),
    }


# ── Runner principal ────────────────────────────────────────────────────────

def run_backtest(
    symbols: list[str],
    days: int,
    timeframe: str,
    config_override: dict | None = None,
    db_conn: sqlite3.Connection | None = None,
    force_refresh: bool = False,
    show_progress: bool = True,
) -> tuple[str, dict[str, list[SimTrade]]]:
    """
    Lance un backtest sur les symboles donnés.
    Retourne (run_id, {symbol: [SimTrade]}).
    """
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
    config = config_override or {}

    engine_config: dict[str, Any] = {}
    if config:
        risk_override = {
            k: config[k]
            for k in ("buy_threshold", "exit_threshold", "atr_multiplier_sl", "atr_multiplier_tp")
            if k in config
        }
        engine_config = {"risk": {
            "buy_threshold": 62, "exit_threshold": 45,
            "position_size_pct": 5.0, "kelly_max_fraction": 0.25,
            "atr_multiplier_sl": 2.0, "atr_multiplier_tp": 3.0,
            "paper_capital_usd": 10000,
            **risk_override,
        }, "scoring": {"weights": {"mirofish": 0.12, "market": 0.50, "agents": 0.20, "contrarian": 0.18}}}

    if db_conn:
        save_run(db_conn, run_id, symbols, days, timeframe, config)

    # Téléchargement des données communes (Fear & Greed)
    logger.info("Téléchargement Fear & Greed historique...")
    fng_df = fetch_fear_greed_history(days=days, force_refresh=force_refresh)

    results: dict[str, list[SimTrade]] = {}
    engine = SimEngine(config=engine_config if engine_config else None)

    for symbol in symbols:
        logger.info(f"\n{'='*60}\nBacktest {symbol} ({days}j {timeframe})\n{'='*60}")

        ohlcv_df = fetch_ohlcv(symbol, timeframe=timeframe, days=days, force_refresh=force_refresh)
        funding_df = fetch_funding_history(symbol, days=days, force_refresh=force_refresh)

        if ohlcv_df.empty:
            logger.warning(f"{symbol}: aucune donnée OHLCV — symbole ignoré")
            continue

        trades = engine.run_asset(
            symbol=symbol,
            ohlcv_df=ohlcv_df,
            fng_df=fng_df,
            funding_df=funding_df,
            show_progress=show_progress,
        )

        metrics = compute_metrics(trades)
        results[symbol] = trades

        if db_conn:
            save_trades(db_conn, run_id, trades)
            save_metrics(db_conn, run_id, symbol, metrics, config)

        _log_metrics_summary(symbol, metrics)

    return run_id, results


def _log_metrics_summary(symbol: str, m: dict) -> None:
    logger.info(
        f"\n  {symbol} — Résultats:\n"
        f"  Cycles: {m['total_cycles']} | BUY: {m['n_buy']} | SELL: {m['n_sell']} | HOLD: {m['n_hold']}\n"
        f"  Win rate: {m['win_rate']*100:.1f}% | P&L total: ${m['total_pnl']:+.2f}\n"
        f"  Sharpe: {m['sharpe']:.3f} | Max DD: ${m['max_drawdown']:.2f} | Profit factor: {m['profit_factor']:.2f}"
    )


# ── Sweep paramétrique ───────────────────────────────────────────────────────

def run_sweep(
    symbols: list[str],
    days: int,
    timeframe: str,
    db_conn: sqlite3.Connection,
    force_refresh: bool = False,
) -> dict[str, dict]:
    """
    Grille de recherche exhaustive sur SWEEP_GRID.
    Retourne le meilleur ensemble de paramètres par symbole (Sharpe).
    """
    # Données téléchargées une seule fois
    fng_df = fetch_fear_greed_history(days=days, force_refresh=force_refresh)
    ohlcv_cache = {}
    funding_cache = {}
    for sym in symbols:
        ohlcv_cache[sym] = fetch_ohlcv(sym, timeframe=timeframe, days=days, force_refresh=force_refresh)
        funding_cache[sym] = fetch_funding_history(sym, days=days, force_refresh=force_refresh)

    keys = list(SWEEP_GRID.keys())
    values = list(SWEEP_GRID.values())
    combinations = list(itertools.product(*values))
    total = len(combinations)
    logger.info(f"Sweep: {total} combinaisons × {len(symbols)} symboles = {total * len(symbols)} runs")

    best: dict[str, dict] = {s: {"sharpe": -9999.0, "params": {}, "metrics": {}} for s in symbols}

    for idx, combo in enumerate(combinations):
        params = dict(zip(keys, combo))
        config_override = params.copy()

        run_id = f"sweep_{datetime.now(timezone.utc).strftime('%H%M%S%f')}_{idx}"
        save_run(db_conn, run_id, symbols, days, timeframe, config_override)

        risk = {
            "buy_threshold": params["buy_threshold"],
            "exit_threshold": params["exit_threshold"],
            "atr_multiplier_sl": params["atr_multiplier_sl"],
            "atr_multiplier_tp": params["atr_multiplier_tp"],
            "position_size_pct": 5.0,
            "kelly_max_fraction": 0.25,
            "paper_capital_usd": 10_000,
        }
        engine_config = {
            "risk": risk,
            "scoring": {"weights": {"mirofish": 0.12, "market": 0.50, "agents": 0.20, "contrarian": 0.18}},
        }
        engine = SimEngine(config=engine_config)

        for sym in symbols:
            df = ohlcv_cache.get(sym)
            if df is None or df.empty:
                continue

            trades = engine.run_asset(sym, df, fng_df, funding_cache.get(sym, __import__("pandas").DataFrame()), show_progress=False)
            metrics = compute_metrics(trades)

            save_trades(db_conn, run_id, trades)
            save_metrics(db_conn, run_id, sym, metrics, config_override)

            if metrics["sharpe"] > best[sym]["sharpe"]:
                best[sym] = {"sharpe": metrics["sharpe"], "params": params.copy(), "metrics": metrics}

        if (idx + 1) % 10 == 0:
            logger.info(f"Sweep: {idx+1}/{total} combinaisons traitées")

    logger.info("\n=== MEILLEURS PARAMÈTRES PAR ACTIF ===")
    for sym, b in best.items():
        logger.info(f"  {sym}: Sharpe={b['sharpe']:.3f} params={b['params']}")

    return best


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas BacktestRunner — simulation quantitative standalone")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, metavar="SYM")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    parser.add_argument("--sweep", action="store_true", help="Activer l'optimisation paramétrique")
    parser.add_argument("--output", default=str(DEFAULT_REPORT), metavar="FILE")
    parser.add_argument("--db", default=str(DEFAULT_DB), metavar="FILE")
    parser.add_argument("--no-cache", action="store_true", dest="no_cache")
    args = parser.parse_args()

    db_conn = init_db(Path(args.db))
    force = args.no_cache

    if args.sweep:
        best_params = run_sweep(
            symbols=args.symbols,
            days=args.days,
            timeframe=args.timeframe,
            db_conn=db_conn,
            force_refresh=force,
        )
        # Run final avec les meilleurs paramètres globaux (Sharpe moyen)
        if best_params:
            best_global = max(best_params.values(), key=lambda x: x["sharpe"])
            config_final = best_global["params"]
            logger.info(f"\nRun final avec meilleurs paramètres: {config_final}")
            run_id, results = run_backtest(
                symbols=args.symbols, days=args.days, timeframe=args.timeframe,
                config_override=config_final, db_conn=db_conn, force_refresh=False,
            )
        else:
            run_id, results = run_backtest(
                symbols=args.symbols, days=args.days, timeframe=args.timeframe,
                db_conn=db_conn, force_refresh=force,
            )
    else:
        run_id, results = run_backtest(
            symbols=args.symbols, days=args.days, timeframe=args.timeframe,
            db_conn=db_conn, force_refresh=force,
        )

    # Générer le rapport HTML
    from backtest.report import generate_report
    all_trades: list[SimTrade] = []
    for tlist in results.values():
        all_trades.extend(tlist)

    all_metrics = {}
    for sym, trades in results.items():
        all_metrics[sym] = compute_metrics(trades)

    report_path = generate_report(
        run_id=run_id,
        trades=all_trades,
        metrics_by_symbol=all_metrics,
        output_path=Path(args.output),
    )
    logger.info(f"\nRapport généré : {report_path}")

    db_conn.close()


if __name__ == "__main__":
    main()
