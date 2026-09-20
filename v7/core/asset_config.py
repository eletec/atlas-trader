"""
v7/core/asset_config.py — Configuration loader for the Funding Carry assets.

Reads config/carry_assets.yaml and exposes the enabled assets with their parameters.
Used by the DAG factory, the backtest and the dashboard.

Paths:
- Container: /app/data/carry_assets.yaml  (runtime writable, volume v4_storage)
- Outside the container: config/carry_assets.yaml (repo copy, never duplicated)
- Override: V7_DATA_DIR environment variable
- Bootstrap: inside the container, if the runtime copy is missing, copy the repo one.
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
    """Active config path: /app/data inside the container, the repo otherwise."""
    if _IN_CONTAINER or "V7_DATA_DIR" in os.environ:
        return _RUNTIME_PATH
    return _GIT_PATH


def _bootstrap_config() -> Path:
    """Return the config file to read.

    Inside the container: /app/data/carry_assets.yaml (volume-backed), copied from
    the repo version on first start.
    Outside the container: the repo file directly (no stray copy).
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
    """Load the YAML config (runtime > git, with a cache)."""
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
    """Clear the cache and reload the config (after a scan or an external change)."""
    global _CACHE
    _CACHE = None
    return load_config()


def save_config(cfg: dict) -> None:
    """Save the YAML config (runtime inside the container, the repo otherwise)."""
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
    """Return the list of enabled symbols (enabled: true)."""
    cfg = load_config()
    assets = cfg.get("assets", {})
    return [sym for sym, params in assets.items() if params.get("enabled", False)]


def get_all_assets() -> list[str]:
    """Return ALL symbols (enabled and disabled)."""
    cfg = load_config()
    return list(cfg.get("assets", {}).keys())


def get_asset_params(symbol: str) -> dict[str, Any]:
    """Return the parameters of one specific asset."""
    cfg = load_config()
    return cfg.get("assets", {}).get(symbol, {})


def get_global_params() -> dict[str, Any]:
    """Return the global parameters."""
    cfg = load_config()
    return cfg.get("global", {})


def set_asset_enabled(symbol: str, enabled: bool) -> None:
    """Enable or disable an asset."""
    cfg = load_config()
    if symbol in cfg.get("assets", {}):
        cfg["assets"][symbol]["enabled"] = enabled
        save_config(cfg)


def update_asset_params(symbol: str, params: dict) -> None:
    """Update the parameters of one asset."""
    cfg = load_config()
    if symbol in cfg.get("assets", {}):
        cfg["assets"][symbol].update(params)
        save_config(cfg)


# ── Symbol normalisation ────────────────────────────────────────────────────
# Backtests accept freely typed CLI symbols (BTC, btcusdt,
# BTC/USDT, BTC/USDT:USDT). Without normalisation a short symbol makes the
# spot fetch fail and the backtest silently fell back to fabricated P&L.
_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD")


def normalize_symbol(raw: str) -> str:
    """Normalise a user symbol to the CCXT spot format "BASE/USDT".

    Accepts: BTC, btc, BTCUSDT, BTC/USDT, BTC/USDT:USDT, SHIB, 1000SHIB.
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
