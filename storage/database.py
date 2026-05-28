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

# Chemin de la DB (configurable) : ancré sur le dossier du module,
# indépendant du répertoire courant (dashboard, daemon, tests, etc.).
_DB_PATH = Path(__file__).resolve().parent / "zeitgeist.db"
_lock = threading.RLock()  # RLock (réentrant) — évite le deadlock si logger appelle get_connection()


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
        reflection_done INTEGER DEFAULT 0,     -- 1 = leçon LLM déjà générée
        weights_snapshot TEXT,                 -- JSON des poids au moment de la décision
        decision_context TEXT,                  -- JSON complet : market_indicators + agent_summaries + effective_weights + reasoning
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
    # ── Méta-analyses LLM (patterns d'échec) ──
    """
    CREATE TABLE IF NOT EXISTS meta_analyses (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT    NOT NULL,
        asset           TEXT,              -- NULL = analyse globale multi-actifs
        summary_text    TEXT    NOT NULL,  -- Markdown rendu par le LLM
        patterns_json   TEXT,              -- JSON structuré (patterns, recos, agents_faibles)
        n_trades        INTEGER DEFAULT 0,
        n_losing        INTEGER DEFAULT 0,
        run_trigger     TEXT    DEFAULT 'auto'  -- 'auto' | 'manual'
    )
    """,
    # ── Kronos Forecasts (AAAI 2026 foundation model) ──
    """
    CREATE TABLE IF NOT EXISTS kronos_forecasts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        cycle_id        TEXT    NOT NULL,
        timestamp       TEXT    NOT NULL,
        asset           TEXT    NOT NULL,
        model_name      TEXT    NOT NULL DEFAULT 'NeoQuasar/Kronos-mini',
        horizon_candles INTEGER NOT NULL,
        current_price   REAL    NOT NULL,
        predicted_price REAL    NOT NULL,
        pct_change      REAL    NOT NULL,
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
    "CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_flux_name_ts ON flux_metrics(flux_name, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_tfm_ts ON timesfm_forecasts(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_kronos_ts ON kronos_forecasts(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_shadow_profile ON shadow_decisions(profile_name, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_shadow_cycle ON shadow_decisions(cycle_id)",
    "CREATE INDEX IF NOT EXISTS idx_meta_ts ON meta_analyses(timestamp DESC)",
    # ── V2 quant state (une seule ligne mise à jour à chaque barre) ──────────
    """
    CREATE TABLE IF NOT EXISTS v2_state (
        id              INTEGER PRIMARY KEY DEFAULT 1,
        updated_at      TEXT    NOT NULL,
        asset           TEXT    NOT NULL DEFAULT 'BTC/USDT',
        bar_ts          TEXT,
        close_price     REAL,
        regime          INTEGER,    -- 1=trending, 0=ranging, NULL=inconnu
        prob_up         REAL,       -- P(up) ∈ [0,1] ou NULL
        action          TEXT,       -- long | short | flat
        reason          TEXT,
        atr_14          REAL,
        position_side   TEXT,       -- long | short | NULL (si pas de position)
        entry_price     REAL,
        sl_price        REAL,
        tp_price        REAL,
        capital         REAL,
        model_fit_at    TEXT        -- timestamp dernier ré-entraînement
    )
    """,
    # ── V2 equity curve (une ligne par barre traitée) ─────────────────────────
    """
    CREATE TABLE IF NOT EXISTS v2_equity (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          TEXT    NOT NULL,
        asset       TEXT    NOT NULL,
        equity      REAL    NOT NULL,
        action      TEXT,
        close_price REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_v2_equity_ts ON v2_equity(ts DESC)",
]


def init_db(db_path: str | Path | None = None) -> None:
    """Crée la DB et les tables si elles n'existent pas."""
    global _DB_PATH
    if db_path:
        # S8: empêche la traversée de répertoire
        _allowed_root = Path(__file__).resolve().parent
        resolved = Path(db_path).resolve()
        if not str(resolved).startswith(str(_allowed_root)):
            raise ValueError(f"Chemin de DB non autorisé: {db_path!r}")
        _DB_PATH = resolved

    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        # P2: WAL mode — lectures concurrentes pendant une écriture
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        for stmt in DDL_STATEMENTS:
            conn.execute(stmt)
        # Migrations V1 → V2 : ajouter les colonnes manquantes sans casser l'existant
        _migrate_v2(conn)
        conn.commit()
    logger.info(f"Base de données initialisée : {_DB_PATH}")
    _start_sqlite_log_writer()


