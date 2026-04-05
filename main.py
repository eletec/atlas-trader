"""
main.py — Point d'entrée principal de Atlas Trader
Usage :
    python main.py --run-once           # un seul cycle
    python main.py --daemon             # boucle toutes les 15min
    python main.py --daemon --interval 300   # boucle toutes les 5min
    python main.py --dashboard          # lancer uniquement le dashboard Streamlit
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
import traceback

logger = logging.getLogger("zeitgeist.main")

# Événements inter-threads
_shutdown_event = threading.Event()   # arrêt propre global
_force_cycle_event = threading.Event()  # cycle immédiat demandé par le monitor

# Prix live partagé entre threads (mis à jour par le WebSocket)
_live_price: dict = {"price": 0.0, "ts": 0.0}  # thread-safe : GIL suffit pour float
_live_price_lock = threading.Lock()


def _websocket_price_loop(symbol: str) -> None:
    """
    Thread WebSocket Binance — met à jour _live_price en continu.
    Donne un prix tick-by-tick (~100ms) au lieu du polling 60s.
    Fallback automatique sur polling si WebSocket indisponible.
    """
    ws_symbol = symbol.replace("/", "").lower()  # BTC/USDT → btcusdt
    url = f"wss://stream.binance.com:9443/ws/{ws_symbol}@miniTicker"
    logger.info(f"WebSocket prix démarré : {url}")

    while not _shutdown_event.is_set():
        try:
            import websocket as ws_lib  # websocket-client

            def on_message(ws, msg):
                import json
                data = json.loads(msg)
                price = float(data.get("c", 0))  # 'c' = close price
                if price > 0:
                    with _live_price_lock:
                        _live_price["price"] = price
                        _live_price["ts"] = time.time()

            def on_error(ws, err):
                logger.debug(f"WebSocket prix erreur : {err}")

            def on_close(ws, *args):
                logger.debug("WebSocket prix fermé — reconnexion dans 5s")

            conn = ws_lib.WebSocketApp(
                url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            conn.run_forever(ping_interval=20, ping_timeout=10)
        except ImportError:
            # websocket-client non disponible → polling
            logger.warning("websocket-client absent — prix via polling toutes les 5s")
            try:
                from agents.market_data_agent import MarketDataAgent
                mda = MarketDataAgent()
                ind = mda.get_indicators(symbol)
                price = ind.get("price", 0.0)
                if price > 0:
                    with _live_price_lock:
                        _live_price["price"] = price
                        _live_price["ts"] = time.time()
            except Exception:
                pass
        except Exception as exc:
            logger.debug(f"WebSocket prix crash : {exc}")

        if not _shutdown_event.is_set():
            _shutdown_event.wait(5)  # reconnexion dans 5s

    logger.info("WebSocket prix arrêté.")


def _signal_handler(sig, frame):
    logger.info("Signal d'arrêt reçu — arrêt propre en cours...")
    _shutdown_event.set()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Atlas Trader — Système de trading IA autonome"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--run-once", action="store_true",
        help="Exécute un seul cycle de trading et quitte"
    )
    group.add_argument(
        "--daemon", action="store_true",
        help="Lance la boucle principale en continu"
    )
    group.add_argument(
        "--dashboard", action="store_true",
        help="Lance uniquement le dashboard Streamlit"
    )
    group.add_argument(
        "--post-mortem", action="store_true",
        help="Lance uniquement l'agent post-mortem"
    )
    parser.add_argument(
        "--interval", type=int, default=None,
        help="Intervalle en secondes entre les cycles (override settings.yaml)"
    )
    parser.add_argument(
        "--asset", type=str, default=None,
        help="Actif à trader (ex: BTC/USDT)"
    )
    parser.add_argument(
        "--log-level", type=str, default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Niveau de log (override settings.yaml)"
    )
    return parser.parse_args()


def bootstrap() -> dict:
    """Initialise le système : config, logging, DB."""
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
    logger.info("=== Atlas Trader démarré ===")
    logger.info(
        f"Asset: {cfg.get('project', {}).get('asset', 'BTC/USDT')} | "
        f"Mode: {cfg.get('risk', {}).get('mode', 'balanced')} | "
        f"LLM: {cfg.get('llm', {}).get('model', '?')}"
    )
    return cfg


def run_single_cycle(asset: str, trigger: str = "scheduled") -> dict:
    """Lance un seul cycle et retourne l'état final."""
    from graph.workflow import run_cycle
    return run_cycle(asset=asset, trigger=trigger)


