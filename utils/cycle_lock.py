"""
utils/cycle_lock.py — Cross-process cycle lock.

Prevents the daemon and Streamlit dashboard from running
trading cycles concurrently, which causes OOM + SQLite contention.
Uses a simple lockfile with stale-lock detection.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("zeitgeist.cycle_lock")

# Use /tmp inside container — survives across both supervisord processes
# but NOT across container restarts (no stale locks after restart)
_LOCK_FILE = Path("/tmp/atlas_cycle.lock") if os.path.exists("/app") else Path(__file__).resolve().parent.parent / "storage" / ".cycle.lock"
_MAX_CYCLE_DURATION = 600  # seconds — stale lock threshold


def try_acquire(owner: str = "unknown") -> bool:
    """
    Non-blocking attempt to acquire the cycle lock.
    Returns True if lock acquired, False if another cycle is running.
    Stale locks (older than _MAX_CYCLE_DURATION) are automatically removed.
    """
    if _LOCK_FILE.exists():
        try:
            content = _LOCK_FILE.read_text().strip().split("\n")
            ts = float(content[1])
            age = time.time() - ts
            if age < _MAX_CYCLE_DURATION:
                prev_owner = content[0] if content else "?"
                logger.warning(
                    f"Cycle lock held by '{prev_owner}' (age={age:.0f}s) — skipping"
                )
                return False
            # Stale lock
            logger.warning(f"Stale cycle lock detected (age={age:.0f}s) — removing")
        except Exception:
            logger.warning("Corrupted cycle lock — removing")
        try:
            _LOCK_FILE.unlink()
        except Exception:
            pass

    try:
        _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LOCK_FILE.write_text(f"{owner}\n{time.time()}\n{os.getpid()}\n")
        logger.debug(f"Cycle lock acquired by '{owner}'")
        return True
    except Exception as exc:
        logger.error(f"Failed to acquire cycle lock: {exc}")
        return False


def release():
    """Release the cycle lock."""
    try:
        _LOCK_FILE.unlink(missing_ok=True)
        logger.debug("Cycle lock released")
    except Exception as exc:
        logger.warning(f"Failed to release cycle lock: {exc}")


def is_locked() -> bool:
    """Check if a cycle is currently running (non-stale lock exists)."""
    if not _LOCK_FILE.exists():
        return False
    try:
        content = _LOCK_FILE.read_text().strip().split("\n")
        ts = float(content[1])
        return (time.time() - ts) < _MAX_CYCLE_DURATION
    except Exception:
        return False


def lock_info() -> dict | None:
    """Return info about the current lock holder, or None if unlocked."""
    if not _LOCK_FILE.exists():
        return None
    try:
        content = _LOCK_FILE.read_text().strip().split("\n")
        owner = content[0]
        ts = float(content[1])
        age = time.time() - ts
        if age >= _MAX_CYCLE_DURATION:
            return None
        return {"owner": owner, "age_s": int(age)}
    except Exception:
        return None
