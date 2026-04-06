"""
utils/session.py — Session-aware scheduler for non-24/7 markets.

Usage:
    from utils.session import MarketSession
    s = MarketSession("XAU/USD")
    if s.is_open():
        interval = s.interval_seconds()
"""
from __future__ import annotations

import datetime
from typing import NamedTuple


class SessionWindow(NamedTuple):
    open_utc: int   # hour (0-23)
    close_utc: int  # hour (0-23), exclusive
    interval_s: int # loop interval in seconds during this window


# Market profiles: list of session windows (sorted by open_utc)
_PROFILES: dict[str, list[SessionWindow]] = {
    # Crypto: always open, fixed interval
    "crypto": [
        SessionWindow(0, 24, 900),   # 24/7, 15 min
    ],
    # Gold / XAU: Mon-Fri, two active sessions
    "xau": [
        SessionWindow(0,  7,  1800),  # Asian/quiet: 30 min
        SessionWindow(7,  12, 900),   # London: 15 min
        SessionWindow(12, 17, 900),   # London/NY overlap: 15 min
        SessionWindow(17, 22, 900),   # NY: 15 min
        SessionWindow(22, 24, 1800),  # Post-NY quiet: 30 min
    ],
    # Forex majors: Mon-Fri, session-aware with quiet Asia
    "forex": [
        SessionWindow(0,  7,  3600),  # Asia quiet: no trading, 60 min check
        SessionWindow(7,  12, 900),   # London: 15 min
        SessionWindow(12, 17, 300),   # London/NY overlap: 5 min (high liquidity)
        SessionWindow(17, 22, 900),   # NY: 15 min
        SessionWindow(22, 24, 3600),  # Post-NY quiet: no trading, 60 min check
    ],
}

# Sessions where trading is blocked (only monitoring)
_NO_TRADE_SESSIONS: dict[str, set[int]] = {
    "forex": {0, 22},   # Asia and post-NY quiet windows (open_utc values)
}

# Map asset slugs to market profiles
_ASSET_PROFILE: dict[str, str] = {
    "BTC/USDT": "crypto",
    "ETH/USDT": "crypto",
    "BNB/USDT": "crypto",
    "SOL/USDT": "crypto",
    "XAU/USD":  "xau",
    "XAG/USD":  "xau",
    "EUR/USD":  "forex",
    "GBP/USD":  "forex",
    "USD/JPY":  "forex",
    "EUR/JPY":  "forex",
}


def _get_profile(asset: str) -> str:
    """Returns the market profile for an asset. Defaults to 'crypto'."""
    return _ASSET_PROFILE.get(asset, "crypto")


class MarketSession:
    """
    Session-aware scheduler for a given asset.

    Attributes:
        asset (str): e.g. "BTC/USDT", "XAU/USD", "EUR/USD"
        profile (str): "crypto" | "xau" | "forex"
    """

    def __init__(self, asset: str):
        self.asset = asset
        self.profile = _get_profile(asset)
        self._windows = _PROFILES[self.profile]
        self._no_trade_opens = _NO_TRADE_SESSIONS.get(self.profile, set())

    def _now_utc(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    def _current_window(self, now: datetime.datetime | None = None) -> SessionWindow | None:
        """Returns the SessionWindow covering the current UTC hour, or None if market closed."""
        now = now or self._now_utc()

        # Crypto: always open
        if self.profile == "crypto":
            return self._windows[0]

        # Non-crypto: closed on weekends (Sat=5, Sun=6)
        if now.weekday() >= 5:
            return None

        h = now.hour
        for w in self._windows:
            if w.open_utc <= h < w.close_utc:
                return w
        return None

    def is_open(self, now: datetime.datetime | None = None) -> bool:
        """
        Returns True if the market accepts orders right now.
        For forex, Asia-quiet windows are NOT tradeable even if the market is technically open.
        """
        w = self._current_window(now)
        if w is None:
            return False
        if w.open_utc in self._no_trade_opens:
            return False
        return True

    def is_monitoring(self, now: datetime.datetime | None = None) -> bool:
        """Returns True if we should still run monitoring (even if trading is blocked)."""
        w = self._current_window(now)
        return w is not None

    def interval_seconds(self, now: datetime.datetime | None = None) -> int:
        """
        Returns the recommended loop interval for the current session.
        Falls back to the last window's interval if after hours.
        """
        w = self._current_window(now)
        if w is not None:
            return w.interval_s
        # Outside session: use the longest interval (conservative)
        return max(w.interval_s for w in self._windows)

    def next_open(self, now: datetime.datetime | None = None) -> datetime.datetime:
        """
        Returns the next datetime (UTC) when is_open() will be True.
        For crypto, returns now (always open).
        """
        now = now or self._now_utc()
        if self.profile == "crypto":
            return now

        # Find next non-weekend, non-no-trade window
        candidate = now
        for _ in range(10 * 24):  # max 10 days look-ahead
            candidate += datetime.timedelta(hours=1)
            candidate = candidate.replace(minute=0, second=0, microsecond=0)
            if candidate.weekday() >= 5:
                continue
            h = candidate.hour
            for w in self._windows:
                if w.open_utc <= h < w.close_utc and w.open_utc not in self._no_trade_opens:
                    return candidate
        return now + datetime.timedelta(days=1)  # fallback

    def wait_seconds_until_open(self, now: datetime.datetime | None = None) -> int:
        """Returns seconds to wait until next open. 0 if already open."""
        now = now or self._now_utc()
        if self.is_open(now):
            return 0
        nxt = self.next_open(now)
        return max(0, int((nxt - now).total_seconds()))

    def status_label(self, now: datetime.datetime | None = None) -> str:
        """Human-readable session status label for the dashboard."""
        now = now or self._now_utc()
        w = self._current_window(now)
        if self.profile == "crypto":
            return "24/7"
        if w is None:
            nxt = self.next_open(now)
            mins = int((nxt - now).total_seconds() / 60)
            return f"⛔ fermé — ouverture dans {mins}min"
        h = now.hour
        if 7 <= h < 12:
            return "🟡 London"
        if 12 <= h < 17:
            return "🟢 London/NY"
        if 17 <= h < 22:
            return "🟠 NY"
        return "⚫ hors session"
