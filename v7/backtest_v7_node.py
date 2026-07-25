"""
v7/backtest_v7_node.py — Backtest avec le vrai FundingCarryNode + prix réels spot/perp.

Fetch les données daily spot + perp + funding, les aligne, et nourrit le
même nœud que le live. Produit des métriques réalistes.

Usage:
    docker exec atlas-v4-api python /app/src/v7/backtest_v7_node.py --symbol ALL --days 365
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Désactiver les appels DB dans le GlobalAllocator pour le backtest
os.environ["V7_BACKTEST"] = "1"

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backtest_v7_node")

# ── Charger les actifs depuis la config ──
try:
    from v7.core.asset_config import get_active_assets, get_all_assets
    SYMBOLS = get_active_assets()
    ALL_SYMBOLS = get_all_assets()
    if not SYMBOLS:
        SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
    logger.info("Loaded %d active assets from config", len(SYMBOLS))
except Exception:
    SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
    ALL_SYMBOLS = SYMBOLS


def _perp_symbol(symbol: str) -> str:
    """Convertit un symbole spot en symbole perp USDⓈ-M (gère les contrats ×1000)."""
    base = symbol.split("/")[0]
    MULTIPLIER_MAP = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "BONK": "1000BONK",
                      "FLOKI": "1000FLOKI", "LUNC": "1000LUNC"}
    base_perp = MULTIPLIER_MAP.get(base, base)
    return f"{base_perp}/USDT:USDT"


def fetch_prices(symbol: str, days: int, is_perp: bool = False) -> pd.DataFrame:
    """Fetch daily OHLCV spot ou perp via CCXT."""
    try:
        import ccxt
        if is_perp:
            ex = ccxt.binanceusdm({"enableRateLimit": True})
            sym = _perp_symbol(symbol)
        else:
            ex = ccxt.binance({"enableRateLimit": True})
            sym = symbol
        since = ex.parse8601((datetime.utcnow() - timedelta(days=days + 7)).strftime("%Y-%m-%dT00:00:00Z"))
        ohlcv = ex.fetch_ohlcv(sym, "1d", since=since, limit=days + 10)
        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.set_index("datetime")
        return df[["close"]].rename(columns={"close": "perp_price" if is_perp else "spot_price"})
    except Exception as e:
        logger.warning("Price fetch %s (perp=%s): %s", symbol, is_perp, e)
        return pd.DataFrame()


def fetch_funding_history(symbol: str, days: int) -> pd.DataFrame:
    """Récupère l'historique des funding rates depuis Binance USDⓈ-M."""
    try:
        import ccxt
        exchange = ccxt.binanceusdm({"enableRateLimit": True})
        symbol_perp = _perp_symbol(symbol)
        since = int((datetime.utcnow() - timedelta(days=days + 1)).timestamp() * 1000)
        rates = exchange.fetch_funding_rate_history(symbol_perp, since=since, limit=1000)
        if not rates:
            import requests
            symbol_clean = symbol.replace("/", "")
            resp = requests.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": symbol_clean, "limit": min(days * 3, 1000)},
                timeout=30,
            )
            rates = resp.json()
            if not isinstance(rates, list):
                return pd.DataFrame()
        rows = [{"timestamp": r.get("fundingTime") or r.get("timestamp") or 0,
                 "funding_rate": float(r.get("fundingRate", 0))} for r in rates]
        df = pd.DataFrame(rows).sort_values("timestamp")
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df.set_index("datetime")
    except Exception as e:
        logger.error("Funding fetch failed for %s: %s", symbol, e)
        return pd.DataFrame()


