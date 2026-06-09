"""
v4/nodes/quant/reflection.py — ReflectionNode (mémoire des trades).

Après chaque cycle, analyse les trades fermés récents et génère
une leçon concise (une phrase) stockée en base. Injecte les leçons
passées dans le contexte du LLM pour améliorer les décisions futures.

Inspiré du mécanisme de reflection de TradingAgents.
"""

from __future__ import annotations

import logging
from typing import Any

from v4.core.node import Node

logger = logging.getLogger("v4.nodes.quant.reflection")


class ReflectionNode(Node):
    """
    Apprend des trades fermés et enrichit le contexte AI.

    Inputs  : aucun (lit la DB directement)

    Outputs :
        lessons     : str   — leçons consolidées pour le prompt AI
        n_reflected : int   — nombre de nouvelles réflexions générées
        recent_pnl  : float — PnL cumulé des derniers trades

    Params :
        max_lessons  : int — nombre max de leçons à injecter (défaut: 5)
        min_pnl_abs  : float — PnL min (absolu) pour générer une leçon (défaut: 1.0)
    """

    @property
    def node_type(self) -> str:
        return "ReflectionNode"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"lessons": "str", "n_reflected": "int", "recent_pnl": "float"}

    def _ensure_table(self, conn) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS v4_reflections (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id        TEXT UNIQUE NOT NULL,
                symbol          TEXT NOT NULL,
                action          TEXT NOT NULL,
                entry_price     REAL NOT NULL,
                close_price     REAL,
                pnl_usd         REAL NOT NULL,
                pnl_pct         REAL,
                held_hours      REAL,
                lesson          TEXT NOT NULL,
                created_at      TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reflections_symbol
            ON v4_reflections(symbol, created_at DESC)
        """)
        conn.commit()

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from storage.paper_trader import get_v4_trades
        from storage.database import get_connection
        from datetime import datetime, timezone

        max_lessons = int(self.params.get("max_lessons", 5))
        min_pnl_abs = float(self.params.get("min_pnl_abs", 1.0))

        # ── Récupérer les trades fermés sans réflexion ──
        all_trades = get_v4_trades(n=100)
        closed_trades = [t for t in all_trades if t.get("status") == "closed" and t.get("pnl_usd", 0) != 0]

        if not closed_trades:
            return {"lessons": "", "n_reflected": 0, "recent_pnl": 0.0}

        new_reflections = 0
        now = datetime.now(timezone.utc).isoformat()

        try:
            with get_connection() as conn:
                self._ensure_table(conn)

                for trade in closed_trades:
                    trade_id = trade["trade_id"]
                    symbol = trade.get("symbol", "?")
                    action = trade.get("action", "?")
                    entry = float(trade.get("entry_price", 0))
                    pnl = float(trade.get("pnl_usd", 0))

                    # Déjà réfléchi ?
                    existing = conn.execute(
                        "SELECT 1 FROM v4_reflections WHERE trade_id=?",
                        (trade_id,),
                    ).fetchone()
                    if existing:
                        continue

                    if abs(pnl) < min_pnl_abs:
                        continue

                    # ── Générer la leçon (heuristique, pas d'appel LLM) ──
                    lesson = self._generate_lesson(symbol, action, entry, pnl, trade)
                    if not lesson:
                        continue

                    close_price = float(trade.get("close_price", trade.get("entry_price", entry)))
                    pnl_pct = (pnl / (float(trade.get("size_usd", 1)) or 1)) * 100 if trade.get("size_usd") else None

                    conn.execute(
                        """INSERT OR IGNORE INTO v4_reflections
                           (trade_id, symbol, action, entry_price, close_price,
                            pnl_usd, pnl_pct, held_hours, lesson, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (trade_id, symbol, action, entry, close_price,
                         round(pnl, 4), round(pnl_pct, 2) if pnl_pct else None,
                         None, lesson, now),
                    )
                    new_reflections += 1
                    logger.info("Reflection [%s] %s %s pnl=$%.2f → %s", symbol, trade_id, action, pnl, lesson[:60])

                conn.commit()

                # ── Récupérer les leçons récentes pour le contexte AI ──
                rows = conn.execute(
                    """SELECT symbol, action, pnl_usd, lesson FROM v4_reflections
                       ORDER BY created_at DESC LIMIT ?""",
                    (max_lessons,),
                ).fetchall()

                # ── PnL récent cumulé ──
                pnl_row = conn.execute(
                    """SELECT COALESCE(SUM(pnl_usd), 0) FROM v4_reflections
                       WHERE created_at > datetime('now', '-7 days')"""
                ).fetchone()

        except Exception as exc:
            logger.warning("ReflectionNode DB error: %s", exc)
            return {"lessons": "", "n_reflected": 0, "recent_pnl": 0.0}

        recent_pnl = float(pnl_row[0]) if pnl_row else 0.0

        # ── Formater les leçons pour le prompt AI ──
        if rows:
            lesson_lines = []
            for r in rows:
                sym = r["symbol"]
                act = r["action"]
                pnl = r["pnl_usd"]
                lesson_text = r["lesson"]
                emoji = "✅" if pnl > 0 else "❌"
                lesson_lines.append(f"- {emoji} {sym} {act}: {lesson_text} (PnL: ${pnl:+.2f})")
            lessons = "Past trade lessons:\n" + "\n".join(lesson_lines)
        else:
            lessons = ""

        return {
            "lessons": lessons,
            "n_reflected": new_reflections,
            "recent_pnl": round(recent_pnl, 2),
        }

    def _generate_lesson(
        self, symbol: str, action: str, entry: float, pnl: float, trade: dict
    ) -> str:
        """Génère une leçon concise sans LLM (patterns heuristiques)."""
        won = pnl > 0

        # Patterns communs
        if won:
            if action == "short":
                return f"Short {symbol} was profitable — downward momentum confirmed, trailing SL protected gains"
            else:
                return f"Long {symbol} was profitable — upward trend followed through, SL trailed correctly"
        else:
            if action == "short":
                return f"Short {symbol} was a loss — price reversed upward, SL too tight or trend changed"
            else:
                return f"Long {symbol} was a loss — price reversed downward, consider tighter SL or earlier exit"

        return ""
