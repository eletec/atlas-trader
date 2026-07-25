"""
v7/backtest_v7.py — ⚠️ DEPRECATED (juillet 2026).

Ce backtest est un modèle simplifié "funding-only" qui ne modélise PAS :
  - Les prix spot/perp réels
  - Le basis P&L
  - Les 4 jambes de frais correctement

➡️ Utiliser backtest_v7_node.py à la place (backtest avec vrais prix + FundingCarryNode).
   C'est celui qu'utilise le grid search et le scanner.

Conservé pour référence historique uniquement.
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
    fraction: float = 0.50,
    min_funding: float = 0.00005,
    hurdle_annual: float = 0.07,       # V7.2: hurdle dynamique ~7%
    exit_after_negative_hours: int = 72,
    max_hold_days: int = 90,            # V7.2: time-stop long (sortie économique prioritaire)
    fee_bps: float = 7.0,               # V7.2: 7 bps × 4 jambes = 28 bps round-trip
    slippage_bps: float = 2.0,
    stress_loss_pct: float = 0.04,     # V7.2: dépend de l'actif (BTC=4%, alts=12%)
    v72: bool = True,                   # Flag V7.2 rules
) -> V7BTResult:
    """Backtest la stratégie Funding Carry (V7.2 rules).
    
    V7.2 improvements over V7.0:
    - Causal funding (shift 1) — pas de look-ahead
    - 4-leg fees (28bps round-trip)
    - Dynamic hurdle rate
    - Risk budgeting sizing (net_return / stress_loss)
    - Time-stop + funding exit
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
    
    # ── CAUSAL FIX (3 audits): funding connu à t ne doit pas servir pour la décision à t ──
    df["funding_rate"] = df["funding_rate"].shift(1)
    df = df.dropna(subset=["funding_rate"])  # garde le DatetimeIndex (pas de reset_index !)
    if df.empty:
        logger.warning("Funding data empty after causal shift")
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
    entry_time: Optional[pd.Timestamp] = None
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
        
        # Annualisation
        periods_per_year = 365 * 24 / 8  # 1095
        annual_funding = funding_rate * periods_per_year
        
        # ── Decision (V7.2) ──
        if not position_open:
            # V7.2: hurdle dynamique + risk budgeting
            should_open = False
            if funding_rate >= min_funding:
                if annual_funding > hurdle_annual:
                    # Risk budgeting sizing
                    net_return = annual_funding - hurdle_annual
                    score = max(0, net_return) / stress_loss_pct if stress_loss_pct > 0 else 0
                    raw_size = capital * fraction * min(score, 0.25)
                    if raw_size >= 50:  # taille minimum
                        should_open = True
                        entry_capital = raw_size
            
            if should_open:
                position_open = True
                negative_since = None
                entry_time = ts
                n_trades += 1
                
                # Entry + exit costs (4 legs × fee_bps)
                roundtrip_cost = entry_capital * 4 * (fee_bps + slippage_bps) / 10000
                total_fees_paid += entry_capital * 4 * fee_bps / 10000
                total_slippage_cost += entry_capital * 4 * slippage_bps / 10000
                equity -= roundtrip_cost
        else:
            # Position ouverte → recevoir funding
            if funding_rate > 0:
                payment = entry_capital * funding_rate
                funding_received += payment
                n_payments += 1
                equity += payment
            
            # Vérifier sortie
            should_close = False
            
            # Exit 1: funding négatif prolongé
            if funding_rate < 0:
                if negative_since is None:
                    negative_since = ts
                hours_negative = (ts - negative_since).total_seconds() / 3600
                if hours_negative > exit_after_negative_hours:
                    should_close = True
            else:
                negative_since = None
            
            # Exit 2: time-stop (V7.2: long, 90j — sortie économique prioritaire)
            if not should_close and entry_time is not None:
                days_held = (ts - entry_time).total_seconds() / 86400
                if days_held > max_hold_days:
                    should_close = True
            
            if should_close:
                position_open = False
                n_trades += 1
                # Exit costs already provisioned at entry (roundtrip_cost)
            else:
                negative_since = None
        
        # Track daily
        date_key = ts.floor("1D")
        if date_key not in daily_pnl:
            daily_pnl[date_key] = 0.0
        daily_pnl[date_key] = equity - equity_curve[-1] if equity_curve else 0.0
        equity_curve.append(equity)
        equity_dates.append(ts)
    
    # ── Close if still open at end (no extra fees, already provisioned) ──
    if position_open:
        n_trades += 1
        # Roundtrip fees already deducted at entry — no double charge
    
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
    parser.add_argument("--exit-hours", type=int, default=72,
                       help="Heures avant sortie si funding négatif (défaut=72h)")
    parser.add_argument("--v72", action="store_true", default=True,
                       help="Utiliser les règles V7.2 (hurdle dynamique, risk budgeting, 4-leg fees)")
    args = parser.parse_args()
    
    # V7.2: per-asset stress loss
    _stress_map = {"BTC": 0.04, "ETH": 0.04, "SOL": 0.08, "BNB": 0.08,
                   "XRP": 0.12, "ADA": 0.12, "DOGE": 0.12}
    
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
                v72=args.v72,
                stress_loss_pct=_stress_map.get(sym.split("/")[0].upper(), 0.10),
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
