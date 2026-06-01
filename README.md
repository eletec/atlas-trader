# Atlas Trader 🤖

> Autonomous AI trading system — **10 Binance Crypto Perps** (BTC · ETH · SOL · BNB · XRP · ADA · DOGE · AVAX · LINK · DOT)  
> V3 Quant Engine · HMM Regime · LogReg Signal · ATR Risk · Per-Asset Config · 8-language i18n

> **Research verdict (June 2026)** : 15 phases · 374 configs tested · **0 robust edge** on public OHLCV data at retail costs.  
> See [`RESEARCH_HISTORY.md`](RESEARCH_HISTORY.md) for the full development & research chronicle.  
> See [`PHASES_0_13_FINAL_REPORT.md`](PHASES_0_13_FINAL_REPORT.md) for the quantitative research final report.

---

## What it does

Atlas Trader runs a **pure-quant pipeline** every ~5 minutes on each of 10 Binance USDT perpetuals. For each asset, independently:

1. **Fetches** OHLCV 5m (90 days) + 1h (100 days) from Binance via ccxt, cached as parquet
2. **Computes** 20+ causal features (returns, RSI, MACD, ADX, BB%b, VWAP, ATR, OBV...)
3. **Detects regime** with a 3-state GaussianHMM (TREND / RANGE / PANIC) — fallback to ADX threshold
4. **Predicts direction** with a calibrated LogisticRegression (P(up) over 48-bar horizon = 4h)
5. **Decides** LONG / SHORT / FLAT using P(up) thresholds + regime gate + 1h trend filter + correlation veto
6. **Sizes position** with ATR-based SL x2 / TP x4 (R:R = 2.0) using ATR from the 1h timeframe
7. **Persists** everything to SQLite and displays it on a real-time Streamlit dashboard

---

## Assets

| Asset | Paper capital | Fraction | Notes |
|---|---|---|---|
| BTC/USDT | $10 000 | 0.50% | Highest liquidity, benchmark |
| ETH/USDT | $5 000 | 0.45% | Second tier |
| SOL/USDT | $5 000 | 0.35% | Higher vol — smaller fraction |
| BNB/USDT | $3 000 | 0.50% | Stable funding cycles |
| XRP/USDT | $3 000 | 0.50% | Frequent TREND regime |
| ADA/USDT | $2 000 | 0.45% | Lower vol |
| DOGE/USDT | $2 000 | 0.40% | Meme — high dead-zone rate |
| AVAX/USDT | $2 000 | 0.50% | Alt-L1, correlated to SOL |
| LINK/USDT | $2 000 | 0.50% | Oracle, frequent RANGE |
| DOT/USDT | $2 000 | 0.45% | Low on-chain activity |

---

## Architecture

```
+------------------------------------------------------------------+
|  DATA LAYER                                                      |
|  ccxt Binance USDM — OHLCV 5m (90d) + 1h (100d)                 |
|  Parquet cache (quant/data_loader.py)                            |
+---------------------------+--------------------------------------+
                            |  DataFrame OHLCV
+---------------------------v--------------------------------------+
|  FEATURE PIPELINE  (quant/features.py + normalization.py)        |
|  log_return_1/4/24/96 · rsi_14 · macd_hist · ema_cross           |
|  atr_14 · atr_pct · adx_14 · dist_ma50 · roc_12                  |
|  volume_z_20 · vol_of_vol_20 · vwap_dist_20 · bb_pct_b           |
|  obv_proxy_20 · Donchian(shift-1) · funding z-score (opt.)       |
|  -> quantile-normalised variants (*_q)                           |
+---------------------------+--------------------------------------+
                            |  feats_all DataFrame
+---------------------------v--------------------------------------+
|  REGIME DETECTOR  (quant/regime.py)                              |
|  GaussianHMM 3 states -> TREND / RANGE / PANIC                   |
|  Fallback: ADX > threshold & vol_of_vol < threshold              |
+------+-----------------------------------------------------------+
       |  regime in {1.0=TREND, 0.5=RANGE, 0.0=PANIC}
+------v-----------------------------------------------------------+
|  SIGNAL MODEL  (quant/signal_model.py)                           |
|  LogisticRegression + optional Platt calibration                 |
|  Target: price direction in 48 bars (4h horizon)                 |
|  Output: P(up) in [0.0, 1.0]                                     |
+------+-----------------------------------------------------------+
       |  prob_up
+------v-----------------------------------------------------------+
|  STRATEGY  (quant/strategy.py)                                   |
|  TREND regime:  LONG if P(up) > 0.55 / SHORT if P(up) < 0.45    |
|  RANGE regime:  mean-revert via BB%b + VWAP (if range_enabled)   |
|  PANIC regime:  FLAT always                                      |
|  + 1h filter:   LONG veto if SMA20_1h < SMA50_1h                 |
|  + corr filter: veto if >=3 correlated positions same direction  |
|  + vol filter:  veto if volume < 70% of 20-bar median            |
+------+-----------------------------------------------------------+
       |  action in {LONG, SHORT, FLAT}
+------v-----------------------------------------------------------+
|  RISK ENGINE  (execution/risk_manager.py)                        |
|  ATR source: 1h candles (coherent with 4h horizon)               |
|  SL = entry +/- 2.0 x ATR_1h                                     |
|  TP = entry +/- 4.0 x ATR_1h    (R:R = 2.0)                      |
|  Size = fraction x capital / entry_price                         |
|  Trailing stop + time-exit (8 bars in loss)                      |
+------+-----------------------------------------------------------+
       |
+------v-----------------------------------------------------------+
|  PAPER TRADER  (execution/paper_trader.py)                       |
|  SQLite persist -> v2_equity · v2_state · v2_decisions           |
|  Streamlit dashboard (real-time)                                 |
+------------------------------------------------------------------+
```

