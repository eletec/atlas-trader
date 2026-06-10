# v5/nodes/__init__.py
from v5.nodes.meta_gate import MetaGate
from v5.nodes.circuit_breaker import CircuitBreaker
from v5.nodes.portfolio_risk import PortfolioRisk

NODE_REGISTRY: dict[str, type] = {
    "MetaGate": MetaGate,
    "CircuitBreaker": CircuitBreaker,
    "PortfolioRisk": PortfolioRisk,
}

__all__ = ["MetaGate", "CircuitBreaker", "PortfolioRisk", "NODE_REGISTRY"]
