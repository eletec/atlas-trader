"""
v7/tests/test_node_state.py — Node state: persistence, signed funding, realisation.

The node is rebuilt from scratch on every live cycle (run_carry_cycle.go), so
anything kept only in memory is lost every 8 hours. These tests pin down what
must survive that rebuild, and what the node must realise when it closes.

Three defects from the external review are covered here:

- ``entry_perp`` was overwritten with ``entry_spot`` on restore, so the basis at
  entry read as zero.
- ``negative_since`` was never restored, so the 72h negative-funding timer
  restarted on every cycle and could never fire.
- The funding window was never restored, so the "7-day MA" filter degenerated to
  "is the current rate positive".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from v7.nodes.funding_carry_node import FundingCarryNode, FundingCarryState


def make_state(**kwargs) -> FundingCarryState:
    st = FundingCarryState(symbol="BTC/USDT")
    st.position_open = True
    st.entry_capital = 1000.0
    st.entry_spot = 100.0
    st.entry_perp = 100.5          # a real basis, not ~0
    st.entry_time = "2026-09-01T00:00:00"
    st.fees_paid = 2.40
    for k, v in kwargs.items():
        setattr(st, k, v)
    return st


class TestStatePersistence:
    def test_round_trip_preserves_the_whole_position(self):
        src = make_state()
        src.total_funding_received = 3.25
        src.n_payments = 7
        src.n_negative_payments = 2
        src.negative_since = "2026-09-19T12:00:00"
        src.funding_history = [0.001] * 20 + [-0.002]

        dst = FundingCarryState(symbol="BTC/USDT")
        assert dst.load_position_dict(src.to_dict()) is True

        assert dst.entry_capital == pytest.approx(1000.0)
        assert dst.entry_spot == pytest.approx(100.0)
        assert dst.entry_perp == pytest.approx(100.5)      # not entry_spot
        assert dst.entry_time == "2026-09-01T00:00:00"
        assert dst.total_funding_received == pytest.approx(3.25)
        assert dst.fees_paid == pytest.approx(2.40)
        assert dst.n_payments == 7
        assert dst.n_negative_payments == 2
        assert dst.negative_since == "2026-09-19T12:00:00"
        assert dst.funding_history == pytest.approx(src.funding_history)
        assert dst.position_open is True

    def test_entry_perp_is_not_silently_replaced_by_spot(self):
        """REGRESSION: the old restore did `entry_perp = entry_spot`."""
        src = make_state(entry_perp=101.0)
        dst = FundingCarryState(symbol="BTC/USDT")
        dst.load_position_dict(src.to_dict())
        assert dst.entry_perp != dst.entry_spot

    def test_negative_since_survives_so_the_timer_can_fire(self):
        """REGRESSION: without this the 72h timer never accumulated."""
        src = make_state(negative_since="2026-09-17T00:00:00")
        dst = FundingCarryState(symbol="BTC/USDT")
        dst.load_position_dict(src.to_dict())
        assert dst.negative_since == "2026-09-17T00:00:00"

    def test_funding_history_survives_so_the_ma_is_a_real_ma(self):
        """REGRESSION: an empty window made the MA equal the current rate."""
        src = make_state()
        src.funding_history = [0.0001] * 20
        dst = FundingCarryState(symbol="BTC/USDT")
        dst.load_position_dict(src.to_dict())
        assert len(dst.funding_history) == 20

    def test_empty_payload_is_not_a_position(self):
        dst = FundingCarryState(symbol="BTC/USDT")
        assert dst.load_position_dict({}) is False
        assert dst.position_open is False

    def test_a_position_without_perp_falls_back_to_spot(self):
        """Legacy rows have no perp price; the basis is then honestly unknown."""
        dst = FundingCarryState(symbol="BTC/USDT")
        dst.load_position_dict({"leg_notional": 500.0, "entry_spot": 100.0})
        assert dst.entry_perp == pytest.approx(100.0)
        assert dst.entry_capital == pytest.approx(500.0)


class TestRealizeClose:
    """Closing must realise the basis — not just report funding minus fees."""

    def _node_in_position(self, entry_spot=100.0, entry_perp=100.5) -> FundingCarryNode:
        node = FundingCarryNode(node_id="t", symbol="BTC/USDT", capital=2000)
        node.state = FundingCarryState(symbol="BTC/USDT")
        node.state.position_open = True
        node.state.entry_capital = 1000.0
        node.state.entry_spot = entry_spot
        node.state.entry_perp = entry_perp
        node.state.entry_time = "2026-09-01T00:00:00"
        node.state.total_funding_received = 5.00      # signed, already accrued
        node.state.fees_paid = 2.40                   # entry legs charged
        return node

    def test_realises_the_basis_and_the_exit_legs(self):
        node = self._node_in_position()
        pnl = node._realize_close(100.0, 101.0)       # basis widened
        # basis = 1000 * ((100/100 - 1) - (101/100.5 - 1)) = -4.975
        assert pnl == pytest.approx(5.00 - 4.9751 - 4.80, abs=1e-3)
        assert node.state.fees_paid == pytest.approx(4.80)
        assert node.state.closed is True

    def test_funding_only_would_have_been_the_buggy_answer(self):
        node = self._node_in_position()
        pnl = node._realize_close(100.0, 101.0)
        funding_minus_fees = 5.00 - 4.80
        assert pnl < funding_minus_fees            # the basis is a real loss
        assert pnl != pytest.approx(funding_minus_fees)

    def test_is_idempotent(self):
        node = self._node_in_position()
        first = node._realize_close(100.0, 101.0)
        second = node._realize_close(100.0, 101.0)
        assert second == pytest.approx(first)
        assert node.state.fees_paid == pytest.approx(4.80)

    def test_a_flat_close_keeps_only_funding_minus_fees(self):
        node = self._node_in_position(entry_spot=100.0, entry_perp=100.0)
        pnl = node._realize_close(100.0, 100.0)
        assert pnl == pytest.approx(5.00 - 4.80)

    def test_missing_perp_price_falls_back_to_spot(self):
        node = self._node_in_position(entry_spot=100.0, entry_perp=100.0)
        assert node._realize_close(100.0, 0.0) == pytest.approx(5.00 - 4.80)


class TestSeedGuard:
    """The exchange backfill must never run in a backtest or when already warm.

    The exchange is stubbed: the previous version of the "already full" test used 21
    periods, which was the window size at the time. Once the window grew to 270 the
    test silently started making a real network call, which is both slow and flaky.
    """

    def test_no_seed_in_a_backtest(self):
        node = FundingCarryNode(node_id="t", symbol="BTC/USDT", params={"_backtest": True})
        node._seed_funding_history()          # must not touch the network
        assert node._funding_rate_history == []

    def test_no_seed_when_the_window_is_already_full(self, monkeypatch):
        from v7.nodes.funding_carry_node import FUNDING_WINDOW
        node = FundingCarryNode(node_id="t", symbol="BTC/USDT")
        node._funding_rate_history = [0.0001] * FUNDING_WINDOW
        before = list(node._funding_rate_history)

        called = []
        monkeypatch.setattr(node, "_is_backtest", lambda: False)
        monkeypatch.setitem(sys.modules, "ccxt", _stub_ccxt([], called))

        node._seed_funding_history()
        assert called == [], "the exchange was queried with a full window"
        assert node._funding_rate_history == before

    def test_seeds_from_the_exchange_when_the_old_bar_was_not_enough(self, monkeypatch):
        """21 periods satisfied the 7-day MA but left the percentile filter dead:
        it needs 30 and the live node could never get there."""
        from v7.nodes.funding_carry_node import FUNDING_WINDOW
        node = FundingCarryNode(node_id="t", symbol="BTC/USDT")
        node._funding_rate_history = [0.0001] * 21

        called = []
        rows = [{"fundingRate": 0.0002}] * FUNDING_WINDOW
        monkeypatch.setattr(node, "_is_backtest", lambda: False)
        monkeypatch.setitem(sys.modules, "ccxt", _stub_ccxt(rows, called))

        node._seed_funding_history()
        assert called, "the exchange was never queried"
        assert len(node._funding_rate_history) == FUNDING_WINDOW

    def test_a_failed_seed_leaves_the_window_alone(self, monkeypatch):
        node = FundingCarryNode(node_id="t", symbol="BTC/USDT")
        node._funding_rate_history = [0.0001] * 21
        before = list(node._funding_rate_history)
        monkeypatch.setattr(node, "_is_backtest", lambda: False)
        monkeypatch.setitem(sys.modules, "ccxt", _stub_ccxt(None, []))
        node._seed_funding_history()
        assert node._funding_rate_history == before


def _stub_ccxt(rows, called):
    """A ccxt module whose exchange records that it was built and returns `rows`."""
    class _Exchange:
        def fetch_funding_rate_history(self, symbol, limit=None):
            if rows is None:
                raise RuntimeError("exchange unavailable")
            return rows

    class _Module:
        @staticmethod
        def binanceusdm(config):
            called.append(1)
            return _Exchange()

    return _Module()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
