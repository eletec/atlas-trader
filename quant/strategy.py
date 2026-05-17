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

logger = logging.getLogger("zeitgeist.quant.strategy")


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
    upper_threshold: float = 0.58,
    lower_threshold: float = 0.42,
) -> Decision:
    """Décision atomique. Zone morte [0.42, 0.58] — élargie selon consensus 3 IA.

    Note : appeler uniquement quand regime = TRENDING (1.0).
    Pour regime = RANGE (0.5), utiliser decide_range().
    Pour regime = PANIC (0.0), retourner FLAT directement.
    """
    if not regime_trending:
        return Decision(Action.FLAT, probability_up, regime_trending, "regime_not_trending")
    if probability_up is None or pd.isna(probability_up):
        return Decision(Action.FLAT, probability_up, regime_trending, "no_signal")
    if probability_up > upper_threshold:
        return Decision(Action.LONG, probability_up, regime_trending, "p_up_high")
    if probability_up < lower_threshold:
        return Decision(Action.SHORT, probability_up, regime_trending, "p_up_low")
    return Decision(Action.FLAT, probability_up, regime_trending, "dead_zone")


def decide_range(
    bb_pct_b: float | None,
    vwap_dist: float | None,
    prob_up: float | None = None,
    bb_long_threshold: float = 0.10,
    bb_short_threshold: float = 0.90,
    vwap_conf: float = 0.30,
) -> Decision:
    """Mean-reverting signal pour régime RANGE (consensus Grok + GPT + DeepSeek).

    Logique : en RANGE, le prix a tendance à revenir vers sa moyenne.
    - LONG  : prix au plancher des BB (%b < seuil) ET sous le VWAP → fade la pression vendeuse
    - SHORT : prix au plafond des BB (%b > seuil) ET au-dessus du VWAP → fade la pression acheteuse

    Veto ML optionnel : si P(up) est fort CONTRE la direction, on passe en FLAT
    (ne pas acheter si le modèle est fortement baissier P(up) < 0.35).

    Args:
        bb_pct_b: Bollinger %b normalisé ∈ [0, 1].
        vwap_dist: Distance au VWAP normalisée par ATR (>0 = au-dessus).
        prob_up: P(up) du signal ML (optionnel — veto seulement).
        bb_long_threshold: Seuil %b bas pour LONG (défaut 0.10).
        bb_short_threshold: Seuil %b haut pour SHORT (défaut 0.90).
        vwap_conf: |vwap_dist| minimum pour confirmation (défaut 0.30).
    """
    if bb_pct_b is None or pd.isna(bb_pct_b):
        return Decision(Action.FLAT, prob_up, False, "range_no_bb")
    if vwap_dist is None or pd.isna(vwap_dist):
        return Decision(Action.FLAT, prob_up, False, "range_no_vwap")

    # LONG : plancher BB + confirmation sous VWAP
    if bb_pct_b < bb_long_threshold and vwap_dist < -vwap_conf:
        # Veto ML : ne pas acheter si signal fortement baissier
        if prob_up is not None and not pd.isna(prob_up) and prob_up < 0.35:
            return Decision(Action.FLAT, prob_up, False, "range_ml_veto_long")
        return Decision(Action.LONG, prob_up, False, "range_mean_revert_long")

    # SHORT : plafond BB + confirmation au-dessus VWAP
    if bb_pct_b > bb_short_threshold and vwap_dist > vwap_conf:
        # Veto ML : ne pas shorter si signal fortement haussier
        if prob_up is not None and not pd.isna(prob_up) and prob_up > 0.65:
            return Decision(Action.FLAT, prob_up, False, "range_ml_veto_short")
        return Decision(Action.SHORT, prob_up, False, "range_mean_revert_short")

    return Decision(Action.FLAT, prob_up, False, "range_dead_zone")


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
