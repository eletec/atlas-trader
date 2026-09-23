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
from datetime import datetime, timedelta
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


class TestDeriskRule:
    """The DERISK exit is a marginal decision: hold, or close now?

    The exit legs are paid whenever the position closes - now or at max_hold_days -
    so they cancel out of that comparison. The rule used to compare against
    `hurdle + 48bps * 365 / days_held`, which billed a decision already made AND
    amortised over the days ELAPSED: the test was tightest when the position was
    youngest, so the zone always fired on its first bar. The effective holding period
    was max_hold_days / 2 and the fee burden was twice what the entry gate budgeted.
    """

    def _run_aged(self, days_held: float, funding_rate: float, max_hold_days: int = 14):
        node = FundingCarryNode(node_id="t_derisk", symbol="BTC/USDT", capital=1000.0,
                                max_hold_days=max_hold_days,
                                params={"_backtest": True})
        st = node.state
        st.position_open = True
        st.entry_capital = 1000.0
        st.entry_spot = 100.0
        st.entry_perp = 100.0
        st.closed = False
        now = datetime(2026, 9, 20, 12, 0, 0)
        st.entry_time = (now - timedelta(days=days_held)).isoformat()
        return node.run({
            "symbol": "BTC/USDT", "spot_price": 100.0, "perp_price": 100.0,
            "funding_rate": funding_rate, "now": now,
        })

    def test_a_carry_that_still_covers_the_hurdle_is_held(self):
        """0.01%/8h is Binance's neutral rate, 10.95%/yr - well above the 5% hurdle.

        The old rule closed it: at 8 days held it demanded
        5% + 0.48% * 365/8 = 26.9%/yr.
        """
        r = self._run_aged(days_held=8, funding_rate=0.0001)
        assert r["signal"] != "close_carry"
        assert r["position_open"] is True
        assert "DERISK" not in r["reason"]

    def test_a_carry_that_no_longer_covers_the_hurdle_is_closed(self):
        r = self._run_aged(days_held=8, funding_rate=0.00001)   # 1.1%/yr
        assert r["signal"] == "close_carry"
        assert "DERISK" in r["reason"]

    def test_the_round_trip_is_no_longer_amortised_over_elapsed_days(self):
        """The reason string carried the symptom: `hurdle+exit=<n>%/yr` with n rising
        as the position got younger."""
        r = self._run_aged(days_held=8, funding_rate=0.00001)
        assert "hurdle+exit" not in r["reason"]
        assert "hurdle=5.0%/yr" in r["reason"]

    def test_the_horizon_the_entry_budgeted_is_now_reachable(self):
        """A carry that clears the hurdle is held into the CLOSE zone rather than
        being stopped at half the configured holding period."""
        # 13 of 14 days: inside DERISK, one day short of the forced close
        r = self._run_aged(days_held=13, funding_rate=0.0001)
        assert r["signal"] != "close_carry"
        # past max_hold_days the forced close still applies
        r2 = self._run_aged(days_held=15, funding_rate=0.0001)
        assert r2["signal"] == "close_carry"
        assert "ZONE CLOSE" in r2["reason"]


class TestEntryFeeAmortisation:
    """The entry gate must amortise the round trip over the hold the EXIT allows.

    The DERISK zone opens at ``max_hold_days / 2``, so half the horizon is the
    earliest an economic close can ever happen. The gate amortised over the full
    horizon instead, justified by a comment claiming this was "truthful only
    because the DERISK exit no longer closes at half the horizon". Measurement
    contradicts that comment: the three trades of the 365-day ACTIVE run closed
    after 15.3, 15.7 and 16.0 days against ``max_hold_days = 30``, so the gate was
    budgeting half the fee burden it actually pays.

    48 bps over 30 days is 5.84%/yr; over 15 days it is 11.68%/yr. The two rules
    therefore disagree on any carry whose annual funding lands between 10.84% and
    16.68%/yr -- which is exactly where the majors trade, and why this is worth a
    test rather than a comment. The two tests below are the two sides of that
    boundary; neither could pass under the other rule.
    """

    def _entry(self, annual_funding_pct: float, max_hold_days: int = 30):
        """Drive the entry path with a controlled funding rate.

        The funding window is pre-filled so the 7-day MA filter and the percentile
        filter cannot mask whatever the fee amortisation decides.
        """
        node = FundingCarryNode(
            node_id="t_entry", symbol="BTC/USDT", capital=2000.0,
            fraction=0.5, min_funding=0.00001, max_funding=0.01,
            max_hold_days=max_hold_days, params={"_backtest": True},
        )
        rate = annual_funding_pct / 100.0 / (365 * 3)   # 8h funding periods
        node._funding_rate_history = [rate] * 300
        node.state.funding_history = list(node._funding_rate_history)
        return node.run({
            "symbol": "BTC/USDT", "spot_price": 100.0, "perp_price": 100.0,
            "funding_rate": rate, "now": datetime(2026, 9, 20, 12, 0, 0),
        })

    def test_a_carry_below_the_doubled_cost_does_not_open(self):
        # 15%/yr clears the hurdle under the old 30-day amortisation
        # (15 - 5.84 = 9.16% > 5%) but not under the real 15-day one
        # (15 - 11.68 = 3.32% < 5%). Only one of the two can be correct.
        r = self._entry(15.0)
        assert r["signal"] != "open_carry", r["reason"]
        assert r["position_open"] is False

    def test_a_carry_above_the_doubled_cost_still_opens(self):
        # 25%/yr clears both: 25 - 11.68 = 13.32% > 5%.
        r = self._entry(25.0)
        assert r["signal"] == "open_carry", r["reason"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
