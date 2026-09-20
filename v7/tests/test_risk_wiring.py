"""
v7/tests/test_risk_wiring.py — the circuit breaker has to reach the entry path.

`PositionMonitor` has always maintained a circuit breaker that is documented as
"Tier 0 — blocks new entries" while the market data it depends on is unusable.
Nothing read it: the flag was an instance attribute of the monitor, and entry is
decided in `run_carry_cycle`, which never sees that instance. This pins the two
halves together so the documented behaviour is the actual behaviour.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from v7 import run_carry_cycle
from v7.core import risk_state


class TestRiskState:
    def test_defaults_to_inactive(self):
        risk_state.set_circuit_breaker(False)
        assert risk_state.circuit_breaker_active() is False
        assert risk_state.circuit_breaker_reason() == ""

    def test_publishes_and_clears_the_flag(self):
        risk_state.set_circuit_breaker(True, "stale prices (600s)")
        assert risk_state.circuit_breaker_active() is True
        assert "stale" in risk_state.circuit_breaker_reason()

        risk_state.set_circuit_breaker(False)
        assert risk_state.circuit_breaker_active() is False
        assert risk_state.circuit_breaker_reason() == ""

    def test_clearing_also_clears_the_reason(self):
        risk_state.set_circuit_breaker(True, "reason")
        risk_state.set_circuit_breaker(False, "ignored while inactive")
        assert risk_state.circuit_breaker_reason() == ""


class TestWiring:
    def test_the_monitor_publishes_its_breaker(self):
        from v7 import position_monitor
        src = inspect.getsource(position_monitor)
        assert "set_circuit_breaker(True" in src
        assert "set_circuit_breaker(False" in src

    def test_the_entry_path_consults_it(self):
        src = inspect.getsource(run_carry_cycle)
        assert "circuit_breaker_active()" in src
        # and it must actually suppress the signal, not merely log it
        assert 'signal = "flat"' in src

    def test_a_missing_perp_is_not_replaced_by_spot(self):
        """Substituting spot invents basis = 0, which is the state the entry filter
        is looking for — a fabricated price could open a position."""
        src = inspect.getsource(run_carry_cycle)
        assert "perp_price if perp_price > 0 else spot_price" not in src
        assert "perp price fetch failed" in src

    def test_the_cycle_uses_the_settled_period_not_the_current_rate(self):
        """`fetch_current_funding()` returns 0.0 for a real zero rate AND for a
        failed call, so booking from it can mark a period done with a $0 payment
        and lose the real settlement for good."""
        src = inspect.getsource(run_carry_cycle)
        assert "fetch_latest_settlement()" in src
        assert "settlement is None" in src
        assert '"funding_ts": funding_ts.isoformat()' in src

    def test_the_kill_switch_close_uses_the_canonical_pnl(self):
        """Both monitor close paths must bank the same amount: funding, the exact
        basis move, and BOTH fee legs. The kill-switch used to bank the mark."""
        from v7 import position_monitor
        src = inspect.getsource(position_monitor)
        assert src.count("_econ = self._compute_carry_economics(pd, max_loss_pct)") >= 2


class TestWalkForwardParity:
    def test_funding_is_not_shifted_by_a_period(self):
        """The node credits funding_rate[t] to a position already open at t and
        uses it only for the decision when flat. Shifting put the walk-forward one
        period behind the single-asset backtest."""
        from v7 import backtest_walkforward
        src = inspect.getsource(backtest_walkforward)
        assert 'funding_rate"].shift(1)' not in src

    def test_a_missing_perp_is_not_replaced_by_spot(self):
        from v7 import backtest_walkforward
        src = inspect.getsource(backtest_walkforward)
        assert "perp_price = spot_price" not in src

    def test_prices_are_paginated_eight_hour_bars(self):
        from v7 import backtest_walkforward
        src = inspect.getsource(backtest_walkforward)
        assert '_paginate(' in src
        assert '"8h"' in src
        assert '"1d"' not in src
