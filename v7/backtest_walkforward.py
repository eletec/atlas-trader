"""
v7/backtest_walkforward.py — Walk-Forward Backtest (3 years, 2023-2026).

GPT audit priority #2 (25/07/2026):
  - Causal historical universe (assets listed at t, no look-ahead)
  - Walk-forward: train 12 months, test 3 months, step 3 months
  - Frozen parameters (exogenous hurdle, never optimised inside the window)
  - OOS metrics: portfolio Sharpe, MaxDD, % of positive windows
  - Market-regime segmentation (bull/bear/range via BTC)

Usage:
    docker exec atlas-v4-api python -B /app/src/v7/backtest_walkforward.py --days 1278
    docker exec atlas-v4-api python -B /app/src/v7/backtest_walkforward.py --quick  # 6 months, fast
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("walkforward")

# -- Load the assets --
try:
    from v7.core.asset_config import get_active_assets, get_all_assets, normalize_symbol
    SYMBOLS = get_active_assets()
    ALL_SYMBOLS = get_all_assets()
    if not SYMBOLS:
        SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    logger.info("Loaded %d active, %d total assets", len(SYMBOLS), len(ALL_SYMBOLS))
except Exception:
    SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
    ALL_SYMBOLS = SYMBOLS

    def normalize_symbol(raw: str) -> str:  # minimal fallback
        s = (raw or "").strip().upper()
        return s if "/" in s else f"{s}/USDT"


# ═══════════════════════════════════════════════════════════════════════════════
# Data Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def _perp_symbol(symbol: str) -> str:
    base = symbol.split("/")[0]
    MULTIPLIER_MAP = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "BONK": "1000BONK",
                      "FLOKI": "1000FLOKI", "LUNC": "1000LUNC"}
    base_perp = MULTIPLIER_MAP.get(base, base)
    return f"{base_perp}/USDT:USDT"


def fetch_funding_history_3y(symbol: str, days: int = 1300) -> pd.DataFrame:
    """Fetch up to ~3.5 years of funding rates (since ~2023-01-01)."""
    try:
        import ccxt
        exchange = ccxt.binanceusdm({"enableRateLimit": True})
        symbol_perp = _perp_symbol(symbol)
        since = int((datetime.utcnow() - timedelta(days=days + 5)).timestamp() * 1000)
        
        all_rates = []
        while True:
            rates = exchange.fetch_funding_rate_history(symbol_perp, since=since, limit=1000)
            if not rates:
                break
            all_rates.extend(rates)
            since = rates[-1]["timestamp"] + 1
            if len(rates) < 1000:
                break
            time.sleep(0.1)
        
        if not all_rates:
            # Fallback: Binance public API
            import requests
            symbol_clean = symbol.replace("/", "")
            # Handle multiplier contracts
            base = symbol.split("/")[0]
            MULT = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "BONK": "1000BONK",
                    "FLOKI": "1000FLOKI", "LUNC": "1000LUNC"}
            symbol_clean = MULT.get(base, base) + "USDT"
            resp = requests.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": symbol_clean, "limit": 1000},
                timeout=30,
            )
            data = resp.json()
            if isinstance(data, list):
                all_rates = [{"fundingTime": r["fundingTime"], "fundingRate": float(r["fundingRate"])} for r in data]
        
        rows = [{"timestamp": r.get("fundingTime") or r.get("timestamp") or 0,
                 "funding_rate": float(r.get("fundingRate", 0))} for r in all_rates]
        df = pd.DataFrame(rows).sort_values("timestamp")
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("datetime")
        # No shift here. The node credits funding_rate[t] to a position that is
        # ALREADY open at t and uses it for the decision only when flat, which is
        # the correct rule. Shifting made an open position receive funding_rate[t-1]
        # and put the walk-forward a period behind the single-asset backtest.
        return df.dropna(subset=["funding_rate"])
    except Exception as e:
        logger.warning("Funding fetch %s: %s", symbol, e)
        return pd.DataFrame()


def fetch_prices_3y(symbol: str, days: int = 1300, is_perp: bool = False) -> pd.DataFrame:
    """Fetch 8h spot or perp closes, paginated, shifted one bar.

    The single-asset backtest moved to 8h causal prices; this one kept daily
    candles and a plain `index <= ts` slice, so a funding stamp at 08:00 still saw
    the close of that same day at 23:59. Same defect, same fix.

    A bar stamped T closes at T+8h, so shifting the index forward by one bar means
    a stamp can only ever see a bar that has already closed.
    """
    try:
        import ccxt
        from v7.backtest_v7_node import _paginate
        if is_perp:
            ex = ccxt.binanceusdm({"enableRateLimit": True})
            sym = _perp_symbol(symbol)
        else:
            ex = ccxt.binance({"enableRateLimit": True})
            sym = symbol
        since = ex.parse8601((datetime.utcnow() - timedelta(days=days + 5)).strftime("%Y-%m-%dT00:00:00Z"))
        # limit=days + 10 used to cap this: 1310 daily bars for a 1300-day run, but
        # only 383 eight-hour bars, so most of the window had no price at all and
        # the nearest-price lookup silently served a much older one.
        ohlcv = _paginate(
            lambda cursor, limit: ex.fetch_ohlcv(sym, "8h", since=cursor, limit=limit),
            since,
        )
        if not ohlcv:
            return pd.DataFrame()
        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.set_index("datetime")
        df.index = df.index + pd.Timedelta(hours=8)
        return df[["close"]].rename(columns={"close": "perp_price" if is_perp else "spot_price"})
    except Exception as e:
        logger.warning("Price fetch %s (perp=%s): %s", symbol, is_perp, e)
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════════
# Regime Classifier
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RegimeLabel:
    """Simple BTC regime classification."""
    date: pd.Timestamp
    regime: str       # "bull", "bear", "range"
    btc_price: float
    ma_200d: float


def classify_regimes(btc_prices: pd.DataFrame) -> pd.DataFrame:
    """Classify each day as bull/bear/range based on BTC vs its 200-day MA.

    Bull:  price > MA200 and rising over 30 days
    Bear:  price < MA200 and falling over 30 days
    Range: everything else
    """
    df = btc_prices.copy()
    if "spot_price" in df.columns:
        df["price"] = df["spot_price"]
    elif "close" in df.columns:
        df["price"] = df["close"]
    else:
        df["price"] = df.iloc[:, 0]
    
    df["ma_200"] = df["price"].rolling(200, min_periods=50).mean()
    df["return_30d"] = df["price"].pct_change(30)
    
    conditions = [
        (df["price"] > df["ma_200"]) & (df["return_30d"] > 0.05),
        (df["price"] < df["ma_200"]) & (df["return_30d"] < -0.05),
    ]
    choices = ["bull", "bear"]
    df["regime"] = np.select(conditions, choices, default="range")
    
    return df[["price", "ma_200", "regime"]]


# ═══════════════════════════════════════════════════════════════════════════════
# Walk-Forward Engine
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WFWindow:
    """Result of one walk-forward window."""
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    regime: str                     # majority regime over the test window
    n_assets_available: int         # assets with at least 6 months of history
    n_assets_traded: int            # assets that opened ≥1 trade
    total_trading_pnl: float
    total_capital: float
    trading_return_pct: float
    portfolio_sharpe: float         # Sharpe of the portfolio equity curve
    max_dd_pct: float
    capital_utilisation_pct: float
    staking_pnl: float


def generate_wf_windows(
    start_date: str = "2023-01-01",
    end_date: str = "2026-07-25",
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3,
) -> list[dict]:
    """Generate the walk-forward windows (causal, no look-ahead)."""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    windows = []
    
    current = start + pd.DateOffset(months=train_months)
    while current + pd.DateOffset(months=test_months) <= end:
        train_start = current - pd.DateOffset(months=train_months)
        train_end = current
        test_start = current
        test_end = current + pd.DateOffset(months=test_months)
        
        windows.append({
            "train_start": train_start.strftime("%Y-%m-%d"),
            "train_end": train_end.strftime("%Y-%m-%d"),
            "test_start": test_start.strftime("%Y-%m-%d"),
            "test_end": test_end.strftime("%Y-%m-%d"),
        })
        current += pd.DateOffset(months=step_months)
    
    return windows


def is_asset_available_at(symbol: str, date: pd.Timestamp, 
                          funding_data: dict[str, pd.DataFrame],
                          min_history_months: int = 6) -> bool:
    """Check whether an asset is available at date t (>=6 months of history before t)."""
    df = funding_data.get(symbol)
    if df is None or df.empty:
        return False
    min_required = date - pd.DateOffset(months=min_history_months)
    return df.index.min() <= min_required


def run_walkforward(
    symbols: list[str] | None = None,
    days: int = 1300,
    capital: float = 2_000,
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3,
    quick: bool = False,
) -> dict:
    """Full walk-forward backtest.
    
    Returns:
        dict with windows (list of WFWindow), portfolio_summary, regime_summary.
    """
    if symbols is None:
        symbols = ALL_SYMBOLS if ALL_SYMBOLS else SYMBOLS
    
    if quick:
        train_months, test_months, step_months = 3, 1, 1
        logger.info("QUICK MODE: train=%dm test=%dm step=%dm", train_months, test_months, step_months)
    
    # ── 1) Data pipeline (one fetch per asset) ──
    logger.info("=" * 70)
    logger.info("PHASE 1: Data pipeline - %d assets, ~3.5 years", len(symbols))
    logger.info("=" * 70)
    
    funding_data: dict[str, pd.DataFrame] = {}
    price_data: dict[str, dict[str, pd.DataFrame]] = {}  # sym → {spot, perp}
    
    t0 = time.time()
    for sym in symbols:
        df_f = fetch_funding_history_3y(sym, days=days)
        if df_f.empty:
            logger.warning("%s: no funding data, skipping", sym)
            continue
        funding_data[sym] = df_f
        
        # Load spot + perp prices (daily) for basis P&L modeling (DeepSeek audit, 25/07/2026)
        df_spot = fetch_prices_3y(sym, days=days, is_perp=False)
        df_perp = fetch_prices_3y(sym, days=days, is_perp=True)
        if not df_spot.empty and not df_perp.empty:
            # Handle multiplier contracts
            base = sym.split("/")[0]
            MULT = {"PEPE": 1000, "SHIB": 1000, "BONK": 1000, "FLOKI": 1000, "LUNC": 1000}
            contract_mult = MULT.get(base, 1)
            if contract_mult > 1 and "perp_price" in df_perp.columns:
                df_perp["perp_price"] = df_perp["perp_price"] / contract_mult
            price_data[sym] = {"spot": df_spot, "perp": df_perp}
        else:
            # Without real prices the backtest fell back to $1000: 100% fabricated P&L.
            logger.error("%s: spot/perp prices unavailable - asset excluded from the backtest", sym)
            funding_data.pop(sym, None)
            continue
        
        logger.info("  %s: %d funding periods (%s → %s)",
                    sym, len(df_f),
                    df_f.index.min().strftime("%Y-%m-%d"),
                    df_f.index.max().strftime("%Y-%m-%d"))
    
    logger.info("Data loaded: %d/%d assets in %.0fs", len(funding_data), len(symbols), time.time() - t0)
    
    # ── 2) Regime classification (BTC only) ──
    logger.info("=" * 70)
    logger.info("PHASE 2: Regime classification (BTC)")
    logger.info("=" * 70)
    
    btc_spot = fetch_prices_3y("BTC/USDT", days=days, is_perp=False)
    if not btc_spot.empty:
        regimes = classify_regimes(btc_spot)
        logger.info("Regimes: %s", regimes["regime"].value_counts().to_dict())
    else:
        logger.warning("No BTC price data — regime classification skipped")
        regimes = pd.DataFrame()
    
    # ── 3) Walk-forward loop (efficient: slice pre-loaded data) ──
    windows_config = generate_wf_windows(
        train_months=train_months,
        test_months=test_months,
        step_months=step_months,
    )
    
    logger.info("=" * 70)
    logger.info("PHASE 3: Walk-forward - %d windows", len(windows_config))
    logger.info("=" * 70)
    
    from v7.nodes.funding_carry_node import FundingCarryNode
    
    wf_results: list[WFWindow] = []
    
    for wi, wc in enumerate(windows_config):
        test_start = pd.Timestamp(wc["test_start"])
        test_end = pd.Timestamp(wc["test_end"])
        
        # -- Causal universe: assets available at test_start --
        available = [s for s in funding_data 
                    if is_asset_available_at(s, test_start, funding_data)]
        
        if not available:
            logger.warning("Window %d: no assets available at %s", wi + 1, wc["test_start"])
            continue
        
        # ── Regime ──
        regime = "unknown"
        if not regimes.empty:
            try:
                window_regimes = regimes.loc[wc["test_start"]:wc["test_end"]]
                if not window_regimes.empty:
                    regime = window_regimes["regime"].mode().iloc[0]
            except Exception:
                pass
        
        # ── Run backtest per asset using pre-loaded funding data ──
        window_trading_pnl = 0.0
        window_staking = 0.0
        window_assets_traded = 0
        # Portfolio equity per timestamp, accumulated across every asset in the
        # window. Per-asset, it would only ever describe the last asset seen.
        equity_by_ts: dict = {}
        
        for sym in available:
            df_f = funding_data[sym]
            # Slice to test window
            test_data = df_f.loc[wc["test_start"]:wc["test_end"]]
            if test_data.empty or len(test_data) < 10:
                continue
            
            # Run FundingCarryNode directly on sliced data (no re-fetch!)
            # Params read from carry_assets.yaml so the run mirrors the live strategy.
            try:
                from v7.core.asset_config import get_asset_params
                _cfg = get_asset_params(sym)
            except Exception:
                _cfg = {}
            node = FundingCarryNode(
                node_id=f"wf_{sym.split('/')[0].lower()}",
                symbol=sym,
                capital=capital,
                fraction=float(_cfg.get("fraction", 0.50)),
                min_funding=float(_cfg.get("min_funding", 0.0002)),
                max_funding=float(_cfg.get("max_funding", 0.003)),
                exit_after_hours=int(_cfg.get("exit_after_hours", 72)),
                max_hold_days=int(_cfg.get("max_hold_days", 30)),
                stop_loss_pct=float(_cfg.get("stop_loss_pct", -0.05)),
                params={"_backtest": True},
            )
            
            # Per-asset accounting. The node owns the numbers - it charges all four
            # legs and realises the basis on close - so this loop only accumulates.
            # It used to charge 24bps per side itself AND saturate the funding with
            # max(), which made the report disagree with the node it is meant to be
            # measuring.
            asset_realized = 0.0
            asset_traded = False
            asset_open_mtm = 0.0
            
            for ts, row in test_data.iterrows():
                fr = float(row["funding_rate"])
                # Real spot/perp prices (DeepSeek audit, 25/07/2026: basis P&L must be modeled)
                # No default price: without a real price we do not simulate (no fabricated P&L).
                spot_price = None
                perp_price = None
                sym_prices = price_data.get(sym, {})
                if sym_prices:
                    df_s = sym_prices.get("spot")
                    df_p = sym_prices.get("perp")
                    if df_s is not None and not df_s.empty:
                        # Get nearest price at or before funding timestamp
                        spot_slice = df_s[df_s.index <= ts]
                        if not spot_slice.empty:
                            spot_price = float(spot_slice.iloc[-1]["spot_price"])
                    if df_p is not None and not df_p.empty:
                        perp_slice = df_p[df_p.index <= ts]
                        if not perp_slice.empty:
                            col = "perp_price" if "perp_price" in df_p.columns else df_p.columns[0]
                            perp_price = float(perp_slice.iloc[-1][col])
                # No spot fallback for the perp: substituting it invents basis = 0,
                # which is the state the entry filter looks for. The live path and
                # the single-asset backtest both refuse; this one did not.
                if spot_price is None or perp_price is None or perp_price <= 0:
                    continue
                
                result = node.run({
                    "symbol": sym,
                    "spot_price": spot_price,
                    "funding_rate": fr,
                    "perp_price": perp_price,
                    # Simulated bar timestamp so the node's time-based exits are
                    # evaluated on simulated days, not on real elapsed seconds.
                    "now": ts,
                })
                
                signal = result.get("signal", "flat")
                size_usd = result.get("size_usd", 0)

                if signal == "open_carry" and size_usd > 0:
                    asset_traded = True
                if signal == "close_carry":
                    asset_realized += float(result.get("realized_pnl_usd", 0) or 0)

                # Mark the open position to market: its funding so far, its fees so
                # far and its basis at the current price.
                asset_open_mtm = 0.0
                if result.get("position_open"):
                    unrealized_usd = (
                        (result.get("unrealized_pnl_pct", 0) or 0) / 100.0
                        * node.state.entry_capital
                    )
                    asset_open_mtm = (node.state.total_funding_received
                                      - node.state.fees_paid + unrealized_usd)
                equity_by_ts[ts] = equity_by_ts.get(ts, 0.0) + asset_realized + asset_open_mtm
            
            if asset_traded:
                window_assets_traded += 1
                window_trading_pnl += asset_realized + asset_open_mtm
            window_staking += node.state.staking_earned
        
        total_capital = len(available) * capital

        # ── Window equity curve → real Sharpe and drawdown ──
        # These were hardcoded to 0.0, so every walk-forward report printed a
        # Sharpe of zero and a drawdown of zero for every window.
        portfolio_sharpe = 0.0
        window_max_dd_pct = 0.0
        nav_series = sorted(equity_by_ts.items())
        if len(nav_series) > 10 and total_capital > 0:
            navs = np.array([v for _, v in nav_series], dtype=float)
            # Returns on the allocated book: the P&L moves over a fixed capital base,
            # so this stays well behaved when the running P&L crosses zero.
            period_returns = np.diff(navs) / total_capital
            if period_returns.std() > 0:
                # one observation per funding period, three per day
                portfolio_sharpe = float(
                    period_returns.mean() / period_returns.std() * np.sqrt(365 * 3)
                )
            curve = np.cumsum(period_returns)
            peak = np.maximum.accumulate(curve)
            window_max_dd_pct = float(((curve - peak) * 100).min())
        wf_result = WFWindow(
            train_start=wc["train_start"],
            train_end=wc["train_end"],
            test_start=wc["test_start"],
            test_end=wc["test_end"],
            regime=regime,
            n_assets_available=len(available),
            n_assets_traded=window_assets_traded,
            total_trading_pnl=round(window_trading_pnl, 2),
            total_capital=total_capital,
            trading_return_pct=round(window_trading_pnl / total_capital * 100, 4) if total_capital > 0 else 0,
            portfolio_sharpe=round(portfolio_sharpe, 3),
            max_dd_pct=round(window_max_dd_pct, 3),
            capital_utilisation_pct=round(window_assets_traded / len(available) * 100, 1) if available else 0,
            staking_pnl=round(window_staking, 2),
        )
        wf_results.append(wf_result)
        
        logger.info("  Window %2d [%s → %s] %5s: %2d/%2d traded, PnL=$%7.2f (%+.3f%%)",
                    wi + 1, wc["test_start"], wc["test_end"], regime.upper(),
                    window_assets_traded, len(available),
                    window_trading_pnl,
                    window_trading_pnl / total_capital * 100 if total_capital > 0 else 0)
    
    # ── 4) Portfolio summary ──
    oos_windows = [w for w in wf_results if w.n_assets_traded > 0]
    
    if oos_windows:
        oos_returns = [w.trading_return_pct for w in oos_windows]
        positive_pct = sum(1 for r in oos_returns if r > 0) / len(oos_returns) * 100
        median_return = np.median(oos_returns)
        worst_return = min(oos_returns)
        best_return = max(oos_returns)
        
        # By regime
        regime_groups = {}
        for w in oos_windows:
            r = w.regime
            if r not in regime_groups:
                regime_groups[r] = []
            regime_groups[r].append(w.trading_return_pct)
    else:
        positive_pct = 0
        median_return = 0
        worst_return = 0
        best_return = 0
        regime_groups = {}
    
    total_trading = sum(w.total_trading_pnl for w in wf_results)
    total_staking = sum(w.staking_pnl for w in wf_results)
    total_cap = sum(w.total_capital for w in wf_results)
    
    return {
        "windows": wf_results,
        "portfolio_summary": {
            "n_windows": len(wf_results),
            "n_oos_windows": len(oos_windows),
            "oos_positive_pct": round(positive_pct, 1),
            "oos_median_return_pct": round(median_return, 4),
            "oos_worst_return_pct": round(worst_return, 4),
            "oos_best_return_pct": round(best_return, 4),
            "total_trading_pnl": round(total_trading, 2),
            "total_staking_pnl": round(total_staking, 2),
            "total_capital": total_cap,
        },
        "regime_summary": {
            r: {
                "n_windows": len(vals),
                "median_return_pct": round(np.median(vals), 4),
                "mean_return_pct": round(np.mean(vals), 4),
                "worst_return_pct": round(min(vals), 4),
                "best_return_pct": round(max(vals), 4),
            }
            for r, vals in regime_groups.items()
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="V7 Walk-Forward Backtest (GPT audit Priority #2)")
    parser.add_argument("--symbols", type=str, default="ALL",
                        help="ALL, ACTIVE, BTC, BTC/USDT, or BTC,ETH (comma-separated)")
    parser.add_argument("--days", type=int, default=1300, help="Days of data (default 1300 = ~3.5 years)")
    parser.add_argument("--capital", type=float, default=2000)
    parser.add_argument("--train", type=int, default=12, help="Training months")
    parser.add_argument("--test", type=int, default=3, help="OOS test length in months")
    parser.add_argument("--step", type=int, default=3, help="Step in months")
    parser.add_argument("--quick", action="store_true", help="Fast mode (train=3, test=1, step=1)")
    args = parser.parse_args()
    
    if args.symbols == "ALL":
        symbols = ALL_SYMBOLS
    elif args.symbols == "ACTIVE":
        symbols = SYMBOLS
    else:
        symbols = [normalize_symbol(s) for s in args.symbols.split(",") if s.strip()]
    
    print("=" * 80)
    print("ATLAS V7 — Walk-Forward Backtest (GPT audit priority #2)")
    print(f"Assets: {len(symbols)} | Train: {args.train}m | Test: {args.test}m | Step: {args.step}m")
    print(f"Capital: ${args.capital}/asset | Fees: 48bps RT | Hurdle: 5% (frozen)")
    print("=" * 80)
    
    results = run_walkforward(
        symbols=symbols,
        days=args.days,
        capital=args.capital,
        train_months=args.train,
        test_months=args.test,
        step_months=args.step,
        quick=args.quick,
    )
    
    # -- Display the results --
    print("\n" + "=" * 80)
    print("OOS RESULTS (out-of-sample)")
    print("=" * 80)
    
    ps = results["portfolio_summary"]
    print(f"Windows: {ps['n_windows']} total, {ps['n_oos_windows']} with trades")
    print(f"OOS median return: {ps['oos_median_return_pct']:+.3f}%")
    print(f"OOS worst return:  {ps['oos_worst_return_pct']:+.3f}%")
    print(f"OOS best return:   {ps['oos_best_return_pct']:+.3f}%")
    print(f"OOS % positive:    {ps['oos_positive_pct']:.0f}%  (over the {ps['n_oos_windows']} windows that actually traded)")
    print(f"Total Trading P&L: ${ps['total_trading_pnl']:,.2f}")
    print(f"Total Staking P&L: ${ps['total_staking_pnl']:,.2f}")
    
    if results["regime_summary"]:
        print("\n-- By regime --")
        for regime, stats in sorted(results["regime_summary"].items()):
            print(f"  {regime.upper():5s}: {stats['n_windows']} windows, "
                  f"median={stats['median_return_pct']:+.3f}%, "
                  f"worst={stats['worst_return_pct']:+.3f}%, "
                  f"best={stats['best_return_pct']:+.3f}%")
    
    print("\n-- Per-window detail --")
    print(f"{'Train':<22} {'Test':<22} {'Regime':<6} {'Assets':<8} {'Traded':<7} {'Trading P&L':<12} {'Return%':<10}")
    print("-" * 90)
    for w in results["windows"]:
        print(f"{w.train_start}→{w.train_end}  {w.test_start}→{w.test_end}  "
              f"{w.regime:<6} {w.n_assets_available:<8} {w.n_assets_traded:<7} "
              f"${w.total_trading_pnl:>8,.2f}   {w.trading_return_pct:>+.3f}%")
    
    print("\n" + "=" * 80)
    # A window with no trade at all says NOTHING about the edge: it must neither
    # inflate '% positive' nor trigger a green light. The verdict now compares
    # the annualised median against the strategy hurdle (5%/yr) and
    # checks the actual coverage (traded windows / total windows).
    _n_traded = ps['n_oos_windows']
    _n_total = ps['n_windows']
    _coverage = (_n_traded / _n_total * 100) if _n_total else 0.0
    _med_quarter = ps['oos_median_return_pct']
    _med_annual = _med_quarter * 4
    _hurdle = 5.0

    print(f"Traded windows  : {_n_traded}/{_n_total} ({_coverage:.0f}% coverage)")
    print(f"OOS median      : {_med_quarter:+.3f}%/quarter  ~ {_med_annual:+.2f}%/yr")
    print(f"Strategy hurdle : {_hurdle:+.2f}%/yr")
    if _med_annual < _hurdle:
        print(f"  ⚠️  The OOS median is BELOW the hurdle: the strategy does not cover")
        print(f"      its cost of capital on this sample.")
    if _coverage < 50:
        print(f"  ⚠️  Fewer than half of the windows traded: weak sample.")
    print("-" * 80)

    if _n_traded < 5:
        verdict = f"NO-GO - insufficient sample ({_n_traded} traded window(s))"
    elif _coverage < 50:
        verdict = f"Paper trading only — insufficient OOS coverage ({_coverage:.0f}%)"
    elif _med_annual < _hurdle:
        verdict = (f"Paper trading only — OOS return {_med_annual:+.2f}%/yr "
                   f"below the hurdle ({_hurdle:.0f}%/yr)")
    else:
        verdict = "GO for real capital"
    print(f"Verdict: {verdict}")
    print("=" * 80)


if __name__ == "__main__":
    main()
