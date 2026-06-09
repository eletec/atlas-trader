# v4/nodes/__init__.py
from v4.nodes.ai import LLMNode, DebateNode
from v4.nodes.quant import NODE_REGISTRY as _QUANT_REGISTRY

# Fusion des registres
NODE_REGISTRY: dict[str, type] = {
    **_QUANT_REGISTRY,
    "LLMNode": LLMNode,
    "DebateNode": DebateNode,
}

__all__ = ["NODE_REGISTRY"]
