"""
main.py — Point d entree V2 Atlas Trader

Usage :
    python main.py --run-once          # un seul cycle quant
    python main.py --daemon            # boucle toutes les 15min (ou settings.yaml)
    python main.py --dashboard         # lance le dashboard Streamlit V2
    python main.py --backtest [--days N]  # backtest OOS
    python main.py --walkforward       # walk-forward 6m/3m

V2 : aucun LLM dans la boucle de decision — pipeline quant pur.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
import traceback
from datetime import datetime

logger = logging.getLogger("atlas.main")


def _signal_handler(sig, frame):
    logger.info("Signal recu — arret propre en cours...")
    sys.exit(0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atlas Trader V2 — quant pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-once", action="store_true", help="Un seul cycle quant")
    group.add_argument("--daemon", action="store_true", help="Boucle toutes les 15min")
    group.add_argument("--dashboard", action="store_true", help="Lance le dashboard V2")
    group.add_argument("--backtest", action="store_true", help="Backtest OOS complet")
    group.add_argument("--walkforward", action="store_true", help="Walk-forward 6m/3m")
    parser.add_argument("--interval", type=int, default=None, help="Intervalle secondes (override)")
    parser.add_argument("--asset", type=str, default=None, help="Actif (ex: BTC/USDT)")
    parser.add_argument("--days", type=int, default=90, help="Historique en jours")
    parser.add_argument("--log-level", type=str, default=None,
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def bootstrap() -> dict:
    """Initialise config, logging, DB."""
    from utils.config import load_settings
    from utils.logger import setup_logging
    from storage.database import init_db

    cfg = load_settings()
    log_cfg = cfg.get("logging", {})
    setup_logging(
        level=log_cfg.get("level", "INFO"),
        log_file=log_cfg.get("file_path", "logs/zeitgeist.log"),
        max_bytes=log_cfg.get("max_bytes", 5_242_880),
        backup_count=log_cfg.get("backup_count", 5),
        sqlite_db=log_cfg.get("sqlite_db", "storage/zeitgeist.db"),
    )
    init_db(log_cfg.get("sqlite_db", "storage/zeitgeist.db"))
    logger.info("=== Atlas Trader V2 started ===")
    return cfg


def run_single_cycle(asset: str, trigger: str = "scheduled") -> dict:
    """Lance un cycle V2 et retourne le resultat."""
    from graph.workflow import run_cycle
    return run_cycle(asset=asset, trigger=trigger)


def daemon_loop(asset: str, interval_s: int, cfg: dict | None = None) -> None:
    """Boucle principale : cycle quant toutes les interval_s secondes.

    Si cfg contient project.active_assets, tourne sur tous les actifs configurés.
    Sinon, tourne sur asset uniquement.
    """
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    from utils.session import MarketSession

    active_assets = (cfg or {}).get("project", {}).get("active_assets", [asset])
    if not active_assets:
        active_assets = [asset]

    logger.info(
        f"Daemon V2 démarré — actifs={active_assets} | intervalle_défaut={interval_s}s"
    )
    # Compteur d'erreurs par actif — un actif qui échoue systématiquement est mis en quarantaine.
    asset_errors: dict[str, int] = {a: 0 for a in active_assets}
    _QUARANTINE_AFTER = 3  # erreurs consécutives → mise en quarantaine

    while True:
        t0 = time.time()
        for sym in active_assets:
            if asset_errors.get(sym, 0) >= _QUARANTINE_AFTER:
                logger.debug(f"[{sym}] En quarantaine ({asset_errors[sym]} erreurs) — ignoré.")
                continue

            # Vérification session (forex / commodités non 24/7)
            sess = MarketSession(sym)
            if not sess.is_monitoring():
                logger.debug(f"[{sym}] Marché fermé (weekend) — cycle ignoré.")
                continue
            if not sess.is_open():
                logger.debug(f"[{sym}] Hors session de trading — cycle ignoré (monitoring actif).")
                continue

            try:
                result = run_single_cycle(asset=sym, trigger="scheduled")
                asset_errors[sym] = 0  # reset sur succès
                action = result.get("action", "flat").upper()
                capital = result.get("capital", 0)
                logger.info(f"[{sym}] Cycle OK — action={action} capital={capital:.0f}$")
            except KeyboardInterrupt:
                logger.info("Arrêt par KeyboardInterrupt.")
                return
            except Exception as exc:
                asset_errors[sym] = asset_errors.get(sym, 0) + 1
                logger.error(f"[{sym}] Erreur cycle (tentative {asset_errors[sym]}): {exc}")
                logger.debug(traceback.format_exc())
                if asset_errors[sym] == _QUARANTINE_AFTER:
                    logger.warning(f"[{sym}] Mis en quarantaine après {_QUARANTINE_AFTER} erreurs.")

        # Arrêt si TOUS les actifs sont en quarantaine
        if all(asset_errors.get(a, 0) >= _QUARANTINE_AFTER for a in active_assets):
            logger.critical("Tous les actifs en quarantaine — arrêt daemon.")
            sys.exit(1)

        # Intervalle dynamique : minimum de tous les actifs ouverts (le plus réactif gagne)
        open_intervals = [
            MarketSession(a).interval_seconds()
            for a in active_assets
            if MarketSession(a).is_open()
        ]
        wait_target = min(open_intervals) if open_intervals else interval_s
        elapsed = time.time() - t0
        wait = max(0.0, wait_target - elapsed)
        logger.debug(f"Prochain cycle dans {wait:.0f}s (intervalle={wait_target}s, durée={elapsed:.0f}s)")
        time.sleep(wait)


def cmd_backtest(asset: str, days: int) -> int:
    """Backtest en dehors d echantillon."""
    from quant.data_loader import fetch_history
    from quant.pipeline import run_pipeline, run_baseline, PipelineConfig
    from quant.validation import walk_forward_split
    from quant.backtest import buy_and_hold

    logger.info(f"Backtest {asset} {days}j...")
    ohlcv = fetch_history(symbol=asset, timeframe="15m", days=days)
    if len(ohlcv) < 500:
        logger.error(f"Donnees insuffisantes ({len(ohlcv)} barres).")
        return 1
    split = int(len(ohlcv) * 0.70)
    train_idx = ohlcv.index[:split]
    test_idx = ohlcv.index[split:]
    arts = run_pipeline(ohlcv, train_idx, test_idx, PipelineConfig(use_hmm=False))
    logger.info("=== Strategie V2 OOS ===\n" + arts.backtest.to_summary())
    bh = buy_and_hold(ohlcv.loc[test_idx])
    logger.info("=== Buy-and-Hold OOS ===\n" + bh.to_summary())
    bl = run_baseline(ohlcv.loc[test_idx])
    logger.info("=== Baseline Donchian OOS ===\n" + bl.to_summary())
    return 0


def cmd_walkforward(asset: str, days: int) -> int:
    """Walk-forward 6m train / 3m test."""
    from quant.data_loader import fetch_history
    from quant.pipeline import run_pipeline, PipelineConfig
    from quant.validation import walk_forward_split
    import pandas as pd

    ohlcv = fetch_history(symbol=asset, timeframe="15m", days=days)
    folds = list(walk_forward_split(ohlcv.index, train_months=6, test_months=3))
    if not folds:
        logger.error("Historique insuffisant pour walk-forward 6m/3m.")
        return 1
    rows = []
    for k, (train_idx, test_idx) in enumerate(folds, 1):
        logger.info(f"Fold {k}/{len(folds)}")
        arts = run_pipeline(ohlcv, train_idx, test_idx, PipelineConfig(use_hmm=False))
        m = arts.backtest.metrics
        rows.append({"fold": k, "sharpe": m["sharpe"], "ret": m["total_return"],
                     "dd": m["max_dd"], "n_trades": len(arts.backtest.trades)})
    df = pd.DataFrame(rows)
    logger.info("=== Walk-forward ===\n" + df.to_string(index=False))
    logger.info(f"Sharpe moyen: {df['sharpe'].mean():.2f} | Ret moyen: {df['ret'].mean():.2%}")
    return 0


def main(argv=None) -> int:
    args = parse_args()

    # Appliquer log-level CLI avant bootstrap si specifie
    if args.log_level:
        logging.basicConfig(level=getattr(logging, args.log_level))

    if args.dashboard:
        import subprocess
        import os
        dashboard_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "dashboard", "streamlit_v2.py"
        )
        cmd = [
            sys.executable, "-m", "streamlit", "run", dashboard_path,
            "--server.headless", "true",
            "--server.port", "8501",
            "--server.address", "0.0.0.0",
        ]
        logger.info(f"Lancement dashboard V2: {' '.join(cmd)}")
        return subprocess.call(cmd)

    cfg = bootstrap()

    if args.log_level:
        logging.getLogger().setLevel(getattr(logging, args.log_level))

    asset = args.asset or cfg.get("project", {}).get("asset", "BTC/USDT")
    interval_s = args.interval or cfg.get("project", {}).get("loop_interval_seconds", 900)

    if args.run_once:
        result = run_single_cycle(asset=asset, trigger="manual")
        print(f"Resultat: {result.get('action','?').upper()} | capital={result.get('capital','?')}$")
        return 0

    if args.daemon:
        daemon_loop(asset=asset, interval_s=interval_s, cfg=cfg)
        return 0

    if args.backtest:
        return cmd_backtest(asset=asset, days=args.days)

    if args.walkforward:
        return cmd_walkforward(asset=asset, days=max(args.days, 540))

    return 1


if __name__ == "__main__":
    sys.exit(main())
