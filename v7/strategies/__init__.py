"""
v7/strategies/__init__.py — V7 Strategy Modules.

V7 pivots from directional prediction to risk premium harvesting.
Each strategy produces a normalized signal consumed by MetaAllocator.
"""

from v7.strategies.funding_carry import FundingCarryEngine, CarrySignal
from v7.strategies.dominance_rotation import DominanceRotationEngine, DominanceSignal

__all__ = ["FundingCarryEngine", "CarrySignal", "DominanceRotationEngine", "DominanceSignal"]
