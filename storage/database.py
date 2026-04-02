"""
storage/database.py — Couche d'accès SQLite
Gestion des décisions, simulations, métriques de flux et logs.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("zeitgeist.db")

# Chemin de la DB (configurable)
_DB_PATH = Path("storage/zeitgeist.db")
_lock = threading.Lock()


# ===========================================================
# INITIALISATION
# ===========================================================

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS decisions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        cycle_id        TEXT    UNIQUE NOT NULL,
        timestamp       TEXT    NOT NULL,
        asset           TEXT    NOT NULL,
        action          TEXT    NOT NULL,      -- BUY | SELL | HOLD
        score           REAL    NOT NULL,
        explanation     TEXT,
        entry_price     REAL,
        sl_price        REAL,
        tp_price        REAL,
        position_size   REAL,
        result_24h      REAL,                  -- P&L après 24h (NULL jusqu'au post-mortem)
        weights_snapshot TEXT,                 -- JSON des poids au moment de la décision
        llm_tokens      INTEGER DEFAULT 0,
        cycle_duration_ms INTEGER DEFAULT 0,
        errors          TEXT                   -- JSON array
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS simulations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        cycle_id    TEXT    NOT NULL,
        timestamp   TEXT    NOT NULL,
        n_agents    INTEGER NOT NULL,
        score       REAL    NOT NULL,
        narratives  TEXT,                      -- JSON array
        probas      TEXT,                      -- JSON {bull, bear, neutral}
        FOREIGN KEY (cycle_id) REFERENCES decisions(cycle_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS flux_metrics (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp     TEXT    NOT NULL,
        flux_name     TEXT    NOT NULL,
        status        TEXT    NOT NULL,        -- ok | error | timeout
        latency_ms    INTEGER DEFAULT 0,
        items_count   INTEGER DEFAULT 0,
        error_message TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS logs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp    TEXT NOT NULL,
        level        TEXT NOT NULL,
        module       TEXT NOT NULL,
        message      TEXT NOT NULL,
        context_json TEXT
    )
    """,
    # Index pour les requêtes fréquentes
    "CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_flux_name_ts ON flux_metrics(flux_name, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(timestamp DESC)",
]


def init_db(db_path: str | Path | None = None) -> None:
    """Crée la DB et les tables si elles n'existent pas."""
    global _DB_PATH
    if db_path:
        _DB_PATH = Path(db_path)

    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        for stmt in DDL_STATEMENTS:
            conn.execute(stmt)
        conn.commit()
    logger.info(f"Base de données initialisée : {_DB_PATH}")


@contextmanager
def get_connection():
    """Gestionnaire de contexte pour la connexion SQLite thread-safe."""
    with _lock:
        conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


# ===========================================================
# DÉCISIONS
# ===========================================================

def log_decision(cycle_id: str, state: dict, trade_result: dict | None = None) -> None:
    """Enregistre une décision de trading dans SQLite."""
    decision = state.get("decision") or {}
    mirofish = state.get("mirofish_result") or {}

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO decisions
            (cycle_id, timestamp, asset, action, score, explanation,
             entry_price, sl_price, tp_price, position_size,
             weights_snapshot, llm_tokens, cycle_duration_ms, errors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cycle_id,
                state.get("timestamp", datetime.utcnow().isoformat()),
                state.get("asset", ""),
                decision.get("action", "HOLD"),
                state.get("global_score", 50.0),
                decision.get("explanation", ""),
                decision.get("entry_price"),
                decision.get("sl_price"),
                decision.get("tp_price"),
                decision.get("position_size_usd"),
                json.dumps({}),  # poids actuels à injecter si dispo
                state.get("llm_tokens_used", 0),
                state.get("cycle_duration_ms", 0),
                json.dumps(state.get("errors", [])),
            )
        )

        # Enregistrer la simulation MiroFish liée
        if mirofish:
            conn.execute(
                """
                INSERT INTO simulations
                (cycle_id, timestamp, n_agents, score, narratives, probas)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle_id,
                    state.get("timestamp", datetime.utcnow().isoformat()),
                    mirofish.get("n_agents_used", 0),
                    mirofish.get("score", 50.0),
                    json.dumps(mirofish.get("narratives", [])),
                    json.dumps(mirofish.get("probas", {})),
                )
            )
        conn.commit()


def update_decision_result(cycle_id: str, result_24h: float) -> None:
    """Met à jour le P&L 24h après la décision (post-mortem)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE decisions SET result_24h = ? WHERE cycle_id = ?",
            (result_24h, cycle_id)
        )
        conn.commit()


