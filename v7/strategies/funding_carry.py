"""
v7/strategies/funding_carry.py — Funding Rate Carry Strategy V7.

Collecte la prime de funding rate en shorter le perpétuel et en achetant le spot.
Market-neutral : le PnL vient du funding, pas de la direction du prix.

Usage:
    from v7.strategies.funding_carry import FundingCarryEngine
    engine = FundingCarryEngine(symbol="BTC/USDT", capital=5000)
    signal = engine.evaluate(funding_rate=0.0005, spot_price=67000, perp_price=67005)

Architecture:
    - Short perpetual → reçoit le funding (si funding > 0)
    - Long spot → couvre le delta
    - Net: PnL ≈ funding_rate × time - frais - slippage
    - Exit si funding devient négatif > 24h
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger("funding_carry")


@dataclass
class CarrySignal:
    symbol: str
    action: str  # "open_carry" | "close_carry" | "flat"
    funding_rate: float  # annualisé
    expected_return: float  # % attendu sur la période
    size_usd: float
    confidence: float  # 0-1
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class FundingCarryEngine:
    """Calcule le signal de funding carry pour un actif.
    
    Stratégie :
    - Si funding_rate > min_threshold → open carry (short perp + long spot)
    - Si funding_rate < 0 depuis >24h → close carry
    - Taille basée sur Kelly fractionnel appliqué au capital alloué
    """

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        capital: float = 10_000,
        min_funding: float = 0.00005,       # 0.005% par 8h = ~5.5% annualisé
        max_funding: float = 0.003,          # 0.3% par 8h = cap (anormal)
        fraction: float = 0.20,              # 20% du capital en carry
        kelly_fraction: float = 0.5,         # half-Kelly
        exit_after_hours: int = 48,          # fermer si funding négatif >48h
        min_expected_return_pct: float = 0.02,  # 2% annualisé minimum
    ):
        self.symbol = symbol
        self.capital = capital
        self.min_funding = min_funding
        self.max_funding = max_funding
        self.fraction = fraction
        self.kelly_fraction = kelly_fraction
        self.exit_after_hours = exit_after_hours
        self.min_expected_return_pct = min_expected_return_pct
        
        self._position_open = False
        self._negative_since: Optional[datetime] = None
    
    def evaluate(
        self,
        funding_rate: float,       # taux par période (8h pour Binance)
        spot_price: float,
        perp_price: Optional[float] = None,
        hours_to_next_funding: float = 8.0,
    ) -> CarrySignal:
        """Évalue le signal de funding carry.
        
        Args:
            funding_rate: taux de funding actuel (ex: 0.0001 = 0.01%)
            spot_price: prix spot BTC/USDT
            perp_price: prix du perpétuel (si None, = spot_price)
            hours_to_next_funding: heures jusqu'au prochain paiement
        
        Returns:
            CarrySignal avec action et sizing
        """
        # Annualiser le funding rate
        periods_per_year = 365 * 24 / 8  # 1095 périodes de 8h par an
        annual_funding = funding_rate * periods_per_year
        
        # Calculer le spread perp-spot (basis)
        if perp_price and perp_price > 0:
            basis_pct = (perp_price - spot_price) / spot_price
        else:
            basis_pct = 0.0
        
        # ── Règles de décision ──
        
        # Cas 1: Funding positif → opportunité de carry
        if funding_rate >= self.min_funding and not self._position_open:
            # Vérifier que le basis n'est pas trop défavorable
            # (si le perp est très au-dessus du spot, le carry est moins attractif)
            if basis_pct > funding_rate * 3:
                return CarrySignal(
                    symbol=self.symbol,
                    action="flat",
                    funding_rate=annual_funding,
                    expected_return=0.0,
                    size_usd=0.0,
                    confidence=0.3,
                    reason=f"basis trop élevé ({basis_pct*100:.4f}% > funding)",
                )
            
            # Calculer le retour espéré annualisé
            expected_return = annual_funding - abs(basis_pct) * periods_per_year
            
            if expected_return < self.min_expected_return_pct:
                return CarrySignal(
                    symbol=self.symbol,
                    action="flat",
                    funding_rate=annual_funding,
                    expected_return=expected_return,
                    size_usd=0.0,
                    confidence=0.5,
                    reason=f"retour espéré {expected_return*100:.2f}% < {self.min_expected_return_pct*100:.0f}%",
                )
            
            # Kelly sizing: edge = expected_return, odds = 1 (market neutral)
            kelly_f = max(0.0, min(0.5, expected_return / 0.10))  # cap à 50%
            size = self.capital * self.fraction * kelly_f * self.kelly_fraction
            confidence = min(0.9, max(0.5, kelly_f * 2))
            
            self._position_open = True
            self._negative_since = None
            
            return CarrySignal(
                symbol=self.symbol,
                action="open_carry",
                funding_rate=annual_funding,
                expected_return=expected_return,
                size_usd=round(size, 2),
                confidence=round(confidence, 2),
                reason=f"funding={funding_rate*100:.4f}% → carry {expected_return*100:.2f}%/an",
            )
        
        # Cas 2: Position ouverte — surveiller la sortie
        if self._position_open:
            # Funding devenu négatif → timer de sortie
            if funding_rate < 0:
                if self._negative_since is None:
                    self._negative_since = datetime.now()
                hours_negative = (datetime.now() - self._negative_since).total_seconds() / 3600
                
                if hours_negative > self.exit_after_hours:
                    self._position_open = False
                    return CarrySignal(
                        symbol=self.symbol,
                        action="close_carry",
                        funding_rate=annual_funding,
                        expected_return=0.0,
                        size_usd=0.0,
                        confidence=0.8,
                        reason=f"funding négatif depuis {hours_negative:.0f}h > {self.exit_after_hours}h",
                    )
                
                return CarrySignal(
                    symbol=self.symbol,
                    action="flat",
                    funding_rate=annual_funding,
                    expected_return=annual_funding,
                    size_usd=0.0,
                    confidence=0.5,
                    reason=f"funding négatif depuis {hours_negative:.0f}h, attente",
                )
            else:
                self._negative_since = None
                return CarrySignal(
                    symbol=self.symbol,
                    action="flat",
                    funding_rate=annual_funding,
                    expected_return=annual_funding,
                    size_usd=0.0,
                    confidence=0.7,
                    reason="carry actif, funding OK",
                )
        
        # Cas 3: Flat — pas d'opportunité
        return CarrySignal(
            symbol=self.symbol,
            action="flat",
            funding_rate=annual_funding,
            expected_return=annual_funding,
            size_usd=0.0,
            confidence=0.5,
            reason=f"funding={funding_rate*100:.4f}% < min={self.min_funding*100:.4f}%",
        )
    
    def reset(self):
        """Réinitialise l'état (utile pour backtest)."""
        self._position_open = False
        self._negative_since = None


# ── Test rapide ──
if __name__ == "__main__":
    engine = FundingCarryEngine(symbol="BTC/USDT", capital=10_000)
    
    # Scénario: funding à 0.01% (bon)
    sig = engine.evaluate(funding_rate=0.0001, spot_price=67000)
    print(f"Funding 0.01%: {sig}")
    
    # Scénario: funding à 0.1% (excellent)
    sig2 = engine.evaluate(funding_rate=0.001, spot_price=67000)
    print(f"Funding 0.1%: {sig2}")
    
    # Scénario: funding négatif
    engine.reset()
    sig3 = engine.evaluate(funding_rate=-0.0001, spot_price=67000)
    print(f"Funding -0.01%: {sig3}")
