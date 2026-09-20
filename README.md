# Atlas Trader — Funding Rate Carry

> **Delta-neutral funding-rate harvesting** on Binance USDⓈ-M perpetuals.
> Short perpetual + long spot, same notional → near-zero directional exposure.
> **Status**: 🟡 paper trading only — no exchange account, no real money.
> **Last update**: 20 September 2026

---

## 1. What the trade actually is

A perpetual future is tethered to its spot price by a **funding rate**, exchanged
between longs and shorts every 8 hours. When funding is positive, longs pay
shorts. This project collects that payment while cancelling price exposure:

| Leg | Side | Purpose |
|-----|------|---------|
| Spot | **Long** | Owns the asset — the hedge |
| Perpetual | **Short** (same notional) | Collects the funding payment |

If the price of the asset moves, the spot leg gains exactly what the perp leg
loses (and vice versa). What remains is the funding collected, minus fees, plus
whatever the **basis** did (see below).

No directional prediction, no ML, no price forecasting. The edge — if any — is a
risk premium paid by leveraged longs to whoever is willing to hold the hedge.

### The two things that can go wrong

1. **Funding flips negative** — then the position *pays* instead of collecting.
2. **The short perp leg gets liquidated** — delta-neutral is not the same as
   risk-free: a violent price rise can exhaust the perp margin before the spot
   gain can be realised or mobilised. The monitor models this explicitly.

---

## 2. How P&L is computed

Three components, all in USD:

**a. Funding collected** — on the perp leg only (half the position):
```
funding_pnl = entry_capital × funding_rate      per 8h payment
```
The node accumulates this in `total_funding_received` each cycle.

**b. Basis P&L** — the perp/spot price differential, where `basis = (spot − perp) / spot`:
```
basis_pnl = (basis_entry − basis_now) × size_usd
```
Because the position is long spot *and* short perp, it **gains when the basis
contracts** and loses when it widens. Basis is the main source of unrealised
drawdown even while funding is being collected.

**c. Fees** — 48 bps round-trip, i.e. **4 legs × 12 bps** (10 bps taker +
2 bps slippage): open spot, open perp, close spot, close perp. Fees are paid up
front and only recovered after enough funding periods.

```
net_pnl = funding_pnl + basis_pnl − 48 bps × notional
```

### Two traps this README wants you to avoid

- **The basis is deliberately excluded from the entry expected-return.** The
  code sets `expected_return = annual_funding` only. A negative basis must not
  silently "pay for" a marginal trade, because basis convergence is not
  guaranteed. Basis is used as an entry *filter* (must be > −0.30%) and as a
  monitored *risk*, never as expected profit.
- **Staking is not trading.** Idle capital accrues a simulated 5%/yr staking
  yield (`global.staking_annual`), reported separately. The backtest summary
  prints `Total P&L = trading + staking`, and at current funding levels staking
  dominates by ~50×. **Read the "Trading P&L" line, not "Total P&L".**

---

## 3. Entry decision (evaluated in this order)

Implemented in `v7/nodes/funding_carry_node.py`. Every gate must pass:

| # | Gate | Threshold | Why |
|---|------|-----------|-----|
| 1 | Cooldown after last close | 24 h | Anti-churn: 3 SHIB round-trips in 16 h once cost −$1.44 in fees alone |
| 2 | Instant funding in range | 0.02% – 0.30% / 8h | Below 0.02% the fees cannot be amortised; above 0.30% the rate is usually a transient spike |
| 3 | 7-day funding MA | > 0 | Rejects isolated spikes that revert before the position pays for itself |
| 4 | Basis | > −0.30% | Refuses to open into an already-stretched perp premium |
| 5 | Net expected return | > hurdle (5%/yr) | `annual_funding − (48 bps × 365 / max_hold_days)` must beat the cost of capital |
| 6 | Relative funding level | ≥ 60th percentile | Only take trades where funding is high *for this asset* over its own 90-day history |
| 7 | Position size | ≥ $50 | Risk budgeting, see below |
| 8 | Portfolio + DB checks | — | Global exposure cap, and a hard check that no position is already open |

**Position sizing** is risk budgeting, not equal-weight:
```
score   = (net_expected_return − hurdle) / stress_loss_pct
size    = min(capital × fraction × min(score, 0.25), safety_cap)
```
`stress_loss_pct` and `safety_cap` are per-asset. `min(score, 0.25)` caps a
single position at 25% of the allocated capital regardless of how attractive the
signal looks.

## 4. Exit logic

Two independent mechanisms:

