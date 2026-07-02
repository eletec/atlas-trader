"""
v7/api/live_pnl.py — Endpoint minimal pour widget live P&L.
Appelé par le widget JS du dashboard Streamlit.
Retourne le P&L latent de toutes les positions V7.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import urllib.request

logger = logging.getLogger("v7.api.live_pnl")

API_BASE = "http://localhost:8000"
DB_PATH = "/app/data/v4.db"


def get_live_prices() -> dict[str, float]:
    """Fetch live prices from V7 API."""
    try:
        req = urllib.request.Request(f"{API_BASE}/prices/snapshot")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return {sym: float(d["price"]) for sym, d in data.items() if isinstance(d, dict) and "price" in d}
    except Exception:
        return {}


def get_live_pnl():
    """Retourne le P&L latent total et par actif."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, action, entry_price, size_usd FROM v4_trades WHERE status='open'"
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"error": str(e), "total_pnl": 0, "trades": []}

    prices = get_live_prices()
    trades = []
    total_pnl = 0.0

    for r in rows:
        symbol = r["symbol"] or "?"
        entry = float(r["entry_price"] or 0)
        size = float(r["size_usd"] or 0)
        action = r["action"] or "SHORT"
        current = prices.get(symbol, 0)

        if entry > 0 and current > 0 and size > 0:
            if action in ("SELL", "SHORT", "CARRY"):
                pnl_pct = (entry - current) / entry
            else:
                pnl_pct = (current - entry) / entry
            pnl_usd = size * pnl_pct
        else:
            pnl_usd = 0.0
            pnl_pct = 0.0

        total_pnl += pnl_usd
        trades.append({
            "symbol": symbol.split("/")[0],
            "pnl_usd": round(pnl_usd, 2),
            "pnl_pct": round(pnl_pct * 100, 2),
        })

    return {"total_pnl": round(total_pnl, 2), "trades": trades}


# ── FastAPI endpoint (si utilisé dans l'API) ──
try:
    from fastapi import APIRouter
    router = APIRouter()

    @router.get("/live-pnl")
    async def live_pnl_endpoint():
        return get_live_pnl()
except ImportError:
    router = None
