"""
v7/cross_exchange_scanner.py — Scanner de carry cross-exchange (Binance vs Bybit vs OKX).

DeepSeek/GPT audit (25/07/2026) : meilleure piste pour augmenter le rendement.
Compare les funding rates entre exchanges et identifie les opportunités d'arbitrage.

Principe :
    - Short perp sur l'exchange où le funding est le PLUS ÉLEVÉ (on reçoit plus)
    - Long spot sur l'exchange où le spot est le MOINS CHER
    - Ou : short perp exchange A + long perp exchange B (plus simple, pas de spot)

Usage:
    python v7/cross_exchange_scanner.py              # scan one-shot
    python v7/cross_exchange_scanner.py --min-spread 0.0001  # spread min 1bps
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cross_exchange")


@dataclass
class CrossExchangeOpportunity:
    """Une opportunité d'arbitrage de funding entre deux exchanges."""
    symbol: str                    # ex: "BTC/USDT"
    exchange_long: str             # exchange where we short (to receive the funding)
    exchange_short: str            # exchange where we go long (to pay the funding)
    funding_long: float            # funding rate on exchange_long
    funding_short: float           # funding rate on exchange_short
    spread_bps: float              # spread in bps (100 = 1%)
    annual_spread_pct: float       # annualised spread
    spot_long: float               # prix spot exchange_long
    spot_short: float              # prix spot exchange_short
    viable: bool                   # spread > frais round-trip ?


def get_exchange(name: str):
    """Retourne une instance CCXT configurée."""
    import ccxt
    exchanges = {
        "binance": ccxt.binance,
        "bybit": ccxt.bybit,
        "okx": ccxt.okx,
    }
    if name not in exchanges:
        raise ValueError(f"Unknown exchange: {name}")
    return exchanges[name]({"enableRateLimit": True})


def fetch_funding_rates(exchange_name: str, symbols: list[str]) -> dict[str, float]:
    """Récupère les funding rates pour une liste de symboles sur un exchange."""
    try:
        ex = get_exchange(exchange_name)
        # Build the exchange-formatted symbols
        if exchange_name == "binance":
            syms = [f"{s.split('/')[0]}/USDT:USDT" for s in symbols]
        elif exchange_name == "bybit":
            syms = [f"{s.split('/')[0]}/USDT:USDT" for s in symbols]
        elif exchange_name == "okx":
            syms = [f"{s.split('/')[0]}/USDT:USDT" for s in symbols]
        else:
            syms = symbols
        
        rates = ex.fetch_funding_rates(syms)
        result = {}
        for sym_orig, sym_ex in zip(symbols, syms):
            if sym_ex in rates:
                result[sym_orig] = float(rates[sym_ex].get("fundingRate", 0))
        return result
    except Exception as e:
        logger.warning("%s funding fetch failed: %s", exchange_name, e)
        return {}


def fetch_spot_prices(exchange_name: str, symbols: list[str]) -> dict[str, float]:
    """Récupère les prix spot."""
    try:
        ex = get_exchange(exchange_name)
        syms = [f"{s.split('/')[0]}/USDT" for s in symbols]
        tickers = ex.fetch_tickers(syms)
        result = {}
        for sym_orig, sym_ex in zip(symbols, syms):
            if sym_ex in tickers:
                result[sym_orig] = float(tickers[sym_ex].get("last", 0))
        return result
    except Exception as e:
        logger.warning("%s spot fetch failed: %s", exchange_name, e)
        return {}


