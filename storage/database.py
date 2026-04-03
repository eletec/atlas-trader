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
    """
    CREATE TABLE IF NOT EXISTS timesfm_forecasts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        cycle_id        TEXT    NOT NULL,
        timestamp       TEXT    NOT NULL,
        asset           TEXT    NOT NULL,
        horizon_candles INTEGER NOT NULL,
        current_price   REAL    NOT NULL,
        predicted_price REAL    NOT NULL,
        pct_change      REAL    NOT NULL,
        q10             REAL,
        q90             REAL,
        confidence      REAL,
        score           REAL,
        signal          TEXT,
        actual_price    REAL,                  -- rempli par post-mortem
        actual_change   REAL,                  -- rempli par post-mortem
        direction_hit   INTEGER,               -- 1 = correct, 0 = faux (post-mortem)
        evaluated_at    TEXT,                  -- timestamp du post-mortem
        latency_ms      INTEGER DEFAULT 0
    )
    """,
    # ── Shadow Decisions (profils de comparaison) ──
    """
    CREATE TABLE IF NOT EXISTS shadow_decisions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        cycle_id        TEXT    NOT NULL,
        profile_name    TEXT    NOT NULL,
        timestamp       TEXT    NOT NULL,
        asset           TEXT    NOT NULL,
        action          TEXT    NOT NULL,
        score           REAL    NOT NULL,
        entry_price     REAL,
        sl_price        REAL,
        tp_price        REAL,
        position_size   REAL,
        result_24h      REAL,
        config_snapshot TEXT,
        UNIQUE(cycle_id, profile_name)
    )
    """,
    # Index pour les requêtes fréquentes
    "CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_flux_name_ts ON flux_metrics(flux_name, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_tfm_ts ON timesfm_forecasts(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_shadow_profile ON shadow_decisions(profile_name, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_shadow_cycle ON shadow_decisions(cycle_id)",
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
                json.dumps(state.get("score_breakdown") or {}),  # scores bruts pour replay
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


# ===========================================================
# TIMESFM FORECASTS — tracking & évaluation
# ===========================================================

def log_timesfm_forecast(
    cycle_id: str,
    asset: str,
    forecast_details: dict,
    score: float,
    signal: str,
    confidence: float,
) -> None:
    """Persiste une prédiction TimesFM pour évaluation ultérieure."""
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO timesfm_forecasts
                (cycle_id, timestamp, asset, horizon_candles,
                 current_price, predicted_price, pct_change,
                 q10, q90, confidence, score, signal, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle_id,
                    datetime.utcnow().isoformat(),
                    asset,
                    forecast_details.get("horizon_candles", 24),
                    forecast_details.get("current_price", 0),
                    forecast_details.get("predicted_price", 0),
                    forecast_details.get("pct_change", 0),
                    forecast_details.get("q10"),
                    forecast_details.get("q90"),
                    confidence,
                    score,
                    signal,
                    forecast_details.get("latency_ms", 0),
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"Cannot log TimesFM forecast: {exc}")


def evaluate_timesfm_forecasts() -> int:
    """
    Post-mortem : évalue les prédictions TimesFM arrivées à échéance.
    Compare predicted_price vs prix réel après horizon_candles × 15min.
    Retourne le nombre de forecasts évalués.
    """
    import ccxt

    try:
        exchange = ccxt.binance({"enableRateLimit": True})
    except Exception as exc:
        logger.warning(f"Cannot init exchange for TimesFM eval: {exc}")
        return 0

    evaluated = 0
    now = datetime.utcnow()

    try:
        with get_connection() as conn:
            # Forecasts non encore évalués
            rows = conn.execute(
                """
                SELECT id, timestamp, asset, horizon_candles, current_price,
                       predicted_price, pct_change, signal
                FROM timesfm_forecasts
                WHERE actual_price IS NULL
                ORDER BY timestamp ASC
                LIMIT 50
                """
            ).fetchall()

            for row in rows:
                fc_time = datetime.fromisoformat(row["timestamp"])
                horizon_minutes = row["horizon_candles"] * 15
                target_time = fc_time + __import__("datetime").timedelta(minutes=horizon_minutes)

                if now < target_time:
                    continue  # pas encore arrivé à échéance

                # Récupérer le prix réel à l'échéance
                try:
                    ohlcv = exchange.fetch_ohlcv(
                        row["asset"], "15m",
                        since=int(target_time.timestamp() * 1000),
                        limit=1,
                    )
                    if not ohlcv:
                        continue
                    actual_price = float(ohlcv[0][4])  # close
                except Exception:
                    continue

                actual_change = ((actual_price - row["current_price"]) / row["current_price"]) * 100
                predicted_dir = 1 if row["pct_change"] >= 0 else -1
                actual_dir = 1 if actual_change >= 0 else -1
                direction_hit = 1 if predicted_dir == actual_dir else 0

                conn.execute(
                    """
                    UPDATE timesfm_forecasts
                    SET actual_price = ?, actual_change = ?,
                        direction_hit = ?, evaluated_at = ?
                    WHERE id = ?
                    """,
                    (actual_price, round(actual_change, 4), direction_hit,
                     now.isoformat(), row["id"]),
                )
                evaluated += 1

            if evaluated:
                conn.commit()
                logger.info(f"TimesFM post-mortem: {evaluated} forecasts evaluated")

    except Exception as exc:
        logger.warning(f"TimesFM evaluation error: {exc}")

    return evaluated


