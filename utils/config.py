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

# Permet de surcharger le fichier settings via variable d'environnement
# Ex: SETTINGS_FILE=/app/config/settings.gx10.yaml dans docker-compose.yml
_SETTINGS_PATH = Path(os.environ.get("SETTINGS_FILE", "config/settings.yaml"))

# Rediriger vers /app/data/ pour écriture (Docker mount read-only sur /app/src/config)
# Détection : /app/data existe uniquement dans le conteneur Docker (volume v4_storage)
if Path("/app/data").is_dir() and str(_SETTINGS_PATH).startswith("config/"):
    _RUNTIME_SETTINGS = Path("/app/data") / "settings.yaml"
    _RUNTIME_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    # Bootstrap : copier du git-tracked vers /app/data/ au premier lancement
    if not _RUNTIME_SETTINGS.exists():
        _src = Path("/app/src") / _SETTINGS_PATH
        if _src.exists():
            import shutil
            shutil.copy2(_src, _RUNTIME_SETTINGS)
    _SETTINGS_PATH = _RUNTIME_SETTINGS
_ASSETS_DIR = Path("config/assets")


def load_settings(path: str | Path | None = None) -> dict:
    """
    Charge settings.yaml — optionnel, retourne {} s'il est absent.

    settings.yaml est un reliquat de la strategie V2 (directionnel + crawler news).
    La configuration de la strategie en production est UNIQUEMENT dans
    config/carry_assets.yaml. On ne leve donc plus d'exception si le fichier
    manque : l'application doit demarrer sans lui.
    """
    p = Path(path) if path else _SETTINGS_PATH
    if not p.exists():
        return {}

    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_settings(settings: dict, path: str | Path | None = None) -> None:
    """Sauvegarde un dict settings dans settings.yaml.

    Stratégie : lecture du fichier disque + deep-merge avec les nouvelles valeurs.
    Cela préserve les clés non gérées par le dashboard (ex: corrections manuelles,
    clés ajoutées par git pull pendant que le dashboard tourne).

    Sur bind-mount Docker, os.rename() inter-filesystem échoue.
    On écrit donc via un buffer en mémoire → write direct sur la cible.
    """
    import io
    import stat as _stat

    p = Path(path) if path else _SETTINGS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)

    # Lire le fichier courant sur disque et merger — préserve les clés non touchées
    if p.exists():
        try:
            on_disk = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            on_disk = {}
        merged = _deep_merge(copy.deepcopy(on_disk), settings)
    else:
        merged = settings

    import io
    buf = io.StringIO()
    yaml.dump(merged, buf, allow_unicode=True, default_flow_style=False,
              sort_keys=False, width=120)
    content = buf.getvalue()

    # Tentative d'écriture directe (sans passer par os.access qui peut mentir sur bind-mounts)
    try:
        p.write_text(content, encoding="utf-8")
        return
    except PermissionError:
        pass

    # Écriture échoue → tenter chmod self-service (ne fonctionne que si on est owner ou root)
    try:
        p.chmod(p.stat().st_mode | _stat.S_IWUSR | _stat.S_IWGRP | _stat.S_IWOTH)
        p.write_text(content, encoding="utf-8")
        return
    except (PermissionError, OSError):
        raise PermissionError(
            f"Impossible d'écrire dans {p} (permission refusée).\n"
            f"Sur GX10 : docker exec -u root atlas-trader-gx10 chmod 666 /app/config/settings.yaml\n"
            f"Puis redémarrez le container avec 'user: \"0\"' dans docker-compose.gx10.yml."
        )


def _asset_slug(asset: str) -> str:
    """'BTC/USDT' → 'BTC_USDT'"""
    return asset.replace("/", "_").replace(" ", "_")


