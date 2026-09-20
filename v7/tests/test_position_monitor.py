"""
v7/tests/test_position_monitor.py — Portfolio drawdown kill-switch tests.

The kill-switch is a single comparison, but getting it wrong is expensive: on
20 Sep 2026 the faulty version evaluated to "P&L < +20%", which is true for every
possible portfolio state. The first monitor pass with any open position closed the
whole book (`KILL-SWITCH PORTFOLIO_DD — 1 position(s) closed`), and because Tier 2+
requires a manual reset, the kill-switch then stayed disarmed permanently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

## The diagnostic print() calls contain non-ASCII characters (arrows, minus signs).
## On Windows the console is cp1252 and pytest -s crashes with UnicodeEncodeError
## even though the assertions pass. Force UTF-8 on stdout/stderr.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from v7.position_monitor import PORTFOLIO_DD_PCT_DEFAULT, portfolio_dd_breached


class TestPortfolioDrawdownKillSwitch:
    """The kill-switch must fire *below* the limit and never above it."""

    def test_constant_is_negative_by_convention(self):
        """Like MAX_LOSS_PCT_DEFAULT, the constant carries the sign."""
        assert PORTFOLIO_DD_PCT_DEFAULT == -0.20

    @pytest.mark.parametrize("pnl_pct", [0.0, 0.01, 1.0, 5.0, 19.9, 20.0, 100.0])
    def test_never_fires_on_a_flat_or_profitable_book(self, pnl_pct):
        """REGRESSION: the buggy version fired for any P&L below +20%."""
        assert portfolio_dd_breached(pnl_pct, PORTFOLIO_DD_PCT_DEFAULT) is False

    @pytest.mark.parametrize("pnl_pct", [-0.1, -1.0, -5.0, -19.9])
    def test_does_not_fire_before_the_limit(self, pnl_pct):
        assert portfolio_dd_breached(pnl_pct, PORTFOLIO_DD_PCT_DEFAULT) is False

    @pytest.mark.parametrize("pnl_pct", [-20.1, -25.0, -50.0])
    def test_fires_below_the_limit(self, pnl_pct):
        assert portfolio_dd_breached(pnl_pct, PORTFOLIO_DD_PCT_DEFAULT) is True

    def test_exact_limit_is_not_a_breach(self):
        """-20.0% is the limit itself; the comparison is strict."""
        assert portfolio_dd_breached(-20.0, PORTFOLIO_DD_PCT_DEFAULT) is False

    def test_robust_to_a_positively_signed_constant(self):
        """Passing +0.20 must behave identically to -0.20."""
        for pnl in (-21.0, -20.1, -20.0, -19.9, 0.0, 30.0):
            assert (portfolio_dd_breached(pnl, 0.20)
                    == portfolio_dd_breached(pnl, -0.20))

    def test_generates_an_error_and_a_normal_run_message(self):
        """A short end-to-end sanity check on the numbers the monitor logs."""
        limit = abs(PORTFOLIO_DD_PCT_DEFAULT) * 100
        healthy = [-5.0, -19.0, 0.0, 12.0]
        fatal = [-20.5, -31.0]
        assert not any(portfolio_dd_breached(p, PORTFOLIO_DD_PCT_DEFAULT) for p in healthy)
        assert all(portfolio_dd_breached(p, PORTFOLIO_DD_PCT_DEFAULT) for p in fatal)
        assert limit == 20.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
