# v5/nodes/__init__.py
from v5.nodes.meta_gate import MetaGate

NODE_REGISTRY: dict[str, type] = {
    "MetaGate": MetaGate,
}

__all__ = ["MetaGate", "NODE_REGISTRY"]
