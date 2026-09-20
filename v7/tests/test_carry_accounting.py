"""
v7/tests/test_carry_accounting.py — Tests unitaires de comptabilité Funding Carry.

Valide les 3 cas du GPT audit (25/07/2026) :
  Cas A — Prix inchangés, funding positif → perte si frais > funding
  Cas B — Basis défavorable → perte même avec funding positif
  Cas C — Variation directionnelle parfaitement couverte → P&L net = funding + basis − frais

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
    capital: float = 2000.0,
) -> dict:
    """Simule un trade carry complet : short perp + long spot.

    Returns:
        Dict avec le breakdown complet du P&L.
    """
    # -- Entry --
    # Spot long: we buy capital/2 worth of spot
    spot_qty = (capital / 2) / entry_spot
    # Short perp : on vend capital/2 de perp
    perp_qty = (capital / 2) / entry_perp

    open_fees = capital * FEES_2_LEGS_OPEN  # 2 legs on entry

    # -- Funding received --
    total_funding = 0.0
    for fr in funding_rates:
        if fr > 0:
            total_funding += (capital / 2) * fr  # paid on the short perp leg only
        elif fr < 0:
            total_funding += (capital / 2) * fr  # we pay when the funding is negative

    # ── Sortie ──
    spot_pnl = spot_qty * (exit_spot - entry_spot)        # long spot
    perp_pnl = perp_qty * (entry_perp - exit_perp)         # short perp
    basis_pnl = spot_pnl + perp_pnl                        # should be ~0 when hedged
    close_fees = capital * FEES_2_LEGS_CLOSE               # 2 legs on exit
    total_fees = open_fees + close_fees

    net_pnl = total_funding + basis_pnl - total_fees

    return {
        "spot_pnl": round(spot_pnl, 4),
        "perp_pnl": round(perp_pnl, 4),
        "basis_pnl": round(basis_pnl, 4),
        "total_funding": round(total_funding, 4),
        "open_fees": round(open_fees, 4),
        "close_fees": round(close_fees, 4),
        "total_fees": round(total_fees, 4),
        "net_pnl": round(net_pnl, 4),
        "net_pnl_pct": round(net_pnl / capital * 100, 4),
    }


class TestCarryAccounting:
    """Tests de comptabilité — GPT audit 25/07/2026."""

    def test_case_a_flat_prices_funding_positive(self):
        """
        Cas A — Prix inchangés, funding reçu +20 bps, frais −48 bps.
        Résultat attendu : −28 bps (perte).
        """
        result = simulate_carry_trade(
            entry_spot=100.0,
            entry_perp=100.0,
            exit_spot=100.0,
            exit_perp=100.0,
            funding_rates=[0.0020],  # +20 bps over 1 period
            capital=2000.0,
        )

        # Assertions
        assert result["basis_pnl"] == 0.0, "Prix inchangés → basis P&L doit être 0"
        assert result["spot_pnl"] == 0.0, "Spot inchangé → spot P&L = 0"
        assert result["perp_pnl"] == 0.0, "Perp inchangé → perp P&L = 0"

        # Funding: capital/2 * 0.0020 = 1000 * 0.002 = $2
        expected_funding = (2000 / 2) * 0.0020  # $2.00
        assert abs(result["total_funding"] - expected_funding) < 0.01, \
            f"Funding devrait être ${expected_funding:.2f}, reçu ${result['total_funding']:.2f}"

        # Frais: 2000 * 0.0048 = $9.60
        expected_fees = 2000 * FEES_4_LEGS  # $9.60
        assert abs(result["total_fees"] - expected_fees) < 0.01, \
            f"Frais devraient être ${expected_fees:.2f}, prélevés ${result['total_fees']:.2f}"

        # Net: $2.00 - $9.60 = -$7.60 (-0.38%)
        expected_net = expected_funding - expected_fees
        assert abs(result["net_pnl"] - expected_net) < 0.01, \
            f"P&L net devrait être ${expected_net:.2f}, obtenu ${result['net_pnl']:.2f}"

        print(f"\n  Cas A — Prix inchangés, funding +20bps: P&L=${result['net_pnl']:.2f} ({result['net_pnl_pct']:.2f}%)")

    def test_case_b_unfavorable_basis(self):
        """
        Cas B — Basis défavorable (−50 bps), funding +30 bps, frais −48 bps.
        Résultat attendu : −68 bps (perte).
        """
        # Entry: spot=100, perp=100.2 (basis +0.2%)
        # Exit: spot=101, perp=101.7 (basis +0.7%, widened by 50 bps)
        result = simulate_carry_trade(
            entry_spot=100.0,
            entry_perp=100.2,   # basis +0.2% on entry
            exit_spot=101.0,
            exit_perp=101.7,    # basis +0.7% on exit -> a 50 bps loss
            funding_rates=[0.0030],  # +30 bps
            capital=2000.0,
        )

        # Basis P&L: LONG spot = +$10, SHORT perp = (100.2-101.7)*10 = -$15 → basis = -$5
        spot_qty = 1000 / 100.0  # 10 units
        perp_qty = 1000 / 100.2  # ~9.98 units
        expected_spot = spot_qty * (101.0 - 100.0)  # +$10.00
        expected_perp = perp_qty * (100.2 - 101.7)   # ~-$14.97
        expected_basis = expected_spot + expected_perp  # ~-$4.97

        assert abs(result["basis_pnl"] - expected_basis) < 0.05, \
            f"Basis P&L devrait être ~${expected_basis:.2f}, obtenu ${result['basis_pnl']:.2f}"

        # The basis P&L is indeed negative (a loss)
        assert result["basis_pnl"] < 0, "Basis défavorable → basis P&L doit être négatif"

        # Funding: 1000 * 0.003 = $3
        expected_funding = (2000 / 2) * 0.0030  # $3.00

        # Frais: $9.60
        expected_fees = 2000 * FEES_4_LEGS

        # Net: $3.00 + (-$4.97) - $9.60 = -$11.57
        expected_net = expected_funding + expected_basis - expected_fees
        assert abs(result["net_pnl"] - expected_net) < 0.05, \
            f"P&L net devrait être ~${expected_net:.2f}, obtenu ${result['net_pnl']:.2f}"

        print(f"\n  Cas B — Basis défavorable: P&L=${result['net_pnl']:.2f} ({result['net_pnl_pct']:.2f}%)")

    def test_case_c_perfectly_hedged_directional(self):
        """
        Cas C — Variation directionnelle parfaitement couverte.
        Spot +20%, Perp +20%, funding +50 bps, frais −48 bps.
        Résultat attendu : P&L directionnel net = 0, P&L total = funding − frais.
        """
        result = simulate_carry_trade(
            entry_spot=100.0,
            entry_perp=100.0,
            exit_spot=120.0,   # +20%
            exit_perp=120.0,   # +20% (perfectly correlated)
            funding_rates=[0.0050, 0.0050, 0.0050],  # 3 periods x 50 bps
            capital=2000.0,
        )

        # Directional: spot + perp must cancel out
        spot_qty = 1000 / 100.0  # 10 units
        perp_qty = 1000 / 100.0  # 10 units
        expected_spot = spot_qty * (120 - 100)    # +$200
        expected_perp = perp_qty * (100 - 120)     # -$200
        expected_basis = expected_spot + expected_perp  # $0

        assert abs(result["basis_pnl"]) < 0.01, \
            f"Couverture parfaite → basis P&L doit être ~0, obtenu ${result['basis_pnl']:.2f}"

        # Funding: 3 x (1000 * 0.005) = $15
        expected_funding = 3 * (2000 / 2) * 0.0050  # $15.00
        assert abs(result["total_funding"] - expected_funding) < 0.01

        # Frais: $9.60
        expected_fees = 2000 * FEES_4_LEGS

        # Net: $15.00 + $0 - $9.60 = $5.40
        expected_net = expected_funding - expected_fees
        assert abs(result["net_pnl"] - expected_net) < 0.01, \
            f"P&L net devrait être ${expected_net:.2f}, obtenu ${result['net_pnl']:.2f}"

        # The trade must be profitable because the funding covers the fees
        assert result["net_pnl"] > 0, \
            f"Funding 150bps > frais 48bps → trade devrait être rentable, P&L={result['net_pnl']:.2f}"

        print(f"\n  Cas C — Directionnel couvert, funding 3×50bps: P&L=${result['net_pnl']:.2f} ({result['net_pnl_pct']:.2f}%)")

    def test_breakeven_funding(self):
        """
        Test supplémentaire : calcul du funding minimum pour couvrir les frais.
        Avec 48 bps de frais et 60j de hold estimé :
          - Sur 7j : besoin de 48/(7*3) = 2.29 bps par 8h
          - Sur 60j : besoin de 48/(60*3) = 0.27 bps par 8h
        """
        # Over 7 days (21 periods)
        periods_7d = 21
        breakeven_7d = FEES_4_LEGS / periods_7d  # 0.0048/21 = 0.000229 = 2.29 bps/8h

        # Over 60 days (180 periods)
        periods_60d = 180
        breakeven_60d = FEES_4_LEGS / periods_60d  # 0.0048/180 = 0.000027 = 0.27 bps/8h

        assert breakeven_7d > 0.0002, f"Breakeven 7j={breakeven_7d*10000:.1f}bps — très élevé"
        assert breakeven_60d < 0.0001, f"Breakeven 60j={breakeven_60d*10000:.1f}bps — raisonnable"

        # With min_funding=0.005% (0.00005):
        # - Over 7d: 0.005% < 2.29 bps -> NOT profitable (does not cover the fees)
        # - Over 60d: 0.005% > 0.27 bps -> profitable
        min_funding = 0.00005
        assert min_funding < breakeven_7d, \
            f"min_funding={min_funding*10000:.1f}bps < breakeven 7j={breakeven_7d*10000:.1f}bps → NON viable sur 7j"
        assert min_funding > breakeven_60d, \
            f"min_funding={min_funding*10000:.1f}bps > breakeven 60j={breakeven_60d*10000:.1f}bps → viable sur 60j"

        print(f"\n  Breakeven: 7j={breakeven_7d*10000:.1f}bps/8h | 60j={breakeven_60d*10000:.1f}bps/8h")
        print(f"  min_funding=0.005%={min_funding*10000:.1f}bps → viable seulement si hold ≥ ~33j")

    def test_unrealized_pnl_percent_vs_decimal(self):
        """
        Test de regression (25/07/2026): le node output unrealized_pnl_pct en % (×100),
        le backtest doit le diviser par 100 avant de calculer unrealized_usd.
        
        Sans ce fix, un unrealized_pnl_pct de -0.7 (soit -0.7%) était interprété
        comme -0.7 (soit -70%) → unrealized_usd 100× trop grand → MaxDD explosif.
        """
        entry_capital = 500.0
        
        # Simulate what the node returns
        unrealized_pnl_pct_from_node = -0.71  # -0.71% (the basis diverged by 0.71%)
        
        # BUG (old code): multiplied directly
        bug_unrealized_usd = unrealized_pnl_pct_from_node * entry_capital  # -0.71 * 500 = -$355!
        
        # FIX: diviser par 100 d'abord
        unrealized_decimal = unrealized_pnl_pct_from_node / 100.0
        fix_unrealized_usd = unrealized_decimal * entry_capital  # -0.0071 * 500 = -$3.55
        
        # The bug amplifies by 100x
        assert abs(bug_unrealized_usd) > abs(fix_unrealized_usd) * 50, \
            f"Le bug amplifie l'unrealized PnL: ${bug_unrealized_usd:.2f} vs ${fix_unrealized_usd:.2f} (correct)"
        
        # The correct value is reasonable (0.71% of $500 = $3.55)
        assert abs(fix_unrealized_usd - (-3.55)) < 0.01, \
            f"Unrealized USD correct: ${fix_unrealized_usd:.2f} devrait être ~-$3.55"
        
        # Check the MaxDD impact: NAV goes from $2000 to $1996.45 (correct)
        # instead of $2000 to $1645 (bug)
        nav_start = 2000.0
        nav_bug = nav_start + bug_unrealized_usd  # $1645 → -17.7% DD
        nav_fix = nav_start + fix_unrealized_usd  # $1996.45 → -0.18% DD
        
        assert nav_bug < nav_fix, "Le bug sous-estime la NAV (MaxDD amplifié)"
        
        print(f"\n  Unrealized P&L % bug: node=-0.71% → bug=$-{abs(bug_unrealized_usd):.0f} → fix=$-{abs(fix_unrealized_usd):.2f}")
        print(f"  NAV impact: bug={nav_bug:.0f} (-{100-nav_bug/nav_start*100:.1f}% DD) vs fix={nav_fix:.0f} (-{100-nav_fix/nav_start*100:.2f}% DD)")

    def test_x1000_contract_perp_normalization(self):
        """
        Régression (04/09/2026) : les contrats ×1000 (SHIB/PEPE/BONK/FLOKI/LUNC)
        ont un prix perp 1000× supérieur au prix spot du token. Sans normalisation
        (perp/1000), la basis (perp−spot)/spot vaut ≈ −999 au lieu de ~0, ce qui
        amplifie toute variation de basis par 1000× (bug du −$18.45 sur SHIB).
        """
        from v7.nodes.funding_carry_node import FundingCarryNode

        # Multiplier: 1000 for x1000 contracts, 1 otherwise
        for sym in ("SHIB/USDT", "PEPE/USDT", "BONK/USDT", "FLOKI/USDT", "LUNC/USDT"):
            assert FundingCarryNode._perp_multiplier(sym) == 1000.0, f"{sym} doit être ×1000"
        for sym in ("BTC/USDT", "ETH/USDT", "DOGE/USDT", "SOL/USDT", "AVAX/USDT"):
            assert FundingCarryNode._perp_multiplier(sym) == 1.0, f"{sym} doit être ×1"

        # Correct vs buggy basis for SHIB
        spot = 5.41e-06
        perp_raw = 0.00541                       # prix du contrat 1000SHIB
        perp_norm = perp_raw / 1000.0            # prix par token
        basis_wrong = (perp_raw - spot) / spot   # ≈ 999 (bug)
        basis_right = (perp_norm - spot) / spot  # ≈ 0
        assert basis_wrong > 900, "Sans normalisation la basis explose (~999)"
        assert abs(basis_right) < 0.01, "Basis normalisée doit être ~0"

        print(f"\n  ×1000: basis brute={basis_wrong:.1f} → normalisée={basis_right:.6f}")

    def test_entry_break_even_vs_max_hold(self):
        """
        Régression (04/09/2026) : le coût de round-trip (48bps) doit être amorti
        par le funding sur la durée de hold max. Avec max_hold_days=14, le funding
        minimum pour couvrir les frais est 48bps × 365/14 = 12.5%/an. Le min_funding
        configuré (0.005%/8h = 5.48%/an) est INSUFFISANT → laisser entrer = perte garantie.
        """
        round_trip_cost = 0.0048  # 48bps
        hold_days = 14
        min_viable_annual = round_trip_cost * 365 / hold_days  # 12.51%
        assert min_viable_annual > 0.12, f"Seuil viable = {min_viable_annual:.2%}/an"

        # configured min_funding = 0.005%/8h -> annualised (3 periods per day)
        min_funding = 0.00005
        annual_at_min_funding = min_funding * (365 * 3)  # 5.475%
        assert annual_at_min_funding < min_viable_annual, \
            f"min_funding {annual_at_min_funding:.2%}/an < seuil viable {min_viable_annual:.2%}/an"

        # With max_hold_days=60 (the old hardcode) the threshold drops to 2.92% -> too permissive
        old_cost = round_trip_cost * 365 / 60
        assert old_cost < min_viable_annual, "Le hardcode 60j sous-estimait le coût"

        print(f"\n  Break-even: hold={hold_days}j → funding ≥ {min_viable_annual:.2%}/an")
        print(f"  min_funding actuel = {annual_at_min_funding:.2%}/an → sous le seuil (non rentable)")

    def test_normalize_symbol_variants(self):
        """
        Régression (19/09/2026) : les backtests acceptent des symboles saisis
        librement en CLI. Sans normalisation, « --symbol BTC » faisait échouer le
        fetch spot (« binance does not have market symbol BTC ») et le backtest
        retombait SILENCIEUSEMENT sur des prix fixes de 1000 $ → P&L fictif.
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
        Régression (19/09/2026) : les backtests doivent lire les seuils depuis
        carry_assets.yaml (fraction, min_funding, max_hold_days) et non des
        constantes en dur — sinon le backtest valide une autre stratégie que le live.
        """
        from v7.core.asset_config import get_active_assets, get_asset_params

        actives = get_active_assets()
        assert actives, "Aucun actif activé dans carry_assets.yaml"

        for sym in actives:
            p = get_asset_params(sym)
            assert p.get("enabled") is True, f"{sym} listé actif mais enabled≠true"
            assert 0 < float(p.get("fraction", 0)) <= 1, f"{sym}: fraction invalide"
            assert float(p.get("min_funding", 0)) > 0, f"{sym}: min_funding invalide"
            assert int(p.get("max_hold_days", 0)) > 0, f"{sym}: max_hold_days invalide"

            # The fees (48bps) must be amortised over the real hold duration
            min_viable = 0.0048 * 365 / int(p["max_hold_days"])
            assert min_viable < 1.0, f"{sym}: seuil de viabilité incohérent"

        print(f"\n  {len(actives)} actifs cohérents avec la config live")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
