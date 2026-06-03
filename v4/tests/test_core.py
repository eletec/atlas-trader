"""
v4/tests/test_core.py — Tests unitaires pour Node, AIPlugin, ContextStore, DAGExecutor.

Tests sans dépendances externes (pas de ccxt, pas d'Ollama).
Utilise des nœuds factices (DummyNode) pour valider le comportement du moteur.
"""
from __future__ import annotations

import time
from typing import Any

import pytest

from v4.core.ai_plugin import AIOutput, PassthroughPlugin
from v4.core.context_store import ContextRegistry, ContextStore
from v4.core.dag_executor import DAGExecutor, DAGValidationError
from v4.core.node import Node, NodeMeta, NodeStatus


# ------------------------------------------------------------------
# Nœuds factices pour les tests
# ------------------------------------------------------------------

class AddOneNode(Node):
    """Reçoit value: float → retourne result: float = value + 1."""

    @property
    def node_type(self) -> str:
        return "AddOne"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"value": "float"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"result": "float"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"result": float(inputs.get("value", 0)) + 1}


class MultiplyNode(Node):
    """Reçoit value: float → retourne result: float = value × factor."""

    @property
    def node_type(self) -> str:
        return "Multiply"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"value": "float"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"result": "float"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        factor = self.params.get("factor", 2.0)
        return {"result": float(inputs.get("value", 0)) * factor}


class SourceNode(Node):
    """Nœud sans input — retourne une valeur fixe."""

    @property
    def node_type(self) -> str:
        return "Source"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"value": "float"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"value": float(self.params.get("value", 10.0))}


class ErrorNode(Node):
    """Nœud qui lève toujours une exception."""

    @property
    def node_type(self) -> str:
        return "Error"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"value": "float"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("intentional error")


# ------------------------------------------------------------------
# Tests Node
# ------------------------------------------------------------------

class TestNode:
    def test_execute_success(self):
        node = AddOneNode("add_1", params={})
        result = node.execute({"value": 5.0})
        assert result.status == NodeStatus.DONE
        assert result.outputs["result"] == 6.0

    def test_execute_error(self):
        node = ErrorNode("err_1")
        result = node.execute({})
        assert result.status == NodeStatus.ERROR
        assert result.error is not None

    def test_bypass(self):
        node = AddOneNode("add_1", meta=NodeMeta(bypass=True))
        result = node.execute({"value": 99.0})
        assert result.status == NodeStatus.BYPASSED
        # La valeur d'input est passée directement en output
        assert result.outputs.get("result") == 99.0

    def test_to_dict(self):
        node = SourceNode("src_1", params={"value": 42.0}, meta=NodeMeta(x=10, y=20))
        d = node.to_dict()
        assert d["id"] == "src_1"
        assert d["type"] == "Source"
        assert d["position"] == {"x": 10, "y": 20}
        assert d["params"]["value"] == 42.0


# ------------------------------------------------------------------
# Tests AIPlugin
# ------------------------------------------------------------------

class TestAIPlugin:
    def test_passthrough_returns_fallback(self):
        plugin = PassthroughPlugin(fallback_value=0.0)
        result = plugin.run_with_timeout(
            node_id="n1", node_type="Test",
            inputs={}, quant_outputs={}, params={},
        )
        assert result.fallback_used is True
        assert result.value == 0.0

    def test_timeout_returns_fallback(self):
        import concurrent.futures
        from v4.core.ai_plugin import AIPlugin

        class SlowPlugin(AIPlugin):
            @property
            def plugin_type(self) -> str:
                return "Slow"

            def run(self, context: dict) -> AIOutput:
                time.sleep(5)  # plus long que le timeout
                return AIOutput(value=1.0)

        plugin = SlowPlugin(timeout_s=0.1, fallback_value=-1.0)
        result = plugin.run_with_timeout("n1", "T", {}, {}, {})
        assert result.fallback_used is True
        assert result.value == -1.0

    def test_blend_numeric(self):
        plugin = PassthroughPlugin(fallback_value=0.0)
        # Blend normal : quant=10, IA=20, weight=0.5 → 15
        ai_out = AIOutput(value=20.0, fallback_used=False)
        blended = plugin.blend({"score": 10.0}, ai_out, weight=0.5)
        assert blended["score"] == pytest.approx(15.0)

    def test_blend_fallback_ignored(self):
        plugin = PassthroughPlugin(fallback_value=0.0)
        ai_out = AIOutput(value=999.0, fallback_used=True)
        blended = plugin.blend({"score": 10.0}, ai_out, weight=0.5)
        assert blended["score"] == 10.0  # fallback → quant pur


