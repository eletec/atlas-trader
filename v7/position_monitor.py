"""
v7/position_monitor.py — Surveillance continue des positions ouvertes.

Thread indépendant du cycle carry. Toutes les 60 secondes :
  1. Récupère les positions ouvertes (tous symboles)
  2. Fetch les prix spot et perp actuels via CCXT (cache 30s)
  3. Vérifie SL/TP contre le prix courant (sauf carry)
  4. Applique le time-stop (max_hold_days écoulé — positions NON-carry ;
     les positions carry utilisent les zones économiques 30/60/90j)
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
MAX_HOLD_DAYS_DEFAULT = 10       # time-stop par défaut si l'actif n'est pas configuré (non-carry)
MAX_LOSS_PCT_DEFAULT = -0.05     # perte max par position (-5%)
PORTFOLIO_DD_PCT_DEFAULT = -0.20 # kill-switch global (-20%)
TOTAL_CAPITAL_DEFAULT = 14_000   # fallback si carry_assets.yaml est illisible
PAYBACK_DAYS_MAX_DEFAULT = 30    # sortie économique carry si payback > 30j


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
        self._circuit_breaker = False  # Tier 0: bloque nouvelles entrées

    @property
    def circuit_breaker_active(self) -> bool:
        """Tier 0: vrai si les nouvelles entrées doivent être bloquées."""
        return self._circuit_breaker

    @staticmethod
    def _load_config() -> dict:
        """Paramètres de risk management.

        Source unique de vérité : carry_assets.yaml via v7.core.asset_config.
        (config/asset_profiles.yaml — reliquat V2 directionnel — a été supprimé :
        il portait un max_hold_days différent de celui de la stratégie.)
        """
        glob: dict = {}
        try:
            from v7.core.asset_config import get_global_params
            glob = get_global_params()
        except Exception as exc:
            logger.warning("PositionMonitor: carry_assets.yaml indisponible (%s) — fallback", exc)
        return {
            "max_loss_pct": MAX_LOSS_PCT_DEFAULT,
            "max_portfolio_dd_pct": PORTFOLIO_DD_PCT_DEFAULT,
            "total_capital": int(glob.get("total_capital", TOTAL_CAPITAL_DEFAULT)),
            "payback_days_max": PAYBACK_DAYS_MAX_DEFAULT,
        }

    @staticmethod
    def _max_hold_days_for(symbol: str) -> int:
        """Time-stop configuré pour l'actif (carry_assets.yaml), sinon défaut."""
        try:
            from v7.core.asset_config import get_asset_params
            val = get_asset_params(symbol).get("max_hold_days")
            if val:
                return int(val)
        except Exception:
            pass
        return MAX_HOLD_DAYS_DEFAULT

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
        logger.info("PositionMonitor started (interval=%ds)", CHECK_INTERVAL_S)

    def stop(self) -> None:
        """Arrête le thread proprement."""
        if self._stop_event:
            self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("PositionMonitor stopped")

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
            logger.warning("PositionMonitor: storage.paper_trader unavailable")
            return

        positions = get_open_positions()
        if not positions:
            return

        cfg = self._load_config()
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

            # P&L réel : basis P&L pour carry, spot P&L pour les autres
            if action == "carry":
                carry_econ = self._compute_carry_economics(
                    {"symbol": symbol, "entry_price": entry_price, "size_usd": size_usd,
                     "current_price": current_price, "context_json": pos.get("context_json")},
                    max_loss_pct)
                unrealized = carry_econ.get("net_carry_pnl", 0.0)
            elif action in ("short",):
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
                "context_json": pos.get("context_json"),
            })

        if not pos_data:
            return

        # ── Phase 0 : Circuit breaker (Tier 0) — bloque nouvelles entrées ──
        stale_data = False
        with self._lock:
            cache_ages = [time.time() - v[1] for v in self._price_cache.values() if v[1] > 0]
        max_cache_age = max(cache_ages) if cache_ages else 0
        if max_cache_age > 300:  # 5 minutes sans prix frais
            stale_data = True
            logger.warning("TIER 0 CIRCUIT BREAKER: stale prices (%.0fs) → NO NEW RISK", max_cache_age)
            self._circuit_breaker = True
        elif max_cache_age < 60 and self._circuit_breaker:
            self._circuit_breaker = False
            logger.info("TIER 0: circuit breaker lifted — prices OK")

        # ── Phase 2 : Kill-switch multi-tier ─────────────────────────────
        total_pnl_pct = (total_unrealized / total_capital * 100) if total_capital > 0 else 0
        
        # Tier 1: Operational — données périmées
        if stale_data:
            logger.error("KILL-SWITCH TIER 1 (OPERATIONAL): stale prices (%.0fs)", max_cache_age)
        
        # Tier 2: Market — P&L extrême (>10% capital)
        market_stress = abs(total_unrealized) > total_capital * 0.10
        
        # Tier 3: Portfolio drawdown (-20%)
        portfolio_dd = total_pnl_pct < -(max_portfolio_dd_pct * 100)
        
        # Tier 4: Pertes de basis corrélées (3 audits, 20/07/2026)
        # L'ancienne règle "≥3 positions perdantes" déclenchait sur un simple
        # élargissement banal du basis. La nouvelle vérifie la corrélation des pertes.
        carry_losses = [pd for pd in pos_data
                        if pd["action"] == "carry" and pd["unrealized"] < 0]
        losing_count = len(carry_losses)
        # Correlated loss: ≥3 carry positions losing AND portfolio loss > 3%
        # AND the average carry loss is significant (>1% of position)
        correlated_loss = False
        if losing_count >= 3 and total_pnl_pct < -3.0:
            avg_loss_pct = sum(
                abs(pd["unrealized"]) / max(pd["size_usd"], 1) * 100
                for pd in carry_losses
            ) / max(losing_count, 1)
            correlated_loss = avg_loss_pct > 1.0  # average loss > 1% per position
        
        kill_switch = stale_data or market_stress or portfolio_dd or correlated_loss
        kill_tier = ("OPERATIONAL" if stale_data else 
                     "MARKET" if market_stress else 
                     "PORTFOLIO_DD" if portfolio_dd else 
                     "CORRELATED_LOSS" if correlated_loss else None)

        if kill_switch and kill_tier and not self._kill_switch_triggered:
            self._kill_switch_triggered = True
            logger.error(
                "🔴 KILL-SWITCH TIER %s : P&L=%.2f%% (%.2f$) → FERMETURE DE TOUTES LES POSITIONS",
                kill_tier, total_pnl_pct, total_unrealized,
            )
            for pd in pos_data:
                try:
                    if pd["action"] == "carry":
                        # P&L carry réel (basis+funding) — pas le spot directionnel
                        pnl = pd["unrealized"]
                    elif pd["action"] in ("short",):
                        pnl = (pd["entry_price"] - pd["current_price"]) / pd["entry_price"] * pd["size_usd"]
                    else:
                        pnl = (pd["current_price"] - pd["entry_price"]) / pd["entry_price"] * pd["size_usd"]
                    close_position(pd["trade_id"], pd["current_price"], round(pnl, 4), f"kill_switch_{kill_tier}")
                    closed_count += 1
                    logger.info("KILL-SWITCH CLOSE %s %s @ %.2f pnl=$%.2f",
                               pd["symbol"], pd["trade_id"], pd["current_price"], pnl)
                except Exception as exc:
                    logger.error("Kill-switch close failed %s: %s", pd["trade_id"], exc)
            if closed_count > 0:
                logger.info("PositionMonitor: KILL-SWITCH %s — %d position(s) closed", kill_tier, closed_count)
            return

        # ── Kill-switch reset policy (3 audits, 20/07/2026) ──
        # Tier 1 (OPERATIONAL): auto-reset quand les données redeviennent fraîches
        # Tier 2+ (MARKET/PORTFOLIO_DD/CORRELATED_LOSS): reset MANUEL requis
        # → pas d'auto-reset, le flag reste jusqu'à redémarrage ou intervention
        if self._kill_switch_triggered and kill_tier == "OPERATIONAL":
            if not stale_data:
                self._kill_switch_triggered = False
                logger.info("KILL-SWITCH TIER 1 auto-reset: data restored")
        # Tier 2+ : pas d'auto-reset. Nécessite redémarrage du container ou
        # appel API /dag/reset-kill-switch pour réarmer.

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

            # 3c) Pour les trades carry : sortie économique (payback_days)
            #     Pour les autres : time-stop calendaire
            if not should_close and pd["ts_str"]:
                try:
                    opened_at = datetime.fromisoformat(pd["ts_str"].replace("Z", "+00:00"))
                    days_held = (now - opened_at).total_seconds() / 86400
                    if is_carry:
                        # Grace period: skip economic stop for positions < 1h old
                        # (PositionMonitor needs time to fetch perp prices, 25/07/2026)
                        if days_held < 0.04:  # ~1 hour
                            pass  # too new — skip economic check
                        else:
                            carry_econ = self._compute_carry_economics(pd, max_loss_pct)
                            payback_days = carry_econ["payback_days"]
                            if carry_econ.get("data_degraded"):
                                logger.warning("PositionMonitor: %s carry economics degraded — skipping economic stop", pd["symbol"])
                            elif payback_days > 90:
                                should_close = True
                                reason = f"ECONOMIC STOP (ZONE CLOSE): payback={payback_days:.0f}j > 90j"
                            elif payback_days > 60 and loss_pct < -1.0:
                                should_close = True
                                reason = f"ECONOMIC STOP (ZONE DERISK): payback={payback_days:.0f}j + loss={loss_pct:+.2f}%"
                            elif payback_days > 30:
                                logger.info("PositionMonitor: %s carry WATCH payback=%.0fj (zone 30-60j)",
                                       pd["symbol"], payback_days)
                            else:
                                logger.debug("PositionMonitor: %s carry HEALTHY payback=%.0fj", pd["symbol"], payback_days)
                    else:
                        # Time-stop classique pour non-carry — seuil propre à l'actif
                        _mhd = self._max_hold_days_for(pd["symbol"])
                        if days_held > _mhd:
                            should_close = True
                            reason = f"TIME-STOP: {days_held:.1f}j > {_mhd}j max (loss={loss_pct:+.2f}%)"
                except (ValueError, OSError):
                    pass

            # 3d) Margin Monitor — carry positions only (3 audits consensus, 20/07/2026)
            #      A delta-neutral carry can still be liquidated if the short perp
            #      runs out of margin before the spot gain can be mobilized.
            if not should_close and is_carry:
                margin_alert = self._check_margin_safety(pd)
                if margin_alert == "LIQUIDATION_RISK":
                    should_close = True
                    reason = f"MARGIN: liquidation risk (price={pd['current_price']:.2f})"
                    logger.error("PositionMonitor: %s MARGIN LIQUIDATION RISK → CLOSE", pd["trade_id"])
                elif margin_alert == "MARGIN_WARNING":
                    logger.warning("PositionMonitor: %s margin buffer low — monitor closely", pd["trade_id"])

            # 3e) Exécuter la clôture
            if should_close:
                if pd["action"] == "carry":
                    # P&L carry réel (basis+funding) — delta-neutre, pas le spot directionnel
                    pnl = pd["unrealized"]
                elif pd["action"] in ("short",):
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
                        logger.warning("PositionMonitor: close_position failed for %s", pd["trade_id"])
                except Exception as exc:
                    logger.error("PositionMonitor: exception close_position %s: %s", pd["trade_id"], exc)

        if closed_count > 0:
            logger.info("PositionMonitor: %d position(s) closed this cycle | total P&L=%.2f$ (%.2f%%)",
                       closed_count, total_unrealized, total_pnl_pct)

    # ── Carry Economics (two-leg P&L) ────────────────────────────────────

    def _get_cached_perp(self, symbol: str) -> float:
        """Retourne le prix perp actuel, avec cache 30s."""
        now = time.time()
        with self._lock:
            cached = self._perp_cache.get(symbol)
            if cached and (now - cached[1]) < PRICE_CACHE_TTL_S:
                return cached[0]
        price = self._fetch_perp(symbol)
        if price > 0:
            with self._lock:
                self._perp_cache[symbol] = (price, now)
        return price

    @staticmethod
    def _fetch_perp(symbol: str) -> float:
        """Fetch le prix du perpetual via CCXT Binance (gère les contrats ×1000).
        Retourne le prix normalisé au token (÷1000 pour les contrats 1000X)."""
        try:
            import ccxt
            exchange = ccxt.binance({"enableRateLimit": True})
            MULTIPLIER_MAP = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "BONK": "1000BONK",
                              "FLOKI": "1000FLOKI", "LUNC": "1000LUNC"}
            base = symbol.split("/")[0]
            symbol_perp = f"{MULTIPLIER_MAP.get(base, base)}/USDT:USDT"
            ticker = exchange.fetch_ticker(symbol_perp)
            raw = float(ticker.get("last", 0))
            # Contrat ×1000 : le prix du contrat vaut ×1000 le prix spot du token
            return raw / 1000.0 if base in MULTIPLIER_MAP else raw
        except Exception as exc:
            logger.debug("PositionMonitor: fetch perp %s failed: %s", symbol, exc)
            return 0.0

    def _compute_carry_economics(self, pd: dict, max_loss_pct: float) -> dict:
        """Calcule le P&L carry réel (basis + funding estimé) et le payback.

        Returns:
            dict avec basis_pnl, funding_est, net_carry_pnl, payback_days
        """
        result = {"basis_pnl": 0.0, "funding_est": 0.0, "net_carry_pnl": 0.0, "payback_days": 999}
        try:
            symbol = pd["symbol"]
            entry_spot = pd["entry_price"]
            size_usd = pd["size_usd"]
            current_spot = pd["current_price"]

            # Récupérer le prix perp (obligatoire pour le carry)
            current_perp = self._get_cached_perp(symbol)
            if current_perp <= 0:
                # Pas de fallback spot ! (3 audits, 20/07/2026)
                # Si le perp est indisponible, le basis est INCONNU.
                # Remplacer par le spot masquerait le risque (basis=0 artificiel).
                result["data_degraded"] = True
                logger.warning("PositionMonitor: perp price missing for %s → carry economics UNKNOWN", symbol)
                return result

            # Récupérer entry_perp depuis le context_json
            entry_perp = None
            try:
                import json as _j
                ctx_raw = pd.get("context_json")
                if ctx_raw:
                    ctx = _j.loads(ctx_raw) if isinstance(ctx_raw, str) else ctx_raw
                    entry_perp = float(ctx.get("entry_perp_price", 0))
            except Exception:
                pass

            if entry_perp is None or entry_perp <= 0:
                result["data_degraded"] = True
                logger.warning("PositionMonitor: entry_perp missing for %s → carry economics UNKNOWN", symbol)
                return result

            # Calculer le basis (spot - perp) / spot
            basis_entry = (entry_spot - entry_perp) / entry_spot if entry_spot > 0 else 0
            basis_now = (current_spot - current_perp) / current_spot if current_spot > 0 else 0

            # Basis P&L (Round 4 fix, 22/07/2026)
            # Position: LONG spot + SHORT perp → gains when basis CONTRACTS
            # basis_entry > basis_now → gain (basis decreased)
            basis_pnl = (basis_entry - basis_now) * size_usd
            result["basis_pnl"] = round(basis_pnl, 4)

            # Funding estimé (approximation : ~0.01%/8h moyen récent)
            # En pratique, on devrait lire le funding réel depuis la DB/state
            daily_funding_est = size_usd * 0.0001 * 3  # 0.01% × 3 fois/jour
            result["funding_est"] = round(daily_funding_est, 6)

            # Net carry P&L
            result["net_carry_pnl"] = round(basis_pnl, 4)  # + funding (négligeable en daily)

            # Payback days : combien de jours de funding pour rembourser la perte basis
            if basis_pnl < 0 and daily_funding_est > 0:
                result["payback_days"] = abs(basis_pnl) / daily_funding_est
            elif basis_pnl >= 0:
                result["payback_days"] = 0  # pas de perte à rembourser
            else:
                result["payback_days"] = 999  # funding nul ou négatif → impossible à rembourser

        except Exception as e:
            result["data_degraded"] = True
            logger.debug("PositionMonitor: carry_economics failed for %s: %s", pd.get("symbol", "?"), e)

        return result

    @staticmethod
    def _leverage_for(symbol: str, coin: str) -> float:
        """Levier du short perp : carry_assets.yaml en priorite, table majors sinon.

        Source unique de verite — la table codee en dur divergeait silencieusement
        de la config si un levier y etait modifie.
        """
        try:
            from v7.core.asset_config import get_asset_params
            lev = get_asset_params(symbol).get("leverage")
            if lev:
                return float(lev)
        except Exception:
            pass
        return {"BTC": 2.0, "ETH": 2.0, "SOL": 1.5, "BNB": 1.5,
                "XRP": 1.0, "ADA": 1.0, "DOGE": 1.0}.get(coin, 1.0)

    def _check_margin_safety(self, pd: dict) -> str:
        """
        Simulate margin safety for a carry position (3 audits consensus, 20/07/2026).
        
        A delta-neutral carry can still be liquidated: the short perp leg needs
        margin, and a sharp spot increase can exhaust it before the spot gain
        can be mobilized.
        
        Returns: "OK", "MARGIN_WARNING", or "LIQUIDATION_RISK"
        """
        try:
            symbol = pd.get("symbol", "")
            size_usd = float(pd.get("size_usd", 0) or 0)
            entry_price = float(pd.get("entry_price", 0) or 0)
            current_price = float(pd.get("current_price", 0) or 0)

            if size_usd <= 0 or entry_price <= 0 or current_price <= 0:
                return "OK"

            coin = symbol.split("/")[0].upper() if "/" in symbol else symbol.upper()

            # ── Leverage assumptions ──
            # Lu depuis carry_assets.yaml (BTC/ETH 2x, SOL/BNB 1.5x, majors alts 1x)
            leverage = self._leverage_for(symbol, coin)

            # Maintenance margin rate (Binance standard: ~0.5%–2.5% depending on notional)
            maint_margin_rate = 0.005  # 0.5% conservative

            # ── Calculations ──
            notional = size_usd  # position size = notional value
            initial_margin = notional / leverage
            maintenance_margin = notional * maint_margin_rate

            # For a SHORT position: liquidation when price rises
            # liquidation_price = entry_price × (1 + 1/leverage - maint_margin_rate)
            # Simplified: the short loses (current_price - entry_price) × quantity
            # When loss > initial_margin - maintenance_margin → liquidation
            price_increase_pct = (current_price - entry_price) / entry_price
            short_loss = price_increase_pct * notional  # loss on short leg
            margin_remaining = initial_margin - short_loss

            if margin_remaining <= maintenance_margin:
                liq_distance_pct = 0.0
                return "LIQUIDATION_RISK"

            # Liquidation distance: how much more price increase before liquidation
            loss_to_liquidation = margin_remaining - maintenance_margin
            liq_distance_pct = (loss_to_liquidation / notional) * 100  # as % of position

            # ── Thresholds ──
            if liq_distance_pct < 5.0:
                logger.warning(
                    "MARGIN ALERT: %s liq_dist=%.1f%% margin_remaining=$%.0f "
                    "(entry=%.2f current=%.2f lev=%.1fx size=$%.0f)",
                    symbol, liq_distance_pct, margin_remaining,
                    entry_price, current_price, leverage, size_usd,
                )
                return "LIQUIDATION_RISK"
            elif liq_distance_pct < 15.0:
                logger.warning(
                    "MARGIN WARNING: %s liq_dist=%.1f%% margin_remaining=$%.0f",
                    symbol, liq_distance_pct, margin_remaining,
                )
                return "MARGIN_WARNING"
            else:
                return "OK"

        except Exception as e:
            logger.debug("PositionMonitor: margin_safety failed for %s: %s",
                        pd.get("symbol", "?"), e)
            return "OK"  # fail open — don't close on a calculation error

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