**Economic zones** (evaluated by the node each cycle, on days held):

| Zone | Condition | Action |
|------|-----------|--------|
| < 14 d | — | Hold |
| > 14 d | — | REVIEW — logged only |
| > 30 d | — | **DERISK** — close if `forward_funding < hurdle + exit_cost_annual` |
| > 60 d | — | **CLOSE** unconditionally |

"Forward funding" is the current annualised rate; the exit cost is the 48 bps
round-trip amortised over the days actually held. A carry that no longer covers
its own exit costs is closed rather than held in hope.

**Continuous monitor** (`v7/position_monitor.py`, every 60 s) — a 4-tier
kill-switch that closes everything:

| Tier | Trigger | Meaning |
|------|---------|---------|
| OPERATIONAL | Price cache older than 5 min | We are blind — no new risk |
| MARKET | \|unrealised P&L\| > 10% of total capital | Abnormal market stress |
| PORTFOLIO_DD | Portfolio P&L < −20% | Drawdown limit |
| CORRELATED_LOSS | ≥ 3 carry positions losing **and** portfolio < −3% **and** average loss > 1% | Basis blow-out across the book, not noise |

Plus, per position: max loss (−5%), stale-price circuit breaker, and a
`_check_margin_safety()` calculation that estimates the liquidation price of the
short leg using each asset's configured leverage.

### Why one SHIB trade once reported −$18.45

The perp contract for SHIB is `1000SHIB`: its price is 1000× the token price.
Comparing it against the spot price made `(perp − spot)/spot ≈ −999` instead of
~0, multiplying every basis move by 1000 and firing the kill-switch. Perp prices
are now normalised (`÷1000` for PEPE/SHIB/BONK/FLOKI/LUNC) in the node, the
monitor, the API and the backtests. Historical rows were corrected: the real
closed P&L was −$4.25, not −$22.69.

---

## 5. Measured performance — and why it is currently ~zero

**This is the most important section of this README.**

A fresh 1-year backtest on the 6 active assets, run 20 Sep 2026
(`backtest_v7_node.py --symbol ACTIVE --days 365`, real spot/perp/funding data):

```
Portfolio: 6 actifs | 2 traded, 4 never entered
Trading P&L : $3.71   (0.03% on $12,000)     ← the strategy itself
Staking P&L : $187.57 (1.56%)                ← idle capital, NOT trading
Total P&L   : $191.28 (1.59%)
```

Two of six assets traded **once each** over a full year. The other four never
cleared the 0.02%/8h entry gate.

Current live funding rates (20 Sep 2026) explain why:

| Asset | Funding / 8h | vs 0.02% gate |
|-------|--------------|---------------|
| BTC | +0.0071% | below |
| ETH | −0.0009% | **negative** |
| SOL | +0.0100% | below |
| BNB | +0.0103% | below |
| AVAX | +0.0100% | below |
| XRP | +0.0100% | below |

**Conclusion: the strategy is structurally sound but not currently profitable.**
At these funding levels the measured trading edge is ~0% — below the 5% hurdle
and below the risk-free rate. The 3-year walk-forward (July 2026) points the
same way: median OOS return +0.032%/quarter (~0.13%/yr) once fees are paid.

The strategy only becomes interesting in a **high-funding regime** (broadly:
strong bullish leverage demand), which did not occur in the sampled period.

### Limits, stated plainly

- **Paper trading only.** No order routing, no exchange account, no keys. Fills
  are modelled, not observed.
- **Regime-dependent.** BEAR markets are **untested** — no bear regime appears
  in the 2023–2026 sample. Conclusions do not extrapolate to one.
- **Two trades is not a sample.** All performance figures above are indicative,
  not statistically meaningful.
- **Staking yield is an assumption** (5%/yr), not a realised return. It is
  reported separately for exactly this reason.
- **Counterparty / venue risk is not modelled.** If Binance halts withdrawals or
  the perp leg is force-closed, the hedge breaks.
- **Liquidation risk is approximated**, not simulated: the monitor uses a
  simplified maintenance-margin model.
- **Concentrated universe** — 6 majors. Fewer candidates means fewer trades.
- **No rebalancing logic**: as the two legs drift, the position becomes
  slightly directional until closed.

---

## 6. Configuration

`config/carry_assets.yaml` is the **single source of truth** —
`get_active_assets()` / `get_asset_params()` are used by the live cycle, the
monitor, the backtests and the grid search, so a backtest always tests the
strategy that is actually running.

