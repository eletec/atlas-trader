"""
v7/position_monitor.py — Surveillance continue des positions ouvertes.

Thread indépendant du cycle DAG. Toutes les 60 secondes :
  1. Récupère les positions ouvertes (tous symboles)
  2. Fetch les prix spot actuels via CCXT (cache 30s par symbole)
  3. Vérifie SL/TP contre le prix courant
  4. Applique le time-stop (max_hold_days écoulé)
  5. Ferme les positions qui ont atteint leur condition de sortie

Ce module remplace le PositionManager manquant dans les DAGs V7.
Le PositionManager original (v4/nodes/quant/position_manager.py) nécessitait
des inputs OHLCV et n'était pas inclus dans le DAG V7. Ce monitor comble
ce gap avec une approche légère (prix spot uniquement, pas d'ATR).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("v7.position_monitor")

# ── Configuration ──────────────────────────────────────────────────────────
CHECK_INTERVAL_S = 60          # vérification toutes les 60 secondes
PRICE_CACHE_TTL_S = 30         # cache des prix spot par symbole
MAX_HOLD_DAYS_DEFAULT = 21     # time-stop par défaut si non spécifié


class PositionMonitor:
    """Moniteur de positions — singleton thread-safe."""

    _instance: "PositionMonitor | None" = None
    _thread: threading.Thread | None = None
    _stop_event: threading.Event | None = None

    def __init__(self) -> None:
        self._price_cache: dict[str, tuple[float, float]] = {}  # symbol → (price, timestamp)
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> "PositionMonitor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Public API ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Démarre le thread de surveillance en arrière-plan."""
        if self._thread is not None and self._thread.is_alive():
            logger.info("PositionMonitor déjà actif")
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="position-monitor")
        self._thread.start()
        logger.info("PositionMonitor démarré (intervalle=%ds)", CHECK_INTERVAL_S)

    def stop(self) -> None:
        """Arrête le thread proprement."""
        if self._stop_event:
            self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("PositionMonitor arrêté")

    # ── Internal ───────────────────────────────────────────────────────────

    def _loop(self) -> None:
        """Boucle principale : vérifie les positions toutes les N secondes."""
        logger.info("PositionMonitor loop started")
        # Petit délai initial pour laisser l'API démarrer
        time.sleep(10)

        while self._stop_event and not self._stop_event.is_set():
            try:
                self._check_all_positions()
            except Exception as exc:
                logger.error("PositionMonitor error: %s", exc, exc_info=True)
            self._stop_event.wait(CHECK_INTERVAL_S)

    def _check_all_positions(self) -> None:
        """Vérifie toutes les positions ouvertes et ferme celles qui doivent l'être."""
        try:
            from storage.paper_trader import get_open_positions, close_position
        except ImportError:
            logger.warning("PositionMonitor: storage.paper_trader indisponible")
            return

        positions = get_open_positions()
        if not positions:
            return

        now = datetime.now(timezone.utc)
        closed_count = 0

        for pos in positions:
            trade_id = pos.get("trade_id", "")
            symbol = pos.get("symbol", "")
            action = (pos.get("action") or "long").lower()
            entry_price = float(pos.get("entry_price", 0) or 0)
            sl_price = float(pos.get("stop_loss", 0) or 0)
            tp_price = float(pos.get("take_profit", 0) or 0)
            size_usd = float(pos.get("size_usd", 0) or 0)
            ts_str = pos.get("timestamp", "")

            if not symbol or not entry_price or not trade_id:
                continue

            # 1) Récupérer le prix spot actuel (avec cache)
            current_price = self._get_cached_price(symbol)
            if current_price <= 0:
                continue  # skip si prix indisponible

            should_close = False
            close_price = current_price
            reason = ""

            # Pour les trades "carry" (delta-neutre : short perp + long spot),
            # le SL/TP spot n'a pas de sens car la position est couverte.
            # Seul le time-stop et le basis-SL (géré par le DAG) s'appliquent.
            is_carry = action == "carry"

            # 2) Vérifier SL → prix traverse le stop-loss
            # Désactivé pour les trades carry (le vrai risque est sur la basis, pas le spot)
            if not is_carry and sl_price > 0:
                if action in ("short", "carry"):
                    # Short: SL est au-dessus du prix d'entrée → on ferme si prix ≥ SL
                    if current_price >= sl_price:
                        should_close = True
                        close_price = sl_price
                        pnl_pct = (entry_price - sl_price) / entry_price * 100
                        reason = f"SL hit: {pnl_pct:+.2f}% (entry={entry_price:.2f} sl={sl_price:.2f} price={current_price:.2f})"
                else:
                    # Long: SL est en-dessous du prix d'entrée → on ferme si prix ≤ SL
                    if current_price <= sl_price:
                        should_close = True
                        close_price = sl_price
                        pnl_pct = (sl_price - entry_price) / entry_price * 100
                        reason = f"SL hit: {pnl_pct:+.2f}% (entry={entry_price:.2f} sl={sl_price:.2f} price={current_price:.2f})"

            # 3) Vérifier TP → prix atteint le take-profit
            # Désactivé pour les trades carry (même raison que SL)
            if not should_close and not is_carry and tp_price > 0:
                if action in ("short", "carry"):
                    if current_price <= tp_price:
                        should_close = True
                        close_price = tp_price
                        pnl_pct = (entry_price - tp_price) / entry_price * 100
                        reason = f"TP hit: {pnl_pct:+.2f}%"
                else:
                    if current_price >= tp_price:
                        should_close = True
                        close_price = tp_price
                        pnl_pct = (tp_price - entry_price) / entry_price * 100
                        reason = f"TP hit: {pnl_pct:+.2f}%"

            # 4) Time-stop → position trop vieille
            if not should_close and ts_str:
                try:
                    opened_at = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    days_held = (now - opened_at).total_seconds() / 86400
                    # Utiliser max_hold_days depuis les paramètres V7 si disponible
                    max_days = MAX_HOLD_DAYS_DEFAULT
                    if days_held > max_days:
                        should_close = True
                        # Calculer P&L
                        if action in ("short", "carry"):
                            pnl_pct = (entry_price - current_price) / entry_price * 100
                        else:
                            pnl_pct = (current_price - entry_price) / entry_price * 100
                        reason = f"TIME-STOP: {days_held:.1f}j > {max_days}j max (pnl={pnl_pct:+.2f}%)"
                except (ValueError, OSError):
                    pass

            # 5) Exécuter la clôture
            if should_close:
                if action in ("short", "carry"):
                    pnl = (entry_price - close_price) / entry_price * size_usd
                else:
                    pnl = (close_price - entry_price) / entry_price * size_usd

                try:
                    ok = close_position(trade_id, close_price, round(pnl, 4), reason)
                    if ok:
                        closed_count += 1
                        logger.info(
                            "CLOSE [%s] %s %s @ %.2f→%.2f size=$%.0f pnl=$%.2f | %s",
                            "monitor", trade_id, action, entry_price, close_price, size_usd, pnl, reason,
                        )
                    else:
                        logger.warning("PositionMonitor: échec close_position pour %s", trade_id)
                except Exception as exc:
                    logger.error("PositionMonitor: exception close_position %s: %s", trade_id, exc)

        if closed_count > 0:
            logger.info("PositionMonitor: %d position(s) fermée(s) ce cycle", closed_count)

    # ── Price fetching (avec cache courte durée) ───────────────────────────

    def _get_cached_price(self, symbol: str) -> float:
        """Retourne le prix spot actuel, avec cache 30s pour éviter de spammer l'exchange."""
        now = time.time()
        with self._lock:
            cached = self._price_cache.get(symbol)
            if cached and (now - cached[1]) < PRICE_CACHE_TTL_S:
                return cached[0]

        # Fetch depuis CCXT
        price = self._fetch_spot(symbol)
        if price > 0:
            with self._lock:
                self._price_cache[symbol] = (price, now)
        return price

    @staticmethod
    def _fetch_spot(symbol: str) -> float:
        """Fetch le prix spot via CCXT Binance."""
        try:
            import ccxt
            exchange = ccxt.binance({"enableRateLimit": True})
            ticker = exchange.fetch_ticker(symbol)
            return float(ticker.get("last", 0))
        except Exception as exc:
            logger.warning("PositionMonitor: fetch spot %s failed: %s", symbol, exc)
            return 0.0


# ── Module-level convenience ───────────────────────────────────────────────

_monitor: PositionMonitor | None = None


def start_monitor() -> None:
    """Lance le moniteur de positions (appelé depuis main.py au démarrage)."""
    global _monitor
    if _monitor is None:
        _monitor = PositionMonitor.instance()
    _monitor.start()


def stop_monitor() -> None:
    """Arrête le moniteur (appelé au shutdown)."""
    global _monitor
    if _monitor:
        _monitor.stop()
        _monitor = None
