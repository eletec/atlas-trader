"""
v7/core/__init__.py — V7 Core Modules.

MetaAllocator + RegimeEngine V7 + (future: EventEngine, PortfolioOptimizer).
"""

from v7.core.meta_allocator import MetaAllocator, StrategyScore, Allocation, MetaAllocation
from v7.core.regime_engine import RegimeEngineV7, RegimeDistribution

__all__ = [
    "MetaAllocator", "StrategyScore", "Allocation", "MetaAllocation",
    "RegimeEngineV7", "RegimeDistribution",
]