def _migrate_v2(conn) -> None:
    """Migrations idempotentes V1 → V2 — ajoute les colonnes manquantes."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(decisions)")}
    migrations = [
        ("asset",             "ALTER TABLE decisions ADD COLUMN asset TEXT NOT NULL DEFAULT 'BTC/USDT'"),
        ("weights_snapshot",  "ALTER TABLE decisions ADD COLUMN weights_snapshot TEXT"),
        ("decision_context",  "ALTER TABLE decisions ADD COLUMN decision_context TEXT"),
        ("llm_tokens",        "ALTER TABLE decisions ADD COLUMN llm_tokens INTEGER DEFAULT 0"),
        ("cycle_duration_ms", "ALTER TABLE decisions ADD COLUMN cycle_duration_ms INTEGER DEFAULT 0"),
        ("errors",            "ALTER TABLE decisions ADD COLUMN errors TEXT"),
        ("reflection_done",   "ALTER TABLE decisions ADD COLUMN reflection_done INTEGER DEFAULT 0"),
    ]
    for col, stmt in migrations:
        if col not in existing:
            try:
                conn.execute(stmt)
                logger.info(f"Migration DB: colonne '{col}' ajoutée à decisions")
            except Exception as exc:
                logger.warning(f"Migration '{col}' ignorée: {exc}")

    # Nettoyage : les lignes SELL orphelines (result_24h IS NULL) sont des signaux
    # de sortie, pas des shorts réels. On les clôture proprement (P&L=0).
    # Système long-only spot — les SELL ne sont jamais des positions ouvertes.
    try:
        n = conn.execute(
            "UPDATE decisions SET result_24h = 0.0 WHERE action = 'SELL' AND result_24h IS NULL"
        ).rowcount
        if n > 0:
            logger.info(f"Nettoyage DB: {n} ligne(s) SELL orpheline(s) clôturée(s) (result_24h=0)")
    except Exception as exc:
        logger.warning(f"Nettoyage SELL orphelins ignoré: {exc}")


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

    # Construire le contexte de décision complet pour audit/replay
    market_ind = state.get("market_indicators") or {}
    agent_analyses = state.get("agent_analyses") or {}
    score_breakdown = state.get("score_breakdown") or {}
    decision_context = {
        # Prix et indicateurs techniques au moment de la décision
        "market": {
            "price":        market_ind.get("price"),
            "rsi_14":       market_ind.get("rsi_14"),
            "macd":         market_ind.get("macd"),
            "macd_signal":  market_ind.get("macd_signal"),
            "bb_upper":     market_ind.get("bb_upper"),
            "bb_lower":     market_ind.get("bb_lower"),
            "atr_14":       market_ind.get("atr_14"),
            "volume_24h":   market_ind.get("volume_24h"),
            "funding_rate": market_ind.get("funding_rate"),
            "ma_50":        market_ind.get("ma_50"),
            "above_ma50":   market_ind.get("above_ma50"),
        },
        # Score et signal de chaque agent
        "agents": {
            name: {
                "score":   a.get("score"),
                "signal":  a.get("signal"),
                "summary": a.get("summary", "")[:500],  # tronqué à 500 chars
                # Champs supplémentaires pour la synthèse (débat + signal 5-niveaux)
                **(
                    {
                        "signal_detail": a.get("signal_detail"),
                        "debate_winner": a.get("debate_winner"),
                        "bull_argument": (a.get("bull_argument") or "")[:600],
                        "bear_argument": (a.get("bear_argument") or "")[:600],
                    }
                    if name == "synthesis"
                    else {}
                ),
            }
            for name, a in agent_analyses.items()
            if isinstance(a, dict)
        },
        # Poids effectifs utilisés (après alpha_combination éventuel)
        "effective_weights": score_breakdown.get("breakdown", {}),
        # Scores composants
        "scores": {
            "mirofish":   score_breakdown.get("mirofish_score"),
            "market":     score_breakdown.get("market_score"),
            "contrarian": score_breakdown.get("contrarian_score"),
            "agents_raw": score_breakdown.get("agent_scores"),
        },
        # Régime de marché
        "regime": {
            "state":              score_breakdown.get("regime"),
            "hmm_prob":           score_breakdown.get("hmm_prob"),
            "direction_pressure": score_breakdown.get("direction_pressure"),
        },
        # Reasoning de la décision
        "decision": {
            "action":         decision.get("action"),
            "score":          state.get("global_score"),
            "buy_threshold":  decision.get("buy_threshold"),
            "exit_threshold": decision.get("exit_threshold"),
            "reasoning":      decision.get("reasoning", ""),
        },
    }

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO decisions
            (cycle_id, timestamp, asset, action, score, explanation,
             entry_price, sl_price, tp_price, position_size,
             weights_snapshot, decision_context, llm_tokens, cycle_duration_ms, errors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(score_breakdown),  # scores bruts pour replay
                json.dumps(decision_context),  # contexte complet pour audit
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


def mark_reflection_done(cycle_id: str) -> None:
    """Marque la réflexion LLM comme complète pour éviter les doublons."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE decisions SET reflection_done = 1 WHERE cycle_id = ?",
            (cycle_id,)
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
            "SELECT action, entry_price, position_size, sl_price, tp_price, timestamp, asset, score FROM decisions WHERE cycle_id = ?",
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
            (round(pnl, 4), f"\n\n[Auto-closed — {reason} @ {close_price:.2f}]", cycle_id)
        )
        conn.commit()

    # ── Audit log complet de la transaction ───────────────────────────────
    pnl_pct = (close_price - entry) / entry * 100 if entry > 0 else 0
    # Durée de la position
    try:
        from datetime import datetime as _dt
        open_ts = _dt.fromisoformat(row["timestamp"].replace("Z", "+00:00").replace("+00:00", ""))
        hold_min = int((_dt.utcnow() - open_ts).total_seconds() / 60)
        hold_str = f"{hold_min // 60}h{hold_min % 60:02d}m" if hold_min >= 60 else f"{hold_min}m"
    except Exception:
        hold_str = "?"
    sl = row["sl_price"] or 0
    tp = row["tp_price"] or 0
    asset = row["asset"] or "?"
    score = row["score"] or 0
    logger.info(
        f"TRADE CLOSE │ {asset} │ {cycle_id[:8]} │ "
        f"entry={entry:.2f} close={close_price:.2f} │ "
        f"size=${size_usd:.0f} qty={qty:.6f} │ "
        f"SL={sl:.2f} TP={tp:.2f} │ "
        f"P&L={pnl:+.2f}$ ({pnl_pct:+.2f}%) │ "
        f"durée={hold_str} │ raison={reason} │ score={score:.0f}"
    )


def get_open_positions() -> list[dict]:
    """Retourne les positions BUY ouvertes (long-only spot, result_24h IS NULL)."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM decisions
            WHERE result_24h IS NULL
              AND action = 'BUY'
            ORDER BY timestamp ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def count_open_positions(asset: str | None = None) -> int:
    """Compte les positions BUY actuellement ouvertes. Filtré par actif si précisé."""
    with get_connection() as conn:
        if asset:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM decisions WHERE result_24h IS NULL AND action = 'BUY' AND asset = ?",
                (asset,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM decisions WHERE result_24h IS NULL AND action = 'BUY'"
            ).fetchone()
        return int(row["n"]) if row else 0


def get_last_action_minutes_ago(asset: str, action: str) -> float | None:
    """Retourne le nombre de minutes depuis la dernière action pour cet actif, ou None si aucune."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT timestamp FROM decisions WHERE asset = ? AND action = ? ORDER BY timestamp DESC LIMIT 1",
            (asset, action),
        ).fetchone()
    if not row:
        return None
    try:
        ts = datetime.fromisoformat(row["timestamp"])
        return (datetime.utcnow() - ts).total_seconds() / 60.0
    except Exception:
        return None


