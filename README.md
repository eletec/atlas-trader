# Atlas Trader — Risk Premium Harvesting

> **Funding Rate Carry** : delta-neutral strategy (short perp + long spot) capturing the funding rate premium.
> **Status** : 🟢 Paper trading live on GX10 (192.168.1.80) since 15 June 2026
> **Last audit** : 20 July 2026 — 3 AIs, 25+ recommendations, 11 implemented

---

## Strategy

The strategy is **market-neutral** : short perpetual futures + long spot. Price movements cancel out. The only P&L comes from:

1. **Funding rate** — received every 8h when funding > 0 (longs pay shorts)
2. **Basis change** — (perp − spot) spread variation (typically < 0.01%/day)

No directional prediction. No ML. Pure risk premium harvesting.

### Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Capital per asset | $2,000 | 7 assets = $14,000 total |
| Dynamic hurdle | ~7% | SOFR 5% + exchange 1% + USDT 0.5% + buffer 0.5% |
| Hurdle filter | Double | Economic + percentile (top 20% of 90d) |
| Sizing | Risk budgeting | `score = net_return / stress_loss`, capped at 25% |
| Stress loss | 4-12% per asset | BTC/ETH 4%, SOL/BNB 8%, alts 12% |
| Entry filters | Funding range + MA 7d > 0 + basis OK | |
| Exit | Economic zones | HEALTHY < 14j / REVIEW 14-30j / DERISK 30-60j / CLOSE > 60j |
| Safety exit | Max loss −5% | Checked every 60s |
| Global Allocator | 40% cap, max 4 positions | Cross-asset exposure control |
| Margin Monitor | Liquidation distance | Simulates perp margin safety |
| Kill-switch | 4 tiers recalibrated | Tier 1 auto-reset, Tier 2+ manual (`POST /dag/reset-kill-switch`) |
| Funding interval | Dynamic (Binance API) | `fundingIntervalHours` per symbol |
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
| `v7/nodes/funding_carry_node.py` | Core strategy — double hurdle, risk budgeting, economic exit zones |
| `v7/position_monitor.py` | Risk monitor (60s) — kill-switch 4-tiers, Margin Monitor, carry P&L |
| `v7/core/global_allocator.py` | Cross-asset allocation — exposure cap, position limits, scoring |
| `v7/backtest_v7.py` | Backtest engine (V7.2 rules) |
| `v7/api/live_pnl.py` | Real carry P&L endpoint (`/v7/carry-pnl`) |
| `v4/api/routes/dag.py` | DAG CRUD + kill-switch reset endpoint |
| `scripts/reconcile.py` | DB ↔ market reconciliation |
| `scripts/stress_test.py` | Kill-switch validation (8 scenarios) |
| `config/asset_profiles.yaml` | Carry defaults per asset |
| `dashboard/streamlit_app.py` | Streamlit dashboard (i18n, 8 languages) |
| `utils/i18n.py` | Backend translations (~250 keys × 8 languages) |
| `v4/frontend/src/i18n/` | Frontend i18n (React Context, 8 JSON files) |