def get_timesfm_stats() -> dict:
    """
    Retourne les statistiques de performance TimesFM.
    - total: nb total de prédictions
    - evaluated: nb évaluées
    - direction_accuracy: % de bonnes directions
    - mae: erreur absolue moyenne (%)
    - avg_confidence: confiance moyenne
    - avg_latency_ms: latence moyenne
    - recent: les 10 dernières prédictions évaluées
    """
    try:
        with get_connection() as conn:
            # Stats globales
            row = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN actual_price IS NOT NULL THEN 1 ELSE 0 END) as evaluated,
                    AVG(CASE WHEN direction_hit IS NOT NULL THEN direction_hit END) as direction_accuracy,
                    AVG(CASE WHEN actual_change IS NOT NULL
                        THEN ABS(pct_change - actual_change) END) as mae,
                    AVG(confidence) as avg_confidence,
                    AVG(latency_ms) as avg_latency_ms
                FROM timesfm_forecasts
                """
            ).fetchone()

            stats = {
                "total": row["total"] or 0,
                "evaluated": row["evaluated"] or 0,
                "direction_accuracy": round(row["direction_accuracy"] * 100, 1) if row["direction_accuracy"] is not None else None,
                "mae": round(row["mae"], 3) if row["mae"] is not None else None,
                "avg_confidence": round(row["avg_confidence"], 2) if row["avg_confidence"] is not None else None,
                "avg_latency_ms": int(row["avg_latency_ms"]) if row["avg_latency_ms"] is not None else None,
            }

            # Dernières prédictions évaluées
            recent = conn.execute(
                """
                SELECT timestamp, current_price, predicted_price, pct_change,
                       actual_price, actual_change, direction_hit, confidence, signal
                FROM timesfm_forecasts
                WHERE actual_price IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT 10
                """
            ).fetchall()
            stats["recent"] = [dict(r) for r in recent]

            # Dernières prédictions en attente
            pending = conn.execute(
                """
                SELECT timestamp, current_price, predicted_price, pct_change,
                       confidence, signal, horizon_candles
                FROM timesfm_forecasts
                WHERE actual_price IS NULL
                ORDER BY timestamp DESC
                LIMIT 5
                """
            ).fetchall()
            stats["pending"] = [dict(r) for r in pending]

            return stats

    except Exception as exc:
        logger.warning(f"Cannot get TimesFM stats: {exc}")
        return {"total": 0, "evaluated": 0, "recent": [], "pending": []}


# ===========================================================
# SHADOW DECISIONS — Profils de comparaison
# ===========================================================

def log_shadow_decision(
    cycle_id: str,
    profile_name: str,
    timestamp: str,
    asset: str,
    decision: dict,
    config_snapshot: str = "{}",
) -> None:
    """Insère une décision shadow pour un profil donné."""
    action = decision.get("action", "HOLD")
    if action == "HOLD":
        return  # pas de log pour les HOLD (économie d'espace)

    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO shadow_decisions
                (cycle_id, profile_name, timestamp, asset, action, score,
                 entry_price, sl_price, tp_price, position_size, config_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle_id, profile_name, timestamp, asset, action,
                    decision.get("score", 50),
                    decision.get("entry_price"),
                    decision.get("sl_price"),
                    decision.get("tp_price"),
                    decision.get("position_size_usd"),
                    config_snapshot,
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"Shadow log [{profile_name}] erreur : {exc}")


def get_shadow_open_positions_for_profile(profile_name: str) -> list[dict]:
    """Retourne les positions shadow ouvertes pour un profil."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM shadow_decisions
                WHERE profile_name = ?
                  AND result_24h IS NULL
                  AND action IN ('BUY', 'SELL')
                ORDER BY timestamp ASC
                """,
                (profile_name,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def close_shadow_position(shadow_id: int, close_price: float) -> None:
    """Clôture une position shadow en calculant le P&L."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT action, entry_price, position_size FROM shadow_decisions WHERE id = ?",
                (shadow_id,),
            ).fetchone()
            if not row:
                return
            entry = float(row["entry_price"] or 0)
            size = float(row["position_size"] or 0)
            if entry <= 0 or size <= 0:
                return
            qty = size / entry
            if row["action"] == "BUY":
                pnl = (close_price - entry) * qty
            else:
                pnl = (entry - close_price) * qty
            conn.execute(
                "UPDATE shadow_decisions SET result_24h = ? WHERE id = ?",
                (round(pnl, 4), shadow_id),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"Shadow close position erreur : {exc}")


