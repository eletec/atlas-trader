# Atlas Trader — Risk Premium Harvesting

> **Funding Rate Carry** : delta-neutral strategy (short perp + long spot) capturing the funding rate premium.
> **Status** : 🟢 Paper trading live on GX10 (192.168.1.80) — 26 assets, 8h DAG cycles
> **Last audit** : 23 July 2026 — 43 Spot∩Perp scanned, 26 viable, grid search optimized

---

## Strategy

The strategy is **market-neutral** : short perpetual futures + long spot. Price movements cancel out. The only P&L comes from:

1. **Funding rate** — received every 8h when funding > 0 (longs pay shorts)
2. **Basis change** — (perp − spot) spread variation (typically < 0.01%/day)

No directional prediction. No ML. Pure risk premium harvesting.

### Key Parameters (V7.3 — 24 July 2026)

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Capital per asset | $2,000 | Configurable per asset in `carry_assets.yaml` |
| Dynamic hurdle | 5% (optimized) | SOFR + venue risk — grid search validated |
| Sizing | Risk budgeting | `score = net_return / stress_loss`, capped at 25% |
| Stress loss | Per-asset (optimizer) | Derived from 30d volatility |
| Entry filters | Funding range + percentile + basis check | |
| Exit | Economic zones | HEALTHY < 14j / REVIEW 14-30j / DERISK 30-60j / CLOSE > 60j |
| Safety cap | Per-asset (optimizer) | Proportional to open interest |
| Global Allocator | Dynamic exposure, max N positions | Cross-asset exposure control from config |
| Kill-switch | 4 tiers recalibrated | Tier 1 auto-reset, Tier 2+ manual |
| Fees | 48 bps round-trip | 4 legs × 12 bps |

### V7.3 Backtest — 1 year (July 2025–2026), real spot/perp prices

26 active assets, $2,000/asset, economic hurdle 5%:

| Metric | Value |
|--------|-------|
| Traded assets | 26/26 |
| Portfolio PnL | +$153 (0.3%) |
| Sharpe (traded) | 0.35 |
| Duration | 91s for 26 assets |

> ⚠️ Funding rates in 2025–2026 were historically low. 3-year backtest (2023–2026) shows 20–26 trades/asset with stronger PnL. Strategy conserves capital in low-rate regimes via staking (5%/yr idle).

---

## Architecture

```
Docker Compose :
  atlas-v4-api       — FastAPI (port 8000) : DAG execution + PositionMonitor
  atlas-v4-dashboard — Streamlit (port 8502) : BO + FO unified
  atlas-v4-frontend  — Next.js (port 3000) : DAG canvas editor
  atlas-v4-ollama    — Local LLM (DeepSeek fallback)

DAG per active asset (8h cycle) :
  AssetDef → FundingCarryNode → PaperTrader + RecordDecision + LLMNode

Dynamic DAG management :
  carry_assets.yaml → scanner (CCXT) → optimizer → POST /dag/reload → live sync
```

## Quick Start

```bash
git clone https://github.com/eletec/atlas-trader.git
cd atlas-trader
git checkout v7-dev

# Start services
docker compose -f docker-compose.v4.yml up -d --build

# Scan Binance for eligible Spot∩Perp pairs
docker exec atlas-v4-api python /app/src/v7/core/carry_scanner.py --save

# Compute optimized parameters (requires backtest first)
docker exec atlas-v4-api python /app/src/v7/core/carry_scanner.py --save --optimize

# Run backtest (V7.3 rules, real spot/perp prices)
docker exec atlas-v4-api python -B /app/src/v7/backtest_v7_node.py --symbol ACTIVE --days 365

# Grid search best parameters (36 combos × 2 passes per asset)
docker exec atlas-v4-api python -B /app/src/v7/core/grid_search.py --symbol ACTIVE --days 365
```

## Key Files

| Path | Purpose |
|------|---------|
| `v7/nodes/funding_carry_node.py` | Core strategy — economic hurdle, risk budgeting, exit zones |
| `v7/position_monitor.py` | Risk monitor (60s) — kill-switch 4-tiers, Margin Monitor |
| `v7/core/global_allocator.py` | Cross-asset allocation — exposure cap, position limits |
| `v7/core/asset_config.py` | Dynamic config loader — reads `carry_assets.yaml` |
| `v7/core/carry_scanner.py` | CCXT scanner — Spot∩Perp intersection, volume/OI filters |
| `v7/core/grid_search.py` | 2-pass grid search — coarse + fine param optimization |
| `v7/backtest_v7_node.py` | Backtest engine (real spot/perp prices, config-driven) |
| `v4/api/routes/dag.py` | DAG CRUD + kill-switch reset + `/dag/reload` endpoint |
| `v4/api/main.py` | Startup reconciliation — DAGs synced with `carry_assets.yaml` |
| `config/carry_assets.yaml` | Single source of truth — 43 assets, per-asset params |
| `dashboard/streamlit_app.py` | Streamlit dashboard — i18n, carry_cfg editor, scanner UI |
| `dashboard/multi_asset.py` | Live price cards + asset icons + sidebar navigation |
| `utils/i18n.py` | Backend translations (~300 keys × 8 languages) |
| `images/assets/` | 42 official crypto logo SVGs |

## Backoffice — Carry Assets Tab

The **🎯 Carry Assets** tab provides full lifecycle management:

1. **🔄 Scan Binance** — CCXT detects all Spot∩Perp pairs (43 candidates)
2. **📊 Optimize** — fetches volatility, funding history, OI per asset; reads backtest results; flags viability
3. **🛑 Disable non-viable** — one-click bulk disable (0 trades, extreme drawdown)
4. **📊 Apply optimized** — copies `_optimized_*` params to live config (respects 🔒 locked assets)
5. **🚀 Apply & Reload DAGs** — syncs API DAGs with config without restart
6. **📂 Expand/Collapse all** — bulk asset management
7. **📷 Logo upload** — per-asset official logo (local storage)

## Operations (OPS.md)

Full runbook at [`OPS.md`](OPS.md):
- Startup, monitoring, emergency stop
- Backtest commands
- Kill-switch management
- Maintenance (DB reset, disk space)

---

**Built by Jako · July 2026**

