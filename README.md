# Atlas Trader V7.2 — Risk Premium Harvesting

> **Funding Rate Carry** : delta-neutral strategy (short perp + long spot) capturing the funding rate premium.
> **Status** : 🟢 Paper trading live on GX10 since 15 June 2026

**Branch**: `v7-dev`

---

## Strategy

The strategy is **market-neutral** : short perpetual futures + long spot. Price movements cancel out. The only P&L comes from:

1. **Funding rate** — received every 8h when funding > 0 (longs pay shorts)
2. **Basis change** — (perp − spot) spread variation (typically < 0.01%/day)

No directional prediction. No ML. Pure risk premium harvesting.

### Key Parameters (V7.2)

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Capital per asset | $2,000 | |
| Dynamic hurdle | ~7% | SOFR 5% + exchange risk 1% + USDT 0.5% + buffer 0.5% |
| Sizing | Risk budgeting | `score = net_return / stress_loss`, capped at 25% capital |
| Stress loss | 4-12% per asset | BTC/ETH 4%, SOL/BNB 8%, alts 12% |
| Entry filters | Funding in range + MA 7d > 0 + basis OK + vol multiplier | |
| Primary exit | Payback days zones | HEALTHY < 30j / WATCH 30-60j / DERISK 60-90j / CLOSE > 90j |
| Safety exit | Max loss −5% | Checked every 60s |
| Kill-switch | 4 tiers | Tier 0 (circuit breaker) → Tier 3 (portfolio −20%) → Tier 4 (emergency) |
| Fees | 28 bps round-trip | 4 legs × 7 bps |

### V7.2 Backtest — 3 years (2023-2026)

Causal funding (no look-ahead), 4-leg fees, dynamic hurdle, risk budgeting:

| Asset | PnL (3y) | % | Sharpe | MaxDD | Trades |
|-------|----------|---|--------|-------|--------|
| DOGE | $458 | 4.6% | 7.25 | 0.1% | 24 |
| ADA | $423 | 4.2% | 6.58 | 0.1% | 26 |
| XRP | $421 | 4.2% | 6.95 | 0.1% | 24 |
| BTC | $367 | 3.7% | 6.07 | 0.1% | 24 |
| SOL | $355 | 3.6% | 5.79 | 0.1% | 24 |
| ETH | $335 | 3.4% | 5.70 | 0.1% | 24 |
| BNB | $78 | 0.8% | 1.64 | 0.1% | 20 |

> ⚠️ The backtest uses funding-only simulation (no spot/perp prices). Real P&L depends on basis movements. The 0.1% max drawdown reflects the strategy's conservative design — most capital remains idle.

## Architecture

```
Docker Compose :
  atlas-v4-api       — FastAPI (port 8000) : DAG execution + PositionMonitor
  atlas-v4-dashboard — Streamlit (port 8502)
  atlas-v4-frontend  — Next.js (port 3000)
  atlas-v4-ollama    — Local LLM (DeepSeek fallback)

DAG per asset (7 assets, 8h cycle) :
  AssetDef → FundingCarryNode → PaperTrader + RecordDecision + LLMNode

PositionMonitor (60s loop) :
  Tier 0 circuit breaker → Kill-switch 4-tiers → Max loss −5% → Payback zones
```

## Quick Start

```bash
git clone https://github.com/eletec/atlas-trader.git
cd atlas-trader
git checkout v7-dev

# Start services
docker compose -f docker-compose.v4.yml up -d --build

# Run backtest (V7.2 rules)
docker exec atlas-v4-api python /app/src/v7/backtest_v7.py --symbol BTC/USDT --days 1095

# Reconcile positions
docker exec atlas-v4-api python /app/src/scripts/reconcile.py

# Run stress tests (8 scenarios)
docker exec atlas-v4-api python /app/src/scripts/stress_test.py
```

## Key Files

| Path | Purpose |
|------|---------|
| `v7/nodes/funding_carry_node.py` | Core strategy logic |
| `v7/position_monitor.py` | Risk monitor (60s loop) |
| `v7/backtest_v7.py` | Backtest engine (V7.2 rules) |
| `v7/api/live_pnl.py` | Real carry P&L endpoint |
| `scripts/reconcile.py` | DB ↔ market reconciliation |
| `scripts/stress_test.py` | Kill-switch validation (8 scenarios) |
| `config/asset_profiles.yaml` | V7 carry defaults |
| `dashboard/streamlit_app.py` | Streamlit dashboard |

