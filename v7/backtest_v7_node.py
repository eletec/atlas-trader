"""
v7/backtest_v7_node.py — Backtest with the real FundingCarryNode + real spot/perp prices.

Fetches the daily spot + perp + funding data, aligns it, and feeds the same
node that runs live. Produces realistic metrics.

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

## Disable DB calls in the GlobalAllocator for the backtest
os.environ["V7_BACKTEST"] = "1"

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backtest_v7_node")

# -- Load the assets from the config --
try:
    from v7.core.asset_config import get_active_assets, get_all_assets, normalize_symbol
    SYMBOLS = get_active_assets()
    ALL_SYMBOLS = get_all_assets()
    if not SYMBOLS:
        SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
    logger.info("Loaded %d active assets from config", len(SYMBOLS))
except Exception:
    SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
    ALL_SYMBOLS = SYMBOLS

    def normalize_symbol(raw: str) -> str:  # fallback minimal
        s = (raw or "").strip().upper()
        return s if "/" in s else f"{s}/USDT"


def _perp_symbol(symbol: str) -> str:
    """Convert a spot symbol into a USDⓈ-M perp symbol (handles x1000 contracts)."""
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
    """Fetch the funding rate history from Binance USDⓈ-M."""
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
    """Backtest one asset with the real FundingCarryNode + real prices."""
    from v7.nodes.funding_carry_node import FundingCarryNode

    # 1) Load the data
    spot_df = fetch_prices(symbol, days, is_perp=False)
    perp_df = fetch_prices(symbol, days, is_perp=True)
    funding_df = fetch_funding_history(symbol, days)

    if funding_df.empty:
        return {"symbol": symbol, "error": "no funding data"}

    # 2) Merge prices + funding on the dates
    # Interpolate the spot/perp prices onto the funding timestamps (forward fill)
    if not spot_df.empty and not perp_df.empty:
        combined = funding_df.join(spot_df.rename(columns={"spot_price": "spot_raw"}), how="left")
        combined = combined.join(perp_df.rename(columns={"perp_price": "perp_raw"}), how="left")
        combined["spot_price"] = combined["spot_raw"].ffill().bfill()
        combined["perp_price"] = combined["perp_raw"].ffill().bfill()
        if combined["spot_price"].isna().any() or combined["perp_price"].isna().any():
            return {"symbol": symbol, "error": "spot/perp prices cannot be aligned with the funding"}
    else:
        # OLD BEHAVIOUR (bug): a silent $1000 fallback meant the backtest
        # no longer modelled any price risk and displayed fabricated P&L.
        logger.error("Spot/perp prices unavailable for %s — backtest refused", symbol)
        return {
            "symbol": symbol,
            "error": "spot/perp prices unavailable (fabricated fallback removed)",
        }

    if combined.empty:
        return {"symbol": symbol, "error": "no merged data"}

    # 3) Initialise the node (params override for the grid search)
    # Params read from carry_assets.yaml so the run mirrors the live strategy.
    ov = params_override or {}
    try:
        from v7.core.asset_config import get_asset_params
        _cfg = get_asset_params(symbol)
    except Exception:
        _cfg = {}
    node = FundingCarryNode(
        node_id=f"bt_{symbol.split('/')[0].lower()}",
        symbol=symbol,
        capital=capital,
        fraction=ov.get("fraction", float(_cfg.get("fraction", 0.50))),
        min_funding=ov.get("min_funding", float(_cfg.get("min_funding", 0.0002))),
        max_funding=float(_cfg.get("max_funding", 0.003)),
        exit_after_hours=int(_cfg.get("exit_after_hours", 72)),
        max_hold_days=ov.get("max_hold_days", int(_cfg.get("max_hold_days", 30))),
        stop_loss_pct=float(_cfg.get("stop_loss_pct", -0.05)),
        params={"_backtest": True, **ov.get("node_params", {})},
    )

    # 4) Backtest loop with NAV tracking (round 5, 2026-07-25)
    # BUGFIX: unrealized_pnl_pct from node is already ×100 (percent), backtest must ÷100
    trades: list[dict] = []
    realized_total = 0.0     # sum of closed positions' P&L (funding + basis - fees)
    funding_closed = 0.0     # signed funding of the closed positions
    fees_closed = 0.0        # fees of the closed positions
    nav_history: list[tuple] = []  # (timestamp, trading_nav, total_nav)
    no_trade_reason = ""  # diagnostic for assets that never trade
    max_funding_seen = 0.0  # for diagnosing why no trade

    for ts, row in combined.iterrows():
        fr = float(row["funding_rate"])
        spot_price = float(row["spot_price"])
        perp_price = float(row["perp_price"])
        max_funding_seen = max(max_funding_seen, fr)
        
        # Adjust the perp price for multiplier contracts (1000PEPE, etc.)
        base = symbol.split("/")[0]
        MULT = {"PEPE": 1000, "SHIB": 1000, "BONK": 1000, "FLOKI": 1000, "LUNC": 1000}
        contract_mult = MULT.get(base, 1)
        perp_price = perp_price / contract_mult

        result = node.run({
            "symbol": symbol,
            "spot_price": spot_price,
            "funding_rate": fr,
            "perp_price": perp_price,
            # Simulated bar timestamp: the node's time-based exits (time-stop,
            # DERISK/CLOSE zones, negative-funding timer, cooldown) are evaluated
            # against it instead of the real clock.
            "now": ts,
        })

        signal = result.get("signal", "flat")
        size_usd = result.get("size_usd", 0)
        # The node owns the accounting; the backtest only accumulates it.
        # Funding is SIGNED, the four legs are charged by the node on entry and on
        # exit, and a close realises the basis instead of dropping it. Recomputing
        # any of it here is how the two engines used to disagree.
        unrealized_pnl_pct_raw = result.get("unrealized_pnl_pct", 0) or 0
        unrealized_pct = unrealized_pnl_pct_raw / 100.0  # convert % → decimal
        position_open = result.get("position_open", False)
        reason = result.get("reason", "")

        # Track reason for non-trading assets
        if not position_open and signal == "flat" and reason and not no_trade_reason:
            no_trade_reason = reason[:120]

        if signal == "open_carry" and size_usd > 0:
            trades.append({"open_ts": ts, "size": size_usd, "open_fee": 0.0, "close_fee": 0.0})

        if signal == "close_carry":
            realized = float(result.get("realized_pnl_usd", 0) or 0)
            realized_total += realized
            funding_closed += node.state.total_funding_received
            fees_closed += node.state.fees_paid
            if trades:
                trades[-1]["close_fee"] = node.state.fees_paid
                trades[-1]["close_ts"] = ts
                trades[-1]["realized"] = realized

        # ── NAV computation ──
        # Trading NAV = capital + the closed positions' P&L + the open position's
        # mark-to-market. Staking is tracked separately: it is not trading alpha.
        staking_now = node.state.staking_earned
        unrealized_usd = unrealized_pct * (node.state.entry_capital if position_open else 0) if position_open else 0
        open_mtm = 0.0
        if position_open:
            open_mtm = (node.state.total_funding_received
                        - node.state.fees_paid + unrealized_usd)
        trading_nav = capital + realized_total + open_mtm
        total_nav = trading_nav + staking_now
        nav_history.append((ts, trading_nav, total_nav))

    # 5) Metrics (round 5, 2026-07-25 - GPT audit: staking separated, unrealised % fix)
    staking = node.state.staking_earned
    # Final figures: the closed positions' realised P&L plus what the open position
    # is worth, marked at the last price of the run.
    total_funding = funding_closed
    total_fees = fees_closed
    if position_open:
        total_funding += node.state.total_funding_received
        total_fees += node.state.fees_paid
    trading_pnl = realized_total + (open_mtm if position_open else 0.0)
    basis_pnl = trading_pnl - total_funding + total_fees
    total_pnl = trading_pnl + staking  # includes staking for reference, but trading_pnl is the real metric
    
    # No-trade diagnostic
    if len(trades) == 0 and not no_trade_reason:
        periods_per_year = 365 * 24 / 8
        max_annual = max_funding_seen * periods_per_year
        no_trade_reason = f"max funding={max_funding_seen*100:.4f}% ({max_annual*100:.1f}%/yr) < hurdle=5%"

    # NAV returns (use trading NAV for Sharpe/MaxDD — staking-free)
    if len(nav_history) > 2:
        nav_df = pd.DataFrame(nav_history, columns=["ts", "trading_nav", "total_nav"]).set_index("ts")
        nav_df["trading_return"] = nav_df["trading_nav"].pct_change().fillna(0)
        periods_per_day = 3  # funding 8h
        nav_returns = nav_df["trading_return"].dropna()
        if len(nav_returns) > 10 and nav_returns.std() > 0:
            sharpe = float(nav_returns.mean() / nav_returns.std() * np.sqrt(365 * periods_per_day))
        else:
            sharpe = 0.0
        # Max drawdown on trading NAV
        nav_df["peak"] = nav_df["trading_nav"].cummax()
        nav_df["dd"] = (nav_df["trading_nav"] - nav_df["peak"]) / nav_df["peak"] * 100
        max_dd = float(nav_df["dd"].min())
        # Capital utilisation: % of time position was open
        position_mask = nav_df.index.isin([t.get("open_ts") for t in trades])
        # Approximate: count periods with unrealized != 0 or funding received
        capital_utilisation = len(nav_returns[nav_returns.abs() > 1e-10]) / max(len(nav_returns), 1) * 100
    else:
        sharpe = 0.0
        max_dd = 0.0
        capital_utilisation = 0.0

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
            "realized": round(t.get("realized", 0), 4),
        })

    return {
        "symbol": symbol,
        "pnl": round(trading_pnl, 2),           # trading P&L ONLY (funding - fees, ex-staking)
        "pnl_pct": round(trading_pnl / capital * 100, 2),
        "total_pnl": round(total_pnl, 2),        # trading + staking (for reference)
        "total_pnl_pct": round(total_pnl / capital * 100, 2),
        "funding": round(total_funding, 4),
        "basis_pnl": round(basis_pnl, 2),        # realised + marked basis, net of funding
        "staking": round(staking, 2),
        "fees": round(total_fees, 2),
        "trading_pnl": round(trading_pnl, 2),    # explicit alias
        "trades": len(trades),
        "sharpe": round(sharpe, 2),
        "max_dd_pct": round(max_dd, 2),
        "days": days,
        "capital_utilisation_pct": round(capital_utilisation, 1),
        "no_trade_reason": no_trade_reason if len(trades) == 0 else "",
        "params": params_override or {},  # for the grid search
        "trade_breakdown": trade_breakdown,  # per-trade P&L audit
    }


def main():
    parser = argparse.ArgumentParser(description="V7 Backtest — FundingCarryNode + real spot/perp prices")
    parser.add_argument("--symbol", type=str, default="ALL",
                        help="ALL, ACTIVE, BTC, BTC/USDT, or BTC,ETH (comma-separated)")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--capital", type=float, default=2000)
    parser.add_argument("--fraction", type=float, default=None,
                        help="Share of capital held in carry (default: value from carry_assets.yaml)")
    args = parser.parse_args()

    if args.symbol == "ALL":
        symbols = ALL_SYMBOLS
    elif args.symbol == "ACTIVE":
        symbols = SYMBOLS
    else:
        symbols = [normalize_symbol(s) for s in args.symbol.split(",") if s.strip()]

    print("=" * 90)
    print("ATLAS V7 — Backtest (FundingCarryNode + real spot/perp prices)")
    print(f"Symbols: {len(symbols)} assets | Days: {args.days} | Capital: ${args.capital:,.0f}/asset")
    print(f"Fees: 48bps RT (4 legs) | Hurdle: 5% | Staking: 5%/yr on idle (separate from trading P&L)")
    print("=" * 90)

    results = []
    t0 = time.time()
    for sym in symbols:
        logger.info("%s...", sym)
        _ov = {"fraction": args.fraction} if args.fraction is not None else None
        r = backtest_asset(sym, args.days, args.capital, params_override=_ov)
        results.append(r)
        if "error" not in r:
            tag = ""
            if r.get("no_trade_reason"):
                tag = f"  ⚠️ {r['no_trade_reason'][:80]}"
            print(f"  {sym:<12} Trade=${r['trading_pnl']:>7,.2f} ({r['pnl_pct']:>5.1f}%)  "
                  f"Sharpe={r['sharpe']:>6.2f}  MaxDD={r['max_dd_pct']:>5.1f}%  "
                  f"Trades={r['trades']:>2d}  Util={r['capital_utilisation_pct']:>4.1f}%  "
                  f"Fees=${r['fees']:>5.2f}{tag}")
        else:
            print(f"  {sym:<12} ERROR: {r['error']}")

    elapsed = time.time() - t0

    # -- Save the results as JSON for the optimiser --
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
    total_trading_pnl = sum(r["trading_pnl"] for r in results if "error" not in r)
    total_staking = sum(r["staking"] for r in results if "error" not in r)
    total_pnl_all = total_trading_pnl + total_staking
    total_cap = args.capital * len([r for r in results if "error" not in r])
    if valid:
        avg_sharpe = np.mean([r["sharpe"] for r in valid])
        avg_util = np.mean([r["capital_utilisation_pct"] for r in valid])
    else:
        avg_sharpe = 0.0
        avg_util = 0.0
    print("\n" + "=" * 90)
    print(f"Portfolio: {len(symbols)} assets | {len(valid)} traded, {len(staking_only)} with no trade")
    print()
    print(f"  TRADING (the strategy) : ${total_trading_pnl:>10,.2f}   {total_trading_pnl/total_cap*100:+.2f}%")
    print(f"  Staking (idle capital) : ${total_staking:>10,.2f}   {total_staking/total_cap*100:+.2f}%   <-- simulated, NOT trading")
    print( "  " + "-" * 72)
    print(f"  Total                  : ${total_pnl_all:>10,.2f}   {total_pnl_all/total_cap*100:+.2f}%   <-- do not read as a strategy performance")
    print()
    if not valid:
        print("  ⚠️  NO TRADE over the period: at these funding levels no asset clears")
        print("      the entry threshold (min_funding). The 'Total' above is entirely")
        print("      staking on idle capital.")
    elif total_trading_pnl <= 0:
        print("  ⚠️  The strategy is flat or losing over the period.")
    print(f"\n  Mean Sharpe (traded): {avg_sharpe:.2f} | Capital utilisation: {avg_util:.1f}%")
    print(f"  Duration: {elapsed:.0f}s | Total capital: ${total_cap:,.0f}")
    if staking_only:
        print(f"\n⚠️  {len(staking_only)} assets with no trade (simulated staking only):")
        for r in staking_only:
            print(f"    {r['symbol']:<12} → {r.get('no_trade_reason', '?')}")
    print("=" * 90)


if __name__ == "__main__":
    main()
