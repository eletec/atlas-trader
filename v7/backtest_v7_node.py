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
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backtest_v7_node")

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]


def fetch_prices(symbol: str, days: int, is_perp: bool = False) -> pd.DataFrame:
    """Fetch daily OHLCV spot ou perp via CCXT."""
    try:
        import ccxt
        ex = ccxt.binance({"enableRateLimit": True})
        sym = f"{symbol}:USDT" if is_perp and ":" not in symbol else symbol
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
    """Récupère l'historique des funding rates depuis Binance."""
    try:
        import ccxt
        exchange = ccxt.binance({"enableRateLimit": True})
        symbol_perp = f"{symbol}:USDT" if ":" not in symbol else symbol
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


def backtest_asset(symbol: str, days: int, capital: float) -> dict[str, Any]:
    """Backtest un actif avec le vrai FundingCarryNode + prix réels."""
    from v7.nodes.funding_carry_node import FundingCarryNode

    # 1) Charger les données
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

    # 3) Initialiser le nœud (mêmes params que le live)
    node = FundingCarryNode(
        node_id=f"bt_{symbol.split('/')[0].lower()}",
        symbol=symbol,
        capital=capital,
        fraction=0.80,
        min_funding=0.00001,
        max_funding=0.003,
        exit_after_hours=168,
        kelly_fraction=0.25,
        max_hold_days=14,
        stop_loss_pct=-0.05,
        params={"_backtest": True},  # ne pas restaurer depuis la DB live
    )

    # 4) Boucle de backtest
    trades: list[dict] = []
    total_funding = 0.0
    total_fees = 0.0
    pnl_history: list[float] = []
    daily_pnl: float = 0.0
    prev_ts = None

    for ts, row in combined.iterrows():
        fr = float(row["funding_rate"])
        spot_price = float(row["spot_price"])
        perp_price = float(row["perp_price"])

        result = node.run({
            "symbol": symbol,
            "spot_price": spot_price,
            "funding_rate": fr,
            "perp_price": perp_price,
        })

        signal = result.get("signal", "flat")
        size_usd = result.get("size_usd", 0)
        total_funding = max(total_funding, result.get("total_funding_received", 0) or 0)

        # Frais simulés
        if signal == "open_carry" and size_usd > 0:
            fee = size_usd * 0.0007
            total_fees += fee
            trades.append({"open_ts": ts, "size": size_usd, "fee": fee})

        if signal == "close_carry":
            fee = node.state.entry_capital * 0.0007
            total_fees += fee

    # 5) Métriques
    total_pnl = total_funding - total_fees
    returns = pd.Series(pnl_history).dropna()
    sharpe = float(returns.mean() / returns.std() * np.sqrt(365)) if len(returns) > 5 and returns.std() > 0 else 0.0

    return {
        "symbol": symbol,
        "pnl": round(total_pnl, 2),
        "pnl_pct": round(total_pnl / capital * 100, 2),
        "funding": round(total_funding, 4),
        "fees": round(total_fees, 2),
        "trades": len(trades),
        "sharpe": round(sharpe, 2),
        "days": days,
    }


def main():
    parser = argparse.ArgumentParser(description="V7 Backtest — FundingCarryNode + données réelles")
    parser.add_argument("--symbol", type=str, default="ALL")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--capital", type=float, default=2000)
    args = parser.parse_args()

    symbols = SYMBOLS if args.symbol == "ALL" else [args.symbol]

    print("=" * 80)
    print("ATLAS V7 — Backtest (FundingCarryNode + prix spot/perp réels)")
    print(f"Days: {args.days} | Capital: ${args.capital:,.0f}/asset")
    print("=" * 80)

    results = []
    t0 = time.time()
    for sym in symbols:
        logger.info("%s...", sym)
        r = backtest_asset(sym, args.days, args.capital)
        results.append(r)
        if "error" not in r:
            print(f"  {sym:<12} PnL=${r['pnl']:>8,.2f} ({r['pnl_pct']:>5.1f}%)  "
                  f"Sharpe={r['sharpe']:>6.2f}  Trades={r['trades']:>3d}  "
                  f"Funding=${r['funding']:,.2f}  Fees=${r['fees']:,.2f}")
        else:
            print(f"  {sym:<12} ERROR: {r['error']}")

    elapsed = time.time() - t0
    valid = [r for r in results if "error" not in r]
    if valid:
        total_pnl = sum(r["pnl"] for r in valid)
        total_cap = args.capital * len(valid)
        avg_sharpe = np.mean([r["sharpe"] for r in valid])
        print("\n" + "=" * 80)
        print(f"Portfolio: {len(valid)} actifs | PnL=${total_pnl:,.2f} ({total_pnl/total_cap*100:.1f}%)")
        print(f"Sharpe moyen={avg_sharpe:.2f} | Durée={elapsed:.0f}s | Capital total=${total_cap:,.0f}")
        print("=" * 80)


if __name__ == "__main__":
    main()
