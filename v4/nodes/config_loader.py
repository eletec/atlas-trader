"""
v4/nodes/config_loader.py — Chargeur de configuration V4.

Chaque nœud appelle `load_v4_config(symbol, section)` pour obtenir
ses paramètres avec la priorité :
  paramètre DAG > settings.yaml assets/{symbol} > settings.yaml global > défaut.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("v4.nodes.config_loader")

# Cache du fichier settings.yaml (rechargé si modifié)
_cache: dict | None = None
_cache_mtime: float = 0.0


def _get_settings() -> dict:
    """Charge settings.yaml + secrets.yaml avec cache (invalidation si fichier modifié)."""
    global _cache, _cache_mtime
    # Priorité : /app/data/ (writable, persistant) > config/ (git-tracked, read-only)
    _git_settings = Path(__file__).resolve().parent.parent.parent / "config" / "settings.yaml"
    _data_settings = Path("/app/data") / "settings.yaml"
    # Bootstrap : copier vers /app/data/ au premier lancement
    if not _data_settings.exists() and _git_settings.exists():
        import shutil
        _data_settings.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_git_settings, _data_settings)
    settings_path = _data_settings if _data_settings.exists() else _git_settings
    secrets_path = Path(__file__).resolve().parent.parent.parent / "config" / "secrets.yaml"
    try:
        mtime = settings_path.stat().st_mtime if settings_path.exists() else 0
        # aussi vérifier secrets.yaml
        if secrets_path.exists():
            mtime = max(mtime, secrets_path.stat().st_mtime)
        if _cache is not None and mtime == _cache_mtime:
            return _cache
        import yaml
        cfg: dict = {}
        if settings_path.exists():
            with settings_path.open("r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
        # Fusionner secrets.yaml (priorité sur settings.yaml)
        if secrets_path.exists():
            with secrets_path.open("r", encoding="utf-8") as fh:
                secrets = yaml.safe_load(fh) or {}
            _deep_merge(cfg, secrets)
        _cache = cfg
        _cache_mtime = mtime
        return _cache
    except Exception:
        return _cache or {}


def _deep_merge(base: dict, override: dict) -> None:
    """Fusionne override dans base (modifie base in-place, priorité override).
    Ne remplace PAS une valeur existante par une chaîne vide ou None."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        elif value or not isinstance(value, (str, type(None))):
            # skip empty strings and None — don't erase existing values
            base[key] = value
        elif key not in base:
            base[key] = value


def load_v4_config(symbol: str | None, section: str, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Charge les paramètres d'une section avec priorité symbole > global > défaut.

    Args:
        symbol: paire ex. "BTC/USDT", ou None pour sauter les overrides symbole
        section: clé dans settings.yaml (ex. "risk", "signal", "exit")
        defaults: valeurs par défaut si rien dans le fichier

    Returns:
        dict fusionné avec les valeurs résolues.
    """
    result = dict(defaults or {})
    settings = _get_settings()

    # 1) Global
    section_cfg = settings.get(section, {})
    if isinstance(section_cfg, dict):
        result.update(section_cfg)

    # 2) Per-symbol override
    if symbol:
        assets_cfg = settings.get("assets", {})
        if isinstance(assets_cfg, dict):
            sym_cfg = assets_cfg.get(symbol, {})
            if isinstance(sym_cfg, dict):
                sym_section = sym_cfg.get(section, {})
                if isinstance(sym_section, dict):
                    result.update(sym_section)

    return result