def fast_monitor_loop(asset: str, monitor_interval: int, breaking_threshold: float) -> None:
    """
    Boucle de surveillance rapide (toutes les ~60s).
    - Détecte les breaking news (score > threshold) → déclenche un cycle immédiat
    - Vérifie SL/TP via prix WebSocket (tick-by-tick) ou polling 60s
    - Surveille le score marché continu → cycle forcé si signal technique extrême
    """
    logger.info(f"Monitor rapide démarré — intervalle {monitor_interval}s | seuil breaking={breaking_threshold}")
    from collections import deque
    last_news_titles: deque[str] = deque(maxlen=500)  # borné — évite la fuite mémoire sur durée longue
    _last_news_titles_set: set[str] = set()  # lookup O(1) — rebuildé depuis le deque
    _last_market_score_trigger = 0.0  # anti-spam score marché (pas d'annotation — nonlocal l'exige)

    while not _shutdown_event.is_set():
        t0 = time.time()
        try:
            # --- 1. Breaking news ---
            from agents.fast_news_listener import FastNewsListener
            listener = FastNewsListener()
            items = listener.fetch_all(asset)
            breaking = [
                n for n in items
                if n.get("relevance_score", 0) >= breaking_threshold
                and n.get("title", "") not in _last_news_titles_set
            ]
            if breaking:
                titles = [n["title"][:80] for n in breaking[:3]]
                for n in breaking:
                    last_news_titles.append(n["title"])
                _last_news_titles_set.clear()
                _last_news_titles_set.update(last_news_titles)
                # Ne forcer un cycle que si aucun cycle n'est déjà en cours
                from utils.cycle_lock import is_locked as _cycle_locked
                if not _cycle_locked():
                    logger.warning(
                        f"[MONITOR] {len(breaking)} breaking news détectée(s) — cycle forcé\n"
                        + "\n".join(f"  · {t}" for t in titles)
                    )
                    _force_cycle_event.set()
                else:
                    logger.info(
                        f"[MONITOR] {len(breaking)} breaking news — cycle déjà actif, ignoré\n"
                        + "\n".join(f"  · {t}" for t in titles)
                    )

            # --- 2. Surveillance SL/TP — prix WebSocket (ou fallback polling) ---
            try:
                from storage.database import get_open_positions, close_position
                from agents.market_data_agent import MarketDataAgent

                open_positions = [
                    p for p in get_open_positions()
                    if p.get("sl_price") and p.get("tp_price")
                ]
                if open_positions:
                    # Utiliser le prix WebSocket si récent (< 10s), sinon polling
                    with _live_price_lock:
                        ws_price = _live_price["price"]
                        ws_age = time.time() - _live_price["ts"]
                    if ws_price > 0 and ws_age < 10:
                        price = ws_price
                        indicators = {"price": price}
                    else:
                        mda = MarketDataAgent()
                        indicators = mda.get_indicators(asset)
                        price = indicators.get("price", 0)
                    if price > 0:
                        for pos in open_positions:
                            pos_action = pos["action"]
                            sl = float(pos["sl_price"])
                            tp = float(pos["tp_price"])
                            cid = pos.get("cycle_id", "?")
                            if pos_action == "BUY":
                                if price <= sl:
                                    logger.warning(
                                        f"[MONITOR] STOP-LOSS BUY — cycle {cid} | "
                                        f"prix={price:.2f} <= SL={sl:.2f} → clôture"
                                    )
                                    close_position(cid, price, reason="STOP-LOSS")
                                elif price >= tp:
                                    logger.info(
                                        f"[MONITOR] TAKE-PROFIT BUY — cycle {cid} | "
                                        f"prix={price:.2f} >= TP={tp:.2f} → clôture"
                                    )
                                    close_position(cid, price, reason="TAKE-PROFIT")
                            elif pos_action == "SELL":
                                if price >= sl:
                                    logger.warning(
                                        f"[MONITOR] STOP-LOSS SELL — cycle {cid} | "
                                        f"prix={price:.2f} >= SL={sl:.2f} → clôture"
                                    )
                                    close_position(cid, price, reason="STOP-LOSS")
                                elif price <= tp:
                                    logger.info(
                                        f"[MONITOR] TAKE-PROFIT SELL — cycle {cid} | "
                                        f"prix={price:.2f} <= TP={tp:.2f} → clôture"
                                    )
                                    close_position(cid, price, reason="TAKE-PROFIT")
            except Exception as exc:
                logger.debug(f"Monitor SL/TP ignoré : {exc}")

            # --- 3. Score marché continu — signal technique extrême ---
            # Déclenche un cycle immédiat si RSI/MACD très extrêmes SANS attendre 15min
            try:
                from agents.market_data_agent import MarketDataAgent
                from graph.workflow import _derive_market_score
                mda = MarketDataAgent()
                mkt = mda.get_indicators(asset)
                mkt_score = _derive_market_score(mkt)
                # Seuils extrêmes : score ≥ 85 (très bullish) ou ≤ 15 (très bearish)
                now = time.time()
                if (mkt_score >= 85 or mkt_score <= 15) and (now - _last_market_score_trigger > 1800):
                    from utils.cycle_lock import is_locked as _cycle_locked_mkt
                    if not _cycle_locked_mkt():
                        logger.warning(
                            f"[MONITOR] Signal marché extrême — score={mkt_score:.0f} "
                            f"(RSI={mkt.get('rsi_14', 0):.0f}) → cycle forcé"
                        )
                        _last_market_score_trigger = now
                        _force_cycle_event.set()
                    else:
                        logger.debug(f"[MONITOR] Signal extrême score={mkt_score:.0f} — cycle actif, ignoré")
                else:
                    logger.debug(f"[MONITOR] Market score={mkt_score:.0f} (RSI={mkt.get('rsi_14', 0):.0f})")
            except Exception as exc:
                logger.debug(f"Monitor market score ignoré : {exc}")

        except Exception as exc:
            logger.warning(f"[MONITOR] Erreur non bloquante : {exc}")

        elapsed = time.time() - t0
        # Garantir un délai minimum de 30s entre les itérations même si fetch_all()
        # a débordé sur l'intervalle cible — évite la boucle serrée sur fetches lents
        sleep_time = max(30, monitor_interval - elapsed)
        _shutdown_event.wait(sleep_time)

    logger.info("Monitor rapide arrêté.")


