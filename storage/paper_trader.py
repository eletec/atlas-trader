"""
storage/paper_trader.py — Persistence of the V4 PaperTrader trades in SQLite.

Used by v4/nodes/quant/output.py (PaperTrader.run).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("storage.paper_trader")


def _ensure_table(conn) -> None:
    """Create the v4_trades table when missing."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS v4_trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id        TEXT    UNIQUE NOT NULL,
            dag_id          TEXT    NOT NULL,
            timestamp       TEXT    NOT NULL,
            symbol          TEXT    NOT NULL,
            action          TEXT    NOT NULL,      -- long | short
            entry_price     REAL    NOT NULL,
            stop_loss       REAL,
            take_profit     REAL,
            size_usd        REAL    NOT NULL,
            size_units      REAL,
            atr             REAL,
            status          TEXT    DEFAULT 'open', -- open | closed | cancelled
            closed_at       TEXT,
            pnl_usd         REAL    DEFAULT 0,
            context_json    TEXT,                   -- JSON: full decision (signal, trend, regime...)
            testnet         INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_v4_trades_dag
        ON v4_trades(dag_id, timestamp DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_v4_trades_symbol
        ON v4_trades(symbol, timestamp DESC)
    """)
    conn.commit()


def persist_trade(
    symbol: str,
    action: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    size_usd: float,
    testnet: bool = True,
    dag_id: str = "",
    size_units: float = 0,
    atr: float = 0,
    context: dict | None = None,
) -> str:
    """
    Persist a paper trade in the v4_trades table.

    Args:
        context: optional dict — stored as JSON in context_json for traceability

    Returns:
        trade_id (str) — unique UUID of the trade.
    """
    from storage.database import get_connection
    import json as _json

    trade_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()
    ctx_json = _json.dumps(context, default=str) if context else None

    try:
        with get_connection() as conn:
            _ensure_table(conn)
            conn.execute(
                """INSERT INTO v4_trades
                   (trade_id, dag_id, timestamp, symbol, action, entry_price,
                    stop_loss, take_profit, size_usd, size_units, atr, status, testnet, context_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
                (trade_id, dag_id, now, symbol, action, entry_price,
                 stop_loss, take_profit, size_usd, size_units, atr, int(testnet), ctx_json),
            )
            conn.commit()
        logger.info("Trade persisted: %s %s %s @ %.2f size=$%.0f", trade_id, symbol, action, entry_price, size_usd)
        return trade_id
    except Exception as exc:
        logger.warning("persist_trade failed: %s", exc)
        return trade_id  # return the ID even when persistence fails


def get_v4_trades(n: int = 200, symbol: str | None = None) -> list[dict]:
    """Return the last N V4 trades."""
    from storage.database import get_connection

    try:
        with get_connection() as conn:
            if symbol:
                rows = conn.execute(
                    "SELECT * FROM v4_trades WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                    (symbol, n),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM v4_trades ORDER BY timestamp DESC LIMIT ?",
                    (n,),
                ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_open_positions(symbol: str | None = None) -> list[dict]:
    """Return every still-open position."""
    from storage.database import get_connection

    try:
        with get_connection() as conn:
            _ensure_table(conn)
            if symbol:
                rows = conn.execute(
                    "SELECT * FROM v4_trades WHERE status='open' AND symbol=? ORDER BY timestamp ASC",
                    (symbol,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM v4_trades WHERE status='open' ORDER BY timestamp ASC"
                ).fetchall()
        result = [dict(r) for r in rows]
        if result:
            logger.info("get_open_positions: %d found", len(result))
        return result
    except Exception:
        return []


def close_position(
    trade_id: str,
    close_price: float,
    pnl_usd: float,
    reason: str = "sl",
) -> bool:
    """Close a position and record the PnL.

    Args:
        trade_id: trade UUID
        close_price: closing price
        pnl_usd: profit/loss in USD
        reason: 'sl' | 'tp' | 'signal_reverse' | 'manual'

    Returns:
        True when the close succeeded.
    """
    from storage.database import get_connection

    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_connection() as conn:
            _ensure_table(conn)
            conn.execute(
                """UPDATE v4_trades
                   SET status='closed', closed_at=?, pnl_usd=?
                   WHERE trade_id=? AND status='open'""",
                (now, pnl_usd, trade_id),
            )
            conn.commit()
        logger.info(
            "Position closed: %s @ %.2f pnl=$%.2f (%s)",
            trade_id, close_price, pnl_usd, reason,
        )
        return True
    except Exception as exc:
        logger.warning("close_position failed: %s", exc)
        return False


def update_stop_loss(trade_id: str, new_sl: float) -> bool:
    """Update the stop-loss of an open position (trailing)."""
    from storage.database import get_connection

    try:
        with get_connection() as conn:
            _ensure_table(conn)
            conn.execute(
                "UPDATE v4_trades SET stop_loss=? WHERE trade_id=? AND status='open'",
                (new_sl, trade_id),
            )
            conn.commit()
        logger.info("SL updated: %s -> %.4f", trade_id, new_sl)
        return True
    except Exception as exc:
        logger.warning("update_stop_loss failed: %s", exc)
        return False
