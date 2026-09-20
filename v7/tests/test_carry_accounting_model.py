"""
v7/tests/test_carry_accounting_model.py — Tests for the single accounting model.

These pin down the three defects an external review found in the previous
accounting, each of which made the strategy look better than it is:

1. **Funding was unsigned.** Only positive rates were accrued, so every period
   of negative funding was free. Fixed by ``accrue_funding`` being signed.
2. **The basis was never realised.** The node dropped ``unrealized_pnl_pct`` to
   zero when a position closed, so the accumulated basis vanished instead of
   becoming a realised gain or loss. Fixed by ``realized_pnl_usd``.
3. **``size_usd`` had no defined meaning.** The node treated it as one leg's
   notional while the accounting test treated it as both legs. Fixed by naming
   it ``leg_notional`` and deriving ``gross_notional``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

## The diagnostic print() calls contain non-ASCII characters. On Windows the
## console is cp1252 and pytest -s crashes with UnicodeEncodeError even though
## the assertions pass. Force UTF-8 on stdout/stderr.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from v7.core.carry_accounting import (
    LEG_FEE_BPS_DEFAULT,
    CarryPosition,
    basis_pct,
    basis_pnl_usd,
    basis_return,
    entry_fee_usd,
    exit_fee_usd,
    funding_ma,
    funding_payment_usd,
    round_trip_fee_usd,
)


class TestConvention:
    """The notional convention must be unambiguous."""

    def test_leg_notional_is_one_leg(self):
        pos = CarryPosition(symbol="BTC/USDT", leg_notional=400.0)
        assert pos.leg_notional == 400.0
        assert pos.gross_notional == 800.0

    def test_round_trip_is_48bps_of_the_leg(self):
        """4 legs x 12 bps."""
        assert LEG_FEE_BPS_DEFAULT == 12.0
        assert round_trip_fee_usd(1000.0) == pytest.approx(4.80)
        assert entry_fee_usd(1000.0) == pytest.approx(2.40)
        assert exit_fee_usd(1000.0) == pytest.approx(2.40)
        assert entry_fee_usd(1000.0) + exit_fee_usd(1000.0) == pytest.approx(4.80)

    def test_fees_are_two_legs_each_way(self):
        """Entry is spot bought + perp sold: two legs, not one."""
        assert entry_fee_usd(1000.0) == pytest.approx(2 * 1000.0 * 12.0 / 10_000.0)


class TestSignedFunding:
    """REGRESSION: the node accrued only positive funding."""

    def test_negative_period_reduces_the_pnl(self):
        pos = CarryPosition(symbol="BTC/USDT", leg_notional=2000.0)
        pos.accrue_funding(0.0020)          # +20 bps received
        assert pos.funding_pnl == pytest.approx(4.00)
        pos.accrue_funding(-0.0010)         # -10 bps paid
        assert pos.funding_pnl == pytest.approx(2.00)
        pos.accrue_funding(-0.0030)         # -30 bps paid
        assert pos.funding_pnl == pytest.approx(-4.00)

    def test_a_negative_period_is_not_a_zero(self):
        """The bug was that this returned the same as an empty period."""
        paid = CarryPosition(symbol="X", leg_notional=1000.0)
        paid.accrue_funding(-0.002)
        assert paid.funding_pnl < 0

    def test_payment_helper_is_signed(self):
        assert funding_payment_usd(1000.0, 0.001) == pytest.approx(1.0)
        assert funding_payment_usd(1000.0, -0.001) == pytest.approx(-1.0)

    def test_negative_periods_are_counted(self):
        pos = CarryPosition(symbol="X", leg_notional=1000.0)
        pos.accrue_funding(0.001)
        pos.accrue_funding(-0.001)
        pos.accrue_funding(-0.001)
        assert pos.n_payments == 3
        assert pos.n_negative_payments == 2


class TestNegativeFundingTimer:
    """The 72h timer must survive a process restart, hence the persistence."""

    def test_negative_since_is_set_then_cleared(self):
        pos = CarryPosition(symbol="X", leg_notional=1000.0)
        pos.accrue_funding(-0.001, now="2026-09-20T00:00:00")
        assert pos.negative_since == "2026-09-20T00:00:00"
        pos.accrue_funding(-0.001, now="2026-09-20T08:00:00")
        assert pos.negative_since == "2026-09-20T00:00:00"   # not reset
        pos.accrue_funding(0.001, now="2026-09-20T16:00:00")
        assert pos.negative_since is None                     # cleared

    def test_hours_negative(self):
        from datetime import datetime, timedelta
        pos = CarryPosition(symbol="X", leg_notional=1000.0, entry_time="2026-01-01T00:00:00")
        pos.negative_since = "2026-09-20T00:00:00"
        assert pos.hours_negative(datetime.fromisoformat("2026-09-20T03:00:00")) == pytest.approx(3.0)
        assert pos.hours_negative(datetime.fromisoformat("2026-09-23T01:00:00")) == pytest.approx(73.0)

    def test_hours_negative_is_zero_when_positive(self):
        from datetime import datetime
        pos = CarryPosition(symbol="X", leg_notional=1000.0)
        assert pos.hours_negative(datetime(2026, 9, 20)) == 0.0


class TestBasis:
    """The book is delta-neutral: only the *relative* move matters."""

    def test_perfect_hedge_has_no_basis_pnl(self):
        assert basis_return(100.0, 100.0, 120.0, 120.0) == pytest.approx(0.0)
        assert basis_return(100.0, 100.0, 50.0, 50.0) == pytest.approx(0.0)

    def test_pure_directional_move_cancels_exactly(self):
        """Spot +20%, perp +20% -> nothing, whatever the notional."""
        assert basis_pnl_usd(1000.0, 100.0, 100.0, 120.0, 120.0) == pytest.approx(0.0)

    def test_basis_widening_is_a_loss(self):
        """Long spot + short perp loses when the perp premium grows."""
        # entry basis 0.2%, exit basis 0.7% -> ~50 bps loss
        assert basis_return(100.0, 100.2, 101.0, 101.7) == pytest.approx(-0.00497006, abs=1e-7)
        assert basis_pnl_usd(1000.0, 100.0, 100.2, 101.0, 101.7) < 0

    def test_basis_contracting_is_a_gain(self):
        assert basis_return(100.0, 101.0, 100.0, 100.0) > 0

    def test_the_exact_formula_beats_the_old_approximation(self):
        """The node used (perp-spot)/spot, which drifts when both legs move."""
        entry_spot, entry_perp = 100.0, 100.5
        spot, perp = 150.0, 150.5          # same premium, both legs +50%
        approx = (entry_perp - entry_spot) / entry_spot - (perp - spot) / spot
        exact = basis_return(entry_spot, entry_perp, spot, perp)
        assert approx == pytest.approx(0.00166667, abs=1e-8)
        assert exact == pytest.approx(0.00248756, abs=1e-8)
        # the approximation is 33% off - it is not a rounding difference
        assert abs(exact / approx - 1) > 0.4

    def test_basis_pct_is_the_entry_filter_only(self):
        assert basis_pct(100.0, 100.2) == pytest.approx(0.002)
        assert basis_pct(0.0, 100.0) == 0.0


class TestRealizedPnl:
    """The basis must be realised at close, and fees charged once."""

    def test_flat_prices_negative_funding(self):
        """Leg 1000, +20 bps funding, 48 bps round trip -> -28 bps."""
        pos = CarryPosition(symbol="X", leg_notional=1000.0, entry_spot=100.0, entry_perp=100.0)
        pos.charge_entry_fees()
        pos.accrue_funding(0.0020)
        assert pos.realized_return_pct(100.0, 100.0) == pytest.approx(-0.28)

    def test_realizing_twice_does_not_double_charge(self):
        """The cycle and the monitor may both ask for the realised P&L."""
        pos = CarryPosition(symbol="X", leg_notional=1000.0, entry_spot=100.0, entry_perp=100.0)
        pos.charge_entry_fees()
        pos.accrue_funding(0.0020)
        first = pos.realized_pnl_usd(100.0, 100.0)
        second = pos.realized_pnl_usd(100.0, 100.0)
        assert first == pytest.approx(2.00 - 4.80)
        assert second == pytest.approx(first)
        assert pos.fees_paid == pytest.approx(4.80)

    def test_realizes_the_basis_instead_of_dropping_it(self):
        """REGRESSION: the node zeroed the basis on close."""
        pos = CarryPosition(symbol="X", leg_notional=1000.0, entry_spot=100.0, entry_perp=100.2)
        pos.charge_entry_fees()
        pos.accrue_funding(0.0030)
        pnl = pos.realized_pnl_usd(101.0, 101.7)          # basis widened 50 bps
        basis = basis_pnl_usd(1000.0, 100.0, 100.2, 101.0, 101.7)
        assert basis < 0
        assert pnl == pytest.approx(3.00 + basis - 4.80)
        assert pnl != pytest.approx(3.00 - 4.80)          # the buggy value

    def test_fees_are_charged_once(self):
        pos = CarryPosition(symbol="X", leg_notional=1000.0, entry_spot=100.0, entry_perp=100.0)
        pos.charge_entry_fees()
        pos.realized_pnl_usd(100.0, 100.0)
        assert pos.fees_paid == pytest.approx(4.80)

    def test_can_skip_exit_fees_for_an_open_position(self):
        pos = CarryPosition(symbol="X", leg_notional=1000.0, entry_spot=100.0, entry_perp=100.0)
        pos.charge_entry_fees()
        pos.realized_pnl_usd(100.0, 100.0, charge_exit=False)
        assert pos.fees_paid == pytest.approx(2.40)

    def test_total_identity(self):
        """realized = signed funding + realised basis - fees."""
        pos = CarryPosition(symbol="X", leg_notional=1000.0, entry_spot=100.0, entry_perp=100.0)
        pos.charge_entry_fees()
        for rate in (0.001, 0.002, -0.003, 0.0005):
            pos.accrue_funding(rate)
        pnl = pos.realized_pnl_usd(105.0, 105.5)
        expected = pos.funding_pnl + basis_pnl_usd(1000.0, 100.0, 100.0, 105.0, 105.5) - pos.fees_paid
        assert pnl == pytest.approx(expected)


class TestPersistence:
    """Live state must survive the node being rebuilt on every cycle."""

    def test_round_trip_preserves_everything(self):
        src = CarryPosition(symbol="BTC/USDT", leg_notional=400.0,
                            entry_spot=100.0, entry_perp=100.1, entry_time="2026-09-01T00:00:00")
        src.charge_entry_fees()
        for rate in (0.001, 0.002, -0.0015, 0.0008):
            src.accrue_funding(rate, now="2026-09-10T00:00:00")

        restored = CarryPosition.from_dict("BTC/USDT", src.to_dict())

        assert restored.leg_notional == pytest.approx(src.leg_notional)
        assert restored.entry_spot == pytest.approx(src.entry_spot)
        assert restored.entry_perp == pytest.approx(src.entry_perp)
        assert restored.entry_time == src.entry_time
        assert restored.funding_pnl == pytest.approx(src.funding_pnl)
        assert restored.fees_paid == pytest.approx(src.fees_paid)
        assert restored.n_payments == src.n_payments
        assert restored.funding_history == pytest.approx(src.funding_history)

    def test_funding_history_survives_so_the_7d_ma_is_real(self):
        """REGRESSION: a rebuilt node started with an empty history, so the
        7-day funding MA collapsed to the current rate."""
        src = CarryPosition(symbol="BTC/USDT", leg_notional=1000.0)
        for rate in [0.0001] * 20 + [0.01]:
            src.accrue_funding(rate)
        restored = CarryPosition.from_dict("BTC/USDT", src.to_dict())
        assert len(restored.funding_history) == 21
        assert restored.funding_ma_7d < 0.001          # not the last spike
        assert restored.funding_ma_7d == pytest.approx(funding_ma(src.funding_history))

    def test_negative_since_survives(self):
        src = CarryPosition(symbol="BTC/USDT", leg_notional=1000.0)
        src.accrue_funding(-0.002, now="2026-09-19T12:00:00")
        restored = CarryPosition.from_dict("BTC/USDT", src.to_dict())
        assert restored.negative_since == "2026-09-19T12:00:00"

    def test_nothing_is_lost_when_history_exceeds_the_cap(self):
        src = CarryPosition(symbol="X", leg_notional=1000.0)
        for i in range(400):
            src.accrue_funding(0.0001 * (i % 5))
        assert len(src.funding_history) == src.max_history
        assert len(CarryPosition.from_dict("X", src.to_dict()).funding_history) == 21


class TestFundingMovingAverage:
    def test_empty_history_is_zero_not_an_error(self):
        assert funding_ma([]) == 0.0

    def test_uses_the_last_window(self):
        rates = [0.001] * 30 + [0.01] * 21
        assert funding_ma(rates, 21) == pytest.approx(0.01)
        assert funding_ma(rates, 51) == pytest.approx((30 * 0.001 + 21 * 0.01) / 51)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
