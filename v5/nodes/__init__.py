# v5/nodes/__init__.py
from v5.nodes.meta_gate import MetaGate
from v5.nodes.circuit_breaker import CircuitBreaker
from v5.nodes.portfolio_risk import PortfolioRisk
from v5.nodes.regime_detector import RegimeDetector

NODE_REGISTRY: dict[str, type] = {
    "MetaGate": MetaGate,
    "CircuitBreaker": CircuitBreaker,
    "PortfolioRisk": PortfolioRisk,
    "RegimeDetector": RegimeDetector,
}

__all__ = ["MetaGate", "CircuitBreaker", "PortfolioRisk", "RegimeDetector", "NODE_REGISTRY"]
