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
        # Inputs dynamiques — tout ce qui est connecté est accepté
        return {}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"response": "str", "parsed": "dict", "tokens_used": "int", "model": "str", "duration_ms": "float"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from v4.nodes.config_loader import load_v4_config

        # ── Mode async : fire-and-forget, retour immédiat ──
        async_mode = bool(self.params.get("async_mode", True))
        dag_id = self.params.get("dag_id", "unknown")
        cache_key = f"llm_{dag_id}_{self.node_id}"

        if async_mode:
            from v4.core.async_tasks import dispatch, get_result, is_pending

            # Récupérer le résultat du cycle précédent (sera None au 1er cycle)
            cached = get_result(cache_key)
            import logging
            _logger = logging.getLogger("v4.nodes.ai.llm_node")
            _logger.info("LLMNode [%s] cache_key=%s cached=%s", self.node_id, cache_key,
                         "HIT" if cached else "MISS")

            # Lancer le nouvel appel en arrière-plan (capture les inputs actuels)
            _inputs_snapshot = dict(inputs)  # copie pour le thread
            _params_snapshot = dict(self.params)
            _node_id = self.node_id

            def _async_call():
                # Ré-exécuter run() en mode sync pour ce snapshot
                import copy
                # On évite la récursion infinie : on appelle directement le code sync
                return self._run_sync(_inputs_snapshot)

            dispatch(cache_key, _async_call)

            if cached and "error" not in cached:
                _logger.info("LLMNode [%s] returning cached result", self.node_id)
                cached["_async"] = True
                cached["_pending_next"] = is_pending(cache_key)
                return cached
            else:
                # Premier cycle : pas encore de résultat
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

        # ── Modèle : priorité DAG → settings.yaml global → défaut ──
        _llm_cfg = load_v4_config(None, "llm", {
            "provider": "deepseek", "model": "deepseek-v4-pro",
            "ollama_url": "http://atlas-v4-ollama:11434",
        })
        provider      = self.params.get("provider") or _llm_cfg.get("provider", "ollama")
        model         = self.params.get("model") or _llm_cfg.get("model", "phi4:latest")
        system_prompt = self.params.get("system_prompt", "You are a trading assistant. Respond in JSON.")
        user_prompt   = self.params.get("user_prompt", "Analyze: {inputs}")
        temperature   = float(self.params.get("temperature", 0.3))
        max_tokens    = int(self.params.get("max_tokens", 512))
        ollama_url    = self.params.get("ollama_url", _llm_cfg.get("ollama_url", "http://atlas-v4-ollama:11434"))
        timeout_s     = int(self.params.get("timeout_s", 60))

        # Substitution des placeholders dans le user_prompt
        # Injecter les leçons de reflection si présentes
        reflections = inputs.get("lessons") or inputs.get("reflections", "")
        if reflections:
            formatted_prompt = user_prompt.replace("{reflections}", str(reflections))
        else:
            formatted_prompt = user_prompt.replace("{reflections}", "")

        try:
            formatted_prompt = formatted_prompt.format(**inputs, inputs=json.dumps(inputs, default=str))
        except (KeyError, ValueError):
            formatted_prompt = formatted_prompt.replace("{inputs}", json.dumps(inputs, default=str))

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
                # Ollama local (pas de clé API)
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
                # Lire la clé API : param DAG > secrets.yaml llm > env
                api_key = self.params.get("api_key", "") or ""
                if not api_key:
                    api_key = _llm_cfg.get("deepseek_api_key", "") or ""
                if not api_key:
                    api_key = _llm_cfg.get("api_key", "") or ""
                if not api_key:
                    import os
                    api_key = os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("DEEPSEEK_KEY", "")
                import litellm
                litellm.drop_params = True
                # LiteLLM lit DEEPSEEK_API_KEY depuis l'environnement
                if api_key:
                    import os as _os
                    _os.environ.setdefault("DEEPSEEK_API_KEY", api_key)
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
                resp_obj = litellm.completion(**kwargs)
                response_text = resp_obj.choices[0].message.content if resp_obj.choices else ""
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
        # Extraire le premier bloc JSON (entre ```json ... ``` ou { ... })
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Essayer de trouver le premier { ... }
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
