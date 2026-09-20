# v4/nodes/__init__.py
from v4.nodes.ai import LLMNode, DebateNode
from v4.nodes.quant import NODE_REGISTRY as _QUANT_REGISTRY

# Fusion des registres V4 + V5 (si disponible)
NODE_REGISTRY: dict[str, type] = {
    **_QUANT_REGISTRY,
    "LLMNode": LLMNode,
    "DebateNode": DebateNode,
}

## Inject the V5 nodes when the module exists
try:
    from v5.nodes import NODE_REGISTRY as _V5_REGISTRY
    NODE_REGISTRY.update(_V5_REGISTRY)
except ImportError:
    pass

__all__ = ["NODE_REGISTRY"]
