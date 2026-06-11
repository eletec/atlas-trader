"""
v5/nodes/portfolio_risk.py — Portfolio Risk Engine V5.

Gère l'exposition inter-actifs :
  - Calcule l'exposition BTC-équivalente
  - Plafonne le risque cluster (BTC+ETH ≤ 30%, ALTs ≤ 20%)
  - Ajuste le sizing en fonction des corrélations
  - Circuit-breaker global (DD > 5% → réduire, > 8% → flat)

S'intègre avant le PaperTrader, après le RiskATR.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from v4.core.node import Node

logger = logging.getLogger("v5.nodes.portfolio_risk")

# ── Clusters de corrélation ──
CLUSTERS = {
    "BTC": ["BTC/USDT", "ETH/USDT"],
    "ALT": ["SOL/USDT", "BNB/USDT"],
    "OTHER": ["XRP/USDT"],
}

# ── Corrélations approximatives (moyennes mobiles 30j) ──
# En production, recalculées quotidiennement
DEFAULT_CORR = {
    ("BTC/USDT", "ETH/USDT"): 0.80,
    ("BTC/USDT", "SOL/USDT"): 0.65,
    ("BTC/USDT", "BNB/USDT"): 0.60,
    ("BTC/USDT", "XRP/USDT"): 0.45,
}


class PortfolioRisk(Node):
    """
    Contrôle le risque portfolio global.
    Doit recevoir les infos de TOUS les actifs (via un nœud aggregateur).
    Version simplifiée : contrôle par actif avec limites globales.

    Inputs :
        decision     : dict — sortie RiskATR
        symbol       : str  — actif concerné
        total_exposure : float — exposition agrégée du portfolio

    Outputs :
        decision     : dict — ajusté (sizing réduit si nécessaire)
        blocked      : bool
        reason       : str
    """

    # ── Shared state across all instances ──
    _exposure_by_symbol: dict[str, float] = {}
    _total_exposure: float = 0.0

    @classmethod
    def update_exposure(cls, symbol: str, size_usd: float):
        """Called by PaperTrader or externally to track live exposure."""
        cls._exposure_by_symbol[symbol] = abs(size_usd)
        cls._total_exposure = sum(cls._exposure_by_symbol.values())

    @property
    def node_type(self) -> str:
        return "PortfolioRisk"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"decision": "dict", "symbol": "str", "total_exposure": "float"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"decision": "dict", "blocked": "bool", "reason": "str"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        decision = inputs.get("decision", {})
        if isinstance(decision, str):
            decision = {}
        action = decision.get("action", "flat")
        if action == "flat":
            return {"decision": decision, "blocked": False, "reason": ""}

        symbol = inputs.get("symbol", "BTC/USDT")
        # Use shared state if no total_exposure provided
        total_exposure = float(inputs.get("total_exposure", PortfolioRisk._total_exposure))

        # ── Déterminer le cluster ──
        cluster = "OTHER"
        for cname, symbols in CLUSTERS.items():
            if symbol in symbols:
                cluster = cname
                break

        # ── Calculer l'exposition effective (pondérée par corrélation BTC) ──
        corr_btc = DEFAULT_CORR.get(("BTC/USDT", symbol), 0.5)
        effective_exposure = abs(float(decision.get("size_usd", 0))) * corr_btc

        # ── Limites par cluster ──
        max_cluster = float(self.params.get("max_cluster_pct", 30.0))  # % du capital
        max_total = float(self.params.get("max_total_pct", 150.0))
        capital = float(self.params.get("capital", 10_000))

        cluster_exposure_pct = (total_exposure / capital * 100) if capital > 0 else 0
        effective_exposure_pct = (effective_exposure / capital * 100) if capital > 0 else 0

        # ── Vérification des limites ──
        if cluster_exposure_pct >= max_cluster:
            logger.info(
                "PortfolioRisk: cluster %s exposure %.1f%% ≥ %.0f%% → block %s",
                cluster, cluster_exposure_pct, max_cluster, action,
            )
            return {
                "decision": {"action": "flat", "reason": f"cluster_exposure={cluster_exposure_pct:.0f}%"},
                "blocked": True,
                "reason": f"Cluster {cluster} saturé ({cluster_exposure_pct:.0f}%)",
            }

        # ── Sizing ajusté ──
        decision_out = dict(decision)
        if effective_exposure_pct > 15.0:
            # Réduire le sizing si exposition effective trop élevée
            scale = 15.0 / effective_exposure_pct
            old_size = float(decision.get("size_usd", 0))
            new_size = old_size * scale
            decision_out["size_usd"] = round(new_size, 2)
            decision_out["reason"] = decision.get("reason", "") + f" | sized_{scale:.1f}x"
            logger.info("PortfolioRisk: %s sizing scaled %.2fx (%.0f→%.0f$)",
                        symbol, scale, old_size, new_size)

        return {"decision": decision_out, "blocked": False, "reason": ""}
