"""
v7/tests/test_funding_idempotency.py — one settlement, one booking.

The node is rebuilt on every live cycle, so funding arrives as "the current rate"
rather than as a stream of settled periods. Nothing recorded *which* period had
been booked, so a manual `POST /carry/run`, or the cycle that runs right after a
container restart, added the same payment a second time. The backtest supplies
exactly one row per 8h period, so the two engines disagreed by construction.

The percentile filter is covered here too: it needs 30 periods of history, the
live seed provided 21, so live silently ran without a filter the backtest applied.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from v7.nodes.funding_carry_node import (
    FUNDING_WINDOW,
    FundingCarryNode,
    FundingCarryState,
)


def live_node(monkeypatch) -> FundingCarryNode:
    """A node that behaves live but never touches the network or the database.

    `params={"_backtest": True}` keeps every DB path skipped, then `_is_backtest`
    is overridden so the funding-period guard is active — that is the branch under
    test. `_seed_funding_history` and `_last_close_age_hours` are stubbed because
    they reach for Binance and sqlite respectively.
    """
    node = FundingCarryNode(node_id="t_idem", symbol="BTC/USDT", capital=1000.0,
                            params={"_backtest": True})
    monkeypatch.setattr(node, "_is_backtest", lambda: False)
    monkeypatch.setattr(node, "_seed_funding_history", lambda: None)
    monkeypatch.setattr(node, "_last_close_age_hours", lambda: None)
    return node


def open_position(node: FundingCarryNode) -> None:
    st = node.state
    st.position_open = True
    st.entry_capital = 1000.0
    st.entry_spot = 100.0
    st.entry_perp = 100.0
    st.entry_time = "2026-09-20T00:00:00"
    st.closed = False


INPUTS = {"symbol": "BTC/USDT", "spot_price": 100.0, "perp_price": 100.0,
          "funding_rate": 0.0002}


class TestFundingPeriodKey:
    def test_is_none_in_a_backtest(self):
        """One row per period by construction — nothing to guard."""
        node = FundingCarryNode(node_id="t_bt", symbol="BTC/USDT", capital=1000.0,
                                params={"_backtest": True})
        assert node._funding_period_key() is None

    def test_floors_onto_the_settlement_boundary(self, monkeypatch):
        node = live_node(monkeypatch)
        for hour, minute, expected in (
            (9, 0, "2026-09-20T08:00:00"),
            (10, 30, "2026-09-20T08:00:00"),
            (8, 0, "2026-09-20T08:00:00"),
            (16, 0, "2026-09-20T16:00:00"),
            (17, 45, "2026-09-20T16:00:00"),
            (0, 5, "2026-09-20T00:00:00"),
        ):
            node._sim_now = datetime(2026, 9, 20, hour, minute, 0)
            assert node._funding_period_key() == expected

    def test_interval_is_configurable(self, monkeypatch):
        """4h-funding contracts settle twice as often."""
        node = FundingCarryNode(node_id="t4", symbol="BTC/USDT", capital=1000.0,
                                params={"_backtest": True,
                                        "funding_interval_hours": 4})
        monkeypatch.setattr(node, "_is_backtest", lambda: False)
        node._sim_now = datetime(2026, 9, 20, 10, 30, 0)
        assert node._funding_period_key() == "2026-09-20T08:00:00"


class TestOneBookingPerPeriod:
    def test_two_cycles_in_one_period_book_one_payment(self, monkeypatch):
        node = live_node(monkeypatch)
        open_position(node)

        node.run({**INPUTS, "now": datetime(2026, 9, 20, 9, 0, 0)})
        assert node.state.n_payments == 1
        booked = node.state.total_funding_received

        # a manual re-run, or the startup cycle after a restart
        node.run({**INPUTS, "now": datetime(2026, 9, 20, 10, 30, 0)})
        assert node.state.n_payments == 1, "the same settlement was booked twice"
        assert node.state.total_funding_received == pytest.approx(booked)

        # the next settlement is a new period and must be booked
        node.run({**INPUTS, "now": datetime(2026, 9, 20, 17, 0, 0)})
        assert node.state.n_payments == 2
        assert node.state.total_funding_received == pytest.approx(booked * 2)

    def test_the_skipped_cycle_still_reports_holding(self, monkeypatch):
        node = live_node(monkeypatch)
        open_position(node)
        node.run({**INPUTS, "now": datetime(2026, 9, 20, 9, 0, 0)})
        r = node.run({**INPUTS, "now": datetime(2026, 9, 20, 9, 30, 0)})
        assert r["signal"] == "flat"
        assert r["position_open"] is True
        assert "already booked" in r["reason"]

    def test_the_marker_survives_a_restart(self, monkeypatch):
        node = live_node(monkeypatch)
        open_position(node)
        node.run({**INPUTS, "now": datetime(2026, 9, 20, 9, 0, 0)})
        assert node.state.last_funding_ts == "2026-09-20T08:00:00"

        # the cycle rebuilds the node from the persisted context_json
        restarted = FundingCarryState(symbol="BTC/USDT")
        assert restarted.load_position_dict(node.state.to_dict()) is True
        assert restarted.last_funding_ts == "2026-09-20T08:00:00"

    def test_a_backtest_books_every_bar(self, monkeypatch):
        """The guard must not touch the simulated path: one row, one payment."""
        node = FundingCarryNode(node_id="t_sim", symbol="BTC/USDT", capital=1000.0,
                                params={"_backtest": True})
        monkeypatch.setattr(node, "_seed_funding_history", lambda: None)
        open_position(node)
        for hour in (0, 8, 16, 24):
            node.run({**INPUTS, "now": datetime(2026, 9, 20 + hour // 24, hour % 24, 0, 0)})
        assert node.state.n_payments == 4


class TestFundingWindow:
    def test_window_covers_the_percentile_filter(self):
        """The filter activates at 30 periods; the seed used to provide 21."""
        assert FUNDING_WINDOW >= 30

    def test_the_whole_window_is_persisted(self):
        st = FundingCarryState(symbol="BTC/USDT")
        st.funding_history = [0.0001] * FUNDING_WINDOW
        assert len(st.to_dict()["funding_history"]) == FUNDING_WINDOW

    def test_history_longer_than_the_window_is_trimmed_on_restore(self):
        st = FundingCarryState(symbol="BTC/USDT")
        assert st.load_position_dict({
            "leg_notional": 1000.0,
            "funding_history": [0.0001] * (FUNDING_WINDOW * 2),
        }) is True
        assert len(st.funding_history) == FUNDING_WINDOW
