"""
v7/core/risk_state.py — process-wide risk flags.

`PositionMonitor` maintains a circuit breaker that is supposed to block new
entries while the market data it depends on is unusable. Nothing ever read it:
the flag lived on the monitor instance, and the entry path is in
`run_carry_cycle`, which never sees that instance. The README claimed
"Tier 0: blocks new entries" and no code did.

Both now run in the same process (the API starts the monitor in a thread and
serves the cycle from the same interpreter), so a module-level flag is enough.
If the cycle is ever moved to its own process this has to become shared state
on disk or in the database — the flag would silently stop working.
"""

from __future__ import annotations

_breaker_active = False
_reason = ""


def set_circuit_breaker(active: bool, reason: str = "") -> None:
    """Called by the monitor when the price feed becomes unusable (and again when
    it recovers)."""
    global _breaker_active, _reason
    _breaker_active = bool(active)
    _reason = reason if active else ""


def circuit_breaker_active() -> bool:
    """Called by the entry path before opening a position."""
    return _breaker_active


def circuit_breaker_reason() -> str:
    return _reason
