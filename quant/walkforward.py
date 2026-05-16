"""quant/walkforward.py — Validation walk-forward sur données historiques.

Usage:
    python -m quant.walkforward [--symbol BTC/USDT] [--tf 5m] [--days 420]

Protocole (3 IA convergentes) :
    - Fenêtre train : 90 jours
    - Fenêtre test  : 30 jours (Out-Of-Sample pur)
    - Glissement    : 30 jours (aucun chevauchement OOS)
    - Minimum 8 folds → 12 mois de test OOS
    - Métriques par fold + agrégat final
    - Test de permutation (500 shuffles) → p-value de l'edge
    - Critères go-live avec bilan binaire

Critères de passage en live :
    - Sharpe médian OOS > 0.5
    - % folds avec Sharpe > 0 ≥ 60 %
    - Profit Factor moyen > 1.2
    - Max DrawDown moyen < 20 %
    - Nombre de trades total ≥ 250
    - p-value (test de permutation unilatéral) < 0.10
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("zeitgeist.quant.walkforward")

# ── Paramètres du protocole ───────────────────────────────────────────────────
TRAIN_DAYS: int = 90
TEST_DAYS:  int = 30
STEP_DAYS:  int = 30   # pas de glissement = TEST_DAYS (aucun chevauchement OOS)
MIN_FOLDS:  int = 12   # F.1 : 12 folds → 450j OOS pour couvrir bull+bear+chop (Grok+DeepSeek)
MAX_FOLDS:  int = 24
PERM_ITER:  int = 500  # 500 suffisent pour p-value ±0.02 ; mettre 1000 en prod


@dataclass
class FoldResult:
    fold:         int
    train_start:  str
    test_start:   str
    test_end:     str
    sharpe:       float
    total_return: float
    max_dd:       float
    win_rate:     float
    profit_factor: float
    n_trades:     int
    error:        str | None = field(default=None)


def _bars_per_day(timeframe: str) -> int:
    mapping = {"1m": 1440, "3m": 480, "5m": 288, "15m": 96, "1h": 24, "4h": 6, "1d": 1}
    return mapping.get(timeframe, 288)


def _safe_metric(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
    v = metrics.get(key, default)
    return float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else default


def run_walkforward(
    symbol: str = "BTC/USDT",
    timeframe: str = "5m",
    total_days: int = 420,
    verbose: bool = True,
) -> dict[str, Any] | None:
    """Lance la validation walk-forward complète.

    Returns:
        dict avec clés "folds" (DataFrame), "p_value" (float), "pass_criteria" (bool),
        ou None si erreur.
    """
    logger.info("=" * 60)
    logger.info(f"Walk-forward  {symbol}  {timeframe}  —  {total_days} jours historiques")
    logger.info(f"Protocole : {TRAIN_DAYS}j train / {TEST_DAYS}j test / +{STEP_DAYS}j par fold")
    logger.info("=" * 60)

    # 1. Chargement des données historiques ───────────────────────────────────
    try:
        from quant.data_loader import fetch_history
        ohlcv = fetch_history(symbol=symbol, timeframe=timeframe, days=total_days, cache=True)
    except Exception as exc:
        logger.error(f"fetch_history échec : {exc}")
        return None

    min_bars = (_bars_per_day(timeframe) * (TRAIN_DAYS + TEST_DAYS))
    if len(ohlcv) < min_bars:
        logger.error(f"Données insuffisantes : {len(ohlcv)} barres (min {min_bars})")
        return None
    logger.info(f"Données : {len(ohlcv)} barres  [{str(ohlcv.index[0])[:19]} → {str(ohlcv.index[-1])[:19]}]")

    # 2. Walk-forward rolling ─────────────────────────────────────────────────
    from quant.pipeline import PipelineConfig, run_pipeline

    cfg = PipelineConfig()
    bpd = _bars_per_day(timeframe)
    train_bars = TRAIN_DAYS * bpd
    test_bars  = TEST_DAYS  * bpd
    step_bars  = STEP_DAYS  * bpd

    fold_results: list[FoldResult] = []

    for fold_idx in range(MAX_FOLDS):
        start    = fold_idx * step_bars
        train_end = start + train_bars
        test_end  = train_end + test_bars

        if test_end > len(ohlcv):
            break

        fold_ohlcv = ohlcv.iloc[start:test_end]
        train_idx  = fold_ohlcv.index[:train_bars]
        test_idx   = fold_ohlcv.index[train_bars:]

        try:
            artifacts = run_pipeline(
                fold_ohlcv,
                train_idx=train_idx,
                test_idx=test_idx,
                config=cfg,
            )
            m = artifacts.backtest.metrics
            trades = getattr(artifacts.backtest, "trades", [])
            n_trades = len(trades) if trades is not None else 0

            result = FoldResult(
                fold=fold_idx + 1,
                train_start=str(train_idx[0])[:10],
                test_start=str(test_idx[0])[:10],
                test_end=str(test_idx[-1])[:10],
                sharpe=_safe_metric(m, "sharpe"),
                total_return=_safe_metric(m, "total_return"),
                max_dd=_safe_metric(m, "max_dd"),
                win_rate=_safe_metric(m, "win_rate"),
                profit_factor=_safe_metric(m, "profit_factor"),
                n_trades=n_trades,
            )
            fold_results.append(result)

            if verbose:
                _status = "✓" if result.sharpe > 0 else "✗"
                logger.info(
                    f"Fold {fold_idx+1:2d}  [{result.test_start} → {result.test_end}]  "
                    f"{_status}  Sharpe={result.sharpe:+.2f}  "
                    f"DD={result.max_dd:.1%}  WR={result.win_rate:.1%}  "
                    f"PF={result.profit_factor:.2f}  Trades={result.n_trades}"
                )

        except Exception as exc:
            logger.warning(f"Fold {fold_idx+1} échec : {exc}")
            fold_results.append(
                FoldResult(
                    fold=fold_idx + 1,
                    train_start=str(train_idx[0])[:10],
                    test_start=str(test_idx[0])[:10],
                    test_end=str(test_idx[-1])[:10],
                    sharpe=0.0,
                    total_return=0.0,
                    max_dd=0.0,
                    win_rate=0.0,
                    profit_factor=0.0,
                    n_trades=0,
                    error=str(exc),
                )
            )

    valid_folds = [r for r in fold_results if r.error is None]
    if not valid_folds:
        logger.error("Aucun fold réussi — abandon.")
        return None

    # 3. Métriques agrégées ───────────────────────────────────────────────────
    df = pd.DataFrame([vars(r) for r in valid_folds])

    sharpe_med      = float(df["sharpe"].median())
    sharpe_mean     = float(df["sharpe"].mean())
    pct_positive    = float((df["sharpe"] > 0).mean())
    ret_mean        = float(df["total_return"].mean())
    dd_mean         = float(df["max_dd"].mean())
    wr_mean         = float(df["win_rate"].mean())
    pf_mean         = float(df["profit_factor"].mean())
    trades_per_fold = float(df["n_trades"].mean())
    trades_total    = int(df["n_trades"].sum())

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"RÉSULTATS AGRÉGÉS — {len(valid_folds)} folds valides / {len(fold_results)} tentés")
    logger.info("=" * 60)
    logger.info(f"  Sharpe médian OOS    : {sharpe_med:+.3f}")
    logger.info(f"  Sharpe moyen OOS     : {sharpe_mean:+.3f}")
    logger.info(f"  % folds Sharpe > 0   : {pct_positive:.0%}")
    logger.info(f"  Total return moyen   : {ret_mean:.2%}")
    logger.info(f"  Max DD moyen         : {dd_mean:.2%}")
    logger.info(f"  Win rate moyen       : {wr_mean:.2%}")
    logger.info(f"  Profit Factor moyen  : {pf_mean:.2f}")
    logger.info(f"  Trades / fold        : {trades_per_fold:.0f}")
    logger.info(f"  Trades total OOS     : {trades_total}")

    # 4. Test de permutation — block sign randomization (GPT + DeepSeek)
    # Block size ≈20% des folds pour préserver la dépendance temporelle (autocorrélation)
    logger.info("")
    logger.info(f"--- Test de permutation H₀ : edge = 0 ({PERM_ITER} itérations, block bootstrap) ---")
    rng = np.random.default_rng(42)
    sharpe_obs = sharpe_mean
    null_dist = np.empty(PERM_ITER)
    sharpe_vals = df["sharpe"].values.copy()
    n_folds = len(sharpe_vals)
    block_size = max(2, n_folds // 5)   # ~20% de la série par bloc

    for i in range(PERM_ITER):
        # Randomisation des signes par blocs corrélés (préserve l'autocorrélation entre folds consécutifs)
        n_blocks = (n_folds + block_size - 1) // block_size
        block_signs = rng.choice([-1.0, 1.0], size=n_blocks)
        signs = np.repeat(block_signs, block_size)[:n_folds]
        null_dist[i] = float((sharpe_vals * signs).mean())

    p_value = float((null_dist >= sharpe_obs).mean())
    logger.info(f"  Sharpe moyen observé : {sharpe_obs:+.3f}")
    logger.info(f"  Taille de bloc       : {block_size} folds")
    logger.info(f"  p-value (unilatérale): {p_value:.3f}  ← {'✓ SIGNIFICATIF' if p_value < 0.10 else '✗ NON SIGNIFICATIF'}")

    # 5. Critères de passage en live ──────────────────────────────────────────
    logger.info("")
    logger.info("--- CRITÈRES DE PASSAGE EN LIVE ---")
    criteria = {
        f"Sharpe médian OOS > 0.5  [{sharpe_med:+.3f}]":      sharpe_med      > 0.5,
        f"% folds Sharpe>0 ≥ 60%  [{pct_positive:.0%}]":      pct_positive    >= 0.60,
        f"Profit Factor moyen > 1.2  [{pf_mean:.2f}]":         pf_mean         > 1.2,
        f"Max DD moyen < 20%  [{dd_mean:.1%}]":                dd_mean         < 0.20,
        f"Trades total ≥ 250  [{trades_total}]":               trades_total    >= 250,
        f"p-value < 0.10  [{p_value:.3f}]":                    p_value         < 0.10,
    }
    all_ok = all(criteria.values())
    for name, ok in criteria.items():
        logger.info(f"  {'✓' if ok else '✗'}  {name}")
    logger.info("")
    verdict = "PASSAGE EN LIVE AUTORISÉ ✓" if all_ok else "PAPIER TRADING UNIQUEMENT ✗"
    logger.info(f"→ {verdict}")
    logger.info("=" * 60)

    return {
        "folds": df,
        "p_value": p_value,
        "pass_criteria": all_ok,
        "sharpe_median": sharpe_med,
        "sharpe_mean": sharpe_mean,
        "pct_positive_folds": pct_positive,
        "profit_factor_mean": pf_mean,
        "max_dd_mean": dd_mean,
        "trades_total": trades_total,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Walk-forward validation — Atlas Trader V2")
    parser.add_argument("--symbol",  default="BTC/USDT",  help="Paire de trading (ex: ETH/USDT)")
    parser.add_argument("--tf",      default="5m",         dest="timeframe", help="Timeframe (5m, 15m, 1h…)")
    parser.add_argument("--days",    default=420,           type=int, help="Jours historiques à charger")
    parser.add_argument("--quiet",   action="store_true",  help="Mode silencieux (agrégats seulement)")
    args = parser.parse_args()

    run_walkforward(
        symbol=args.symbol,
        timeframe=args.timeframe,
        total_days=args.days,
        verbose=not args.quiet,
    )