```yaml
global:
  total_capital: 14000          # kill-switch denominator (6 × $2,000 + buffer)
  max_total_exposure_pct: 0.6   # ≤ 60% of capital deployed at once
  max_simultaneous_positions: 6 # one per major
  round_trip_cost_bps: 48       # 4 legs × 12 bps
  estimated_hold_days: 30       # fee-amortisation horizon
  staking_annual: 0.05          # idle-capital yield (reported separately)

assets:
  BTC/USDT:
    enabled: true
    capital: 2000               # notional allocated to this asset
    fraction: 0.5               # share of that capital actually deployed
    safety_cap: 400             # hard ceiling on position size
    stress_loss_pct: 0.04       # denominator of the risk-budgeting score
    max_hold_days: 30           # fee-amortisation + time-stop horizon
    min_funding: 0.0002         # 0.02% per 8h
    max_funding: 0.003          # 0.30% per 8h
    exit_after_hours: 72
    leverage: 2.0               # used by the margin/liquidation check
```

**Why 6 majors and not 37?** `carry_scanner.py` finds 37 Spot∩Perp pairs, but
alt funding is noisy and round-trips are expensive: a 24 h hold pays 48 bps of
fees against ~6 bps of funding. The universe was cut to assets where liquidity
and funding quality justify the fixed cost.

**Why a 5% hurdle?** It represents the cost of capital, and it is deliberately
**not** optimised. Grid-searching the hurdle reintroduces data mining: whatever
value maximises the backtest is, by construction, fitted to the past.

**Why 30 days max hold?** 48 bps of round-trip fees amortised over 30 days is
~5.8%/yr of drag — the point where the hurdle and the cost structure are
consistent. The earlier hardcoded 60-day assumption understated the real cost
~4×.

### Editing the configuration at runtime

The dashboard writes `carry_assets.yaml`; the API process caches it. After
editing in **Carry Assets → Apply & reload**, the dashboard calls
`POST /carry/reload-config`, which clears the API cache, re-reads the active
asset list and starts price tickers for any newly enabled asset. A full
container restart is no longer required.

---

## 7. Architecture

```
                      ┌─────────────────────────────────────────┐
  Binance REST ──────▶│  atlas-v4-api  (FastAPI :8000)          │
  (ccxt, 1 shared     │   ├─ consolidated price poller          │
   exchange instance) │   │    ~3s + 0.1s/asset                 │
                      │   ├─ carry cycle thread  (every 8h)     │
                      │   │    run_carry_cycle.run_cycle()      │
                      │   ├─ PositionMonitor     (every 60s)    │
                      │   └─ REST: /health /prices /dag /v7     │
                      │            /carry/run /carry/reload-config│
                      └───────────────┬─────────────────────────┘
                                      │ SQLite WAL
                                      ▼
                      /app/data/v4.db  (trades, decisions, logs)
                                      ▲
                      ┌───────────────┴─────────────────────────┐
                      │  atlas-v4-dashboard  (Streamlit :8502)  │
                      │   FO: portfolio, prices, trades, logs   │
                      │   BO: Carry Assets, History, Backup…    │
                      └─────────────────────────────────────────┘
                                      ▲
                          Nginx + Let's Encrypt
```

Each 8-hour cycle is a single deterministic pass, no DAG engine:

```
run_carry_cycle.run_cycle()
  └─ reload_config()                     ← picks up dashboard edits
     └─ for each enabled asset:
          FundingCarryNode.run()
            ├─ fetch spot / perp / funding
            ├─ evaluate entry gates (section 3)
            └─ open / hold / close → persist_trade() → v4_trades
```

**Storage.** One SQLite file in WAL mode on a Docker volume. The dashboard and
the API are separate processes sharing that file — hence the `timeout=10` on
every connection, and hence the config-reload endpoint instead of relying on
in-process state.

**Config flow.** `carry_assets.yaml` is read by both containers. Inside Docker
the runtime copy lives at `/app/data/carry_assets.yaml` (volume-backed, what the
dashboard edits); outside Docker the repo copy is used directly. This is
deliberate: on Windows, `/app/data` silently resolves to `C:\app\data`, and a
stale file there once made local backtests run a different universe than
production.

---

## 8. Quick Start

