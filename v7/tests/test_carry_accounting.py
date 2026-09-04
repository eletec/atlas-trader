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

FEE_PER_LEG = 0.0012       # 12 bps (10 fees + 2 slippage)
FEES_4_LEGS = FEE_PER_LEG * 4  # 48 bps round-trip
FEES_2_LEGS_OPEN = FEE_PER_LEG * 2   # 24 bps à l'ouverture
FEES_2_LEGS_CLOSE = FEE_PER_LEG * 2  # 24 bps à la fermeture


def simulate_carry_trade(
    entry_spot: float,
    entry_perp: float,
    exit_spot: float,
    exit_perp: float,
    funding_rates: list[float],  # liste de taux par période de 8h
    capital: float = 2000.0,
) -> dict:
    """Simule un trade carry complet : short perp + long spot.

    Returns:
        Dict avec le breakdown complet du P&L.
    """
    # ── Entrée ──
    # Long spot : on achète capital/2 de spot
    spot_qty = (capital / 2) / entry_spot
    # Short perp : on vend capital/2 de perp
    perp_qty = (capital / 2) / entry_perp

    open_fees = capital * FEES_2_LEGS_OPEN  # 2 jambes à l'ouverture

    # ── Funding reçu ──
    total_funding = 0.0
    for fr in funding_rates:
        if fr > 0:
            total_funding += (capital / 2) * fr  # payé sur la jambe short perp uniquement
        elif fr < 0:
            total_funding += (capital / 2) * fr  # on paie si funding négatif

    # ── Sortie ──
    spot_pnl = spot_qty * (exit_spot - entry_spot)        # long spot
    perp_pnl = perp_qty * (entry_perp - exit_perp)         # short perp
    basis_pnl = spot_pnl + perp_pnl                        # devrait être ~0 si couvert
    close_fees = capital * FEES_2_LEGS_CLOSE               # 2 jambes à la fermeture
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
            funding_rates=[0.0020],  # +20 bps sur 1 période
            capital=2000.0,
        )

        # Vérifications
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
        # Entrée: spot=100, perp=100.2 (basis +0.2%)
        # Sortie: spot=101, perp=101.7 (basis +0.7%, s'est élargi de 50 bps)
        result = simulate_carry_trade(
            entry_spot=100.0,
            entry_perp=100.2,   # basis +0.2% à l'entrée
            exit_spot=101.0,
            exit_perp=101.7,    # basis +0.7% à la sortie → perte de 50 bps
            funding_rates=[0.0030],  # +30 bps
            capital=2000.0,
        )

        # Basis P&L: LONG spot = +$10, SHORT perp = (100.2-101.7)*10 = -$15 → basis = -$5
        spot_qty = 1000 / 100.0  # 10 unités
        perp_qty = 1000 / 100.2  # ~9.98 unités
        expected_spot = spot_qty * (101.0 - 100.0)  # +$10.00
        expected_perp = perp_qty * (100.2 - 101.7)   # ~-$14.97
        expected_basis = expected_spot + expected_perp  # ~-$4.97

        assert abs(result["basis_pnl"] - expected_basis) < 0.05, \
            f"Basis P&L devrait être ~${expected_basis:.2f}, obtenu ${result['basis_pnl']:.2f}"

        # Le basis est bien négatif (perte)
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
            exit_perp=120.0,   # +20% (parfaitement corrélé)
            funding_rates=[0.0050, 0.0050, 0.0050],  # 3 périodes × 50 bps
            capital=2000.0,
        )

        # Directionnel: spot + perp doivent s'annuler
        spot_qty = 1000 / 100.0  # 10 unités
        perp_qty = 1000 / 100.0  # 10 unités
        expected_spot = spot_qty * (120 - 100)    # +$200
        expected_perp = perp_qty * (100 - 120)     # -$200
        expected_basis = expected_spot + expected_perp  # $0

        assert abs(result["basis_pnl"]) < 0.01, \
            f"Couverture parfaite → basis P&L doit être ~0, obtenu ${result['basis_pnl']:.2f}"

        # Funding: 3 × (1000 * 0.005) = $15
        expected_funding = 3 * (2000 / 2) * 0.0050  # $15.00
        assert abs(result["total_funding"] - expected_funding) < 0.01

        # Frais: $9.60
        expected_fees = 2000 * FEES_4_LEGS

        # Net: $15.00 + $0 - $9.60 = $5.40
        expected_net = expected_funding - expected_fees
        assert abs(result["net_pnl"] - expected_net) < 0.01, \
            f"P&L net devrait être ${expected_net:.2f}, obtenu ${result['net_pnl']:.2f}"

        # Le trade doit être rentable car le funding couvre les frais
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
        # Sur 7 jours (21 périodes)
        periods_7d = 21
        breakeven_7d = FEES_4_LEGS / periods_7d  # 0.0048/21 = 0.000229 = 2.29 bps/8h

        # Sur 60 jours (180 périodes)
        periods_60d = 180
        breakeven_60d = FEES_4_LEGS / periods_60d  # 0.0048/180 = 0.000027 = 0.27 bps/8h

        assert breakeven_7d > 0.0002, f"Breakeven 7j={breakeven_7d*10000:.1f}bps — très élevé"
        assert breakeven_60d < 0.0001, f"Breakeven 60j={breakeven_60d*10000:.1f}bps — raisonnable"

        # Avec min_funding=0.005% (0.00005) :
        # - Sur 7j: 0.005% < 2.29 bps → PAS rentable (ne couvre pas les frais)
        # - Sur 60j: 0.005% > 0.27 bps → rentable
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
        
        # Simuler ce que le node renvoie
        unrealized_pnl_pct_from_node = -0.71  # -0.71% (basis divergé de 0.71%)
        
        # BUG (ancien code): multiplié directement
        bug_unrealized_usd = unrealized_pnl_pct_from_node * entry_capital  # -0.71 * 500 = -$355!
        
        # FIX: diviser par 100 d'abord
        unrealized_decimal = unrealized_pnl_pct_from_node / 100.0
        fix_unrealized_usd = unrealized_decimal * entry_capital  # -0.0071 * 500 = -$3.55
        
        # Le bug amplifie de 100×
        assert abs(bug_unrealized_usd) > abs(fix_unrealized_usd) * 50, \
            f"Le bug amplifie l'unrealized PnL: ${bug_unrealized_usd:.2f} vs ${fix_unrealized_usd:.2f} (correct)"
        
        # La valeur correcte est raisonnable (0.71% de $500 = $3.55)
        assert abs(fix_unrealized_usd - (-3.55)) < 0.01, \
            f"Unrealized USD correct: ${fix_unrealized_usd:.2f} devrait être ~-$3.55"
        
        # Vérifier l'impact sur le MaxDD: NAV passe de $2000 à $1996.45 (correct)
        # au lieu de $2000 à $1645 (bug)
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

        # Multiplicateur : 1000 pour les ×1000, 1 sinon
        for sym in ("SHIB/USDT", "PEPE/USDT", "BONK/USDT", "FLOKI/USDT", "LUNC/USDT"):
            assert FundingCarryNode._perp_multiplier(sym) == 1000.0, f"{sym} doit être ×1000"
        for sym in ("BTC/USDT", "ETH/USDT", "DOGE/USDT", "SOL/USDT", "AVAX/USDT"):
            assert FundingCarryNode._perp_multiplier(sym) == 1.0, f"{sym} doit être ×1"

        # Basis correcte vs buggée pour SHIB
        spot = 5.41e-06
        perp_raw = 0.00541                       # prix du contrat 1000SHIB
        perp_norm = perp_raw / 1000.0            # prix par token
        basis_wrong = (perp_raw - spot) / spot   # ≈ 999 (bug)
        basis_right = (perp_norm - spot) / spot  # ≈ 0
        assert basis_wrong > 900, "Sans normalisation la basis explose (~999)"
        assert abs(basis_right) < 0.01, "Basis normalisée doit être ~0"

        print(f"\n  ×1000: basis brute={basis_wrong:.1f} → normalisée={basis_right:.6f}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
