"""
utils/claude_cli.py — CA7 : Intégration Claude CLI pour analyses ad-hoc

Expose run_claude_analysis() pour lancer des prompts Claude directement
depuis le panel admin du dashboard Streamlit.

Prérequis : `claude` CLI doit être installé et accessible dans $PATH.
  npm install -g @anthropic-ai/claude-cli  (ou eq.)

En cas d'absence du CLI, fallback sur l'API Python anthropic si disponible.
"""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger("zeitgeist.claude_cli")

# Timeout par défaut pour les appels CLI (secondes)
_DEFAULT_TIMEOUT = 60


def run_claude_analysis(prompt: str, timeout: int = _DEFAULT_TIMEOUT) -> str:
    """
    Envoie `prompt` au LLM configuré et retourne la réponse textuelle.

    Strategy :
    1. Essaie le CLI `claude --print --output-format json` (si installé)
    2. Fallback sur l'API du provider configuré dans settings.yaml
       (deepseek, anthropic, openai, xai, ollama, github)
    """
    try:
        return _run_via_cli(prompt, timeout)
    except FileNotFoundError:
        logger.info("`claude` CLI not found — falling back to Python API")
        return _run_via_api(prompt, timeout)
    except subprocess.TimeoutExpired:
        logger.warning("Claude CLI timeout (%ds)", timeout)
        return f"[Erreur] Timeout après {timeout}s. Essayez un prompt plus court."
    except Exception as exc:
        logger.error("Claude CLI unexpected error: %s", exc)
        return _run_via_api(prompt, timeout)


def run_claude_analysis_structured(prompt: str, timeout: int = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    """
    Variante retournant un dict avec au moins les clés :
        text (str), model (str), input_tokens (int), output_tokens (int)
    """
    text = run_claude_analysis(prompt, timeout)
    return {
        "text": text,
        "model": "unknown",
        "input_tokens": 0,
        "output_tokens": 0,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _run_via_cli(prompt: str, timeout: int) -> str:
    """Exécute le CLI claude et retourne la sortie texte."""
    result = subprocess.run(
        ["claude", "--print", "--output-format", "json"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr_snippet = (result.stderr or "")[:200]
        raise RuntimeError(f"CLI exit code {result.returncode}: {stderr_snippet}")

    stdout = result.stdout.strip()
    # L'output JSON du CLI peut être : {"type":"result","result":"...","cost_usd":...}
    try:
        parsed = json.loads(stdout)
        if isinstance(parsed, dict):
            return str(parsed.get("result") or parsed.get("text") or stdout)
    except json.JSONDecodeError:
        pass
    return stdout


def _run_via_api(prompt: str, timeout: int) -> str:
    """Appel direct via le provider LLM configuré dans settings.yaml."""
    import os
    from utils.config import load_settings
    cfg = load_settings()
    llm_cfg = cfg.get("llm", {})
    provider = llm_cfg.get("provider", "anthropic")
    model    = llm_cfg.get("model", "")

    _placeholder_suffixes = ("...", "sk-ant-...", "sk-...", "")

    try:
        if provider == "deepseek":
            from openai import OpenAI
            key = llm_cfg.get("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
            if not key or key in _placeholder_suffixes or key.endswith("..."):
                return "[Erreur] DEEPSEEK_API_KEY manquante dans le .env ou settings."
            client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
            resp = client.chat.completions.create(
                model=model or "deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                timeout=timeout,
            )
            return resp.choices[0].message.content or ""

        elif provider in ("openai", "github"):
            from openai import OpenAI
            if provider == "github":
                key     = llm_cfg.get("github_api_key") or os.environ.get("GITHUB_TOKEN", "")
                base    = "https://models.inference.ai.azure.com"
                model   = model or "gpt-4o"
            else:
                key     = llm_cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
                base    = None
                model   = model or "gpt-4o-mini"
            if not key or key in _placeholder_suffixes or key.endswith("..."):
                return f"[Erreur] Clé API {provider.upper()} manquante dans le .env ou settings."
            kwargs = dict(api_key=key, timeout=timeout)
            if base:
                kwargs["base_url"] = base
            client = OpenAI(**kwargs)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            return resp.choices[0].message.content or ""

        elif provider == "xai":
            from openai import OpenAI
            key = llm_cfg.get("xai_api_key") or os.environ.get("XAI_API_KEY", "")
            if not key or key in _placeholder_suffixes or key.endswith("..."):
                return "[Erreur] XAI_API_KEY manquante dans le .env ou settings."
            client = OpenAI(api_key=key, base_url="https://api.x.ai/v1")
            resp = client.chat.completions.create(
                model=model or "grok-beta",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                timeout=timeout,
            )
            return resp.choices[0].message.content or ""

        elif provider == "ollama":
            from openai import OpenAI
            base = llm_cfg.get("ollama_base_url") or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
            client = OpenAI(api_key="ollama", base_url=base)
            resp = client.chat.completions.create(
                model=model or "llama3",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                timeout=timeout,
            )
            return resp.choices[0].message.content or ""

        else:  # anthropic (défaut)
            import anthropic
            key = llm_cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
            if not key or key in _placeholder_suffixes or key.endswith("..."):
                return (
                    "[Erreur] Clé API Anthropic non configurée.\n"
                    "Renseignez ANTHROPIC_API_KEY dans le .env du container."
                )
            client = anthropic.Anthropic(api_key=key)
            resp = client.messages.create(
                model=model or "claude-3-5-haiku-20241022",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text if resp.content else ""

    except Exception as exc:
        logger.error("LLM API échoué (provider=%s) : %s", provider, exc)
        return f"[Erreur] {exc}"