```bash
git clone https://github.com/eletec/atlas-trader.git
cd atlas-trader

docker compose -f docker-compose.v4.yml up -d --build

# Run one carry cycle manually
docker exec atlas-v4-api python -B /app/src/v7/run_carry_cycle.py

# Scan Binance for eligible Spot∩Perp pairs
docker exec atlas-v4-api python -B /app/src/v7/core/carry_scanner.py --save

# 1-year backtest on the active universe (real spot/perp/funding prices)
docker exec atlas-v4-api python -B /app/src/v7/backtest_v7_node.py --symbol ACTIVE --days 365
#   --symbol accepts: ALL | ACTIVE | BTC | BTC/USDT | BTC,ETH
#   Without real prices the backtest REFUSES to run rather than fabricate a P&L.

# 3-year walk-forward, segmented by regime
docker exec atlas-v4-api python -B /app/src/v7/backtest_walkforward.py --symbols ALL --days 1300

# Cross-exchange funding comparison (Binance vs Bybit)
docker exec atlas-v4-api python -B /app/src/v7/cross_exchange_scanner.py

# Unit tests — on the host (needs pytest)
python -m pytest v7/tests/test_carry_accounting.py -v

# Unit tests — in the container (pytest is NOT in the production image)
docker exec atlas-v4-api pip install -q pytest
docker exec atlas-v4-api python -m pytest /app/src/v7/tests/test_carry_accounting.py -v
```

---

## 9. Repository layout

| Path | Purpose |
|------|---------|
| `v7/nodes/funding_carry_node.py` | **The strategy** — gates, sizing, exit zones |
| `v7/run_carry_cycle.py` | One cycle over all enabled assets |
| `v7/position_monitor.py` | 60 s risk monitor, 4-tier kill-switch, margin check |
| `v7/core/asset_config.py` | Config loader (`carry_assets.yaml`) + symbol normalisation |
| `v7/core/global_allocator.py` | Cross-asset exposure cap |
| `v7/core/carry_scanner.py` | CCXT scanner — Spot∩Perp universe |
| `v7/core/grid_search.py` | 2-pass parameter search (not used live) |
| `v7/backtest_v7_node.py` | Single-asset backtest, config-driven |
| `v7/backtest_walkforward.py` | Walk-forward with causal universe + regime split |
| `v7/cross_exchange_scanner.py` | Binance vs Bybit funding spread |
| `v7/tests/test_carry_accounting.py` | 9 unit tests — accounting, breakeven, ×1000, symbols |
| `config/carry_assets.yaml` | **Single source of truth** for the strategy |
| `v4/api/main.py` | FastAPI app, scheduler threads, `/carry/*` endpoints |
| `dashboard/streamlit_app.py` | Streamlit UI (FO + BO) |
| `dashboard/multi_asset.py` | Live price cards, sidebar navigation |
| `utils/i18n.py` | 8-language UI strings (FR/EN/DE/ES/IT/PT/NL/ZH) |

---

## 10. Known issues / not production-ready

- Only 2 trades in 12 months of backtest — statistically meaningless.
- No order execution layer: turning this into a live system requires at minimum
  exchange order routing, leg-synchronisation, margin management, and error
  recovery for partially-filled hedges.
- No funding-payment reconciliation against exchange statements.
- The dashboard reads some values from the API over HTTP; if the API is
  restarting, panels fall back to cached data.
- `storage/database.py` still contains functions from earlier V2/V3 iterations
  (shadow profiles, V2 equity curve, TimesFM/Kronos forecasting) that are no
  longer called.

## 11. Engineering history

Kept because the failure modes are instructive:

| Date | Bug | Impact | Fix |
|------|-----|--------|-----|
| 25 Jul 2026 | Fees 24 bps instead of 48 bps | Backtest undercharged by 50% | 4 legs × 12 bps |
| 25 Jul 2026 | Unrealised P&L ×100 | MaxDD −71.5% on exotic assets | Percent ÷ 100 |
| 25 Jul 2026 | Staking counted as P&L | 89% of "PnL" was fictional | Trading and staking separated |
| 25 Jul 2026 | Hurdle optimised by grid search | Data mining reintroduced | Hurdle fixed as cost of capital |
| 25 Jul 2026 | Kill-switch sign error | Every position closed every 60 s | Missing minus sign |
| Sep 2026 | ×1000 contract basis | False −$18.45 loss, kill-switch fired | Normalise perp price ÷1000 |
| Sep 2026 | Fee amortisation hardcoded at 60 d | Round-trip cost underestimated 4× | Amortise on real `max_hold_days` |
| Sep 2026 | Alt churn | 3 round-trips in 16 h = −$1.44 fees | 24 h cooldown, universe → majors |
| Sep 2026 | Backtests silently used flat $1000 prices when data was missing | Fabricated P&L | Backtests refuse to run without real prices |

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

MIT — see [`LICENSE`](LICENSE)

---

**Built by Jako · 2026** · https://atlastrader.org


