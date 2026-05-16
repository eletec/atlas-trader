"""
quant/strategy.py — Logique de décision : arbre simple, AUDITABLE.

Pas de magie. Pas de LLM. Une décision = (régime, P(up)) → {LONG, SHORT, FLAT}.

Règles consensus 5 IA :
1. Trader uniquement quand régime = trending (filtre HMM/threshold).
2. LONG si P(up) > 0.55, SHORT si P(up) < 0.45, sinon FLAT (zone morte).
3. Baseline simple : breakout Donchian 20, sans modèle de signal — sert de
   référence pour ablation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import pandas as pd

logger = logging.getLogger("quant.strategy")


class Action(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass
class Decision:
    action: Action
    probability_up: float | None
    regime_trending: bool
    reason: str


def decide(
    probability_up: float | None,
    regime_trending: bool,
    upper_threshold: float = 0.55,
    lower_threshold: float = 0.45,
) -> Decision:
    """Décision atomique. Aucune dépendance externe."""
    if not regime_trending:
        return Decision(Action.FLAT, probability_up, regime_trending, "regime_mean_reverting")
    if probability_up is None or pd.isna(probability_up):
        return Decision(Action.FLAT, probability_up, regime_trending, "no_signal")
    if probability_up > upper_threshold:
        return Decision(Action.LONG, probability_up, regime_trending, "p_up_high")
    if probability_up < lower_threshold:
        return Decision(Action.SHORT, probability_up, regime_trending, "p_up_low")
    return Decision(Action.FLAT, probability_up, regime_trending, "dead_zone")


@dataclass
class BaselineStrategy:
    """Baseline ultra-simple : breakout Donchian 20 sans modèle.

    Sert de référence d'ablation : si la stratégie complète ne bat pas ça
    significativement, le signal n'apporte rien.
    """

    period: int = 20

    def signals(self, features: pd.DataFrame) -> pd.Series:
        """Retourne une série d'Action."""
        actions = pd.Series(index=features.index, dtype="object")
        up = features["breakout_up"]
        dn = features["breakout_dn"]
        actions[:] = Action.FLAT
        actions[up == 1] = Action.LONG
        actions[dn == 1] = Action.SHORT
        return actions
