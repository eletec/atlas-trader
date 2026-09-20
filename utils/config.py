"""
utils/config.py — Loading and saving of settings.yaml with Pydantic validation.
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

# Lets you override the settings file through an environment variable
# e.g. SETTINGS_FILE=/app/config/settings.gx10.yaml in docker-compose.yml
_SETTINGS_PATH = Path(os.environ.get("SETTINGS_FILE", "config/settings.yaml"))

# Redirect to /app/data/ for writing (/app/src/config is a read-only Docker mount)
# Detection: /app/data only exists inside the Docker container (v4_storage volume)
if Path("/app/data").is_dir() and str(_SETTINGS_PATH).startswith("config/"):
    _RUNTIME_SETTINGS = Path("/app/data") / "settings.yaml"
    _RUNTIME_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    # Bootstrap: copy from git-tracked to /app/data/ on first launch
    if not _RUNTIME_SETTINGS.exists():
        _src = Path("/app/src") / _SETTINGS_PATH
        if _src.exists():
            import shutil
            shutil.copy2(_src, _RUNTIME_SETTINGS)
    _SETTINGS_PATH = _RUNTIME_SETTINGS
_ASSETS_DIR = Path("config/assets")


def load_settings(path: str | Path | None = None) -> dict:
    """
    Load settings.yaml — optional, returns {} when it is absent.

    settings.yaml is a leftover from the V2 strategy (directional + news crawler).
    The production strategy configuration is ONLY in
    config/carry_assets.yaml. We therefore no longer raise an exception when the
    file is missing: the application must start without it.
    """
    p = Path(path) if path else _SETTINGS_PATH
    if not p.exists():
        return {}

    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_settings(settings: dict, path: str | Path | None = None) -> None:
    """Save a settings dict into settings.yaml.

    Strategy: read the file from disk + deep-merge with the new values.
    This preserves the keys not managed by the dashboard (e.g. manual fixes,
    keys added by git pull while the dashboard is running).

    On a Docker bind-mount, an inter-filesystem os.rename() fails.
    We therefore write through an in-memory buffer → direct write to the target.
    """
    import io
    import stat as _stat

    p = Path(path) if path else _SETTINGS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)

    # Read the current file from disk and merge - preserves untouched keys
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

    # Try a direct write (avoid os.access, which can lie on bind-mounts)
    try:
        p.write_text(content, encoding="utf-8")
        return
    except PermissionError:
        pass

    # Write failed -> attempt a self-service chmod (works only as owner or root)
    try:
        p.chmod(p.stat().st_mode | _stat.S_IWUSR | _stat.S_IWGRP | _stat.S_IWOTH)
        p.write_text(content, encoding="utf-8")
        return
    except (PermissionError, OSError):
        raise PermissionError(
            f"Cannot write to {p} (permission denied).\n"
            f"On GX10: docker exec -u root atlas-trader-gx10 chmod 666 /app/config/settings.yaml\n"
            f"Then restart the container with 'user: \"0\"' in docker-compose.gx10.yml."
        )


def _asset_slug(asset: str) -> str:
    """'BTC/USDT' → 'BTC_USDT'"""
    return asset.replace("/", "_").replace(" ", "_")


def _carry_config_path() -> Path:
    """Effective path of carry_assets.yaml (runtime inside the container, repo otherwise)."""
    try:
        from v7.core.asset_config import config_path
        return config_path()
    except Exception:
        return _SETTINGS_PATH.parent / "carry_assets.yaml"


def load_asset_config(asset: str, base_path: str | Path | None = None) -> dict:
    """
    Load the asset-specific config from config/assets/{slug}.yaml
    and merge it onto settings.yaml (the asset yaml takes priority over the global one).

    Returns a complete dict usable by DecisionEngine, MarketDataAgent, etc.
    """
    global_cfg = load_settings(base_path)

    slug = _asset_slug(asset)
    asset_file = _ASSETS_DIR / f"{slug}.yaml"

    if not asset_file.exists():
        # No asset-specific config -> use the global one as-is
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

    # Deep merge: asset_cfg overrides global_cfg key by key
    merged = _deep_merge(copy.deepcopy(global_cfg), asset_cfg)
    return merged


def save_asset_config(asset: str, cfg: dict) -> None:
    """Save one asset config into config/assets/{slug}.yaml."""
    import stat
    # Use the absolute path derived from the settings file to stay consistent
    assets_dir = _SETTINGS_PATH.parent / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    # Fix the folder permissions when needed
    try:
        if not os.access(assets_dir, os.W_OK):
            assets_dir.chmod(assets_dir.stat().st_mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    except PermissionError:
        pass
    slug = _asset_slug(asset)
    path = assets_dir / f"{slug}.yaml"
    # Fix the file permissions when needed
    if path.exists() and not os.access(path, os.W_OK):
        try:
            path.chmod(path.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
        except PermissionError:
            raise PermissionError(
                f"Permission denied: {path}\n"
                f"On GX10: chmod -R 666 /app/config/assets/"
            )
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def export_config_zip() -> bytes:
    """
    Export the whole trader configuration into an in-memory ZIP file.

    ZIP content:
        settings.yaml               ← global config
        assets/BTC_USDT.yaml        ← per-asset configs
        assets/ETH_USDT.yaml
        ... (every file in config/assets/)

    Returns the ZIP bytes, ready to be downloaded (st.download_button).
    """
    import io
    import zipfile
    from datetime import datetime

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # carry_assets.yaml — THE carry strategy config (single source of truth).
        # Without it the backup protected nothing useful.
        carry_path = _carry_config_path()
        if carry_path.exists():
            zf.write(carry_path, arcname="carry_assets.yaml")

        # settings.yaml (or the active file via SETTINGS_FILE)
        settings_path = _SETTINGS_PATH
        if settings_path.exists():
            zf.write(settings_path, arcname="settings.yaml")

        # Every file in config/assets/*.yaml
        assets_dir = _SETTINGS_PATH.parent / "assets"
        if assets_dir.is_dir():
            for asset_file in sorted(assets_dir.glob("*.yaml")):
                zf.write(asset_file, arcname=f"assets/{asset_file.name}")

    return buf.getvalue()


def import_config_zip(zip_bytes: bytes, backup_first: bool = True) -> dict:
    """
    Restore the configuration from a ZIP exported by export_config_zip().

    Args:
        zip_bytes: content of the ZIP file to import
        backup_first: when True, back up the current state before overwriting

    Returns:
        dict with the keys:
            "restored_files": list[str]  — restored files
            "backup_path": str | None    — path of the prior backup
            "errors": list[str]          — non-blocking errors

    Raises:
        ValueError: when the ZIP is invalid or empty
        zipfile.BadZipFile: when the bytes do not form a valid ZIP
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
            raise ValueError("Empty ZIP - no file to restore.")

        # Safety check: no path traversal
        for name in names:
            clean = Path(name).as_posix()
            if ".." in clean or clean.startswith("/"):
                raise ValueError(f"Unauthorised path in the ZIP: {name!r}")

        # Prior backup (optional but enabled by default)
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
                errors.append(f"Pre-import backup failed (import aborted): {exc}")
                raise RuntimeError(errors[-1]) from exc

        # Restore
        config_dir = _SETTINGS_PATH.parent
        assets_dir = config_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        for name in names:
            # Only carry_assets.yaml, settings.yaml and assets/*.yaml are accepted
            p = Path(name)
            if p.name == "carry_assets.yaml" and len(p.parts) == 1:
                dest = _carry_config_path()
            elif p.name == "settings.yaml" and len(p.parts) == 1:
                # Restore into the active file (SETTINGS_FILE), not a hardcoded settings.yaml
                dest = _SETTINGS_PATH
            elif len(p.parts) == 2 and p.parts[0] == "assets" and p.suffix == ".yaml":
                dest = assets_dir / p.name
            else:
                errors.append(f"File skipped (out of scope): {name}")
                continue

            try:
                content = zf.read(name)
                # Basic YAML validation before overwriting
                yaml.safe_load(content)
                # Fix permissions when needed
                if dest.exists() and not os.access(dest, os.W_OK):
                    try:
                        dest.chmod(dest.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR)
                    except PermissionError:
                        errors.append(f"Permission denied: {dest}")
                        continue
                dest.write_bytes(content)
                restored.append(name)
            except yaml.YAMLError as ye:
                errors.append(f"Invalid YAML in {name}: {ye}")
            except Exception as exc:
                errors.append(f"Error restoring {name}: {exc}")

    if not restored:
        raise ValueError("No file could be restored. " + " | ".join(errors))

    return {
        "restored_files": restored,
        "backup_path": backup_path,
        "errors": errors,
    }


