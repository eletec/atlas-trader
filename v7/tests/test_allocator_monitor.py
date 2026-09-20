"""
v7/tests/test_allocator_monitor.py — the two places that disagreed with the config.

1. GlobalAllocator capped the book with module constants (40% of capital, 4
   simultaneous positions) while carry_assets.yaml and the dashboard said 60% and
   6. The engine never saw the configured limits, and because the constants were
   bound at import a reload changed nothing either.

2. PositionMonitor estimated the funding at a hardcoded 0.01%/8h and then left it
   out of the total with the comment "negligible on a daily horizon", so it
   reported a basis-only P&L for a strategy whose whole point is the funding leg.
   It also read `entry_perp_price` after the cycle had started writing `entry_perp`,
   which degraded every new position to "economics UNKNOWN".
"""

from __future__ import annotations

import json
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

import v7.core.asset_config as asset_config
from v7.core import global_allocator as ga
from v7.position_monitor import PositionMonitor


class TestAllocatorLimits:
    def test_limits_come_from_config(self, monkeypatch):
        """The YAML is the source of truth, not the module constants."""
        monkeypatch.setattr(
            asset_config,
            "get_global_params",
            lambda: {
                "total_capital": 14_000,
                "max_total_exposure_pct": 0.6,
                "max_simultaneous_positions": 6,
            },
        )
        assert ga.get_limits() == (0.6, 6, 14_000.0)

    def test_limits_fall_back_when_config_unreadable(self, monkeypatch):
        def _boom():
            raise RuntimeError("no config")

        monkeypatch.setattr(asset_config, "get_global_params", _boom)
        assert ga.get_limits() == (0.40, 4, 14_000.0)

    def test_configured_position_cap_is_enforced(self, monkeypatch):
        """With 2 configured, the third position must be refused."""
        monkeypatch.setattr(
            asset_config,
            "get_global_params",
            lambda: {
                "total_capital": 14_000,
                "max_total_exposure_pct": 0.6,
                "max_simultaneous_positions": 2,
            },
        )
        monkeypatch.setattr(ga, "get_open_count", lambda: 2)
        monkeypatch.setattr(ga, "get_total_exposure", lambda: 0.0)

        ok, why = ga.can_open_position("BTC/USDT", 100.0, 1.0)
        assert not ok
        assert "max 2 positions" in why

    def test_configured_capital_cap_is_enforced(self, monkeypatch):
        """60% of 14k = 8.4k: an 8.5k book must be refused, a 8.0k one accepted."""
        monkeypatch.setattr(
            asset_config,
            "get_global_params",
            lambda: {
                "total_capital": 14_000,
                "max_total_exposure_pct": 0.6,
                "max_simultaneous_positions": 6,
            },
        )
        monkeypatch.setattr(ga, "get_open_count", lambda: 0)
        monkeypatch.setattr(ga, "get_total_exposure", lambda: 8_500.0)

        ok, why = ga.can_open_position("BTC/USDT", 100.0, 1.0)
        assert not ok
        assert "total exposure" in why

        monkeypatch.setattr(ga, "get_total_exposure", lambda: 8_000.0)
        ok, _ = ga.can_open_position("BTC/USDT", 100.0, 1.0)
        assert ok


def _monitor_with_perp(perp: float) -> PositionMonitor:
    """A PositionMonitor without a DB or a websocket, just the price cache."""
    m = object.__new__(PositionMonitor)
    m._get_cached_perp = lambda symbol: perp  # type: ignore[attr-defined]
    return m


def _position(**ctx) -> dict:
    return {
        "symbol": "BTC/USDT",
        "entry_price": 100.0,
        "size_usd": 1000.0,
        "current_price": 100.0,
        "context_json": json.dumps(ctx),
    }


class TestMonitorCarryEconomics:
    def test_reads_the_persisted_funding(self):
        m = _monitor_with_perp(100.0)
        r = m._compute_carry_economics(
            _position(entry_perp=100.0, funding_pnl=1.25, fees_paid=0.24), -0.05
        )
        assert r["funding_source"] == "state"
        assert r["funding_est"] == pytest.approx(1.25)
        # basis is flat here, so the net is funding minus the fees paid so far
        assert r["net_carry_pnl"] == pytest.approx(1.01)

    def test_accepts_the_legacy_context_keys(self):
        m = _monitor_with_perp(100.0)
        r = m._compute_carry_economics(
            _position(entry_perp_price=100.0, total_funding_received=2.0), -0.05
        )
        assert r["funding_source"] == "state"
        assert r["funding_est"] == pytest.approx(2.0)
        assert r["net_carry_pnl"] == pytest.approx(2.0)

    def test_current_key_is_not_treated_as_missing(self):
        """Regression: the monitor used to read only entry_perp_price."""
        m = _monitor_with_perp(100.0)
        r = m._compute_carry_economics(_position(entry_perp=100.0), -0.05)
        assert not r.get("data_degraded")

    def test_falls_back_to_the_estimate_without_state(self):
        m = _monitor_with_perp(100.0)
        r = m._compute_carry_economics(_position(entry_perp=100.0), -0.05)
        assert r["funding_source"] == "estimate"
        assert r["funding_est"] == pytest.approx(1000.0 * 0.0001 * 3)

    def test_still_degrades_without_a_perp_price(self):
        m = _monitor_with_perp(0.0)
        r = m._compute_carry_economics(_position(entry_perp=100.0, funding_pnl=1.0), -0.05)
        assert r["data_degraded"] is True
        assert r["net_carry_pnl"] == 0.0

    def test_basis_gain_adds_to_the_funding(self):
        """Entry basis 1% (spot 100, perp 99) closing to 0 is a gain on the book."""
        m = _monitor_with_perp(100.0)
        r = m._compute_carry_economics(
            _position(entry_perp=99.0, funding_pnl=0.5), -0.05
        )
        # basis_entry = (100-99)/100 = 0.01, basis_now = 0 -> +1% of 1000
        assert r["basis_pnl"] == pytest.approx(10.0)
        assert r["net_carry_pnl"] == pytest.approx(10.5)

    def test_payback_uses_the_real_daily_rate(self):
        m = _monitor_with_perp(100.0)
        # entry basis -1% (spot 100, perp 101) closing to 0 is a loss on the book
        r = m._compute_carry_economics(
            _position(entry_perp=101.0, funding_pnl=-0.4), -0.05
        )
        assert r["basis_pnl"] == pytest.approx(-10.0)
        assert r["net_carry_pnl"] == pytest.approx(-10.4)
        assert r["payback_days"] > 0

    def test_negative_funding_can_never_repay(self):
        m = _monitor_with_perp(100.0)
        pd = _position(entry_perp=101.0, funding_pnl=-2.0)
        pd["opened_at"] = (datetime.now() - timedelta(days=2)).isoformat()
        r = m._compute_carry_economics(pd, -0.05)
        # -2.0 over 2 days = -1/day -> the shortfall can never be repaid
        assert r["funding_source"] == "state"
        assert r["payback_days"] == 999