def backtest_asset(symbol: str, days: int = 365, capital: float = 2_000,
                   params_override: dict | None = None) -> dict:
    """Backtest un actif avec le vrai FundingCarryNode + prix reels."""
    from v7.nodes.funding_carry_node import FundingCarryNode

    # 1) Charger les donnees
    spot_df = fetch_prices(symbol, days, is_perp=False)
    perp_df = fetch_prices(symbol, days, is_perp=True)
    funding_df = fetch_funding_history(symbol, days)

    if funding_df.empty:
        return {"symbol": symbol, "error": "no funding data"}

    # 2) Fusionner prix + funding sur les dates
    # Interpoler les prix spot/perp aux timestamps de funding (forward fill)
    if not spot_df.empty and not perp_df.empty:
        combined = funding_df.join(spot_df.rename(columns={"spot_price": "spot_raw"}), how="left")
        combined = combined.join(perp_df.rename(columns={"perp_price": "perp_raw"}), how="left")
        combined["spot_price"] = combined["spot_raw"].ffill().fillna(1000)
        combined["perp_price"] = combined["perp_raw"].ffill().fillna(combined["spot_price"])
    else:
        # Fallback: prix fixes
        combined = funding_df.copy()
        combined["spot_price"] = 1000.0
        combined["perp_price"] = 1000.0

    if combined.empty:
        return {"symbol": symbol, "error": "no merged data"}

    # 3) Initialiser le noeud (params override pour grid search)
    ov = params_override or {}
    node = FundingCarryNode(
        node_id=f"bt_{symbol.split('/')[0].lower()}",
        symbol=symbol,
        capital=capital,
        fraction=ov.get("fraction", 0.50),
        min_funding=ov.get("min_funding", 0.00005),
        max_funding=0.003,
        exit_after_hours=72,
        max_hold_days=ov.get("max_hold_days", 14),
        stop_loss_pct=-0.05,
        params={"_backtest": True},
    )

    # 4) Boucle de backtest avec NAV tracking (Round 4, 22/07/2026)
    trades: list[dict] = []
    total_funding = 0.0
    total_fees = 0.0
    nav_history: list[tuple] = []  # (timestamp, nav_value)
    prev_nav = capital  # start at capital

    for ts, row in combined.iterrows():
        fr = float(row["funding_rate"])
        spot_price = float(row["spot_price"])
        perp_price = float(row["perp_price"])
        
        # Ajuster le prix perp pour les contrats à multiplicateur (1000PEPE, etc.)
        base = symbol.split("/")[0]
        MULT = {"PEPE": 1000, "SHIB": 1000, "BONK": 1000, "FLOKI": 1000, "LUNC": 1000}
        contract_mult = MULT.get(base, 1)
        perp_price = perp_price / contract_mult

        result = node.run({
            "symbol": symbol,
            "spot_price": spot_price,
            "funding_rate": fr,
            "perp_price": perp_price,
        })

        signal = result.get("signal", "flat")
        size_usd = result.get("size_usd", 0)
        total_funding = max(total_funding, result.get("total_funding_received", 0) or 0)
        unrealized_pct = result.get("unrealized_pnl_pct", 0) or 0
        position_open = result.get("position_open", False)

        # Frais: 4 jambes × 12bps = 48bps round-trip (GPT audit, 25/07/2026)
        #   Open:  long spot (12bps) + short perp (12bps) = 24bps
        #   Close: sell spot (12bps) + buy back perp (12bps) = 24bps
        cost_this_step = 0.0
        if signal == "open_carry" and size_usd > 0:
            cost_this_step = size_usd * 0.0024  # 24bps = 2 jambes (spot + perp)
            total_fees += cost_this_step
            trades.append({"open_ts": ts, "size": size_usd, "open_fee": cost_this_step, "close_fee": 0.0})

        if signal == "close_carry":
            cost_this_step = node.state.entry_capital * 0.0024  # 24bps = 2 jambes
            total_fees += cost_this_step
            if trades and trades[-1].get("close_fee") == 0.0:
                trades[-1]["close_fee"] = cost_this_step
                trades[-1]["close_ts"] = ts

        # ── NAV computation ──
        # NAV = capital + funding_collected + staking - fees + unrealized_carry_pnl
        staking_now = node.state.staking_earned
        unrealized_usd = unrealized_pct * (node.state.entry_capital if position_open else 0) if position_open else 0
        nav = capital + total_funding + staking_now - total_fees + unrealized_usd
        nav_history.append((ts, nav))
        prev_nav = nav

    # 5) Métriques (Round 4: NAV-based Sharpe + Max DD)
    staking = node.state.staking_earned
    total_pnl = total_funding + staking - total_fees

    # NAV returns
    if len(nav_history) > 2 and len(trades) > 0:
        nav_df = pd.DataFrame(nav_history, columns=["ts", "nav"]).set_index("ts")
        nav_df["return"] = nav_df["nav"].pct_change().fillna(0)
        # Sharpe annualisé (×√365 pour daily, ×√1095 pour 8h)
        periods_per_day = 3  # funding 8h
        nav_returns = nav_df["return"].dropna()
        if len(nav_returns) > 10 and nav_returns.std() > 0:
            sharpe = float(nav_returns.mean() / nav_returns.std() * np.sqrt(365 * periods_per_day))
        else:
            sharpe = 0.0
        # Max drawdown
        nav_df["peak"] = nav_df["nav"].cummax()
        nav_df["dd"] = (nav_df["nav"] - nav_df["peak"]) / nav_df["peak"] * 100
        max_dd = float(nav_df["dd"].min())
    else:
        sharpe = 0.0
        max_dd = 0.0

    # ── Per-trade breakdown (GPT audit, 25/07/2026) ──
    trade_breakdown = []
    for t in trades:
        open_fee = t.get("open_fee", 0)
        close_fee = t.get("close_fee", 0)
        trade_breakdown.append({
            "open_ts": str(t.get("open_ts", "")),
            "close_ts": str(t.get("close_ts", "")),
            "size_usd": round(t.get("size", 0), 2),
            "open_fee": round(open_fee, 4),
            "close_fee": round(close_fee, 4),
            "total_fee": round(open_fee + close_fee, 4),
        })

    return {
        "symbol": symbol,
        "pnl": round(total_pnl, 2),
        "pnl_pct": round(total_pnl / capital * 100, 2),
        "funding": round(total_funding, 4),
        "staking": round(staking, 2),
        "fees": round(total_fees, 2),
        "trades": len(trades),
        "sharpe": round(sharpe, 2),
        "max_dd_pct": round(max_dd, 2),
        "days": days,
        "params": params_override or {},  # pour le grid search
        "trade_breakdown": trade_breakdown,  # per-trade P&L audit
    }


