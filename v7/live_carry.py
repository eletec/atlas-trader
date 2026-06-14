"""
v7/live_carry.py — Live Funding Carry Runner.

À intégrer dans le scheduler principal (aux côtés du DAG directionnel).
Tourne toutes les 8h (cycle de funding Binance) pour tous les actifs.

Usage standalone:
    python v7/live_carry.py

Usage intégré (dans workflow.py ou main.py):
    from v7.live_carry import FundingCarryScheduler
    scheduler = FundingCarryScheduler()
    scheduler.run_cycle()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("live_carry")

from v7.nodes.funding_carry_node import FundingCarryNode

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
DEFAULT_CAPITAL_PER_ASSET = 2_000  # $2K par actif


@dataclass
class CarryPosition:
    symbol: str
    open: bool = False
    size_usd: float = 0.0
    total_funding: float = 0.0
    n_payments: int = 0
    opened_at: str = ""
    last_funding_rate: float = 0.0


class FundingCarryScheduler:
    """Orchestrateur live du funding carry pour tous les actifs.
    
    Intégration:
        scheduler = FundingCarryScheduler(capital_per_asset=2000)
        # À chaque cycle de 8h:
        results = scheduler.run_cycle()
        for r in results:
            print(r["symbol"], r["signal"], r["size_usd"])
    """

    def __init__(self, capital_per_asset: float = DEFAULT_CAPITAL_PER_ASSET):
        self.capital_per_asset = capital_per_asset
        self.nodes: dict[str, FundingCarryNode] = {}
        self.positions: dict[str, CarryPosition] = {}
        
        for sym in SYMBOLS:
            self.nodes[sym] = FundingCarryNode(
                node_id=f"live_carry_{sym.replace('/', '_').lower()}",
                symbol=sym,
                capital=capital_per_asset,
                fraction=0.50,
                min_funding=0.00005,
            )
            self.positions[sym] = CarryPosition(symbol=sym)
    
    def run_cycle(self, spot_prices: dict[str, float] | None = None) -> list[dict]:
        """Exécute un cycle de funding carry pour tous les actifs.
        
        Args:
            spot_prices: dict {symbol: price} — si None, utilise 0 (pas nécessaire
                        pour la décision carry, juste pour le basis check)
        
        Returns:
            Liste de décisions par actif
        """
        results = []
        
        for sym, node in self.nodes.items():
            try:
                price = spot_prices.get(sym, 0) if spot_prices else 0
                output = node.run({"spot_price": price})
                
                # Mettre à jour le suivi
                pos = self.positions[sym]
                pos.open = output["position_open"]
                pos.total_funding = output["total_funding_received"]
                pos.n_payments = output["n_payments"]
                pos.last_funding_rate = output["funding_rate"]
                
                if output["signal"] == "open_carry":
                    pos.size_usd = output["size_usd"]
                    pos.opened_at = datetime.now().isoformat()
                
                results.append({
                    "symbol": sym,
                    "signal": output["signal"],
                    "size_usd": output["size_usd"],
                    "funding_rate": output["funding_rate"],
                    "annual_pct": output["annual_funding_pct"],
                    "total_funding": output["total_funding_received"],
                    "reason": output["reason"],
                    "confidence": output["confidence"],
                })
                
                if output["signal"] in ("open_carry", "close_carry"):
                    logger.info("CARRY %s: %s | size=$%.0f | funding=%.4f%% | %s",
                               sym, output["signal"].upper(), output["size_usd"],
                               output["funding_rate"] * 100, output["reason"])
                
            except Exception as e:
                logger.error("Carry error for %s: %s", sym, e)
        
        return results
    
    def get_summary(self) -> dict:
        """Retourne un résumé des positions carry ouvertes."""
        open_positions = [p for p in self.positions.values() if p.open]
        total_funding = sum(p.total_funding for p in self.positions.values())
        total_size = sum(p.size_usd for p in open_positions)
        
        return {
            "active_carries": len(open_positions),
            "total_size_usd": total_size,
            "total_funding_received": total_funding,
            "positions": [
                {
                    "symbol": p.symbol,
                    "size": p.size_usd,
                    "funding": p.total_funding,
                    "payments": p.n_payments,
                    "opened": p.opened_at[:19] if p.opened_at else "",
                }
                for p in open_positions
            ],
        }


# ── Test ──
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    
    scheduler = FundingCarryScheduler(capital_per_asset=2_000)
    
    # Prix spot mock (en prod: depuis le pipeline data)
    spot_prices = {
        "BTC/USDT": 67000,
        "ETH/USDT": 3500,
        "SOL/USDT": 150,
        "BNB/USDT": 620,
        "XRP/USDT": 0.52,
        "ADA/USDT": 0.45,
        "DOGE/USDT": 0.12,
    }
    
    print("=== V7 Funding Carry — Live Test ===\n")
    results = scheduler.run_cycle(spot_prices)
    
    for r in results:
        flag = "🟢" if r["signal"] == "open_carry" else "🔴" if r["signal"] == "close_carry" else "⚪"
        print(f"{flag} {r['symbol']:<10} {r['signal']:<12} size=${r['size_usd']:<8.0f} "
              f"funding={r['funding_rate']*100:.4f}% ({r['annual_pct']:.1f}%/an) "
              f"| {r['reason'][:60]}")
    
    print(f"\n📊 Résumé: {scheduler.get_summary()}")
