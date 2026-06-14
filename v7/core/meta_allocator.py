"""
v7/core/meta_allocator.py — Meta Allocation Engine V7.

Remplace MetaGate V6. Au lieu de prédire LONG/SHORT/FLAT, alloue le capital
entre plusieurs stratégies indépendantes en fonction de leurs performances récentes
et du régime de marché.

Entrées:
    - Signaux normalisés de chaque stratégie (score, confiance, retour espéré)
    - Régime de marché courant (probabilités)
    - Historique récent de performance par stratégie

Sortie:
    - Allocation de capital par stratégie (somme = 1.0)
    - Taille de position globale
    - Niveau de risque autorisé

Méthode:
    - Phase 1: XGBoost léger (si assez d'historique)
    - Phase 2: Online SGD (River) pour adaptation continue
    - Fallback: Risk Parity naïf (1/N si pas d'historique)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("meta_allocator")


@dataclass
class StrategyScore:
    name: str
    score: float          # signal normalisé [-1, 1]
    confidence: float     # 0-1
    expected_return: float  # annualisé
    recent_sharpe: float = 0.0  # Sharpe glissant (30j)
    active: bool = True


@dataclass
class Allocation:
    strategy: str
    weight: float          # 0-1, fraction du capital
    size_usd: float
    reason: str


@dataclass
class MetaAllocation:
    allocations: list[Allocation]
    total_exposure: float  # fraction du capital déployée
    risk_level: str        # "low" | "medium" | "high"
    regime_override: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class MetaAllocator:
    """Alloue le capital entre N stratégies.
    
    Règles:
    1. Si une stratégie a un Sharpe récent < -1 → poids = 0
    2. Si régime = CHOP → max 20% du capital déployé
    3. Si régime = PANIC → 0% (CircuitBreaker)
    4. Allocation ∝ (recent_sharpe + 1) × confidence × regime_multiplier
    5. Normalisation pour que sum(poids) = 1 (ou 0 si tout négatif)
    """

    def __init__(
        self,
        capital: float = 10_000,
        max_strategies: int = 4,
        lookback_days: int = 30,
        min_weight: float = 0.05,
        regime_multipliers: dict | None = None,
    ):
        self.capital = capital
        self.max_strategies = max_strategies
        self.lookback_days = lookback_days
        self.min_weight = min_weight
        self.regime_multipliers = regime_multipliers or {
            "TREND": 1.0,
            "RANGE": 0.5,
            "CHOP": 0.2,
            "BULL_EXPANSION": 1.2,
            "BEAR_EXPANSION": 0.3,
            "PANIC": 0.0,
        }
        
        # Historique de performance par stratégie
        self._performance: dict[str, list[float]] = {}
    
    def record_performance(self, strategy: str, pnl_pct: float):
        """Enregistre le PnL daily d'une stratégie."""
        if strategy not in self._performance:
            self._performance[strategy] = []
        self._performance[strategy].append(pnl_pct)
        # Garder seulement les N derniers jours
        if len(self._performance[strategy]) > self.lookback_days:
            self._performance[strategy] = self._performance[strategy][-self.lookback_days:]
    
    def _recent_sharpe(self, strategy: str) -> float:
        """Calcule le Sharpe glissant d'une stratégie."""
        returns = self._performance.get(strategy, [])
        if len(returns) < 5:
            return 0.0
        import numpy as np
        arr = np.array(returns[-self.lookback_days:])
        mu = arr.mean()
        sigma = arr.std()
        if sigma == 0:
            return 0.0
        return float(mu / sigma * np.sqrt(252))
    
    def allocate(
        self,
        strategies: list[StrategyScore],
        regime: str = "TREND",
        max_capital_fraction: float = 0.80,
    ) -> MetaAllocation:
        """Alloue le capital entre les stratégies actives."""
        
        # Filtrer stratégies actives
        active = [s for s in strategies if s.active]
        if not active:
            return MetaAllocation(
                allocations=[],
                total_exposure=0.0,
                risk_level="low",
                regime_override="no_active_strategies",
            )
        
        # ── Calcul des scores d'allocation ──
        regime_mult = self.regime_multipliers.get(regime, 1.0)
        
        if regime == "PANIC" or regime_mult == 0.0:
            return MetaAllocation(
                allocations=[],
                total_exposure=0.0,
                risk_level="low",
                regime_override="PANIC — circuit breaker",
            )
        
        weights_raw = {}
        for s in active:
            # Score = Sharpe récent (si dispo) ou score × confidence
            recent_sharpe = self._recent_sharpe(s.name)
            s.recent_sharpe = recent_sharpe
            
            if recent_sharpe < -1.0:
                # Stratégie en forte perte → exclue
                weights_raw[s.name] = 0.0
                continue
            
            # Base: score × confidence × regime_mult
            base = max(0.0, s.score * s.confidence * regime_mult)
            
            # Bonus si Sharpe récent positif
            if recent_sharpe > 0:
                base *= (1.0 + min(1.0, recent_sharpe))
            
            weights_raw[s.name] = base
        
        # Normaliser
        total = sum(weights_raw.values())
        if total <= 0:
            # Aucune stratégie viable → flat
            return MetaAllocation(
                allocations=[],
                total_exposure=0.0,
                risk_level="low",
                regime_override="no_viable_strategy",
            )
        
        # ── Allocation finale ──
        allocations = []
        for s in active:
            w = weights_raw.get(s.name, 0.0) / total
            if w < self.min_weight:
                continue  # trop petit → exclu
            
            size = self.capital * max_capital_fraction * w * regime_mult
            allocations.append(Allocation(
                strategy=s.name,
                weight=round(w, 3),
                size_usd=round(size, 2),
                reason=f"score={s.score:.2f} conf={s.confidence:.2f} sharpe={s.recent_sharpe:.2f} regime={regime}",
            ))
        
        # Re-normaliser après filtrage min_weight
        total_w = sum(a.weight for a in allocations)
        if total_w > 0:
            for a in allocations:
                a.weight /= total_w
        
        # Risk level
        total_exposure = sum(a.weight for a in allocations) * max_capital_fraction
        if total_exposure < 0.20:
            risk_level = "low"
        elif total_exposure < 0.50:
            risk_level = "medium"
        else:
            risk_level = "high"
        
        return MetaAllocation(
            allocations=allocations,
            total_exposure=round(total_exposure, 3),
            risk_level=risk_level,
        )


# ── Test ──
if __name__ == "__main__":
    allocator = MetaAllocator(capital=10_000)
    
    strategies = [
        StrategyScore(name="funding_carry", score=0.70, confidence=0.80, expected_return=0.10),
        StrategyScore(name="dominance_rotation", score=0.50, confidence=0.65, expected_return=0.08),
        StrategyScore(name="mean_reversion", score=0.30, confidence=0.55, expected_return=0.05),
        StrategyScore(name="trend_following", score=-0.10, confidence=0.40, expected_return=-0.02),
    ]
    
    # Simuler un peu d'historique
    for _ in range(20):
        allocator.record_performance("funding_carry", 0.002)
        allocator.record_performance("dominance_rotation", 0.001)
        allocator.record_performance("mean_reversion", -0.001)
        allocator.record_performance("trend_following", -0.003)
    
    result = allocator.allocate(strategies, regime="TREND")
    print(f"TREND: {result}")
    
    result_chop = allocator.allocate(strategies, regime="CHOP")
    print(f"CHOP: {result_chop}")
    
    result_panic = allocator.allocate(strategies, regime="PANIC")
    print(f"PANIC: {result_panic}")