def get_shadow_pending_postmortems(delay_hours: int = 24) -> list[dict]:
    """Retourne les shadow decisions ouvertes depuis > delay_hours."""
    cutoff = datetime.utcnow().replace(microsecond=0).isoformat()
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM shadow_decisions
                WHERE result_24h IS NULL
                  AND action IN ('BUY', 'SELL')
                  AND datetime(timestamp, '+' || ? || ' hours') < datetime(?)
                """,
                (delay_hours, cutoff),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def update_shadow_result(shadow_id: int, result_24h: float) -> None:
    """Met à jour le P&L 24h d'une shadow decision."""
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE shadow_decisions SET result_24h = ? WHERE id = ?",
                (result_24h, shadow_id),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"Shadow update result erreur : {exc}")


def get_shadow_comparison_stats() -> list[dict]:
    """
    Retourne les statistiques agrégées par profil shadow.
    Inclut aussi le profil 'baseline' reconstitué depuis la table decisions.
    """
    stats = []
    try:
        with get_connection() as conn:
            # ── Stats des profils shadow ──
            rows = conn.execute(
                """
                SELECT
                    profile_name,
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN action = 'BUY' THEN 1 ELSE 0 END) as buys,
                    SUM(CASE WHEN action = 'SELL' THEN 1 ELSE 0 END) as sells,
                    SUM(CASE WHEN result_24h IS NOT NULL THEN 1 ELSE 0 END) as evaluated,
                    SUM(CASE WHEN result_24h > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN result_24h < 0 THEN 1 ELSE 0 END) as losses,
                    COALESCE(SUM(result_24h), 0) as total_pnl,
                    COALESCE(AVG(CASE WHEN result_24h IS NOT NULL THEN result_24h END), 0) as avg_pnl,
                    COALESCE(MAX(result_24h), 0) as best_trade,
                    COALESCE(MIN(result_24h), 0) as worst_trade,
                    MIN(timestamp) as first_trade,
                    MAX(timestamp) as last_trade
                FROM shadow_decisions
                GROUP BY profile_name
                ORDER BY total_pnl DESC
                """
            ).fetchall()

            for row in rows:
                evaluated = row["evaluated"] or 0
                wins = row["wins"] or 0
                stats.append({
                    "profile": row["profile_name"],
                    "total_trades": row["total_trades"],
                    "buys": row["buys"],
                    "sells": row["sells"],
                    "evaluated": evaluated,
                    "wins": wins,
                    "losses": row["losses"] or 0,
                    "win_rate": round(wins / evaluated * 100, 1) if evaluated > 0 else 0,
                    "total_pnl": round(row["total_pnl"], 2),
                    "avg_pnl": round(row["avg_pnl"], 2),
                    "best_trade": round(row["best_trade"], 2),
                    "worst_trade": round(row["worst_trade"], 2),
                    "first_trade": row["first_trade"],
                    "last_trade": row["last_trade"],
                })

            # ── Stats du profil baseline (depuis decisions) ──
            baseline_row = conn.execute(
                """
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN action = 'BUY' THEN 1 ELSE 0 END) as buys,
                    SUM(CASE WHEN action = 'SELL' THEN 1 ELSE 0 END) as sells,
                    SUM(CASE WHEN result_24h IS NOT NULL THEN 1 ELSE 0 END) as evaluated,
                    SUM(CASE WHEN result_24h > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN result_24h < 0 THEN 1 ELSE 0 END) as losses,
                    COALESCE(SUM(result_24h), 0) as total_pnl,
                    COALESCE(AVG(CASE WHEN result_24h IS NOT NULL THEN result_24h END), 0) as avg_pnl,
                    COALESCE(MAX(result_24h), 0) as best_trade,
                    COALESCE(MIN(result_24h), 0) as worst_trade,
                    MIN(timestamp) as first_trade,
                    MAX(timestamp) as last_trade
                FROM decisions
                WHERE action != 'HOLD'
                """
            ).fetchone()
            if baseline_row and baseline_row["total_trades"]:
                evaluated = baseline_row["evaluated"] or 0
                wins = baseline_row["wins"] or 0
                stats.insert(0, {
                    "profile": "baseline",
                    "total_trades": baseline_row["total_trades"],
                    "buys": baseline_row["buys"],
                    "sells": baseline_row["sells"],
                    "evaluated": evaluated,
                    "wins": wins,
                    "losses": baseline_row["losses"] or 0,
                    "win_rate": round(wins / evaluated * 100, 1) if evaluated > 0 else 0,
                    "total_pnl": round(baseline_row["total_pnl"], 2),
                    "avg_pnl": round(baseline_row["avg_pnl"], 2),
                    "best_trade": round(baseline_row["best_trade"], 2),
                    "worst_trade": round(baseline_row["worst_trade"], 2),
                    "first_trade": baseline_row["first_trade"],
                    "last_trade": baseline_row["last_trade"],
                })

    except Exception as exc:
        logger.warning(f"Shadow stats erreur : {exc}")

    # Ajouter les profils sans trades pour qu'ils apparaissent dans le tableau
    try:
        from comparison.shadow_runner import load_profiles
        all_profiles = load_profiles()
        existing = {s["profile"] for s in stats}
        for name, cfg in all_profiles.items():
            if cfg.get("active", False):
                continue  # baseline déjà inclus
            if name not in existing:
                stats.append({
                    "profile": name,
                    "total_trades": 0, "buys": 0, "sells": 0,
                    "evaluated": 0, "wins": 0, "losses": 0,
                    "win_rate": 0, "total_pnl": 0, "avg_pnl": 0,
                    "best_trade": 0, "worst_trade": 0,
                    "first_trade": None, "last_trade": None,
                })
    except Exception:
        pass

    return stats


