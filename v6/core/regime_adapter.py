"""
v6/core/regime_adapter.py — V6 Regime → Parameters Adaptation Table.

Implémente l'adaptation dynamique des paramètres selon le régime détecté,
comme recommandé par le consensus des 5 IA.

Régimes : TREND, RANGE, CHOP
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── Table de correspondance Régime → Paramètres ────────────────────────────
# Format: (sizing_multiplier, sl_mult_adjustment, tp_mult_adjustment, 
#          meta_threshold_adjustment, strategy, max_positions)

REGIME_PARAMS = {
    "TREND": {
        "size_multiplier": 1.0,        # 100% du sizing ATR
        "sl_mult": 2.0,                # SL standard
        "tp_mult": 4.0,                # TP standard
        "meta_threshold_mult": 1.0,    # seuil nominal
        "strategy": "trend_following", # stratégie principale
        "max_positions": 3,            # nominal
        "description": "Marché directionnel — stratégie trend-following pleine taille",
    },
    "RANGE": {
        "size_multiplier": 0.3,        # 30% du sizing ATR
        "sl_mult": 1.5,                # SL plus serré
        "tp_mult": 2.0,                # TP fixe (pas trailing)
        "meta_threshold_mult": 1.5,    # seuil +50% (plus strict)
        "strategy": "mean_reversion",  # basculer en mean-reversion
        "max_positions": 2,            # moins de positions
        "description": "Marché latéral — mean-reversion, sizing réduit, stops serrés",
    },
    "CHOP": {
        "size_multiplier": 0.0,        # pas d'entrées
        "sl_mult": 2.0,
        "tp_mult": 4.0,
        "meta_threshold_mult": 999.0,  # seuil infini → tout bloqué
        "strategy": "flat",            # pas de trading
        "max_positions": 0,            # pas de nouvelles positions
        "description": "Marché chaotique — aucune entrée, on attend",
    },
}


@dataclass
class RegimeAdapter:
    """Adapte les paramètres de trading au régime détecté."""

    current_regime: str = "TREND"

    def adapt_params(self, base_params: dict[str, Any]) -> dict[str, Any]:
        """Retourne les paramètres adaptés au régime courant."""
        regime_cfg = REGIME_PARAMS.get(self.current_regime, REGIME_PARAMS["TREND"])
        
        adapted = dict(base_params)
        adapted["size_multiplier"] = regime_cfg["size_multiplier"]
        adapted["sl_mult"] = base_params.get("sl_mult", 2.0) * regime_cfg.get("sl_mult", 1.0) / 2.0
        # Ajuster selon le régime — on garde le ratio SL/TP cohérent
        sl_base = base_params.get("sl_mult", 2.0)
        adapted["sl_mult"] = max(1.0, sl_base * regime_cfg.get("sl_mult", 2.0) / 2.0)
        adapted["tp_mult"] = max(1.5, base_params.get("tp_mult", 4.0) * regime_cfg.get("tp_mult", 4.0) / 4.0)
        adapted["meta_threshold"] = base_params.get("threshold", 0.20) * regime_cfg["meta_threshold_mult"]
        adapted["strategy"] = regime_cfg["strategy"]
        adapted["max_positions"] = regime_cfg["max_positions"]
        adapted["regime"] = self.current_regime
        
        return adapted

    def should_block_entries(self) -> bool:
        """Retourne True si le régime courant bloque les nouvelles entrées."""
        return REGIME_PARAMS.get(self.current_regime, {}).get("strategy") == "flat"

    def get_size_multiplier(self) -> float:
        """Multiplicateur de sizing pour le régime courant."""
        return REGIME_PARAMS.get(self.current_regime, REGIME_PARAMS["TREND"])["size_multiplier"]

    def get_strategy(self) -> str:
        """Stratégie à utiliser pour le régime courant."""
        return REGIME_PARAMS.get(self.current_regime, REGIME_PARAMS["TREND"])["strategy"]
