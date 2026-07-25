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


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