# ------------------------------------------------------------------
# Tests ContextStore
# ------------------------------------------------------------------

class TestContextStore:
    def test_set_get(self):
        store = ContextStore(asset="TEST")
        store.set("temperature", -42.0)
        assert store.get("temperature") == -42.0

    def test_missing_key_returns_fallback(self):
        store = ContextStore(asset="TEST")
        assert store.get("nonexistent", fallback=99.0) == 99.0

    def test_stale(self):
        store = ContextStore(asset="TEST")
        store.set("old_value", 1.0)
        # max_age_s=0 → immédiatement stale
        assert store.get("old_value", fallback=0.0, max_age_s=0.0) == 0.0

    def test_snapshot(self):
        store = ContextStore(asset="TEST")
        store.set("a", 1.0, source="node_1")
        store.set("b", 2.0, source="node_2")
        snap = store.snapshot()
        assert "a" in snap
        assert snap["a"]["value"] == 1.0
        assert snap["a"]["source"] == "node_1"

    def test_registry_isolation(self):
        store_btc = ContextRegistry.get_store("BTC/USDT")
        store_eth = ContextRegistry.get_store("ETH/USDT")
        store_btc.set("price", 100000.0)
        assert store_eth.get("price") is None  # isolation garantie


# ------------------------------------------------------------------
# Tests DAGExecutor
# ------------------------------------------------------------------

class TestDAGExecutor:
    def _simple_dag(self) -> DAGExecutor:
        """Source(10) → AddOne → Multiply(×3) — résultat attendu: 33"""
        executor = DAGExecutor(asset="TEST")
        executor.add_node(SourceNode("src", params={"value": 10.0}))
        executor.add_node(AddOneNode("add"))
        executor.add_node(MultiplyNode("mul", params={"factor": 3.0}))
        executor.add_edge("src", "value", "add", "value")
        executor.add_edge("add", "result", "mul", "value")
        return executor

    def test_run_once_correct_result(self):
        executor = self._simple_dag()
        executor.validate()
        results = executor.run_once()
        assert results["mul"].status == NodeStatus.DONE
        assert results["mul"].outputs["result"] == pytest.approx(33.0)

    def test_cycle_detection(self):
        executor = DAGExecutor(asset="TEST")
        executor.add_node(AddOneNode("a"))
        executor.add_node(AddOneNode("b"))
        executor.add_edge("a", "result", "b", "value")
        executor.add_edge("b", "result", "a", "value")  # cycle !
        with pytest.raises(DAGValidationError, match="cycle"):  # "DAG contains a cycle"
            executor.validate()

    def test_unknown_node_in_edge(self):
        executor = DAGExecutor(asset="TEST")
        executor.add_node(SourceNode("src"))
        executor.add_edge("src", "value", "nonexistent", "value")
        with pytest.raises(DAGValidationError, match="unknown node"):  # "Edge references unknown node"
            executor.validate()

    def test_invalid_port(self):
        executor = DAGExecutor(asset="TEST")
        executor.add_node(SourceNode("src"))
        executor.add_node(AddOneNode("add"))
        executor.add_edge("src", "WRONG_PORT", "add", "value")
        with pytest.raises(DAGValidationError, match="output port"):  # "has no output port"
            executor.validate()

    def test_error_node_does_not_crash_executor(self):
        executor = DAGExecutor(asset="TEST")
        executor.add_node(ErrorNode("err"))
        results = executor.run_once()
        assert results["err"].status == NodeStatus.ERROR

    def test_duplicate_node_id_raises(self):
        executor = DAGExecutor(asset="TEST")
        executor.add_node(SourceNode("src"))
        with pytest.raises(ValueError, match="Duplicate"):
            executor.add_node(SourceNode("src"))

    def test_context_store_written_after_run(self):
        executor = self._simple_dag()
        executor.validate()
        executor.run_once()
        store = ContextRegistry.get_store("TEST")
        # Le résultat du nœud mul doit être dans le ContextStore
        val = store.get("mul.result")
        assert val == pytest.approx(33.0)
