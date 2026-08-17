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
    """Prix live — lecture directe du PriceStore en mémoire (même process).

    Évite le round-trip HTTP localhost:8000 qui timeout quand l'event loop
    est occupée par les cycles DAG (ccxt synchrone, 23 actifs).
    """
    try:
        from v4.api.routes.prices import PriceStore
        prices: dict[str, float] = {}
        for rec in PriceStore.instance().snapshot():
            sym = rec.get("symbol", "")
            # Normalize: BTCUSDT → BTC/USDT, BTC/USDT → BTC/USDT
            norm = sym if "/" in sym else f"{sym[:-4]}/{sym[-4:]}" if sym.endswith("USDT") else sym
            try:
                prices[norm] = float(rec.get("price", 0))
            except (TypeError, ValueError):
                pass
        return prices
    except Exception:
        # Fallback HTTP (si PriceStore indisponible)
        try:
            req = urllib.request.Request(f"{API_BASE}/prices/snapshot")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            prices = {}
            for sym, d in data.items():
                if isinstance(d, dict) and "price" in d:
                    norm = sym if "/" in sym else f"{sym[:-4]}/{sym[-4:]}" if sym.endswith("USDT") else sym
                    prices[norm] = float(d["price"])
            return prices
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


def get_carry_pnl():
    """Retourne le P&L réel du carry (basis P&L + funding), pas le P&L spot trompeur.
    
    Pour chaque position carry ouverte :
      - Fetch spot + perp via /prices/snapshot
      - Calcule basis_entry depuis context_json
      - Calcule basis_now = (perp - spot) / spot
      - basis_pnl = (basis_now - basis_entry) × size_usd
    """
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT trade_id, symbol, action, entry_price, size_usd, context_json "
            "FROM v4_trades WHERE status='open'"
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"error": str(e), "total_pnl": 0, "trades": []}

    if not rows:
        return {"total_pnl": 0, "trades": [], "note": "no open positions"}

    # Fetch spot + perp prices
    spot_prices = get_live_prices()
    perp_prices = {}
    try:
        import ccxt
        exchange = ccxt.binance({"enableRateLimit": True})
        symbols_seen = set()
        for r in rows:
            sym = r["symbol"]
            if sym and sym not in symbols_seen:
                symbols_seen.add(sym)
                try:
                    # Gérer les contrats ×1000 (SHIB→1000SHIB, PEPE→1000PEPE...)
                    MULTIPLIER_MAP = {"PEPE": "1000PEPE", "SHIB": "1000SHIB",
                                      "BONK": "1000BONK", "FLOKI": "1000FLOKI",
                                      "LUNC": "1000LUNC"}
                    base = sym.split("/")[0]
                    sym_perp = f"{MULTIPLIER_MAP.get(base, base)}/USDT:USDT"
                    ticker = exchange.fetch_ticker(sym_perp)
                    perp_prices[sym] = float(ticker.get("last", 0))
                except Exception:
                    perp_prices[sym] = spot_prices.get(sym, 0)
    except ImportError:
        # Fallback: perp ≈ spot
        perp_prices = dict(spot_prices)

    trades = []
    total_pnl = 0.0

    for r in rows:
        trade_id = r["trade_id"] or "?"
        symbol = r["symbol"] or "?"
        action = (r["action"] or "long").lower()
        entry_spot = float(r["entry_price"] or 0)
        size_usd = float(r["size_usd"] or 0)
        spot = spot_prices.get(symbol, 0)
        perp = perp_prices.get(symbol, spot)

        # Spot P&L (pour référence)
        spot_pnl = 0.0
        if entry_spot > 0 and spot > 0:
            if action in ("short", "carry"):
                spot_pnl = (entry_spot - spot) / entry_spot * size_usd
            else:
                spot_pnl = (spot - entry_spot) / entry_spot * size_usd

        # Basis P&L (le vrai P&L pour le carry)
        basis_pnl = 0.0
        entry_perp = entry_spot  # fallback
        if action == "carry":
            try:
                ctx_raw = r["context_json"]
                if ctx_raw:
                    ctx = json.loads(ctx_raw) if isinstance(ctx_raw, str) else ctx_raw
                    entry_perp = float(ctx.get("entry_perp_price", entry_spot))
            except Exception:
                pass
            
            if entry_spot > 0 and spot > 0 and perp > 0:
                basis_entry = (entry_perp - entry_spot) / entry_spot
                basis_now = (perp - spot) / spot
                basis_pnl = (basis_now - basis_entry) * size_usd

        # P&L réel = basis P&L pour carry, spot P&L pour les autres
        real_pnl = basis_pnl if action == "carry" else spot_pnl
        total_pnl += real_pnl

        trades.append({
            "trade_id": trade_id[:8],
            "symbol": symbol,
            "action": action.upper(),
            "spot": round(spot, 4) if spot else 0,
            "perp": round(perp, 4) if perp else 0,
            "spot_pnl": round(spot_pnl, 4),
            "basis_pnl": round(basis_pnl, 4),
            "real_pnl": round(real_pnl, 4),
            "real_pnl_pct": round(real_pnl / size_usd * 100, 2) if size_usd > 0 else 0,
            "is_carry": action == "carry",
        })

    return {
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / max(sum(t["spot_pnl"] / max(t["real_pnl"], 0.01) * size_usd for t in trades), 0.01), 2),
        "is_carry": True,
        "trades": trades,
    }


# ── FastAPI endpoint (si utilisé dans l'API) ──
try:
    from fastapi import APIRouter
    from fastapi.responses import HTMLResponse
    router = APIRouter()

    @router.get("/live-pnl")
    async def live_pnl_endpoint():
        return get_live_pnl()

    @router.get("/carry-pnl")
    async def carry_pnl_endpoint():
        """P&L réel du carry (two-leg : basis + funding)."""
        return get_carry_pnl()

    @router.get("/live-pnl-widget", response_class=HTMLResponse)
    async def live_pnl_widget():
        """Widget HTML auto-rafraîchi — intégré en iframe dans le dashboard."""
        data = get_live_pnl()
        total = data.get("total_pnl", 0)
        color = "#2ecc71" if total >= 0 else "#e74c3c"
        sign = "+" if total >= 0 else ""
        trades_html = " | ".join(
            f'{t["symbol"]} {sign}{t["pnl_usd"]:.2f}$ ({sign}{t["pnl_pct"]:.2f}%)'
            for t in data.get("trades", [])
        )
        return HTML(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta http-equiv="refresh" content="10">
<style>body{{margin:0;padding:4px 12px;background:#0d1117;color:#e6edf3;
font-family:monospace;font-size:12px;border-radius:6px;border:1px solid #30363d;
white-space:nowrap;overflow:hidden;}}</style></head>
<body>💰 P&L: <b style="color:{color}">{sign}{total:.2f}$</b> &nbsp;{trades_html}</body>
</html>""")
except ImportError:
    router = None
