"""
agents/synthesis_agent.py — Synthèse LLM de toutes les analyses
Génère l'explication narrative finale + score consolidé.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("zeitgeist.synthesis_agent")


class SynthesisAgent:
    """Agent de synthèse — orchestre tous les résultats via LLM."""

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        llm_cfg = cfg.get("llm", {})
        self.model: str = llm_cfg.get("model", "claude-3-5-sonnet-20241022")
        self.temperature: float = llm_cfg.get("temperature", 0.3)
        self.max_tokens: int = min(llm_cfg.get("max_tokens", 4096), 2048)
        self._llm = self._init_llm(llm_cfg)

    def _init_llm(self, cfg: dict):
        provider = cfg.get("provider", "anthropic")
        timeout_s = int(cfg.get("request_timeout_seconds", 60))
        try:
            from utils.config import get_env

            if provider == "deepseek":
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(
                    model=cfg.get("model", "deepseek-chat"),
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    openai_api_key=get_env("DEEPSEEK_API_KEY"),
                    openai_api_base="https://api.deepseek.com",
                    request_timeout=timeout_s,
                )

            elif provider == "github":
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(
                    model=cfg.get("model", "gpt-4o"),
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    openai_api_key=get_env("GITHUB_TOKEN"),
                    openai_api_base="https://models.inference.ai.azure.com",
                    request_timeout=timeout_s,
                )

            elif provider == "xai":
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(
                    model=cfg.get("model", "grok-beta"),
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    openai_api_key=get_env("XAI_API_KEY"),
                    openai_api_base="https://api.x.ai/v1",
                    request_timeout=timeout_s,
                )

            elif provider == "ollama":
                from langchain_openai import ChatOpenAI
                base_url = get_env("OLLAMA_BASE_URL", required=False, default="http://localhost:11434/v1")
                return ChatOpenAI(
                    model=cfg.get("model", "nemotron"),
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    openai_api_key="ollama",
                    openai_api_base=base_url,
                    request_timeout=timeout_s,
                )

            else:  # anthropic (défaut)
                from langchain_anthropic import ChatAnthropic
                return ChatAnthropic(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    api_key=get_env("ANTHROPIC_API_KEY"),
                    timeout=timeout_s,
                )

        except Exception as exc:
            logger.warning(f"LLM non disponible (provider={provider}, err={exc}) — mode fallback")
            return None

    def synthesize(self, state: dict) -> dict:
        """Génère la synthèse complète depuis l'état LangGraph."""
        if self._llm is None:
            return self._fallback_synthesis(state)

        prompt = self._build_prompt(state)
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
            import yaml

            with open("config/prompts.yaml", "r", encoding="utf-8") as f:
                prompts = yaml.safe_load(f)
            system_prompt = prompts.get("synthesis_agent", "Tu es un analyste financier expert.")

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ]
            # Timeout global sur l'appel LLM (en plus du timeout réseau du client)
            # IMPORTANT: ne PAS utiliser "with ThreadPoolExecutor" — son __exit__ appelle
            # shutdown(wait=True) même après un return/exception, ce qui bloque indéfiniment
            # si le thread LLM est encore en attente réseau.
            _hard_timeout = 90  # secondes
            from utils.config import load_settings as _ls2
            _hard_timeout = int(_ls2().get("llm", {}).get("request_timeout_seconds", 60)) + 30
            _pool = ThreadPoolExecutor(max_workers=1)
            _fut = _pool.submit(self._llm.invoke, messages)
            try:
                response = _fut.result(timeout=_hard_timeout)
            except FuturesTimeout:
                logger.error(f"SynthesisAgent LLM timeout ({_hard_timeout}s) — fallback")
                _pool.shutdown(wait=False)  # abandon le thread, ne pas bloquer
                return self._fallback_synthesis(state)
            except Exception:
                _pool.shutdown(wait=False)
                raise
            _pool.shutdown(wait=False)
            content = response.content
            tokens = response.usage_metadata.get("input_tokens", 0) + \
                     response.usage_metadata.get("output_tokens", 0) \
                     if hasattr(response, "usage_metadata") else 0

            # Parse JSON de la réponse
            try:
                # Extraire le JSON s'il est dans des balises ```
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                parsed = json.loads(content)
            except json.JSONDecodeError:
                logger.warning("Impossible de parser le JSON de la synthèse")
                parsed = {"score_global": 50, "resume_court": content[:200]}

            return {
                "agent_name": "synthesis",
                "score": float(parsed.get("score_global", 50)),
                "signal": parsed.get("signal", "NEUTRAL"),
                "summary": parsed.get("resume_court", ""),
                "explanation_complete": parsed.get("explication_complete", ""),
                "risks": parsed.get("risques_identifies", []),
                "catalysts": parsed.get("catalyseurs_potentiels", []),
                "confidence": 0.8,
                "tokens_used": tokens,
            }
        except Exception as exc:
            logger.error(f"Erreur SynthesisAgent LLM: {exc}")
            return self._fallback_synthesis(state)

    def _build_prompt(self, state: dict) -> str:
        """Construit le prompt de synthèse depuis l'état."""
        analyses = state.get("agent_analyses", {})
        mirofish = state.get("mirofish_result", {})
        market = state.get("market_indicators", {})
        news_count = len(state.get("news_items", []))

        parts = [
            f"**Asset** : {state.get('asset', 'BTC/USDT')}",
            f"**News collectées** : {news_count}",
            f"**Score MiroFish** : {mirofish.get('score', 50):.1f}/100",
            f"**Narrative dominante MiroFish** : {mirofish.get('dominant_narrative', 'N/A')}",
            f"**Prix** : {market.get('price', 0):.2f}",
            f"**RSI** : {market.get('rsi_14', 50):.1f}",
            f"**Funding rate** : {market.get('funding_rate', 0):.4f}",
        ]

        for agent_name, analysis in analyses.items():
            if isinstance(analysis, dict):
                parts.append(
                    f"**Agent {agent_name}** : score={analysis.get('score', 50):.0f} "
                    f"signal={analysis.get('signal', 'N/A')} — {analysis.get('summary', '')}"
                )

        adt = state.get("air_du_temps", {})
        if adt:
            parts.append(f"**Air du Temps** : {adt.get('full_text', '')[:500]}")

        return "\n".join(parts) + "\n\nGénère la synthèse au format JSON demandé."

    def _fallback_synthesis(self, state: dict) -> dict:
        """Synthèse déterministe sans LLM."""
        analyses = state.get("agent_analyses", {})
        scores = [v.get("score", 50) for v in analyses.values() if isinstance(v, dict)]
        mean_score = sum(scores) / len(scores) if scores else 50.0

        signal = "BULLISH" if mean_score > 60 else ("BEARISH" if mean_score < 40 else "NEUTRAL")
        return {
            "agent_name": "synthesis",
            "score": round(mean_score, 1),
            "signal": signal,
            "summary": f"Synthèse automatique (sans LLM) — {len(scores)} agents analysés",
            "risks": [],
            "catalysts": [],
            "confidence": 0.3,
            "tokens_used": 0,
        }
