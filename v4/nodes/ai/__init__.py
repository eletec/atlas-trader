"""
v4/nodes/ai/__init__.py — Nœuds AI V4 (LLM, sentiment, synthèse)
"""
from v4.nodes.ai.llm_node import LLMNode
from v4.nodes.ai.debate_node import DebateNode

__all__ = ["LLMNode", "DebateNode"]
