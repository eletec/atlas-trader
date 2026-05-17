"""
utils/cycle_lock.py — Per-asset cycle lock.

Prevents concurrent cycles for the SAME asset (daemon + dashboard).
Each asset gets its own lockfile: /tmp/atlas_cycle_{slug}.lock
Global lock (/tmp/atlas_cycle.lock) kept for backward compat (dashboard).
Uses a simple lockfile with stale-lock detection.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("zeitgeist.cycle_lock")

_IN_CONTAINER = os.path.exists("/app")
_LOCK_DIR = Path("/tmp") if _IN_CONTAINER else Path(__file__).resolve().parent.parent / "storage"
_LOCK_FILE = _LOCK_DIR / "atlas_cycle.lock"  # global fallback (backward compat)
_MAX_CYCLE_DURATION = 900  # seconds — stale lock threshold (premier refit HMM 8 actifs ~20min)


def _lock_path(asset: str | None = None) -> Path:
    """Return the lock file path for a given asset (or global if None)."""
    if asset:
        slug = asset.replace("/", "_").replace(" ", "_")
        return _LOCK_DIR / f"atlas_cycle_{slug}.lock"
    return _LOCK_FILE


def try_acquire(owner: str = "unknown", asset: str | None = None) -> bool:
    """
    Non-blocking attempt to acquire the cycle lock for `asset`.
    Returns True if lock acquired, False if another cycle is running.
    Stale locks (older than _MAX_CYCLE_DURATION) are automatically removed.
    """
    lock_file = _lock_path(asset)
    if lock_file.exists():
        try:
            content = lock_file.read_text().strip().split("\n")
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
            lock_file.unlink()
        except Exception:
            pass

    try:
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text(f"{owner}\n{time.time()}\n{os.getpid()}\n")
        logger.debug(f"Cycle lock acquired by '{owner}'" + (f" [{asset}]" if asset else ""))
        return True
    except Exception as exc:
        logger.error(f"Failed to acquire cycle lock: {exc}")
        return False


def release(asset: str | None = None):
    """Release the cycle lock for `asset`."""
    lock_file = _lock_path(asset)
    try:
        lock_file.unlink(missing_ok=True)
        logger.debug("Cycle lock released" + (f" [{asset}]" if asset else ""))
    except Exception as exc:
        logger.warning(f"Failed to release cycle lock: {exc}")


def is_locked(asset: str | None = None) -> bool:
    """Check if a cycle is currently running for `asset` (non-stale lock exists).
    Si asset=None, retourne True si N'IMPORTE quel actif a un cycle actif
    (V2 utilise des locks par actif : atlas_cycle_BTC_USDT.lock, etc.)
    """
    if asset is None:
        # Chercher tout lock actif parmi les actifs V2
        import glob as _glob
        for lf in _glob.glob(str(_LOCK_DIR / "atlas_cycle_*.lock")):
            try:
                content = Path(lf).read_text().strip().split("\n")
                ts = float(content[1])
                if (time.time() - ts) < _MAX_CYCLE_DURATION:
                    return True
            except Exception:
                pass
        # Fallback : lock global legacy
        lock_file = _lock_path(None)
        if not lock_file.exists():
            return False
        try:
            content = lock_file.read_text().strip().split("\n")
            ts = float(content[1])
            return (time.time() - ts) < _MAX_CYCLE_DURATION
        except Exception:
            return False

    lock_file = _lock_path(asset)
    if not lock_file.exists():
        return False
    try:
        content = lock_file.read_text().strip().split("\n")
        ts = float(content[1])
        return (time.time() - ts) < _MAX_CYCLE_DURATION
    except Exception:
        return False


def lock_info(asset: str | None = None) -> dict | None:
    """Return info about the current lock holder for `asset`, or None if unlocked."""
    lock_file = _lock_path(asset)
    if not lock_file.exists():
        return None
    try:
        content = lock_file.read_text().strip().split("\n")
        owner = content[0]
        ts = float(content[1])
        age = time.time() - ts
        if age >= _MAX_CYCLE_DURATION:
            return None
        return {"owner": owner, "age_s": int(age)}
    except Exception:
        return None
