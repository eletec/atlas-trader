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
    """Charge settings.yaml avec cache (invalidation si fichier modifié)."""
    global _cache, _cache_mtime
    settings_path = Path(__file__).resolve().parent.parent.parent / "config" / "settings.yaml"
    try:
        mtime = settings_path.stat().st_mtime if settings_path.exists() else 0
        if _cache is not None and mtime == _cache_mtime:
            return _cache
        import yaml
        with settings_path.open("r", encoding="utf-8") as fh:
            _cache = yaml.safe_load(fh) or {}
        _cache_mtime = mtime
        return _cache
    except Exception:
        return _cache or {}


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
