# Atlas Trader V7 — Funding Carry Strategy

> **Market-neutral funding rate harvesting** : short perpetual + long spot, delta-neutral.
> **Status** : 🟢 Paper trading live on Infomaniak · **https://atlastrader.org**
> **Last update** : 6 August 2026 — Memory optimization (3.4GB→566MB), consolidated poller, swap added

---

## Architecture

```
Infomaniak VPS (8 GB RAM, 2 GB swap)
├── Docker Compose V4
│   ├── atlas-v4-api       — FastAPI :8000 (carry cycle 8h + PositionMonitor 60s + prix)
│   └── atlas-v4-dashboard — Streamlit :8502 (FO + BO)
├── Nginx + Let's Encrypt → atlastrader.org
└── SQLite /app/data/v4.db (WAL mode)
```

**Single script** `v7/run_carry_cycle.py` — cycle carry unique (8h).
**Consolidated price poller** : 1 task for all 23 assets (was 48 tasks → 3.4GB).

> ⚠️ **OPS.md** (runbook serveur) n'est pas versionné — voir l'instance de production.

## Strategy

The strategy captures the **funding rate premium** on crypto perpetual futures:

1. **Short perpetual** + **Long spot** on the same asset = delta-neutral
2. Every 8h, longs pay shorts when funding > 0 → we collect
3. No directional prediction. No ML. Pure risk premium.

### Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Universe | 37 Spot∩Perp pairs | Binance Spot + USDⓈ-M intersection |
| Active assets | 23 | Filtered by liquidity, backtest |
| Capital per asset | $2,000 | Safety > optimizer (never < $500) |
| Economic hurdle | 5% annual | Cost of capital (SOFR + venue risk) |
| Fees | 48 bps round-trip | 4 legs × 12 bps |
| Exit zones | 14/30/60 days | HEALTHY → REVIEW → DERISK → CLOSE |
| Kill-switch | 4 tiers | Portfolio DD, exposure, consecutive losses |
| Cycle | 8h | Single script → `v7/run_carry_cycle.py` |
| Price refresh | 3s per asset | 1 consolidated REST poller (shared ccxt instance) |

### Walk-Forward Validation (2023–2026, GPT/DeepSeek audit)

```
✅ 100% OOS windows positive (10/10)
✅ Median OOS return: +0.032%/quarter (~0.13%/year)
✅ BULL regime: median +0.089%/quarter
✅ RANGE regime: median +0.038%/quarter
⚠️ BEAR: untested (no bear market 2023-2026)
⚠️ Current funding regime too low for meaningful returns
```

### Bug Fixes (25 July 2026)

| Bug | Impact | Fix |
|-----|--------|-----|
| Fees 24bps instead of 48bps | 50% fee undercharge in backtest | 4 legs × 12bps |
| Unrealized P&L ×100 | MaxDD -71.5% on exotic assets | % ÷ 100 conversion |
| Staking inflated PnL | 89% of "PnL" was fictional staking | Separated trading/staking |
| Hurdle optimized by grid search | Data mining reintroduced | Hurdle fixed as cost of capital |
| Kill-switch sign bug | All positions closed every 60s | Missing minus sign |

---

## Architecture

```
Docker Compose V4:
  atlas-v4-api       — FastAPI :8000 → carry cycle + PositionMonitor
  atlas-v4-dashboard — Streamlit :8502 → FO/BO unified UI
  Nginx + Let's Encrypt → https://atlastrader.org

Cycle (8h): run_carry_cycle.py → 23 assets → FundingCarryNode → persist_trade
UI: Streamlit dashboard (FO/BO unifié)
```

### Simplified (25 July 2026)

After the GPT/DeepSeek audit, the execution architecture was replaced:
- **29 DAGs** → single `run_carry_cycle.py` script (background thread)
- **React/Next.js frontend** → removed (Streamlit BO tabs)
- **LLM out of critical path** — zero impact on trading decisions

---

## Quick Start

```bash
git clone https://github.com/eletec/atlas-trader.git
cd atlas-trader
git checkout v7-dev

# Start services
docker compose -f docker-compose.v4.yml up -d --build

# Run one carry cycle (manual)
docker exec atlas-v4-api python -B /app/src/v7/run_carry_cycle.py

# Scan Binance for eligible pairs
docker exec atlas-v4-api python -B /app/src/v7/core/carry_scanner.py --save

# 1-year backtest (real spot/perp prices)
docker exec atlas-v4-api python -B /app/src/v7/backtest_v7_node.py --symbol ALL --days 365

# 3-year walk-forward backtest
docker exec atlas-v4-api python -B /app/src/v7/backtest_walkforward.py --symbols ALL --days 1300

# Cross-exchange funding scanner (Binance vs Bybit)
docker exec atlas-v4-api python -B /app/src/v7/cross_exchange_scanner.py

# Unit tests
docker exec atlas-v4-api python -m pytest /app/src/v7/tests/test_carry_accounting.py -v
```

---

## Key Files

| Path | Purpose |
|------|---------|
| `v7/nodes/funding_carry_node.py` | Core strategy — hurdle, risk budgeting, exit zones |
| `v7/run_carry_cycle.py` | Single-script carry cycle |
| `v7/position_monitor.py` | Risk monitor (60s) — kill-switch 4 tiers |
| `v7/backtest_v7_node.py` | Backtest engine (real prices, config-driven) |
| `v7/backtest_walkforward.py` | Walk-forward 3Y (causal universe, regime segmentation) |
| `v7/cross_exchange_scanner.py` | Binance vs Bybit funding rate comparison |
| `v7/core/carry_scanner.py` | CCXT scanner — Spot∩Perp intersection |
| `v7/core/grid_search.py` | 2-pass grid search (hurdle removed — now fixed) |
| `v7/core/global_allocator.py` | Cross-asset allocation — exposure cap |
| `v7/core/asset_config.py` | Dynamic config loader — `carry_assets.yaml` |
| `v7/tests/test_carry_accounting.py` | 5 unit tests — P&L accounting, breakeven, % bugs |
| `config/carry_assets.yaml` | Single source of truth — 42 assets, per-asset params |
| `dashboard/streamlit_app.py` | Streamlit dashboard — BO/FO unified |
| `dashboard/multi_asset.py` | Live price cards, global overview, JS poller |

---

## Backoffice — Key Features

- **📡 Live Prices** — real-time price cards with % change and position status
- **🌐 Global View** — per-asset scores, funding rates, net returns vs hurdle
- **💼 Portfolio** — capital, exposure, open trades, P&L
- **🎯 Carry Assets** — scan, optimize, apply, reload config
- **📊 Live Monitor** — cycle status, open positions, recent decisions
- **📋 Trades** — sortable trade journal
- **🤖 AI Config** — dual LLM (DeepSeek, Ollama)

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, code style, and PR guidelines.

## License

MIT — see [`LICENSE`](LICENSE)

---

**Built by Jako · July 2026**

