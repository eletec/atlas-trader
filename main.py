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
import os
import signal
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("atlas.main")


def _signal_handler(sig, frame):
    logger.info(f"Signal recu (sig={sig}) — arret propre en cours...")
    sys.exit(0)


def _sigusr1_handler(sig, frame):
    """SIGUSR1 — dump du stack (déclenché par le watchdog avant restart)."""
    import faulthandler
    logger.warning("[WATCHDOG] SIGUSR1 reçu — dump stack dans stderr")
    faulthandler.dump_traceback()


def _write_heartbeat(asset: str) -> None:
    """Écrit le fichier heartbeat pour cet actif (surveillé par le watchdog)."""
    try:
        Path(f"/tmp/atlas_heartbeat_{asset.replace('/', '_')}").write_text(
            str(time.time()), encoding="utf-8"
        )
    except OSError:
        pass  # /tmp inexistant en dehors du container — ignorer silencieusement


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atlas Trader V2 — quant pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-once", action="store_true", help="Un seul cycle quant")
    group.add_argument("--daemon", action="store_true", help="Boucle toutes les 15min")
    group.add_argument("--dashboard", action="store_true", help="Lance le dashboard V2")
    group.add_argument("--backtest", action="store_true", help="Backtest OOS complet")
    group.add_argument("--walkforward", action="store_true", help="Walk-forward 6m/3m")
    group.add_argument("--validate", action="store_true", help="Validation Phase 4 complete (PBO, MC, stress)")
    group.add_argument("--multi-asset", action="store_true", dest="multi_asset",
                       help="Walk-forward sur tous les actifs actifs")
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


def _run_daily_assets(cfg: dict, daily_errors: dict) -> None:
    """Exécute les actifs daily si l'heure d'exécution est atteinte.

    Appelé à chaque tour de la boucle principale ; les guards internes de
    DailyRunner empêchent une double exécution le même jour UTC.
    """
    from graph.workflow_daily import (
        run_daily_cycle,
        get_daily_active_assets,
        should_run_daily,
    )

    daily_assets = (
        cfg.get("quant", {}).get("daily_active_assets", [])
        or get_daily_active_assets()
    )
    if not daily_assets:
        return

    execution_hour = (
        cfg.get("quant", {}).get("daily_execution_hour_utc")
        or cfg.get("project", {}).get("daily_execution_hour_utc", 18)
    )
    if not should_run_daily(int(execution_hour)):
        return

    _QUARANTINE_AFTER = 3
    for sym in daily_assets:
        if daily_errors.get(sym, 0) >= _QUARANTINE_AFTER:
            logger.debug(f"[daily/{sym}] En quarantaine — ignoré.")
            continue
        try:
            result = run_daily_cycle(asset=sym, trigger="scheduled")
            daily_errors[sym] = 0
            action  = result.get("action", "flat").upper()
            capital = result.get("capital", 0)
            logger.info(
                f"[daily/{sym}] Cycle OK — action={action} capital={capital:.0f}$ "
                f"regime={result.get('regime','?')} prob_up={result.get('prob_up')}"
            )
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            daily_errors[sym] = daily_errors.get(sym, 0) + 1
            logger.error(f"[daily/{sym}] Erreur ({daily_errors[sym]}): {exc}")
            logger.error(traceback.format_exc())


def daemon_loop(asset: str, interval_s: int, cfg: dict | None = None) -> None:
    """Boucle principale : cycle quant toutes les interval_s secondes.

    Si cfg contient project.active_assets, tourne sur tous les actifs configurés.
    Sinon, tourne sur asset uniquement.
    """
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGUSR1, _sigusr1_handler)

    from utils.session import MarketSession

    active_assets = (cfg or {}).get("project", {}).get("active_assets", [asset])
    if not active_assets:
        active_assets = [asset]

    logger.info(
        f"Daemon V2 démarré — actifs={active_assets} | intervalle_défaut={interval_s}s"
    )
    # Compteur d'erreurs par actif — un actif qui échoue systématiquement est mis en quarantaine.
    asset_errors: dict[str, int] = {a: 0 for a in active_assets}
    daily_errors: dict[str, int] = {}          # erreurs actifs daily
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
            # Hors session : cycle "monitor" (analyse + historique, pas d'entrée)
            _trigger = "scheduled" if sess.is_open() else "monitor"

            try:
                result = run_single_cycle(asset=sym, trigger=_trigger)
                asset_errors[sym] = 0  # reset sur succès
                action = result.get("action", "flat").upper()
                capital = result.get("capital", 0)
                logger.info(f"[{sym}] Cycle OK — action={action} capital={capital:.0f}$")
                _write_heartbeat(sym)
            except KeyboardInterrupt:
                logger.info("Arrêt par KeyboardInterrupt.")
                return
            except Exception as exc:
                asset_errors[sym] = asset_errors.get(sym, 0) + 1
                logger.error(f"[{sym}] Erreur cycle (tentative {asset_errors[sym]}): {exc}")
                logger.error(traceback.format_exc())
                if asset_errors[sym] == _QUARANTINE_AFTER:
                    logger.warning(f"[{sym}] Mis en quarantaine après {_QUARANTINE_AFTER} erreurs.")

        # Arrêt si TOUS les actifs sont en quarantaine
        if all(asset_errors.get(a, 0) >= _QUARANTINE_AFTER for a in active_assets):
            logger.critical("Tous les actifs en quarantaine — arrêt daemon.")
            sys.exit(1)

        # ── Pipeline daily (FX/métaux) ─────────────────────────────────────
        _run_daily_assets(cfg or {}, daily_errors)

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
    from quant.walkforward import run_walkforward

    result = run_walkforward(symbol=asset, timeframe="5m", total_days=max(days, 420))
    return 0 if result is not None else 1


def cmd_validate(asset: str, days: int) -> int:
    """Validation Phase 4 complete : WF + PBO + Monte Carlo + Stress tests."""
    from quant.validation import run_full_validation

    result = run_full_validation(
        symbol=asset,
        timeframe="5m",
        total_days=max(days, 420),
        n_mc_perms=5_000,
        verbose=True,
    )
    return 0 if result.get("pass_all") else 2


def cmd_multi_asset(days: int) -> int:
    """Walk-forward sur tous les actifs actifs — tableau comparatif."""
    from quant.multi_asset_runner import run_all_assets
    import pandas as pd

    df = run_all_assets(timeframe="5m", total_days=max(days, 420))
    if df.empty:
        logger.error("Aucun résultat — vérifier active_assets dans settings.yaml.")
        return 1
    logger.info("\n=== Résultats Multi-Actifs ===\n" + df.to_string(index=False))
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
        return cmd_walkforward(asset=asset, days=args.days)

    if args.validate:
        return cmd_validate(asset=asset, days=args.days)

    if args.multi_asset:
        return cmd_multi_asset(days=args.days)

    return 1


if __name__ == "__main__":
    sys.exit(main())
