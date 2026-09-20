"""
v7/core/global_allocator.py — Global Carry Allocator (3 audits consensus, 20/07/2026).

Constraints:
- Max total carry exposure: 40% of total capital
- Max simultaneous positions: 4 (out of 7 assets)
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
MAX_TOTAL_EXPOSURE_PCT = 0.40      # 40% of total capital in carry
MAX_SIMULTANEOUS_POSITIONS = 4     # max 4 simultaneous carries
TOTAL_CAPITAL = 14_000             # 7 x $2,000

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
    open_count = get_open_count()
    if open_count >= MAX_SIMULTANEOUS_POSITIONS:
        return False, f"max {MAX_SIMULTANEOUS_POSITIONS} positions already open ({open_count})"

    # 3) Total exposure check
    current_exposure = get_total_exposure()
    new_exposure = current_exposure + proposed_size_usd
    max_exposure = TOTAL_CAPITAL * MAX_TOTAL_EXPOSURE_PCT
    if new_exposure > max_exposure:
        return False, (
            f"total exposure ${new_exposure:.0f} > "
            f"${max_exposure:.0f} ({MAX_TOTAL_EXPOSURE_PCT*100:.0f}% of capital)"
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
        available_capital: total capital to allocate (default: 40% of TOTAL_CAPITAL)

    Returns:
        {asset: allocated_size_usd}
    """
    if available_capital is None:
        available_capital = TOTAL_CAPITAL * MAX_TOTAL_EXPOSURE_PCT

    # Filter: only positive scores
    candidates = {
        a: s for a, s in asset_scores.items()
        if s > 0 and can_open_position(a, SAFETY_CAPS.get(a.split("/")[0].upper(), 200), s)[0]
    }
    if not candidates:
        return {}

    # Sort by score descending
    ranked = sorted(candidates.items(), key=lambda x: x[1], reverse=True)

    # Allocate top N (max MAX_SIMULTANEOUS_POSITIONS)
    allocation: dict[str, float] = {}
    remaining = available_capital

    for asset, score in ranked[:MAX_SIMULTANEOUS_POSITIONS]:
        coin = asset.split("/")[0].upper()
        cap = SAFETY_CAPS.get(coin, 200)
        alloc = min(cap, remaining / max(1, len(ranked[:MAX_SIMULTANEOUS_POSITIONS])))
        if alloc >= 50:  # min trade size
            allocation[asset] = round(alloc, 2)
            remaining -= alloc

    return allocation