def list_config_backups() -> list[dict]:
    """
    List the backups available in config/backups/.

    Returns a sorted list (most recent first) of dicts:
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



    """Return the list of enabled assets from settings.yaml."""
    cfg = load_settings()
    return cfg.get("project", {}).get("active_assets", [
        cfg.get("project", {}).get("asset", "BTC/USDT")
    ])


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursive merge: override supersedes base, sub-dicts are merged.
    When a base key is a dict but override supplies a scalar, the base value is
    kept (a scalar from the asset YAML must not destroy a complex config).
    """
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        elif key in base and isinstance(base[key], dict) and not isinstance(val, (dict, list)):
            # A scalar tries to override a dict - ignore (e.g. exchange: 'binance' vs exchange: {...})
            pass
        else:
            base[key] = val
    return base


def get_active_assets() -> list[str]:
    """Return the complete list of active assets:
    project.active_assets (5m crypto) + quant.daily_active_assets (FX/metals daily).
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
    """Save settings.yaml while preserving the existing comments."""
    import stat
    p = Path(path) if path else _SETTINGS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    # Auto-fix permissions when the file exists but is not writable
    if p.exists() and not os.access(p, os.W_OK):
        try:
            current_mode = p.stat().st_mode
            p.chmod(current_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
        except PermissionError:
            raise PermissionError(
                f"Cannot write to {p} (permission denied).\n"
                f"On GX10, fix it with:\n"
                f"  chmod 666 {p}"
            )
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(settings, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False)


def hash_password(password: str) -> str:
    """Compute the SHA-256 of a password."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_admin_password(password: str, settings: dict) -> bool:
    """Verify the admin password."""
    stored = settings.get("admin", {}).get("password_hash", "")
    if not stored:
        # First run: hash it automatically from .env
        env_pass = os.getenv("ADMIN_PASSWORD", "changeme")
        return password == env_pass
    return hash_password(password) == stored


def get_env(key: str, required: bool = True, default: str | None = None) -> str | None:
    """Fetch an environment variable with validation."""
    value = os.getenv(key, default)
    if required and not value:
        raise EnvironmentError(
            f"Missing environment variable: {key}. "
            f"Check your .env file"
        )
    return value
