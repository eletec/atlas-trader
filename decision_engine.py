"""
decision_engine.py — Moteur de decision V2 (quant pur)

Remplace le systeme V1 (ScoringWeights, AlphaCombinationAgent,
MiroFish, Kronos, vetos techniques, Kelly sizing).

V2 : wrapper mince autour de quant/strategy.py.
     Toute la logique de decision est dans :
       - quant.strategy.decide()       — arbre regime x P(up)
       - quant.risk.RiskManager        — sizing, SL/TP, trailing, kill-switch
       - graph.workflow.LiveRunner     — etat stateful inter-cycles

Ce fichier expose la classe DecisionEngine pour retrocompatibilite
eventuelle et comme point de documentation des regles V2.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("quant.decision_engine")


@dataclass
class V2Decision:
    """Structure d une decision V2."""
    action: str              # long | short | flat
    reason: str              # raison machine (dead_zone, p_up_high, etc.)
    regime_trending: bool
    probability_up: float | None
    entry_price: float | None = None
    sl_price: float | None = None
    tp_price: float | None = None
    position_size_pct: float = 0.015


class DecisionEngine:
    """
    Moteur de decision V2 — interface unifiee pour tests et debug.

    Usage normal : utiliser graph.workflow.run_cycle() directement.
    Usage test/debug : instancier DecisionEngine et appeler decide_from_state().
    """

    # Seuils de decision (PLAN_DEV_V2.md — consensus 5 IA)
    P_UP_THRESHOLD = 0.55     # au-dessus : LONG
    P_DN_THRESHOLD = 0.45     # en dessous : SHORT
    # Zone morte [0.45, 0.55] : FLAT meme en regime trending

    def decide_from_state(
        self,
        regime_trending: bool,
        probability_up: float | None,
        close_price: float | None = None,
        atr_14: float | None = None,
        capital: float = 10_000.0,
    ) -> V2Decision:
        """
        Produit une decision a partir de l etat courant.

        Regles (inchangeables sauf validation OOS) :
        1. Si regime = ranging (mean-reverting) → FLAT toujours.
        2. Si regime = trending ET P(up) > 0.55 → LONG.
        3. Si regime = trending ET P(up) < 0.45 → SHORT.
        4. Sinon → FLAT (zone morte de +/-5% autour de 0.50).

        SL = 2.5 × ATR14 ; TP = 3.0 × ATR14 (R:R ≈ 1.2)
        Sizing : 1.5% du capital / distance_SL
        """
        from quant.strategy import decide
        from quant.risk import RiskManager, RiskParams

        d = decide(
            probability_up=probability_up,
            regime_trending=regime_trending,
            upper_threshold=self.P_UP_THRESHOLD,
            lower_threshold=self.P_DN_THRESHOLD,
        )

        sl_price = None
        tp_price = None
        size_pct = 0.015

        if d.action.value != "flat" and close_price and atr_14:
            rm = RiskManager(RiskParams())
            try:
                pos = rm.compute_position(
                    side=d.action.value,
                    entry_price=close_price,
                    atr_value=atr_14,
                    capital=capital,
                )
                sl_price = pos.stop_loss
                tp_price = pos.take_profit
            except Exception as exc:
                logger.debug(f"Sizing skip: {exc}")

        return V2Decision(
            action=d.action.value,
            reason=d.reason,
            regime_trending=regime_trending,
            probability_up=probability_up,
            entry_price=close_price,
            sl_price=sl_price,
            tp_price=tp_price,
            position_size_pct=size_pct,
        )

    def decide_flat(self, reason: str = "manual") -> V2Decision:
        """Retourne toujours FLAT — utilise pour les periodes de pause / kill-switch."""
        return V2Decision(
            action="flat", reason=reason,
            regime_trending=False, probability_up=None,
        )
