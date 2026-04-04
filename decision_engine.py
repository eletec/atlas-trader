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
        mirofish_n_agents: int = 0,
    ) -> tuple[float, dict]:
        """
        Calcule le score global pondéré.

        Si MiroFish tourne en mode fallback lexical (n_agents_used < 500),
        son poids est réduit à 12 % et les poids restants sont renormalisés.
        Cela évite qu'un score lexical naïf (~50) écrase les signaux forts.

        Returns:
            score: float [0-100]
            breakdown: dict — contribution de chaque composant
        """
        # Poids MiroFish adaptatif
        _MIROFISH_FALLBACK_WEIGHT = 0.12
        if mirofish_n_agents < 500 and self.weights.mirofish > _MIROFISH_FALLBACK_WEIGHT:
            # Réduire MiroFish et redistribuer le delta sur market + agents
            delta = self.weights.mirofish - _MIROFISH_FALLBACK_WEIGHT
            w_mf = _MIROFISH_FALLBACK_WEIGHT
            remaining = self.weights.market + self.weights.agents + self.weights.contrarian
            w_mkt = self.weights.market  + delta * (self.weights.market  / remaining)
            w_agt = self.weights.agents  + delta * (self.weights.agents  / remaining)
            w_ctr = self.weights.contrarian + delta * (self.weights.contrarian / remaining)
            logger.info(
                f"MiroFish fallback (n_agents={mirofish_n_agents}) — poids réduit "
                f"{self.weights.mirofish:.0%}→{w_mf:.0%}, "
                f"market {self.weights.market:.0%}→{w_mkt:.0%}"
            )
        else:
            w_mf, w_mkt, w_agt, w_ctr = (
                self.weights.mirofish, self.weights.market,
                self.weights.agents, self.weights.contrarian,
            )

        # Score moyen des agents (hors contrarian)
        agents_mean = (
            sum(agent_scores.values()) / len(agent_scores)
            if agent_scores else 50.0
        )

        weighted_score = (
            mirofish_score * w_mf
            + market_score * w_mkt
            + agents_mean * w_agt
            + contrarian_score * w_ctr
        )

        score = max(0.0, min(100.0, weighted_score))

        breakdown = {
            "mirofish": {"score": mirofish_score, "weight": w_mf,
                         "contribution": round(mirofish_score * w_mf, 2),
                         "fallback_mode": mirofish_n_agents < 500},
            "market": {"score": market_score, "weight": w_mkt,
                       "contribution": round(market_score * w_mkt, 2)},
            "agents": {"score": agents_mean, "weight": w_agt,
                       "contribution": round(agents_mean * w_agt, 2),
                       "detail": agent_scores},
            "contrarian": {"score": contrarian_score, "weight": w_ctr,
                           "contribution": round(contrarian_score * w_ctr, 2)},
            "final_score": round(score, 2),
        }

        logger.debug(
            f"Score: {score:.1f} "
            f"(MF={mirofish_score:.0f}×{w_mf:.2f} "
            f"+ MKT={market_score:.0f}×{w_mkt:.2f} "
            f"+ AGT={agents_mean:.0f}×{w_agt:.2f} "
            f"+ CTR={contrarian_score:.0f}×{w_ctr:.2f})"
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

    def is_circuit_breaker_active(self, market_indicators: dict | None = None) -> bool:
        """Vérifie uniquement le drawdown maximal (circuit breaker dur).
        Pour le funding, utiliser check_funding_circuit_breaker() qui retourne un multiplier graduel.
        """
        try:
            from storage.database import get_pnl_history
            history = get_pnl_history()
            if history:
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

    def check_funding_circuit_breaker(
        self, market_indicators: dict | None = None, regime: str | None = None
    ) -> tuple[bool, str, float]:
        """
        Évalue le risque de sur-levier via le funding rate.

        Retourne:
            blocked   : bool   — True = ne pas ouvrir de nouveau BUY
            reason    : str    — explication pour les logs / SynthesisAgent
            size_mult : float  — multiplicateur à appliquer sur la taille de position (0.0–1.0)

        Trois niveaux :
          funding < warning  → normal, taille 100%
          warning ≤ funding < block → réduction progressive jusqu'à max_reduction
          funding ≥ block (soutenu sur sustain_cycles) → blocage total
          funding très négatif → signal contrarian LONG (noté dans reason)

        En régime HIGH_VOLATILITY le seuil de blocage est abaissé de 0.045 % → 0.035 %
        pour protéger davantage lors des périodes de haute volatilité.
        """
        from utils.config import load_settings
        cfg = load_settings().get("circuit_breaker", {})

        f_warning  = float(cfg.get("funding_warning",  0.00018))  # 0.018 %
        f_block    = float(cfg.get("funding_block",    0.00045))  # 0.045 %
        sustain    = int(cfg.get("sustain_period_cycles", 3))
        max_reduc  = float(cfg.get("max_reduction", 0.75))

        # Seuil plus strict en HIGH_VOLATILITY (0.045 % → 0.035 %)
        if regime == "HIGH_VOLATILITY":
            f_block = min(f_block, 0.00035)
            logger.debug(f"[FundingCB] HIGH_VOLATILITY — f_block abaissé à {f_block:.4%}")

        ind = market_indicators or {}
        current_funding = float(ind.get("funding_rate", 0.0) or 0.0)

        # Historique récent (liste des N dernières valeurs collectées par MarketDataAgent)
        recent = list(ind.get("recent_funding_rates") or [current_funding])
        if not recent:
            recent = [current_funding]

        # Moyenne sur les derniers `sustain` cycles — filtre les pics isolés
        window = recent[-sustain:] if len(recent) >= sustain else recent
        avg_funding = sum(window) / len(window)

        reason = ""
        size_mult = 1.0
        blocked = False

        if avg_funding >= f_block:
            # Blocage dur uniquement si soutenu (avg sur sustain cycles)
            blocked = True
            size_mult = 0.0
            reason = (
                f"EXTREME_LONG_OVERLEVERAGE: funding moyen={avg_funding:.4%} "
                f">= seuil blocage {f_block:.4%} (soutenu {len(window)} cycles)"
            )
            logger.warning(f"[FundingCB] Blocage BUY — {reason}")

        elif avg_funding >= f_warning:
            # Réduction progressive : linéaire entre warning et block
            excess = (avg_funding - f_warning) / max(f_block - f_warning, 1e-9)
            size_mult = max(1.0 - excess * max_reduc, 1.0 - max_reduc)
            reason = (
                f"HIGH_FUNDING_WARNING: funding moyen={avg_funding:.4%} "
                f"→ taille réduite à {size_mult:.0%}"
            )
            logger.info(f"[FundingCB] {reason}")

        else:
            reason = f"funding_normal ({avg_funding:.4%})"

        # Signal contrarian bonus : funding très négatif = shorts sur-leveragés
        if avg_funding < -0.00025:  # −0.025 %
            reason += " | EXTREME_SHORT_CROWDING (potential long squeeze)"

        return blocked, reason, size_mult

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
        # --- Funding circuit breaker (graduel) ---
        funding_blocked = False
        funding_size_mult = 1.0
        funding_reason = ""
        if action == "BUY":
            _regime = agent_analyses.get("market_regime", {}).get("regime") if agent_analyses else None
            funding_blocked, funding_reason, funding_size_mult = (
                self.risk_engine.check_funding_circuit_breaker(market_indicators, regime=_regime)
            )
            if funding_blocked:
                action = "HOLD"
                logger.info(f"Funding CB: BUY → HOLD — {funding_reason}")
            elif funding_size_mult < 1.0:
                logger.info(f"Funding CB: taille BUY ×{funding_size_mult:.2f} — {funding_reason}")

        if action in ("BUY", "SELL"):
            position_size = round(
                self.risk_engine.calculate_position_size(price, score=score)
                * ma50_size_penalty
                * funding_size_mult,
                2,
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
            "funding_blocked": funding_blocked,
            "funding_size_mult": funding_size_mult,
            "funding_reason": funding_reason,
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
        from utils.i18n import t

        mf_score = (mirofish_result or {}).get("score", 50)
        mf_narrative = (mirofish_result or {}).get("dominant_narrative", "n/a")
        price = (market_indicators or {}).get("price", 0)
        rsi = (market_indicators or {}).get("rsi_14", 50)

        synthesis = agent_analyses.get("synthesis", {})
        synthesis_text = synthesis.get("summary", "") if isinstance(synthesis, dict) else ""

        explanation = (
            f"**{t('dec_decision')}: {action}** ({t('dec_conviction')}: {score:.0f}/100)\n\n"
            f"**{t('dec_mirofish')}** ({mf_score:.0f}/100): {mf_narrative}\n\n"
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
            explanation += f"**{t('dec_agents')}**: " + " | ".join(agent_rows) + "\n\n"

        rsi_key = "dec_rsi_oversold" if rsi < 30 else ("dec_rsi_overbought" if rsi > 70 else "dec_rsi_neutral")
        explanation += (
            f"**{t('dec_market')}**: Price={price:.2f} | RSI={rsi:.0f} ({t(rsi_key)})\n\n"
        )

        if synthesis_text:
            explanation += f"**{t('dec_ai_summary')}**: {synthesis_text}\n\n"

        if action == "HOLD" and ma50_blocked:
            explanation += t("dec_ma50_blocked").format(
                score=f"{score:.0f}", price=f"{price:.0f}", ma50=f"{ma_50:.0f}"
            )
        elif action == "BUY" and ma50_size_penalty < 1.0:
            explanation += t("dec_ma50_strong").format(
                score=f"{score:.0f}", factor=f"{ma50_size_penalty:.1f}",
                price=f"{price:.0f}", ma50=f"{ma_50:.0f}"
            )
        elif action == "HOLD":
            explanation += t("dec_neutral_zone").format(
                score=f"{score:.0f}", lo=f"{self.exit_threshold:.0f}",
                hi=f"{self.buy_threshold:.0f}"
            )
        elif action == "BUY":
            explanation += t("dec_buy_signal").format(
                score=f"{score:.0f}", threshold=f"{self.buy_threshold:.0f}"
            )
        else:
            explanation += t("dec_sell_signal").format(
                score=f"{score:.0f}", threshold=f"{self.exit_threshold:.0f}"
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
