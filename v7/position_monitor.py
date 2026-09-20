"""
v7/position_monitor.py — Continuous monitoring of open positions.

Independent thread alongside the carry cycle. Every 60 seconds:
  1. Load the open positions (all symbols)
  2. Fetch the current spot and perp prices via CCXT (30s cache)
  3. Check SL/TP against the current price (except carry)
  4. Apply the time-stop (max_hold_days elapsed — NON-carry positions;
     carry positions use the 30/60/90-day economic zones)
  5. Apply the per-position max loss (max_loss_pct, unifies SL + time-stop)
  6. Global kill-switch: close everything when the portfolio P&L breaches -20%
  7. Close the positions that reached their exit condition
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from v7.core.carry_accounting import basis_pnl_usd, exit_fee_usd
from v7.core.risk_state import set_circuit_breaker

logger = logging.getLogger("v7.position_monitor")

# ── Configuration ──────────────────────────────────────────────────────────
CHECK_INTERVAL_S = 60
PRICE_CACHE_TTL_S = 30
MAX_HOLD_DAYS_DEFAULT = 10       # default time-stop when the asset is not configured (non-carry)
MAX_LOSS_PCT_DEFAULT = -0.05     # max loss per position (-5%)
PORTFOLIO_DD_PCT_DEFAULT = -0.20 # kill-switch global (-20%)
TOTAL_CAPITAL_DEFAULT = 14_000   # fallback when carry_assets.yaml cannot be read
PAYBACK_DAYS_MAX_DEFAULT = 30    # carry economic exit when payback > 30d


def position_age_days(ts_value: Any) -> float | None:
    """Days elapsed since an ISO timestamp, or None when it cannot be read.

    Tolerates a trailing `Z` and mixes of naive and aware values: the monitor
    subtracts the result from an aware `now`, so a naive timestamp raised
    TypeError, which the surrounding `except (ValueError, OSError)` did not catch.
    """
    if not ts_value:
        return None
    try:
        opened = datetime.fromisoformat(str(ts_value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    now = datetime.now(timezone.utc) if opened.tzinfo else datetime.now()
    return (now - opened).total_seconds() / 86400


def portfolio_dd_breached(total_pnl_pct: float, max_portfolio_dd_pct: float) -> bool:
    """True when the portfolio P&L has breached the drawdown kill-switch level.

    ``max_portfolio_dd_pct`` is negative by convention (-0.20 = -20%), like
    MAX_LOSS_PCT_DEFAULT above. Its magnitude is used so the comparison stays
    correct whichever sign the constant carries.

    Regression note: the earlier version negated the already-negative constant
    (`total_pnl_pct < -(max_portfolio_dd_pct * 100)`), which evaluated to
    "P&L < +20%" — true for every possible portfolio state. The first monitor
    pass with any open position therefore closed the whole book and latched the
    kill-switch permanently. See v7/tests/test_position_monitor.py.
    """
    return total_pnl_pct < -abs(max_portfolio_dd_pct) * 100


class PositionMonitor:
    """Position monitor — thread-safe singleton."""

    _instance: "PositionMonitor | None" = None
    _thread: threading.Thread | None = None
    _stop_event: threading.Event | None = None

    def __init__(self) -> None:
        self._price_cache: dict[str, tuple[float, float]] = {}  # symbol → (price, timestamp)
        self._perp_cache: dict[str, tuple[float, float]] = {}   # symbol → (perp_price, timestamp)
        self._lock = threading.Lock()
        self._kill_switch_triggered = False
        self._circuit_breaker = False  # Tier 0: blocks new entries

    @property
    def circuit_breaker_active(self) -> bool:
        """Tier 0: true when new entries must be blocked."""
        return self._circuit_breaker

    @staticmethod
    def _load_config() -> dict:
        """Risk-management parameters.

        Single source of truth: carry_assets.yaml via v7.core.asset_config.
        (config/asset_profiles.yaml — a leftover from the directional V2 — was
        removed: it carried a max_hold_days that differed from the strategy's.)
        """
        glob: dict = {}
        try:
            from v7.core.asset_config import get_global_params
            glob = get_global_params()
        except Exception as exc:
            logger.warning("PositionMonitor: carry_assets.yaml unavailable (%s) - fallback", exc)
        return {
            "max_loss_pct": MAX_LOSS_PCT_DEFAULT,
            "max_portfolio_dd_pct": PORTFOLIO_DD_PCT_DEFAULT,
            "total_capital": int(glob.get("total_capital", TOTAL_CAPITAL_DEFAULT)),
            "payback_days_max": PAYBACK_DAYS_MAX_DEFAULT,
        }

    @staticmethod
    def _max_hold_days_for(symbol: str) -> int:
        """Time-stop configured for the asset (carry_assets.yaml), otherwise the default."""
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
        """Start the background monitoring thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.info("PositionMonitor already running")
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="position-monitor")
        self._thread.start()
        logger.info("PositionMonitor started (interval=%ds)", CHECK_INTERVAL_S)

    def stop(self) -> None:
        """Stop the thread cleanly."""
        if self._stop_event:
            self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("PositionMonitor stopped")

    # ── Internal ───────────────────────────────────────────────────────────

    def _loop(self) -> None:
        """Main loop: check the positions every N seconds."""
        logger.info("PositionMonitor loop started")
        # Small initial delay to let the API start
        time.sleep(10)

        while self._stop_event and not self._stop_event.is_set():
            try:
                self._check_all_positions()
            except Exception as exc:
                logger.error("PositionMonitor error: %s", exc, exc_info=True)
            self._stop_event.wait(CHECK_INTERVAL_S)

    def _check_all_positions(self) -> None:
        """Check every open position and close those that must be closed.

        Order of the checks:
          1. Global kill-switch (portfolio P&L below the drawdown limit, -20%)
          2. Per-position max loss (unrealized P&L < max_loss_pct)
          3. Price SL/TP (except carry)
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

        # -- Phase 1: compute the total P&L for the kill-switch --
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

            # Real P&L: basis P&L for carry, spot P&L for everything else
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

        # -- Phase 0: circuit breaker (tier 0) - blocks new entries --
        stale_data = False
        with self._lock:
            cache_ages = [time.time() - v[1] for v in self._price_cache.values() if v[1] > 0]
        max_cache_age = max(cache_ages) if cache_ages else 0
        if max_cache_age > 300:  # 5 minutes without fresh prices
            stale_data = True
            logger.warning("TIER 0 CIRCUIT BREAKER: stale prices (%.0fs) → NO NEW RISK", max_cache_age)
            self._circuit_breaker = True
            set_circuit_breaker(True, f"stale prices ({max_cache_age:.0f}s)")
        elif max_cache_age < 60 and self._circuit_breaker:
            self._circuit_breaker = False
            set_circuit_breaker(False)
            logger.info("TIER 0: circuit breaker lifted — prices OK")

        # ── Phase 2: Multi-tier kill-switch ─────────────────────────────
        total_pnl_pct = (total_unrealized / total_capital * 100) if total_capital > 0 else 0
        
        # Tier 1: operational - stale data
        if stale_data:
            logger.error("KILL-SWITCH TIER 1 (OPERATIONAL): stale prices (%.0fs)", max_cache_age)
        
        # Tier 2: market - extreme P&L (>10% of capital)
        market_stress = abs(total_unrealized) > total_capital * 0.10
        
        # Tier 3: Portfolio drawdown (-20%)
        portfolio_dd = portfolio_dd_breached(total_pnl_pct, max_portfolio_dd_pct)
        
        # Tier 4: correlated basis losses (3 audits, 2026-07-20)
        # The old '3 or more losing positions' rule fired on a mere
        # routine basis widening. The new one checks the correlation of the losses.
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
                "🔴 KILL-SWITCH TIER %s: P&L=%.2f%% (%.2f$) -> CLOSING ALL POSITIONS",
                kill_tier, total_pnl_pct, total_unrealized,
            )
            for pd in pos_data:
                try:
                    if pd["action"] == "carry":
                        # Real carry P&L (basis+funding) - not the directional spot P&L
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
        # Tier 1 (OPERATIONAL): auto-reset once the data is fresh again
        # Tier 2+ (MARKET/PORTFOLIO_DD/CORRELATED_LOSS): MANUAL reset required
        # -> no auto-reset, the flag stays until a restart or manual intervention
        if self._kill_switch_triggered and kill_tier == "OPERATIONAL":
            if not stale_data:
                self._kill_switch_triggered = False
                logger.info("KILL-SWITCH TIER 1 auto-reset: data restored")
        # Tier 2+: no auto-reset. Requires a container restart or
        # a call to the /dag/reset-kill-switch API to re-arm.

        # -- Phase 3: per-position checks --
        for pd in pos_data:
            should_close = False
            close_price = pd["current_price"]
            reason = ""
            is_carry = pd["action"] == "carry"

            # 3a) Unified max loss (replaces the basis stop + the fixed time-stop)
            # For any trade type: when the unrealised loss > |max_loss_pct| -> close
            loss_pct = (pd["unrealized"] / pd["size_usd"] * 100) if pd["size_usd"] > 0 else 0
            if loss_pct < (max_loss_pct * 100):  # ex: -5% < -5% → trigger
                should_close = True
                reason = f"MAX LOSS: {loss_pct:+.2f}% < {max_loss_pct*100:.0f}% (entry={pd['entry_price']:.2f} price={pd['current_price']:.2f})"
                logger.info("PositionMonitor: %s %s loss=%.2f%% → CLOSE", pd["symbol"], pd["trade_id"], loss_pct)

            # 3b) Price SL/TP (non-carry only)
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

            # 3c) For carry trades: economic exit (payback_days)
            #     For the others: calendar time-stop
            if not should_close and pd["ts_str"]:
                try:
                    days_held = position_age_days(pd["ts_str"])
                    if days_held is None:
                        days_held = 0.0
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
                                reason = f"ECONOMIC STOP (ZONE CLOSE): payback={payback_days:.0f}d > 90d"
                            elif payback_days > 60 and loss_pct < -1.0:
                                should_close = True
                                reason = f"ECONOMIC STOP (ZONE DERISK): payback={payback_days:.0f}d + loss={loss_pct:+.2f}%"
                            elif payback_days > 30:
                                logger.info("PositionMonitor: %s carry WATCH payback=%.0fd (zone 30-60d)",
                                       pd["symbol"], payback_days)
                            else:
                                logger.debug("PositionMonitor: %s carry HEALTHY payback=%.0fd", pd["symbol"], payback_days)
                    else:
                        # Classic time-stop for non-carry - an asset-specific threshold
                        _mhd = self._max_hold_days_for(pd["symbol"])
                        if days_held > _mhd:
                            should_close = True
                            reason = f"TIME-STOP: {days_held:.1f}d > {_mhd}d max (loss={loss_pct:+.2f}%)"
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

            # 3e) Execute the close
            if should_close:
                if pd["action"] == "carry":
                    # The closed-position P&L from the canonical module: funding
                    # actually accrued, the exact basis move, both entry legs and
                    # both exit legs. The old value was `pd["unrealized"]`, which
                    # carried no funding and no exit fee at all.
                    _econ = self._compute_carry_economics(pd, max_loss_pct)
                    pnl = _econ.get("realized_usd")
                    if pnl is None:
                        pnl = pd["unrealized"]
                        logger.warning(
                            "PositionMonitor: %s carry economics unavailable - closing on "
                            "the mark; P&L excludes funding and exit fees", pd["trade_id"])
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
        """Return the current perp price, with a 30s cache."""
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
        """Fetch the perpetual price via CCXT Binance (handles ×1000 contracts).
        Returns the price normalised to the token (÷1000 for 1000X contracts)."""
        try:
            import ccxt
            exchange = ccxt.binance({"enableRateLimit": True})
            MULTIPLIER_MAP = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "BONK": "1000BONK",
                              "FLOKI": "1000FLOKI", "LUNC": "1000LUNC"}
            base = symbol.split("/")[0]
            symbol_perp = f"{MULTIPLIER_MAP.get(base, base)}/USDT:USDT"
            ticker = exchange.fetch_ticker(symbol_perp)
            raw = float(ticker.get("last", 0))
            # x1000 contract: the contract price is 1000x the token spot price
            return raw / 1000.0 if base in MULTIPLIER_MAP else raw
        except Exception as exc:
            logger.debug("PositionMonitor: fetch perp %s failed: %s", symbol, exc)
            return 0.0

    def _compute_carry_economics(self, pd: dict, max_loss_pct: float) -> dict:
        """Compute the real carry P&L (basis + estimated funding) and the payback.

        Returns:
            dict with basis_pnl, funding_est, net_carry_pnl, payback_days
        """
        result = {"basis_pnl": 0.0, "funding_est": 0.0, "net_carry_pnl": 0.0, "payback_days": 999}
        try:
            symbol = pd["symbol"]
            entry_spot = pd["entry_price"]
            size_usd = pd["size_usd"]
            current_spot = pd["current_price"]

            # Fetch the perp price (mandatory for carry)
            current_perp = self._get_cached_perp(symbol)
            if current_perp <= 0:
                # No spot fallback! (3 audits, 20/07/2026)
                # When the perp is unavailable the basis is UNKNOWN.
                # Substituting spot would hide the risk (an artificial basis=0).
                result["data_degraded"] = True
                logger.warning("PositionMonitor: perp price missing for %s → carry economics UNKNOWN", symbol)
                return result

            # Entry perp and the funding actually accrued on this position.
            # The cycle writes the node's carry_state as context_json, which names
            # these `entry_perp` and `funding_pnl`; older rows used
            # `entry_perp_price` / `total_funding_received`. Accept both, or the
            # economics silently degrade to "UNKNOWN" for every new position.
            entry_perp = None
            funding_real = None
            fees_paid = None
            try:
                import json as _j
                ctx_raw = pd.get("context_json")
                if ctx_raw:
                    ctx = _j.loads(ctx_raw) if isinstance(ctx_raw, str) else ctx_raw
                    entry_perp = float(ctx.get("entry_perp", ctx.get("entry_perp_price", 0)) or 0)
                    funding_raw = ctx.get("funding_pnl", ctx.get("total_funding_received"))
                    if funding_raw is not None:
                        funding_real = float(funding_raw)
                    fees_raw = ctx.get("fees_paid")
                    if fees_raw is not None:
                        fees_paid = float(fees_raw)
            except Exception:
                pass

            if entry_perp is None or entry_perp <= 0:
                result["data_degraded"] = True
                logger.warning("PositionMonitor: entry_perp missing for %s → carry economics UNKNOWN", symbol)
                return result

            # Basis P&L, from the canonical module. This used to be
            # `(basis_entry - basis_now) * size_usd`, the first-order approximation
            # the node and the backtest had already dropped: on a 50% directional
            # move the two disagree by ~33%, and a delta-neutral book is exposed to
            # nothing except that differential. The monitor was the last caller
            # still computing it its own way.
            basis_pnl = basis_pnl_usd(size_usd, entry_spot, entry_perp,
                                      current_spot, current_perp)
            result["basis_pnl"] = round(basis_pnl, 4)

            # Funding. This used to be estimated at a hardcoded 0.01%/8h and then
            # dropped from the total with the comment "negligible on a daily
            # horizon": the monitor reported a basis-only P&L and ignored the leg
            # the strategy is actually built on. The node persists what it really
            # received, so read that.
            daily_funding = size_usd * 0.0001 * 3  # fallback: 0.01% x 3 per day
            if funding_real is not None:
                result["funding_est"] = round(funding_real, 6)
                result["funding_source"] = "state"
                # `ts_str` is what the monitoring loop actually puts on each row;
                # opened_at/entry_time are accepted for callers that build their own
                # dict. Reading only the latter meant the real accrued funding was in
                # hand and the daily rate still fell back to the hardcoded estimate.
                age_days = position_age_days(
                    pd.get("ts_str") or pd.get("opened_at") or pd.get("entry_time"))
                if age_days is not None and age_days > 0.01:
                    daily_funding = funding_real / age_days
            else:
                result["funding_est"] = round(daily_funding, 6)
                result["funding_source"] = "estimate"

            # Net carry P&L = basis + funding actually received - fees paid so far
            net_carry_pnl = basis_pnl + (funding_real or 0.0) - (fees_paid or 0.0)
            result["net_carry_pnl"] = round(net_carry_pnl, 4)

            # What a close at this price would actually bank: the same net figure
            # less the two exit legs. The node charges them when it closes; a close
            # driven by the monitor did not, so the same trade banked one amount or
            # another depending on which component happened to close it.
            exit_fees = exit_fee_usd(size_usd)
            result["exit_fee_usd"] = round(exit_fees, 4)
            result["realized_usd"] = round(net_carry_pnl - exit_fees, 4)

            # Payback days: how many days of funding are needed to repay the shortfall
            if net_carry_pnl < 0 and daily_funding > 0:
                result["payback_days"] = abs(net_carry_pnl) / daily_funding
            elif net_carry_pnl >= 0:
                result["payback_days"] = 0  # no loss to repay
            else:
                result["payback_days"] = 999  # zero or negative funding -> impossible to repay

        except Exception as e:
            result["data_degraded"] = True
            logger.debug("PositionMonitor: carry_economics failed for %s: %s", pd.get("symbol", "?"), e)

        return result

    @staticmethod
    def _leverage_for(symbol: str, coin: str) -> float:
        """Short perp leverage: carry_assets.yaml first, majors table otherwise.

        Single source of truth — the hardcoded table silently drifted away
        from the config whenever a leverage was edited there.
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
            # Read from carry_assets.yaml (BTC/ETH 2x, SOL/BNB 1.5x, major alts 1x)
            leverage = self._leverage_for(symbol, coin)

            # Maintenance margin rate (Binance standard: ~0.5%–2.5% depending on notional)
            maint_margin_rate = 0.005  # 0.5% conservative

            # ── Calculations ──
            notional = size_usd  # position size = notional value
            initial_margin = notional / leverage
            maintenance_margin = notional * maint_margin_rate

            # For a SHORT position: liquidation when price rises
            # liquidation_price = entry_price x (1 + 1/leverage - maint_margin_rate)
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

    # -- Price fetching (with a short-lived cache) --

    def _get_cached_price(self, symbol: str) -> float:
        """Return the current spot price, with a 30s cache to avoid hammering the exchange."""
        now = time.time()
        with self._lock:
            cached = self._price_cache.get(symbol)
            if cached and (now - cached[1]) < PRICE_CACHE_TTL_S:
                return cached[0]

        # Fetch from CCXT
        price = self._fetch_spot(symbol)
        if price > 0:
            with self._lock:
                self._price_cache[symbol] = (price, now)
        return price

    @staticmethod
    def _fetch_spot(symbol: str) -> float:
        """Fetch the spot price through CCXT Binance."""
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
    """Start the position monitor (called from main.py at startup)."""
    global _monitor
    if _monitor is None:
        _monitor = PositionMonitor.instance()
    _monitor.start()


def stop_monitor() -> None:
    """Stop the monitor (called on shutdown)."""
    global _monitor
    if _monitor:
        _monitor.stop()
        _monitor = None
