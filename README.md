# Atlas Trader — Risk Premium Harvesting

> **Funding Rate Carry** : delta-neutral strategy (short perp + long spot) capturing the funding rate premium.
> **Status** : 🟢 Paper trading live on GX10 (192.168.1.80) — 26 assets, 8h DAG cycles · **http://atlastrader.org**
> **Last update** : 24 July 2026 — kill-switch fixed, dual LLM config, exposure card, i18n EN logs

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
| Economic hurdle | **5%** (optimized) | SOFR only — grid search: 25/26 assets prefer 5% over 7% |
| Sizing | Risk budgeting | `score = net_return / stress_loss`, capped at 25% |
| Stress loss | Per-asset (optimizer) | Derived from 30d volatility |
| Entry filters | Funding range + percentile + basis check | |
| Exit | Economic zones | HEALTHY < 14j / REVIEW 14-30j / DERISK 30-60j / CLOSE > 60j |
| Safety cap | Per-asset (optimizer) | Proportional to open interest |
| Global Allocator | Dynamic exposure, max N positions | Cross-asset exposure control from config |
| Kill-switch | 4 tiers recalibrated | **FIXED 24/07**: Tier 3 sign bug (0% < +20% always true → fixed to -20%) |
| Fees | 48 bps round-trip | 4 legs × 12 bps |
| LLM (DAG analysis) | Dual config | Deep model (BO) + Fast model (DAG, configurable) |

### 🔧 Bug Fixes — 24 July 2026

| Bug | Impact | Fix |
|-----|--------|-----|
| Kill-switch PORTFOLIO_DD always triggers | All positions closed after 40s | `total_pnl_pct < -(max_portfolio_dd_pct * 100)` |
| Economic hurdle 7% blocks assets | NEAR $7 < $50 min → skip | Default 7% → 5% (grid search validated) |
| `_deep_merge` erases keys with empty strings | API key lost from settings.yaml | Skip empty/None values in merge |
| Score 0/100 in dashboard | Carry score never persisted | Store in `context_json`, extract in `_get_recent_trades()` |
| Duplicate ZEC openings | Race condition DB check | Added DB safety check before `position_open = True` |
| LLMNode `str.format()` crash | Duplicate `inputs` kwarg | Pop `inputs` from format dict before passing |
| French logs in PositionMonitor | Mixed FR/EN logs | All logs → English |

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
  atlas-v4-dashboard — Streamlit (port 8502) : BO + FO unified · http://atlastrader.org
  atlas-v4-frontend  — Next.js (port 3000) : DAG canvas editor
  atlas-v4-ollama    — Local LLM (DeepSeek fallback)

DAG per active asset (8h cycle) :
  AssetDef → FundingCarryNode → PaperTrader + RecordDecision + LLMNode (use_fast=True)

Dynamic DAG management :
  carry_assets.yaml → scanner (CCXT) → optimizer → POST /dag/reload → live sync

Dual LLM config :
  settings.yaml → llm (deep model, BO reasoning) + llm.fast_* (fast model, DAG analysis)
  Supports different providers with separate API keys
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
| `v4/nodes/config_loader.py` | Settings loader — `/app/data/` priority, secrets merge (skip empty) |
| `v4/nodes/ai/llm_node.py` | LLM node — dual config (deep/fast), secrets.yaml API key resolution |
| `config/carry_assets.yaml` | Single source of truth — 43 assets, per-asset params |
| `dashboard/streamlit_app.py` | Streamlit dashboard — i18n, carry_cfg editor, scanner UI |
| `dashboard/multi_asset.py` | Live price cards + asset icons + sidebar navigation |
| `utils/i18n.py` | Backend translations (~300 keys × 8 languages) |
| `images/assets/` | 42 official crypto logo SVGs |

## Backoffice — Key Features

**🎯 Carry Assets Tab** — full lifecycle management:
1. **🔄 Scan Binance** — CCXT detects all Spot∩Perp pairs (43 candidates)
2. **📊 Optimize** — fetches volatility, funding history, OI per asset; reads backtest results; flags viability
3. **📊 Apply optimized** — copies `_optimized_*` params to live config (respects 🔒 locked assets)
4. **🚀 Apply & Reload DAGs** — syncs API DAGs with config without restart
5. **📂 Expand/Collapse all** + **📷 Logo uploads** — SVG fallback from `images/assets/`

**💸 Portfolio Exposure Card** — total $ in open carry positions with % of capital

**🤖 Dual AI Model Config** — separate deep (reasoning) and fast (DAG analysis) models with independent API keys

**🗑️ Reset** — one-click DAG stop + trade history clear + DAG restart

## Operations (OPS.md)

Full runbook at [`OPS.md`](OPS.md):
- Startup, monitoring, emergency stop
- Backtest commands
- Kill-switch management
- Maintenance (DB reset, disk space)

---

**Built by Jako · July 2026**

