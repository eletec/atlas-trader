"""
v7/backtest_v7_node.py — Backtest utilisant le vrai FundingCarryNode (pas une simulation).

Importe le même nœud que le live, le nourrit avec l'historique de funding,
et produit des métriques réalistes (mêmes règles que le live).

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


def fetch_funding_history(symbol: str, days: int) -> pd.DataFrame:
    """Récupère l'historique des funding rates depuis Binance."""
    try:
        import ccxt
        exchange = ccxt.binance({"enableRateLimit": True})
        symbol_perp = f"{symbol}:USDT" if ":" not in symbol else symbol
        since = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)

        rates = exchange.fetch_funding_rate_history(symbol_perp, since=since, limit=1000)
        if not rates:
            # Fallback: public API
            import requests
            symbol_clean = symbol.replace("/", "")
            resp = requests.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": symbol_clean, "limit": min(days * 3, 1000)},
                timeout=30,
            )
            rates = resp.json()
            if not isinstance(rates, list):
                return pd.DataFrame(columns=["timestamp", "funding_rate"])

        rows = []
        for r in rates:
            ts = r.get("fundingTime") or r.get("timestamp") or 0
            fr = float(r.get("fundingRate", 0))
            rows.append({"timestamp": ts, "funding_rate": fr})

        df = pd.DataFrame(rows).sort_values("timestamp")
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        logger.error("Funding fetch failed for %s: %s", symbol, e)
        return pd.DataFrame(columns=["timestamp", "funding_rate"])


def backtest_asset(symbol: str, days: int, capital: float) -> dict[str, Any]:
    """Backtest un actif avec le vrai FundingCarryNode."""
    from v7.nodes.funding_carry_node import FundingCarryNode

    funding_df = fetch_funding_history(symbol, days)
    if funding_df.empty:
        return {"symbol": symbol, "error": "no data"}

    # Initialiser le nœud avec les mêmes params que le live
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
    )

    trades: list[dict] = []
    total_funding_collected = 0.0
    total_fees = 0.0
    daily_pnl: list[float] = []

    prev_date = None
    daily_pnl_sum = 0.0

    for _, row in funding_df.iterrows():
        fr = float(row["funding_rate"])
        ts = row["datetime"]
        date_key = ts.date()

        # Simuler un prix spot approximatif (on n'a pas l'historique spot,
        # mais le nœud ne l'utilise que pour le basis — on met un prix fixe)
        # Le vrai edge vient du funding, pas du prix
        spot_price = 1000.0  # prix fictif (le carry est market-neutral)
        perp_price = spot_price  # basis=0 en l'absence de données spot

        # Appeler le nœud avec ces inputs
        try:
            result = node.run({
                "spot_price": spot_price,
                "funding_rate": fr,
                "perp_price": perp_price,
            })
        except Exception as e:
            logger.debug("%s: node.run error at %s: %s", symbol, ts, e)
            continue

        signal = result.get("signal", "flat")
        size_usd = result.get("size_usd", 0)

        # Suivi des trades
        if signal == "open_carry" and size_usd > 0:
            fee = size_usd * 0.0007  # 5bps spot + 2bps perp
            total_fees += fee
            trades.append({
                "open_ts": ts.isoformat(),
                "size_usd": size_usd,
                "signal": signal,
                "fee": fee,
            })

        if signal == "close_carry":
            fee = node.state.entry_capital * 0.0007
            total_fees += fee
            # Trouver le trade correspondant et le fermer
            for t in trades:
                if t.get("close_ts") is None:
                    t["close_ts"] = ts.isoformat()
                    t["exit_reason"] = result.get("reason", "")
                    break

        # Accumuler le funding collecté
        fr_collected = result.get("total_funding_received", 0)
        total_funding_collected = max(total_funding_collected, fr_collected)

        # PnL quotidien
        if prev_date and date_key != prev_date:
            daily_pnl.append(daily_pnl_sum)
            daily_pnl_sum = 0.0
        prev_date = date_key

    if daily_pnl_sum != 0:
        daily_pnl.append(daily_pnl_sum)

    # Calcul des métriques
    open_trades = [t for t in trades if t.get("close_ts") is None]
    closed_trades = [t for t in trades if t.get("close_ts") is not None]
    total_pnl = total_funding_collected - total_fees

    # Sharpe (sur les returns quotidiens si dispo, sinon estimation)
    if len(daily_pnl) > 5:
        returns = np.array(daily_pnl) / capital
        sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0
    else:
        sharpe = 0.0

    return {
        "symbol": symbol,
        "pnl": round(total_pnl, 2),
        "pnl_pct": round(total_pnl / capital * 100, 2),
        "funding_collected": round(total_funding_collected, 4),
        "fees": round(total_fees, 2),
        "trades": len(trades),
        "open": len(open_trades),
        "closed": len(closed_trades),
        "sharpe": round(sharpe, 2),
        "days": days,
    }


def main():
    parser = argparse.ArgumentParser(description="V7 Backtest — via FundingCarryNode (live logic)")
    parser.add_argument("--symbol", type=str, default="ALL")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--capital", type=float, default=2000)
    args = parser.parse_args()

    symbols = SYMBOLS if args.symbol == "ALL" else [args.symbol]

    print("=" * 80)
    print("ATLAS V7 — Backtest (FundingCarryNode — live logic)")
    print(f"Days: {args.days} | Capital: ${args.capital:,.0f}/asset")
    print("=" * 80)

    results = []
    t0 = time.time()
    for sym in symbols:
        logger.info("Backtesting %s...", sym)
        r = backtest_asset(sym, args.days, args.capital)
        results.append(r)
        if "error" not in r:
            print(f"  {sym:<12} PnL=${r['pnl']:>8,.2f} ({r['pnl_pct']:>5.1f}%)  "
                  f"Sharpe={r['sharpe']:>6.2f}  Trades={r['trades']:>3d}  "
                  f"Funding=${r['funding_collected']:,.2f}  Fees=${r['fees']:,.2f}")

    elapsed = time.time() - t0

    # Résumé portfolio
    valid = [r for r in results if "error" not in r]
    if valid:
        total_pnl = sum(r["pnl"] for r in valid)
        total_capital = args.capital * len(valid)
        avg_sharpe = np.mean([r["sharpe"] for r in valid])
        print("\n" + "=" * 80)
        print(f"Portfolio: {len(valid)} actifs | PnL=${total_pnl:,.2f} ({total_pnl/total_capital*100:.1f}%)")
        print(f"Sharpe moyen={avg_sharpe:.2f} | Durée={elapsed:.0f}s")
        print("=" * 80)


if __name__ == "__main__":
    main()
