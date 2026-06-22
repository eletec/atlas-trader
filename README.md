# Atlas Trader V7 🧠 — Risk Premium Harvesting

> **Live**: 7 trades ouverts · $28 P&L latent · funding collecté depuis 15/06/2026  
> Strategy: Funding Rate Carry (short perp + long spot) — market-neutral

**Branch**: `v7-dev` | **Status**: 🟢 Live paper trading on GX10 (Intel N100, 16GB)

---

## Pourquoi V7 ?

Après 6 versions de prédiction directionnelle (XGBoost, MetaGate, HMM, Walk-Forward — **374+ configs, 0 edge**), le consensus de 5 IA (GPT, DeepSeek, Gemini, Grok, Claude) a été unanime :

> *"L'alpha n'est pas dans la prédiction du prix. Il est dans les primes de risque structurelles."*

**V7 pivote** : au lieu de prédire BTC↑/↓, on collecte passivement le funding rate (prime de risque des perpetual futures).

## Backtest — 3 ans (2023-2026)

| Actif | Sharpe | PnL | 
|---|---|---|
| BTC/USDT | +9.93 | $1,051 |
| ETH/USDT | +10.55 | $1,125 |
| SOL/USDT | +5.83 | $902 |
| BNB/USDT | +3.57 | $366 |
| XRP/USDT | +8.62 | $1,165 |
| ADA/USDT | +10.19 | $1,266 |
| DOGE/USDT | +11.48 | $1,308 |
| **Portfolio** | **+8.60** | **$7,184** |

## Live — 7 jours (depuis 15/06/2026)

| Actif | Ouvert | Taille | P&L latent | Funding collecté |
|---|---|---|---|---|
| ADA | 17/06 | $400 | **+6.0%** | — (funding négatif) |
| BTC | 19/06 | $173 | -2.6% | $0.05 (8×) |
| ETH | 19/06 | $213 | -2.1% | $0.03 (6×) |
| SOL | 19/06 | $400 | -8.2% | $0.06 (5×) |
| BNB | 20/06 | $400 | -1.2% | $0.03 (2×) |
| XRP | 19/06 | $400 | -0.7% | $0.03 (2×) |
| DOGE | 19/06 | $241 | -1.3% | $0.04 (5×) |

## Quick Start

```bash
git clone https://github.com/eletec/atlas-trader.git
cd atlas-trader
git checkout v7-dev

# Docker
docker compose -f docker-compose.v4.yml up -d --build

# Backtest Funding Carry :
docker exec atlas-v4-api python /app/src/v7/backtest_v7.py --symbol ALL --days 1095
```

## Architecture V7

```
AssetDef → FundingCarryNode → PaperTrader + RecordDecision + LLMNode
                │
                ├── Fetch funding rate (Binance API)
                ├── Fetch spot + perp prices (CCXT)
                ├── Kelly sizing (quarter-Kelly, ×0.25)
                ├── Funding MA 7j filter (évite spikes)
                ├── Per-asset liquidity caps
                ├── Funding regime sizing (×0.40–1.0)
                ├── Stop-loss basis -5% + Time-stop 14j
                └── Cross-margin risk monitoring
```

## Améliorations V7.1 (post-critique 5 IA)

| Changement | Avant | Après |
|---|---|---|
| Filtre entrée | funding instantané | funding MA 7j > 0 |
| Kelly | half-Kelly (0.50) | quarter-Kelly (0.25) |
| Stop-loss | -10% fixe | -5% + time-stop 14j |
| Sizing | $400 uniforme | Caps par liquidité (BTC $400 → DOGE $100) |
| Régime | Taille fixe | ×0.40 à ×1.0 selon funding |

## Branches

| Branch | Description |
|---|---|
| `v7-dev` | **Active** — V7.1 Funding Carry (live paper trading) |
| `v6-dev` | V6 — Walk-Forward (concluded: no directional edge) |
| `main` | V6 (concluded) |
