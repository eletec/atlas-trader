#!/usr/bin/env python
"""
tools/benchmark_levers.py — Test comparatif des 4 leviers de performance.

Mesure l'impact isolé de chaque levier sur le PnL, Sharpe, et nombre de trades.
Produit un tableau comparatif.

Usage :
    docker exec atlas-v4-api python tools/benchmark_levers.py

Output :
    Tableau comparatif + synthèse du meilleur levier.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("benchmark_levers")

from dashboard.backtest_v4 import run_backtest_v4

# ── Actifs testés ──
ASSETS = ["BTC/USDT", "ETH/USDT"]

# ── Paramètres communs ──
COMMON = dict(capital=10_000, risk_pct=1.0, fraction=0.02,
              exit_strategy="chandelier", exit_atr_mult=3.0, min_atr_dist=0.5,
              gate_mode="fusion", fusion_threshold=0.15)

# ── Définition des leviers ──

def baseline(symbol, days):
    """V4 actuel — p_up=0.52, p_dn=0.48, SL=2.0, TP=4.0."""
    return run_backtest_v4(symbol=symbol, days=days,
                           sl_mult=2.0, tp_mult=4.0,
                           p_up_threshold=0.52, p_dn_threshold=0.48,
                           **COMMON)

def multi_horizon(symbol, days):
    """Simule multi-horizon en baissant les seuils (proxy)."""
    # Un vrai multi-horizon nécessiterait 3 XGBoost.
    # Proxy : baisser les seuils pour simuler + de signaux filtrés
    return run_backtest_v4(symbol=symbol, days=days,
                           sl_mult=2.0, tp_mult=4.0,
                           p_up_threshold=0.51, p_dn_threshold=0.49,
                           fusion_threshold=0.10,
                           **{k: v for k, v in COMMON.items() if k != "fusion_threshold"})

def mean_reversion_range(symbol, days):
    """Simule mean-reversion en range : active les signaux contra-tendance."""
    # Proxy : utiliser un seuil fusion plus bas + SL/TP plus serrés
    return run_backtest_v4(symbol=symbol, days=days,
                           sl_mult=1.5, tp_mult=3.0,
                           p_up_threshold=0.52, p_dn_threshold=0.48,
                           fusion_threshold=0.05,
                           **{k: v for k, v in COMMON.items() if k != "fusion_threshold"})

def kelly_sizing(symbol, days):
    """Simule Kelly sizing : sizing variable selon probabilité."""
    # Proxy : augmenter la fraction pour simuler des mises plus agressives
    # quand le signal est fort, et réduire quand faible.
    return run_backtest_v4(symbol=symbol, days=days,
                           sl_mult=2.0, tp_mult=4.0, fraction=0.03,
                           p_up_threshold=0.52, p_dn_threshold=0.48,
                           **COMMON)

def more_assets_test(assets, days):
    """Test sur plus d'actifs (ADA, DOGE, LINK en plus de BTC, ETH)."""
    results = {}
    for sym in assets:
        try:
            r = run_backtest_v4(symbol=sym, days=days, sl_mult=2.0, tp_mult=4.0,
                               p_up_threshold=0.52, p_dn_threshold=0.48, **COMMON)
            results[sym] = r
        except Exception as e:
            logger.warning("  %s: SKIP (%s)", sym, e)
    return results


def main():
    days = 60
    levers = {
        "Baseline V4": lambda s: baseline(s, days),
        "Multi-horizon XGB": lambda s: multi_horizon(s, days),
        "Mean-reversion Range": lambda s: mean_reversion_range(s, days),
        "Kelly sizing": lambda s: kelly_sizing(s, days),
    }

    all_results: list[dict] = []
    t0 = time.time()

    for name, fn in levers.items():
        logger.info("=" * 50)
        logger.info("Testing: %s", name)
        for symbol in ASSETS:
            try:
                r = fn(symbol)
                all_results.append({
                    "levier": name,
                    "asset": symbol,
                    "trades": r.n_trades,
                    "pnl": round(r.total_pnl, 2),
                    "pnl_pct": round(r.total_pnl_pct, 2),
                    "win_rate": round(r.win_rate, 1),
                    "sharpe": round(r.sharpe, 2),
                    "max_dd": round(r.max_drawdown_pct, 2),
                    "avg_win": round(r.avg_win, 2),
                    "avg_loss": round(r.avg_loss, 2),
                })
                logger.info("  %s: %d trades, PnL=$%.0f, Sharpe=%.2f, DD=%.1f%%",
                           symbol, r.n_trades, r.total_pnl, r.sharpe, r.max_drawdown_pct)
            except Exception as e:
                logger.warning("  %s: FAIL (%s)", symbol, e)

    # ── Tableau comparatif ──
    logger.info("\n" + "=" * 80)
    logger.info("COMPARAISON DES LEVIERS (60j)")
    logger.info(f"{'Levier':<25} {'Asset':<12} {'Trades':>6} {'PnL':>8} {'Sharpe':>7} {'DD%':>6} {'Win%':>6}")
    logger.info("-" * 80)
    for r in all_results:
        logger.info(
            f"{r['levier']:<25} {r['asset']:<12} {r['trades']:>6} "
            f"${r['pnl']:>7.0f} {r['sharpe']:>7.2f} {r['max_dd']:>6.1f} {r['win_rate']:>6.1f}"
        )

    # ── Synthèse par levier (moyenne sur les actifs) ──
    logger.info("\n" + "=" * 80)
    logger.info("SYNTHÈSE PAR LEVIER (moyenne BTC+ETH)")
    for name in levers:
        rows = [r for r in all_results if r["levier"] == name]
        if not rows:
            continue
        avg_trades = sum(r["trades"] for r in rows) / len(rows)
        avg_pnl = sum(r["pnl"] for r in rows) / len(rows)
        avg_sharpe = sum(r["sharpe"] for r in rows) / len(rows)
        avg_dd = sum(r["max_dd"] for r in rows) / len(rows)
        logger.info(
            f"  {name:<25} → {avg_trades:.0f} trades | PnL=${avg_pnl:.0f} | "
            f"Sharpe={avg_sharpe:.2f} | DD={avg_dd:.1f}%"
        )

    # ── Test multi-actifs ──
    logger.info("\n" + "=" * 80)
    logger.info("TEST MULTI-ACTIFS (BTC, ETH, ADA, DOGE, LINK)")
    extra_assets = ["ADA/USDT", "DOGE/USDT", "LINK/USDT"]
    all_symbols = ASSETS + extra_assets
    multi_results = more_assets_test(all_symbols, days)
    for sym, r in multi_results.items():
        logger.info("  %s: %d trades, PnL=$%.0f, Sharpe=%.2f", sym, r.n_trades, r.total_pnl, r.sharpe)

    elapsed = time.time() - t0
    logger.info("\nBenchmark terminé en %.0f min", elapsed / 60)


if __name__ == "__main__":
    main()
