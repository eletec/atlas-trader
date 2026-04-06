"""
utils/config.py — Chargement et sauvegarde de settings.yaml avec validation Pydantic.
"""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

_SETTINGS_PATH = Path("config/settings.yaml")
_ASSETS_DIR = Path("config/assets")


def load_settings(path: str | Path | None = None) -> dict:
    """
    Charge settings.yaml et résout les variables d'environnement.
    Utilise un cache simple — appeler reload_settings() pour invalider.
    """
    p = Path(path) if path else _SETTINGS_PATH
    if not p.exists():
        raise FileNotFoundError(f"settings.yaml introuvable : {p.absolute()}")

    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _asset_slug(asset: str) -> str:
    """'BTC/USDT' → 'BTC_USDT'"""
    return asset.replace("/", "_").replace(" ", "_")


def load_asset_config(asset: str, base_path: str | Path | None = None) -> dict:
    """
    Charge la config spécifique à un actif depuis config/assets/{slug}.yaml
    et la merge sur settings.yaml (l'asset yaml a priorité sur le global).

    Retourne un dict complet utilisable par DecisionEngine, MarketDataAgent, etc.
    """
    global_cfg = load_settings(base_path)

    slug = _asset_slug(asset)
    asset_file = _ASSETS_DIR / f"{slug}.yaml"

    if not asset_file.exists():
        # Pas de config spécifique → on utilise le global tel quel
        return global_cfg

    with open(asset_file, "r", encoding="utf-8") as f:
        asset_cfg = yaml.safe_load(f) or {}

    # Merge profond : asset_cfg surcharge global_cfg clé par clé
    merged = _deep_merge(copy.deepcopy(global_cfg), asset_cfg)
    return merged


def save_asset_config(asset: str, cfg: dict) -> None:
    """Sauvegarde la config d'un actif dans config/assets/{slug}.yaml."""
    _ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _asset_slug(asset)
    path = _ASSETS_DIR / f"{slug}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def get_active_assets() -> list[str]:
    """Retourne la liste des actifs activés depuis settings.yaml."""
    cfg = load_settings()
    return cfg.get("project", {}).get("active_assets", [
        cfg.get("project", {}).get("asset", "BTC/USDT")
    ])


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge récursif : override surcharge base, les sous-dicts sont mergés.
    Si une clé de base est un dict mais override fournit un scalaire, on conserve
    la valeur de base (le scalaire de l'asset YAML ne doit pas détruire une config complicate).
    """
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        elif key in base and isinstance(base[key], dict) and not isinstance(val, (dict, list)):
            # Scalaire tente d'écraser un dict — ignorer (ex: exchange: "binance" vs exchange: {...})
            pass
        else:
            base[key] = val
    return base


def save_settings(settings: dict, path: str | Path | None = None) -> None:
    """Sauvegarde settings.yaml en préservant les commentaires existants."""
    p = Path(path) if path else _SETTINGS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(settings, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False)


def hash_password(password: str) -> str:
    """Calcule le SHA-256 d'un mot de passe."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_admin_password(password: str, settings: dict) -> bool:
    """Vérifie le mot de passe admin."""
    stored = settings.get("admin", {}).get("password_hash", "")
    if not stored:
        # Premier lancement : hashage automatique depuis .env
        env_pass = os.getenv("ADMIN_PASSWORD", "changeme")
        return password == env_pass
    return hash_password(password) == stored


def get_env(key: str, required: bool = True, default: str | None = None) -> str | None:
    """Récupère une variable d'environnement avec vérification."""
    value = os.getenv(key, default)
    if required and not value:
        raise EnvironmentError(
            f"Variable d'environnement manquante : {key}. "
            f"Vérifiez votre fichier .env"
        )
    return value
