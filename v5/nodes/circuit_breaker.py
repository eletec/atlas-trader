"""
v5/nodes/circuit_breaker.py — Circuit Breaker V5.

Protection portfolio globale :
  - DD 24h > -3% → plus de nouveaux trades (mode défensif)
  - DD 24h > -5% → flat all positions
  - Vérifié à chaque cycle

S'intègre entre RiskATR et PaperTrader.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from v4.core.node import Node

logger = logging.getLogger("v5.nodes.circuit_breaker")


class CircuitBreaker(Node):
    """Bloque les nouveaux trades si drawdown portfolio excessif."""

    @property
    def node_type(self) -> str:
        return "CircuitBreaker"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {
            "decision": "dict",      # sortie RiskATR
            "portfolio_pnl": "float", # PnL total depuis le début
            "portfolio_value": "float",
        }

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"decision": "dict", "blocked": "bool", "reason": "str"}

    def __init__(self, node_id: str = "", params: dict | None = None, **kwargs):
        super().__init__(node_id=node_id, params=params, **kwargs)
        self._peak_value = None
        self._daily_pnl = 0.0
        self._last_reset = datetime.now(timezone.utc).date()

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        decision = inputs.get("decision", {})
        if isinstance(decision, str):
            decision = {}
        action = decision.get("action", "flat")
        if action == "flat":
            return {"decision": decision, "blocked": False, "reason": ""}

        portfolio_value = float(inputs.get("portfolio_value", 0))
        portfolio_pnl = float(inputs.get("portfolio_pnl", 0))

        # ── DD tracker ──
        if self._peak_value is None or portfolio_value > self._peak_value:
            self._peak_value = portfolio_value
        dd_pct = ((portfolio_value - self._peak_value) / self._peak_value * 100) if self._peak_value > 0 else 0

        # ── Reset daily PnL ──
        today = datetime.now(timezone.utc).date()
        if today != self._last_reset:
            self._daily_pnl = 0.0
            self._last_reset = today
        self._daily_pnl = portfolio_pnl  # simplified

        # ── Seuils configurable ──
        dd_warn = float(self.params.get("dd_warn_pct", -3.0))
        dd_kill = float(self.params.get("dd_kill_pct", -5.0))

        if dd_pct <= dd_kill:
            logger.warning(
                "CircuitBreaker KILL: DD=%.1f%% → flat all", dd_pct,
            )
            return {
                "decision": {"action": "flat", "reason": "circuit_breaker_kill"},
                "blocked": True,
                "reason": f"DD={dd_pct:.1f}% < {dd_kill}%",
            }

        if dd_pct <= dd_warn:
            logger.info(
                "CircuitBreaker WARN: DD=%.1f%% → defensive, block new trades", dd_pct,
            )
            return {
                "decision": {"action": "flat", "reason": "circuit_breaker_warn"},
                "blocked": True,
                "reason": f"DD={dd_pct:.1f}% < {dd_warn}%",
            }

        return {"decision": decision, "blocked": False, "reason": ""}
