"""
quant/multi_asset_runner.py — Walk-forward multi-actifs en parallèle.

Phase 5 : exécute run_walkforward() sur tous les actifs actifs et produit
un tableau comparatif avec verdict go/no-go par actif.

Usage :
    python main.py --multi-asset [--days 420]
    python -m quant.multi_asset_runner [--days 420] [--tf 5m]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger("zeitgeist.quant.multi_asset")


def _run_one(symbol: str, timeframe: str, total_days: int) -> dict[str, Any] | None:
    """Lance le walk-forward pour un actif unique (appelé dans un thread worker)."""
    from quant.walkforward import run_walkforward

    logger.info(f"[{symbol}] Démarrage walk-forward {timeframe} {total_days}j")
    try:
        result = run_walkforward(
            symbol=symbol,
            timeframe=timeframe,
            total_days=total_days,
            verbose=False,
        )
        if result:
            logger.info(
                f"[{symbol}] WF terminé — Sharpe médian={result.get('sharpe_median', 0):.2f} "
                f"| pass={result.get('pass_criteria', False)}"
            )
        return result
    except Exception as exc:
        logger.error(f"[{symbol}] walk-forward échec : {exc}")
        return None


def run_all_assets(
    timeframe: str = "5m",
    total_days: int = 420,
    max_workers: int = 2,
) -> pd.DataFrame:
    """Lance le walk-forward sur tous les actifs actifs et retourne un tableau comparatif.

    Args:
        timeframe: timeframe OHLCV (ex. "5m", "15m").
        total_days: jours d'historique à charger par actif.
        max_workers: threads parallèles max (limiter pour éviter la surcharge réseau).

    Returns:
        DataFrame — une ligne par actif avec les métriques agrégées et le verdict.
    """
    try:
        from utils.config import get_active_assets
        assets = get_active_assets()
    except Exception as exc:
        logger.error(f"Impossible de charger active_assets : {exc}")
        return pd.DataFrame()

    if not assets:
        logger.warning("active_assets est vide dans settings.yaml.")
        return pd.DataFrame()

    logger.info(f"Multi-asset runner : {len(assets)} actifs — {assets}")

    results: dict[str, dict | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(_run_one, symbol=a, timeframe=timeframe, total_days=total_days): a
            for a in assets
        }
        for future in concurrent.futures.as_completed(future_map):
            asset = future_map[future]
            try:
                results[asset] = future.result()
            except Exception as exc:
                logger.error(f"[{asset}] exception inattendue : {exc}")
                results[asset] = None

    rows = []
    for asset in assets:
        r = results.get(asset)
        if r is None:
            rows.append({
                "actif": asset,
                "sharpe_median": float("nan"),
                "sharpe_mean": float("nan"),
                "pf_moyen": float("nan"),
                "dd_moyen_%": float("nan"),
                "trades_total": 0,
                "p_value": float("nan"),
                "folds_positifs_%": float("nan"),
                "verdict": "❌ ERREUR",
            })
        else:
            pass_ok = r.get("pass_criteria", False)
            rows.append({
                "actif": asset,
                "sharpe_median": round(r.get("sharpe_median", 0.0), 3),
                "sharpe_mean": round(r.get("sharpe_mean", 0.0), 3),
                "pf_moyen": round(r.get("profit_factor_mean", 0.0), 3),
                "dd_moyen_%": round(r.get("max_dd_mean", 0.0) * 100, 2),
                "trades_total": int(r.get("trades_total", 0)),
                "p_value": round(r.get("p_value", 1.0), 4),
                "folds_positifs_%": round(r.get("pct_positive_folds", 0.0) * 100, 1),
                "verdict": "✓ GO-LIVE" if pass_ok else "✗ PAPER",
            })

    df = pd.DataFrame(rows)

    # Affichage récapitulatif
    logger.info("\n" + "=" * 80)
    logger.info("RÉSULTATS MULTI-ACTIFS")
    logger.info("=" * 80)
    logger.info(df.to_string(index=False))
    n_golive = (df["verdict"] == "✓ GO-LIVE").sum()
    logger.info(f"\n→ {n_golive}/{len(df)} actifs prêts pour le live.")
    logger.info("=" * 80)

    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Walk-forward multi-actifs — Atlas Trader V2")
    parser.add_argument("--days", default=420, type=int, help="Jours historiques")
    parser.add_argument("--tf",   default="5m",  dest="timeframe", help="Timeframe")
    parser.add_argument("--workers", default=2, type=int, help="Threads parallèles")
    args = parser.parse_args()

    result_df = run_all_assets(
        timeframe=args.timeframe,
        total_days=args.days,
        max_workers=args.workers,
    )
    if not result_df.empty:
        print(result_df.to_string(index=False))
