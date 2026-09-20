"""
utils/logger.py — Configuration centralisée du logging
Rotation de fichiers + handler SQLite + re-export des fonctions utiles.
"""
from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Any


def setup_logging(
    level: str = "INFO",
    log_file: str = "logs/zeitgeist.log",
    max_bytes: int = 5_242_880,
    backup_count: int = 5,
    sqlite_db: str = "storage/zeitgeist.db",
    enable_sqlite: bool = True,
) -> None:
    """Configure the global application logging."""
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "detailed": {
                "format": "[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "simple": {
                "format": "%(levelname)-8s %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "simple",
                "level": level,
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": log_file,
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "formatter": "detailed",
                "level": "DEBUG",
                "encoding": "utf-8",
            },
        },
        "root": {
            "level": "DEBUG",
            "handlers": ["console", "file"],
        },
        "loggers": {
            "zeitgeist": {"level": level, "propagate": True},
            "httpx": {"level": "WARNING", "propagate": True},
            "ccxt": {"level": "WARNING", "propagate": True},
        },
    }

    logging.config.dictConfig(config)

    # Add the SQLite handler when the DB is available
    if enable_sqlite:
        try:
            from storage.database import SQLiteLogHandler, init_db
            init_db(sqlite_db)
            sqlite_handler = SQLiteLogHandler()
            sqlite_handler.setLevel(logging.INFO)
            logging.getLogger("zeitgeist").addHandler(sqlite_handler)
        except Exception as exc:
            logging.getLogger("zeitgeist").warning(
                f"Handler SQLite non disponible: {exc}"
            )

    logging.getLogger("zeitgeist").info("Logging initialised")


def log_flux_metric(
    flux_name: str,
    status: str,
    latency_ms: int = 0,
    items_count: int = 0,
    error_message: str | None = None,
) -> None:
    """Shortcut to record a flux metric."""
    try:
        from storage.database import log_flux_metric as _log
        _log(flux_name, status, latency_ms, items_count, error_message)
    except Exception:
        pass
