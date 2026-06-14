# Atlas Trader V7 🧠 — Risk Premium Harvesting

> **Validated**: 7/7 assets profitable · Sharpe +8.60 (vs V6: -2.09) · PnL $7,184/3ans  
> Strategy: Funding Rate Carry (short perp + long spot) — zero directional risk

**Branch**: `v7-dev` | **Status**: ✅ Backtest validated · 🟡 Paper trading pending

---

## Pourquoi V7 ?

Après 6 versions de prédiction directionnelle (XGBoost, MetaGate, HMM, Walk-Forward — **374+ configs, 0 edge**), le consensus de 4 IA (GPT, DeepSeek, Gemini, Claude) a été unanime :

> *"L'alpha n'est pas dans la prédiction du prix. Il est dans les primes de risque structurelles."*

**V7 pivote** : au lieu de prédire BTC↑/↓, on collecte le funding rate (prime de risque des perpétuels).

## Résultats — Funding Carry 3 ans

| Actif | Sharpe | PnL | MaxDD |
|---|---|---|---|
| BTC/USDT | **+9.93** | $1,051 | 0.5% |
| ETH/USDT | **+10.55** | $1,125 | 0.5% |
| SOL/USDT | **+5.83** | $902 | 0.7% |
| BNB/USDT | **+3.57** | $366 | 0.3% |
| XRP/USDT | **+8.62** | $1,165 | 0.5% |
| ADA/USDT | **+10.19** | $1,266 | 0.2% |
| DOGE/USDT | **+11.48** | $1,308 | 0.3% |
| **Portfolio** | **+8.60** | **$7,184** | |

## Quick Start

```bash
git clone https://github.com/eletec/atlas-trader.git
cd atlas-trader
git checkout v7-dev

# Docker
docker compose -f docker-compose.v4.yml up -d --build

# Backtest Funding Carry (3 ans, 7 actifs) :
docker exec atlas-v4-api python src/v7/backtest_v7.py --symbol ALL --days 1095

# Live Carry Scheduler :
docker exec atlas-v4-api python src/v7/live_carry.py
```

## Architecture V7

```
Market Data ──→ Regime Engine (6 régimes)
    │
    ├── Funding Carry (short perp + long spot → collecte funding)
    ├── Dominance Rotation (BTC.D → switch BTC/ALTs)
    └── Mean Reversion (RSI + Bollinger en RANGE)
         │
         ↓
    MetaAllocator (XGBoost → allocation capital entre stratégies)
         │
         ↓
    Risk Engine (3 niveaux) → PaperTrader
```

## Branches

| Branch | Description |
|---|---|
| `v7-dev` | **Active** — V7.0 (Funding Carry + Risk Premium) |
| `v6-dev` | V6 — Walk-Forward (concluded: no directional edge) |
| `v5-dev` | V5 — MetaGate + CircuitBreaker (production stable) |
| `main` | V6 (concluded) |
