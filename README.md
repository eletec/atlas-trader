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

**a. Funding collected** — on the perp leg only:
```
funding_pnl = leg_notional × funding_rate      per 8h payment     (signed)
```
`size_usd` is the notional of **one** leg; the gross position is `2 × size_usd`.
The node accumulates the **signed** payment in `total_funding_received`, so a
period of negative funding is a payment the book *makes*. It used to be skipped
entirely, which made every reported P&L optimistic.

**b. Basis P&L** — the perp/spot price differential:
```
basis_pnl = leg_notional × [ (spot_exit / spot_entry − 1) − (perp_exit / perp_entry − 1) ]
```
This is the exact relative-return form. The first-order `basis_entry − basis_now`
difference it replaces drifts by ~33% on a 50% directional move — and a carry book
is exposed to *nothing but* that differential.
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
| < 0.25 × `max_hold_days` | — | Hold |
| > 0.25 × `max_hold_days` | — | REVIEW — logged only |
| > 0.50 × `max_hold_days` | — | **DERISK** — close if `forward_funding < hurdle + exit_cost_annual` |
| > `max_hold_days` | — | **CLOSE** unconditionally |

The boundaries **scale with `max_hold_days`**, which *is* the forced exit. They used
to be hardcoded at 14/30/60 d while the entry gate amortised its fees over
`max_hold_days`: the gate assumed one holding period and the exit imposed another,
so a grid search over the holding period changed the gate and never the exit it was
named after. With the default `max_hold_days = 30` the zones are 7.5 / 15 / 30 d.

"Forward funding" is the current annualised rate — the bar's own rate, not a
forecast; the exit cost is the 48 bps round-trip amortised over the days actually
held. A carry that no longer covers its own exit costs is closed rather than held
in hope.

Two consequences are worth knowing, both measured (§5):

- **The economic test is gated to the DERISK zone.** Below it the only exits that
  can fire are the basis stop and the negative-funding timer, so a position whose
  funding collapses early is held into the zone regardless.
- **The threshold is conservative by construction.** It compares the instantaneous
  rate against `hurdle + the full round-trip cost`, even though the entry leg is
  already sunk, and it amortises that cost over the days *elapsed* — so the bar
  loosens the longer you hold.
- **The DERISK test uses the instantaneous rate, not its 7-day mean.** The entry
  side already uses the mean; the exit should too — one noisy period can close a
  position today.

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

All the figures in this section were produced on 20 Sep 2026, **after** three
classes of defect were fixed: the simulated clock (§11), the accounting model, and
the data pipeline. Before that, the backtester never told the strategy what date it
was simulating (so no time-based exit could ever fire), the node and the backtest
each ran their own fee and funding maths (so funding was counted unsigned and the
basis was dropped on close), and the history was truncated to 333 days and joined
on a price the strategy could not have seen yet. The numbers below replace them.

If you are comparing this section against an earlier copy of this README, the
**conclusions are unchanged** — the horizon of this work is what the market pays,
and fixing the engine did not create an edge.

### A 1-year backtest on the 6 active assets

`backtest_v7_node.py --symbol` over the active universe, `--days 365`, 8h candles,
full paginated funding history, real spot/perp/funding data:

```
Portfolio: 6 assets | 2 traded, 4 never entered | capital $12,000

  TRADING (the strategy) : $   -2.52   (-0.02%)
  Staking (idle capital) : $  284.55   (+2.37%)   <- simulated, NOT trading
  Mean Sharpe (traded)   : -1.30 | Worst max drawdown: -0.07% | Fees: $2.88
```

Four of the six never entered at all. The two that did (XRP, BNB) traded once and
twice respectively over the full year and lost, in every case, almost exactly
their own fees.

### Why: the entry gate sits above the market

Measured funding over the same 12 months (1,000 real Binance periods of 8 h):

| Asset | Mean funding | Yearly maximum | Periods above the 0.02%/8h gate |
|-------|--------------|----------------|--------------------------------|
| BTC | +3.38%/yr | 10.9%/yr | **0.0%** |
| ETH | +2.40%/yr | 10.9%/yr | **0.0%** |
| SOL | −1.82%/yr | 10.9%/yr | **0.0%** |
| AVAX | −0.87%/yr | 10.9%/yr | **0.0%** |
| XRP | +0.12%/yr | 47.7%/yr | 0.1% |
| BNB | +1.94%/yr | 23.0%/yr | 0.1% |