def get_shadow_recent_decisions(n: int = 20) -> list[dict]:
    """Retourne les N dernières décisions shadow, tous profils confondus."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM shadow_decisions
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (n,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_shadow_pnl_series() -> dict[str, list[dict]]:
    """
    Retourne les courbes de P&L cumulé par profil shadow.
    Returns: {profile_name: [{timestamp, pnl, cumulative_pnl}, ...]}
    """
    series: dict[str, list[dict]] = {}
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT profile_name, timestamp, result_24h
                FROM shadow_decisions
                WHERE result_24h IS NOT NULL
                ORDER BY timestamp ASC
                """
            ).fetchall()

            for row in rows:
                name = row["profile_name"]
                if name not in series:
                    series[name] = []
                prev_cum = series[name][-1]["cumulative_pnl"] if series[name] else 0
                series[name].append({
                    "timestamp": row["timestamp"],
                    "pnl": row["result_24h"],
                    "cumulative_pnl": round(prev_cum + row["result_24h"], 2),
                })

            # Ajouter baseline depuis decisions
            baseline_rows = conn.execute(
                """
                SELECT timestamp, result_24h
                FROM decisions
                WHERE result_24h IS NOT NULL AND action != 'HOLD'
                ORDER BY timestamp ASC
                """
            ).fetchall()
            if baseline_rows:
                series["baseline"] = []
                for row in baseline_rows:
                    prev_cum = series["baseline"][-1]["cumulative_pnl"] if series["baseline"] else 0
                    series["baseline"].append({
                        "timestamp": row["timestamp"],
                        "pnl": row["result_24h"],
                        "cumulative_pnl": round(prev_cum + row["result_24h"], 2),
                    })
    except Exception as exc:
        logger.warning(f"Shadow PnL series erreur : {exc}")

    return series
