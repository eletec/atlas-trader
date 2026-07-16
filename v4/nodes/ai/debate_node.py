"""
v4/nodes/ai/debate_node.py — DebateNode (Bull vs Bear + Judge).

Inspiré du pattern de débat de TradingAgents.
Lance 2 appels LLM (bull + bear), puis un juge tranche.

Inputs  : arbitraires (transmis aux 2 analystes et au juge)

Outputs :
    decision      : str   — "bullish" | "bearish" | "neutral"
    confidence    : float — [0, 1]
    bull_argument : str   — résumé de l'argument bull
    bear_argument : str   — résumé de l'argument bear
    verdict       : str   — raison du juge (1 phrase)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from v4.core.node import Node

logger = logging.getLogger("v4.nodes.ai.debate_node")

BULL_SYSTEM = """You are a BULLISH crypto analyst. Your job is to find EVERY reason why 
the market should go UP right now. Consider:
- Positive momentum and trend signals
- Support levels holding
- Oversold bounces
- Favorable macro or sentiment
- Any bullish divergence in indicators

Be concise but thorough. End with a CLEAR directional call: BULLISH or NEUTRAL.
Respond in JSON: {"call": "bullish"|"neutral", "confidence": 0.0-1.0, "argument": "..."}"""

BEAR_SYSTEM = """You are a BEARISH crypto analyst. Your job is to find EVERY reason why 
the market should go DOWN right now. Consider:
- Negative momentum and trend signals
- Resistance levels rejecting price
- Overbought conditions
- Unfavorable macro or sentiment
- Any bearish divergence in indicators

Be concise but thorough. End with a CLEAR directional call: BEARISH or NEUTRAL.
Respond in JSON: {"call": "bearish"|"neutral", "confidence": 0.0-1.0, "argument": "..."}"""

JUDGE_SYSTEM = """You are a neutral crypto trading JUDGE. You receive two arguments:
- A BULL argument
- A BEAR argument

