"""
decision_engine.py — Score Calculator + Risk Engine + Decision Engine
Centralise toute la logique de décision et de gestion du risque.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("zeitgeist.decision")


# ===========================================================
# SCORE CALCULATOR
# ===========================================================

@dataclass
class ScoringWeights:
    mirofish: float = 0.40
    market: float = 0.30
    agents: float = 0.20
    contrarian: float = 0.10
    MIN: float = field(default=0.05, repr=False)
    MAX: float = field(default=0.60, repr=False)

    def validate(self) -> None:
        total = self.mirofish + self.market + self.agents + self.contrarian
        if not (0.99 < total < 1.01):
            raise ValueError(f"Les poids doivent sommer à 1.0 (actuel: {total:.3f})")
        for name, val in [("mirofish", self.mirofish), ("market", self.market),
                          ("agents", self.agents), ("contrarian", self.contrarian)]:
            if not (self.MIN <= val <= self.MAX):
                raise ValueError(f"Poids '{name}'={val:.3f} hors bornes [{self.MIN}, {self.MAX}]")


class ScoreCalculator:
    """Calcule le score global de conviction [0-100]."""

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        w = cfg.get("scoring", {}).get("weights", {})
        self.weights = ScoringWeights(
            mirofish=w.get("mirofish", 0.40),
            market=w.get("market", 0.30),
            agents=w.get("agents", 0.20),
            contrarian=w.get("contrarian", 0.10),
        )

    def calculate(
        self,
        mirofish_score: float,
        market_score: float,
        agent_scores: dict[str, float],
        contrarian_score: float,
    ) -> tuple[float, dict]:
        """
        Calcule le score global pondéré.

        Returns:
            score: float [0-100]
            breakdown: dict — contribution de chaque composant
        """
        # Score moyen des agents (hors contrarian)
        agents_mean = (
            sum(agent_scores.values()) / len(agent_scores)
            if agent_scores else 50.0
        )

        weighted_score = (
            mirofish_score * self.weights.mirofish
            + market_score * self.weights.market
            + agents_mean * self.weights.agents
            + contrarian_score * self.weights.contrarian
        )

        score = max(0.0, min(100.0, weighted_score))

        breakdown = {
            "mirofish": {"score": mirofish_score, "weight": self.weights.mirofish,
                         "contribution": round(mirofish_score * self.weights.mirofish, 2)},
            "market": {"score": market_score, "weight": self.weights.market,
                       "contribution": round(market_score * self.weights.market, 2)},
            "agents": {"score": agents_mean, "weight": self.weights.agents,
                       "contribution": round(agents_mean * self.weights.agents, 2),
                       "detail": agent_scores},
            "contrarian": {"score": contrarian_score, "weight": self.weights.contrarian,
                           "contribution": round(contrarian_score * self.weights.contrarian, 2)},
            "final_score": round(score, 2),
        }

        logger.debug(
            f"Score: {score:.1f} "
            f"(MF={mirofish_score:.0f}×{self.weights.mirofish} "
            f"+ MKT={market_score:.0f}×{self.weights.market} "
            f"+ AGT={agents_mean:.0f}×{self.weights.agents} "
            f"+ CTR={contrarian_score:.0f}×{self.weights.contrarian})"
        )
        return round(score, 2), breakdown


# ===========================================================
# RISK ENGINE
# ===========================================================

class RiskEngine:
    """Gestion du risque : sizing, SL/TP, circuit breaker."""

    def __init__(self):
        from utils.config import load_settings
        from storage.database import get_pnl_history
        cfg = load_settings()
        risk = cfg.get("risk", {})
        exchange = cfg.get("exchange", {})

        self.mode: str = risk.get("mode", "balanced")
        self.kelly_max: float = risk.get("kelly_max_fraction", 0.25)
        self.max_dd_pct: float = risk.get("max_drawdown_pct", 15.0)
        self.pos_size_pct: float = risk.get("position_size_pct", 5.0)
        self.atr_sl_mult: float = risk.get("atr_multiplier_sl", 2.0)
        self.atr_tp_mult: float = risk.get("atr_multiplier_tp", 3.0)
        self.capital: float = exchange.get("paper_capital_usd", 10000.0)

        # Ajustements selon le mode
        mode_multipliers = {"conservative": 0.5, "balanced": 1.0, "aggressive": 1.5}
        mult = mode_multipliers.get(self.mode, 1.0)
        self.kelly_max *= mult
        self.pos_size_pct *= mult

    def is_circuit_breaker_active(self) -> bool:
        """Vérifie si le drawdown maximal est atteint."""
        try:
            from storage.database import get_pnl_history
            history = get_pnl_history()
            if not history:
                return False
            cumulative_pnl = sum(h.get("result_24h", 0) or 0 for h in history)
            drawdown_pct = abs(cumulative_pnl) / self.capital * 100
            if drawdown_pct >= self.max_dd_pct:
                logger.warning(
                    f"CIRCUIT BREAKER ACTIF — drawdown={drawdown_pct:.1f}% >= {self.max_dd_pct}%"
                )
                return True
        except Exception:
            pass
        return False

    def calculate_position_size(
        self, price: float, win_rate: float = 0.55, rr_ratio: float = 1.5,
        score: float = 50.0
    ) -> float:
        """Calcule la taille de position en USD via Kelly Criterion.

        La taille est minorée par un multiplicateur de conviction basé sur le score :
        - score au seuil (60 BUY / 40 SELL)  → ~30% de la taille max
        - score à 80                           → ~72% de la taille max
        - score à 100 ou 0                     → 100% de la taille max
        """
        # Kelly fraction = (win_rate * rr - (1 - win_rate)) / rr
        kelly = (win_rate * rr_ratio - (1 - win_rate)) / rr_ratio
        kelly = max(0.0, min(kelly, self.kelly_max))

        # Taille maximale selon pos_size_pct
        max_size = self.capital * (self.pos_size_pct / 100)
        size = self.capital * kelly
        base_size = min(size, max_size)

        # Multiplicateur de conviction : conviction faible → petite position
        # Formule : 0.3 + 0.7 * (|score - 50| / 50), clampé entre 0.3 et 1.0
        conviction = abs(score - 50.0) / 50.0          # 0.0 (neutre) → 1.0 (extrême)
        conviction_mult = max(0.3, min(1.0, 0.3 + 0.7 * conviction))
        final_size = round(base_size * conviction_mult, 2)

        logger.debug(
            f"Position size: base=${base_size:.0f} × conviction_mult={conviction_mult:.2f}"
            f" (score={score:.0f}) → ${final_size:.0f}"
        )
        return final_size

    def calculate_sl_tp(
        self, entry_price: float, action: str, atr: float
    ) -> tuple[float, float]:
        """Calcule SL et TP basés sur l'ATR."""
        atr = max(atr, entry_price * 0.001)  # ATR minimum de 0.1%

        if action == "BUY":
            sl = entry_price - (atr * self.atr_sl_mult)
            tp = entry_price + (atr * self.atr_tp_mult)
        elif action == "SELL":
            sl = entry_price + (atr * self.atr_sl_mult)
            tp = entry_price - (atr * self.atr_tp_mult)
        else:
            sl = tp = entry_price

        return round(sl, 2), round(tp, 2)


