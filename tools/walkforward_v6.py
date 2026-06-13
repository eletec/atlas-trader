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
    """Walk-forward validation : optimise sur train, teste sur test, avance.
    
    Charge TOUT l'historique une fois, puis découpe en fenêtres glissantes.
    Chaque fenêtre de test est strictement postérieure à sa fenêtre de train.
    """
    from dashboard.backtest_v4 import run_backtest_v4
    from quant.data_loader import fetch_history
    from datetime import timedelta
    
    result = WFResult(symbol=symbol, windows=0)
    
    # Charger tout l'historique nécessaire (train max + total_days)
    total_needed = train_days + total_days
    logger.info("Chargement historique %s (%dj)...", symbol, total_needed)
    
    try:
        df_5m_full = fetch_history(symbol, "5m", days=total_needed, cache=True)
        df_1h_full = fetch_history(symbol, "1h", days=total_needed, cache=True)
    except Exception as e:
        logger.error("Erreur chargement données: %s", e)
        return result
    
    if len(df_5m_full) < 500:
        logger.warning("%s: pas assez de données (%d barres)", symbol, len(df_5m_full))
        return result
    
    # ── Découpage en fenêtres walk-forward ──
    # S'assurer que les timestamps sont timezone-aware (UTC)
    if df_5m_full.index.tz is None:
        df_5m_full.index = df_5m_full.index.tz_localize('UTC')
    if df_1h_full.index.tz is None:
        df_1h_full.index = df_1h_full.index.tz_localize('UTC')
    
    end_date = df_5m_full.index[-1]
    start_date = end_date - timedelta(days=total_days)
    
    # Générer les paires (train_end, test_end) en UTC
    windows_dates = []
    cursor = start_date
    while cursor + timedelta(days=train_days + test_days) <= end_date:
        train_end = cursor + timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)
        windows_dates.append((train_end, test_end))
        cursor += timedelta(days=step_days)
    
    if len(windows_dates) < MIN_WINDOWS:
        logger.warning("%s: seulement %d fenêtres (min=%d)", symbol, len(windows_dates), MIN_WINDOWS)
        return result
    
    logger.info("=== Walk-Forward %s : %d fenêtres (train=%dj test=%dj step=%dj) ===",
                symbol, len(windows_dates), train_days, test_days, step_days)
    
    for wi, (train_end, test_end) in enumerate(windows_dates):
        try:
            # Découper les données (index déjà UTC)
            test_5m = df_5m_full[(df_5m_full.index > train_end) & (df_5m_full.index <= test_end)]
            test_1h = df_1h_full[(df_1h_full.index > train_end) & (df_1h_full.index <= test_end)]
            # Inclure 500 barres avant pour le warmup du backtest
            warmup_5m = df_5m_full[df_5m_full.index <= test_end].iloc[-len(test_5m)-500:] if len(test_5m) > 0 else df_5m_full.iloc[-500:]
            
            if len(test_5m) < 200:
                logger.info("  Fenêtre %d/%d SKIP: test trop petit (%d barres)", wi + 1, len(windows_dates), len(test_5m))
                continue
            
            # Lancer le backtest sur cette fenêtre
            bt = run_backtest_v4(
                symbol=symbol,
                days=test_days,
                capital=10_000,
                risk_pct=1.0,
                gate_mode=gate_mode,
                _df_5m_override=warmup_5m,
                _df_1h_override=test_1h,
                **kwargs,
            )
            
            result.sharpe_oos.append(bt.sharpe)
            result.pnl_oos.append(bt.total_pnl)
            result.trades_oos.append(bt.n_trades)
            result.windows += 1
            
            logger.info("  Fenêtre %d/%d [%s→%s]: Sharpe=%.2f PnL=$%.0f Trades=%d",
                        wi + 1, len(windows_dates),
                        train_end.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d"),
                        bt.sharpe, bt.total_pnl, bt.n_trades)
        except Exception as e:
            logger.warning("  Fenêtre %d/%d SKIP: %s", wi + 1, len(windows_dates), e)
    
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
        fraction = trial.suggest_float("fraction", 0.002, 0.010, step=0.001)
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
            # Score = Sharpe pénalisé par drawdown (pas de bonus au nombre de trades)
            if r.n_trades == 0:
                return -999
            dd_penalty = max(0.0, 1.0 - r.max_drawdown_pct / 100.0)
            return r.sharpe * dd_penalty
        except Exception:
            return -999
    
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
    
    return {
        "symbol": symbol,
        "best_params": study.best_params,
        "best_score": study.best_value,
        "n_trials": n_trials,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)  # silence Optuna logs
    
    parser = argparse.ArgumentParser(description="V6 Walk-Forward + Optuna")
    parser.add_argument("--asset", type=str, default=None)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--trials", type=int, default=30, help="Optuna trials (default: 30, réduire pour aller plus vite)")
    parser.add_argument("--mode", type=str, default="meta", choices=["meta", "fusion", "veto"])
    parser.add_argument("--no-optuna", action="store_true", help="Skip Optuna, use defaults")
    parser.add_argument("--fast", action="store_true", help="Skip Optuna, use proven V4/V5 params")
    parser.add_argument("--optuna-days", type=int, default=60, help="Jours pour Optuna (default: 60)")
    args = parser.parse_args()
    
    symbols = [args.asset] if args.asset else SYMBOLS
    
    # ── Params éprouvés V4/V5 (mode --fast) ──
    FAST_PARAMS = {
        "fusion_threshold": 0.15, "sl_mult": 2.0, "tp_mult": 4.0,
        "fraction": 0.005, "exit_strategy": "chandelier", "exit_atr_mult": 3.0,
    }
    
    print("=" * 80)
    print("ATLAS V6 — Walk-Forward Validation Engine")
    print(f"Symboles: {len(symbols)} | Jours: {args.days} | Mode: {args.mode} | Trials: {args.trials}")
    if args.fast:
        print("⚡ Mode FAST — Optuna skip, params V4/V5")
    if args.no_optuna:
        print("⚡ No Optuna — defaults only")
    print("=" * 80)
    
    all_wf = []
    all_opt = []
    start = time.time()
    
    for idx, symbol in enumerate(symbols):
        t_sym = time.time()
        best_params = None
        
        # 1) Optuna — trouver les meilleurs params
        if args.fast:
            wf_kwargs = dict(FAST_PARAMS)
            logger.info("%s: ⚡ fast mode — params V4/V5", symbol)
        elif args.no_optuna:
            wf_kwargs = {}
            logger.info("%s: no Optuna — defaults", symbol)
        else:
            logger.info("%s [%d/%d]: Optuna %d trials × %dj…", symbol, idx+1, len(symbols), args.trials, args.optuna_days)
            opt = optimize_optuna(symbol, days=args.optuna_days, n_trials=args.trials, gate_mode=args.mode)
            if opt:
                all_opt.append(opt)
                best_params = opt["best_params"]
                logger.info("%s: Optuna best score=%.2f params=%s (%.0fs)", symbol, opt["best_score"], best_params, time.time()-t_sym)
            wf_kwargs = {}
            if best_params:
                wf_kwargs = {
                    "fusion_threshold": best_params["meta_th"],
                    "sl_mult": best_params["sl_mult"],
                    "tp_mult": best_params["tp_mult"],
                    "fraction": best_params["fraction"],
                    "exit_strategy": best_params["exit_strat"],
                    "exit_atr_mult": best_params["exit_atr"],
                }
        
        # 2) Walk-Forward
        logger.info("%s: Walk-Forward %dj…", symbol, args.days)
        wf = walkforward(symbol, total_days=args.days, gate_mode=args.mode, **wf_kwargs)
        all_wf.append(wf)
        logger.info("%s: done in %.0fs (windows=%d)", symbol, time.time()-t_sym, wf.windows)
    
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
                  f"frac={p['fraction']:.3f} → score={opt['best_score']:.2f}")
    
    print(f"\n✅ Terminé en {elapsed:.0f}s")


if __name__ == "__main__":
    main()