Compare their logic, evidence quality, and conviction. Pick the winner.
If both are equally convincing, say NEUTRAL.
Respond in JSON: {"winner": "bull"|"bear"|"neutral", "verdict": "One sentence explaining why", "confidence": 0.0-1.0}"""


class DebateNode(Node):
    """
    Débat Bull vs Bear avec juge.

    Inputs  : arbitraires (transmis aux prompts)

    Outputs :
        decision      : str   — "bullish" | "bearish" | "neutral"
        confidence    : float — [0, 1]
        bull_argument : str
        bear_argument : str
        verdict       : str

    Params :
        provider       : str — LLM provider (défaut: ollama)
        model          : str — modèle (défaut: phi4:latest)
        temperature    : float (défaut: 0.4)
        max_tokens     : int (défaut: 256)
        ollama_url     : str
        timeout_s      : int (défaut: 90)
        skip_debate    : bool — si True, passe directement (défaut: False)
    """

    @property
    def node_type(self) -> str:
        return "DebateNode"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {
            "decision": "str",
            "confidence": "float",
            "bull_argument": "str",
            "bear_argument": "str",
            "verdict": "str",
        }

    def _call_llm_raw(
        self, system: str, prompt: str, provider: str, model: str,
        temperature: float, max_tokens: int, ollama_url: str, timeout_s: int,
        api_key: str = "",
    ) -> str:
        """Appelle le LLM et retourne le texte brut."""
        payload = {
            "model": model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

        try:
            if provider == "ollama":
                import urllib.request
                req = urllib.request.Request(
                    f"{ollama_url}/api/generate",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                response_text = body.get("response", "")
            else:
                import litellm
                litellm.drop_params = True
                kwargs = dict(
                    model=f"{provider}/{model}" if "/" not in model else model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout_s,
                )
                if api_key:
                    kwargs["api_key"] = api_key
                resp_obj = litellm.completion(**kwargs)
                response_text = resp_obj.choices[0].message.content if resp_obj.choices else ""
        except Exception as exc:
            logger.warning("Debate LLM call failed: %s", exc)
            return f'{{"call": "neutral", "confidence": 0.0, "argument": "Error: {exc}"}}'

        return response_text

    def _parse_json_response(self, text: str) -> dict:
        """Extrait le JSON d'une réponse LLM."""
        raw = text.strip()
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except json.JSONDecodeError:
                    pass
        return {"call": "neutral", "confidence": 0.0, "argument": raw[:200]}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        skip = bool(self.params.get("skip_debate", False))
        if skip:
            return {
                "decision": "neutral", "confidence": 0.5,
                "bull_argument": "", "bear_argument": "", "verdict": "Debate skipped",
            }

        # ── Mode async : fire-and-forget, retour immédiat ──
        async_mode = bool(self.params.get("async_mode", True))
        dag_id = self.params.get("dag_id", "unknown")
        cache_key = f"debate_{dag_id}_{self.node_id}"

        if async_mode:
            from v4.core.async_tasks import dispatch, get_result, is_pending

            cached = get_result(cache_key)

            _inputs_snapshot = dict(inputs)
            _params_snapshot = dict(self.params)

            def _async_call():
                return self._run_sync(_inputs_snapshot)

            dispatch(cache_key, _async_call)

            if cached and "error" not in cached:
                cached["_async"] = True
                cached["_pending_next"] = is_pending(cache_key)
                return cached
            else:
                return {
                    "decision": "neutral",
                    "confidence": 0.5,
                    "bull_argument": "⏳ Débat en cours...",
                    "bear_argument": "⏳ Débat en cours...",
                    "verdict": "L'IA débat, verdict au prochain cycle.",
                    "_async": True,
                    "_pending_next": True,
                }

        return self._run_sync(inputs)

    def _run_sync(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Exécution synchrone du débat (utilisée par async mode en background)."""
        from v4.nodes.config_loader import load_v4_config

        _llm_cfg = load_v4_config(None, "llm", {
            "provider": "deepseek", "model": "deepseek-v4-pro",
            "ollama_url": "http://atlas-v4-ollama:11434",
        })
        provider = self.params.get("provider") or _llm_cfg.get("provider", "ollama")
        model = self.params.get("model") or _llm_cfg.get("model", "phi4:latest")
        temperature = float(self.params.get("temperature", 0.4))
        max_tokens = int(self.params.get("max_tokens", 512))
        ollama_url = self.params.get("ollama_url", _llm_cfg.get("ollama_url", "http://atlas-v4-ollama:11434"))
        timeout_s = int(self.params.get("timeout_s", 90))
        import os as _os_dk
        api_key = (_os_dk.environ.get("DEEPSEEK_API_KEY", "") or _os_dk.environ.get("DEEPSEEK_KEY", "")
                    or _llm_cfg.get("deepseek_api_key", "") or _llm_cfg.get("api_key", ""))

        # ── Construire le prompt commun ──
        reflections = inputs.get("lessons") or inputs.get("reflections", "")
        market_data = json.dumps({k: v for k, v in inputs.items()
                                   if k not in ("lessons", "reflections")}, default=str)

        prompt = ""
        if reflections:
            prompt += f"Past lessons:\n{reflections}\n\n"
        prompt += f"Current market state:\n{market_data}\n\n"
        prompt += "Analyze the above and give your call in JSON."

        # ── Phase 1 : Bull & Bear ──
        t0 = time.time()
        logger.info("Debate: calling Bull analyst...")
        bull_raw = self._call_llm_raw(
            BULL_SYSTEM, prompt, provider, model,
            temperature, max_tokens, ollama_url, timeout_s, api_key,
        )
        bull_result = self._parse_json_response(bull_raw)
        logger.info("Debate: Bull raw=%.120s", bull_raw)
        logger.info("Debate: Bull → %s (conf=%.2f)", bull_result.get("call"), bull_result.get("confidence", 0))

        logger.info("Debate: calling Bear analyst...")
        bear_raw = self._call_llm_raw(
            BEAR_SYSTEM, prompt, provider, model,
            temperature, max_tokens, ollama_url, timeout_s, api_key,
        )
        bear_result = self._parse_json_response(bear_raw)
        logger.info("Debate: Bear raw=%.120s", bear_raw)
        logger.info("Debate: Bear → %s (conf=%.2f)", bear_result.get("call"), bear_result.get("confidence", 0))

        # ── Phase 2 : Juge ──
        judge_prompt = (
            f"Bull argument: {bull_result.get('argument', 'N/A')}\n\n"
            f"Bear argument: {bear_result.get('argument', 'N/A')}\n\n"
            "Who wins? Respond in JSON."
        )
        logger.info("Debate: calling Judge...")
        judge_raw = self._call_llm_raw(
            JUDGE_SYSTEM, judge_prompt, provider, model,
            temperature, max_tokens, ollama_url, timeout_s, api_key,
        )
        judge_result = self._parse_json_response(judge_raw)

        winner = judge_result.get("winner", "neutral")
        verdict = judge_result.get("verdict", "Could not decide")
        judge_conf = float(judge_result.get("confidence", 0.5))

        # ── Mapping winner → decision ──
        if winner == "bull":
            decision = "bullish"
            confidence = judge_conf
        elif winner == "bear":
            decision = "bearish"
            confidence = judge_conf
        else:
            decision = "neutral"
            confidence = 0.5

        duration_ms = (time.time() - t0) * 1000
        logger.info(
            "Debate verdict: %s (conf=%.2f) in %.0fms — %s",
            decision, confidence, duration_ms, verdict[:80],
        )

        return {
            "decision": decision,
            "confidence": round(confidence, 4),
            "bull_argument": bull_result.get("argument", "")[:300],
            "bear_argument": bear_result.get("argument", "")[:300],
            "verdict": verdict[:200],
            "duration_ms": round(duration_ms, 1),
        }
