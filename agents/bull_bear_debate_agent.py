"""
agents/bull_bear_debate_agent.py — Débat structuré Haussier vs Baissier.

Deux appels LLM parallèles (Claude Haiku ou équivalent léger) :
  - BullDebater : défend le scénario haussier le plus solide
  - BearDebater : défend le scénario baissier le plus solide

Le pair de thèses est injecté dans analyses["debate"] et disponible
pour SynthesisAgent afin de nuancer le score final.

Activé via config/settings.yaml :
  agents:
    bull_bear_debate:
      enabled: true
      weight_in_scoring: 0.0   # 0 = pas de score direct, juste contexte narratif
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from typing import Any

logger = logging.getLogger("zeitgeist.debate")

_BULL_SYSTEM = (
    "You are BullDebater, a crypto analyst whose job is to defend the strongest possible "
    "bullish case for the current market situation. Be concise (3-4 sentences). "
    "Use data from the context. Do NOT mention that you are playing a role."
)
_BEAR_SYSTEM = (
    "You are BearDebater, a crypto analyst whose job to defend the strongest possible "
    "bearish case for the current market situation. Be concise (3-4 sentences). "
    "Use data from the context. Do NOT mention that you are playing a role."
)


class BullBearDebateAgent:
    """Lance un débat contradictoire haussier/baissier en parallèle."""

    TIMEOUT_S = 60

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        self._llm_cfg = cfg.get("llm", {})
        debate_cfg = cfg.get("agents", {}).get("bull_bear_debate", {})
        self._enabled = bool(debate_cfg.get("enabled", False))

    # ------------------------------------------------------------------
    # Interface principale
    # ------------------------------------------------------------------

    def analyze(self, state: dict) -> dict:
        """Point d'entrée compatible pipeline LangGraph."""
        if not self._enabled:
            return _disabled_result()

        try:
            context = self._build_context(state)
            bull_thesis, bear_thesis = self._run_parallel(context)
            summary = f"Bull: {bull_thesis[:80]}… | Bear: {bear_thesis[:80]}…"
            logger.info(f"BullBearDebate done: {summary}")
            return {
                "agent_name":   "debate",
                "score":        50.0,   # neutre — score délibérément non directif
                "signal":       "NEUTRAL",
                "summary":      summary,
                "confidence":   0.5,
                "bull_thesis":  bull_thesis,
                "bear_thesis":  bear_thesis,
            }
        except Exception as exc:
            logger.warning(f"BullBearDebateAgent error: {exc}")
            return _disabled_result(reason=str(exc))

    # ------------------------------------------------------------------
    # Parallélisme
    # ------------------------------------------------------------------

    def _run_parallel(self, context: str) -> tuple[str, str]:
        tasks = {
            "bull": (_BULL_SYSTEM, context),
            "bear": (_BEAR_SYSTEM, context),
        }
        results: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(self._call_llm, sys_prompt, ctx): side
                for side, (sys_prompt, ctx) in tasks.items()
            }
            for fut in as_completed(futures, timeout=self.TIMEOUT_S):
                side = futures[fut]
                try:
                    results[side] = fut.result(timeout=self.TIMEOUT_S)
                except (TimeoutError, Exception) as exc:
                    logger.warning(f"Debate {side} failed: {exc}")
                    results[side] = f"[{side.upper()} analysis unavailable]"

        return results.get("bull", "[unavailable]"), results.get("bear", "[unavailable]")

    # ------------------------------------------------------------------
    # Appel LLM (supporte tous les providers de synthesis_agent)
    # ------------------------------------------------------------------

    def _call_llm(self, system_prompt: str, user_content: str) -> str:
        cfg = self._llm_cfg
        provider = cfg.get("provider", "anthropic")
        timeout_s = int(cfg.get("request_timeout_seconds", 60))

        try:
            from utils.config import get_env

            if provider == "anthropic":
                import anthropic
                client = anthropic.Anthropic(api_key=get_env("ANTHROPIC_API_KEY"))
                # Haiku — rapide et pas cher pour ce rôle tactique
                msg = client.messages.create(
                    model="claude-haiku-4-5",
                    max_tokens=256,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_content}],
                    timeout=timeout_s,
                )
                return msg.content[0].text.strip()

            if provider in ("deepseek", "github", "xai", "ollama"):
                # Réutilise l'API OpenAI-compatible
                from langchain_openai import ChatOpenAI
                from langchain_core.messages import HumanMessage, SystemMessage

                api_key, base_url, model = _openai_compat_params(provider, cfg)
                llm = ChatOpenAI(
                    model=model,
                    temperature=0.4,
                    max_tokens=256,
                    openai_api_key=api_key,
                    openai_api_base=base_url,
                    request_timeout=timeout_s,
                )
                response = llm.invoke([
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_content),
                ])
                return str(response.content).strip()

        except Exception as exc:
            raise RuntimeError(f"LLM call failed ({provider}): {exc}") from exc

        return "[unsupported provider]"

    # ------------------------------------------------------------------
    # Construction du contexte
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(state: dict) -> str:
        """Résumé compact du state pour les debaters."""
        analyses: dict = state.get("agent_analyses", {})
        price   = state.get("market_indicators", {}).get("price", "?")
        regime  = analyses.get("market_regime", {}).get("regime", "UNKNOWN")
        fear    = analyses.get("fear_greed", {}).get("score", "?")
        x_sent  = analyses.get("x_sentiment", {}).get("score", "?")
        fundamental = analyses.get("fundamental", {}).get("summary", "")
        market_sum  = analyses.get("market_regime", {}).get("summary", "")

        lines = [
            f"Asset price: {price} USD",
            f"Market regime: {regime}",
            f"Fear & Greed index: {fear}/100",
            f"X/Twitter sentiment score: {x_sent}/100",
        ]
        if fundamental:
            lines.append(f"Fundamental: {fundamental[:200]}")
        if market_sum:
            lines.append(f"Technical: {market_sum[:200]}")

        return "\n".join(lines)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _disabled_result(reason: str = "disabled") -> dict:
    return {
        "agent_name":  "debate",
        "score":       50.0,
        "signal":      "NEUTRAL",
        "summary":     f"Debate {reason}",
        "confidence":  0.0,
        "bull_thesis": "",
        "bear_thesis": "",
    }


def _openai_compat_params(provider: str, cfg: dict) -> tuple[str, str, str]:
    from utils.config import get_env
    if provider == "deepseek":
        return get_env("DEEPSEEK_API_KEY"), "https://api.deepseek.com", cfg.get("model", "deepseek-chat")
    if provider == "github":
        return get_env("GITHUB_TOKEN"), "https://models.inference.ai.azure.com", cfg.get("model", "gpt-4o-mini")
    if provider == "xai":
        return get_env("XAI_API_KEY"), "https://api.x.ai/v1", cfg.get("model", "grok-beta")
    if provider == "ollama":
        return "ollama", cfg.get("ollama_base_url", "http://localhost:11434/v1"), cfg.get("model", "llama3")
    return "", "", ""
