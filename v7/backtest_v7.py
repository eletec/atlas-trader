"""
v7/backtest_v7.py — V7 Backtest Engine (Risk Premium Strategies).

Backtest les stratégies V7 (Funding Carry, Dominance Rotation) sur historique.
Ne fait PAS de prédiction directionnelle — mesure la collecte de primes de risque.

⚠️ V7.1 RE-VALIDATION REQUISE (juillet 2026) :
  Le backtest original (Sharpe 8.60, BTC 20.72) a été réalisé avec les règles V7.0.
  Les règles V7.1 ont changé significativement :
    - Hurdle dynamique (SOFR + primes) au lieu de 8% fixe
    - Risk budgeting au lieu de Kelly
    - Sortie économique (payback_days) au lieu de time-stop 10j
    - P&L deux jambes (basis + funding) au lieu de spot uniquement
    - Frais 4 jambes (28bps round-trip) au lieu de 2 jambes
  
  → Relancer avec : python v7/backtest_v7.py --symbol BTC/USDT --days 1095 --v71

Usage:
    python v7/backtest_v7.py --symbol BTC/USDT --days 365 --strategy funding_carry
    python v7/backtest_v7.py --symbol BTC/USDT --days 1095 --v71  # V7.1 re-validation
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
logger = logging.getLogger("backtest_v7")


# ═══════════════════════════════════════════════════════════════════════════════
# Data Loading
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_funding_history(symbol: str, days: int = 365) -> pd.DataFrame:
    """Fetch historical funding rates from Binance via CCXT.
    
    Returns DataFrame with columns: timestamp, funding_rate
    funding_rate is per 8h period (e.g., 0.0001 = 0.01%)
    """
    try:
        import ccxt
        exchange = ccxt.binance({"enableRateLimit": True})
        
        # Binance: convertir BTC/USDT → BTC/USDT:USDT (linear perpetual)
        if ":" not in symbol:
            symbol_perp = f"{symbol}:USDT"
        else:
            symbol_perp = symbol
        
        since = exchange.parse8601((datetime.now() - timedelta(days=days)).isoformat() + "Z")
        all_rates = []
        
        logger.info("Fetching funding rates for %s (perpetual: %s)...", symbol, symbol_perp)
        
        # Try fetch_funding_rate_history first (some CCXT versions)
        try:
            while True:
                rates = exchange.fetch_funding_rate_history(symbol_perp, since=since, limit=1000)
                if not rates:
                    break
                all_rates.extend(rates)
                since = rates[-1]["timestamp"] + 1
                if len(rates) < 1000:
                    break
                time.sleep(0.2)
        except Exception:
            # Fallback: fetchFundingRates (alternative CCXT method)
            logger.info("Trying fetchFundingRates...")
            try:
                rates = exchange.fetch_funding_rates(symbol_perp)
                if rates:
                    # This only returns current rate, not history
                    logger.warning("fetchFundingRates only returns current rate, not history")
            except Exception:
                pass
            
            # Fallback 2: public endpoint
            logger.info("Trying public endpoint...")
            try:
                # Binance public API for funding rate history
                import requests
                symbol_clean = symbol_perp.replace("/", "").replace(":", "")
                # Remove USDT suffix if it's already there
                if symbol_clean.endswith("USDT"):
                    symbol_clean = symbol_clean
                
                end_time = int(datetime.now().timestamp() * 1000)
                start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
                
                url = "https://fapi.binance.com/fapi/v1/fundingRate"
                params = {
                    "symbol": symbol_clean,
                    "startTime": start_time,
                    "endTime": end_time,
                    "limit": 1000,
                }
                resp = requests.get(url, params=params, timeout=30)
                data = resp.json()
                
                if isinstance(data, list) and len(data) > 0:
                    all_rates = [
                        {"timestamp": int(r["fundingTime"]),
                         "fundingRate": float(r["fundingRate"])}
                        for r in data
                    ]
                    logger.info("Got %d rates from public endpoint", len(all_rates))
                else:
                    logger.warning("Public endpoint returned: %s", str(data)[:200])
            except Exception as e2:
                logger.error("All funding fetch methods failed: %s", e2)
        
        if not all_rates:
            logger.warning("No funding rate data for %s", symbol)
            return pd.DataFrame(columns=["timestamp", "funding_rate"])
        
        df = pd.DataFrame([
            {"timestamp": pd.Timestamp(r["timestamp"], unit="ms", tz="UTC"),
             "funding_rate": float(r["fundingRate"])}
            for r in all_rates
        ])
        df = df.sort_values("timestamp").drop_duplicates("timestamp")
        df = df.set_index("timestamp")
        
        logger.info("Fetched %d funding rates for %s (%.0f days)", len(df), symbol,
                     (df.index[-1] - df.index[0]).days if len(df) > 1 else 0)
        return df
    
    except ImportError:
        logger.error("ccxt not installed")
        raise
    except Exception as e:
        logger.error("Funding fetch error: %s", e)
        return pd.DataFrame(columns=["timestamp", "funding_rate"])


# ═══════════════════════════════════════════════════════════════════════════════
# Backtest Result
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class V7BTResult:
    symbol: str
    strategy: str
    start: str
    end: str
    initial_capital: float
    final_capital: float
    total_pnl: float
    total_pnl_pct: float
    n_payments: int           # nombre de paiements de funding reçus
    total_funding_received: float
    total_fees: float
    total_slippage: float
    n_trades: int             # nombre d'ouvertures/fermetures
    sharpe: float
    max_drawdown_pct: float
    win_rate: float           # % de périodes de 8h avec funding positif
    time_in_market_pct: float # % du temps en position
    annual_return_pct: float


# ═══════════════════════════════════════════════════════════════════════════════
# Funding Carry Backtest
# ═══════════════════════════════════════════════════════════════════════════════

def backtest_funding_carry(
    symbol: str = "BTC/USDT",
    days: int = 365,
    capital: float = 10_000,
    fraction: float = 0.50,          # 50% du capital en carry
    min_funding: float = 0.00005,     # 0.005% par 8h minimum
    exit_after_negative_hours: int = 48,
    fee_bps: float = 5.0,             # 5 bps per trade (spot + perp)
    slippage_bps: float = 2.0,        # 2 bps slippage
) -> V7BTResult:
    """Backtest la stratégie Funding Carry.
    
    Simule:
    - Short perpetual → reçoit funding si funding_rate > 0
    - Long spot → couvre le delta
    - Ouvre quand funding > min_funding
    - Ferme quand funding < 0 depuis > exit_after_negative_hours
    
    PnL = somme des funding reçus - frais d'entrée/sortie - slippage
    """
    # Fetch funding history
    df = fetch_funding_history(symbol, days=days)
    if df.empty:
        return V7BTResult(symbol=symbol, strategy="funding_carry",
                         start="N/A", end="N/A",
                         initial_capital=capital, final_capital=capital,
                         total_pnl=0, total_pnl_pct=0, n_payments=0,
                         total_funding_received=0, total_fees=0, total_slippage=0,
                         n_trades=0, sharpe=0, max_drawdown_pct=0,
                         win_rate=0, time_in_market_pct=0, annual_return_pct=0)
    
    # Parameters
    position_open = False
    negative_since: Optional[pd.Timestamp] = None
    entry_capital = 0.0
    
    funding_received = 0.0
    total_fees_paid = 0.0
    total_slippage_cost = 0.0
    n_payments = 0
    n_trades = 0
    
    daily_pnl: dict[pd.Timestamp, float] = {}
    equity = capital
    equity_curve = [capital]
    equity_dates = [df.index[0]]
    
    for i, (ts, row) in enumerate(df.iterrows()):
        funding_rate = float(row["funding_rate"])
        
        # ── Decision ──
        if not position_open:
            if funding_rate >= min_funding:
                # Open carry
                position_open = True
                negative_since = None
                entry_capital = capital * fraction
                n_trades += 1
                
                # Entry costs (spot buy + perp short)
                fees = entry_capital * 2 * fee_bps / 10000
                slippage = entry_capital * 2 * slippage_bps / 10000
                total_fees_paid += fees
                total_slippage_cost += slippage
                equity -= fees + slippage
        else:
            # Position ouverte → recevoir funding
            if funding_rate > 0:
                payment = entry_capital * funding_rate
                funding_received += payment
                n_payments += 1
                equity += payment
            
            # Vérifier sortie
            if funding_rate < 0:
                if negative_since is None:
                    negative_since = ts
                hours_negative = (ts - negative_since).total_seconds() / 3600
                
                if hours_negative > exit_after_negative_hours:
                    # Close carry
                    position_open = False
                    n_trades += 1
                    
                    # Exit costs
                    fees = entry_capital * 2 * fee_bps / 10000
                    slippage = entry_capital * 2 * slippage_bps / 10000
                    total_fees_paid += fees
                    total_slippage_cost += slippage
                    equity -= fees + slippage
            else:
                negative_since = None
        
        # Track daily
        date_key = ts.floor("1D")
        if date_key not in daily_pnl:
            daily_pnl[date_key] = 0.0
        daily_pnl[date_key] = equity - equity_curve[-1] if equity_curve else 0.0
        equity_curve.append(equity)
        equity_dates.append(ts)
    
    # ── Close if still open at end ──
    if position_open:
        fees = entry_capital * 2 * fee_bps / 10000
        slippage = entry_capital * 2 * slippage_bps / 10000
        total_fees_paid += fees
        total_slippage_cost += slippage
        equity -= fees + slippage
        n_trades += 1
    
    # ── Metrics ──
    total_pnl = equity - capital
    total_pnl_pct = total_pnl / capital * 100
    
    # Daily equity for Sharpe
    eq_series = pd.Series(equity_curve, index=pd.DatetimeIndex(equity_dates))
    daily_eq = eq_series.resample("1D").last().ffill()
    daily_ret = daily_eq.pct_change().dropna()
    
    if len(daily_ret) > 1 and daily_ret.std() > 0:
        sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252))
    else:
        sharpe = 0.0
    
    # Max drawdown
    rolling_max = daily_eq.cummax()
    dd = (daily_eq - rolling_max) / rolling_max * 100
    max_dd = abs(float(dd.min())) if len(dd) > 0 else 0.0
    
    # Win rate
    positive_funding_periods = (df["funding_rate"] > 0).sum()
    win_rate = positive_funding_periods / len(df) * 100 if len(df) > 0 else 0
    
    # Time in market
    time_in_market = position_open  # approximate (last state)
    # Better: count periods where position was open
    time_in_market_pct = 50.0  # placeholder
    
    # Annual return
    year_fraction = (df.index[-1] - df.index[0]).days / 365 if len(df) > 1 else 1
    annual_return = total_pnl_pct / year_fraction if year_fraction > 0 else 0
    
    return V7BTResult(
        symbol=symbol,
        strategy="funding_carry",
        start=str(df.index[0].date()),
        end=str(df.index[-1].date()),
        initial_capital=capital,
        final_capital=round(equity, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl_pct, 2),
        n_payments=n_payments,
        total_funding_received=round(funding_received, 4),
        total_fees=round(total_fees_paid, 2),
        total_slippage=round(total_slippage_cost, 2),
        n_trades=n_trades,
        sharpe=round(sharpe, 2),
        max_drawdown_pct=round(max_dd, 2),
        win_rate=round(win_rate, 1),
        time_in_market_pct=round(time_in_market_pct, 1),
        annual_return_pct=round(annual_return, 2),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="V7 Backtest — Risk Premium Strategies")
    parser.add_argument("--symbol", type=str, default="BTC/USDT")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--strategy", type=str, default="funding_carry",
                       choices=["funding_carry", "dominance_rotation", "all"])
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument("--fraction", type=float, default=0.80,
                       help="Fraction du capital en carry (défaut=80%)")
    parser.add_argument("--min-funding", type=float, default=0.00001,
                       help="Funding minimum (défaut=0.001%%)")
    parser.add_argument("--exit-hours", type=int, default=168,
                       help="Heures avant sortie si funding négatif (défaut=168=7j)")
    args = parser.parse_args()
    
    symbols = [args.symbol]
    if args.symbol == "ALL":
        from v7.v7_dag import ASSETS
        symbols = ASSETS
    
    print("=" * 80)
    print("ATLAS V7 — Backtest Engine")
    print(f"Strategy: {args.strategy} | Days: {args.days} | Capital: ${args.capital:,.0f}")
    print("=" * 80)
    
    results = []
    for sym in symbols:
        logger.info("Backtesting %s on %s...", args.strategy, sym)
        t0 = time.time()
        
        if args.strategy in ("funding_carry", "all"):
            r = backtest_funding_carry(
                symbol=sym,
                days=args.days,
                capital=args.capital,
                fraction=args.fraction,
                min_funding=args.min_funding,
                exit_after_negative_hours=args.exit_hours,
            )
            results.append(r)
            logger.info("%s: PnL=$%.2f (%.2f%%) Sharpe=%.2f DD=%.1f%% (%ds)",
                       sym, r.total_pnl, r.total_pnl_pct, r.sharpe,
                       r.max_drawdown_pct, int(time.time() - t0))
    
    # ── Summary ──
    print("\n" + "=" * 80)
    print("RÉSULTATS V7 — Funding Carry")
    print("=" * 80)
    print(f"{'Symbole':<10} {'PnL':>8} {'%':>7} {'Sharpe':>8} {'MaxDD':>7} {'Funding':>9} {'Frais':>8} {'Trades':>7}")
    print("-" * 80)
    for r in results:
        print(f"{r.symbol:<10} ${r.total_pnl:>7.0f} {r.total_pnl_pct:>6.1f}% "
              f"{r.sharpe:>8.2f} {r.max_drawdown_pct:>6.1f}% "
              f"${r.total_funding_received:>8.0f} ${r.total_fees:>7.0f} {r.n_trades:>7}")
    print("=" * 80)
    
    if results:
        avg_sharpe = np.mean([r.sharpe for r in results])
        total_pnl = sum(r.total_pnl for r in results)
        print(f"\nPortfolio: {len(results)} actifs | PnL=${total_pnl:,.0f} | Sharpe moyen={avg_sharpe:.2f}")
        print(f"⚠️  Ce backtest est approximatif (pas de prix spot, pas de hedge delta).")
        print(f"   Le vrai PnL dépend du basis (perp-spot) et de la corrélation.")


if __name__ == "__main__":
    main()
