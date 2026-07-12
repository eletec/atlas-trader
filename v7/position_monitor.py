"""
v7/position_monitor.py — Surveillance continue des positions ouvertes.

Thread indépendant du cycle DAG. Toutes les 60 secondes :
  1. Récupère les positions ouvertes (tous symboles)
  2. Fetch les prix spot et perp actuels via CCXT (cache 30s)
  3. Vérifie SL/TP contre le prix courant (sauf carry)
  4. Applique le time-stop (max_hold_days écoulé)
  5. Applique la perte max par position (max_loss_pct, unifié SL+time-stop)
  6. Kill-switch global : ferme tout si P&L total < -max_portfolio_dd_pct
  7. Ferme les positions qui ont atteint leur condition de sortie
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("v7.position_monitor")

# ── Configuration ──────────────────────────────────────────────────────────
CHECK_INTERVAL_S = 60
PRICE_CACHE_TTL_S = 30
MAX_HOLD_DAYS_DEFAULT = 10       # time-stop par défaut
MAX_LOSS_PCT_DEFAULT = -0.05     # perte max par position (-5%)
PORTFOLIO_DD_PCT_DEFAULT = -0.20 # kill-switch global (-20%)
TOTAL_CAPITAL_DEFAULT = 14_000   # 7 actifs × $2,000


class PositionMonitor:
    """Moniteur de positions — singleton thread-safe."""

    _instance: "PositionMonitor | None" = None
    _thread: threading.Thread | None = None
    _stop_event: threading.Event | None = None

    def __init__(self) -> None:
        self._price_cache: dict[str, tuple[float, float]] = {}  # symbol → (price, timestamp)
        self._perp_cache: dict[str, tuple[float, float]] = {}   # symbol → (perp_price, timestamp)
        self._lock = threading.Lock()
        self._kill_switch_triggered = False

    @classmethod
    def instance(cls) -> "PositionMonitor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _load_config() -> dict:
        """Charge les paramètres de risk management depuis asset_profiles.yaml."""
        try:
            import yaml, os
            path = os.path.join(os.path.dirname(__file__), "..", "config", "asset_profiles.yaml")
            with open(path) as f:
                cfg = yaml.safe_load(f) or {}
            carry = cfg.get("v7_carry_defaults", {})
            return {
                "max_hold_days": int(carry.get("max_hold_days", MAX_HOLD_DAYS_DEFAULT)),
                "max_loss_pct": float(carry.get("max_loss_pct", MAX_LOSS_PCT_DEFAULT)),
                "max_portfolio_dd_pct": float(carry.get("max_portfolio_dd_pct", PORTFOLIO_DD_PCT_DEFAULT)),
                "total_capital": int(carry.get("total_capital", TOTAL_CAPITAL_DEFAULT)),
            }
        except Exception:
            return {
                "max_hold_days": MAX_HOLD_DAYS_DEFAULT,
                "max_loss_pct": MAX_LOSS_PCT_DEFAULT,
                "max_portfolio_dd_pct": PORTFOLIO_DD_PCT_DEFAULT,
                "total_capital": TOTAL_CAPITAL_DEFAULT,
            }

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
        """Vérifie toutes les positions ouvertes et ferme celles qui doivent l'être.
        
        Ordre des vérifications :
          1. Kill-switch global (P&L total < -max_portfolio_dd_pct)
          2. Perte max par position (unrealized P&L < max_loss_pct)
          3. SL/TP prix (sauf carry)
          4. Time-stop
        """
        try:
            from storage.paper_trader import get_open_positions, close_position
        except ImportError:
            logger.warning("PositionMonitor: storage.paper_trader indisponible")
            return

        positions = get_open_positions()
        if not positions:
            return

        cfg = self._load_config()
        max_hold_days = cfg["max_hold_days"]
        max_loss_pct = cfg["max_loss_pct"]       # ex: -0.05 = -5%
        max_portfolio_dd_pct = cfg["max_portfolio_dd_pct"]  # ex: -0.20 = -20%
        total_capital = cfg["total_capital"]

        now = datetime.now(timezone.utc)
        closed_count = 0

        # ── Phase 1 : Calculer le P&L total pour le kill-switch ──────────
        total_unrealized = 0.0
        total_size = 0.0
        pos_data: list[dict] = []

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

            current_price = self._get_cached_price(symbol)
            if current_price <= 0:
                continue

            # P&L spot (approximation pour le kill-switch)
            if action in ("short", "carry"):
                unrealized = (entry_price - current_price) / entry_price * size_usd
            else:
                unrealized = (current_price - entry_price) / entry_price * size_usd

            total_unrealized += unrealized
            total_size += size_usd

            pos_data.append({
                "trade_id": trade_id, "symbol": symbol, "action": action,
                "entry_price": entry_price, "sl_price": sl_price, "tp_price": tp_price,
                "size_usd": size_usd, "current_price": current_price,
                "unrealized": unrealized, "ts_str": ts_str,
            })

        if not pos_data:
            return

        # ── Phase 2 : Kill-switch global ──────────────────────────────────
        total_pnl_pct = (total_unrealized / total_capital * 100) if total_capital > 0 else 0
        kill_switch = total_pnl_pct < (max_portfolio_dd_pct * 100)  # ex: -20% → < -20

        if kill_switch and not self._kill_switch_triggered:
            self._kill_switch_triggered = True
            logger.error(
                "🔴 KILL-SWITCH GLOBAL : P&L total = %.2f%% (%.2f$) < %.0f%% → FERMETURE DE TOUTES LES POSITIONS",
                total_pnl_pct, total_unrealized, max_portfolio_dd_pct * 100,
            )
            for pd in pos_data:
                try:
                    if pd["action"] in ("short", "carry"):
                        pnl = (pd["entry_price"] - pd["current_price"]) / pd["entry_price"] * pd["size_usd"]
                    else:
                        pnl = (pd["current_price"] - pd["entry_price"]) / pd["entry_price"] * pd["size_usd"]
                    close_position(pd["trade_id"], pd["current_price"], round(pnl, 4), "kill_switch_global")
                    closed_count += 1
                    logger.info("KILL-SWITCH CLOSE %s %s @ %.2f pnl=$%.2f",
                               pd["symbol"], pd["trade_id"], pd["current_price"], pnl)
                except Exception as exc:
                    logger.error("Kill-switch close failed %s: %s", pd["trade_id"], exc)
            if closed_count > 0:
                logger.info("PositionMonitor: KILL-SWITCH — %d position(s) fermée(s)", closed_count)
            return  # ne pas faire d'autres vérifications ce cycle

        # Reset kill-switch flag si le P&L est remonté (positions fermées entre-temps)
        if self._kill_switch_triggered and total_pnl_pct >= (max_portfolio_dd_pct * 100 * 0.5):
            self._kill_switch_triggered = False

        # ── Phase 3 : Vérifications par position ──────────────────────────
        for pd in pos_data:
            should_close = False
            close_price = pd["current_price"]
            reason = ""
            is_carry = pd["action"] == "carry"

            # 3a) Perte max unifiée (remplace basis SL + time-stop fixe)
            # Pour tout type de trade : si perte latente > |max_loss_pct| → fermer
            loss_pct = (pd["unrealized"] / pd["size_usd"] * 100) if pd["size_usd"] > 0 else 0
            if loss_pct < (max_loss_pct * 100):  # ex: -5% < -5% → trigger
                should_close = True
                reason = f"MAX LOSS: {loss_pct:+.2f}% < {max_loss_pct*100:.0f}% (entry={pd['entry_price']:.2f} price={pd['current_price']:.2f})"
                logger.info("PositionMonitor: %s %s loss=%.2f%% → CLOSE", pd["symbol"], pd["trade_id"], loss_pct)

            # 3b) SL/TP prix (non-carry uniquement)
            if not should_close and not is_carry:
                if pd["sl_price"] > 0:
                    if pd["action"] == "short":
                        if pd["current_price"] >= pd["sl_price"]:
                            should_close = True
                            close_price = pd["sl_price"]
                            reason = f"SL hit @ {pd['sl_price']:.2f}"
                    else:
                        if pd["current_price"] <= pd["sl_price"]:
                            should_close = True
                            close_price = pd["sl_price"]
                            reason = f"SL hit @ {pd['sl_price']:.2f}"

                if not should_close and pd["tp_price"] > 0:
                    if pd["action"] == "short":
                        if pd["current_price"] <= pd["tp_price"]:
                            should_close = True
                            close_price = pd["tp_price"]
                            reason = f"TP hit @ {pd['tp_price']:.2f}"
                    else:
                        if pd["current_price"] >= pd["tp_price"]:
                            should_close = True
                            close_price = pd["tp_price"]
                            reason = f"TP hit @ {pd['tp_price']:.2f}"

            # 3c) Time-stop (tous types)
            if not should_close and pd["ts_str"]:
                try:
                    opened_at = datetime.fromisoformat(pd["ts_str"].replace("Z", "+00:00"))
                    days_held = (now - opened_at).total_seconds() / 86400
                    if days_held > max_hold_days:
                        should_close = True
                        reason = f"TIME-STOP: {days_held:.1f}j > {max_hold_days}j max (loss={loss_pct:+.2f}%)"
                except (ValueError, OSError):
                    pass

            # 3d) Exécuter la clôture
            if should_close:
                if pd["action"] in ("short", "carry"):
                    pnl = (pd["entry_price"] - close_price) / pd["entry_price"] * pd["size_usd"]
                else:
                    pnl = (close_price - pd["entry_price"]) / pd["entry_price"] * pd["size_usd"]

                try:
                    ok = close_position(pd["trade_id"], close_price, round(pnl, 4), reason)
                    if ok:
                        closed_count += 1
                        logger.info(
                            "CLOSE [%s] %s %s @ %.2f→%.2f size=$%.0f pnl=$%.2f | %s",
                            "monitor", pd["trade_id"], pd["action"],
                            pd["entry_price"], close_price, pd["size_usd"], pnl, reason,
                        )
                    else:
                        logger.warning("PositionMonitor: échec close_position pour %s", pd["trade_id"])
                except Exception as exc:
                    logger.error("PositionMonitor: exception close_position %s: %s", pd["trade_id"], exc)

        if closed_count > 0:
            logger.info("PositionMonitor: %d position(s) fermée(s) ce cycle | P&L total=%.2f$ (%.2f%%)",
                       closed_count, total_unrealized, total_pnl_pct)

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