def close_position(cycle_id: str, close_price: float, reason: str = "SL/TP") -> None:
    """Clôture une position ouverte en calculant le P&L réalisé.

    Le P&L = (close_price - entry_price) * (position_size / entry_price)
    Pour un BUY : gain si close > entry, perte si close < entry.
    Pour un SELL short : inverse.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT action, entry_price, position_size FROM decisions WHERE cycle_id = ?",
            (cycle_id,)
        ).fetchone()
        if not row:
            return
        action = row["action"]
        entry = float(row["entry_price"] or 0)
        size_usd = float(row["position_size"] or 0)
        if entry <= 0 or size_usd <= 0:
            return
        qty = size_usd / entry
        if action == "BUY":
            pnl = (close_price - entry) * qty
        else:
            pnl = (entry - close_price) * qty
        conn.execute(
            "UPDATE decisions SET result_24h = ?, explanation = explanation || ? WHERE cycle_id = ?",
            (round(pnl, 4), f"\n\n[Clôturé automatiquement — {reason} @ {close_price:.2f}]", cycle_id)
        )
        conn.commit()
    logger.info(f"Position {cycle_id} clôturée ({reason}) @ {close_price:.2f} → P&L={pnl:+.2f}$")


def get_open_positions() -> list[dict]:
    """Retourne les positions BUY/SELL ouvertes (result_24h IS NULL)."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM decisions
            WHERE result_24h IS NULL
              AND action IN ('BUY', 'SELL')
            ORDER BY timestamp ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def count_open_positions() -> int:
    """Compte les positions actuellement ouvertes."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM decisions WHERE result_24h IS NULL AND action IN ('BUY','SELL')"
        ).fetchone()
        return int(row["n"]) if row else 0


def get_recent_decisions(n: int = 50) -> list[dict]:
    """Retourne les N dernières décisions."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT ?", (n,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_pending_postmortems(delay_hours: int = 24) -> list[dict]:
    """Retourne les décisions sans résultat 24h et ayant le délai écoulé."""
    cutoff = (
        datetime.utcnow().replace(microsecond=0).isoformat()
    )
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM decisions
            WHERE result_24h IS NULL
              AND action != 'HOLD'
              AND datetime(timestamp, '+' || ? || ' hours') < datetime(?)
            """,
            (delay_hours, cutoff)
        ).fetchall()
        return [dict(row) for row in rows]


def get_pnl_history() -> list[dict]:
    """Retourne l'historique des P&L pour le dashboard."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT timestamp, action, score, result_24h, entry_price
            FROM decisions
            WHERE result_24h IS NOT NULL
            ORDER BY timestamp ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


# ===========================================================
# MÉTRIQUES DE FLUX
# ===========================================================

def log_flux_metric(
    flux_name: str,
    status: str,
    latency_ms: int = 0,
    items_count: int = 0,
    error_message: str | None = None
) -> None:
    """Enregistre une métrique de flux dans SQLite."""
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO flux_metrics
                (timestamp, flux_name, status, latency_ms, items_count, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.utcnow().isoformat(),
                    flux_name, status, latency_ms, items_count, error_message
                )
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"Impossible d'enregistrer la métrique flux {flux_name}: {exc}")


# ===========================================================
# LOGS DANS SQLite (handler optionnel)
# ===========================================================

class SQLiteLogHandler(logging.Handler):
    """Handler logging qui écrit dans la table logs SQLite."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO logs (timestamp, level, module, message, context_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        datetime.utcfromtimestamp(record.created).isoformat(),
                        record.levelname,
                        record.name,
                        record.getMessage(),
                        None,
                    )
                )
                conn.commit()
        except Exception:
            pass  # Ne jamais crasher à cause du logging
