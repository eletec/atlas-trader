#!/usr/bin/env python3
"""
run_backtest_v2.py — Backtest du pipeline quantitatif V2 sur tous les actifs configurés.

Utilise le vrai moteur V2 (RegimeDetector + SignalModel + RiskManager) en mode batch :
  - Split train/test (train_fraction)
  - Fit sur la partie train
  - Simulation walk-forward sur la partie test
  - Métriques : win rate, P&L, Sharpe, max drawdown, profit factor

Usage :
    cd zeitgeist-trader
    python run_backtest_v2.py                              # tous les active_assets, config YAML
    python run_backtest_v2.py --days 90                    # 3 mois d'historique
    python run_backtest_v2.py --symbols BTC/USDT XAU/USD   # actifs spécifiques
    python run_backtest_v2.py --timeframe 1h               # timeframe 1h (conseillé forex)
    python run_backtest_v2.py --sweep                      # optimisation paramétrique
    python run_backtest_v2.py --no-cache                   # force re-téléchargement

Notes sur la disponibilité des données :
    Crypto  (Binance)   : jusqu'à 730 jours de 15m disponibles
    Forex / Commo (yfinance) : max 59 jours de données intraday (15m / 1h)
                               illimité en timeframe 1d
    → Pour XAU, XAG, WTI, EUR, GBP sur une longue période : --timeframe 1d --days 730
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_backtest_v2")

# Actifs routés via yfinance — limités à 59j en intraday
_YAHOO_ASSETS = {"XAU/USD", "XAG/USD", "WTI/USD", "EUR/USD", "GBP/USD"}


def _load_config() -> dict:
    try:
        from utils.config import load_settings
        return load_settings()
    except Exception as exc:
        logger.warning(f"Impossible de charger settings.yaml : {exc}")
        return {}


def _active_assets(cfg: dict) -> list[str]:
    return cfg.get("project", {}).get("active_assets", ["BTC/USDT"])


def _quant_defaults(cfg: dict) -> tuple[str, int, float]:
    """Retourne (timeframe, history_days, train_fraction) depuis quant config."""
    q = cfg.get("quant", {})
    return (
        q.get("timeframe", "15m"),
        int(q.get("history_days", 90)),
        float(q.get("train_fraction", 0.70)),
    )


def _warn_yfinance_limit(symbols: list[str], timeframe: str, days: int) -> None:
    yf_assets = [s for s in symbols if s in _YAHOO_ASSETS]
    if not yf_assets:
        return
    if timeframe in ("15m", "1h") and days > 59:
        logger.warning(
            f"⚠  yfinance limite les données intraday à 59 jours pour : {yf_assets}\n"
            f"   Données réelles utilisées : 59j (demandé : {days}j)\n"
            f"   Pour Pour un backtest long sur ces actifs : --timeframe 1d --days 730"
        )


def _print_summary(results: dict, metrics_by_symbol: dict) -> None:
    """Affiche un tableau récapitulatif en console."""
    print("\n" + "=" * 80)
    print(f"{'ACTIF':<14} {'TRADES':>7} {'WIN%':>7} {'P&L $':>10} "
          f"{'SHARPE':>8} {'MAX DD $':>10} {'PF':>6}")
    print("-" * 80)

    portfolio_pnl = 0.0
    for sym, m in metrics_by_symbol.items():
        n_active = m["n_buy"] + m["n_sell"]
        if n_active == 0:
            print(f"{sym:<14} {'—':>7} {'—':>7} {'—':>10} {'—':>8} {'—':>10} {'—':>6}  ⚠ aucun trade")
            continue
        pnl_sign = "+" if m["total_pnl"] >= 0 else ""
        print(
            f"{sym:<14} {n_active:>7} {m['win_rate']*100:>6.1f}% "
            f"{pnl_sign}{m['total_pnl']:>9.2f} "
            f"{m['sharpe']:>8.3f} {m['max_drawdown']:>10.2f} "
            f"{m['profit_factor']:>6.2f}"
        )
        portfolio_pnl += m["total_pnl"]

    print("-" * 80)
    pnl_sign = "+" if portfolio_pnl >= 0 else ""
    print(f"{'PORTFOLIO':<14} {'':>7} {'':>7} {pnl_sign}{portfolio_pnl:>9.2f}")
    print("=" * 80)


def main() -> None:
    cfg = _load_config()
    default_tf, default_days, default_train_frac = _quant_defaults(cfg)
    default_symbols = _active_assets(cfg)

    parser = argparse.ArgumentParser(
        description="Backtest du pipeline V2 sur les actifs configurés",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--symbols", nargs="+", default=default_symbols, metavar="SYM",
        help=f"Actifs à tester (défaut: active_assets du YAML → {default_symbols})",
    )
    parser.add_argument(
        "--days", type=int, default=default_days, metavar="N",
        help=f"Profondeur historique en jours (défaut: {default_days} depuis quant.history_days)",
    )
    parser.add_argument(
        "--timeframe", default=default_tf, metavar="TF",
        help=f"Granularité OHLCV (défaut: {default_tf} depuis quant.timeframe)",
    )
    parser.add_argument(
        "--train-frac", type=float, default=default_train_frac, metavar="F",
        help=f"Fraction train/test (défaut: {default_train_frac})",
    )
    parser.add_argument(
        "--sweep", action="store_true",
        help="Activer l'optimisation paramétrique (grille p_up / p_dn thresholds)",
    )
    parser.add_argument(
        "--output", default="backtest_report.html", metavar="FILE",
        help="Fichier HTML de sortie (défaut: backtest_report.html)",
    )
    parser.add_argument(
        "--no-cache", action="store_true", dest="no_cache",
        help="Force le re-téléchargement des données (ignore le cache)",
    )
    parser.add_argument(
        "--horizon", type=int, default=None, metavar="N",
        help="Override horizon_bars (barres à prédire en avance). Ex: --horizon 4 sur 1h = prédire 4h",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Affichage détaillé (DEBUG)",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Override horizon_bars si --horizon fourni
    if args.horizon is not None:
        try:
            from quant.config import get_quant_cfg
            _cfg = get_quant_cfg(reload=True)
            _cfg.horizon_bars = args.horizon
            import quant.config as _qcfg_mod
            _qcfg_mod._CACHE = _cfg
            logger.info(f"horizon_bars overridé → {args.horizon} barres")
        except Exception as exc:
            logger.warning(f"Impossible d'overrider horizon_bars : {exc}")

    # ── Infos de démarrage ─────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"  Atlas Trader — Backtest V2")
    logger.info(f"  Actifs   : {args.symbols}")
    logger.info(f"  Période  : {args.days} jours | TF: {args.timeframe}")
    logger.info(f"  Train    : {args.train_frac*100:.0f}% | Test: {(1-args.train_frac)*100:.0f}%")
    logger.info(f"  Mode     : {'sweep paramétrique' if args.sweep else 'run standard'}")
    logger.info("=" * 60)

    _warn_yfinance_limit(args.symbols, args.timeframe, args.days)

    # ── Import runner ──────────────────────────────────────────────────────
    try:
        from backtest.runner import (
            run_backtest, run_sweep, compute_metrics,
            SWEEP_GRID,
        )
        from backtest.report import generate_report
        from backtest.sim_engine import SimTrade
    except ImportError as exc:
        logger.error(f"Impossible d'importer backtest/ : {exc}")
        sys.exit(1)

    output_path = Path(args.output)
    force = args.no_cache

    # ── Run ───────────────────────────────────────────────────────────────
    try:
        if args.sweep:
            logger.info(f"Grille paramétrique : {SWEEP_GRID}")
            # Le sweep utilise une db temporaire (pas de persistance)
            import sqlite3, tempfile
            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as _tf:
                _db_path = Path(_tf.name)
            from backtest.runner import init_db
            db_conn = init_db(_db_path)

            best = run_sweep(
                symbols=args.symbols,
                days=args.days,
                timeframe=args.timeframe,
                db_conn=db_conn,
                force_refresh=force,
            )
            db_conn.close()

            # Run final avec les meilleurs paramètres globaux
            best_global = max(best.values(), key=lambda x: x["sharpe"]) if best else {}
            config_final = best_global.get("params", {})
            logger.info(f"\n→ Meilleurs paramètres globaux : {config_final}")
            run_id, results = run_backtest(
                symbols=args.symbols, days=args.days, timeframe=args.timeframe,
                config_override=config_final, db_conn=None, force_refresh=False,
            )
        else:
            run_id, results = run_backtest(
                symbols=args.symbols, days=args.days, timeframe=args.timeframe,
                db_conn=None, force_refresh=force,
            )
    except KeyboardInterrupt:
        logger.info("\nInterrompu par l'utilisateur.")
        sys.exit(0)
    except Exception as exc:
        logger.error(f"Erreur fatale : {exc}", exc_info=True)
        sys.exit(1)

    if not results:
        logger.error("Aucun résultat — vérifier la disponibilité des données.")
        sys.exit(1)

    # ── Métriques + rapport ────────────────────────────────────────────────
    all_trades: list[SimTrade] = []
    metrics_by_symbol: dict[str, dict] = {}

    for sym, trades in results.items():
        m = compute_metrics(trades)
        metrics_by_symbol[sym] = m
        all_trades.extend(trades)

    _print_summary(results, metrics_by_symbol)

    try:
        report_path = generate_report(
            run_id=run_id,
            trades=all_trades,
            metrics_by_symbol=metrics_by_symbol,
            output_path=output_path,
        )
        logger.info(f"\n✅ Rapport HTML généré : {report_path}")
    except Exception as exc:
        logger.warning(f"Génération rapport HTML échouée : {exc}")

    # ── Résumé final ─────────────────────────────────────────────────────
    n_total_trades = sum(
        m["n_buy"] + m["n_sell"] for m in metrics_by_symbol.values()
    )
    portfolio_pnl = sum(m["total_pnl"] for m in metrics_by_symbol.values())
    logger.info(
        f"\nBilan global : {n_total_trades} trades | "
        f"P&L portfolio : {'+'if portfolio_pnl>=0 else ''}{portfolio_pnl:.2f}$ | "
        f"Run ID : {run_id}"
    )


if __name__ == "__main__":
    main()
