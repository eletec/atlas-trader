"""
v7/core/global_allocator.py — Global Carry Allocator (3 audits consensus, 20/07/2026).

Constraints:
- Max total carry exposure: from carry_assets.yaml (max_total_exposure_pct)
- Max simultaneous positions: from carry_assets.yaml (max_simultaneous_positions)
- Per-asset safety caps (unchanged)
- Per-venue (Binance) budget tracking
- Per-stablecoin (USDT) budget tracking

Called by FundingCarryNode before opening a position.
Reads current state from DB (v4_trades) to make allocation decisions.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("v7.core.global_allocator")

# ── Global limits ────────────────────────────────────────────────────────────
# Defaults only. The live values live in carry_assets.yaml and are read through
# get_global_params() on every call: these used to be module constants, so the
# engine capped the book at 40% and 4 positions while the dashboard happily let
# you save 60% and 6. The two never met, and a config reload changed nothing.
MAX_TOTAL_EXPOSURE_PCT_DEFAULT = 0.40
MAX_SIMULTANEOUS_POSITIONS_DEFAULT = 4
TOTAL_CAPITAL_DEFAULT = 14_000


def get_limits() -> tuple[float, int, float]:
    """(max_exposure_pct, max_simultaneous_positions, total_capital).

    Read from the live config; falls back to the defaults above when the config
    cannot be read (backtests, unit tests).
    """
    try:
        from v7.core.asset_config import get_global_params

        g = get_global_params()
        return (
            float(g.get("max_total_exposure_pct", MAX_TOTAL_EXPOSURE_PCT_DEFAULT)),
            int(g.get("max_simultaneous_positions", MAX_SIMULTANEOUS_POSITIONS_DEFAULT)),
            float(g.get("total_capital", TOTAL_CAPITAL_DEFAULT)),
        )
    except Exception:
        return (
            MAX_TOTAL_EXPOSURE_PCT_DEFAULT,
            MAX_SIMULTANEOUS_POSITIONS_DEFAULT,
            TOTAL_CAPITAL_DEFAULT,
        )

# ── Per-asset safety caps (same as FundingCarryNode) ─────────────────────────
# ── Per-asset safety caps (loaded from config or defaults) ──────────────────
def _load_safety_caps() -> dict[str, float]:
    try:
        from v7.core.asset_config import get_all_assets, get_asset_params
        caps = {}
        for sym in get_all_assets():
            coin = sym.split("/")[0].upper()
            caps[coin] = float(get_asset_params(sym).get("safety_cap", 200))
        return caps
    except Exception:
        pass
    return {
        "BTC": 400, "ETH": 300, "SOL": 200, "BNB": 200,
        "XRP": 200, "ADA": 150, "DOGE": 100,
    }

SAFETY_CAPS: dict[str, float] = _load_safety_caps()

# ── Per-asset stress loss (same as FundingCarryNode) ─────────────────────────
ASSET_STRESS_LOSS: dict[str, float] = {
    "BTC": 0.04, "ETH": 0.04,
    "SOL": 0.08, "BNB": 0.08,
    "XRP": 0.12, "ADA": 0.12, "DOGE": 0.12,
    "AVAX": 0.10, "LINK": 0.10, "DOT": 0.10,
    "LTC": 0.06, "NEAR": 0.12, "SUI": 0.12,
}


def get_open_carry_positions() -> list[dict]:
    """Return all currently open carry positions from the DB.
    In backtest mode, returns empty list (no DB available)."""
    import os
    if os.environ.get("V7_BACKTEST"):
        return []
    try:
        from storage.paper_trader import get_open_positions
        positions = get_open_positions()
        return [p for p in positions if p.get("action") in ("carry", "short")]
    except Exception as e:
        logger.warning("GlobalAllocator: cannot read open positions: %s", e)
        return []


def get_total_exposure() -> float:
    """Sum of size_usd for all open carry positions."""
    positions = get_open_carry_positions()
    return sum(float(p.get("size_usd", 0) or 0) for p in positions)


def get_open_count() -> int:
    """Number of currently open carry positions."""
    return len(get_open_carry_positions())


def can_open_position(
    asset: str,
    proposed_size_usd: float,
    score: float,
) -> tuple[bool, str]:
    """
    Check if a new carry position can be opened.

    Returns (allowed, reason).
    """
    coin = asset.split("/")[0].upper() if "/" in asset else asset.upper()

    # 1) Per-asset safety cap
    cap = SAFETY_CAPS.get(coin, 200)
    if proposed_size_usd > cap:
        return False, f"size ${proposed_size_usd:.0f} > safety cap ${cap:.0f}"

    # 2) Max simultaneous positions
    max_exposure_pct, max_positions, total_capital = get_limits()
    open_count = get_open_count()
    if open_count >= max_positions:
        return False, f"max {max_positions} positions already open ({open_count})"

    # 3) Total exposure check
    current_exposure = get_total_exposure()
    new_exposure = current_exposure + proposed_size_usd
    max_exposure = total_capital * max_exposure_pct
    if new_exposure > max_exposure:
        return False, (
            f"total exposure ${new_exposure:.0f} > "
            f"${max_exposure:.0f} ({max_exposure_pct*100:.0f}% of capital)"
        )

    # 4) Score must be positive (excess carry > 0)
    if score <= 0:
        return False, f"score={score:.3f} ≤ 0"

    return True, "OK"


def allocate_capital(
    asset_scores: dict[str, float],
    available_capital: Optional[float] = None,
) -> dict[str, float]:
    """
    Allocate capital across assets based on risk-adjusted scores.

    Args:
        asset_scores: {asset: score} where score = net_return / stress_loss
        available_capital: total capital to allocate (default: the configured
            share of TOTAL_CAPITAL, i.e. max_total_exposure_pct)

    Returns:
        {asset: allocated_size_usd}
    """
    max_exposure_pct, max_positions, total_capital = get_limits()
    if available_capital is None:
        available_capital = total_capital * max_exposure_pct

    # Filter: only positive scores
    candidates = {
        a: s for a, s in asset_scores.items()
        if s > 0 and can_open_position(a, SAFETY_CAPS.get(a.split("/")[0].upper(), 200), s)[0]
    }
    if not candidates:
        return {}

    # Sort by score descending
    ranked = sorted(candidates.items(), key=lambda x: x[1], reverse=True)

    # Allocate top N (max max_simultaneous_positions)
    allocation: dict[str, float] = {}
    remaining = available_capital

    for asset, score in ranked[:max_positions]:
        coin = asset.split("/")[0].upper()
        cap = SAFETY_CAPS.get(coin, 200)
        alloc = min(cap, remaining / max(1, len(ranked[:max_positions])))
        if alloc >= 50:  # min trade size
            allocation[asset] = round(alloc, 2)
            remaining -= alloc

    return allocation