def main():
    parser = argparse.ArgumentParser(description="V7 Backtest — FundingCarryNode + données réelles")
    parser.add_argument("--symbol", type=str, default="ALL")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--capital", type=float, default=2000)
    args = parser.parse_args()

    symbols = ALL_SYMBOLS if args.symbol == "ALL" else (SYMBOLS if args.symbol == "ACTIVE" else [args.symbol])

    print("=" * 80)
    print("ATLAS V7 — Backtest (FundingCarryNode + prix spot/perp réels)")
    print(f"Symbols: {len(symbols)} actifs | Days: {args.days} | Capital: ${args.capital:,.0f}/asset | Staking: 5%/an sur idle")
    print("=" * 80)

    results = []
    t0 = time.time()
    for sym in symbols:
        logger.info("%s...", sym)
        r = backtest_asset(sym, args.days, args.capital)
        results.append(r)
        if "error" not in r:
            print(f"  {sym:<12} PnL=${r['pnl']:>8,.2f} ({r['pnl_pct']:>5.1f}%)  "
                  f"Sharpe={r['sharpe']:>6.2f}  MaxDD={r['max_dd_pct']:>5.1f}%  Trades={r['trades']:>3d}  "
                  f"Funding=${r['funding']:,.2f}  Staking=${r['staking']:,.2f}  Fees=${r['fees']:,.2f}")
        else:
            print(f"  {sym:<12} ERROR: {r['error']}")

    elapsed = time.time() - t0

    # ── Sauvegarder les résultats en JSON pour l'optimiseur ──
    try:
        import json as _json
        out_path = Path("/app/data/backtest_results.json")
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "days": args.days,
            "capital_per_asset": args.capital,
            "symbols": symbols,
            "results": results,
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            _json.dump(summary, f, default=str)
    except Exception:
        pass

    valid = [r for r in results if "error" not in r and r.get("trades", 0) > 0]
    staking_only = [r for r in results if "error" not in r and r.get("trades", 0) == 0]
    total_pnl = sum(r["pnl"] for r in results if "error" not in r)
    total_cap = args.capital * len([r for r in results if "error" not in r])
    if valid:
        avg_sharpe = np.mean([r["sharpe"] for r in valid])
    else:
        avg_sharpe = 0.0
    print("\n" + "=" * 80)
    print(f"Portfolio: {len(symbols)} actifs | {len(valid)} tradés, {len(staking_only)} staking seul | "
          f"PnL=${total_pnl:,.2f} ({total_pnl/total_cap*100:.1f}%)")
    print(f"Sharpe moyen={avg_sharpe:.2f} (actifs tradés) | Durée={elapsed:.0f}s | Capital total=${total_cap:,.0f}")
    print("=" * 80)


if __name__ == "__main__":
    main()