def _carry_config_path() -> Path:
    """Chemin effectif de carry_assets.yaml (runtime en container, depot sinon)."""
    try:
        from v7.core.asset_config import config_path
        return config_path()
    except Exception:
        return _SETTINGS_PATH.parent / "carry_assets.yaml"


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

    try:
        raw_bytes = asset_file.read_bytes()
        try:
            raw_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = raw_bytes.decode("utf-8", errors="replace")
            # Re-save as clean UTF-8 to prevent future errors
            asset_file.write_text(raw_text, encoding="utf-8")
        asset_cfg = yaml.safe_load(raw_text) or {}
    except Exception:
        asset_cfg = {}

    # Merge profond : asset_cfg surcharge global_cfg clé par clé
    merged = _deep_merge(copy.deepcopy(global_cfg), asset_cfg)
    return merged


def save_asset_config(asset: str, cfg: dict) -> None:
    """Sauvegarde la config d'un actif dans config/assets/{slug}.yaml."""
    import stat
    # Utiliser le chemin absolu basé sur le fichier settings pour rester cohérent
    assets_dir = _SETTINGS_PATH.parent / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    # Fix permissions du dossier si nécessaire
    try:
        if not os.access(assets_dir, os.W_OK):
            assets_dir.chmod(assets_dir.stat().st_mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    except PermissionError:
        pass
    slug = _asset_slug(asset)
    path = assets_dir / f"{slug}.yaml"
    # Fix permissions du fichier si nécessaire
    if path.exists() and not os.access(path, os.W_OK):
        try:
            path.chmod(path.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
        except PermissionError:
            raise PermissionError(
                f"Permission refusée : {path}\n"
                f"Sur GX10 : chmod -R 666 /app/config/assets/"
            )
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def export_config_zip() -> bytes:
    """
    Exporte toute la configuration du trader dans un fichier ZIP en mémoire.

    Contenu du ZIP :
        settings.yaml               ← config globale
        assets/BTC_USDT.yaml        ← configs par actif
        assets/ETH_USDT.yaml
        ... (tous les fichiers dans config/assets/)

    Retourne les bytes du ZIP, prêts à être téléchargés (st.download_button).
    """
    import io
    import zipfile
    from datetime import datetime

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # carry_assets.yaml — LA config de la strategie carry (source unique de verite).
        # Sans elle, la sauvegarde ne protegeait rien d'utile.
        carry_path = _carry_config_path()
        if carry_path.exists():
            zf.write(carry_path, arcname="carry_assets.yaml")

        # settings.yaml (ou le fichier actif via SETTINGS_FILE)
        settings_path = _SETTINGS_PATH
        if settings_path.exists():
            zf.write(settings_path, arcname="settings.yaml")

        # Tous les fichiers config/assets/*.yaml
        assets_dir = _SETTINGS_PATH.parent / "assets"
        if assets_dir.is_dir():
            for asset_file in sorted(assets_dir.glob("*.yaml")):
                zf.write(asset_file, arcname=f"assets/{asset_file.name}")

    return buf.getvalue()


def import_config_zip(zip_bytes: bytes, backup_first: bool = True) -> dict:
    """
    Restaure la configuration depuis un ZIP exporté par export_config_zip().

    Args:
        zip_bytes: contenu du fichier ZIP à importer
        backup_first: si True, sauvegarde l'état actuel avant d'écraser

    Returns:
        dict avec les clés :
            "restored_files": list[str]  — fichiers restaurés
            "backup_path": str | None    — chemin de la sauvegarde préalable
            "errors": list[str]          — erreurs non bloquantes

    Raises:
        ValueError: si le ZIP est invalide ou vide
        zipfile.BadZipFile: si les bytes ne forment pas un ZIP valide
    """
    import io
    import zipfile
    import stat
    from datetime import datetime

    errors: list[str] = []
    restored: list[str] = []
    backup_path: str | None = None

    zf_io = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(zf_io, "r") as zf:
        names = zf.namelist()
        if not names:
            raise ValueError("ZIP vide — aucun fichier à restaurer.")

        # Vérification de sécurité : pas de path traversal
        for name in names:
            clean = Path(name).as_posix()
            if ".." in clean or clean.startswith("/"):
                raise ValueError(f"Chemin non autorisé dans le ZIP : {name!r}")

        # Sauvegarde préalable (optionnelle mais activée par défaut)
        if backup_first:
            try:
                backup_bytes = export_config_zip()
                ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                backup_dir = _SETTINGS_PATH.parent / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                bp = backup_dir / f"config_backup_{ts}.zip"
                bp.write_bytes(backup_bytes)
                backup_path = str(bp)
            except Exception as exc:
                errors.append(f"Sauvegarde préalable échouée (import annulé) : {exc}")
                raise RuntimeError(errors[-1]) from exc

        # Restauration
        config_dir = _SETTINGS_PATH.parent
        assets_dir = config_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        for name in names:
            # Seuls carry_assets.yaml, settings.yaml et assets/*.yaml sont acceptes
            p = Path(name)
            if p.name == "carry_assets.yaml" and len(p.parts) == 1:
                dest = _carry_config_path()
            elif p.name == "settings.yaml" and len(p.parts) == 1:
                # Restaurer vers le fichier actif (SETTINGS_FILE), pas settings.yaml hardcode
                dest = _SETTINGS_PATH
            elif len(p.parts) == 2 and p.parts[0] == "assets" and p.suffix == ".yaml":
                dest = assets_dir / p.name
            else:
                errors.append(f"Fichier ignoré (hors périmètre) : {name}")
                continue

            try:
                content = zf.read(name)
                # Validation YAML basique avant d'écraser
                yaml.safe_load(content)
                # Correction permissions si nécessaire
                if dest.exists() and not os.access(dest, os.W_OK):
                    try:
                        dest.chmod(dest.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR)
                    except PermissionError:
                        errors.append(f"Permission refusée : {dest}")
                        continue
                dest.write_bytes(content)
                restored.append(name)
            except yaml.YAMLError as ye:
                errors.append(f"YAML invalide dans {name} : {ye}")
            except Exception as exc:
                errors.append(f"Erreur lors de la restauration de {name} : {exc}")

    if not restored:
        raise ValueError("Aucun fichier n'a pu être restauré. " + " | ".join(errors))

    return {
        "restored_files": restored,
        "backup_path": backup_path,
        "errors": errors,
    }


def list_config_backups() -> list[dict]:
    """
    Liste les sauvegardes disponibles dans config/backups/.

    Retourne une liste triée (plus récent en premier) de dicts :
        {"filename": str, "path": Path, "size_kb": float, "mtime": datetime}
    """
    from datetime import datetime
    backup_dir = _SETTINGS_PATH.parent / "backups"
    if not backup_dir.is_dir():
        return []
    backups = []
    for f in backup_dir.glob("config_backup_*.zip"):
        try:
            stat = f.stat()
            backups.append({
                "filename": f.name,
                "path": f,
                "size_kb": round(stat.st_size / 1024, 1),
                "mtime": datetime.utcfromtimestamp(stat.st_mtime),
            })
        except Exception:
            continue
    backups.sort(key=lambda x: x["mtime"], reverse=True)
    return backups



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


def get_active_assets() -> list[str]:
    """Retourne la liste complète des actifs actifs :
    project.active_assets (crypto 5m) + quant.daily_active_assets (FX/métaux daily).
    """
    cfg = load_settings()
    intraday = list(cfg.get("project", {}).get("active_assets", []))
    daily = list(cfg.get("quant", {}).get("daily_active_assets", [])
                 or cfg.get("project", {}).get("daily_active_assets", []))
    combined = intraday + [a for a in daily if a not in intraday]
    if not combined:
        fallback = cfg.get("project", {}).get("asset", "BTC/USDT")
        return [fallback]
    return combined


def save_settings(settings: dict, path: str | Path | None = None) -> None:
    """Sauvegarde settings.yaml en préservant les commentaires existants."""
    import stat
    p = Path(path) if path else _SETTINGS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    # Auto-correction des permissions si le fichier existe mais n'est pas writable
    if p.exists() and not os.access(p, os.W_OK):
        try:
            current_mode = p.stat().st_mode
            p.chmod(current_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
        except PermissionError:
            raise PermissionError(
                f"Impossible d'écrire dans {p} (permission refusée).\n"
                f"Sur GX10, corrigez avec :\n"
                f"  chmod 666 {p}"
            )
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
