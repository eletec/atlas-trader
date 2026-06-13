# Atlas Trader V6 🧠

> Autonomous crypto trading system — **7 assets** (BTC · ETH · SOL · BNB · XRP · ADA · DOGE)  
> DAG-based pipeline · MetaGate (ML) · RegimeDetector · Kelly sizing · Walk-Forward 365j

**Branch**: `v6-dev` | **Status**: Paper trading live on GX10 (Intel N100, 16 GB)

---

## Architecture V6

```
LoadMultiTF (5m+1h) ──→ ComputeFeatures ──→ Normalize
       │                        │
       ├─→ CrossTFArb           ├─→ SignalXGB (48b + 12b)   ← V6 multi-horizon
       ├─→ TrendFilter          │
       └─→ RegimeDetector ──────┤    (ADX+Choppiness → TREND/RANGE/CHOP)
                                │
                                ↓
                         ╔══ MetaGate V6 ═══╗
                         ║ LogisticRegression║  ← entraîné 180j/actif
                         ║ 8 features        ║
                         ║ + RegimeAdapter   ║  ← TREND×1.0, RANGE×0.3, CHOP=BLOCK
                         ║ + IA Veto         ║  ← confiance > 0.8 → flat
                         ╚═══════════════════╝
                                │
                                ↓
                        RiskATR (Kelly sizing)
                                │
                                ↓
                        CircuitBreaker (DD > -5%)
                                │
                                ↓
                        PortfolioRisk (sizing × corr)
                                │
                                ↓
                        PaperTrader

[Async] LLMNode + DebateNode (DeepSeek V4 Pro)
[Async] ReflectionEngine (analyse trades perdants)
[Tools] WalkForward 365j + Optuna
```

## Key Features (V4 → V6 evolution)

| Feature | V4 | V5 | V6 |
|---|---|---|---|
| **Gate** | Poids fixes (50/25/10/10/5) | LogisticRegression entraînée | + Multi-horizon (12+48b) + Kelly |
| **Régime** | Passthrough (toujours TREND) | ADX + Choppiness | + RegimeAdapter (seuil×1.5 RANGE, BLOCK CHOP) |
| **Sizing** | Fixe (fraction × capital) | ATR-based | + Kelly fractionnel + sizing×corr |
| **Validation** | Backtest 60j | Backtest 180j | **Walk-Forward 365j** (6 fenêtres OOS) |
| **Optimisation** | Grid search 16 combos | Grid search + Optuna | Optuna Bayesian |
| **IA** | Signal cosmétique (10%) | Async cache | + ReflectionEngine + Veto conditionnel |
| **Risque** | Aucun | CircuitBreaker + PortfolioRisk | + sizing × (1 − corr_BTC) |
| **Actifs** | 5 | 7 (ADA+DOGE) | 7 |

## Quick Start

```bash
git clone https://github.com/eletec/atlas-trader.git
cd atlas-trader
git checkout v6-dev

# Docker
docker compose -f docker-compose.v4.yml up -d --build

# Train MetaGate models (7 assets, 180 days, ~20 min first run)
docker exec atlas-v4-api python src/tools/train_meta_gate.py

# Walk-Forward validation (365 days)
docker exec atlas-v4-api python src/tools/walkforward_v6.py --asset BTC/USDT --days 365 --trials 50
```

## Dashboard

`http://localhost:8502` — Streamlit dashboard
- **Public**: Live positions, P&L, AI analysis, trade history, charts
- **Admin** (`?admin=1`): Backtest V6, Walk-Forward, Configuration, Réflexions IA, Logs

## Branches

| Branch | Description |
|---|---|
| `main` | Stable (V3 research) |
| `v5-dev` | Production V5 (MetaGate + CircuitBreaker + PortfolioRisk) |
| `v6-dev` | **Active** — V6.1 (Multi-horizon + Kelly + IA Veto + WalkForward) |

## Tech Stack

Python 3.11 · FastAPI · Streamlit · Next.js 14 · XGBoost · scikit-learn · Optuna · LiteLLM (DeepSeek V4 Pro) · Docker · SQLite · Binance Spot (ccxt)

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — System architecture
- [`CDC.md`](CDC.md) — Cahier des charges
- [`RESEARCH_HISTORY.md`](RESEARCH_HISTORY.md) — Development chronicle