10.9%/yr is 0.01%/8h — Binance's **neutral** funding rate, where the market
settles whenever the perp trades at spot. BTC, ETH, SOL and AVAX essentially never
leave it. The entry gate (0.02%/8h = 21.9%/yr) is therefore **above the yearly
maximum of four of the six assets**, and is touched on roughly one period in a
thousand by the other two.

This is not specific to the six majors. Sweeping the whole configured universe
(77 assets, 74 with public history): **0 of the 69 assets that have a full year of
data reach the strategy's break-even.** The highest carry anywhere in the
universe is ASTER at 9.6%/yr.

### The rotation schedule, not the asset choice, is what kills it

| Policy | Fees per year | Break-even | Assets clearing it |
|--------|---------------|------------|--------------------|
| 30-day cycles (12 round trips) | 5.76% | 10.84%/yr | **0 of 69** |
| Static hold (1 round trip) | 0.48% | 5.00%/yr | 3 of 69 |

The same assets that lose money on a 30-day cycle are the best performers in the
universe if you simply hold them. The strategy's own exit schedule is what makes
it unprofitable.

### Timing the carry makes it worse

The obvious repair — “hold while trailing funding ≥ 5%/yr, flat otherwise” — was
tested with no look-ahead. It never beats a static hold on any asset:

| Asset | Funding, static hold | Best timing rule | Fees, static | Fees, rule |
|-------|----------------------|------------------|--------------|------------|
| ASTER | 9.27%/yr | 5.13%/yr | 0.24% | 1.20% |
| XPL | 6.69%/yr | 5.57%/yr | 0.24% | 1.20% |
| CELR | 5.93%/yr | 5.31%/yr | 0.24% | 0.24% |
| PUMP | 5.37%/yr | 4.28%/yr | 0.24% | 2.16% |

With short windows (3–14 days, what any live implementation would use) it is far
worse: PUMP loses **−14.8%/yr** across 41 round trips paying 19.9%/yr in fees.

A trailing average is a **lagging** signal — it enters after the spike has begun
and leaves at the first dip. Forgoing funding costs more (~6.4%/yr on ASTER) than
the staking earned while flat (~3.5%/yr). Holding, not timing, is the better rule
at every threshold tested.

### Cross-venue spreads

“Short the perp on the venue with the higher funding, long the other venue” was
measured on Binance, Bybit and OKX. Binance vs Bybit over a full year: **9 pairs,
0 with a stable sign** (best: XPL at +3.4%/yr but the sign flips on 35% of days).
Binance vs OKX cannot be settled from public data at all — OKX retains only three
months of funding history, and on those 96 shared days the average OKX-minus-
Binance spread is **+0.31%/yr** across nine assets, i.e. noise.

### The 3-year walk-forward

`backtest_walkforward.py --symbols ACTIVE --days 1300` — train 12 months, test 3,
step 3, parameters frozen, causal universe:

```
Traded windows  : 5/10 (50% coverage)
OOS median      : +0.022%/quarter  ~ +0.09%/yr
OOS worst/best  : -0.015% / +0.376%
Total Trading   : $54.99 over 3 years ($12,000 of capital)
Total Staking   : $629.50                      <- 11x the trading

BULL  : 2 windows, median +0.233%
RANGE : 3 windows, median -0.015%

Verdict: Paper trading only — OOS return +0.09%/yr below the hurdle (5%/yr)
```

Two things a reader should not skim past:

- **Half the windows never traded at all.** A window with zero trades proves
  nothing about the edge — it is not evidence of profitability, and the tool now
  reports it as 50% coverage rather than folding it into a "% positive" figure.
- **+0.09%/yr is ~55x below the hurdle.** The tool's own verdict logic reports
  `Paper trading only — OOS return +0.09%/yr below the hurdle (5%/yr)` instead of
  the "GO for real capital" it used to print for any positive median.

Only 2 of 10 windows fell in a BULL regime, and those carry the return (+0.233%
per quarter median). The strategy is a **regime bet**, not an all-weather one —
and even the bull quarters annualise to well under the 5% hurdle.

### Limits, stated plainly

- **Paper trading only.** No order routing, no exchange account, no keys. Fills
  are modelled, not observed.
