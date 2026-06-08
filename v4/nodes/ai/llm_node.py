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
        try:
            formatted_prompt = user_prompt.format(**inputs, inputs=json.dumps(inputs, default=str))
        except (KeyError, ValueError):
            formatted_prompt = user_prompt.replace("{inputs}", json.dumps(inputs, default=str))

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
                import litellm
                litellm.drop_params = True
                resp_obj = litellm.completion(
                    model=f"{provider}/{model}" if provider != "deepseek" else f"deepseek/{model}",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": formatted_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout_s,
                )
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
        response = body.get("response", "")
        tokens_eval = body.get("eval_count", 0)
        tokens_prompt = body.get("prompt_eval_count", 0)

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