def get_closed_trade_stats(asset: str | None = None, min_trades: int = 5) -> dict:
    """Retourne win_rate et rr_ratio réels depuis les trades BUY fermés.

    Retourne {} si pas assez de données (< min_trades).
    """
    with get_connection() as conn:
        if asset:
            rows = conn.execute(
                "SELECT result_24h FROM decisions WHERE action = 'BUY' AND result_24h IS NOT NULL "
                "AND asset = ? ORDER BY timestamp DESC LIMIT 50",
                (asset,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT result_24h FROM decisions WHERE action = 'BUY' AND result_24h IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 50"
            ).fetchall()
    pnls = [float(r["result_24h"]) for r in rows if r["result_24h"] is not None]
    if len(pnls) < min_trades:
        return {}
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(pnls)
    avg_win  = sum(wins)   / len(wins)   if wins   else 0.01
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.01
    rr_ratio = avg_win / avg_loss
    return {"win_rate": win_rate, "avg_win": avg_win, "avg_loss": avg_loss,
            "rr_ratio": rr_ratio, "n_trades": len(pnls)}


def get_recent_decisions(n: int = 50, asset: str | None = None) -> list[dict]:
    """Retourne les N dernières décisions, filtré par actif si précisé."""
    with get_connection() as conn:
        if asset:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE asset = ? ORDER BY timestamp DESC LIMIT ?",
                (asset, n),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT ?", (n,)
            ).fetchall()
        return [dict(row) for row in rows]


def count_trades(asset: str | None = None) -> int:
    """Nombre total de trades BUY/SELL dans la table decisions (sans limite)."""
    with get_connection() as conn:
        if asset:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM decisions WHERE action IN ('BUY','SELL') AND asset = ?",
                (asset,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM decisions WHERE action IN ('BUY','SELL')"
            ).fetchone()
    n = int(row["n"]) if row else 0
    if n > 0:
        return n

    # Fallback V2: les décisions live V2 sont historisées dans v2_decisions
    # avec action {long, short, flat}.
    with get_connection() as conn:
        try:
            if asset:
                row_v2 = conn.execute(
                    "SELECT COUNT(*) as n FROM v2_decisions "
                    "WHERE LOWER(action) IN ('long','short') AND asset = ?",
                    (asset,),
                ).fetchone()
            else:
                row_v2 = conn.execute(
                    "SELECT COUNT(*) as n FROM v2_decisions "
                    "WHERE LOWER(action) IN ('long','short')"
                ).fetchone()
            return int(row_v2["n"]) if row_v2 else 0
        except sqlite3.Error:
            return 0


def get_recent_trades(n: int = 200, asset: str | None = None) -> list[dict]:
    """P3: retourne les n derniers BUY/SELL (sans HOLD) — filtre SQL, pas Python."""
    with get_connection() as conn:
        if asset:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE action IN ('BUY', 'SELL') AND asset = ? "
                "ORDER BY timestamp DESC LIMIT ?", (asset, n)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE action IN ('BUY', 'SELL') "
                "ORDER BY timestamp DESC LIMIT ?", (n,)
            ).fetchall()
    trades = [dict(row) for row in rows]
    if trades:
        return trades

    # Fallback V2: mapper v2_decisions vers le schéma historique attendu
    # par le dashboard (timestamp/action/entry_price/SL/TP/result_24h/score).
    with get_connection() as conn:
        try:
            if asset:
                rows_v2 = conn.execute(
                    """
                    WITH entries AS (
                        SELECT
                            id, ts, asset, action, close_price,
                            sl_price, tp_price, prob_up, reason, capital,
                            position_size_usd, realized_pnl
                        FROM v2_decisions
                        WHERE LOWER(action) IN ('long','short') AND asset = ?
                    )
                    SELECT
                        e.ts AS timestamp,
                        e.asset,
                        CASE
                            WHEN LOWER(e.action) = 'long'  THEN 'BUY'
                            WHEN LOWER(e.action) = 'short' THEN 'SELL'
                            ELSE UPPER(e.action)
                        END AS action,
                        e.close_price AS entry_price,
                        NULL AS position_size,
                        e.sl_price,
                        e.tp_price,
                        ROUND(COALESCE(
                            e.realized_pnl,
                            (
                                SELECT d2.realized_pnl
                                FROM v2_decisions d2
                                WHERE d2.asset = e.asset
                                  AND d2.id > e.id
                                  AND d2.realized_pnl IS NOT NULL
                                ORDER BY d2.id ASC
                                LIMIT 1
                            )
                        ), 2) AS result_24h,
                        e.position_size_usd,
                        ROUND(COALESCE(e.prob_up, 0) * 100.0, 1) AS score,
                        e.reason,
                        NULL AS decision_context
                    FROM entries e
                    ORDER BY e.id DESC
                    LIMIT ?
                    """,
                    (asset, n),
                ).fetchall()
            else:
                rows_v2 = conn.execute(
                    """
                    WITH entries AS (
                        SELECT
                            id, ts, asset, action, close_price,
                            sl_price, tp_price, prob_up, reason, capital,
                            position_size_usd, realized_pnl
                        FROM v2_decisions
                        WHERE LOWER(action) IN ('long','short')
                    )
                    SELECT
                        e.ts AS timestamp,
                        e.asset,
                        CASE
                            WHEN LOWER(e.action) = 'long'  THEN 'BUY'
                            WHEN LOWER(e.action) = 'short' THEN 'SELL'
                            ELSE UPPER(e.action)
                        END AS action,
                        e.close_price AS entry_price,
                        NULL AS position_size,
                        e.sl_price,
                        e.tp_price,
                        ROUND(COALESCE(
                            e.realized_pnl,
                            (
                                SELECT d2.realized_pnl
                                FROM v2_decisions d2
                                WHERE d2.asset = e.asset
                                  AND d2.id > e.id
                                  AND d2.realized_pnl IS NOT NULL
                                ORDER BY d2.id ASC
                                LIMIT 1
                            )
                        ), 2) AS result_24h,
                        e.position_size_usd,
                        ROUND(COALESCE(e.prob_up, 0) * 100.0, 1) AS score,
                        e.reason,
                        NULL AS decision_context
                    FROM entries e
                    ORDER BY e.id DESC
                    LIMIT ?
                    """,
                    (n,),
                ).fetchall()
                        NULL AS decision_context
                    FROM v2m
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (n,),
                ).fetchall()
            return [dict(row) for row in rows_v2]
        except sqlite3.Error:
            try:
                if asset:
                    rows_v2 = conn.execute(
                        """
                        WITH v2m AS (
                            SELECT
                                id,
                                ts,
                                asset,
                                action,
                                close_price,
                                sl_price,
                                tp_price,
                                prob_up,
                                reason,
                                capital,
                                capital - LAG(capital) OVER (PARTITION BY asset ORDER BY id) AS pnl_step
                            FROM v2_decisions
                            WHERE LOWER(action) IN ('long','short') AND asset = ?
                        )
                        SELECT
                            ts AS timestamp,
                            asset,
                            CASE
                                WHEN LOWER(action) = 'long'  THEN 'BUY'
                                WHEN LOWER(action) = 'short' THEN 'SELL'
                                ELSE UPPER(action)
                            END AS action,
                            close_price AS entry_price,
                            NULL AS position_size,
                            sl_price,
                            tp_price,
                            CASE
                                WHEN pnl_step IS NULL THEN NULL
                                WHEN ABS(pnl_step) > 500 THEN NULL
                                WHEN ABS(pnl_step) < 0.01 THEN NULL
                                ELSE ROUND(pnl_step, 2)
                            END AS result_24h,
                            ROUND(COALESCE(prob_up, 0) * 100.0, 1) AS score,
                            reason,
                            NULL AS decision_context
                        FROM v2m
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (asset, n),
                    ).fetchall()
                else:
                    rows_v2 = conn.execute(
                        """
                        WITH v2m AS (
                            SELECT
                                id,
                                ts,
                                asset,
                                action,
                                close_price,
                                sl_price,
                                tp_price,
                                prob_up,
                                reason,
                                capital,
                                capital - LAG(capital) OVER (PARTITION BY asset ORDER BY id) AS pnl_step
                            FROM v2_decisions
                            WHERE LOWER(action) IN ('long','short')
                        )
                        SELECT
                            ts AS timestamp,
                            asset,
                            CASE
                                WHEN LOWER(action) = 'long'  THEN 'BUY'
                                WHEN LOWER(action) = 'short' THEN 'SELL'
                                ELSE UPPER(action)
                            END AS action,
                            close_price AS entry_price,
                            NULL AS position_size,
                            sl_price,
                            tp_price,
                            CASE
                                WHEN pnl_step IS NULL THEN NULL
                                WHEN ABS(pnl_step) > 500 THEN NULL
                                WHEN ABS(pnl_step) < 0.01 THEN NULL
                                ELSE ROUND(pnl_step, 2)
                            END AS result_24h,
                            ROUND(COALESCE(prob_up, 0) * 100.0, 1) AS score,
                            reason,
                            NULL AS decision_context
                        FROM v2m
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (n,),
                    ).fetchall()
                return [dict(row) for row in rows_v2]
            except sqlite3.Error:
                return []