- **The measured edge is ~1–3%/yr above the staking rate, at best.** The best
  result found anywhere in this work is a static, unmanaged basket of the four
  highest-carry assets: ~6.3%/yr against a 5%/yr staking benchmark — before
  basis, liquidation, venue and operational risk, none of which are modelled.
- **Regime-dependent.** BEAR markets are **untested** — no bear regime appears
  in the 2023–2026 sample. Conclusions do not extrapolate to one.
- **Few trades is not a sample.** 5 of 10 walk-forward windows traded; two of the
  six active assets traded once in a year. All performance figures are
  indicative, not statistically meaningful.
- **The entry gate is above the market it trades.** Not a bug, a calibration
  fact: 0 of 69 assets clear the strategy's break-even under its own 30-day
  rotation schedule.
- **The basis term is not reliably measurable from daily closes.** On thin
  alts a single bad bar manufactures a double-digit annual return (see §11). The
  backtests model the basis from daily closes, forward-filled onto funding
  timestamps; treat basis-sensitive results with suspicion.
- **Staking yield is an assumption** (5%/yr), not a realised return. It is
  reported separately for exactly this reason.
- **Counterparty / venue risk is not modelled.** If Binance halts withdrawals or
  the perp leg is force-closed, the hedge breaks.
- **Liquidation risk is approximated**, not simulated: the monitor uses a
  simplified maintenance-margin model. This matters most for the highest-carry
  assets, which are also the thinnest.
- **No rebalancing logic**: as the two legs drift, the position becomes
  slightly directional until closed.
- **`max_hold_days` drives the exits.** The zones are fractions of it (review at a
  quarter, derisk at half, forced close at the value itself), so it also sets the
  holding period the entry gate amortises its fees over. Before, the exits were
  hardcoded at 14/30/60 d and the key only affected the entry calculation.
- **`safety_cap` is far below the capital it allocates.** With `capital: 2000`
  and `fraction: 0.5`, sizes are capped at $100–400 — a 2–10% utilisation — which
  makes the fixed 48 bps round trip disproportionate.

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

**Why 6 majors and not 77?** `carry_scanner.py` returns **77 eligible Spot∩Perp
pairs** (filters: ≥ $5M 24h spot volume, ≥ $10M 24h perp volume, ≥ $2M open
interest). But alt funding is noisy and round-trips are expensive: a 24 h hold
pays 48 bps of fees against ~6 bps of funding. The universe was cut to assets
where liquidity and funding quality justify the fixed cost.

The full scan is kept in the config (disabled) so it can be re-enabled per asset
from the dashboard once its funding history justifies it.

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

- **The strategy is not profitable as configured.** 0 of 69 assets with a full
  year of history clear the break-even of a 30-day rotation. See §5.
- `capital_utilisation` is mislabelled: it counts periods where the NAV moved
  (`abs() > 1e-10`), not time spent in a position. An asset held 9% of the year
  reports 2.3% because its funding is zero on most periods.
- The no-trade diagnostic prints the funding of the period that produced the last
  rejection, not the maximum reached over the series.
- The API has no authentication. It is bound to loopback (`127.0.0.1:8000`, with
  nginx proxying `/api/`), so it is not reachable from outside the host — but
  anything that can already reach the host can call `POST /carry/run`,
  `POST /carry/reload-config` and `POST /dag/reset-kill-switch`. Add auth before
  putting it anywhere else.
- The exit zones scale with `max_hold_days`, but the *entry* gate's DERISK test
  uses the instantaneous funding rate of one period rather than its 7-day mean,
  so a single noisy period can close a position. The entry side already uses the
  mean; the exit should too.
- OKX publishes only ~3 months of public funding history, so no venue effect can
  be established against it without forward recording. A Binance↔OKX arbitrage
  scanner in this repository cannot be backtested.
- `PEPE`, `SHIB` and `BONK` return an empty funding history from the raw symbol;
  they need the `1000X` contract identifier (the backtester handles this, the
  scanners do not).