def run_daemon(asset: str, interval: int) -> None:
    """Boucle principale avec gestion des erreurs et redémarrage automatique."""
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Charger les paramètres du monitor
    from utils.config import load_settings
    cfg = load_settings()
    monitor_cfg = cfg.get("monitor", {})
    monitor_interval = monitor_cfg.get("interval_seconds", 60)
    breaking_threshold = monitor_cfg.get("breaking_news_threshold", 0.8)

    # Démarrer le WebSocket prix (tick-by-tick)
    ws_thread = threading.Thread(
        target=_websocket_price_loop,
        args=(asset,),
        daemon=True,
        name="ws-price",
    )
    ws_thread.start()

    # Démarrer le thread de surveillance rapide
    monitor_thread = threading.Thread(
        target=fast_monitor_loop,
        args=(asset, monitor_interval, breaking_threshold),
        daemon=True,
        name="fast-monitor",
    )
    monitor_thread.start()
    logger.info(f"Mode daemon — intervalle {interval}s — asset {asset}")

    cycle_count = 0
    consecutive_errors = 0

    while not _shutdown_event.is_set():
        cycle_count += 1
        t0 = time.time()
        forced = _force_cycle_event.is_set()
        _force_cycle_event.clear()

        _trigger = "monitor" if forced else "scheduled"
        if forced:
            logger.info(f"Cycle #{cycle_count} FORCÉ par le monitor (breaking news / SL/TP)")
        else:
            logger.info(f"Cycle #{cycle_count} démarré (planifié)")

        try:
            # Timeout global sur un cycle complet — 300s max (news+crawl+agents+LLM)
            # IMPORTANT: Thread daemon — un cycle bloqué ne retient PAS le processus
            # et n'empêche pas supervisord de le redémarrer proprement.
            # ThreadPoolExecutor est INTERDIT ici (threads non-daemon → processus zombie).
            _result_box: list = [None, None]  # [result, exception]
            _cycle_done = threading.Event()

            def _cycle_runner():
                try:
                    _result_box[0] = run_single_cycle(asset, _trigger)
                except Exception as _e:
                    _result_box[1] = _e
                finally:
                    _cycle_done.set()

            _cycle_thread = threading.Thread(
                target=_cycle_runner,
                name=f"cycle-{cycle_count}",
                daemon=True,  # DAEMON: ne bloque pas la sortie du processus
            )
            _cycle_thread.start()

            if not _cycle_done.wait(timeout=300):
                logger.error(f"Cycle #{cycle_count} TIMEOUT (300s) — abandon")
                # Libérer le lock que run_cycle() ne pourra pas relâcher
                from utils.cycle_lock import release as _force_release
                _force_release()
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    logger.critical("5 cycles consécutifs en erreur — arrêt d'urgence")
                    _shutdown_event.set()
                    import sys as _sys; _sys.exit(1)
                continue

            if _result_box[1] is not None:
                raise _result_box[1]
            state = _result_box[0]

            consecutive_errors = 0
            duration = time.time() - t0
            decision = (state.get("decision") or {}).get("action", "N/A")
            score = state.get("global_score", 0)
            logger.info(
                f"Cycle #{cycle_count} terminé — "
                f"{duration:.0f}s | {decision} | score={score:.0f}"
            )
            # Heartbeat — permet à un watchdog externe de détecter un freeze
            try:
                import pathlib
                pathlib.Path("/tmp/atlas_heartbeat").write_text(
                    f"{time.time()}\ncycle={cycle_count}\n{decision}\n"
                )
            except Exception:
                pass
        except KeyboardInterrupt:
            _shutdown_event.set()
            break
        except Exception as exc:
            consecutive_errors += 1
            logger.error(
                f"Cycle #{cycle_count} échoué ({consecutive_errors} consécutif): {exc}\n"
                + traceback.format_exc()
            )
            if consecutive_errors >= 5:
                logger.critical("5 cycles consécutifs en erreur — arrêt d'urgence")
                import sys as _sys; _sys.exit(1)

        # Lancer le post-mortem de façon asynchrone si nécessaire
        logger.debug("Post-mortem check starting...")
        _run_post_mortem_if_needed()
        logger.debug("Post-mortem check done.")

        # Attendre jusqu'au prochain cycle (ou interruption par le monitor)
        elapsed = time.time() - t0
        wait = max(0, interval - elapsed)
        if wait > 0:
            logger.debug(f"Prochain cycle dans {wait:.0f}s (ou plus tôt si breaking news)")
            # Attendre en surveillant à la fois l'arrêt et le forçage
            _force_cycle_event.wait(timeout=wait)

    logger.info("=== Atlas Trader arrêté proprement ===")


