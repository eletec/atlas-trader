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

import json
import sys
from datetime import datetime, timezone
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

S08 = "2026-09-20T08:00:00+00:00"
S16 = "2026-09-20T16:00:00+00:00"


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


class TestSettlementTime:
    def test_none_in_a_backtest(self):
        """One row per period by construction — nothing to deduplicate."""
        node = FundingCarryNode(node_id="t_bt", symbol="BTC/USDT", capital=1000.0,
                                params={"_backtest": True})
        assert node._settlement_ms(S08) is None

    def test_there_is_no_clock_fallback(self, monkeypatch):
        """A missing settlement must never be invented from the wall clock.

        The previous version floored the clock onto an 8h boundary when the caller
        gave no timestamp, which turned a failed fetch into "this period is
        booked" — and the real settlement was then never counted.
        """
        node = live_node(monkeypatch)
        node._sim_now = datetime(2026, 9, 20, 10, 30, 0)
        assert node._settlement_ms(None) is None
        assert node._settlement_ms("") is None
        assert node._settlement_ms("not-a-timestamp") is None

    def test_real_timestamps_become_milliseconds(self, monkeypatch):
        node = live_node(monkeypatch)
        assert node._settlement_ms(S08) == ms(S08)

    def test_a_four_hour_contract_is_not_merged_with_its_neighbour(self, monkeypatch):
        """4h contracts settle six times a day; a floored clock would collide."""
        node = live_node(monkeypatch)
        assert node._settlement_ms("2026-09-20T12:00:00+00:00") > node._settlement_ms(S08)


