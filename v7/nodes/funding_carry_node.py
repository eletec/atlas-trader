"""
v7/nodes/funding_carry_node.py — V7 Funding Carry node.

Fetches the funding rate, evaluates the economic hurdle, produces a signal.
Called by v7/run_carry_cycle.py (single carry cycle, every 8h).

Output: carry signal (open/close/flat) + expected_return + size
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np

from v4.core.node import NodeRunResult, NodeStatus
from v7.core.carry_accounting import (
    LEG_FEE_BPS_DEFAULT,
    basis_return,
    closed_pnl_usd,
    entry_fee_usd,
    exit_fee_usd,
    funding_ma,
    funding_payment_usd,
)

# Funding arrives every 8h. Keep 90 days of it (270 periods) so the
# 60th-percentile filter has a real distribution to compare against: the window
# held 21 periods, enough for a 7-day mean but never enough for the filter that
# needs 30, so live ran without it while the backtest ran with it.
FUNDING_WINDOW = 270

logger = logging.getLogger("funding_carry_node")


@dataclass
class FundingCarryState:
    """Persistent state of the Funding Carry node.

    NOTIONAL CONVENTION — ``entry_capital`` (a.k.a. ``size_usd``) is the notional
    of ONE leg. The spot leg and the perp leg always carry the same notional, so
    the gross exposure is ``2 * entry_capital``. See v7/core/carry_accounting.py;
    nothing here re-implements the arithmetic.

    ``total_funding_received`` is **signed**: a negative funding period is a
    payment the book makes. It used to accumulate positive rates only, which made
    every negative period free and systematically overstated the P&L.
    """
    symbol: str
    position_open: bool = False
    entry_capital: float = 0.0       # notional of ONE leg
    entry_spot: float = 0.0          # spot price at entry
    entry_perp: float = 0.0          # perp price at entry
    entry_time: str = ""             # ISO open timestamp (time-stop)
    negative_since: Optional[str] = None  # ISO timestamp
    total_funding_received: float = 0.0   # signed
    n_payments: int = 0
    n_negative_payments: int = 0
    fees_paid: float = 0.0           # entry legs, then exit legs on close
    closed: bool = False
    # Funding period already booked (ISO, floored to the settlement boundary).
    # Without it a manual /carry/run or a restart cycle books the same payment
    # a second time while the backtest books it once.
    last_funding_ts: Optional[str] = None
    funding_history: list[float] = field(default_factory=list)   # one row per period
    staking_earned: float = 0.0      # USDT staking yield on idle capital
    last_funding_rate: float = 0.0
    last_signal: str = "flat"
    last_update: str = ""

    def to_dict(self) -> dict:
        """Serialise the position so it survives a container restart."""
        return {
            "leg_notional": self.entry_capital,
            "entry_spot": self.entry_spot,
            "entry_perp": self.entry_perp,
            "entry_time": self.entry_time,
            "funding_pnl": self.total_funding_received,
            "fees_paid": self.fees_paid,
            "n_payments": self.n_payments,
            "n_negative_payments": self.n_negative_payments,
            "negative_since": self.negative_since,
            "funding_history": self.funding_history[-FUNDING_WINDOW:],
            "last_funding_ts": self.last_funding_ts,
            "closed": self.closed,
        }

    def load_position_dict(self, data: dict) -> bool:
        """Restore an open position from its persisted form.

        Restores ``entry_perp``, ``negative_since`` and the funding window too —
        without them the basis at entry reads as zero, the 72h negative-funding
        timer restarts on every cycle and the 7-day funding MA collapses to the
        current rate.
        """
        if not data:
            return False
        self.entry_capital = float(data.get("leg_notional", data.get("size_usd", 0)) or 0)
        self.entry_spot = float(data.get("entry_spot", 0) or 0)
        self.entry_perp = float(data.get("entry_perp", 0) or 0) or self.entry_spot
        self.entry_time = str(data.get("entry_time", "") or "")
        self.total_funding_received = float(
            data.get("funding_pnl", data.get("total_funding_received", 0)) or 0)
        self.fees_paid = float(data.get("fees_paid", 0) or 0)
        self.n_payments = int(data.get("n_payments", 0) or 0)
        self.n_negative_payments = int(data.get("n_negative_payments", 0) or 0)
        self.negative_since = data.get("negative_since") or None
        self.last_funding_ts = data.get("last_funding_ts") or None
        self.closed = bool(data.get("closed", False))
        history = data.get("funding_history") or []
        if history:
            self.funding_history = [float(r) for r in history][-FUNDING_WINDOW:]
        self.position_open = self.entry_capital > 0
        return self.position_open


class FundingCarryNode:
    """DAG node for the funding carry strategy.

    Compatible with the Atlas DAG framework.
    Implements the minimal interface: run(inputs), execute(inputs), output_schema().

    Usage inside a DAG:
        node = FundingCarryNode(node_id="btc_carry", symbol="BTC/USDT", capital=5000)
        outputs = node.run({"spot_price": 67000})
    """

    def __init__(
        self,
        node_id: str = "funding_carry",
        symbol: str = "BTC/USDT",
        capital: float = 10_000,
        fraction: float = 0.50,
        min_funding: float = 0.00005,
        max_funding: float = 0.003,
        exit_after_hours: int = 72,    # exit on negative funding after 72h (Grok)
        kelly_fraction: float = 0.35,  # fractional Kelly 35% (Grok)
        max_hold_days: int = 14,        # time-stop: forced exit after N days
        stop_loss_pct: float = -0.05,   # stop-loss on the basis: -5%
        cooldown_hours: int = 24,       # anti-churn: do not reopen within N hours of closing
        exchange_name: str = "binance",  # binance | bybit | okx | kraken
        fee_bps: float = 10.0,       # standard Binance spot fee (0.1% = 10bps)
        slippage_bps: float = 2.0,
        params: dict | None = None,
        meta: object = None,  # DAG framework NodeMeta
    ):
        # If called through the DAG framework (params dict), extract the values
        if params is not None:
            symbol = params.get("symbol", symbol)
            capital = params.get("capital", capital)
            fraction = params.get("fraction", fraction)
            min_funding = params.get("min_funding", min_funding)
            max_funding = params.get("max_funding", max_funding)
            exit_after_hours = params.get("exit_after_hours", exit_after_hours)
            max_hold_days = params.get("max_hold_days", max_hold_days)
            stop_loss_pct = params.get("stop_loss_pct", stop_loss_pct)
            exchange_name = params.get("exchange", exchange_name)
        
        self.node_id = node_id
        self.params = params or {}       # DAG framework
        self.meta = meta                 # DAG framework
        self.symbol = symbol
        self.capital = capital
        self.fraction = fraction
        self.min_funding = min_funding
        self.max_funding = max_funding
        self.exit_after_hours = exit_after_hours
        self.kelly_fraction = kelly_fraction
        self.max_hold_days = max_hold_days
        self.stop_loss_pct = stop_loss_pct
        self.cooldown_hours = int(params.get("cooldown_hours", cooldown_hours)) if params else cooldown_hours
        self.exchange_name = exchange_name
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        
        # Regime filter: 30d volatility is the minimum to enter (via DAG params or default)
        self.min_volatility_30d = float(self.params.get("min_volatility_30d", 0.02))
        
        # Economic hurdle (configurable via grid search)
        # Default 5% = SOFR alone (grid search: 25/26 assets prefer 5%)
        self.economic_hurdle = float(self.params.get("economic_hurdle", 0.05))
        
        self.state = FundingCarryState(symbol=symbol)
        self._funding_rate_history: list[float] = []  # 7d moving average (~21 samples)

        # Simulated clock. Backtests inject inputs["now"] so the time-based exits
        # (time-stop, DERISK/CLOSE zones, negative-funding timer, cooldown) are
        # evaluated on simulated days. Without it they all read the real wall
        # clock, which a backtest burns in seconds - so none of them ever fired
        # and every position stayed open until the end of the run.
        # Live leaves it None and the node uses the real time as before.
        self._sim_now: datetime | None = None
        
        # Restore state from the DB (survives restarts)
        # Not in backtest mode (no live DB)
        backtest = params.get("_backtest", False) if params else False
        if not backtest:
            self._restore_state()

    def _now(self) -> datetime:
        """Current time: the simulated bar timestamp in a backtest, real time live."""
        return self._sim_now if self._sim_now is not None else datetime.now()

    def _is_backtest(self) -> bool:
        """True when the node runs inside the backtester (no live DB access)."""
        return bool(self.params.get("_backtest", False))

    def _funding_period_key(self, explicit: Optional[str] = None) -> Optional[str]:
        """The funding period the current rate belongs to, or None in a backtest.

        Preferred form: the settlement timestamp the exchange reports, passed in by
        the caller. It is the real period boundary, so it is correct for 4h and 8h
        contracts alike and survives a clock that is off or a cycle that runs late.

        Fallback: floor the clock onto the 8h boundary. Binance settles at fixed
        boundaries and the fetched rate is the one settled most recently, so every
        cycle inside one period lands on the same key and the second books nothing.
        """
        if self._is_backtest():
            return None  # one row per period by construction
        if explicit:
            try:
                dt = datetime.fromisoformat(str(explicit).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                dt = None
            if dt is not None:
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt.isoformat(timespec="seconds")
        dt = self._now()
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        step = max(int(self.params.get("funding_interval_hours", 8)), 1)
        return dt.replace(hour=(dt.hour // step) * step, minute=0,
                          second=0, microsecond=0).isoformat(timespec="seconds")

    def _seed_funding_history(self) -> None:
        """Make the rolling funding window real, from the state then the exchange.

        The node is rebuilt on every live cycle, so an in-memory window would never
        hold more than the current sample: the "7-day MA" degrades to "is the rate
        positive right now", and the 60th-percentile filter - which needs 30
        periods - never activates at all. It seeded 21, so live ran without the
        filter while the backtest ran with it.
        """
        if self._is_backtest():
            return  # the simulated bars supply the history
        if not self._funding_rate_history and self.state.funding_history:
            self._funding_rate_history = list(self.state.funding_history)
        if len(self._funding_rate_history) >= FUNDING_WINDOW:
            return
        try:
            import ccxt
            exchange = ccxt.binanceusdm({"enableRateLimit": True})
            # Pass the unified symbol: ccxt resolves it itself. The previous version
            # called exchange.market(...) on a freshly built exchange without ever
            # calling load_markets(), which is not guaranteed to return anything —
            # and a silent seed failure is exactly how the percentile filter stays
            # disabled, since it needs 30 periods and one observation is not enough.
            rows = exchange.fetch_funding_rate_history(
                self._perp_symbol(self.symbol), limit=FUNDING_WINDOW)
            if rows:
                self._funding_rate_history = [
                    float(r.get("fundingRate") or 0) for r in rows
                ][-FUNDING_WINDOW:]
                logger.debug("[%s] funding window seeded: %d periods",
                             self.node_id, len(self._funding_rate_history))
        except Exception as exc:
            logger.debug("[%s] funding window seed skipped: %s", self.node_id, exc)

    def _realize_close(self, spot_price: float, perp_price: float) -> float:
        """Close the position: realise the basis and charge the two exit legs.

        Idempotent — the cycle and the monitor may both ask for the final P&L
        without the exit legs being charged twice.
        """
        exit_perp = perp_price if perp_price > 0 else spot_price
        exit_fee = 0.0
        if not self.state.closed:
            exit_fee = exit_fee_usd(self.state.entry_capital, LEG_FEE_BPS_DEFAULT)
        pnl = closed_pnl_usd(
            self.state.entry_capital, self.state.entry_spot, self.state.entry_perp,
            spot_price, exit_perp,
            funding_pnl=self.state.total_funding_received,
            fees_paid=self.state.fees_paid + exit_fee,
        )
        self.state.fees_paid += exit_fee
        self.state.closed = True
        return pnl
    
    def _restore_state(self):
        """Check whether a carry position is already open for this symbol.

        Restores EVERY field needed to track the position:
        entry_spot, entry_perp, entry_time, entry_capital,
        total_funding_received, n_payments.
        Without these values the SL/TP/time-stop checks are silently skipped.
        """
        try:
            from storage.paper_trader import get_open_positions
            import json as _json
            open_pos = get_open_positions(symbol=self.symbol)
            carry_pos = [p for p in open_pos if p.get("action") in ("carry", "short")]
            if carry_pos:
                pos = carry_pos[0]
                ctx_raw = pos.get("context_json")
                ctx: dict = {}
                if ctx_raw:
                    try:
                        ctx = _json.loads(ctx_raw) if isinstance(ctx_raw, str) else ctx_raw
                    except Exception:
                        ctx = {}
                # Prefer the persisted accounting state: it carries entry_perp,
                # negative_since and the funding window, none of which can be
                # rebuilt from the trade row alone. Fall back to the row itself
                # for positions written before that state existed.
                persisted = (ctx or {}).get("carry_state") or {}
                if not persisted:
                    persisted = {
                        "leg_notional": pos.get("size_usd", 0),
                        "entry_spot": pos.get("entry_price", 0),
                        "entry_perp": ctx.get("entry_perp_price", 0),
                        "entry_time": pos.get("timestamp", ""),
                        "funding_pnl": ctx.get("total_funding_received", 0),
                        "n_payments": ctx.get("n_payments", 0),
                        "negative_since": ctx.get("negative_since"),
                        "funding_history": ctx.get("funding_history"),
                    }
                if self.state.load_position_dict(persisted):
                    logger.info(
                        "[%s] Carry position restored: spot=%.6g perp=%.6g capital=$%.0f "
                        "opened=%s funding=$%.4f fees=$%.2f",
                        self.node_id, self.state.entry_spot, self.state.entry_perp,
                        self.state.entry_capital,
                        self.state.entry_time[:19] if self.state.entry_time else "?",
                        self.state.total_funding_received, self.state.fees_paid,
                    )
        except Exception as e:
            logger.debug("[%s] DB restore skipped: %s", self.node_id, e)

    def _get_funding_interval(self) -> float:
        """Return the funding interval in hours as reported by Binance (3 audits, 20/07/2026).

        Falls back to 8h when the API is unreachable, or inside a backtest.
        """
        # Backtest: no CCXT call, use the standard 8h
        if self.params.get("_backtest", False):
            return 8.0
        # Simple cache (the interval does not change at runtime)
        if hasattr(self, "_cached_funding_interval"):
            return self._cached_funding_interval
        try:
            import ccxt
            exchange = ccxt.binance({"enableRateLimit": True})
            # Use fetch_funding_rate(), which is lighter than load_markets()
            market = exchange.market(self.symbol)
            info = market.get("info", {}) if market else {}
            interval = float(info.get("fundingIntervalHours", 8) or 8)
            self._cached_funding_interval = max(4, min(interval, 24))
            return self._cached_funding_interval
        except Exception:
            return 8.0  # standard fallback

    def _funding_in_top_percentile(self, funding_rate: float, pct: float = 0.20,
                                    window_days: int = 90) -> bool:
        """Check whether the current funding_rate sits in the top pct% of recent history.

        Uses the local history (at most 21 samples = 7 days).
        For window_days > 7 this uses what is available plus a conservative assumption.
        (3 audits, 20/07/2026)"""
        if not self._funding_rate_history or len(self._funding_rate_history) < 5:
            return True  # not enough history -> let it through
        # Use the available history (up to 21 samples = 7 days)
        sorted_rates = sorted(self._funding_rate_history)
        threshold_idx = int(len(sorted_rates) * (1 - pct))
        if threshold_idx >= len(sorted_rates):
            threshold_idx = len(sorted_rates) - 1
        threshold = sorted_rates[threshold_idx]
        return funding_rate >= threshold

    # ── DAG framework compatibility ──
    
    @staticmethod
    def output_schema() -> dict[str, str]:
        return {
            "signal": "str", "size_usd": "float", "expected_return": "float",
            "confidence": "float", "reason": "str", "funding_rate": "float",
            "annual_funding_pct": "float", "position_open": "bool",
            "total_funding_received": "float", "n_payments": "int",
            "decision": "dict",  # format PaperTrader: {action, size_usd, entry_price, ...}
        }
    
    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"symbol": "str", "spot_price": "float", "funding_rate": "float", "perp_price": "float"}
    
    def execute(self, inputs: dict[str, Any]) -> NodeRunResult:
        """DAG framework entry point -> delegates to run()."""
        import time as _time
        t0 = _time.time()
        try:
            outputs = self.run(inputs)
            return NodeRunResult(
                node_id=self.node_id,
                status=NodeStatus.DONE,
                outputs=outputs,
                duration_ms=(_time.time() - t0) * 1000,
            )
        except Exception as e:
            return NodeRunResult(
                node_id=self.node_id,
                status=NodeStatus.ERROR,
                error=str(e),
                duration_ms=(_time.time() - t0) * 1000,
            )
    
    # ── Data fetching ──
    
    def _get_exchange(self):
        """Return the configured CCXT instance (binance | bybit | okx | kraken)."""
        import ccxt
        ex_map = {
            "binance": ccxt.binance, "bybit": ccxt.bybit,
            "okx": ccxt.okx, "kraken": ccxt.kraken,
        }
        return ex_map.get(self.exchange_name, ccxt.binance)({"enableRateLimit": True})

    @staticmethod
    def _perp_symbol(symbol: str) -> str:
        """Convert a spot symbol into a USDⓈ-M perp symbol (handles x1000 contracts)."""
        base = symbol.split("/")[0]
        MULTIPLIER_MAP = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "BONK": "1000BONK",
                          "FLOKI": "1000FLOKI", "LUNC": "1000LUNC"}
        base_perp = MULTIPLIER_MAP.get(base, base)
        return f"{base_perp}/USDT:USDT"

    @staticmethod
    def _perp_multiplier(symbol: str) -> float:
        """USDⓈ-M perp contract multiplier: 1000 for ×1000 contracts
        (the contract price is 1000× the token's spot price), 1 otherwise.
        Essential for the basis (perp − spot)/spot to be correct."""
        base = symbol.split("/")[0]
        return 1000.0 if base in {"PEPE", "SHIB", "BONK", "FLOKI", "LUNC"} else 1.0

    @staticmethod
    def _staking_annual_rate() -> float:
        """Annual staking rate on idle capital (carry_assets.yaml, key
        global.staking_annual). Read from the config so that the value shown
        in the admin panel actually takes effect."""
        try:
            from v7.core.asset_config import get_global_params
            return float(get_global_params().get("staking_annual", 0.05))
        except Exception:
            return 0.05

    def fetch_latest_settlement(self) -> Optional[tuple[datetime, float]]:
        """The most recently SETTLED funding period, as (settlement time, rate).

        `fetch_current_funding()` returns 0.0 both when the rate really is zero and
        when the call fails, and the caller could not tell the two apart. Combined
        with the idempotency guard that is worse than a wrong number: a failed fetch
        at 16:00 booked a $0 payment and marked the period done, so the real
        settlement was never counted at all.

        Returns None on failure so the caller can skip the asset and try again.
        The timestamp is the exchange's own, which also removes the need to guess
        whether a contract settles every 4h or every 8h.
        """
        try:
            exchange = self._get_exchange()
            symbol_perp = self._perp_symbol(self.symbol)
            rates = exchange.fetch_funding_rates([symbol_perp])
            row = rates.get(symbol_perp) if rates else None
            if not row:
                return None
            ts = row.get("fundingTimestamp") or row.get("timestamp")
            rate = row.get("fundingRate")
            if ts is None or rate is None:
                return None
            return (datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc),
                    float(rate))
        except Exception as exc:
            logger.warning("Settlement fetch failed for %s: %s", self.symbol, exc)
            return None

    def fetch_current_funding(self) -> float:
        """Fetch the current funding rate."""
        try:
            import ccxt
            exchange = self._get_exchange()
            symbol_perp = self._perp_symbol(self.symbol)
            rates = exchange.fetch_funding_rates([symbol_perp])
            if rates and symbol_perp in rates:
                return float(rates[symbol_perp]["fundingRate"])
        except Exception as e:
            logger.warning("Funding fetch failed for %s: %s", self.symbol, e)
        
        # Fallback: Binance public API
        try:
            import requests
            symbol_clean = self._perp_symbol(self.symbol).replace("/", "").replace(":USDT", "")
            resp = requests.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": symbol_clean},
                timeout=10,
            )
            data = resp.json()
            return float(data.get("lastFundingRate", 0))
        except Exception:
            return 0.0
    
    def fetch_spot_price(self) -> float:
        """Fetch the current spot price with retries + logging on failure."""
        import time as _time
        last_err = ""
        for attempt in range(3):
            try:
                exchange = self._get_exchange()
                ticker = exchange.fetch_ticker(self.symbol)
                price = float(ticker.get("last", 0))
                if price > 0:
                    return price
                last_err = f"price=0 from ticker"
            except Exception as e:
                last_err = str(e)[:120]
            if attempt < 2:
                _time.sleep(1.0 * (attempt + 1))  # backoff: 1s, 2s
        logger.warning("[%s] fetch_spot_price FAILED after 3 attempts: %s", self.node_id, last_err)
        return 0.0
    
    def fetch_perp_price(self) -> float:
        """Fetch the perpetual price (normalised to the per-token price) with retries."""
        import time as _time
        last_err = ""
        for attempt in range(3):
            try:
                exchange = self._get_exchange()
                symbol_perp = self._perp_symbol(self.symbol)
                ticker = exchange.fetch_ticker(symbol_perp)
                price = float(ticker.get("last", 0))
                if price > 0:
                    return price / self._perp_multiplier(self.symbol)
                last_err = f"price=0 from ticker"
            except Exception as e:
                last_err = str(e)[:120]
            if attempt < 2:
                _time.sleep(1.0 * (attempt + 1))
        logger.warning("[%s] fetch_perp_price FAILED after 3 attempts: %s", self.node_id, last_err)
        return 0.0

    def _last_close_age_hours(self) -> float | None:
        """Hours since this symbol last closed (None when it never closed).

        Anti-churn: prevents reopening an asset whose funding just
        flipped (e.g. SHIB/PEPE) and which would pay round-trip fees over
        and over.
        """
        # A backtest has no live trade history - never read the production DB.
        if self._is_backtest():
            return None
        try:
            from storage.database import get_connection
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT closed_at FROM v4_trades "
                    "WHERE symbol=? AND status='closed' "
                    "ORDER BY closed_at DESC LIMIT 1",
                    (self.symbol,),
                ).fetchone()
            if not row or not row[0]:
                return None
            closed_at = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - closed_at).total_seconds() / 3600
        except Exception:
            return None
    
    # ── Decision logic ──

    
    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Run the Funding Carry node.

        Args:
            inputs: dict with:
                - spot_price (float): current spot price
                - funding_rate (float, optional): overrides the automatic fetch
                - perp_price (float, optional): perpetual price
        
        Returns:
            dict with signal, size_usd, expected_return, confidence, reason
        """
        t0 = time.time()
        
        # The node is bound to ONE asset: self.symbol is authoritative.
        # The internal state (open position, committed capital, funding history)
        # is not reset between calls - so callers instantiate
        # one node per asset (run_carry_cycle, backtests).

        # Pick up the simulated timestamp when the caller provides one (backtest).
        _now_in = inputs.get("now")
        self._sim_now = None
        if _now_in is not None:
            try:
                self._sim_now = (_now_in if isinstance(_now_in, datetime)
                                 else datetime.fromisoformat(str(_now_in)))
            except (TypeError, ValueError):
                self._sim_now = None
        
        spot_price = float(inputs.get("spot_price", 0))
        funding_rate = float(inputs.get("funding_rate", 0))
        perp_price = float(inputs.get("perp_price", spot_price))
        
        # Fetch spot/perp price when not provided (except in backtests)
        if spot_price == 0 and not self.params.get("_backtest", False):
            spot_price = self.fetch_spot_price()
        
        if perp_price == 0 and not self.params.get("_backtest", False):
            perp_price = self.fetch_perp_price()
        if perp_price == 0:
            perp_price = spot_price
        
        # Fetch funding rate when not provided (except in backtests: keep 0)
        if funding_rate == 0 and not self.params.get("_backtest", False):
            funding_rate = self.fetch_current_funding()
        
        self.state.last_funding_rate = funding_rate
        self.state.last_update = self._now().isoformat()
        
        # Keep the funding history for the 7d MA and the percentile (max 270 samples = 90d)
        # The node is rebuilt on every live cycle, so an in-memory window would
        # never exceed one sample and the "7-day MA" would just be the current
        # rate. Backfill it from the exchange when it is too short.
        self._seed_funding_history()
        self._funding_rate_history.append(funding_rate)
        self._funding_rate_history = self._funding_rate_history[-FUNDING_WINDOW:]
        # One series, persisted. `state.funding_history` and `_funding_rate_history`
        # were two variables holding the same idea and only the first was written
        # to the database, so the window never survived a cycle.
        self.state.funding_history = list(self._funding_rate_history)
        funding_ma_7d = funding_ma(self._funding_rate_history)
        
        # ── Decision ──
        signal = "flat"
        size_usd = 0.0
        expected_return = 0.0
        confidence = 0.5
        reason = ""
        unrealized_pct = 0.0
        realized_this_run = 0.0
        economic_hurdle = self.economic_hurdle  # scoped for both open/close branches
        
        # Annualise - uses Binance's real interval (3 audits, 2026-07-20)
        funding_interval_h = self._get_funding_interval()
        periods_per_year = (24 / funding_interval_h) * 365
        annual_funding = funding_rate * periods_per_year
        
        # Basis: entry-quality filter only.
        # The basis is NOT annualised into the expected return (there is no convergence
        # guarantee, and a negative basis must not cancel the funding yield).
        # See below: expected_return = annual_funding only.
        if perp_price > 0:
            basis_pct = (perp_price - spot_price) / spot_price
        else:
            basis_pct = 0.0
        
        if not self.state.position_open:
            # -- Staking on idle capital --
            staking_annual = self._staking_annual_rate()  # carry_assets.yaml (global)
            idle_capital = self.capital * self.fraction
            staking_8h = idle_capital * staking_annual / (365 * 3)  # 3 funding periods of 8h per day
            self.state.staking_earned += staking_8h
            
            # -- Entry opportunity --
            # Anti-churn cooldown: do not reopen a recently closed asset
            _close_age_h = self._last_close_age_hours()
            if _close_age_h is not None and _close_age_h < self.cooldown_hours:
                reason = f"cooldown {self.cooldown_hours}h after close ({_close_age_h:.1f}h)"
                confidence = 0.1
            # Filter 1: instantaneous funding within range
            elif funding_rate >= self.min_funding and funding_rate <= self.max_funding:
                # Filter 2: positive 7d funding MA (avoids isolated spikes)
                if funding_ma_7d <= 0:
                    reason = f"funding 7d MA={funding_ma_7d*100:.4f}% <= 0 -> wait"
                    confidence = 0.2
                # Filter 3: basis not too unfavourable
                elif basis_pct < -0.003:
                    reason = f"unfavourable basis ({basis_pct*100:.4f}%)"
                    confidence = 0.3
                else:
                    # -- Expected return (2026-07-22) --
                    # Funding is annualised; the basis is an entry-quality filter only.
                    # The basis is NOT annualised into the return - there is no convergence
                    # guarantee, and a negative basis must not cancel the funding
                    # yield (GPT round 2: expected_basis_return = 0).
                    expected_return = annual_funding  # funding return only
                    
                    # -- Economic hurdle = SOFR (pure opportunity cost) --
                    # The risk premia (exchange, stablecoin, operational) are covered
                    # by safety_cap and stress_loss_pct, not by the hurdle.
                    # Grid search V7.3: 25 of 26 assets prefer 5% over 7%.
                    
                    # -- Annualised costs (deducted from the return, not from the hurdle) --
                    round_trip_cost = 0.0048   # 48bps (40 fees + 8 slippage)
                    # The annualised cost depends on the real time-stop: a short hold
                    # makes the fees prohibitive (48bps amortised over very few days).
                    # Ex: max_hold_days=14 -> 12.5%/yr in fees; 60d -> 2.9%/yr.
                    estimated_hold = max(self.max_hold_days, 1)
                    annualized_cost = round_trip_cost * 365 / estimated_hold
                    net_expected_return = expected_return - annualized_cost
                    
                    # -- Percentile filter (relative, separate from the economic hurdle) --
                    percentile_ok = True
                    if len(self._funding_rate_history) >= 30:
                        annualized_hist = sorted([r * periods_per_year for r in self._funding_rate_history])
                        p60 = annualized_hist[int(len(annualized_hist) * 0.60)]
                        percentile_ok = annual_funding >= p60
                    
                    if net_expected_return > economic_hurdle and percentile_ok:
                            # ── Risk budgeting (GPT 5.5 + 3 audits) ──
                            # -- Risk budgeting - per-asset stress loss (from config or fallback) --
                            try:
                                from v7.core.asset_config import get_asset_params
                                _cfg = get_asset_params(self.symbol)
                                stress_loss_pct = float(_cfg.get("stress_loss_pct", 0.10))
                            except Exception:
                                _per_asset_stress = {
                                    "BTC": 0.04, "ETH": 0.04,
                                    "SOL": 0.08, "BNB": 0.08,
                                    "XRP": 0.12, "ADA": 0.12, "DOGE": 0.12,
                                    "AVAX": 0.10, "LINK": 0.10, "DOT": 0.10,
                                    "LTC": 0.06, "NEAR": 0.12, "SUI": 0.12,
                                }
                                stress_loss_pct = _per_asset_stress.get(
                                    self.symbol.split("/")[0].upper(), 0.10)
                            net_return = net_expected_return - economic_hurdle
                            score = max(0, net_return) / stress_loss_pct if stress_loss_pct > 0 else 0
                            raw_size = self.capital * self.fraction * min(score, 0.25)

                            # -- Safety caps (from config or fallback) --
                            try:
                                _cfg = get_asset_params(self.symbol)
                                max_size = float(_cfg.get("safety_cap", 200))
                            except Exception:
                                safety_caps = {
                                    "BTC": 400, "ETH": 300, "SOL": 200, "BNB": 200,
                                    "XRP": 200, "ADA": 150, "DOGE": 100,
                                    "AVAX": 150, "LINK": 150, "DOT": 150,
                                    "LTC": 200, "NEAR": 100, "SUI": 100,
                                }
                                coin = self.symbol.split("/")[0].upper()
                                max_size = safety_caps.get(coin, 200)
                            min_size = 50

                            size_usd = min(raw_size, max_size)
                            if size_usd < min_size:
                                reason = f"size ${size_usd:.0f} < min ${min_size} -> skip"
                                confidence = 0.3
                            else:
                                # ── Global Allocator check (3 audits consensus, 20/07/2026) ──
                                from v7.core.global_allocator import can_open_position
                                alloc_ok, alloc_reason = can_open_position(
                                    self.symbol, size_usd, score)
                                if not alloc_ok:
                                    reason = f"GlobalAllocator: {alloc_reason}"
                                    confidence = 0.3
                                else:
                                    # ── DB safety check (anti-duplicate, 24/07/2026) ──
                                    # Skipped in backtest: the production DB would
                                    # otherwise force position_open=True on a symbol
                                    # that a live cycle happens to hold right now.
                                    _db_carry = []
                                    if not self._is_backtest():
                                        from storage.paper_trader import get_open_positions
                                        _db_open = get_open_positions(symbol=self.symbol)
                                        _db_carry = [p for p in _db_open if p.get("action") in ("carry", "short")]
                                    if _db_carry:
                                        # Sync in-memory state with DB reality
                                        self.state.position_open = True
                                        reason = f"DB safety: position already open (id={_db_carry[0].get('trade_id','?')})"
                                        confidence = 0.1
                                        logger.warning("[%s] %s", self.node_id, reason)
                                    else:
                                        self.state.position_open = True
                                        self.state.entry_capital = size_usd
                                        self.state.entry_spot = spot_price
                                        self.state.entry_perp = perp_price if perp_price > 0 else spot_price
                                        self.state.entry_time = self._now().isoformat()
                                        # Per-position accounting: reset on every open so
                                        # these numbers describe THIS position and not a
                                        # running total the consumer would have to undo.
                                        self.state.total_funding_received = 0.0
                                        self.state.n_payments = 0
                                        self.state.n_negative_payments = 0
                                        self.state.negative_since = None
                                        self.state.last_funding_ts = None
                                        self.state.closed = False
                                        self.state.fees_paid = entry_fee_usd(size_usd, LEG_FEE_BPS_DEFAULT)
                                        signal = "open_carry"
                                        confidence = min(0.90, 0.50 + score * 2)
                                        reason = (f"funding={funding_rate*100:.4f}% MA={funding_ma_7d*100:.4f}% "
                                                  f"-> net={net_expected_return*100:.1f}%/yr (hurdle={economic_hurdle*100:.0f}%) | "
                                                  f"size=${size_usd:.0f} (score={score:.2f}, cap=${max_size})")
                    else:
                        reason = f"net return {net_expected_return*100:.1f}%/yr < {economic_hurdle*100:.0f}% hurdle"
                        confidence = 0.5
            else:
                reason = f"funding={funding_rate*100:.4f}% outside [min={self.min_funding*100:.4f}%, max={self.max_funding*100:.2f}%]"
        else:
            # -- Position open --
            # Compute unrealised P&L (basis only; the delta is hedged)
            if self.state.entry_spot > 0 and spot_price > 0:
                # Exact relative return of the hedged book (long spot, short perp).
                # The previous (perp-spot)/spot difference was a first-order
                # approximation: on a 50% directional move it drifts by ~33%.
                unrealized_pct = basis_return(self.state.entry_spot, self.state.entry_perp,
                                              spot_price, perp_price or spot_price)
                unrealized_usd = unrealized_pct * self.state.entry_capital
                
                # Stop-loss: basis loss > 5% -> close
                if unrealized_pct < self.stop_loss_pct:
                    signal = "close_carry"
                    reason = f"STOP-LOSS: basis loss {unrealized_pct*100:.1f}% > {abs(self.stop_loss_pct)*100:.0f}% -> close"
                    confidence = 0.95
                    logger.warning("[%s] %s", self.node_id, reason)
                
                # -- Economic exit (3 audits, 2026-07-20) --
                # Replaces the strict 14d time-stop.
                # ZONES: HEALTHY (<14d), REVIEW (14-30d), DERISK (30-60d), CLOSE (>60d)
                if signal != "close_carry" and self.state.entry_time:
                    try:
                        entry_dt = datetime.fromisoformat(self.state.entry_time)
                        days_held = (self._now() - entry_dt).total_seconds() / 86400

                        # The zones scale with max_hold_days, which IS the forced
                        # exit. They used to be hardcoded at 14/30/60 while the
                        # entry gate amortised its fees over max_hold_days: the
                        # gate assumed one holding period and the exit imposed
                        # another, so a grid search over max_hold_days changed
                        # the gate and never the exit it was named after.
                        hard_stop = max(int(self.max_hold_days), 1)
                        derisk_after = hard_stop * 0.5
                        review_after = hard_stop * 0.25

                        if days_held > hard_stop:
                            signal = "close_carry"
                            reason = (f"ECONOMIC STOP (ZONE CLOSE): {days_held:.0f}d "
                                      f"> {hard_stop}d max")
                            confidence = 0.85
                            logger.warning("[%s] %s", self.node_id, reason)
                        elif days_held > derisk_after:
                            # DERISK: close when forward funding no longer justifies the position
                            forward_funding = funding_rate * periods_per_year
                            exit_cost_annual = 0.0048 * (365 / max(days_held, 1))  # 48bps round-trip amortised
                            if forward_funding < economic_hurdle + exit_cost_annual:
                                signal = "close_carry"
                                reason = (f"ECONOMIC STOP (ZONE DERISK): {days_held:.0f}d, "
                                          f"forward funding={forward_funding*100:.1f}%/yr < "
                                          f"hurdle+exit={(economic_hurdle+exit_cost_annual)*100:.1f}%/yr")
                                confidence = 0.75
                                logger.warning("[%s] %s", self.node_id, reason)
                            else:
                                logger.info("[%s] DERISK zone: %dd, forward funding=%.1f%% > costs -> hold",
                                           self.node_id, days_held, forward_funding*100)
                        elif days_held > review_after:
                            logger.info("[%s] REVIEW zone: %dd — monitoring", self.node_id, days_held)
                    except Exception:
                        pass
            else:
                unrealized_pct = 0.0
            
            # ── Cross-margin risk monitoring ──
            # In paper trading we simulate the short perp liquidation risk
            # When the unrealised loss > 80% of capital → liquidation alert
            if unrealized_pct < -0.80 and self.state.position_open:
                logger.error("[%s] ⚠️ LIQUIDATION RISK: loss=%.1f%% → short perp would be liquidated!",
                           self.node_id, unrealized_pct * 100)
                # In paper mode we do not close automatically but raise a strong alert
            
            # Funding settles once per period. Two cycles inside one period — a
            # manual POST /carry/run, or the startup cycle right after a restart —
            # would both book the same payment, while the backtest books it exactly
            # once. The key is None in a backtest, so this guards only the live path.
            period_key = self._funding_period_key(inputs.get("funding_ts"))
            already_booked = period_key is not None and period_key == self.state.last_funding_ts

            if signal == "close_carry":
                pass  # already handled above
            elif already_booked:
                signal = "flat"
                reason = (f"carry active | period {period_key} already booked "
                          f"({self.state.n_payments} payments, funding="
                          f"{self.state.total_funding_received:+.4f})")
                confidence = 0.70
            else:
                # Funding is SIGNED: a negative period is a payment the book
                # makes. Accruing positive rates only overstated the P&L.
                payment = funding_payment_usd(self.state.entry_capital, funding_rate)
                self.state.total_funding_received += payment
                self.state.n_payments += 1
                if period_key is not None:
                    self.state.last_funding_ts = period_key
                if funding_rate < 0:
                    self.state.n_negative_payments += 1
                    now = self._now()
                    if self.state.negative_since is None:
                        self.state.negative_since = now.isoformat()

                    try:
                        neg_start = datetime.fromisoformat(self.state.negative_since)
                        hours_neg = (now - neg_start).total_seconds() / 3600
                    except Exception:
                        hours_neg = 0

                    if hours_neg > self.exit_after_hours:
                        signal = "close_carry"
                        reason = f"negative funding > {self.exit_after_hours}h -> close"
                        confidence = 0.85
                    else:
                        signal = "flat"
                        reason = (f"negative funding for {hours_neg:.0f}h "
                                  f"(max {self.exit_after_hours}h) | funding={payment:+.4f}")
                        confidence = 0.50
                else:
                    self.state.negative_since = None
                    signal = "flat"
                    reason = (f"carry active | funding received="
                              f"{self.state.total_funding_received:.4f} "
                              f"({self.state.n_payments} payments)")
                    confidence = 0.70

            # Realise the position the moment the signal closes it: the basis and
            # the exit legs used to be dropped, which is why the backtest reported
            # funding minus fees and never the basis. This is the ONLY place that
            # flips `position_open`: branches that close the position only set the
            # signal, otherwise this block would see it already closed and the P&L
            # would vanish.
            if signal == "close_carry" and self.state.position_open:
                realized_this_run = self._realize_close(spot_price, perp_price)
                self.state.position_open = False
                self.state.closed = True
                reason = f"{reason} | realized=${realized_this_run:+.2f}"
                logger.info("[%s] carry closed, realized=$%.2f: %s",
                            self.node_id, realized_this_run, reason)
        
        elapsed = time.time() - t0
        
        # ── Output ──
        # Build a PaperTrader-compatible "decision".
        # For carry trades: NO spot SL/TP (semantically wrong for a delta-neutral book).
        # PositionMonitor uses the unified max_loss_pct (-5%) for the exit.
        # The DAG handles the basis stop-loss and the time-stop.
        # Score rounded to 0-100 for the dashboard display
        _display_score = round(min(score, 0.25) / 0.25 * 100) if signal == "open_carry" else 0
        decision = {
            "action": "flat",
            "size_usd": round(size_usd, 2),
            "entry_price": spot_price,
            "stop_loss": 0,       # no spot stop-loss on carry
            "take_profit": 0,     # no spot take-profit on carry
            "atr": 0,
            "strategy_type": "funding_carry",  # marker for downstream consumers
            "carry_signal": signal,
            "carry_expected_return": round(expected_return, 4),
            "carry_annual_pct": round(annual_funding * 100, 2),
            "score": _display_score,  # for the dashboard display
        }
        if signal == "open_carry":
            decision["action"] = "carry"
            # Two-leg accounting: store the entry prices to compute the basis P&L
            decision["entry_perp_price"] = perp_price if perp_price > 0 else spot_price
            decision["entry_basis"] = round(basis_pct, 6)
        elif signal == "close_carry":
            decision["action"] = "close_carry"
        
        outputs = {
            "signal": signal,
            "size_usd": round(size_usd, 2),
            "expected_return": round(expected_return, 4),
            "confidence": round(confidence, 2),
            "reason": reason,
            "funding_rate": funding_rate,
            "annual_funding_pct": round(annual_funding * 100, 2),
            "position_open": self.state.position_open,
            "total_funding_received": round(self.state.total_funding_received, 4),
            "realized_pnl_usd": round(realized_this_run, 4),
            "n_payments": self.state.n_payments,
            "n_negative_payments": self.state.n_negative_payments,
            "fees_paid": round(self.state.fees_paid, 4),
            # Notional convention: size_usd / entry_capital is ONE leg.
            "leg_notional": round(self.state.entry_capital, 2),
            "gross_notional": round(2 * self.state.entry_capital, 2),
            # Full position state, so the cycle can persist it in context_json and
            # the next cycle can restore entry_perp, negative_since and the
            # funding window instead of starting from zero.
            "carry_state": self.state.to_dict(),
            "staking_earned": round(self.state.staking_earned, 4),
            "basis_pct": round(basis_pct * 100, 4),
            "entry_perp_price": perp_price if perp_price > 0 else spot_price,
            "entry_basis": round(basis_pct, 6),
            "unrealized_pnl_pct": round(unrealized_pct * 100, 2) if self.state.position_open else 0,
            "elapsed_s": round(elapsed, 3),
            "decision": decision,
        }
        
        logger.debug("[%s] signal=%s funding=%.6f size=$%.0f reason=%s",
                     self.node_id, signal, funding_rate, size_usd, reason)
        
        return outputs
    
    def reset(self):
        """Reset the state (for backtests)."""
        self.state = FundingCarryState(symbol=self.symbol)
        self._funding_rate_history = []
        self._sim_now = None


# ── Test ──
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    
    node = FundingCarryNode(symbol="BTC/USDT", capital=10_000)
    
    # Simulate an opening signal
    result = node.run({
        "spot_price": 67000,
        "funding_rate": 0.0001,  # 0.01%
        "perp_price": 67005,
    })
    print(f"Signal: {result['signal']} | Size: ${result['size_usd']:.0f} | "
          f"Expected: {result['expected_return']*100:.1f}%/yr | {result['reason']}")
    
    # Simulate a funding payment
    result2 = node.run({
        "spot_price": 67100,
        "funding_rate": 0.0001,
    })
    print(f"Signal: {result2['signal']} | Funding received: {result2['total_funding_received']:.6f}")
    
    # Simulate negative funding
    node.state.negative_since = (datetime.now() - timedelta(hours=50)).isoformat()
    result3 = node.run({
        "spot_price": 66800,
        "funding_rate": -0.00005,
    })
    print(f"Signal: {result3['signal']} | {result3['reason']}")
