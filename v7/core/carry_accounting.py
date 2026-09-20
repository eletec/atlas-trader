"""
v7/core/carry_accounting.py — The single accounting model for the carry book.

One convention, used by the node, the backtest, the monitor and the cycle.

CONVENTION
----------
``leg_notional`` (a.k.a. ``size_usd``) is the notional of **one leg**. The spot
leg and the perp leg always carry the same notional, so:

    gross_notional = 2 * leg_notional

Fees are charged on each of the four legs (open spot, open perp, close spot,
close perp) at ``fee_bps_per_leg`` each — 48 bps round-trip at the default 12 bps.

Funding is collected on the **perp leg only**, and it is *signed*: a negative
rate is a payment the book makes, not a zero. Accruing only positive rates
overstates the P&L of every period the rate is negative.

The book is long spot and short perp, so its price P&L depends only on the
*relative* move of the two legs:

    basis_return = (spot_exit / spot_entry - 1) - (perp_exit / perp_entry - 1)

This is exact, unlike the first-order ``(perp-spot)/spot`` approximation the
node used before, which drifts whenever the two legs move.

Everything is expressed in USD on a position whose legs are ``leg_notional``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# 10 bps taker + 2 bps slippage, per leg. Four legs = 48 bps round-trip.
LEG_FEE_BPS_DEFAULT = 12.0
FEET_PER_ROUND_TRIP = 4


def per_leg_fee_usd(leg_notional: float, fee_bps: float = LEG_FEE_BPS_DEFAULT) -> float:
    """Fee charged on a single leg."""
    return leg_notional * fee_bps / 10_000.0


def entry_fee_usd(leg_notional: float, fee_bps: float = LEG_FEE_BPS_DEFAULT) -> float:
    """Opening cost: the spot leg is bought and the perp leg is sold."""
    return 2.0 * per_leg_fee_usd(leg_notional, fee_bps)


def exit_fee_usd(leg_notional: float, fee_bps: float = LEG_FEE_BPS_DEFAULT) -> float:
    """Closing cost: the spot leg is sold and the perp leg is bought back."""
    return 2.0 * per_leg_fee_usd(leg_notional, fee_bps)


def round_trip_fee_usd(leg_notional: float, fee_bps: float = LEG_FEE_BPS_DEFAULT) -> float:
    """Full round-trip cost on a position. 48 bps of ``leg_notional`` by default."""
    return entry_fee_usd(leg_notional, fee_bps) + exit_fee_usd(leg_notional, fee_bps)


def funding_payment_usd(leg_notional: float, funding_rate: float) -> float:
    """Signed funding payment for one period, on the perp leg.

    Positive rate -> the book receives. Negative rate -> the book pays.
    """
    return leg_notional * funding_rate


def basis_return(entry_spot: float, entry_perp: float, spot: float, perp: float) -> float:
    """Exact return of the hedged book, per unit of leg notional.

    Long spot + short perp: the move is measured on the two legs *relatively*,
    so a pure directional move cancels exactly.
    """
    if entry_spot <= 0 or entry_perp <= 0 or spot <= 0 or perp <= 0:
        return 0.0
    return (spot / entry_spot - 1.0) - (perp / entry_perp - 1.0)


def basis_pnl_usd(leg_notional: float, entry_spot: float, entry_perp: float,
                  spot: float, perp: float) -> float:
    """Basis P&L in dollars for a position of ``leg_notional`` per leg."""
    return leg_notional * basis_return(entry_spot, entry_perp, spot, perp)


def basis_pct(spot: float, perp: float) -> float:
    """Entry-quality filter only: (perp - spot) / spot."""
    if spot <= 0:
        return 0.0
    return (perp - spot) / spot


def funding_ma(rates: list[float], periods: int = 21) -> float:
    """Mean of the last ``periods`` funding rates (21 = 7 days at 8h funding).

    Returns 0.0 on an empty history so callers never divide by zero.
    """
    window = rates[-periods:]
    if not window:
        return 0.0
    return sum(window) / len(window)


def closed_pnl_usd(leg_notional: float, entry_spot: float, entry_perp: float,
                   exit_spot: float, exit_perp: float,
                   funding_pnl: float = 0.0, fees_paid: float = 0.0) -> float:
    """Final P&L of a closed position, from plain values.

    Same arithmetic as :meth:`CarryPosition.realized_pnl_usd`, exposed for callers
    that keep their state in their own dataclass. One implementation, two entry
    points — never a second formula.
    """
    return (funding_pnl
            + basis_pnl_usd(leg_notional, entry_spot, entry_perp, exit_spot, exit_perp)
            - fees_paid)


@dataclass
class CarryPosition:
    """The complete state of one carry position, and its P&L.

    Every consumer reads the P&L from here — the node, the backtest, the
    monitor and the cycle. There is no second implementation.
    """

    symbol: str
    leg_notional: float
    entry_spot: float = 0.0
    entry_perp: float = 0.0
    entry_time: str = ""
    fee_bps: float = LEG_FEE_BPS_DEFAULT

    funding_pnl: float = 0.0
    fees_paid: float = 0.0
    n_payments: int = 0
    n_negative_payments: int = 0
    negative_since: str | None = None

    # Rolling funding history, in periods, oldest first. 21 periods = 7 days.
    funding_history: list[float] = field(default_factory=list)
    max_history: int = 270

    # Set once the exit fees have been charged. Keeps closing idempotent: the
    # cycle, the monitor and the backtest may all ask for the realised P&L, and
    # only the first call may charge the exit legs.
    closed: bool = False

    # ── Notional ──────────────────────────────────────────────────────────

    @property
    def gross_notional(self) -> float:
        """Both legs together. This is the real market exposure."""
        return 2.0 * self.leg_notional

    @property
    def round_trip_fee(self) -> float:
        return round_trip_fee_usd(self.leg_notional, self.fee_bps)

    @property
    def funding_ma_7d(self) -> float:
        return funding_ma(self.funding_history)

    # ── Accrual ───────────────────────────────────────────────────────────

    def observe_funding(self, funding_rate: float) -> None:
        """Record a funding period in the rolling history."""
        self.funding_history.append(funding_rate)
        if len(self.funding_history) > self.max_history:
            self.funding_history = self.funding_history[-self.max_history:]

    def accrue_funding(self, funding_rate: float, now: str | None = None) -> float:
        """Accrue one funding period. **Signed** — negative rates are payments.

        Also maintains ``negative_since``: it is set on the first negative
        period and cleared on the first non-negative one.
        """
        self.observe_funding(funding_rate)
        payment = funding_payment_usd(self.leg_notional, funding_rate)
        self.funding_pnl += payment
        self.n_payments += 1
        if funding_rate < 0:
            self.n_negative_payments += 1
            if self.negative_since is None:
                self.negative_since = now or datetime.now().isoformat()
        else:
            self.negative_since = None
        return payment

    def hours_negative(self, now: datetime) -> float:
        """Hours elapsed since the funding first turned negative (0 if not)."""
        if not self.negative_since:
            return 0.0
        try:
            start = datetime.fromisoformat(self.negative_since)
        except Exception:
            return 0.0
        return max(0.0, (now - start).total_seconds() / 3600.0)

    def charge_entry_fees(self) -> float:
        fee = entry_fee_usd(self.leg_notional, self.fee_bps)
        self.fees_paid += fee
        return fee

    def charge_exit_fees(self) -> float:
        fee = exit_fee_usd(self.leg_notional, self.fee_bps)
        self.fees_paid += fee
        return fee

    # ── Valuation ─────────────────────────────────────────────────────────

    def unrealized_basis_usd(self, spot: float, perp: float) -> float:
        return basis_pnl_usd(self.leg_notional, self.entry_spot, self.entry_perp, spot, perp)

    def unrealized_basis_pct(self, spot: float, perp: float) -> float:
        """Basis return in percent (the number the node reports downstream)."""
        return basis_return(self.entry_spot, self.entry_perp, spot, perp) * 100.0

    def unrealized_total_usd(self, spot: float, perp: float) -> float:
        """What the book is worth right now: funding so far plus basis, minus fees.

        Fees are counted only once the position closes, so this is the
        mark-to-market used by the monitor while the position is open.
        """
        return self.funding_pnl + self.unrealized_basis_usd(spot, perp) - self.fees_paid

    def realized_pnl_usd(self, exit_spot: float, exit_perp: float,
                         charge_exit: bool = True) -> float:
        """Close the position and return the realised P&L.

        Realises the basis and charges the exit fees, so the number returned is
        final — no component is silently dropped.

        Idempotent: the exit fees are charged on the first call only, so asking
        for the realised P&L twice (cycle + monitor) cannot double-charge.
        """
        basis = basis_pnl_usd(self.leg_notional, self.entry_spot, self.entry_perp,
                              exit_spot, exit_perp)
        if charge_exit and not self.closed:
            self.charge_exit_fees()
            self.closed = True
        return closed_pnl_usd(self.leg_notional, self.entry_spot, self.entry_perp,
                              exit_spot, exit_perp,
                              funding_pnl=self.funding_pnl, fees_paid=self.fees_paid)

    def realized_return_pct(self, exit_spot: float, exit_perp: float,
                            charge_exit: bool = True) -> float:
        """Realised P&L as a percentage of the leg notional."""
        if self.leg_notional <= 0:
            return 0.0
        return self.realized_pnl_usd(exit_spot, exit_perp, charge_exit) / self.leg_notional * 100.0

    # ── Persistence ───────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialise for ``context_json`` so live state survives a cycle."""
        return {
            "leg_notional": round(self.leg_notional, 6),
            "entry_spot": self.entry_spot,
            "entry_perp": self.entry_perp,
            "entry_time": self.entry_time,
            "funding_pnl": round(self.funding_pnl, 8),
            "fees_paid": round(self.fees_paid, 8),
            "n_payments": self.n_payments,
            "n_negative_payments": self.n_negative_payments,
            "negative_since": self.negative_since,
            "funding_history": [round(r, 10) for r in self.funding_history[-21:]],
            "closed": self.closed,
        }

    @classmethod
    def from_dict(cls, symbol: str, data: dict[str, Any],
                  fallback_spot: float = 0.0) -> "CarryPosition":
        """Rebuild a position from its persisted form.

        Restores the funding history and ``negative_since`` too: without them the
        7-day funding filter and the negative-funding timer silently reset on
        every live cycle.
        """
        entry_spot = float(data.get("entry_spot", fallback_spot) or 0.0)
        entry_perp = float(data.get("entry_perp", 0.0) or 0.0) or entry_spot
        pos = cls(
            symbol=symbol,
            leg_notional=float(data.get("leg_notional", data.get("size_usd", 0.0)) or 0.0),
            entry_spot=entry_spot,
            entry_perp=entry_perp,
            entry_time=str(data.get("entry_time", "") or ""),
        )
        pos.funding_pnl = float(data.get("funding_pnl", data.get("total_funding_received", 0.0)) or 0.0)
        pos.fees_paid = float(data.get("fees_paid", 0.0) or 0.0)
        pos.n_payments = int(data.get("n_payments", 0) or 0)
        pos.n_negative_payments = int(data.get("n_negative_payments", 0) or 0)
        pos.negative_since = data.get("negative_since") or None
        pos.closed = bool(data.get("closed", False))
        history = data.get("funding_history") or []
        pos.funding_history = [float(r) for r in history][-pos.max_history:]
        return pos