def _run_post_mortem_if_needed() -> None:
    """Lance le post-mortem si des décisions en attente existent.
    Exécuté avec un timeout global de 120s pour ne jamais bloquer le daemon."""
    import concurrent.futures

    def _post_mortem_work():
        from storage.database import get_pending_postmortems
        from utils.config import load_settings
        from utils.logger import log_flux_metric
        cfg = load_settings()
        pm_cfg = cfg.get("post_mortem", {})
        if not pm_cfg.get("enabled", True):
            log_flux_metric("post_mortem", "disabled", 0, 0)
            return
        pending = get_pending_postmortems(pm_cfg.get("delay_hours", 24))
        if pending:
            logger.info(f"Post-mortem : {len(pending)} décisions à analyser")
            from agents.post_mortem_agent import PostMortemAgent
            agent = PostMortemAgent()
            agent.run(pending)
        else:
            log_flux_metric("post_mortem", "ok", 0, 0)

        # Évaluer les prédictions TimesFM arrivées à échéance
        try:
            from storage.database import evaluate_timesfm_forecasts
            evaluate_timesfm_forecasts()
        except Exception as exc:
            logger.debug(f"TimesFM eval skipped: {exc}")

        # Évaluer les shadow positions arrivées à échéance
        try:
            from comparison.shadow_runner import evaluate_shadow_postmortems
            evaluate_shadow_postmortems()
        except Exception as exc:
            logger.debug(f"Shadow post-mortem skipped: {exc}")

    # IMPORTANT: ne PAS utiliser "with ThreadPoolExecutor" — son __exit__ appelle
    # shutdown(wait=True) même après un TimeoutError, ce qui bloque indéfiniment.
    _pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    _fut = _pool.submit(_post_mortem_work)
    try:
        _fut.result(timeout=120)
    except concurrent.futures.TimeoutError:
        logger.warning("Post-mortem timeout (120s) — skipped, daemon continues")
    except Exception as exc:
        logger.warning(f"Post-mortem ignoré : {exc}")
    finally:
        _pool.shutdown(wait=False)  # abandon le thread, ne jamais bloquer


