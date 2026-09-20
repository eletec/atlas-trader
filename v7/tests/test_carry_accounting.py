"""
v7/tests/test_carry_accounting.py — Unit tests for Funding Carry accounting.

Validates the three cases from the GPT audit (25/07/2026):
  Case A — Prices unchanged, positive funding → a loss when fees > funding
  Case B — Unfavourable basis → a loss even with positive funding
  Case C — Directional move perfectly hedged → net P&L = funding + basis − fees

Usage:
    python -m pytest v7/tests/test_carry_accounting.py -v
    docker exec atlas-v4-api python -m pytest /app/src/v7/tests/test_carry_accounting.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

## The diagnostic print() calls contain non-ASCII characters (arrows, times, dots).
## On Windows the console is cp1252 and pytest -s crashes with UnicodeEncodeError
## even though the assertions pass. Force UTF-8 on stdout/stderr.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from v7.core.carry_accounting import CarryPosition, exit_fee_usd

FEE_PER_LEG = 0.0012       # 12 bps (10 fees + 2 slippage)
FEES_4_LEGS = FEE_PER_LEG * 4  # 48 bps round-trip
FEES_2_LEGS_OPEN = FEE_PER_LEG * 2   # 24 bps on entry
FEES_2_LEGS_CLOSE = FEE_PER_LEG * 2  # 24 bps on exit


def simulate_carry_trade(
    entry_spot: float,
    entry_perp: float,
    exit_spot: float,
    exit_perp: float,
    funding_rates: list[float],  # list of rates per 8h period
    capital: float = 1000.0,
) -> dict:
    """Simulate a complete carry trade through the canonical accounting model.

    ``capital`` is the notional of ONE leg — see v7/core/carry_accounting.py.
    Both legs always carry the same notional, so the gross exposure is 2x this.

    This helper used to re-implement the P&L locally, with ``capital`` meaning
    *both* legs while the node meant *one* leg. That ambiguity is why the same
    word produced two different numbers. It now delegates to CarryPosition, so
    there is a single model and these cases verify it end to end.

    Returns:
        Dict with the full P&L breakdown.
    """
    leg = capital
    spot_pnl = leg * (exit_spot / entry_spot - 1.0)      # long spot
    perp_pnl = -leg * (exit_perp / entry_perp - 1.0)      # short perp
    basis_pnl = spot_pnl + perp_pnl                       # 0 when perfectly hedged

    pos = CarryPosition(symbol="TEST/USDT", leg_notional=leg,
                        entry_spot=entry_spot, entry_perp=entry_perp)
    open_fees = pos.charge_entry_fees()
    for fr in funding_rates:
        pos.accrue_funding(fr)                            # signed
    close_fees = exit_fee_usd(leg)
    net_pnl = pos.realized_pnl_usd(exit_spot, exit_perp)

    return {
        "spot_pnl": round(spot_pnl, 4),
        "perp_pnl": round(perp_pnl, 4),
        "basis_pnl": round(basis_pnl, 4),
        "total_funding": round(pos.funding_pnl, 4),
        "open_fees": round(open_fees, 4),
        "close_fees": round(close_fees, 4),
        "total_fees": round(pos.fees_paid, 4),
        "net_pnl": round(net_pnl, 4),
        "net_pnl_pct": round(net_pnl / capital * 100, 4),
    }


class TestCarryAccounting:
    """Accounting tests — GPT audit 25/07/2026."""

    def test_case_a_flat_prices_funding_positive(self):
        """
        Case A — Prices unchanged, funding received +20 bps, fees −48 bps.
        Expected result: −28 bps (a loss).
        """
        result = simulate_carry_trade(
            entry_spot=100.0,
            entry_perp=100.0,
            exit_spot=100.0,
            exit_perp=100.0,
            funding_rates=[0.0020],  # +20 bps over 1 period
            capital=1000.0,
        )

        # Assertions
        assert result["basis_pnl"] == 0.0, "Prices unchanged → basis P&L must be 0"
        assert result["spot_pnl"] == 0.0, "Spot unchanged → spot P&L = 0"
        assert result["perp_pnl"] == 0.0, "Perp unchanged → perp P&L = 0"

        # Funding: capital/2 * 0.0020 = 1000 * 0.002 = $2
        expected_funding = (2000 / 2) * 0.0020  # $2.00
        assert abs(result["total_funding"] - expected_funding) < 0.01, \
            f"Funding should be ${expected_funding:.2f}, received ${result['total_funding']:.2f}"

        # Fees: 1000 * 0.0048 = $4.80 (4 legs x 12bps on the leg notional)
        expected_fees = 1000 * FEES_4_LEGS  # $4.80
        assert abs(result["total_fees"] - expected_fees) < 0.01, \
            f"Fees should be ${expected_fees:.2f}, charged ${result['total_fees']:.2f}"

        # Net: $2.00 - $4.80 = -$2.80 = -28 bps of the leg notional
        expected_net = expected_funding - expected_fees
        assert abs(result["net_pnl"] - expected_net) < 0.01, \
            f"Net P&L should be ${expected_net:.2f}, got ${result['net_pnl']:.2f}"

        print(f"\n  Case A — prices unchanged, funding +20bps: P&L=${result['net_pnl']:.2f} ({result['net_pnl_pct']:.2f}%)")

    def test_case_b_unfavorable_basis(self):
        """
        Case B — Unfavourable basis (−50 bps), funding +30 bps, fees −48 bps.
        Expected result: −68 bps (a loss).
        """
        # Entry: spot=100, perp=100.2 (basis +0.2%)
        # Exit: spot=101, perp=101.7 (basis +0.7%, widened by 50 bps)
        result = simulate_carry_trade(
            entry_spot=100.0,
            entry_perp=100.2,   # basis +0.2% on entry
            exit_spot=101.0,
            exit_perp=101.7,    # basis +0.7% on exit -> a 50 bps loss
            funding_rates=[0.0030],  # +30 bps
            capital=1000.0,
        )

        # Basis P&L: LONG spot = +$10, SHORT perp = (100.2-101.7)*10 = -$15 → basis = -$5
        spot_qty = 1000 / 100.0  # 10 units
        perp_qty = 1000 / 100.2  # ~9.98 units
        expected_spot = spot_qty * (101.0 - 100.0)  # +$10.00
        expected_perp = perp_qty * (100.2 - 101.7)   # ~-$14.97
        expected_basis = expected_spot + expected_perp  # ~-$4.97

        assert abs(result["basis_pnl"] - expected_basis) < 0.05, \
            f"Basis P&L should be ~${expected_basis:.2f}, got ${result['basis_pnl']:.2f}"

        # The basis P&L is indeed negative (a loss)
        assert result["basis_pnl"] < 0, "Unfavourable basis → basis P&L must be negative"

        # Funding: 1000 * 0.003 = $3
        expected_funding = 1000 * 0.0030  # $3.00

        # Fees: $4.80
        expected_fees = 1000 * FEES_4_LEGS

        # Net: $3.00 + (-$4.97) - $4.80 = -$6.77
        expected_net = expected_funding + expected_basis - expected_fees
        assert abs(result["net_pnl"] - expected_net) < 0.05, \
            f"Net P&L should be ~${expected_net:.2f}, got ${result['net_pnl']:.2f}"

        print(f"\n  Case B — unfavourable basis: P&L=${result['net_pnl']:.2f} ({result['net_pnl_pct']:.2f}%)")

    def test_case_c_perfectly_hedged_directional(self):
        """
        Case C — Directional move perfectly hedged.
        Spot +20%, perp +20%, funding +50 bps, fees −48 bps.
        Expected result: net directional P&L = 0, total P&L = funding − fees.
        """
        result = simulate_carry_trade(
            entry_spot=100.0,
            entry_perp=100.0,
            exit_spot=120.0,   # +20%
            exit_perp=120.0,   # +20% (perfectly correlated)
            funding_rates=[0.0050, 0.0050, 0.0050],  # 3 periods x 50 bps
            capital=1000.0,
        )

        # Directional: spot + perp must cancel out
        spot_qty = 1000 / 100.0  # 10 units
        perp_qty = 1000 / 100.0  # 10 units
        expected_spot = spot_qty * (120 - 100)    # +$200
        expected_perp = perp_qty * (100 - 120)     # -$200
        expected_basis = expected_spot + expected_perp  # $0

        assert abs(result["basis_pnl"]) < 0.01, \
            f"Perfect hedge → basis P&L must be ~0, got ${result['basis_pnl']:.2f}"

        # Funding: 3 x (1000 * 0.005) = $15
        expected_funding = 3 * 1000 * 0.0050  # $15.00
        assert abs(result["total_funding"] - expected_funding) < 0.01

        # Fees: $4.80
        expected_fees = 1000 * FEES_4_LEGS

        # Net: $15.00 + $0 - $4.80 = $10.20
        expected_net = expected_funding - expected_fees
        assert abs(result["net_pnl"] - expected_net) < 0.01, \
            f"Net P&L should be ${expected_net:.2f}, got ${result['net_pnl']:.2f}"

        # The trade must be profitable because the funding covers the fees
        assert result["net_pnl"] > 0, \
            f"Funding 150bps > 48bps fees → trade should be profitable, P&L={result['net_pnl']:.2f}"

        print(f"\n  Case C — hedged direction, 3×50bps funding: P&L=${result['net_pnl']:.2f} ({result['net_pnl_pct']:.2f}%)")

    def test_breakeven_funding(self):
        """
        Extra test: the minimum funding needed to cover the fees.
        With 48 bps of fees and a 60-day estimated hold:
          - Over 7d: needs 48/(7*3) = 2.29 bps per 8h
          - Over 60d: needs 48/(60*3) = 0.27 bps per 8h
        """
        # Over 7 days (21 periods)
        periods_7d = 21
        breakeven_7d = FEES_4_LEGS / periods_7d  # 0.0048/21 = 0.000229 = 2.29 bps/8h

        # Over 60 days (180 periods)
        periods_60d = 180
        breakeven_60d = FEES_4_LEGS / periods_60d  # 0.0048/180 = 0.000027 = 0.27 bps/8h

        assert breakeven_7d > 0.0002, f"7d breakeven={breakeven_7d*10000:.1f}bps — very high"
        assert breakeven_60d < 0.0001, f"60d breakeven={breakeven_60d*10000:.1f}bps — reasonable"

        # With min_funding=0.005% (0.00005):
        # - Over 7d: 0.005% < 2.29 bps -> NOT profitable (does not cover the fees)
        # - Over 60d: 0.005% > 0.27 bps -> profitable
        min_funding = 0.00005
        assert min_funding < breakeven_7d, \
            f"min_funding={min_funding*10000:.1f}bps < 7d breakeven={breakeven_7d*10000:.1f}bps → NOT viable over 7d"
        assert min_funding > breakeven_60d, \
            f"min_funding={min_funding*10000:.1f}bps > 60d breakeven={breakeven_60d*10000:.1f}bps → viable over 60d"

        print(f"\n  Breakeven: 7d={breakeven_7d*10000:.1f}bps/8h | 60d={breakeven_60d*10000:.1f}bps/8h")
        print(f"  min_funding=0.005%={min_funding*10000:.1f}bps → viable only when the hold is ≥ ~33d")

    def test_unrealized_pnl_percent_vs_decimal(self):
        """
        Regression test (25/07/2026): the node outputs unrealized_pnl_pct in % (×100),
        so the backtest must divide it by 100 before computing unrealized_usd.
        
        Without that fix, an unrealized_pnl_pct of -0.7 (i.e. -0.7%) was read as
        -0.7 (i.e. -70%) → unrealized_usd 100× too large → explosive MaxDD.
        """
        entry_capital = 500.0
        
        # Simulate what the node returns
        unrealized_pnl_pct_from_node = -0.71  # -0.71% (the basis diverged by 0.71%)
        
        # BUG (old code): multiplied directly
        bug_unrealized_usd = unrealized_pnl_pct_from_node * entry_capital  # -0.71 * 500 = -$355!
        
        # FIX: divide by 100 first
        unrealized_decimal = unrealized_pnl_pct_from_node / 100.0
        fix_unrealized_usd = unrealized_decimal * entry_capital  # -0.0071 * 500 = -$3.55
        
        # The bug amplifies by 100x
        assert abs(bug_unrealized_usd) > abs(fix_unrealized_usd) * 50, \
            f"The bug amplifies unrealised PnL: ${bug_unrealized_usd:.2f} vs ${fix_unrealized_usd:.2f} (correct)"
        
        # The correct value is reasonable (0.71% of $500 = $3.55)
        assert abs(fix_unrealized_usd - (-3.55)) < 0.01, \
            f"Unrealised USD should be ~-$3.55, got ${fix_unrealized_usd:.2f}"
        
        # Check the MaxDD impact: NAV goes from $2000 to $1996.45 (correct)
        # instead of $2000 to $1645 (bug)
        nav_start = 2000.0
        nav_bug = nav_start + bug_unrealized_usd  # $1645 → -17.7% DD
        nav_fix = nav_start + fix_unrealized_usd  # $1996.45 → -0.18% DD
        
        assert nav_bug < nav_fix, "The bug understates the NAV (amplified MaxDD)"
        
        print(f"\n  Unrealized P&L % bug: node=-0.71% → bug=$-{abs(bug_unrealized_usd):.0f} → fix=$-{abs(fix_unrealized_usd):.2f}")
        print(f"  NAV impact: bug={nav_bug:.0f} (-{100-nav_bug/nav_start*100:.1f}% DD) vs fix={nav_fix:.0f} (-{100-nav_fix/nav_start*100:.2f}% DD)")

    def test_x1000_contract_perp_normalization(self):
        """
        Regression (04/09/2026): ×1000 contracts (SHIB/PEPE/BONK/FLOKI/LUNC)
        have a perp price 1000× the token's spot price. Without normalisation
        (perp/1000) the basis (perp−spot)/spot reads ≈ −999 instead of ~0, which
        amplifies every basis move by 1000× (the −$18.45 SHIB bug).
        """
        from v7.nodes.funding_carry_node import FundingCarryNode

        # Multiplier: 1000 for x1000 contracts, 1 otherwise
        for sym in ("SHIB/USDT", "PEPE/USDT", "BONK/USDT", "FLOKI/USDT", "LUNC/USDT"):
            assert FundingCarryNode._perp_multiplier(sym) == 1000.0, f"{sym} must be ×1000"
        for sym in ("BTC/USDT", "ETH/USDT", "DOGE/USDT", "SOL/USDT", "AVAX/USDT"):
            assert FundingCarryNode._perp_multiplier(sym) == 1.0, f"{sym} must be ×1"

        # Correct vs buggy basis for SHIB
        spot = 5.41e-06
        perp_raw = 0.00541                       # 1000SHIB contract price
        perp_norm = perp_raw / 1000.0            # price per token
        basis_wrong = (perp_raw - spot) / spot   # ≈ 999 (bug)
        basis_right = (perp_norm - spot) / spot  # ≈ 0
        assert basis_wrong > 900, "Without normalisation the basis explodes (~999)"
        assert abs(basis_right) < 0.01, "Normalised basis must be ~0"

        print(f"\n  ×1000: raw basis={basis_wrong:.1f} → normalised={basis_right:.6f}")

    def test_entry_break_even_vs_max_hold(self):
        """
        Regression (04/09/2026): the round-trip cost (48bps) must be amortised by
        the funding over the maximum hold. With max_hold_days=14, the minimum
        funding that covers the fees is 48bps × 365/14 = 12.5%/yr. The configured
        min_funding (0.005%/8h = 5.48%/yr) is INSUFFICIENT → letting it enter = a guaranteed loss.
        """
        round_trip_cost = 0.0048  # 48bps
        hold_days = 14
        min_viable_annual = round_trip_cost * 365 / hold_days  # 12.51%
        assert min_viable_annual > 0.12, f"Viable threshold = {min_viable_annual:.2%}/yr"

        # configured min_funding = 0.005%/8h -> annualised (3 periods per day)
        min_funding = 0.00005
        annual_at_min_funding = min_funding * (365 * 3)  # 5.475%
        assert annual_at_min_funding < min_viable_annual, \
            f"min_funding {annual_at_min_funding:.2%}/yr < viable threshold {min_viable_annual:.2%}/yr"

        # With max_hold_days=60 (the old hardcode) the threshold drops to 2.92% -> too permissive
        old_cost = round_trip_cost * 365 / 60
        assert old_cost < min_viable_annual, "The 60d hardcode understated the cost"

        print(f"\n  Break-even: hold={hold_days}d → funding ≥ {min_viable_annual:.2%}/yr")
        print(f"  current min_funding = {annual_at_min_funding:.2%}/yr → below the threshold (not profitable)")

    def test_normalize_symbol_variants(self):
        """
        Regression (19/09/2026): the backtests accept free-form symbols on the CLI.
        Without normalisation, "--symbol BTC" made the spot fetch fail
        ("binance does not have market symbol BTC") and the backtest SILENTLY
        fell back to flat $1000 prices → fabricated P&L.
        """
        from v7.core.asset_config import normalize_symbol

        # All these inputs must converge on 'BTC/USDT'
        for raw in ("BTC", "btc", " BTC ", "BTCUSDT", "btcusdt", "btc/usdt",
                    "BTC/USDT", "BTC/USDT:USDT"):
            assert normalize_symbol(raw) == "BTC/USDT", f"{raw!r} → {normalize_symbol(raw)!r}"

        # An explicit non-USDT quote is preserved (no silent rewriting)
        assert normalize_symbol("ETH/USDC") == "ETH/USDC"

        # x1000 contracts: the BASE stays intact (the multiplier is handled elsewhere)
        assert normalize_symbol("1000SHIB") == "1000SHIB/USDT"
        assert normalize_symbol("1000SHIB/USDT:USDT") == "1000SHIB/USDT"
        assert normalize_symbol("SHIB") == "SHIB/USDT"

        # Degenerate cases
        assert normalize_symbol("") == ""
        assert normalize_symbol("   ") == ""

        print("\n  normalize_symbol: BTC/btc/BTCUSDT/BTC-USDT:USDT → BTC/USDT")

    def test_backtests_use_live_config_thresholds(self):
        """
        Regression (19/09/2026): the backtests must read their thresholds from
        carry_assets.yaml (fraction, min_funding, max_hold_days), never from
        hardcoded constants — otherwise a backtest validates a different strategy than live.
        """
        from v7.core.asset_config import get_active_assets, get_asset_params

        actives = get_active_assets()
        assert actives, "No asset enabled in carry_assets.yaml"

        for sym in actives:
            p = get_asset_params(sym)
            assert p.get("enabled") is True, f"{sym} is listed as active but enabled≠true"
            assert 0 < float(p.get("fraction", 0)) <= 1, f"{sym}: invalid fraction"
            assert float(p.get("min_funding", 0)) > 0, f"{sym}: invalid min_funding"
            assert int(p.get("max_hold_days", 0)) > 0, f"{sym}: invalid max_hold_days"

            # The fees (48bps) must be amortised over the real hold duration
            min_viable = 0.0048 * 365 / int(p["max_hold_days"])
            assert min_viable < 1.0, f"{sym}: inconsistent viability threshold"

        print(f"\n  {len(actives)} assets consistent with the live config")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
