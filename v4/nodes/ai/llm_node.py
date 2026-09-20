"""
v4/nodes/ai/llm_node.py — Nœud LLMNode

Nœud IA paramétrable — envoie un prompt à Ollama (ou autre backend)
et retourne la réponse. Inputs arbitraires injectés dans le prompt
via {input_key} placeholders.
"""
from __future__ import annotations

import json
import time
from typing import Any

from v4.core.node import Node


class LLMNode(Node):
    """
    Nœud LLM générique. Le prompt utilise des {placeholders} qui sont
    remplacés par les valeurs des inputs au moment de l'exécution.

    Inputs  : arbitraires (tout ce qui est connecté est injecté dans le prompt)

    Outputs :
        response     (str — réponse brute du LLM)
        parsed       (dict/Any — tentative de parse JSON de la réponse)
        tokens_used  (int — nombre de tokens consommés)
        model        (str — modèle utilisé)
        duration_ms  (float)

    Params :
        system_prompt  : str  — prompt système (défaut: "You are a trading assistant.")
        user_prompt    : str  — prompt utilisateur avec {placeholders}
        model          : str  — modèle Ollama (défaut: "phi4:latest")
        temperature    : float — température (défaut 0.3)
        max_tokens     : int  — max tokens (défaut 512)
        ollama_url     : str  — URL du serveur Ollama (défaut: http://atlas-v4-ollama:11434)
        timeout_s      : int  — timeout en secondes (défaut 60)
    """

    @property
    def node_type(self) -> str:
        return "LLMNode"

    @staticmethod
    def input_schema() -> dict[str, str]:
        # Dynamic inputs - everything connected is accepted
        return {}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"response": "str", "parsed": "dict", "tokens_used": "int", "model": "str", "duration_ms": "float"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from v4.nodes.config_loader import load_v4_config

        # -- Async mode: fire-and-forget, returns immediately --
        async_mode = bool(self.params.get("async_mode", True))
        dag_id = self.params.get("dag_id", "unknown")
        cache_key = f"llm_{dag_id}_{self.node_id}"

        if async_mode:
            from v4.core.async_tasks import dispatch, get_result, is_pending

            # Fetch the previous cycle's result (None on the first cycle)
            cached = get_result(cache_key)
            import logging
            _logger = logging.getLogger("v4.nodes.ai.llm_node")
            _logger.info("LLMNode [%s] cache_key=%s cached=%s", self.node_id, cache_key,
                         "HIT" if cached else "MISS")

            # Start the new call in the background (captures the current inputs)
            _inputs_snapshot = dict(inputs)  # copy for the thread
            _params_snapshot = dict(self.params)
            _node_id = self.node_id

            def _async_call():
                # Re-run run() in sync mode for this snapshot
                import copy
                # Avoid infinite recursion by calling the sync code directly
                return self._run_sync(_inputs_snapshot)

            dispatch(cache_key, _async_call)

            if cached and "error" not in cached:
                _logger.info("LLMNode [%s] returning cached result", self.node_id)
                cached["_async"] = True
                cached["_pending_next"] = is_pending(cache_key)
                return cached
            else:
                # First cycle: no result yet
                _logger.info("LLMNode [%s] returning placeholder (cached=%s, has_error=%s)",
                            self.node_id, cached is not None,
                            "error" in (cached or {}))
                return {
                    "response": "⏳ Analyse en cours...",
                    "parsed": {"status": "pending", "message": "L'IA analyse le marché, résultat au prochain cycle."},
                    "tokens_used": 0,
                    "model": self.params.get("model", "?"),
                    "duration_ms": 0,
                    "_async": True,
                    "_pending_next": True,
                }

        # ── Mode sync (fallback) ──
        return self._run_sync(inputs)

    def _run_sync(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Exécution synchrone du LLM (utilisée par async mode en background)."""
        from v4.nodes.config_loader import load_v4_config

        # -- Model: DAG params first -> settings.yaml (back-office) -> DeepSeek default --
        # Support dual config: "deep" (BO, reasoning) vs "fast" (DAG, quick analysis)
        _llm_cfg = load_v4_config(None, "llm", {
            "provider": "deepseek", "model": "deepseek-v4-pro",
            "ollama_url": "http://atlas-v4-ollama:11434",
        })
        use_fast = bool(self.params.get("use_fast", False))
        if use_fast:
            provider = self.params.get("provider") or _llm_cfg.get("fast_provider") or _llm_cfg.get("provider", "deepseek")
            model    = self.params.get("model") or _llm_cfg.get("fast_model", "deepseek-chat")
            temperature = float(self.params.get("temperature") or _llm_cfg.get("fast_temperature", 0.3))
            max_tokens  = int(self.params.get("max_tokens") or _llm_cfg.get("fast_max_tokens", 256))
        else:
            provider = self.params.get("provider") or _llm_cfg.get("provider", "deepseek")
            model    = self.params.get("model") or _llm_cfg.get("model", "deepseek-v4-pro")
            temperature = float(self.params.get("temperature", 0.3))
            max_tokens  = int(self.params.get("max_tokens", 512))
        system_prompt = self.params.get("system_prompt", "You are a trading assistant. Respond in JSON.")
        user_prompt   = self.params.get("user_prompt", "Analyze: {inputs}")
        ollama_url    = self.params.get("ollama_url", _llm_cfg.get("ollama_url", "http://atlas-v4-ollama:11434"))
        timeout_s     = int(self.params.get("timeout_s", 60))

        # Substitute the placeholders in the user_prompt
        # Inject the reflection lessons when present
        reflections = inputs.get("lessons") or inputs.get("reflections", "")
        if reflections:
            formatted_prompt = user_prompt.replace("{reflections}", str(reflections))
        else:
            formatted_prompt = user_prompt.replace("{reflections}", "")

        try:
            # Avoid a clash when 'inputs' is already a key in the dict
            _fmt_inputs = dict(inputs)
            _fmt_inputs.pop("inputs", None)  # on le passe explicitement
            formatted_prompt = formatted_prompt.format(**_fmt_inputs, inputs=json.dumps(inputs, default=str))
        except (KeyError, ValueError):
            # Replace every missing placeholder with 'N/A' instead of leaving {key}
            import re as _re
            def _safe_replace(m):
                key = m.group(1)
                if key == "inputs":
                    return json.dumps(inputs, default=str)
                val = inputs.get(key)
                return str(val) if val is not None else "N/A"
            formatted_prompt = _re.sub(r'\{(\w+)\}', _safe_replace, formatted_prompt)

        payload = {
            "model": model,
            "system": system_prompt,
            "prompt": formatted_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        t0 = time.time()
        try:
            if provider == "ollama":
                # Local Ollama (no API key)
                import urllib.request
                payload = {
                    "model": model,
                    "system": system_prompt,
                    "prompt": formatted_prompt,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                }
                req = urllib.request.Request(
                    f"{ollama_url}/api/generate",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                response_text = body.get("response", "")
            else:
                # DeepSeek / OpenAI-compatible via litellm
                # Read the API key: DAG param > env > settings.yaml > secrets.yaml > fast_api_key
                import os as _os_key
                api_key = self.params.get("api_key", "") or ""
                if not api_key:
                    api_key = _os_key.environ.get("DEEPSEEK_API_KEY", "") or _os_key.environ.get("DEEPSEEK_KEY", "")
                if not api_key:
                    api_key = _llm_cfg.get("deepseek_api_key", "") or ""
                if not api_key:
                    api_key = _llm_cfg.get("api_key", "") or ""
                # In fast mode also look for fast_api_key (a different provider is possible)
                if not api_key and use_fast:
                    api_key = _llm_cfg.get("fast_api_key", "") or ""
                # Also look inside secrets.yaml (kept separate from settings.yaml for security)
                if not api_key:
                    try:
                        import yaml as _yaml
                        for _sec_path in ("/app/data/secrets.yaml", "/app/src/config/secrets.yaml"):
                            try:
                                with open(_sec_path) as _sf:
                                    _secrets = _yaml.safe_load(_sf) or {}
                                _sec_llm = _secrets.get("llm", {})
                                api_key = _sec_llm.get("deepseek_api_key", "") or _sec_llm.get("api_key", "")
                                # In fast mode, look for fast_api_key in secrets too
                                if not api_key and use_fast:
                                    api_key = _sec_llm.get("fast_api_key", "")
                                if api_key:
                                    break
                            except FileNotFoundError:
                                continue
                    except Exception:
                        pass
                import litellm
                litellm.drop_params = True
                kwargs = dict(
                    model=f"{provider}/{model}" if "/" not in model else model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": formatted_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout_s,
                )
                if api_key:
                    kwargs["api_key"] = api_key
                    # Env var fallback for the providers that need it
                    import os as _os
                    _os.environ.setdefault("DEEPSEEK_API_KEY", api_key)
                try:
                    resp_obj = litellm.completion(**kwargs)
                    response_text = resp_obj.choices[0].message.content if resp_obj.choices else ""
                except Exception as _litellm_exc:
                    _err_msg = str(_litellm_exc)
                    # Fallback: when auth fails, try the local Ollama
                    if "auth" in _err_msg.lower() or "key" in _err_msg.lower() or "401" in _err_msg or "403" in _err_msg:
                        import logging as _logging
                        _llm_log = _logging.getLogger("v4.nodes.ai.llm_node")
                        _llm_log.warning("DeepSeek auth failed → fallback Ollama local: %s", _err_msg[:120])
                        try:
                            import urllib.request as _ur2
                            _fb_payload = {
                                "model": "phi4:latest",
                                "system": system_prompt,
                                "prompt": formatted_prompt,
                                "stream": False,
                                "options": {"temperature": temperature, "num_predict": max_tokens},
                            }
                            _fb_req = _ur2.Request(
                                f"{ollama_url}/api/generate",
                                data=json.dumps(_fb_payload).encode("utf-8"),
                                headers={"Content-Type": "application/json"},
                            )
                            with _ur2.urlopen(_fb_req, timeout=timeout_s) as _fb_resp:
                                _fb_body = json.loads(_fb_resp.read().decode("utf-8"))
                            response_text = _fb_body.get("response", "")
                            model = "phi4:latest (ollama fallback)"
                        except Exception as _fb_exc:
                            raise RuntimeError(f"DeepSeek auth failed + Ollama fallback failed: {_fb_exc}") from _litellm_exc
                    else:
                        raise
        except Exception as exc:
            duration_ms = (time.time() - t0) * 1000
            return {
                "response": f"LLM_ERROR: {exc}",
                "parsed": {"error": str(exc)},
                "tokens_used": 0,
                "model": model,
                "duration_ms": round(duration_ms, 1),
            }

        duration_ms = (time.time() - t0) * 1000
        response = response_text.strip()
        tokens_eval = 0
        tokens_prompt = 0

        # Tentative de parse JSON
        parsed = None
        raw = response.strip()
        # Extract the first JSON block (between ```json ... ``` or { ... })
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Try to find the first { ... }
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(raw[start:end + 1])
                except json.JSONDecodeError:
                    parsed = {"raw": raw}

        return {
            "response": response,
            "parsed": parsed or {"raw": raw},
            "tokens_used": tokens_eval + tokens_prompt,
            "model": model,
            "duration_ms": round(duration_ms, 1),
        }
