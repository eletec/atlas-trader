"""
agents/specialized_agents.py - Re-exports de compatibilite (P6).
Les implementations sont desormais dans leurs fichiers canoniques.
"""
from agents.fundamental_agent import FundamentalAgent  # noqa: F401
from agents.contrarian_agent import ContrarianAgent    # noqa: F401
from agents.x_sentiment_agent import XSentimentAgent   # noqa: F401

__all__ = ["FundamentalAgent", "ContrarianAgent", "XSentimentAgent"]