- The runtime config contains a non-ASCII symbol (`牛来/USDT`); it works, but it
  breaks any tooling that assumes ASCII tickers.
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
| 20 Sep 2026 | **The backtest had no clock.** `node.run()` received symbol/spot/funding/perp but no timestamp, while every time-based decision read `datetime.now()`. A 365-day backtest runs in ~5 real seconds, so `days_held` stayed at 0 | ZONE CLOSE (>60 d), ZONE DERISK (>30 d), the 72 h negative-funding timer and the anti-churn cooldown **could never fire**. Only the −5% basis stop could close anything. 14 of 18 positions were still open at day 343, and the reported "trading P&L" was unrealised funding on positions that were never closed: +$29.74 became **+$0.83** once exits worked, and a live Sharpe of +4.49 became **−0.33** | `_now()` in the node — returns the caller's simulated timestamp when one is injected, the wall clock otherwise. Injected by both backtesters. Proven by a deterministic harness that opens at T0 and advances in 5/20/35/65/90-day steps |
| 20 Sep 2026 | The backtest read the production database: `_last_close_age_hours()` and the anti-duplicate check both queried live `v4_trades` | A backtest could inherit a real cooldown, or be forced to `position_open=True` on an asset the live system happened to hold | Both guarded by `params["_backtest"]` |
| 20 Sep 2026 | Universe scan reported `BANK/USDT` at +44%/yr, driven by a perp/spot ratio reaching **3.29** | The gain came entirely from the basis term (+211%/yr), not funding, and the result swung from +218% to +11% between neighbouring parameters — one price dislocation, not an edge | Asset discarded. Lesson recorded: daily-close basis is untrustworthy on thin alts |
| 20 Sep 2026 | **Funding was only ever counted when positive.** The node accrued `funding_rate` inside an `elif funding_rate >= 0` branch; a negative period started the 72 h timer and added nothing | `trading_pnl = total_funding − total_fees` was systematically optimistic: the strategy could be *paying* funding and the books still showed a receipt | Funding is now signed. A negative period is a payment the book makes |
| 20 Sep 2026 | **The basis was never realised.** On close the node set `position_open = False` and `unrealized_pnl_pct` fell back to 0 without converting to cash | The entire P&L leg that a market-neutral book exists for — the spot/perp spread reconverging — was dropped at every close, in the live path as well as the backtest | `_realize_close()` realises the basis and charges the exit legs, **idempotently** (a `closed` flag), so a double call cannot double-count |
| 20 Sep 2026 | **Three exit branches closed the position before it could be realised.** The basis stop-loss and the two economic stops each set `position_open = False`, then the realise block tested `and self.state.position_open` | Every trade closed by a stop reported `realized = $0.00`. The accounting was right and unreachable | Those branches now only raise the signal; one block owns the close |
| 20 Sep 2026 | **The node and the backtest each had their own accounting.** The node charged entry legs on open; the backtest charged 24 bps per side on top and saturated funding with `max()` | Fees counted twice, funding unsigned, and no two reports agreed. A 90-day run decomposed to a residual that grew with the trade count | The node owns the accounting and consumers accumulate it. Verified: `trading_pnl == funding + basis_pnl − fees` exactly |
| 20 Sep 2026 | **The backtest read prices it could not have had.** Daily candles (index 00:00, `close` at 23:59) were forward-filled onto the 08:00 and 16:00 funding stamps | A decision taken at 08:00 read that day's closing price — 16 hours of look-ahead in every entry and every mark | 8h candles matching the funding period, index shifted one bar so a stamp only sees a closed bar; warm-up stamps with no known price are dropped rather than back-filled |
| 20 Sep 2026 | **The funding history was truncated to 333 days.** One call with `limit=1000` at three periods per day covers 333 days; a 3-year run fetched the same three years as a 1-year run | Every "3-year" walk-forward was a 333-day walk-forward repeated over 10 windows, and the report said otherwise | Paginated. The 3-year walk-forward now loads **3,915 periods per asset** (2023-02-23 → 2026-09-20) |
| 20 Sep 2026 | **`max_hold_days` set no holding period.** The exits were hardcoded at 14/30/60 days, so the parameter only affected the entry gate's fee amortisation | A grid search over the holding period varied the gate and never the exit it was named after. Setting it to 5 still held for 60 days | Zones scale from `max_hold_days`: forced exit at `max_hold_days`, derisk at half, review at a quarter |
| 20 Sep 2026 | **Walk-forward Sharpe and drawdown were literals.** `portfolio_sharpe=0.0, max_dd_pct=0.0` | Every window of every walk-forward report showed a Sharpe of zero and a drawdown of zero | Computed from the window's own equity curve |

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

MIT — see [`LICENSE`](LICENSE)

---

**Built by Jako · 2026** · https://atlastrader.org


