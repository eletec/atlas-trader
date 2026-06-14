"""
v7/backtest_dominance.py — Dominance Rotation Backtest V7.

Teste la stratégie de rotation BTC/ALTs basée sur la dominance Bitcoin.
- BTCD en hausse → allouer vers BTC
- BTCD en baisse → allouer vers ALTs

Données: CoinGecko API gratuite (BTC dominance historique).

Usage:
    python v7/backtest_dominance.py --days 1095
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backtest_dominance")


# ═══════════════════════════════════════════════════════════════════════════════
# Data: BTC Dominance from CoinGecko
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_btc_dominance_history(days: int = 365) -> pd.Series:
    """Fetch BTC dominance historique depuis CoinGecko (gratuit).
    
    Returns: Series indexée par date, valeurs en % (ex: 48.5)
    """
    try:
        import requests
        
        # CoinGecko: /global/dominance?vs_currency=usd&days=max
        # Alternative: utiliser BTC market cap / total market cap
        url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        params = {
            "vs_currency": "usd",
            "days": min(days, 1825),  # 5 ans max
        }
        
        logger.info("Fetching BTC market data from CoinGecko (%d days)...", days)
        resp = requests.get(url, params=params, timeout=60)
        data = resp.json()
        
        if "market_caps" not in data:
            logger.warning("CoinGecko returned no market_caps: %s", str(data)[:200])
            return pd.Series(dtype=float)
        
        # BTC market cap
        btc_mcaps = pd.DataFrame(
            data["market_caps"],
            columns=["timestamp", "market_cap"],
        )
        btc_mcaps["date"] = pd.to_datetime(btc_mcaps["timestamp"], unit="ms")
        btc_mcaps = btc_mcaps.set_index("date")["market_cap"]
        
        # Total market cap (from global data — approximate)
        # CoinGecko doesn't give historical total market cap easily.
        # Fallback: use BTC price and approximate total from BTC.D trend
        # For now, construct BTC.D from BTC dominance global endpoint (last value)
        # and scale by BTC market cap changes
        
        # Fetch current BTC.D
        global_url = "https://api.coingecko.com/api/v3/global"
        global_resp = requests.get(global_url, timeout=30)
        global_data = global_resp.json()
        current_btcd = float(global_data["data"]["market_cap_percentage"]["btc"])
        
        # Approximate: BTC.D(t) ≈ current_btcd * (BTC_mcap(t) / BTC_mcap(now)) * adjustment
        # This is rough but captures the trend direction
        current_btc_mcap = btc_mcaps.iloc[-1]
        btcd_series = btc_mcaps / current_btc_mcap * current_btcd
        
        # Clip to realistic range
        btcd_series = btcd_series.clip(35, 75)
        
        logger.info("Constructed %d BTC.D points (%.1f%% → %.1f%%)",
                    len(btcd_series),
                    btcd_series.iloc[0] if len(btcd_series) > 0 else 0,
                    btcd_series.iloc[-1] if len(btcd_series) > 0 else 0)
        
        return btcd_series
    
    except Exception as e:
        logger.error("BTC.D fetch error: %s", e)
        return pd.Series(dtype=float)


# ═══════════════════════════════════════════════════════════════════════════════
# Backtest
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DominanceBTResult:
    sharpe: float = 0
    total_return_pct: float = 0
    max_dd_pct: float = 0
    n_rotations: int = 0
    btc_return_pct: float = 0
    alts_return_pct: float = 0
    strategy_outperforms_btc: bool = False


def backtest_dominance_rotation(
    days: int = 365,
    capital: float = 10_000,
) -> DominanceBTResult:
    """Backtest la rotation BTC dominance.
    
    Règles:
    - BTCD > SMA50 → 70% BTC, 30% ALTs
    - BTCD < SMA50 → 30% BTC, 70% ALTs
    - BTCD > 70% → 10% BTC, 90% ALTs
    - BTCD < 38% → 90% BTC, 10% ALTs
    
    Simplification: ALTs = ETH (proxy pour le marché altcoin).
    """
    from v7.strategies.dominance_rotation import DominanceRotationEngine
    
    # Fetch BTC dominance
    btcd_series = fetch_btc_dominance_history(days)
    if len(btcd_series) < 50:
        logger.warning("Pas assez de données BTC.D (%d points)", len(btcd_series))
        return DominanceBTResult()
    
    # Simuler les prix BTC et ETH (proxys)
    # En vrai backtest: utiliser les vrais prix OHLCV
    # Pour l'instant: utiliser des retours simulés basés sur BTCD
    # BTCD ↑ → BTC surperforme ALTs, BTCD ↓ → ALTs surperforment BTC
    
    np.random.seed(42)
    n_days = len(btcd_series)
    
    # Simulation simple: quand BTCD monte, BTC fait mieux que ETH
    btcd_changes = btcd_series.pct_change().fillna(0)
    
    # Prix simulés
    btc_returns = np.random.normal(0.001, 0.03, n_days) + btcd_changes.values * 0.5
    eth_returns = np.random.normal(0.001, 0.04, n_days) - btcd_changes.values * 0.5
    
    btc_price = 30000 * np.cumprod(1 + btc_returns)
    eth_price = 2000 * np.cumprod(1 + eth_returns)
    
    # ── Stratégie ──
    engine = DominanceRotationEngine(capital=capital, sma_period=50)
    
    strat_equity = capital
    btc_equity = capital
    eth_equity = capital
    
    equity_curve = [capital]
    btc_curve = [capital]
    eth_curve = [capital]
    
    current_alloc = {"btc": 0.5, "eth": 0.5}
    last_signal = "flat"
    n_rotations = 0
    
    for i in range(50, n_days):  # start after SMA warmup
        btcd = float(btcd_series.iloc[i])
        signal = engine.evaluate(btc_dominance=btcd)
        
        # Detect rotation
        if signal.action != last_signal and signal.action != "flat":
            n_rotations += 1
        last_signal = signal.action
        
        # Appliquer l'allocation
        alloc_btc = signal.allocation_btc
        alloc_eth = signal.allocation_alts
        
        # Daily PnL
        btc_pnl = alloc_btc * strat_equity * btc_returns[i]
        eth_pnl = alloc_eth * strat_equity * eth_returns[i]
        strat_equity += btc_pnl + eth_pnl
        equity_curve.append(strat_equity)
        
        # Benchmarks
        btc_equity *= (1 + btc_returns[i])
        eth_equity *= (1 + eth_returns[i])
        btc_curve.append(btc_equity)
        eth_curve.append(eth_equity)
    
    # ── Metrics ──
    eq_series = pd.Series(equity_curve)
    daily_ret = eq_series.pct_change().dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0
    
    rolling_max = eq_series.cummax()
    dd = (eq_series - rolling_max) / rolling_max * 100
    max_dd = abs(float(dd.min()))
    
    total_return = (strat_equity / capital - 1) * 100
    btc_return = (btc_equity / capital - 1) * 100
    eth_return = (eth_equity / capital - 1) * 100
    
    return DominanceBTResult(
        sharpe=round(sharpe, 2),
        total_return_pct=round(total_return, 1),
        max_dd_pct=round(max_dd, 1),
        n_rotations=n_rotations,
        btc_return_pct=round(btc_return, 1),
        alts_return_pct=round(eth_return, 1),
        strategy_outperforms_btc=total_return > btc_return,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="V7 Dominance Rotation Backtest")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--capital", type=float, default=10_000)
    args = parser.parse_args()
    
    print("=" * 80)
    print("ATLAS V7 — Dominance Rotation Backtest")
    print(f"Days: {args.days} | Capital: ${args.capital:,.0f}")
    print("=" * 80)
    
    r = backtest_dominance_rotation(days=args.days, capital=args.capital)
    
    print(f"\nSharpe: {r.sharpe:.2f}")
    print(f"Return: {r.total_return_pct:.1f}%")
    print(f"Max DD: {r.max_dd_pct:.1f}%")
    print(f"Rotations: {r.n_rotations}")
    print(f"\nBenchmarks:")
    print(f"  BTC buy & hold: {r.btc_return_pct:.1f}%")
    print(f"  ETH buy & hold: {r.alts_return_pct:.1f}%")
    print(f"\n  Strategy > BTC: {'✅' if r.strategy_outperforms_btc else '❌'}")
    print(f"\n⚠️  Simulation avec prix synthétiques — backtest réel nécessite OHLCV BTC+ETH.")


if __name__ == "__main__":
    main()