def get_assets_summary() -> list[dict]:
    """
    Retourne une ligne par actif avec son dernier signal, score et P&L.
    Utilisé par la vue globale multi-actifs du dashboard.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT d.asset,
                   d.action,
                   d.score,
                   d.timestamp,
                   d.entry_price,
                   d.result_24h
            FROM decisions d
            INNER JOIN (
                SELECT asset, MAX(timestamp) AS max_ts
                FROM decisions
                GROUP BY asset
            ) latest ON d.asset = latest.asset AND d.timestamp = latest.max_ts
            ORDER BY d.asset
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_pending_postmortems(delay_hours: int = 24) -> list[dict]:
    cutoff = (
        datetime.utcnow().replace(microsecond=0).isoformat()
    )
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM decisions
            WHERE action NOT IN ('HOLD', 'SELL')
              AND reflection_done = 0
              AND (
                -- Position encore ouverte après delay_hours (rare en pratique)
                (result_24h IS NULL AND datetime(timestamp, '+' || ? || ' hours') < datetime(?))
                OR
                -- Position clôturée via SL/TP — reflection jamais déclenchée
                (result_24h IS NOT NULL)
              )
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


def get_agent_performance_stats(asset: str | None = None, days: int = 30) -> list[dict]:
    """
    Calcule les statistiques de performance par agent individuel.

    Pour chaque agent connu (market_data, fundamental, x_sentiment, etc.) :
    - signal_count   : nb de fois où il a émis un signal (score ≠ None)
    - win_rate       : % des fois où son signal (>50=bull, <50=bear) était correct vs résultat réel
    - avg_score      : score moyen émis
    - avg_score_wins : score moyen quand il avait raison
    - brier_score    : erreur quadratique moyenne (0=parfait, 0.25=hasard pur)
    - current_weight : weight_in_scoring dans settings.yaml

    Retourne une liste triée par win_rate desc.
    """
    import json as _json

    cutoff = datetime.utcnow().replace(microsecond=0).isoformat()

    with get_connection() as conn:
        if asset:
            rows = conn.execute(
                """
                SELECT action, weights_snapshot, result_24h
                FROM decisions
                WHERE asset = ?
                  AND action = 'BUY'
                  AND result_24h IS NOT NULL
                  AND result_24h != 0.0
                  AND weights_snapshot IS NOT NULL
                  AND datetime(timestamp) >= datetime(?, ?)
                ORDER BY timestamp ASC
                """,
                (asset, cutoff, f"-{days} days"),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT action, weights_snapshot, result_24h
                FROM decisions
                WHERE action = 'BUY'
                  AND result_24h IS NOT NULL
                  AND result_24h != 0.0
                  AND weights_snapshot IS NOT NULL
                  AND datetime(timestamp) >= datetime(?, ?)
                ORDER BY timestamp ASC
                LIMIT 5000
                """,
                (cutoff, f"-{days} days"),
            ).fetchall()

    # Agréger par agent
    from collections import defaultdict
    buckets: dict[str, list] = defaultdict(list)  # agent -> [(agent_score, result_24h)]

    for row in rows:
        try:
            ws = _json.loads(row["weights_snapshot"] or "{}")
            agent_scores = ws.get("agent_scores", {})
            result = row["result_24h"]
            if result is None:
                continue
            for agent_name, agent_score in agent_scores.items():
                if agent_score is None:
                    continue
                buckets[agent_name].append((float(agent_score), float(result)))
        except Exception:
            continue

    # Charger les poids actuels depuis settings.yaml
    try:
        from utils.config import load_settings
        cfg_agents = load_settings().get("agents", {})
    except Exception:
        cfg_agents = {}

    stats = []
    for agent_name, pairs in buckets.items():
        if len(pairs) < 5:
            continue

        signal_count = len(pairs)
        # Direction correcte : agent bullish (>50) et résultat >0, ou agent bearish (<50) et résultat <0
        correct = [
            1 for s, r in pairs
            if (s > 50 and r > 0) or (s < 50 and r < 0)
        ]
        win_rate = len(correct) / signal_count

        scores = [s for s, _ in pairs]
        results = [r for _, r in pairs]
        avg_score = sum(scores) / len(scores)

        win_scores = [s for s, r in pairs if (s > 50 and r > 0) or (s < 50 and r < 0)]
        avg_score_wins = sum(win_scores) / len(win_scores) if win_scores else avg_score

        # Brier score : MSE entre probabilité agent (score/100) et outcome binaire
        brier = sum((s / 100 - (1 if r > 0 else 0)) ** 2 for s, r in pairs) / signal_count

        # P&L moyen quand l'agent recommandait BUY (score > 50)
        buy_signals = [(s, r) for s, r in pairs if s > 50]
        avg_pnl_on_buy = sum(r for _, r in buy_signals) / len(buy_signals) if buy_signals else 0.0

        current_weight = cfg_agents.get(agent_name, {}).get("weight_in_scoring", None)

        stats.append({
            "agent": agent_name,
            "signal_count": signal_count,
            "win_rate": round(win_rate * 100, 1),
            "avg_score": round(avg_score, 1),
            "avg_score_wins": round(avg_score_wins, 1),
            "brier_score": round(brier, 4),
            "avg_pnl_on_buy": round(avg_pnl_on_buy, 2),
            "current_weight": current_weight,
        })

    stats.sort(key=lambda x: x["win_rate"], reverse=True)
    return stats