def launch_dashboard() -> None:
    """Lance le dashboard Streamlit."""
    import subprocess
    import sys
    logger.info("Lancement du dashboard Streamlit...")
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        "dashboard/streamlit_app.py",
        "--server.headless", "true",
        "--server.port", "8501",
    ])


def main() -> None:
    args = parse_args()

    if args.dashboard:
        launch_dashboard()
        return

    cfg = bootstrap()

    # Override depuis args
    asset = args.asset or cfg.get("project", {}).get("asset", "BTC/USDT")
    interval = args.interval or cfg.get("project", {}).get("loop_interval_seconds", 900)

    if args.log_level:
        logging.getLogger().setLevel(args.log_level)

    if args.run_once:
        logger.info(f"Mode run-once | asset={asset}")
        state = run_single_cycle(asset)
        decision = (state.get("decision") or {}).get("action", "HOLD")
        score = state.get("global_score", 50)
        errors = state.get("errors", [])
        print(f"\n{'='*50}")
        print(f"RÉSULTAT DU CYCLE")
        print(f"  Asset       : {asset}")
        print(f"  Score       : {score:.1f}/100")
        print(f"  Décision    : {decision}")
        print(f"  Tokens LLM  : {state.get('llm_tokens_used', 0)}")
        print(f"  Durée       : {state.get('cycle_duration_ms', 0)}ms")
        if errors:
            print(f"  Erreurs     : {', '.join(errors)}")
        print(f"{'='*50}\n")

    elif args.daemon:
        run_daemon(asset, interval)

    elif args.post_mortem:
        from storage.database import get_pending_postmortems
        from utils.config import load_settings
        pending = get_pending_postmortems()
        logger.info(f"Post-mortem standalone — {len(pending)} décisions en attente")
        if pending:
            from agents.post_mortem_agent import PostMortemAgent
            PostMortemAgent().run(pending)
        else:
            logger.info("Aucune décision en attente de post-mortem")


if __name__ == "__main__":
    main()
