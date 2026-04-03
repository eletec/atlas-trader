"""
agents/mirofish_wrapper.py — Wrapper autour du repo MiroFish
Interface abstraite + fallback si le repo n'est pas installé.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from typing import Any

logger = logging.getLogger("zeitgeist.mirofish")


class MiroFishWrapper:
    """
    Encapsule la simulation swarm MiroFish.
    Essaie d'importer le repo officiel ; si indisponible, utilise un simulateur
    de fallback déterministe basé sur l'analyse du seed texte.
    """

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        mf = cfg.get("mirofish", {})
        self.n_agents: int = mf.get("n_agents", 5000)
        self.n_steps: int = mf.get("n_steps", 100)
        self.seed_news_weight: float = mf.get("seed_news_weight", 0.6)
        self.air_du_temps_weight: float = mf.get("air_du_temps_weight", 0.4)
        self.timeout: int = mf.get("timeout_seconds", 120)
        self._mirofish_available = self._check_mirofish()

    def _check_mirofish(self) -> bool:
        """Vérifie si MiroFish est installé."""
        try:
            import mirofish  # noqa: F401
            logger.info("MiroFish disponible (repo officiel)")
            return True
        except ImportError:
            logger.warning(
                "MiroFish non installé. "
                "Installer via : pip install git+https://github.com/666ghj/MiroFish.git\n"
                "Utilisation du simulateur de fallback."
            )
            return False

    def prepare_seed(
        self,
        news_items: list[dict],
        air_du_temps: dict | None
    ) -> str:
        """
        Construit le texte seed pour la simulation.
        Mélange news récentes et AirDuTemps selon les poids configurés.
        """
        parts = []

        # Contribution news
        if news_items:
            news_text = "\n".join([
                f"- {item.get('title', '')} ({item.get('source', '')})"
                for item in news_items[:15]
            ])
            parts.append(f"[NEWS RÉCENTES — poids {self.seed_news_weight:.0%}]\n{news_text}")

        # Contribution Air du Temps
        if air_du_temps:
            adt_text = air_du_temps.get("full_text", "")[:1000]
            themes = ", ".join(air_du_temps.get("themes", []))
            parts.append(
                f"[AIR DU TEMPS — poids {self.air_du_temps_weight:.0%}]\n"
                f"Thèmes : {themes}\n{adt_text}"
            )

        seed = "\n\n".join(parts) if parts else "Neutral context — insufficient data"
        logger.debug(f"Seed préparé ({len(seed)} chars)")
        return seed

    def run_simulation(self, seed: str) -> dict:
        """
        Lance la simulation et retourne un MiroFishResult.
        Utilise le vrai MiroFish si disponible, sinon le fallback.
        """
        if self._mirofish_available:
            return self._run_official(seed)
        return self._run_fallback(seed)

    def _run_official(self, seed: str) -> dict:
        """Appelle le repo officiel MiroFish."""
        try:
            import mirofish
            result = mirofish.simulate(
                context=seed,
                n_agents=self.n_agents,
                n_steps=self.n_steps,
            )
            return self._parse_official_result(result)
        except Exception as exc:
            logger.error(f"Erreur MiroFish officiel: {exc}")
            return self._run_fallback(seed)

    def _parse_official_result(self, raw: Any) -> dict:
        """Parse le résultat brut du repo officiel."""
        # Adapter selon l'API réelle du repo
        if isinstance(raw, dict):
            score = float(raw.get("score", raw.get("bull_score", 50)))
            narratives = raw.get("narratives", raw.get("stories", []))
            probas = raw.get("probabilities", raw.get("probas", {}))
        else:
            score = 50.0
            narratives = []
            probas = {}

        probas = {
            "bull": probas.get("bull", probas.get("bullish", 0.33)),
            "bear": probas.get("bear", probas.get("bearish", 0.33)),
            "neutral": probas.get("neutral", 0.34),
        }

        return {
            "score": max(0.0, min(100.0, score)),
            "probas": probas,
            "narratives": narratives[:5] if narratives else [],
            "dominant_narrative": narratives[0] if narratives else "indisponible",
            "n_agents_used": self.n_agents,
        }

    def _run_fallback(self, seed: str) -> dict:
        """
        Simulateur de fallback simple basé sur l'analyse sémantique du seed.
        Déterministe pour reproductibilité (seed → hash → score).
        """
        import hashlib

        # Mots bullish vs bearish pour scoring simple
        bullish_words = [
            "hausse", "bull", "growth", "adoption", "institutional", "upgrade",
            "positive", "rally", "breakout", "buy", "support", "record",
            "optimisM", "recovery", "pump", "ath", "momentum"
        ]
        bearish_words = [
            "baisse", "bear", "crash", "ban", "regulation", "sell", "dump",
            "fear", "panic", "risk", "inflation", "recession", "hack",
            "liquidation", "breakdown", "correction", "volatile"
        ]

        seed_lower = seed.lower()
        bull_count = sum(1 for w in bullish_words if w in seed_lower)
        bear_count = sum(1 for w in bearish_words if w in seed_lower)
        total = bull_count + bear_count + 1

        # Score basé sur ratio mots haussiers
        raw_score = 50 + (bull_count - bear_count) / total * 30

        # Ajout de bruit déterministe basé sur le hash du seed
        seed_hash = int(hashlib.md5(seed[:200].encode()).hexdigest(), 16)
        noise = ((seed_hash % 100) - 50) * 0.1
        score = max(5.0, min(95.0, raw_score + noise))

        bull_proba = score / 100
        bear_proba = max(0, (100 - score - 10) / 100)
        neutral_proba = max(0, 1 - bull_proba - bear_proba)

        narratives = [
            f"Signal {'bullish' if score > 55 else 'bearish' if score < 45 else 'neutral'} "
            f"detected in context (degraded mode — MiroFish not installed)",
            f"{bull_count} positive signals vs {bear_count} negative signals identified",
        ]

        logger.debug(f"Fallback MiroFish: score={score:.1f} bull={bull_proba:.0%}")

        return {
            "score": round(score, 2),
            "probas": {
                "bull": round(bull_proba, 3),
                "bear": round(bear_proba, 3),
                "neutral": round(neutral_proba, 3),
            },
            "narratives": narratives,
            "dominant_narrative": narratives[0],
            "n_agents_used": 0,  # 0 indique le mode fallback
        }