def get_agent_scores_history(asset: str | None = None, hours: int = 24) -> list[dict]:
    """
    Retourne l'historique des scores par agent sur les N dernières heures.
    Chaque entrée : {timestamp, action, score, agent_scores: {agent: score}, contrarian_score, mirofish_score, market_score}
    """
    import json as _json
    cutoff = (datetime.utcnow().replace(microsecond=0)
              .isoformat())
    with get_connection() as conn:
        if asset:
            rows = conn.execute(
                """
                SELECT timestamp, action, score, weights_snapshot
                FROM decisions
                WHERE asset = ?
                  AND datetime(timestamp) >= datetime(?, ?)
                  AND weights_snapshot IS NOT NULL
                ORDER BY timestamp ASC
                """,
                (asset, cutoff, f"-{hours} hours")
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT timestamp, action, score, weights_snapshot
                FROM decisions
                WHERE datetime(timestamp) >= datetime(?, ?)
                  AND weights_snapshot IS NOT NULL
                ORDER BY timestamp ASC
                LIMIT 2000
                """,
                (cutoff, f"-{hours} hours")
            ).fetchall()

    result = []
    for row in rows:
        try:
            ws = _json.loads(row["weights_snapshot"] or "{}")
            result.append({
                "timestamp": row["timestamp"],
                "action": row["action"],
                "global_score": row["score"],
                "agent_scores": ws.get("agent_scores", {}),
                "contrarian_score": ws.get("contrarian_score", 50),
                "mirofish_score": ws.get("mirofish_score", 50),
                "market_score": ws.get("market_score", 50),
            })
        except Exception:
            continue
    return result


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

# File d'attente unique — UN seul thread écrit dans SQLite (évite deadlock + explosion de threads)
_LOG_QUEUE: "queue.SimpleQueue[logging.LogRecord | None]" = None  # type: ignore[assignment]


def _start_sqlite_log_writer() -> None:
    """Démarre le thread unique d'écriture SQLite des logs (appelé une seule fois)."""
    import queue as _queue
    global _LOG_QUEUE
    if _LOG_QUEUE is not None:
        return
    _LOG_QUEUE = _queue.SimpleQueue()

    def _writer():
        while True:
            try:
                record = _LOG_QUEUE.get()
                if record is None:
                    break
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

    _t = threading.Thread(target=_writer, daemon=True, name="sqlite-log-writer")
    _t.start()


class SQLiteLogHandler(logging.Handler):
    """Handler logging qui écrit dans la table logs SQLite via une queue.
    emit() est non-bloquant et lock-free : enfile le record, le thread writer l'écrit.
    Évite tout deadlock (AB-BA avec _lock) et toute explosion de threads.
    """

    def emit(self, record: logging.LogRecord) -> None:
        if _LOG_QUEUE is not None:
            try:
                _LOG_QUEUE.put_nowait(record)
            except Exception:
                pass


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
# KRONOS FORECASTS — Foundation model OHLCV (AAAI 2026)
# ===========================================================

def log_kronos_forecast(
    cycle_id: str,
    asset: str,
    forecast_details: dict,
    score: float,
    signal: str,
    confidence: float,
) -> None:
    """Persiste une prédiction Kronos pour évaluation post-mortem."""
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO kronos_forecasts
                (cycle_id, timestamp, asset, model_name, horizon_candles,
                 current_price, predicted_price, pct_change,
                 confidence, score, signal, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle_id,
                    datetime.utcnow().isoformat(),
                    asset,
                    forecast_details.get("model_name", "NeoQuasar/Kronos-mini"),
                    forecast_details.get("horizon_candles", 96),
                    forecast_details.get("current_price", 0),
                    forecast_details.get("predicted_price", 0),
                    forecast_details.get("pct_change", 0),
                    confidence,
                    score,
                    signal,
                    forecast_details.get("latency_ms", 0),
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"Cannot log Kronos forecast: {exc}")


def evaluate_kronos_forecasts() -> int:
    """
    Post-mortem : évalue les prédictions Kronos arrivées à échéance.
    Compare predicted_price vs prix réel après horizon_candles × 15min.
    Retourne le nombre de forecasts évalués.
    """
    import ccxt

    try:
        exchange = ccxt.binance({"enableRateLimit": True})
    except Exception as exc:
        logger.warning(f"Cannot init exchange for Kronos eval: {exc}")
        return 0

    evaluated = 0
    now = datetime.utcnow()

    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, asset, horizon_candles, current_price,
                       predicted_price, pct_change, signal
                FROM kronos_forecasts
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

                # Récupérer le prix réel à l'échéance (fallback Yahoo pour non-crypto)
                try:
                    asset_sym = row["asset"]
                    _YF_MAP = {
                        "XAU/USD": "GC=F", "XAG/USD": "SI=F", "WTI/USD": "CL=F",
                        "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X",
                    }
                    if asset_sym in _YF_MAP:
                        import json, urllib.request as _ur
                        yf_ticker = _YF_MAP[asset_sym]
                        req = _ur.Request(
                            f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_ticker}"
                            f"?interval=15m&range=2d&includePrePost=false",
                            headers={"User-Agent": "atlas-trader/2.0"},
                        )
                        with _ur.urlopen(req, timeout=20) as r:
                            data = json.loads(r.read())
                        timestamps = data["chart"]["result"][0]["timestamp"]
                        closes = data["chart"]["result"][0]["indicators"]["quote"][0].get("close", [])
                        target_ts = int(target_time.timestamp())
                        best_idx = min(range(len(timestamps)), key=lambda i: abs(timestamps[i] - target_ts))
                        actual_price = float(closes[best_idx])
                    else:
                        ohlcv = exchange.fetch_ohlcv(
                            asset_sym, "15m",
                            since=int(target_time.timestamp() * 1000),
                            limit=1,
                        )
                        if not ohlcv:
                            continue
                        actual_price = float(ohlcv[0][4])
                except Exception:
                    continue

                actual_change = ((actual_price - row["current_price"]) / row["current_price"]) * 100
                predicted_dir = 1 if row["pct_change"] >= 0 else -1
                actual_dir = 1 if actual_change >= 0 else -1
                direction_hit = 1 if predicted_dir == actual_dir else 0

                conn.execute(
                    """
                    UPDATE kronos_forecasts
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
                logger.info(f"Kronos post-mortem: {evaluated} forecasts evaluated")

    except Exception as exc:
        logger.warning(f"Kronos evaluation error: {exc}")

    return evaluated


def get_kronos_stats() -> dict:
    """
    Retourne les statistiques de performance Kronos.
    - total, evaluated, direction_accuracy, mae, avg_confidence, avg_latency_ms
    - recent: 10 dernières prédictions évaluées
    - pending: 5 dernières en attente
    """
    try:
        with get_connection() as conn:
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
                FROM kronos_forecasts
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

            recent = conn.execute(
                """
                SELECT timestamp, asset, model_name, current_price, predicted_price,
                       pct_change, actual_price, actual_change, direction_hit,
                       confidence, signal, horizon_candles
                FROM kronos_forecasts
                WHERE actual_price IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT 10
                """
            ).fetchall()
            stats["recent"] = [dict(r) for r in recent]

            pending = conn.execute(
                """
                SELECT timestamp, asset, model_name, current_price, predicted_price,
                       pct_change, confidence, signal, horizon_candles
                FROM kronos_forecasts
                WHERE actual_price IS NULL
                ORDER BY timestamp DESC
                LIMIT 5
                """
            ).fetchall()
            stats["pending"] = [dict(r) for r in pending]

            return stats

    except Exception as exc:
        logger.warning(f"Cannot get Kronos stats: {exc}")
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
        logger.warning(f"Shadow log [{profile_name}] error: {exc}")


def get_shadow_open_positions_for_profile(profile_name: str) -> list[dict]:
    """Retourne les positions BUY shadow ouvertes pour un profil."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM shadow_decisions
                WHERE profile_name = ?
                  AND result_24h IS NULL
                  AND action = 'BUY'
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
        logger.warning(f"Shadow close position error: {exc}")


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
        logger.warning(f"Shadow update result error: {exc}")


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
                    SUM(CASE WHEN action = 'BUY' AND result_24h IS NOT NULL AND result_24h != 0.0 THEN 1 ELSE 0 END) as evaluated,
                    SUM(CASE WHEN action = 'BUY' AND result_24h > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN action = 'BUY' AND result_24h < 0 THEN 1 ELSE 0 END) as losses,
                    COALESCE(SUM(CASE WHEN action = 'BUY' THEN result_24h ELSE 0 END), 0) as total_pnl,
                    COALESCE(AVG(CASE WHEN action = 'BUY' AND result_24h IS NOT NULL AND result_24h != 0.0 THEN result_24h END), 0) as avg_pnl,
                    COALESCE(MAX(CASE WHEN action = 'BUY' THEN result_24h END), 0) as best_trade,
                    COALESCE(MIN(CASE WHEN action = 'BUY' THEN result_24h END), 0) as worst_trade,
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
                total_pnl = round(row["total_pnl"], 2)
                virtual_capital = round(_SHADOW_INITIAL_CAPITAL + total_pnl, 2)
                stats.append({
                    "profile": row["profile_name"],
                    "total_trades": row["total_trades"],
                    "buys": row["buys"],
                    "sells": row["sells"],
                    "evaluated": evaluated,
                    "wins": wins,
                    "losses": row["losses"] or 0,
                    "win_rate": round(wins / evaluated * 100, 1) if evaluated > 0 else 0,
                    "total_pnl": total_pnl,
                    "return_pct": round(total_pnl / _SHADOW_INITIAL_CAPITAL * 100, 2),
                    "virtual_capital": virtual_capital,
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
                    SUM(CASE WHEN action = 'BUY' AND result_24h IS NOT NULL AND result_24h != 0.0 THEN 1 ELSE 0 END) as evaluated,
                    SUM(CASE WHEN action = 'BUY' AND result_24h > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN action = 'BUY' AND result_24h < 0 THEN 1 ELSE 0 END) as losses,
                    COALESCE(SUM(CASE WHEN action = 'BUY' THEN result_24h ELSE 0 END), 0) as total_pnl,
                    COALESCE(AVG(CASE WHEN action = 'BUY' AND result_24h IS NOT NULL AND result_24h != 0.0 THEN result_24h END), 0) as avg_pnl,
                    COALESCE(MAX(CASE WHEN action = 'BUY' THEN result_24h END), 0) as best_trade,
                    COALESCE(MIN(CASE WHEN action = 'BUY' THEN result_24h END), 0) as worst_trade,
                    MIN(timestamp) as first_trade,
                    MAX(timestamp) as last_trade
                FROM decisions
                WHERE action != 'HOLD'
                """
            ).fetchone()
            if baseline_row and baseline_row["total_trades"]:
                evaluated = baseline_row["evaluated"] or 0
                wins = baseline_row["wins"] or 0
                total_pnl = round(baseline_row["total_pnl"], 2)
                # Baseline: capital réel depuis le portefeuille
                try:
                    real_pf = get_portfolio()
                    real_capital = float(real_pf.get("current_value", _SHADOW_INITIAL_CAPITAL))
                except Exception:
                    real_capital = _SHADOW_INITIAL_CAPITAL + total_pnl
                stats.insert(0, {
                    "profile": "baseline",
                    "total_trades": baseline_row["total_trades"],
                    "buys": baseline_row["buys"],
                    "sells": baseline_row["sells"],
                    "evaluated": evaluated,
                    "wins": wins,
                    "losses": baseline_row["losses"] or 0,
                    "win_rate": round(wins / evaluated * 100, 1) if evaluated > 0 else 0,
                    "total_pnl": total_pnl,
                    "return_pct": round(total_pnl / _SHADOW_INITIAL_CAPITAL * 100, 2),
                    "virtual_capital": round(real_capital, 2),
                    "avg_pnl": round(baseline_row["avg_pnl"], 2),
                    "best_trade": round(baseline_row["best_trade"], 2),
                    "worst_trade": round(baseline_row["worst_trade"], 2),
                    "first_trade": baseline_row["first_trade"],
                    "last_trade": baseline_row["last_trade"],
                })

    except Exception as exc:
        logger.warning(f"Shadow stats error: {exc}")

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
                    "win_rate": 0, "total_pnl": 0, "return_pct": 0,
                    "virtual_capital": _SHADOW_INITIAL_CAPITAL,
                    "avg_pnl": 0,
                    "best_trade": 0, "worst_trade": 0,
                    "first_trade": None, "last_trade": None,
                })
    except Exception:
        pass

    return stats


_SHADOW_INITIAL_CAPITAL = 10_000.0  # capital de départ de chaque profil shadow


def get_shadow_virtual_capital(profile_name: str) -> float:
    """
    Retourne le capital virtuel actuel d'un profil shadow.
    = capital_initial + somme des P&L évalués - somme des positions ouvertes.
    Utilisé par shadow_runner pour un sizing proportionnel au capital restant.
    """
    try:
        with get_connection() as conn:
            # Somme des P&L évalués
            row = conn.execute(
                """
                SELECT COALESCE(SUM(result_24h), 0) as realized_pnl
                FROM shadow_decisions
                WHERE profile_name = ? AND result_24h IS NOT NULL
                """,
                (profile_name,),
            ).fetchone()
            realized = float(row["realized_pnl"]) if row else 0.0

            # Somme des positions ouvertes (capital engagé)
            open_row = conn.execute(
                """
                SELECT COALESCE(SUM(position_size), 0) as engaged
                FROM shadow_decisions
                WHERE profile_name = ? AND action = 'BUY' AND result_24h IS NULL
                """,
                (profile_name,),
            ).fetchone()
            engaged = float(open_row["engaged"]) if open_row else 0.0

            virtual = _SHADOW_INITIAL_CAPITAL + realized - engaged
            return max(0.0, round(virtual, 2))
    except Exception:
        return _SHADOW_INITIAL_CAPITAL


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
        logger.warning(f"Shadow PnL series error: {exc}")

    return series


# ===========================================================
# MÉTA-ANALYSE LLM — patterns d'échec
# ===========================================================

def get_decisions_for_meta(
    days: int = 30,
    limit: int = 80,
    asset: str | None = None,
) -> list[dict]:
    """
    Retourne les décisions BUY/SELL évaluées (result_24h NOT NULL) pour la méta-analyse.
    Extrait les scores de chaque composant depuis weights_snapshot.
    """
    import json as _json

    cutoff = datetime.utcnow().replace(microsecond=0).isoformat()
    with get_connection() as conn:
        if asset:
            rows = conn.execute(
                """
                SELECT timestamp, asset, action, score, result_24h,
                       weights_snapshot, explanation
                FROM decisions
                WHERE asset = ?
                  AND action IN ('BUY', 'SELL')
                  AND result_24h IS NOT NULL
                  AND datetime(timestamp) >= datetime(?, ?)
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (asset, cutoff, f"-{days} days", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT timestamp, asset, action, score, result_24h,
                       weights_snapshot, explanation
                FROM decisions
                WHERE action IN ('BUY', 'SELL')
                  AND result_24h IS NOT NULL
                  AND datetime(timestamp) >= datetime(?, ?)
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (cutoff, f"-{days} days", limit),
            ).fetchall()

    result = []
    for row in rows:
        entry: dict = {
            "ts":         row["timestamp"][:16],
            "asset":      row["asset"],
            "action":     row["action"],
            "score":      row["score"],
            "result":     round(float(row["result_24h"]), 2),
        }
        # Extraire les scores depuis le breakdown stocké
        try:
            ws = _json.loads(row["weights_snapshot"] or "{}")
            # Format decision_engine breakdown: agents.detail, mirofish.score, etc.
            entry["mf_score"]      = ws.get("mirofish", {}).get("score") or ws.get("mirofish_score")
            entry["market_score"]  = ws.get("market",   {}).get("score") or ws.get("market_score")
            entry["ctr_score"]     = ws.get("contrarian", {}).get("score") or ws.get("contrarian_score")
            entry["regime"]        = ws.get("regime")
            # Per-agent scores (deux formats possibles)
            agent_detail = ws.get("agents", {}).get("detail") or ws.get("agent_scores") or {}
            entry["agents"]        = {k: round(float(v), 0) for k, v in agent_detail.items() if v is not None}
        except Exception:
            pass
        result.append(entry)
    return result


def save_meta_analysis(
    summary_text: str,
    n_trades: int,
    n_losing: int,
    patterns_json: str | None = None,
    asset: str | None = None,
    run_trigger: str = "auto",
) -> None:
    """Persiste une méta-analyse LLM dans la table meta_analyses."""
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO meta_analyses
                (timestamp, asset, summary_text, patterns_json, n_trades, n_losing, run_trigger)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.utcnow().isoformat(),
                    asset,
                    summary_text,
                    patterns_json,
                    n_trades,
                    n_losing,
                    run_trigger,
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"save_meta_analysis error: {exc}")


def get_last_meta_analysis(asset: str | None = None, limit: int = 3) -> list[dict]:
    """Retourne les N dernières méta-analyses (globales ou par actif)."""
    try:
        with get_connection() as conn:
            if asset:
                rows = conn.execute(
                    """
                    SELECT * FROM meta_analyses
                    WHERE asset = ? OR asset IS NULL
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (asset, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM meta_analyses
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


# ===========================================================
# V2 QUANT — état live + courbe equity
# ===========================================================

def write_v2_state(
    asset: str,
    bar_ts: str,
    close_price: float,
    regime: int | None,
    prob_up: float | None,
    action: str,
    reason: str,
    atr_14: float | None = None,
    position_side: str | None = None,
    entry_price: float | None = None,
    sl_price: float | None = None,
    tp_price: float | None = None,
    capital: float | None = None,
    model_fit_at: str | None = None,
) -> None:
    """Upsert de l'état V2 courant (1 seule ligne id=1)."""
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO v2_state
                    (id, updated_at, asset, bar_ts, close_price, regime, prob_up,
                     action, reason, atr_14, position_side, entry_price, sl_price,
                     tp_price, capital, model_fit_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    updated_at    = excluded.updated_at,
                    asset         = excluded.asset,
                    bar_ts        = excluded.bar_ts,
                    close_price   = excluded.close_price,
                    regime        = excluded.regime,
                    prob_up       = excluded.prob_up,
                    action        = excluded.action,
                    reason        = excluded.reason,
                    atr_14        = excluded.atr_14,
                    position_side = excluded.position_side,
                    entry_price   = excluded.entry_price,
                    sl_price      = excluded.sl_price,
                    tp_price      = excluded.tp_price,
                    capital       = excluded.capital,
                    model_fit_at  = excluded.model_fit_at
                """,
                (
                    datetime.utcnow().isoformat(), asset, bar_ts, close_price,
                    regime, prob_up, action, reason, atr_14, position_side,
                    entry_price, sl_price, tp_price, capital, model_fit_at,
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"write_v2_state error: {exc}")


def append_v2_equity(
    ts: str,
    asset: str,
    equity: float,
    action: str | None = None,
    close_price: float | None = None,
) -> None:
    """Ajoute un point à la courbe equity V2."""
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO v2_equity (ts, asset, equity, action, close_price)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ts, asset, equity, action, close_price),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"append_v2_equity error: {exc}")


def get_v2_assets_summary() -> list[dict]:
    """
    Résumé V2 multi-actifs : dernière ligne v2_equity par actif.
    Utilisé par la vue globale du dashboard (remplacement de get_assets_summary).
    """
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT e.asset, e.action, e.equity, e.close_price, e.ts
                FROM v2_equity e
                INNER JOIN (
                    SELECT asset, MAX(id) AS max_id
                    FROM v2_equity
                    GROUP BY asset
                ) latest ON e.asset = latest.asset AND e.id = latest.max_id
                ORDER BY e.asset
                """
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def get_v2_state() -> dict | None:
    """Lit l'état V2 courant."""
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM v2_state WHERE id = 1").fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def get_v2_equity_curve(n: int = 2000, asset: str = "BTC/USDT") -> list[dict]:
    """Lit les N derniers points equity V2."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT ts, equity, action, close_price FROM v2_equity "
                "WHERE asset = ? ORDER BY id DESC LIMIT ?",
                (asset, n),
            ).fetchall()
            return list(reversed([dict(r) for r in rows]))
    except Exception:
        return []


def get_v2_recent_trades(n: int = 50, asset: str = "BTC/USDT") -> list[dict]:
    """Retourne les N dernières entrées en position V2."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT ts, equity, action, close_price FROM v2_equity "
                "WHERE asset = ? AND action IN ('long', 'short') "
                "ORDER BY id DESC LIMIT ?",
                (asset, n),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_v2_realized_stats(asset: str | None = None, assets: list[str] | None = None) -> dict:
    """Calcule PnL réalisé et nb de trades clôturés depuis v2_equity.

    Un trade clôturé est estimé par un changement d'equity entre deux points
    consécutifs d'un même actif.
    """
    try:
        with get_connection() as conn:
            if asset:
                rows = conn.execute(
                    "SELECT asset, id, equity FROM v2_equity WHERE asset = ? ORDER BY asset, id ASC",
                    (asset,),
                ).fetchall()
            elif assets:
                placeholders = ",".join(["?"] * len(assets))
                rows = conn.execute(
                    f"SELECT asset, id, equity FROM v2_equity WHERE asset IN ({placeholders}) ORDER BY asset, id ASC",
                    tuple(assets),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT asset, id, equity FROM v2_equity ORDER BY asset, id ASC"
                ).fetchall()

        prev_by_asset: dict[str, float] = {}
        realized_pnl = 0.0
        n_closed = 0
        for r in rows:
            a = str(r["asset"])
            eq = float(r["equity"])
            if a not in prev_by_asset:
                prev_by_asset[a] = eq
                continue
            delta = eq - prev_by_asset[a]
            prev_by_asset[a] = eq
            if abs(delta) < 1e-12:
                continue
            realized_pnl += delta
            n_closed += 1

        return {"total_pnl": round(realized_pnl, 2), "n_trades": n_closed}
    except Exception:
        return {"total_pnl": 0.0, "n_trades": 0}


def get_v2_cumulative_pnl(asset: str | None = None, assets: list[str] | None = None,
                          reset_jump_abs: float = 500.0) -> float:
    """P&L cumulé V2 basé sur les deltas de capital dans v2_decisions.

    Ignore les sauts anormaux (reset/restart) au-delà de `reset_jump_abs`.
    """
    try:
        with get_connection() as conn:
            if asset:
                rows = conn.execute(
                    "SELECT asset, id, capital FROM v2_decisions WHERE asset = ? ORDER BY asset, id ASC",
                    (asset,),
                ).fetchall()
            elif assets:
                placeholders = ",".join(["?"] * len(assets))
                rows = conn.execute(
                    f"SELECT asset, id, capital FROM v2_decisions "
                    f"WHERE asset IN ({placeholders}) ORDER BY asset, id ASC",
                    tuple(assets),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT asset, id, capital FROM v2_decisions ORDER BY asset, id ASC"
                ).fetchall()

        prev_by_asset: dict[str, float] = {}
        total = 0.0
        for r in rows:
            a = str(r["asset"])
            cap = r["capital"]
            if cap is None:
                continue
            cap = float(cap)
            if a not in prev_by_asset:
                prev_by_asset[a] = cap
                continue

            delta = cap - prev_by_asset[a]
            prev_by_asset[a] = cap

            # Ignore les resets/restarts (sauts brutaux non-trade)
            if abs(delta) > reset_jump_abs:
                continue
            total += delta

        return round(total, 2)
    except Exception:
        return 0.0