# ===========================================================
# DECISION ENGINE
# ===========================================================

class DecisionEngine:
    """Prend la décision finale et génère l'explication narrative."""

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        risk = cfg.get("risk", {})
        self.buy_threshold: float = risk.get("buy_threshold", 70)
        self.exit_threshold: float = risk.get("exit_threshold", 52)  # seuil de sortie d'une position longue
        self.human_loop: bool = risk.get("human_in_the_loop", False)
        self.ma50_filter_mode: str = risk.get("ma50_filter_mode", "gradual")
        self.ma50_strong_threshold: float = risk.get("ma50_strong_signal_threshold", 80)
        self.ma50_size_factor: float = risk.get("ma50_gradual_size_factor", 0.5)
        self.max_open_positions: int = int(risk.get("max_open_positions", 0))
        self.risk_engine = RiskEngine()

    def decide(
        self,
        score: float,
        market_indicators: dict | None,
        agent_analyses: dict,
        mirofish_result: dict | None,
    ) -> dict:
        """Génère la décision de trading complète."""
        # --- Logique position-aware (long-only spot) ---
        # Si une position longue (BUY) est ouverte : gérer la sortie
        # Sinon : chercher une entrée
        _open_buys: list[dict] = []
        try:
            from storage.database import get_open_positions
            _open_buys = [p for p in get_open_positions() if p["action"] == "BUY"]
        except Exception:
            pass

        has_long = len(_open_buys) > 0

        if has_long:
            # Position ouverte → sortir si le score chute sous exit_threshold
            if score < self.exit_threshold:
                action = "SELL"
                logger.info(
                    f"Exit signal: score {score:.0f} < exit_threshold {self.exit_threshold:.0f} "
                    f"— SELL pour clore {len(_open_buys)} position(s) longue(s)"
                )
            else:
                action = "HOLD"
        else:
            # Pas de position → entrer si score suffisant
            if score >= self.buy_threshold:
                action = "BUY"
            else:
                action = "HOLD"

        # Cap max_open_positions (garde-fou supplémentaire sur BUY)
        if action == "BUY" and self.max_open_positions > 0:
            try:
                from storage.database import count_open_positions
                n_open = count_open_positions()
                if n_open >= self.max_open_positions:
                    logger.info(
                        f"Max positions atteint ({n_open}/{self.max_open_positions}) — BUY converti en HOLD"
                    )
                    action = "HOLD"
            except Exception:
                pass

        price = (market_indicators or {}).get("price", 0.0)
        atr = (market_indicators or {}).get("atr_14", price * 0.02)

        # --- Filtre tendance MA50 ---
        above_ma50 = (market_indicators or {}).get("above_ma50", True)
        ma_50 = (market_indicators or {}).get("ma_50", 0.0)
        ma50_blocked = False
        ma50_size_penalty = 1.0  # multiplicateur appliqué à position_size

        if action == "BUY" and not above_ma50 and ma_50 > 0:
            if self.ma50_filter_mode == "block":
                # Blocage total
                logger.info(
                    f"MA50 filter [block]: BUY bloqué — prix {price:.0f} < MA50 {ma_50:.0f}"
                )
                action = "HOLD"
                ma50_blocked = True
            elif self.ma50_filter_mode == "gradual":
                if score < self.ma50_strong_threshold:
                    # Signal insuffisant → bloqué
                    logger.info(
                        f"MA50 filter [gradual]: BUY bloqué — score {score:.0f} < {self.ma50_strong_threshold} "
                        f"et prix {price:.0f} < MA50 {ma_50:.0f}"
                    )
                    action = "HOLD"
                    ma50_blocked = True
                else:
                    # Signal fort → autorisé avec taille réduite
                    ma50_size_penalty = self.ma50_size_factor
                    logger.info(
                        f"MA50 filter [gradual]: BUY autorisé (score {score:.0f} ≥ {self.ma50_strong_threshold}) "
                        f"mais taille ×{ma50_size_penalty:.1f} (prix sous MA50)"
                    )
            # mode "off" → aucun filtre

        # Sizing et SL/TP seulement si BUY/SELL
        if action in ("BUY", "SELL"):
            position_size = round(
                self.risk_engine.calculate_position_size(price, score=score) * ma50_size_penalty, 2
            )
            sl, tp = self.risk_engine.calculate_sl_tp(price, action, atr)
        else:
            position_size = 0.0
            sl = tp = price

        # Génération de l'explication
        explanation = self._build_explanation(
            action, score, agent_analyses, mirofish_result, market_indicators,
            ma50_blocked=ma50_blocked, ma_50=ma_50, ma50_size_penalty=ma50_size_penalty
        )

        risks = self._extract_risks(agent_analyses)
        catalysts = self._extract_catalysts(agent_analyses)

        return {
            "action": action,
            "score": score,
            "position_size_usd": position_size,
            "entry_price": price,
            "sl_price": sl,
            "tp_price": tp,
            "explanation": explanation,
            "risks": risks,
            "catalysts": catalysts,
            "approved": not self.human_loop,
            "ma50_blocked": ma50_blocked,
            "ma50_size_penalty": ma50_size_penalty,
            "ma_50": ma_50,
            "above_ma50": above_ma50,
        }

    def _build_explanation(
        self,
        action: str,
        score: float,
        agent_analyses: dict,
        mirofish_result: dict | None,
        market_indicators: dict | None,
        ma50_blocked: bool = False,
        ma_50: float = 0.0,
        ma50_size_penalty: float = 1.0,
    ) -> str:
        """Construit l'explication narrative de la décision."""
        mf_score = (mirofish_result or {}).get("score", 50)
        mf_narrative = (mirofish_result or {}).get("dominant_narrative", "n/a")
        price = (market_indicators or {}).get("price", 0)
        rsi = (market_indicators or {}).get("rsi_14", 50)

        synthesis = agent_analyses.get("synthesis", {})
        synthesis_text = synthesis.get("summary", "") if isinstance(synthesis, dict) else ""

        explanation = (
            f"**Decision: {action}** (conviction score: {score:.0f}/100)\n\n"
            f"**MiroFish Analysis** ({mf_score:.0f}/100): {mf_narrative}\n\n"
        )

        # Agent scores
        agent_rows = []
        signal_icons = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}
        for name, analysis in agent_analyses.items():
            if name == "synthesis" or not isinstance(analysis, dict):
                continue
            a_score = analysis.get("score", 50)
            a_signal = analysis.get("signal", "NEUTRAL")
            icon = signal_icons.get(a_signal, "⚪")
            agent_rows.append(f"{icon} **{name}**: {a_score:.0f}/100")
        if agent_rows:
            explanation += "**Agents**: " + " | ".join(agent_rows) + "\n\n"

        rsi_label = "oversold" if rsi < 30 else ("overbought" if rsi > 70 else "neutral")
        explanation += (
            f"**Market**: Price={price:.2f} | RSI={rsi:.0f} ({rsi_label})\n\n"
        )

        if synthesis_text:
            explanation += f"**AI Summary**: {synthesis_text}\n\n"

        if action == "HOLD" and ma50_blocked:
            explanation += (
                f"⚠️ **MA50 Filter active**: score={score:.0f} bullish but price ({price:.0f}) "
                f"is below daily MA50 ({ma_50:.0f}). BUY blocked — bearish macro trend."
            )
        elif action == "BUY" and ma50_size_penalty < 1.0:
            explanation += (
                f"⚠️ **Strong signal below MA50**: score={score:.0f} \u2265 strong threshold. "
                f"BUY allowed but size reduced \u00d7{ma50_size_penalty:.1f} "
                f"(price {price:.0f} below MA50 {ma_50:.0f})."
            )
        elif action == "HOLD":
            explanation += (
                f"Score {score:.0f} is within the neutral zone "
                f"[{self.exit_threshold}\u2013{self.buy_threshold}]. Monitoring maintained."
            )
        elif action == "BUY":
            explanation += (
                f"Signals converge toward bullish sentiment. "
                f"High conviction score ({score:.0f}/100) above buy threshold ({self.buy_threshold})."
            )
        else:
            explanation += (
                f"Signals indicate bearish pressure. "
                f"Conviction score ({score:.0f}/100) below exit threshold "
                f"({self.exit_threshold}) \u2014 long position closed."
            )

        return explanation

    def _extract_risks(self, agent_analyses: dict) -> list[str]:
        synthesis = agent_analyses.get("synthesis", {})
        if isinstance(synthesis, dict):
            return synthesis.get("risks", [])[:3]
        return []

    def _extract_catalysts(self, agent_analyses: dict) -> list[str]:
        synthesis = agent_analyses.get("synthesis", {})
        if isinstance(synthesis, dict):
            return synthesis.get("catalysts", [])[:3]
        return []
