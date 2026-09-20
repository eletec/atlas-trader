"""
v7/core/asset_config.py — Chargeur de configuration des actifs Funding Carry.

Lit config/carry_assets.yaml et expose les actifs activés avec leurs paramètres.
Utilisé par la DAG factory, le backtest, et le dashboard.

Chemins :
- Container : /app/data/carry_assets.yaml  (runtime writable, volume v4_storage)
- Hors container : config/carry_assets.yaml (dépôt, jamais de copie parasite)
- Override : variable d'environnement V7_DATA_DIR
- Bootstrap : en container, si le runtime n'existe pas, copie depuis le dépôt.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("v7.core.asset_config")

# Runtime path (writable, persistent) - used INSIDE the container only
_APP_DATA = Path(os.environ.get("V7_DATA_DIR", "/app/data"))
_RUNTIME_PATH = _APP_DATA / "carry_assets.yaml"
# Git-tracked path (read-only inside the container)
_GIT_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "carry_assets.yaml"
# The repo is mounted into the container at /app/src: a reliable container marker.
# Outside the container (e.g. Windows), '/app/data' resolves to 'C:\app\data' and a
# stale file there would silently override the repo config -
# local backtests would then validate a different strategy than live.
_IN_CONTAINER = Path("/app/src").exists()
_CACHE: dict | None = None


def config_path() -> Path:
    """Chemin de config actif : /app/data en container, dépôt sinon."""
    if _IN_CONTAINER or "V7_DATA_DIR" in os.environ:
        return _RUNTIME_PATH
    return _GIT_PATH


def _bootstrap_config() -> Path:
    """Retourne le fichier de config à lire.

    En container : /app/data/carry_assets.yaml (persisté par le volume), copié
    depuis la version du dépôt au premier lancement.
    Hors container : directement la version du dépôt (aucune copie parasite).
    """
    runtime = config_path()
    if runtime != _RUNTIME_PATH:
        if not runtime.exists():
            logger.warning("No carry_assets.yaml found — using empty config")
        return runtime
    if runtime.exists():
        return runtime
    if _GIT_PATH.exists():
        runtime.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_GIT_PATH, runtime)
        logger.info("Bootstrapped carry_assets.yaml → %s", runtime)
        return runtime
    logger.warning("No carry_assets.yaml found — using empty config")
    return _GIT_PATH  # fallback (this path does not exist, but load_config handles it)


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
    """Sauvegarde la configuration YAML (runtime en container, dépôt sinon)."""
    global _CACHE
    path = config_path()
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


# ── Normalisation des symboles ────────────────────────────────────────────────
# Backtests accept freely typed CLI symbols (BTC, btcusdt,
# BTC/USDT, BTC/USDT:USDT). Without normalisation a short symbol makes the
# spot fetch fail and the backtest silently fell back to fabricated P&L.
_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD")


def normalize_symbol(raw: str) -> str:
    """Normalise un symbole utilisateur vers le format CCXT spot « BASE/USDT ».

    Accepte : BTC, btc, BTCUSDT, BTC/USDT, BTC/USDT:USDT, SHIB, 1000SHIB.
    """
    s = (raw or "").strip().upper().replace(" ", "")
    if not s:
        return ""
    if ":" in s:  # strip the perp suffix ':USDT'
        s = s.split(":", 1)[0]
    if "/" in s:
        base, _, quote = s.partition("/")
        return f"{base}/{quote or 'USDT'}"
    for quote in _QUOTES:  # strip an attached quote: 'BTCUSDT' -> 'BTC/USDT'
        if s.endswith(quote) and len(s) > len(quote):
            return f"{s[:-len(quote)]}/{quote}"
    return f"{s}/USDT"