---

## V3 parameters

```yaml
# config/settings.gx10.yaml
quant:
  horizon_bars: 48          # 48 x 5m = 4h prediction horizon
  history_days: 90          # 90d of 5m OHLCV for training
  train_fraction: 0.70      # 70% train / 30% test
  p_up_threshold: 0.55      # LONG trigger
  p_dn_threshold: 0.45      # SHORT trigger
  use_hmm: true             # GaussianHMM 3-state active
  signal_model_calibrate: true

# config/assets/*.yaml  (per asset, example: BTC_USDT.yaml)
asset: BTC/USDT
timeframe: 5m
paper_capital_usd: 10000
testnet: true
v2_risk:
  stop_loss_atr_mult:   2.0    # SL = 2x ATR_1h
  take_profit_atr_mult: 4.0    # TP = 4x ATR_1h
  fraction_per_trade:   0.0050
```

---

## Key design decisions

| Decision | Rationale |
|---|---|
| ATR from 1h, not 5m | Prediction horizon = 4h — SL/TP must scale to 4h volatility |
| TP x4 (R:R = 2.0) | Below 2.0, retail fees + false-signal rate make positive EV impossible |
| 3-state HMM (TREND/RANGE/PANIC) | Enables distinct strategy per regime (trend-following vs mean-revert vs full-flat) |
| 1h SMA20/50 veto | Eliminates counter-trend entries — consensus DeepSeek + GPT + Grok audit |
| Correlation veto (max 3 same-dir) | 10 perps are 0.80+ correlated — 4+ same-direction = undiversified concentration |
| Conservative fractions (0.35-0.50%) | Paper capital $2k-$10k per asset — small sizes preserve capital for research |
| All-crypto, all-Binance | Homogeneous data, consistent funding, single API — eliminates multi-exchange complexity |

---

## Dashboard

Streamlit dashboard at `http://localhost:8501` (or `https://atlastrader.org` on GX10).

**Public view**: asset selector sidebar · live regime badge (TREND/RANGE/PANIC) · P(up) · current decision · P&L · trade history · logs

**Admin view** (`?admin=1`, 2FA protected): 15-section panel
- **Quant Engine** — pipeline parameters (horizon, history, thresholds, HMM, refit interval)
- **Risk** — SL/TP multipliers, fraction, capital per asset
- **Per Asset** — full per-asset YAML editor (timeframe, capital, v2_risk, paper trading config)
- **Flux Manager** — real-time supervision of pipeline stages with status / latency / logs
- **Backup / Restore** — full config snapshot (all 10 assets + global settings)
- **Reset** — partial (equity+state) / full (all tables) / daemon restart
- **Users** — role management, password reset, 2FA

Language switcher: FR · EN · DE · ES · IT · PT · NL · ZH (590+ translated keys, `utils/i18n.py`).

---

## Tech stack

| Layer | Technology |
|---|---|
| Market data | ccxt 4.x (Binance USDM, WebSocket) |
| Features | numpy / pandas (fully causal, shift-1) |
| Regime detection | hmmlearn GaussianHMM |
| Signal model | scikit-learn LogisticRegression + CalibratedClassifierCV |
| Dashboard | Streamlit 1.35+ |
| Storage | SQLite (decisions · equity · state) |
| Config | PyYAML hot-reloadable |
| Deployment | Docker + supervisord |
| OS / hardware | Ubuntu 22.04, i7, 16 GB RAM (GX10) |

---

## Installation

### Local development

```bash
git clone https://github.com/eletec/atlas-trader.git
cd atlas-trader/zeitgeist-trader

pip install -r requirements.txt

cp .env.example .env
# Fill in: BINANCE_API_KEY, BINANCE_API_SECRET (testnet recommended)

# Single cycle test
python run_v2.py --run-once

# Start dashboard only
streamlit run dashboard/streamlit_app.py
```

### Environment variables (`.env`)

```env
# Exchange (Binance testnet — paper trading only)
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_TESTNET=true

# Optional: alternative data provider
TWELVEDATA_API_KEY=

# Dashboard admin
ATLAS_ADMIN_PASSWORD=changeme
```

### Docker (production — GX10)