def scan_cross_exchange(
    symbols: list[str] | None = None,
    exchanges: list[str] | None = None,
    min_spread_bps: float = 0.5,    # spread minimum en bps (0.5 = 0.005%)
    fees_roundtrip_bps: float = 48,  # estimated round-trip fees
) -> list[CrossExchangeOpportunity]:
    """Scanne les opportunités de carry cross-exchange.

    Args:
        symbols: liste de symboles (ex: ["BTC/USDT", "ETH/USDT"]). None = top 20.
        exchanges: liste d'exchanges. None = ["binance", "bybit"].
        min_spread_bps: spread minimum en bps pour considérer une opportunité.
        fees_roundtrip_bps: frais estimés pour un round-trip cross-exchange.
    
    Returns:
        Liste d'opportunités triées par spread décroissant.
    """
    if symbols is None:
        # Top liquid perps
        symbols = [
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
            "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
            "LTC/USDT", "UNI/USDT", "MATIC/USDT", "NEAR/USDT", "SUI/USDT",
            "OP/USDT", "ARB/USDT", "INJ/USDT", "TIA/USDT", "SEI/USDT",
        ]
    
    if exchanges is None:
        exchanges = ["binance", "bybit"]
    
    logger.info("Scanning %d symbols across %s...", len(symbols), ", ".join(exchanges))
    
    # Fetch all funding rates
    all_funding: dict[str, dict[str, float]] = {}
    all_spot: dict[str, dict[str, float]] = {}
    
    for ex_name in exchanges:
        all_funding[ex_name] = fetch_funding_rates(ex_name, symbols)
        all_spot[ex_name] = fetch_spot_prices(ex_name, symbols)
        logger.info("  %s: %d funding rates, %d spot prices",
                   ex_name, len(all_funding[ex_name]), len(all_spot[ex_name]))
    
    # Compare pair by pair
    opportunities = []
    
    for sym in symbols:
        for i, ex_a in enumerate(exchanges):
            for ex_b in exchanges[i+1:]:
                fr_a = all_funding.get(ex_a, {}).get(sym, 0)
                fr_b = all_funding.get(ex_b, {}).get(sym, 0)
                
                if fr_a == 0 and fr_b == 0:
                    continue
                
                # Spread: the funding rate difference
                spread = abs(fr_a - fr_b)
                spread_bps = spread * 10000  # convertir en bps
                
                if spread_bps < min_spread_bps:
                    continue
                
                # Decide which exchange to short (higher funding = we receive more)
                if fr_a >= fr_b:
                    ex_short = ex_a  # short here (receive the high funding)
                    ex_long = ex_b   # go long here (pay the low funding)
                    fr_short = fr_a
                    fr_long = fr_b
                else:
                    ex_short = ex_b
                    ex_long = ex_a
                    fr_short = fr_b
                    fr_long = fr_a
                
                # Annualisation
                periods_per_year = 365 * 3  # 8h
                annual_spread = (fr_short - fr_long) * periods_per_year * 100
                
                # Cross-exchange fees: spot buy + perp short on A, the reverse on B
                # More legs -> higher fees
                viable = spread_bps > fees_roundtrip_bps
                
                spot_short = all_spot.get(ex_short, {}).get(sym, 0)
                spot_long = all_spot.get(ex_long, {}).get(sym, 0)
                
                opportunities.append(CrossExchangeOpportunity(
                    symbol=sym,
                    exchange_long=ex_long,
                    exchange_short=ex_short,
                    funding_long=fr_long,
                    funding_short=fr_short,
                    spread_bps=round(spread_bps, 2),
                    annual_spread_pct=round(annual_spread, 2),
                    spot_long=spot_long,
                    spot_short=spot_short,
                    viable=viable,
                ))
    
    # Sort by descending spread
    opportunities.sort(key=lambda o: o.spread_bps, reverse=True)
    
    return opportunities


def main():
    parser = argparse.ArgumentParser(description="V7 Cross-Exchange Carry Scanner")
    parser.add_argument("--exchanges", type=str, default="binance,bybit",
                       help="Comma-separated exchanges (default: binance,bybit)")
    parser.add_argument("--min-spread", type=float, default=0.5,
                       help="Minimum spread in bps (default: 0.5)")
    parser.add_argument("--top", type=int, default=10,
                       help="Show top N opportunities (default: 10)")
    args = parser.parse_args()
    
    exchanges = [e.strip() for e in args.exchanges.split(",")]
    
    print("=" * 90)
    print("CROSS-EXCHANGE FUNDING CARRY SCANNER")
    print(f"Exchanges: {', '.join(exchanges)} | Min spread: {args.min_spread} bps")
    print("=" * 90)
    
    t0 = time.time()
    opps = scan_cross_exchange(
        exchanges=exchanges,
        min_spread_bps=args.min_spread,
    )
    elapsed = time.time() - t0
    
    if not opps:
        print(f"\nAucune opportunité ≥ {args.min_spread} bps trouvée. ({elapsed:.1f}s)")
        print("Le marché est efficient entre ces exchanges en ce moment.")
        return
    
    viable = [o for o in opps if o.viable]
    print(f"\n{len(opps)} opportunités trouvées ({len(viable)} viables après frais) en {elapsed:.1f}s\n")
    
    print(f"{'Symbol':<12} {'Short on':<10} {'Long on':<10} {'Spread':>8} {'Ann.%':>8} "
          f"{'FR Short':>10} {'FR Long':>10} {'Viable':>7}")
    print("-" * 90)
    
    for o in opps[:args.top]:
        viable_str = "✅" if o.viable else "❌"
        print(f"{o.symbol:<12} {o.exchange_short:<10} {o.exchange_long:<10} "
              f"{o.spread_bps:>6.1f}bps {o.annual_spread_pct:>6.1f}%  "
              f"{o.funding_short*100:>8.4f}% {o.funding_long*100:>8.4f}%  {viable_str:>6}")
    
    if viable:
        print(f"\n✅ {len(viable)} opportunités viables (spread > frais 48bps)")
        print(f"   Spread max: {max(o.spread_bps for o in viable):.1f} bps")
        print(f"   Rendement annualisé max: {max(o.annual_spread_pct for o in viable):.1f}%")
    else:
        print(f"\n❌ Aucune opportunité viable — les spreads ne couvrent pas les frais")
    
    print(f"\n⚠️  Risques à considérer :")
    print(f"   1. Leg risk : une jambe exécutée, l'autre non → hedge d'urgence nécessaire")
    print(f"   2. Capital sur 2 exchanges → fragmentation, coût d'opportunité")
    print(f"   3. Retraits entre exchanges : délais, frais, limites")
    print(f"   4. API rate limits : risque de ne pas pouvoir fermer en urgence")
    print(f"   5. KYC/Compliance : comptes vérifiés sur chaque exchange requis")


if __name__ == "__main__":
    main()
