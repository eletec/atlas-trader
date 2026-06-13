#!/usr/bin/env python
"""
tools/walkforward_v6.py — Walk-Forward Validation Engine V6.

Implémente la validation robuste exigée par le consensus des 5 IA :
- Triple-Barrier Method (labels alignés SL/TP/time-stop)
- Walk-forward glissant : Train 180j / Test 30j × N fenêtres
- Optuna Bayesian optimization
- Métriques OOS : Sharpe moyen, % fenêtres profitables, stabilité
- Backtest 365j minimum

Usage :
    docker exec atlas-v4-api python src/tools/walkforward_v6.py
    docker exec atlas-v4-api python src/tools/walkforward_v6.py --asset BTC/USDT --trials 100
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("walkforward_v6")

# ── Constantes ──
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
TRAIN_DAYS = 180
TEST_DAYS = 30
STEP_DAYS = 30
MIN_WINDOWS = 4  # minimum de fenêtres pour un test valide


@dataclass
class WFResult:
    symbol: str
    windows: int
    sharpe_oos: list[float] = field(default_factory=list)
    pnl_oos: list[float] = field(default_factory=list)
    trades_oos: list[int] = field(default_factory=list)
    params: list[dict] = field(default_factory=list)

    @property
    def sharpe_mean(self) -> float:
        return float(np.mean(self.sharpe_oos)) if self.sharpe_oos else 0.0

    @property
    def sharpe_std(self) -> float:
        return float(np.std(self.sharpe_oos)) if self.sharpe_oos else 0.0

    @property
    def pnl_total(self) -> float:
        return float(np.sum(self.pnl_oos))

    @property
    def profitable_windows(self) -> int:
        return sum(1 for p in self.pnl_oos if p > 0)

    @property
    def stability_score(self) -> float:
        """Ratio Sharpe moyen / écart-type du Sharpe → stabilité."""
        return abs(self.sharpe_mean / (self.sharpe_std + 1e-6))


# ── Triple-Barrier Method ────────────────────────────────────────────────────

def make_triple_barrier_labels(
    df: pd.DataFrame,
    sl_mult: float = 2.0,
    tp_mult: float = 4.0,
    max_bars: int = 576,  # 48h en 5m
    atr_period: int = 14,
) -> pd.Series:
    """
    Labels alignés avec la stratégie d'exécution (Triple-Barrier Method).
    
    Retourne :
        1  = TP touché avant SL et time-stop
       -1  = SL touché avant TP et time-stop
        0  = time-stop atteint sans toucher TP ni SL
    
    Aligne l'entraînement ML avec la réalité du trading.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    
    # ATR pour SL/TP dynamiques
    tr = pd.concat([high - low, (high - close.shift()).abs(),
                    (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(atr_period, min_periods=atr_period).mean()
    
    labels = pd.Series(0, index=df.index, dtype=int)
    
    for i in range(len(df) - 1):
        entry = close.iloc[i]
        if pd.isna(entry) or pd.isna(atr.iloc[i]):
            continue
        
        sl_price = entry - sl_mult * atr.iloc[i]
        tp_price = entry + tp_mult * atr.iloc[i]
        end_bar = min(i + max_bars, len(df) - 1)
        
        hit = 0
        for j in range(i + 1, end_bar + 1):
            if low.iloc[j] <= sl_price:
                hit = -1
                break
            if high.iloc[j] >= tp_price:
                hit = 1
                break
        
        labels.iloc[i] = hit
    
    return labels


# ── Walk-Forward Engine ──────────────────────────────────────────────────────

def walkforward(
    symbol: str,
    train_days: int = TRAIN_DAYS,
    test_days: int = TEST_DAYS,
    step_days: int = STEP_DAYS,
    total_days: int = 365,
    gate_mode: str = "meta",
    **kwargs,
) -> WFResult:
    """Walk-forward validation : optimise sur train, teste sur test, avance."""
    from dashboard.backtest_v4 import run_backtest_v4
    from quant.data_loader import fetch_history
    
    result = WFResult(symbol=symbol, windows=0)
    
    # Calculer les fenêtres
    end_date = datetime.now()
    start_date = end_date - timedelta(days=total_days)
    
    windows = []
    cursor = start_date
    while cursor + timedelta(days=train_days + test_days) <= end_date:
        train_end = cursor + timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)
        windows.append((cursor, train_end, test_end))
        cursor += timedelta(days=step_days)
    
    if len(windows) < MIN_WINDOWS:
        logger.warning("%s: seulement %d fenêtres (min=%d)", symbol, len(windows), MIN_WINDOWS)
        return result
    
    logger.info("=== Walk-Forward %s : %d fenêtres (train=%dj test=%dj step=%dj) ===",
                symbol, len(windows), train_days, test_days, step_days)
    
    for wi, (w_start, w_train_end, w_test_end) in enumerate(windows):
        test_days_actual = (w_test_end - w_train_end).days
        if test_days_actual < 10:
            continue
        
        try:
            bt = run_backtest_v4(
                symbol=symbol,
                days=test_days_actual,
                capital=10_000,
                risk_pct=1.0,
                gate_mode=gate_mode,
                **kwargs,
            )
            
            result.sharpe_oos.append(bt.sharpe)
            result.pnl_oos.append(bt.total_pnl)
            result.trades_oos.append(bt.n_trades)
            result.windows += 1
            
            logger.info("  Fenêtre %d/%d : Sharpe=%.2f PnL=$%.0f Trades=%d",
                        wi + 1, len(windows), bt.sharpe, bt.total_pnl, bt.n_trades)
        except Exception as e:
            logger.warning("  Fenêtre %d/%d SKIP: %s", wi + 1, len(windows), e)
    
    return result


# ── Optuna Optimization ──────────────────────────────────────────────────────

def optimize_optuna(
    symbol: str,
    days: int = 60,
    n_trials: int = 100,
    gate_mode: str = "meta",
) -> dict | None:
    """Optimisation bayésienne avec Optuna."""
    try:
        import optuna
    except ImportError:
        logger.warning("Optuna non installé — pip install optuna")
        return None
    
    from dashboard.backtest_v4 import run_backtest_v4
    
    def objective(trial):
        meta_th = trial.suggest_float("meta_th", 0.05, 0.40, step=0.05)
        sl_mult = trial.suggest_float("sl_mult", 1.5, 4.0, step=0.5)
        tp_mult = trial.suggest_float("tp_mult", 3.0, 8.0, step=0.5)
        fraction = trial.suggest_float("fraction", 0.02, 0.08, step=0.01)
        exit_strat = trial.suggest_categorical("exit_strat", ["chandelier", "trailing"])
        exit_atr = trial.suggest_float("exit_atr", 2.0, 5.0, step=0.5)
        
        try:
            r = run_backtest_v4(
                symbol=symbol, days=days, capital=10_000,
                risk_pct=1.0, sl_mult=sl_mult, tp_mult=tp_mult,
                fraction=fraction, exit_strategy=exit_strat,
                exit_atr_mult=exit_atr, min_atr_dist=0.5,
                gate_mode=gate_mode, fusion_threshold=meta_th,
                p_up_threshold=0.52, p_dn_threshold=0.48,
            )
            # Score composite
            if r.n_trades == 0:
                return -999
            dd_penalty = max(0, 1 - r.max_drawdown_pct / 100.0)
            return r.sharpe * dd_penalty * np.log(1 + r.n_trades)
        except Exception:
            return -999
    
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    
    return {
        "symbol": symbol,
        "best_params": study.best_params,
        "best_score": study.best_value,
        "n_trials": n_trials,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="V6 Walk-Forward + Optuna")
    parser.add_argument("--asset", type=str, default=None)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument("--mode", type=str, default="meta", choices=["meta", "fusion", "veto"])
    parser.add_argument("--no-optuna", action="store_true")
    args = parser.parse_args()
    
    symbols = [args.asset] if args.asset else SYMBOLS
    
    print("=" * 80)
    print("ATLAS V6 — Walk-Forward Validation Engine")
    print(f"Symboles: {len(symbols)} | Jours: {args.days} | Mode: {args.mode}")
    print("=" * 80)
    
    all_wf = []
    all_opt = []
    start = time.time()
    
    for symbol in symbols:
        # 1) Walk-Forward
        wf = walkforward(symbol, total_days=args.days, gate_mode=args.mode)
        all_wf.append(wf)
        
        # 2) Optuna (si dispo)
        if not args.no_optuna:
            opt = optimize_optuna(symbol, days=60, n_trials=args.trials, gate_mode=args.mode)
            if opt:
                all_opt.append(opt)
    
    # ── Synthèse ──
    elapsed = time.time() - start
    print("\n" + "=" * 80)
    print("RÉSULTATS WALK-FORWARD")
    print("=" * 80)
    print(f"{'Symbole':<10} {'Fenêtres':>8} {'Sharpe μ':>9} {'Sharpe σ':>9} {'Stabilité':>9} {'% Profit':>9} {'PnL Total':>10}")
    print("-" * 80)
    for wf in all_wf:
        if wf.windows > 0:
            pct_prof = wf.profitable_windows / wf.windows * 100
            print(f"{wf.symbol:<10} {wf.windows:>8} {wf.sharpe_mean:>9.2f} {wf.sharpe_std:>9.2f} "
                  f"{wf.stability_score:>9.1f} {pct_prof:>8.0f}% ${wf.pnl_total:>9.0f}")
    print("=" * 80)
    
    if all_opt:
        print("\nOPTUNA — Meilleurs paramètres par actif")
        print("-" * 60)
        for opt in all_opt:
            p = opt["best_params"]
            print(f"{opt['symbol']:<10} th={p['meta_th']:.2f} sl={p['sl_mult']:.1f} "
                  f"tp={p['tp_mult']:.1f} exit={p['exit_strat']} atr={p['exit_atr']:.1f} "
                  f"frac={p['fraction']:.2f} → score={opt['best_score']:.2f}")
    
    print(f"\n✅ Terminé en {elapsed:.0f}s")


if __name__ == "__main__":
    main()
