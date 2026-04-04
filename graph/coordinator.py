"""
graph/coordinator.py — CA6 : Coordinateur multi-agents Claude

Le CoordinatorAgent reçoit les résultats de tous les agents d'analyse et
demande à Claude (Haiku) de les pondérer dynamiquement avant la synthèse
finale. Il peut aussi marquer certains agents comme "outliers" à ignorer.

Activation via settings.yaml :
    agents:
        coordinator:
            enabled: true
            model: "claude-3-5-haiku-20241022"
            max_tokens: 512

Entré  : state["agent_analyses"] — dict {agent_name: AgentAnalysis}
Sortie : state["agent_analyses"]["coordinator_meta"] — dict de pondérations suggérées
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("zeitgeist.coordinator")

_SYSTEM_PROMPT = (
    "Tu es le coordinateur d'Atlas Trader. "
    "Tu reçois les analyses de plusieurs agents spécialisés et tu dois : "
    "1) identifier les agents qui semblent cohérents entre eux, "
    "2) identifier les outliers potentiels, "
    "3) proposer des poids dynamiques (float 0.0-1.0, somme ≈ 1.0). "
    "Réponds UNIQUEMENT en JSON valide (sans markdown) avec les clés : "
    "weights (dict agent_name → float), outliers (list[str]), "
    "reasoning (str ≤ 200 chars), consensus_signal (BULLISH|BEARISH|NEUTRAL)."
)


class CoordinatorAgent:
    """
    Coordinateur LLM léger — pondère dynamiquement les agents d'analyse
    avant la synthèse finale. N'exécute pas d'agents lui-même.
    """

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        coord_cfg = cfg.get("agents", {}).get("coordinator", {})
        llm_cfg = cfg.get("llm", {})
        self.enabled: bool = coord_cfg.get("enabled", False)
        self.model: str = coord_cfg.get("model", llm_cfg.get("haiku_model", "claude-3-5-haiku-20241022"))
        self.max_tokens: int = coord_cfg.get("max_tokens", 512)
        self.provider: str = llm_cfg.get("provider", "anthropic")

    def coordinate(self, agent_analyses: dict[str, Any]) -> dict:
        """
        Analyse les résultats des agents et retourne des méta-données de coordination.

        Args:
            agent_analyses: dict {agent_name: {score, signal, summary, confidence}}

        Returns:
            dict with keys: weights, outliers, reasoning, consensus_signal
        """
        if not self.enabled:
            return {}

        # Filtrer les analyses valides (market_regime est info-seulement, pas pondéré)
        META_KEYS = {"synthesis", "synthesis_agentic", "coordinator_meta", "market_regime"}
        valid = {
            name: v for name, v in agent_analyses.items()
            if isinstance(v, dict) and name not in META_KEYS
        }
        if len(valid) < 2:
            return {}

        # Contexte de régime (optionnel — enrichit le prompt sans poids)
        regime_info = agent_analyses.get("market_regime", {})
        prompt_text = self._build_prompt(valid, regime_info)

        try:
            if self.provider == "anthropic":
                raw = self._call_anthropic(prompt_text)
            else:
                raw = self._call_openai_compatible(prompt_text)
            result = self._parse_json(raw)
            if result:
                logger.info(
                    "[Coordinator] consensus=%s outliers=%s",
                    result.get("consensus_signal", "?"),
                    result.get("outliers", []),
                )
            return result
        except Exception as exc:
            logger.warning("[Coordinator] LLM échoué (%s) — coordination ignorée", exc)
            return {}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(valid: dict[str, Any], regime_info: dict | None = None) -> str:
        lines = []

        # Contexte de régime de marché (si disponible)
        if regime_info and isinstance(regime_info, dict):
            regime = regime_info.get("regime", "UNKNOWN")
            hmm_label = regime_info.get("hmm_state_label", "?")
            transition = regime_info.get("transition_prob", 0.0)
            lines += [
                f"Régime de marché détecté : {regime} "
                f"(HMM : {hmm_label}, prob_transition={transition:.0%})",
                "Consignes d'ajustement des poids selon le régime :",
                "  TRENDING_UP/DOWN → ↑timesfm ↑contrarian ↓fear_greed",
                "  SIDEWAYS         → ↑fear_greed ↓timesfm ↓contrarian",
                "  HIGH_VOLATILITY  → réduis tous les poids extremes, privilégie la prudence",
                "",
            ]

        lines.append("Résultats des agents (score 0-100, signal, résumé) :\n")
        for name, v in valid.items():
            lines.append(
                f"• {name}: score={v.get('score', 50):.0f} "
                f"signal={v.get('signal', 'N/A')} "
                f"confiance={v.get('confidence', 0):.2f} "
                f"— {v.get('summary', '')[:80]}"
            )
        lines.append(
            "\nPropose des poids dynamiques et identifie les outliers. "
            "Retourne un JSON strict."
        )
        return "\n".join(lines)

    def _call_anthropic(self, prompt: str) -> str:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else "{}"

    def _call_openai_compatible(self, prompt: str) -> str:
        from openai import OpenAI
        from utils.config import get_env
        base_url = get_env("OPENAI_BASE_URL", "https://api.openai.com/v1")
        api_key = get_env("OPENAI_API_KEY", "")
        client = OpenAI(base_url=base_url, api_key=api_key)
        response = client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content if response.choices else "{}"

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rstrip("`").strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end])
            except json.JSONDecodeError:
                pass
        return {}
