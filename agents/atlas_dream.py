"""
agents/atlas_dream.py — CA5 : Service AtlasDream de consolidation mémorielle

Tous les N cycles évalués, envoie les 50 dernières décisions à Claude (Haiku)
pour en extraire des insights stratégiques persistants.
Ces insights sont sauvegardés dans storage/dream_insights.json et injectés
dans le prompt du cycle suivant via le state["dream_context"].

Activation : settings.yaml > atlas_dream.enabled: true
Fréquence   : settings.yaml > atlas_dream.consolidate_every_n: 50
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("zeitgeist.atlas_dream")

_DREAM_PATH = Path(__file__).resolve().parent.parent / "storage" / "dream_insights.json"
_DREAM_PATH.parent.mkdir(parents=True, exist_ok=True)

_SYSTEM_PROMPT = (
    "You are the strategic brain of Atlas Trader. "
    "Analyze the provided trading history and identify: "
    "1) recurring success patterns, "
    "2) systematic errors, "
    "3) market conditions to avoid, "
    "4) concrete recommendations for upcoming cycles. "
    "Respond ONLY in valid JSON (no markdown) with keys: "
    "success_patterns (list[str]), recurring_errors (list[str]), "
    "market_conditions_to_avoid (list[str]), recommendations (list[str]), "
    "overall_assessment (str ≤ 200 chars), confidence (float 0-1)."
)


class AtlasDreamService:
    """
    Service de consolidation mémorielle — analyse périodique de l'historique
    des décisions pour générer des insights stratégiques persistants.
    """

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        dream_cfg = cfg.get("atlas_dream", {})
        self.enabled: bool = dream_cfg.get("enabled", True)
        self.consolidate_every_n: int = dream_cfg.get("consolidate_every_n", 50)
        self.max_decisions: int = dream_cfg.get("max_decisions", 50)

        llm_cfg = cfg.get("llm", {})
        self.model: str = llm_cfg.get("haiku_model", "claude-3-5-haiku-20241022")
        self.provider: str = llm_cfg.get("provider", "anthropic")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def maybe_consolidate(self, n_evaluated: int) -> dict | None:
        """
        Appelé par PostMortemAgent après chaque évaluation.
        Déclenche la consolidation si n_evaluated est un multiple de consolidate_every_n.
        Retourne les insights ou None si pas de consolidation.
        """
        if not self.enabled:
            return None
        if n_evaluated == 0 or (n_evaluated % self.consolidate_every_n) != 0:
            return None
        logger.info("[AtlasDream] Déclenchement consolidation (n_evaluated=%d)", n_evaluated)
        return self.consolidate()

    def consolidate(self) -> dict:
        """
        Génère de nouveaux insights à partir de l'historique récent et les persiste.
        Retourne le dict d'insights (ou le dernier connu en cas d'erreur).
        """
        from storage.database import get_recent_decisions

        history = get_recent_decisions(self.max_decisions)
        if len(history) < 5:
            logger.info("[AtlasDream] Historique trop court (%d décisions)", len(history))
            return self._load_insights()

        history_text = self._format_history(history)
        try:
            insights = self._call_llm(history_text)
        except Exception as exc:
            logger.warning("[AtlasDream] LLM échoué (%s) — conservation des insights précédents", exc)
            return self._load_insights()

        self._save_insights(insights, n_decisions=len(history))
        logger.info("[AtlasDream] Insights mis à jour (%d décisions analysées)", len(history))
        return insights

    def load_context_snippet(self, max_chars: int = 600) -> str:
        """
        Retourne un extrait des insights à injecter dans les prompts LLM.
        Utilisé par DecisionEngine / SynthesisAgent pour enrichir le contexte.
        """
        insights = self._load_insights()
        if not insights:
            return ""
        parts = []
        for rec in insights.get("recommendations", [])[:3]:
            parts.append(f"• {rec}")
        assessment = insights.get("overall_assessment", "")
        if assessment:
            parts.insert(0, f"[Mémoire Atlas] {assessment}")
        snippet = "\n".join(parts)
        return snippet[:max_chars]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm(self, history_text: str) -> dict:
        if self.provider == "anthropic":
            return self._call_anthropic(history_text)
        return self._call_openai_compatible(history_text)

    def _call_anthropic(self, history_text: str) -> dict:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": history_text}],
        )
        raw = response.content[0].text if response.content else "{}"
        return self._parse_json(raw)

    def _call_openai_compatible(self, history_text: str) -> dict:
        from openai import OpenAI
        from utils.config import get_env
        base_url = get_env("OPENAI_BASE_URL", "https://api.openai.com/v1")
        api_key = get_env("OPENAI_API_KEY", "")
        client = OpenAI(base_url=base_url, api_key=api_key)
        response = client.chat.completions.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": history_text},
            ],
        )
        raw = response.choices[0].message.content if response.choices else "{}"
        return self._parse_json(raw)

    @staticmethod
    def _format_history(history: list[dict]) -> str:
        lines = ["Historique des 50 dernières décisions de trading :\n"]
        for d in history:
            result = d.get("result_24h")
            result_str = f"{result:+.2f}%" if result is not None else "en attente"
            lines.append(
                f"[{d.get('timestamp', '')[:10]}] "
                f"Action={d.get('action', 'N/A')} "
                f"Score={d.get('score', 0):.0f}/100 "
                f"Résultat={result_str} "
                f"Signal={d.get('signal', 'N/A')}"
            )
        return "\n".join(lines)

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
        logger.warning("[AtlasDream] Impossible de parser le JSON LLM")
        return {}

    def _save_insights(self, insights: dict, n_decisions: int) -> None:
        data = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "n_decisions_analyzed": n_decisions,
            "insights": insights,
        }
        try:
            _DREAM_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.error("[AtlasDream] Impossible d'écrire dream_insights.json : %s", exc)

    @staticmethod
    def _load_insights() -> dict:
        if not _DREAM_PATH.exists():
            return {}
        try:
            data = json.loads(_DREAM_PATH.read_text(encoding="utf-8"))
            return data.get("insights", {})
        except (OSError, json.JSONDecodeError):
            return {}
