"""
agents/post_mortem_agent.py — Analyse rétrospective et ajustement des poids.
"""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger("zeitgeist.post_mortem")


class PostMortemAgent:
    """
    Analyse les décisions passées, compare prédiction vs résultat,
    et propose des ajustements de poids pour les prochains cycles.
    """

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        pm = cfg.get("post_mortem", {})
        self.learning_rate: float = pm.get("learning_rate", 0.05)
        self.min_history: int = pm.get("min_history_for_adjustment", 10)
        self.weight_min: float = cfg.get("scoring", {}).get("min_weight", 0.05)
        self.weight_max: float = cfg.get("scoring", {}).get("max_weight", 0.60)

    def run(self, pending_decisions: list[dict]) -> None:
        """
        Pour chaque décision en attente :
        1. Récupère le prix 24h plus tard
        2. Calcule le résultat réel
        3. Met à jour la DB
        4. Si assez d'historique, ajuste les poids
        """
        from utils.logger import log_flux_metric

        logger.info(f"Post-mortem : analyse de {len(pending_decisions)} décisions")
        t0 = time.time()
        try:
            for decision in pending_decisions:
                self._process_single(decision)

            # Ajustement des poids si assez d'historique
            self._maybe_adjust_weights()

            latency_ms = int((time.time() - t0) * 1000)
            log_flux_metric("post_mortem", "ok", latency_ms, len(pending_decisions))
        except Exception as exc:
            latency_ms = int((time.time() - t0) * 1000)
            log_flux_metric("post_mortem", "error", latency_ms, 0, str(exc))
            raise

    def _process_single(self, decision: dict) -> None:
        """Calcule le résultat réel d'une décision et l'enregistre."""
        from storage.database import update_decision_result
        try:
            cycle_id = decision["cycle_id"]
            action = decision.get("action", "HOLD")
            entry_price = decision.get("entry_price", 0) or 0

            if action == "HOLD" or entry_price == 0:
                update_decision_result(cycle_id, 0.0)
                return

            # Prix actuel via market data
            current_price = self._get_current_price(decision.get("asset", "BTC/USDT"))
            position_size = decision.get("position_size", 0) or 0

            if current_price and entry_price:
                price_change_pct = (current_price - entry_price) / entry_price
                direction = 1 if action == "BUY" else -1
                pnl = position_size * price_change_pct * direction
            else:
                pnl = 0.0

            update_decision_result(cycle_id, round(pnl, 2))
            logger.info(
                f"Post-mortem {cycle_id}: {action} entry={entry_price:.2f} "
                f"current={current_price:.2f} P&L={pnl:.2f}$"
            )
        except Exception as exc:
            logger.error(f"Erreur post-mortem décision {decision.get('cycle_id')}: {exc}")

    def _get_current_price(self, asset: str) -> float:
        """Récupère le prix actuel via CCXT."""
        try:
            from agents.market_data_agent import MarketDataAgent
            agent = MarketDataAgent()
            indicators = agent.get_indicators(asset)
            return indicators.get("price", 0)
        except Exception:
            return 0.0

    def _maybe_adjust_weights(self) -> None:
        """Ajuste les poids de scoring si assez d'historique disponible."""
        from storage.database import get_pnl_history
        from utils.config import load_settings, save_settings

        history = [h for h in get_pnl_history() if h.get("result_24h") is not None]
        if len(history) < self.min_history:
            logger.info(
                f"Post-mortem : {len(history)}/{self.min_history} décisions — "
                f"ajustement des poids reporté"
            )
            return

        # Analyse des dernières N décisions
        recent = history[-self.min_history:]
        wins = [h for h in recent if (h.get("result_24h") or 0) > 0]
        win_rate = len(wins) / len(recent)

        logger.info(
            f"Post-mortem : win_rate={win_rate:.0%} sur {len(recent)} décisions"
        )

        # Ajustement simple basé sur le win_rate
        # Si win_rate > 60% → légèrement augmenter MiroFish (signal de qualité)
        # Si win_rate < 40% → légèrement diminuer MiroFish
        cfg = load_settings()
        weights = cfg.get("scoring", {}).get("weights", {})

        delta = (win_rate - 0.50) * self.learning_rate
        mf_new = weights.get("mirofish", 0.40) + delta
        market_new = weights.get("market", 0.30) - delta / 2
        agents_new = weights.get("agents", 0.20) - delta / 2

        # Borner les poids
        mf_new = max(self.weight_min, min(self.weight_max, mf_new))
        market_new = max(self.weight_min, min(self.weight_max, market_new))
        agents_new = max(self.weight_min, min(self.weight_max, agents_new))

        # Normaliser pour que la somme reste 1
        total = mf_new + market_new + agents_new + weights.get("contrarian", 0.10)
        mf_new /= total
        market_new /= total
        agents_new /= total
        contrarian_new = weights.get("contrarian", 0.10) / total

        cfg["scoring"]["weights"] = {
            "mirofish": round(mf_new, 4),
            "market": round(market_new, 4),
            "agents": round(agents_new, 4),
            "contrarian": round(contrarian_new, 4),
        }
        save_settings(cfg)
        logger.info(
            f"Post-mortem : poids mis à jour → "
            f"mirofish={mf_new:.3f} market={market_new:.3f} "
            f"agents={agents_new:.3f} contrarian={contrarian_new:.3f}"
        )
