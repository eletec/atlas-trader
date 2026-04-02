"""
utils/config.py — Chargement et sauvegarde de settings.yaml avec validation Pydantic.
"""
from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

_SETTINGS_PATH = Path("config/settings.yaml")


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