class TestOneBookingPerSettlement:
    def test_two_cycles_on_one_settlement_book_one_payment(self, monkeypatch):
        node = live_node(monkeypatch)
        open_position(node)
        run = {**INPUTS, "funding_ts": S08}

        node.run({**run, "now": datetime(2026, 9, 20, 9, 0, 0)})
        assert node.state.n_payments == 1
        booked = node.state.total_funding_received
        assert node.state.last_funding_ts_ms == ms(S08)

        # a manual re-run, or the startup cycle after a restart
        node.run({**run, "now": datetime(2026, 9, 20, 10, 30, 0)})
        assert node.state.n_payments == 1, "the same settlement was booked twice"
        assert node.state.total_funding_received == pytest.approx(booked)

    def test_the_next_settlement_is_booked(self, monkeypatch):
        node = live_node(monkeypatch)
        open_position(node)
        node.run({**INPUTS, "funding_ts": S08, "now": datetime(2026, 9, 20, 9, 0, 0)})
        node.run({**INPUTS, "funding_ts": S16, "now": datetime(2026, 9, 20, 17, 0, 0)})
        assert node.state.n_payments == 2

    def test_a_settlement_before_the_entry_is_not_credited(self, monkeypatch):
        """The reason this changed at all. `fetch_funding_rates` returns
        `lastFundingRate` paired with `nextFundingTime`, so the 08:00 payment could
        be credited to a position opened at 08:05 — the book was not standing when
        that payment was made."""
        node = live_node(monkeypatch)
        open_position(node)
        node.state.entry_time = "2026-09-20T08:05:00+00:00"
        node.run({**INPUTS, "funding_ts": S08, "now": datetime(2026, 9, 20, 9, 0, 0)})
        assert node.state.n_payments == 0
        assert node.state.total_funding_received == 0.0

    def test_a_settlement_after_the_entry_is_credited(self, monkeypatch):
        node = live_node(monkeypatch)
        open_position(node)
        node.state.entry_time = "2026-09-20T08:05:00+00:00"
        node.run({**INPUTS, "funding_ts": S16, "now": datetime(2026, 9, 20, 17, 0, 0)})
        assert node.state.n_payments == 1

    def test_the_skipped_cycle_still_reports_holding(self, monkeypatch):
        node = live_node(monkeypatch)
        open_position(node)
        node.run({**INPUTS, "funding_ts": S08, "now": datetime(2026, 9, 20, 9, 0, 0)})
        r = node.run({**INPUTS, "funding_ts": S08,
                      "now": datetime(2026, 9, 20, 9, 30, 0)})
        assert r["signal"] == "flat"
        assert r["position_open"] is True
        assert "already booked" in r["reason"]

    def test_the_rolling_window_does_not_repeat_a_settlement(self, monkeypatch):
        """The history is appended before the booking decision, so a replayed
        period used to duplicate inside the 7-day MA and the percentile filter."""
        node = live_node(monkeypatch)
        open_position(node)
        run = {**INPUTS, "funding_ts": S08}
        node.run({**run, "now": datetime(2026, 9, 20, 9, 0, 0)})
        length = len(node.state.funding_history)
        node.run({**run, "now": datetime(2026, 9, 20, 10, 0, 0)})
        assert len(node.state.funding_history) == length
        assert len(node._funding_rate_history) == length

    def test_the_marker_survives_a_restart(self, monkeypatch):
        node = live_node(monkeypatch)
        open_position(node)
        node.run({**INPUTS, "funding_ts": S08, "now": datetime(2026, 9, 20, 9, 0, 0)})

        restarted = FundingCarryState(symbol="BTC/USDT")
        assert restarted.load_position_dict(node.state.to_dict()) is True
        assert restarted.last_funding_ts_ms == ms(S08)

    def test_a_backtest_books_every_bar(self, monkeypatch):
        """The guard must not touch the simulated path: one row, one payment."""
        node = FundingCarryNode(node_id="t_sim", symbol="BTC/USDT", capital=1000.0,
                                params={"_backtest": True})
        monkeypatch.setattr(node, "_seed_funding_history", lambda: None)
        open_position(node)
        for hour in (0, 8, 16, 24):
            node.run({**INPUTS, "now": datetime(2026, 9, 20 + hour // 24, hour % 24, 0, 0)})
        assert node.state.n_payments == 4


class TestOpenPersistence:
    """OPEN -> context_json -> a fresh node must restore everything.

    The suite already covered `CarryState.to_dict() -> load_position_dict()`, which
    is only half the trip. The cycle persisted `context=decision`, and
    `carry_state` lives at the TOP LEVEL of the node's output, so the position
    state was written for the first time on the next HOLD. A restart in between
    rebuilt the position from the trade row alone and lost `fees_paid` and
    `last_funding_ts_ms`; the degraded state was then written back on that HOLD,
    so the entry fees were gone from the live P&L for good.
    """

    def test_the_node_emits_carry_state_outside_decision(self, monkeypatch):
        """The shape that caused it: `decision` is a sub-dict and lacks it."""
        node = live_node(monkeypatch)
        open_position(node)
        r = node.run({**INPUTS, "now": datetime(2026, 9, 20, 9, 0, 0)})
        assert "carry_state" in r
        assert "carry_state" not in r["decision"]

    def test_the_open_context_round_trips_into_a_fresh_node(self, monkeypatch):
        from v7.run_carry_cycle import build_open_context

        node = live_node(monkeypatch)
        open_position(node)
        node.state.entry_perp = 100.5
        node.state.fees_paid = 2.40
        node.state.total_funding_received = 1.25
        node.state.n_payments = 3
        node.state.funding_history = [0.0001] * 60
        node.state.last_funding_ts_ms = ms(S08)

        result = node.run({**INPUTS, "funding_ts": S16,
                           "now": datetime(2026, 9, 20, 17, 0, 0)})
        ctx = build_open_context(result)

        fresh = FundingCarryState(symbol="BTC/USDT")
        assert fresh.load_position_dict(ctx["carry_state"]) is True
        assert fresh.entry_capital == pytest.approx(node.state.entry_capital)
        assert fresh.entry_spot == pytest.approx(node.state.entry_spot)
        assert fresh.entry_perp == pytest.approx(node.state.entry_perp)
        assert fresh.entry_time == node.state.entry_time
        assert fresh.fees_paid == pytest.approx(node.state.fees_paid)
        assert fresh.last_funding_ts_ms == node.state.last_funding_ts_ms
        assert len(fresh.funding_history) == len(node.state.funding_history)

    def test_a_legacy_row_restores_the_entry_fees(self, monkeypatch):
        """A row persisted before the fix carries no `carry_state`, so the fallback
        builds what it can. The entry legs are charged on open from the leg notional
        alone, so they are reconstructible - dropping them made the live P&L look
        24bps better than it was."""
        import storage.paper_trader as pt

        rows = [{
            "symbol": "BTC/USDT", "action": "carry", "size_usd": 1000.0,
            "entry_price": 100.0, "timestamp": "2026-09-20T00:00:00",
            "context_json": json.dumps({"entry_perp_price": 100.5}),
        }]
        monkeypatch.setattr(pt, "get_open_positions", lambda symbol=None: rows)

        node = live_node(monkeypatch)
        node._restore_state()
        assert node.state.position_open is True
        assert node.state.entry_perp == pytest.approx(100.5)
        assert node.state.fees_paid == pytest.approx(1000.0 * 0.0012 * 2)

    def test_the_cycle_no_longer_persists_the_bare_decision(self):
        import inspect
        from v7 import run_carry_cycle
        src = inspect.getsource(run_carry_cycle)
        assert "context=decision," not in src
        assert "context=build_open_context(result)" in src


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
