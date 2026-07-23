"""
v7/core/asset_config.py — Chargeur de configuration des actifs Funding Carry.

Lit config/carry_assets.yaml et expose les actifs activés avec leurs paramètres.
Utilisé par la DAG factory, le backtest, et le dashboard.

Chemins :
- Runtime (writable) : /app/data/carry_assets.yaml  (volume v4_storage)
- Git-tracked (read-only) : config/carry_assets.yaml
- Bootstrap : si le runtime n'existe pas, copie depuis le git-tracked.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("v7.core.asset_config")

# Chemin runtime (writable, persistant) — prioritaire
_RUNTIME_PATH = Path("/app/data/carry_assets.yaml")
# Chemin git-tracked (read-only dans le container)
_GIT_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "carry_assets.yaml"
_CACHE: dict | None = None


def _bootstrap_config() -> Path:
    """Copie le fichier git-tracked vers /app/data/ au premier lancement."""
    if _RUNTIME_PATH.exists():
        return _RUNTIME_PATH
    if _GIT_PATH.exists():
        _RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_GIT_PATH, _RUNTIME_PATH)
        logger.info("Bootstrapped carry_assets.yaml → /app/data/")
        return _RUNTIME_PATH
    logger.warning("No carry_assets.yaml found — using empty config")
    return _GIT_PATH  # fallback (n'existe pas, mais load_config gère)


def load_config() -> dict:
    """Charge la configuration YAML (runtime > git, avec cache)."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = _bootstrap_config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            _CACHE = yaml.safe_load(f) or {}
        logger.info("Loaded carry_assets.yaml from %s: %d assets", path, len(_CACHE.get("assets", {})))
    except Exception as e:
        logger.warning("Cannot load carry_assets.yaml: %s — using defaults", e)
        _CACHE = {"assets": {}, "global": {}}
    return _CACHE


def reload_config() -> dict:
    """Vide le cache et recharge la configuration (après un scan ou une modif externe)."""
    global _CACHE
    _CACHE = None
    return load_config()


def save_config(cfg: dict) -> None:
    """Sauvegarde la configuration YAML dans /app/data/ (writable)."""
    global _CACHE
    path = _RUNTIME_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
        _CACHE = cfg
        logger.info("Saved carry_assets.yaml → %s", path)
    except Exception as e:
        logger.error("Cannot save carry_assets.yaml: %s", e)


def get_active_assets() -> list[str]:
    """Retourne la liste des symboles activés (enabled: true)."""
    cfg = load_config()
    assets = cfg.get("assets", {})
    return [sym for sym, params in assets.items() if params.get("enabled", False)]


def get_all_assets() -> list[str]:
    """Retourne TOUS les symboles (actifs et inactifs)."""
    cfg = load_config()
    return list(cfg.get("assets", {}).keys())


def get_asset_params(symbol: str) -> dict[str, Any]:
    """Retourne les paramètres d'un actif spécifique."""
    cfg = load_config()
    return cfg.get("assets", {}).get(symbol, {})


def get_global_params() -> dict[str, Any]:
    """Retourne les paramètres globaux."""
    cfg = load_config()
    return cfg.get("global", {})


def set_asset_enabled(symbol: str, enabled: bool) -> None:
    """Active ou désactive un actif."""
    cfg = load_config()
    if symbol in cfg.get("assets", {}):
        cfg["assets"][symbol]["enabled"] = enabled
        save_config(cfg)


def update_asset_params(symbol: str, params: dict) -> None:
    """Met à jour les paramètres d'un actif."""
    cfg = load_config()
    if symbol in cfg.get("assets", {}):
        cfg["assets"][symbol].update(params)
        save_config(cfg)
