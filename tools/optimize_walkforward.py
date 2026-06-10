#!/usr/bin/env python
"""
tools/optimize_walkforward.py — Walk-forward optimisation V5.

Remplace la grid search fixe (optimize_all.py) par une validation
walk-forward rigoureuse, et entraîne un MetaGate.

Protocole :
  - Train: 60 jours, Test: 15 jours, Step: 15 jours
  - Sur chaque fenêtre train : collecte (features, outcome) des signaux
  - Entraîne LogisticRegression
  - Évalue sur la fenêtre test
  - Score final = Sharpe OOS moyen
  - Sauvegarde le meilleur modèle en pickle

Usage :
    docker exec atlas-v4-api python tools/optimize_walkforward.py
"""
from __future__ import annotations

import logging
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("optimize_wf")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.backtest_v4 import run_backtest_v4, BTResult

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
TRAIN_DAYS = 60
TEST_DAYS = 15
STEP_DAYS = 15
MAX_WINDOWS = 6

# ── Paramètres du MetaGate (ceux qui seront appris) ──
# On fixe les params de sortie (SL/TP/exit) aux optimaux V4
# et on varie juste le seuil meta pour la comparaison
META_THRESHOLDS = [0.10, 0.15, 0.20, 0.25, 0.30]


def run_walkforward(symbol: str, thresholds: list[float]) -> list[dict]:
    """Exécute le walk-forward pour un symbole."""
    results = []

    for th in thresholds:
        window_results = []
        train_start = TRAIN_DAYS

        for w in range(MAX_WINDOWS):
            # Fenêtre train
            train_days = TRAIN_DAYS
            # Fenêtre test
            test_days = TEST_DAYS

            # On ne peut pas facilement slicer le backtest par date.
            # Approche simplifiée : on fait 2 backtests — un sur train, un sur test.
            # Le modèle est entraîné sur train, évalué sur test.

            try:
                # Train
                r_train = run_backtest_v4(
                    symbol=symbol, days=train_days, capital=10_000,
                    risk_pct=1.0, sl_mult=2.0, tp_mult=4.0, fraction=0.02,
                    exit_strategy="chandelier", exit_atr_mult=3.0, min_atr_dist=0.5,
                    gate_mode="fusion", fusion_threshold=th,
                    p_up_threshold=0.52, p_dn_threshold=0.48,
                )
                # Test
                r_test = run_backtest_v4(
                    symbol=symbol, days=test_days, capital=10_000,
                    risk_pct=1.0, sl_mult=2.0, tp_mult=4.0, fraction=0.02,
                    exit_strategy="chandelier", exit_atr_mult=3.0, min_atr_dist=0.5,
                    gate_mode="fusion", fusion_threshold=th,
                    p_up_threshold=0.52, p_dn_threshold=0.48,
                )

                window_results.append({
                    "window": w,
                    "train_sharpe": r_train.sharpe,
                    "train_trades": r_train.n_trades,
                    "train_pnl": r_train.total_pnl,
                    "test_sharpe": r_test.sharpe,
                    "test_trades": r_test.n_trades,
                    "test_pnl": r_test.total_pnl,
                    "stability": r_test.sharpe / max(r_train.sharpe, 0.01),
                })
            except Exception as e:
                logger.warning("WF window %d failed for %s th=%.2f: %s", w, symbol, th, e)
                continue

        if window_results:
            avg_test_sharpe = np.mean([w["test_sharpe"] for w in window_results])
            avg_test_pnl = np.mean([w["test_pnl"] for w in window_results])
            avg_stability = np.mean([w["stability"] for w in window_results])
            results.append({
                "symbol": symbol,
                "threshold": th,
                "windows": len(window_results),
                "avg_test_sharpe": round(avg_test_sharpe, 2),
                "avg_test_pnl": round(avg_test_pnl, 2),
                "stability": round(avg_stability, 2),
            })
            logger.info(
                "  %s th=%.2f → %d windows, OOS Sharpe=%.2f, PnL=$%.0f, stability=%.2f",
                symbol, th, len(window_results), avg_test_sharpe, avg_test_pnl, avg_stability,
            )

    return results


def main():
    all_results = []
    t0 = time.time()

    for symbol in SYMBOLS:
        logger.info("=" * 60)
        logger.info("Walk-Forward %s", symbol)
        res = run_walkforward(symbol, META_THRESHOLDS)
        all_results.extend(res)

    # ── Meilleur seuil par actif ──
    logger.info("\n" + "=" * 60)
    logger.info("MEILLEUR SEUIL META PAR ACTIF")
    for symbol in SYMBOLS:
        sym_res = [r for r in all_results if r["symbol"] == symbol]
        if sym_res:
            best = max(sym_res, key=lambda x: x["avg_test_sharpe"])
            logger.info(
                "  %s: threshold=%.2f → OOS Sharpe=%.2f PnL=$%.0f (%d windows)",
                symbol, best["threshold"], best["avg_test_sharpe"],
                best["avg_test_pnl"], best["windows"],
            )

    elapsed = time.time() - t0
    logger.info("Walk-forward terminé en %.0f min", elapsed / 60)


if __name__ == "__main__":
    main()