```bash
docker compose -f docker-compose.gx10.yml up -d

# Restart trader after config change
docker exec atlas-trader-app supervisorctl -s unix:///tmp/supervisor.sock restart trader

# Logs
docker logs atlas-trader-app --tail 80 -f
```

`supervisord` manages two processes: `trader` (main loop) and `dashboard` (Streamlit).

---

## Project structure

```
zeitgeist-trader/
+-- main.py                    # Orchestrator — schedules all 10 asset runners
+-- run_v2.py                  # V3 live runner entry point
|
+-- graph/
|   +-- workflow.py            # LiveRunner class — per-asset cycle logic
|
+-- quant/
|   +-- data_loader.py         # OHLCV fetch + parquet cache
|   +-- features.py            # 20+ causal feature computation
|   +-- normalization.py       # Quantile normalisation
|   +-- regime.py              # RegimeDetector (HMM + fallback)
|   +-- signal_model.py        # SignalModel (LogReg + calibration)
|   +-- strategy.py            # decide() — LONG/SHORT/FLAT logic
|   +-- pipeline.py            # PipelineConfig dataclass
|   +-- config.py              # Quant config helpers
|
+-- execution/
|   +-- paper_trader.py        # Paper trade execution + SQLite persist
|   +-- risk_manager.py        # Position sizing, SL/TP, trailing stop
|
+-- dashboard/
|   +-- streamlit_app.py       # Main UI (public + admin)
|   +-- flux_manager.py        # Flux Manager tab
|   +-- multi_asset.py         # Per-asset config editor
|   +-- auth.py                # 2FA + session management
|
+-- utils/
|   +-- i18n.py                # 590+ keys, 8 languages
|   +-- config.py              # Settings loader
|   +-- logger.py              # Structured logging
|
+-- config/
|   +-- settings.yaml          # Global defaults
|   +-- settings.gx10.yaml     # Production overrides (GX10)
|   +-- assets/                # Per-asset YAML (10 files)
|       +-- BTC_USDT.yaml
|       +-- ETH_USDT.yaml
|       +-- ...
|
+-- storage/
|   +-- zeitgeist.db           # SQLite — v2_equity · v2_state · v2_decisions
|
+-- Dockerfile
+-- docker-compose.yml
+-- docker-compose.gx10.yml
+-- requirements.txt
|
+-- RESEARCH_HISTORY.md        # Full V1->V3 development chronicle
+-- PHASES_0_13_FINAL_REPORT.md  # Quant research final report (15 phases)
```

---

## Typical log output

```
[INFO] LiveRunner refit — fetch 90d BTC/USDT 5m
[INFO] Cache hit: BTCUSDT_5m_90d.parquet (25920 candles)
[INFO] Fallback threshold: adx>37.89 & vov<0.0562 chaos>0.0681
[INFO] SignalModel sklearn fit OK on 9504 samples.
[INFO] 1h data loaded: 2400 bars
[INFO] Refit OK — 18144 bars train | 7776 test
[INFO] [config] BTC/USDT v2_risk override: SL×2.0 TP×4.0 f=0.0050
[INFO] [state] BTC/USDT capital restored from DB: 10000.00$
[INFO] [V2] 2026-06-01 14:30 | PANIC | P(up)=0.558 | FLAT(regime_not_trending) | capital=10000$ | 72366ms
```

**Decision reasons** (FLAT):
- `regime_not_trending` — HMM/ADX says RANGE or PANIC
- `dead_zone` — P(up) in [0.45, 0.55], no conviction
- `panic_veto` — regime = PANIC, all signals blocked
- `1h_trend_veto` — 1h SMA20 < SMA50, contra-trend entry blocked
- `corr_veto` — 3+ correlated positions already open in same direction
- `low_volume` — bar volume < 70% of 20-bar median

---

## Research history

**15 phases of systematic quantitative research** (Jan–Jun 2026) tested 374 configurations across 10 Binance perps, 3 years of data, with a sacrosanct 90-day holdout frozen from Phase 0.

**Verdict**: no strategy survived the filter `{IS Sharpe > 1.0, OOS Sharpe > 0.5, annualized > 2%}` at retail costs (5 bps/side perp).

Root causes: retail competition lag behind HFT/market-makers, insufficient statistical power (3 years ~= 5-15% power to detect Sharpe 0.5), transaction costs exceeding available edges on public OHLCV data.

See [`RESEARCH_HISTORY.md`](RESEARCH_HISTORY.md) and [`PHASES_0_13_FINAL_REPORT.md`](PHASES_0_13_FINAL_REPORT.md) for the full analysis.

---

## Security

- API keys exclusively in `.env` (never committed, `.gitignore`)
- Admin panel uses 2FA — credentials managed in dashboard user interface
- Testnet active by default (`testnet: true` in all asset configs)
- OHLCV validation on CCXT side

---

## License

Private project — internal use only.

---

*Branch `v3-regime-expert` · Repository `eletec/atlas-trader` · June 2026*