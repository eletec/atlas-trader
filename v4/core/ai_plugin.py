"""
v4/core/ai_plugin.py — AIPlugin interface.

An AI plugin plugs into the AI_IN port of a node and produces an AIOutput.
It is always optional, and its result can always be blended or ignored.

Absolute rule: timeout + fallback are mandatory.
A slow or down plugin never blocks the quant cycle.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("v4.core.ai_plugin")

DEFAULT_TIMEOUT_S = 10.0


@dataclass
class AIOutput:
    """Result of an AI plugin."""
    value: Any                          # scalar, dict or string depending on the plugin
    rationale: str = ""                 # human-readable explanation (shown in the dashboard)
    confidence: float = 1.0            # [0, 1] - the model's confidence in its answer
    model_used: str = ""               # name of the model used
    tokens_used: int = 0
    fallback_used: bool = False        # True when the value is a fallback, not a real result


class AIPlugin(ABC):
    """
    Base interface for all AI plugins.

    Implement:
      - run(context) → AIOutput

    The timeout and the fallback are handled by the base class via run_with_timeout().
    Do not override run_with_timeout() unless there is a very specific need.
    """

    def __init__(
        self,
        backend: str = "ollama",
        model: str = "phi4:latest",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        fallback_value: Any = None,
    ) -> None:
        self.backend = backend
        self.model = model
        self.timeout_s = timeout_s
        self.fallback_value = fallback_value

    @property
    @abstractmethod
    def plugin_type(self) -> str:
        """Plugin identifier, e.g. 'OllamaText'."""

    @abstractmethod
    def run(self, context: dict[str, Any]) -> AIOutput:
        """
        Synchronous call to the AI model.
        context contains: node_id, node_type, inputs, quant_outputs, params.
        """

    def run_with_timeout(
        self,
        node_id: str,
        node_type: str,
        inputs: dict[str, Any],
        quant_outputs: dict[str, Any],
        params: dict[str, Any],
    ) -> AIOutput:
        """
        Runs run() with a strict timeout.
        On timeout or error → returns a fallback AIOutput, never raises.
        """
        import concurrent.futures

        context = {
            "node_id": node_id,
            "node_type": node_type,
            "inputs": inputs,
            "quant_outputs": quant_outputs,
            "params": params,
        }

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.run, context)
            try:
                return future.result(timeout=self.timeout_s)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "AIPlugin %s on node %s: timeout after %.1fs — fallback",
                    self.plugin_type, node_id, self.timeout_s,
                )
                return AIOutput(
                    value=self.fallback_value,
                    rationale=f"timeout after {self.timeout_s}s",
                    fallback_used=True,
                )
            except Exception as exc:
                logger.warning(
                    "AIPlugin %s on node %s: error — fallback: %s",
                    self.plugin_type, node_id, exc,
                )
                return AIOutput(
                    value=self.fallback_value,
                    rationale=f"error: {exc}",
                    fallback_used=True,
                )

    def blend(
        self,
        quant_outputs: dict[str, Any],
        ai_output: AIOutput,
        weight: float,
    ) -> dict[str, Any]:
        """
        Default blend: weighted average over the numeric values.
        Nodes can override this method for a custom blend.
        weight=0.0 → pure quant, weight=1.0 → pure AI.
        """
        if ai_output.fallback_used or weight == 0.0:
            return quant_outputs

        result = dict(quant_outputs)

        # Blend only when the AI output is a numeric scalar
        if isinstance(ai_output.value, (int, float)):
            for key, val in result.items():
                if isinstance(val, (int, float)):
                    result[key] = (1 - weight) * val + weight * ai_output.value
                    break  # blend only over the first scalar

        # Add the rationale as metadata
        result["_ai_rationale"] = ai_output.rationale
        result["_ai_model"] = ai_output.model_used
        result["_ai_fallback"] = ai_output.fallback_used
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin": self.plugin_type,
            "backend": self.backend,
            "model": self.model,
            "timeout_s": self.timeout_s,
            "fallback": self.fallback_value,
        }


class PassthroughPlugin(AIPlugin):
    """
    No-op plugin — always returns the fallback.
    Used as a placeholder when no AI plugin is configured.
    """

    @property
    def plugin_type(self) -> str:
        return "Passthrough"

    def run(self, context: dict[str, Any]) -> AIOutput:
        return AIOutput(
            value=self.fallback_value,
            rationale="passthrough — no AI plugin configured",
            fallback_used=True,
        )
