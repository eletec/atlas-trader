# Atlas Trader 🤖

> Autonomous AI trading system — **Multi-Asset Paper Trading** (BTC · ETH · SOL · XAU · XAG · WTI · EUR · GBP)  
> MiroFish Swarm · LangGraph Agents · HMM Market Regime · Kelly Sizing · Per-Asset Configuration

---

## Overview

**Atlas Trader** is a fully autonomous paper-trading system that combines multiple AI layers to generate high-conviction trading signals across **8 assets** (BTC/USDT · ETH/USDT · SOL/USDT · XAU/USD · XAG/USD · WTI/USD · EUR/USD · GBP/USD). Each asset runs its own independent configuration, risk profile, and regime monitoring.

The system runs on a **15-minute loop** by default:
1. Crawls the web to capture the *air du temps* (news, macro, social signals)
2. Simulates a **swarm of 5,000 agents** (MiroFish) to quantify sentiment
3. Runs a **LangGraph pipeline** of specialized LLM agents (technical, fundamental, sentiment, contrarian, debate)
4. Detects the **market regime** (HMM + ADX + DI±) to dynamically adapt weights
5. Computes a **composite score [0–100]** and decides BUY / SELL / HOLD
6. Manages **risk** (Kelly, ATR SL/TP, funding circuit breaker, MA50 filter)
7. Logs everything to SQLite and renders a real-time **Streamlit dashboard**

### Key Features

| Feature | Description |
|---------|-------------|
| 🧠 **Multi-agent LLM** | 7 specialized agents orchestrated by LangGraph |
| 🐟 **MiroFish Swarm** | 5,000 simulated agents, quantified sentiment score — **per-asset seed/air weights** |
| 📡 **Web Crawling** | Free DuckDuckGo + Tavily/Firecrawl, 10 themes × 10 pages — **per-asset templates** |
| 📊 **Market Regime** | HMM (hmmlearn) + ADX/DI± — 4 regimes: TRENDING/SIDEWAYS/HIGH_VOL — **per-asset cards** |
| 🥊 **Bull/Bear Debate** | Two parallel LLM calls debating bull vs bear thesis before synthesis |
| 🔗 **On-chain Metrics** | blockchain.info · mempool.space · CoinGecko (free APIs, no key) |
| ⚖️ **Risk Engine** | Fractional Kelly, dynamic sizing, 4 size multipliers — **per-asset thresholds** |
| 🛡️ **Circuit Breakers** | Funding rate (3 levels), max drawdown, gradual MA50 filter |
| 📈 **Dashboard** | Real-time Streamlit, per-asset regime cards, P&L, logs, 2FA Admin |
| 🧭 **Custom nav sidebar** | Fixed collapsible sidebar injected into DOM — asset nav (`_asset`) + admin nav (`_atab`), tooltip on collapse, localStorage state |
| 🎯 **Per-Asset Config** | Independent YAML per asset — risk, regime, MiroFish, scoring, agents, keywords |
| 🌐 **i18n** | Full UI in 8 languages: FR · EN · DE · ES · IT · PT · NL · ZH |
| 🐳 **Docker** | Supervisord multi-process, healthcheck, production-ready |
| 📉 **Backtesting** | Historical simulation with per-regime metrics, HMM 2 vs 3 states |
| 📊 **Agent Perf Stats** | Per-agent win rate, Brier score, P&L on BUY — admin dashboard tab |
| ⚖️ **Weighted agent scoring** | `weight_in_scoring` per agent is now **actually used** in the weighted mean (not just displayed) |
| 🤖 **Auto-tune weights** | PostMortem auto-adjusts `weight_in_scoring` per agent every 7 days |
| 🔍 **Meta-Analysis LLM** | Claude analyzes failure patterns, surfaces weak agents, gives ranked recommendations |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     INTELLIGENCE LAYER                          │
│  RSS & NewsAPI  ·  DuckDuckGo Crawler  ·  CCXT Market Data      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ AirDuTemps JSON (consolidated context)
┌──────────────────────────▼──────────────────────────────────────┐
│                    SIMULATION LAYER                             │
│        MiroFish Swarm — 5,000 agents · 100 steps                │
│        Sentiment score + narratives + probabilities             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                  LANGGRAPH AGENT PIPELINE                       │
│  ┌──────────────┐  ┌────────────────┐  ┌────────────────────┐   │
│  │ MarketData   │  │  Fundamental   │  │  XSentiment        │   │
│  │ OHLCV·RSI    │  │  on-chain+macro│  │  Twitter·Reddit    │   │
│  └──────┬───────┘  └───────┬────────┘  └─────────┬──────────┘   │
│         │         ┌────────┴────────┐            │              │
│         │         │  On-chain APIs  │            │              │
│         │         │  blockchain.info│            │              │
│         │         │  mempool.space  │            │              │
│         │         │  CoinGecko      │            │              │
│         │         └─────────────────┘            │              │
│  ┌──────▼──────────────────▼──────────────────────▼──────────┐  │
│  │  CoordinatorAgent (LLM Haiku, 30min cache)                │  │
│  │  → injects regime + DI± + per-regime weight multipliers   │  │
│  └──────────────────────────┬────────────────────────────────┘  │
│  ┌───────────────┐          │     ┌───────────────────────┐     │
│  │ Contrarian    │          │     │  MarketRegimeAgent    │     │
│  │ Fear & Greed  │          │     │  HMM + ADX + DI±      │     │
│  └──────┬────────┘          │     │  (info-only)          │     │
│         └───────────────────▼─────└───────────────────────┘     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  BullBearDebateAgent (optional, disabled by default)     │   │
│  │  BullDebater ‖ BearDebater — parallel LLM, 60s timeout   │   │
│  └──────────────────────────┬───────────────────────────────┘   │
│                    SynthesisAgent (LLM Sonnet)                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ score_breakdown JSON
┌──────────────────────────▼──────────────────────────────────────┐
│                   DECISION ENGINE                               │
│  Score Calculator [0–100]                                       │
│    MiroFish 12% · Market 40% · Agents LLM 30% · Contrarian 18%  │
│  ↓                                                              │
│  Decision Engine                                                │
│    BUY (score ≥ 62) · SELL (score < 52) · HOLD (otherwise)      │
│    + Filters: MA50 gradual · Funding CB · HIGH_VOL ×0.65        │
│  ↓                                                              │
│  Risk Engine → Kelly × conviction × ma50 × funding × high_vol   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                   EXECUTION LAYER                               │
│  Paper Trader (CCXT Binance testnet) · SQLite Logger            │
│  Post-Mortem Agent (+24h, walk-forward 7d) · Streamlit Dashboard│
└─────────────────────────────────────────────────────────────────┘
```

---

## LLM Agents (LangGraph)

| Agent | Role | Data |
|-------|------|------|
| `MarketDataAgent` | Technical analysis | OHLCV, RSI, MACD, ATR, Bollinger, funding rate |
| `FundamentalAgent` | On-chain & macro | Hashrate, active addresses, BTC dominance, macro |
| `XSentimentAgent` | Social sentiment | Twitter/X, Reddit, Fear & Greed Index |
| `ContrarianAgent` | Contrarian signal | Fear & Greed extremes, crowd positioning |
| `BullBearDebateAgent` | Structured debate | Parallel bull/bear LLM theses (optional) |
| `MarketRegimeAgent` | Regime detection | HMM (hmmlearn) + ADX/DI± vectorized |
| `SynthesisAgent` | Final synthesis | Aggregation + weighted scoring |
| `CoordinatorAgent` | Orchestration | Adaptive regime weights, 30min cache |
| `PostMortemAgent` | 24h feedback | Actual P&L vs prediction, walk-forward weight adjustment |
| `MetaAnalysisLLM` | Pattern detection | LLM analyzes losing trades to surface failure patterns + recommendations |

---

## MarketRegimeAgent — Regime Detection

Combines a **GaussianHMM** (hmmlearn) with deterministic ADX/DI/momentum features to classify the market into 4 regimes:

| Regime | Emoji | Agent Score | Coordinator Impact | Sizing |
|--------|-------|------------|---------------------|--------|
| `TRENDING_UP` | ▲ | 72 / BULLISH | timesfm×1.3, contrarian×1.2 | ×1.0 |
| `TRENDING_DOWN` | ▼ | 30 / BEARISH | contrarian×1.3, timesfm×0.7 | ×1.0 |
| `SIDEWAYS` | ↔ | 50 / NEUTRAL | fear_greed×1.3, timesfm×0.6 | ×1.0 |
| `HIGH_VOLATILITY` | ⚡ | 45 / NEUTRAL | contrarian×1.4, timesfm×0.4 | **×0.65** |

**Direction signals** (4 sources, threshold ≥2/4 for TRENDING):
- Momentum 20 candles (> ±1%)
- Momentum 50 candles (> ±2%)
- SMA20/SMA50 gap (> ±0.5%)
- **DI spread** DI+ − DI− (> ±5) ← primary direction source

**HMM feature note**: ADX in HMM features is computed using real highs/lows (not closes as a proxy). The final smooth step uses true EMA (alpha = 1/p) instead of Wilder SMMA, which would otherwise diverge to `p × DX` (e.g., 18 × 35 = 630 instead of 35).

---

## Risk Management

### Sizing formula
```
position_size = kelly_fraction
              × conviction_mult     (0.3 + 0.7 × |score-50|/50)
              × ma50_penalty        (1.0 or 0.5 if price < MA50)
              × funding_mult        (linear: 1.0 → 0.25 by funding rate)
              × high_vol_mult       (0.65 if regime = HIGH_VOLATILITY)
```

### Funding Rate Circuit Breaker

```
< 0.018%   : normal          → ×1.0
0.018–0.045%: warning         → linear reduction down to ×0.25
≥ 0.045%   : hard block       → BUY blocked (×0.0)
             (0.035% threshold if regime = HIGH_VOLATILITY)
< −0.025%  : negative funding → contrarian LONG bonus signal
```

Buffer: rolling average over 3 cycles (sustain), `deque(maxlen=8)`.

---

## Backtesting

```bash
# Standard (30 days, BTC/USDT, balanced)
python backtest.py

# With market regime overlay
python backtest.py --with-regime

# Test HMM 3 states (LOW/MED/HIGH volatility)
python backtest.py --with-regime --n-hmm-states 3

# Compare HMM 2 vs 3 states side-by-side
python backtest.py --compare-states

# Other options
python backtest.py --days 60 --tf 1h --mode aggressive --symbol ETH/USDT
```

Produces: total return %, Sharpe ratio, max drawdown, win rate, profit factor — with per-regime breakdown when `--with-regime` is active.

> **Note**: LLM/news scores are neutralized at 50 in backtests. Only the technical signal (RSI/MACD/ATR/MA50) is evaluated.

---

## Tech Stack

```
Python 3.11+
├── LangGraph 0.2+      — agent state machine orchestration
├── LangChain 0.3+      — LLM abstractions + tools
├── Anthropic SDK       — Claude 3.5 Sonnet/Haiku  (primary)
├── langchain-openai    — DeepSeek / GitHub Models / xAI (OpenAI-compatible)
├── Ollama              — local LLM (llama3, mistral…) — no API key needed
├── CCXT 4.x            — market data + paper trading (Binance testnet)
├── hmmlearn            — GaussianHMM for regime detection
├── Streamlit 1.35+     — real-time dashboard
├── SQLite              — decisions, logs, snapshots
├── PyYAML              — hot-reloadable configuration
└── Docker + supervisord — production deployment
```

---

## Installation

### Prerequisites
- Python 3.11+
- Binance testnet account (free)
- At least one LLM API key **or** a local Ollama instance
- Docker (for production deployment)

### Local Development

```bash
git clone https://github.com/eletec/atlas-trader.git
cd atlas-trader/zeitgeist-trader

pip install -r requirements.txt

cp .env.example .env
# Fill in your keys — see section below

# Run a single cycle (test)
python main.py --run-once

# Run as daemon loop
python main.py --daemon

# Start the dashboard
streamlit run dashboard/streamlit_app.py
```

### Environment Variables (`.env`)

```env
# Environment variables — COPY TO .env AND FILL IN
# NEVER COMMIT .env

# ---- LLM Providers (at least one required) ----
ANTHROPIC_API_KEY=sk-ant-...       # https://console.anthropic.com
DEEPSEEK_API_KEY=sk-...            # https://platform.deepseek.com  ← recommended (cheapest)
GITHUB_TOKEN=ghp_...               # https://github.com/settings/tokens (free GPT-4o access)
XAI_API_KEY=xai-...                # https://x.ai (Grok)
OPENAI_API_KEY=sk-...              # optional

# For local Ollama (no API key needed — set provider: ollama in settings.yaml)
# OLLAMA_BASE_URL=http://localhost:11434   # default, can be omitted

# ---- Web Crawling ----
TAVILY_API_KEY=tvly-...
FIRECRAWL_API_KEY=fc-...
SERPAPI_API_KEY=...

# ---- Exchange ----
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_TESTNET=true

# ---- News ----
NEWSAPI_KEY=

# ---- Notifications (optional) ----
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# ---- App ----
LOG_LEVEL=INFO
ENVIRONMENT=development
```

### LLM Provider Configuration

Edit `config/settings.yaml` to switch providers:

```yaml
llm:
  provider: "deepseek"        # anthropic | deepseek | github | xai | ollama
  model: "deepseek-chat"      # deepseek-chat | claude-3-5-sonnet-20241022 | gpt-4o | grok-beta | llama3
  temperature: 0.3
  max_tokens: 4096
```

> **Ollama (local, free)**: set `provider: ollama` and `model: llama3` (or any model you have pulled). No API key required. Requires a running `ollama serve` instance.

> **TimesFM price forecasting**: **disabled** (`timesfm.enabled: false`). Requires a modern GPU (RTX 3060+ / ≥12 GB VRAM). On CPU-only or Pascal-era GPUs (GTX 1050 Ti), the model times out at 180 s and delivers 0 % win-rate — leave disabled unless running on adequate hardware.

---

## Docker (Production)

```bash
# Build & run
docker compose up -d

# Deploy from Windows (syncs to remote host via SMB share):
.\deploy.ps1

# On the container host:
docker exec atlas-trader-app supervisorctl -s unix:///tmp/supervisor.sock restart trader
docker exec atlas-trader-app supervisorctl -s unix:///tmp/supervisor.sock status
docker logs atlas-trader-app --tail 80 -f
```

`supervisord` runs three processes:
- `trader` — `python main.py --daemon` (15min loop, per-asset parallel execution)
- `dashboard` — `streamlit run dashboard/streamlit_app.py --server.port 8501`
- `watchdog` — shell script that monitors `/tmp/atlas_heartbeat`; restarts `trader` after 30 min stale + sends `SIGUSR1` for a stack dump before restart

All three restart automatically (`startretries=100`).

> **Hardware requirements**: i7 CPU + 16 GB RAM minimum. TimesFM is disabled by default (requires RTX 3060+ / ≥12 GB VRAM). All other agents run on CPU only.

---

## Configuration

Atlas Trader uses a **two-layer config system**:

- `config/settings.yaml` — global defaults (LLM provider, loop interval, global risk, agents)
- `config/assets/{slug}.yaml` — **per-asset overrides** (`BTC_USDT.yaml`, `ETH_USDT.yaml`, `XAU_USD.yaml`, `EUR_USD.yaml`, `GBP_USD.yaml`)

Per-asset files deep-merge over the global defaults. If an asset key is absent, the global value applies. All parameters are editable live via the **Admin interface → 🎯 Par Actif** tab.

### `config/settings.yaml` (global defaults)

```yaml
project:
  active_assets:
    - "BTC/USDT"
    - "ETH/USDT"
    - "SOL/USDT"
    - "XAU/USD"
    - "XAG/USD"
    - "WTI/USD"
    - "EUR/USD"
    - "GBP/USD"
  loop_interval_seconds: 900    # 15 min

scoring:
  weights:
    mirofish: 0.12              # reduced (degraded simulator)
    market: 0.40
    agents: 0.30                # LLM agents increased
    contrarian: 0.18            # contrarian signal reinforced

risk:
  mode: balanced                 # conservative | balanced | aggressive
  buy_threshold: 62
  exit_threshold: 52
  kelly_max_fraction: 0.25
  position_size_pct: 5.0
  max_open_positions: 3
  ma50_filter_mode: gradual

circuit_breaker:
  funding_block: 0.00045         # 0.045%
  sustain_period_cycles: 3

market_regime:
  adx_period: 18                 # recommended for BTC 15min
  vol_window: 30
  n_hmm_states: 2                # 3 = LOW/MED/HIGH via --n-hmm-states 3 in backtest

post_mortem:
  walk_forward_days: 7           # weight adjustment at most once per week
  correlation_threshold: 0.75    # reduce weight of correlated agents

agents:
  bull_bear_debate:
    enabled: false               # enable for narrative-enriched synthesis
```

### `config/assets/BTC_USDT.yaml` (per-asset example)

```yaml
risk:
  buy_threshold: 62
  exit_threshold: 52
  kelly_max_fraction: 0.25
  ma50_filter_mode: gradual

market_regime:
  adx_period: 18
  vol_window: 30

mirofish:
  seed_news_weight: 0.70          # weight of fresh news in MiroFish swarm
  air_du_temps_weight: 0.30       # weight of ambient context

news:
  keywords:
    - "bitcoin"
    - "BTC"
    - "crypto"
  x_keywords:
    - "bitcoin"
    - "BTC"
    - "halving"
    - "whale"
```

---

## Dashboard

The Streamlit dashboard (`http://localhost:8501`) provides:

**Navigation** — custom fixed sidebar (`<div id="atlas-sidenav">`) injected directly into `document.body` of the Streamlit parent frame:
- **Front**: asset selector (🌐 Global · ₿ BTC · ⟠ ETH · ◎ SOL · … ) — navigates via `?_asset=BTC_USDT`
- **Admin**: 15-section panel — navigates via `?admin=1&_atab=llm`
- Collapsible (☰ toggle), state in `localStorage['atlas_nav_c']`; tooltips when collapsed
- `position: fixed`, `z-index: 100`, top aligned dynamically below Streamlit header (60 px min fallback, `ResizeObserver` refresh)
- Width: 180 px expanded · 44 px collapsed

**User view (read-only)**
- Composite score + current decision
- Market regime badge:
  - Emoji · regime · HMM probability
  - ADX · DI+ / DI− · direction pressure
  - Relative & annualized volatility
  - HMM posteriors (Low-vol / High-vol)
  - Last 5 cycles history
- **Dernière décision IA + Agent Scores History chart** — side-by-side two-column layout per asset tab:
  - Left: last decision (action badge, score, LLM explanation, score breakdown)
  - Right: multi-line Plotly chart — one line per agent + bold global score line
    - Dashed thresholds at BUY≥62 and EXIT<52
    - BUY/SELL triangle markers on the global score line
    - Time window radio: 24h / 48h / 7j / 30j (X axis forced to selected range)
- Paper P&L + performance curve
- Real-time log stream (last 50 lines)
- **"Force Run" button** — runs a full cycle on demand in a background thread (non-blocking); streams live per-step logs into the dialog at 0.5 s intervals without disconnecting the WebSocket

**Admin view (2FA protected)**
- Navigation via the same custom sidebar (15 sections: ⚙ LLM · ⛏ Crawler · ◈ News · ⊛ Sources · ◇ MiroFish · ⚖ Risk · ⬡ Agents · ≡ Logging · ⏱ TimesFM · 📊 Agents Perf · 🔍 Méta-Analyse · ⊞ Market Regime · ⇄ Flux · 👤 Users · 🌐 Par Actif)
- All `settings.yaml` parameters editable inline
- **🌐 Par Actif** — per-asset configuration panel with tabs (₿ BTC · ⟠ ETH · ◎ XAU · € EUR · £ GBP):
  - Général & scoring weights
  - Risk & Seuils (buy/exit thresholds, Kelly, MA50 mode, drawdown)
  - Circuit Breaker (funding levels, HIGH_VOL CB threshold)
  - Agents (per-agent toggles, keywords injected into LLM context)
  - Market Regime (ADX period, vol window, HMM states)
  - **🐟 MiroFish** — `seed_news_weight` / `air_du_temps_weight` per asset
  - Crawler templates per asset
- **📰 News / 🕷 Crawler / 📡 Sources** — tabbed interface per asset (no more selectbox)
  - Sources: RSS feeds, Nitter, Reddit, **CryptoPanic toggle** (BTC/ETH only)
  - News: keywords per asset (used in fetching + X Sentiment LLM context)
- **📊 Market Regime** — 5 per-asset cards showing: regime, HMM%, direction pressure, ADX+DI±, vol (relative + annualized), HMM posteriors, last 5 cycles history with %
- Per-agent enable/disable toggles
- LLM cost monitoring (tokens/cycle)
- **Exchange settings**: paper capital (`paper_capital_usd`) and testnet toggle
- **LLM sandbox**: run an ad-hoc prompt against the configured provider directly from the Admin UI
- User management (roles, password reset, 2FA reset)
- **Fully localized** in 8 languages (FR · EN · DE · ES · IT · PT · NL · ZH), including all tooltips, info banners, and the hamburger menu

> **Internationalization**: the entire UI (nav bar, hamburger menu, Admin tabs with info texts and help tooltips, Users panel) is rendered through `utils/i18n.py` — a key → 8-language dict. Language is switched via the hamburger menu and persisted as a URL query param.

---

## Project Structure

```
zeitgeist-trader/
├── main.py                      # Entry point + main loop
├── decision_engine.py           # Score Calculator + Decision + Risk Engine
├── backtest.py                  # Historical backtesting engine
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
│
├── agents/
│   ├── market_data_agent.py         # Technical indicators + funding CB
│   ├── fundamental_agent.py         # On-chain (blockchain.info/mempool/CoinGecko) + macro
│   ├── x_sentiment_agent.py         # Social sentiment
│   ├── contrarian_agent.py          # Fear & Greed contrarian
│   ├── bull_bear_debate_agent.py    # Parallel bull/bear LLM debate (optional)
│   ├── market_regime_agent.py       # HMM + ADX/DI± regime detection
│   ├── synthesis_agent.py           # Final LLM aggregation
│   ├── broad_web_crawler.py         # Multi-source crawler
│   ├── fast_news_listener.py        # RSS + NewsAPI
│   ├── air_du_temps_builder.py      # Context consolidation
│   └── post_mortem_agent.py         # 24h feedback + walk-forward weight tuning
│
├── graph/
│   └── workflow.py                  # LangGraph state machine
│
├── execution/
│   └── paper_trader.py              # CCXT Binance testnet
│
├── storage/
│   ├── database.py                  # SQLite (decisions + logs)
│   └── pm_state.json                # Post-mortem walk-forward state
│
├── dashboard/
│   ├── streamlit_app.py             # Main UI
│   └── flux_manager.py              # Real-time flux management
│
├── mirofish/
│   └── core.py                      # Swarm simulation wrapper
│
├── config/
│   ├── settings.yaml                # Global configuration (defaults for all assets)
│   ├── prompts.yaml                 # LLM prompt templates
│   └── assets/                      # Per-asset overrides (deep-merged over settings.yaml)
│       ├── BTC_USDT.yaml
│       ├── ETH_USDT.yaml
│       ├── XAU_USD.yaml
│       ├── EUR_USD.yaml
│       └── GBP_USD.yaml
│
└── utils/
    ├── config.py                    # Config loading + validation
    ├── logger.py                    # Structured logging
    └── i18n.py                      # UI internationalization — 8 languages (FR/EN/DE/ES/IT/PT/NL/ZH)
```

---

## Data Model

### `score_breakdown` (persisted in SQLite)

```json
{
  "mirofish_score": 62.0,
  "market_score": 71.0,
  "contrarian_score": 45.0,
  "regime": "TRENDING_UP",
  "hmm_prob": 0.83,
  "hmm_posteriors": { "state_0": 0.17, "state_1": 0.83 },
  "direction_pressure": "Strong bullish pressure",
  "regime_features": {
    "adx": 22.4,
    "di_plus": 31.2,
    "di_minus": 18.7,
    "rel_volatility": 1.12,
    "vol_abs_annualized": 68.5
  }
}
```

### `decision` returned by DecisionEngine

```json
{
  "action": "BUY",
  "score": 64.2,
  "position_size_usd": 284.0,
  "entry_price": 84200.0,
  "sl_price": 82100.0,
  "tp_price": 87300.0,
  "funding_size_mult": 0.72,
  "high_vol_size_mult": 1.0
}
```

---

## Status & Roadmap

### MVP v1.0 (current)
- [x] **Watchdog** — supervisord process monitors heartbeat file, auto-restarts trader after 30 min stale + SIGUSR1 stack dump
- [x] **Force Run non-blocking** — background thread + `queue.Queue` polling; live log stream, no Streamlit WebSocket timeout
- [x] **CCXT connection leak fix** — `MarketDataAgent` singleton in monitor loop (was re-instantiated every 60 s → socket exhaustion after ~1–2 h)
- [x] **feedparser timeout** — `urllib.urlopen(timeout=15)` wrapper before `feedparser.parse()` (Nitter/Reddit could block indefinitely)
- [x] Complete LangGraph pipeline
- [x] MiroFish swarm integration
- [x] MarketRegimeAgent (HMM + ADX/DI±) — fixed ADX computation (EMA not SMMA for final step)
- [x] Funding rate circuit breaker (3 levels)
- [x] Kelly sizing with 4 multipliers
- [x] Streamlit dashboard with real-time regime badge
- [x] Post-mortem agent +24h with walk-forward (7-day) weight adjustment
- [x] Agent correlation check (Pearson r > 0.75 → reduce redundant agent weight)
- [x] BullBearDebateAgent (optional — parallel bull/bear LLM theses)
- [x] On-chain metrics in FundamentalAgent (blockchain.info, mempool.space, CoinGecko)
- [x] Backtesting engine with per-regime metrics + HMM 2 vs 3 states comparison
- [x] Docker + supervisord
- [x] Admin UI: paper capital + testnet toggle + live `fetch_balance()` in portfolio
  - [x] TimesFM price forecasting — **disabled** (GTX 1050 Ti / Pascal GPU incompatible; re-enable with `backend: gpu` on RTX 3060+)
- [x] Full UI internationalization — 8 languages (hamburger, all Admin tabs + tooltips, users panel)
- [x] LLM sandbox in Admin (ad-hoc prompt → configured provider)
- [x] Flux Manager fully localized (all 6 tabs: Status Board, Pipeline, Controls, Metrics, Logs, Alerts)
- [x] Flux Manager pipeline diagram — native Graphviz (no CDN, works offline/NAS)
- [x] Flux controls redesigned as table layout (name · description · toggle · force-restart per category)
- [x] Tooltip `?` buttons — unified design across all themes (dark/light/system), consistent rendering (circle + glyph)
- [x] Flux Manager pipeline diagram — all agents shown (FearGreed + Polymarket nodes)
- [x] Flux Manager selectboxes → radio horizontal (status window, metric period, log filter)
- [x] **Agent Scores History chart** — per-asset tab, right of Dernière décision IA
  - Plotly multi-line (one line/agent + global), dashed BUY/EXIT thresholds, BUY/SELL markers
  - Time window radio: 24h / 48h / 7j / 30j with forced X-axis range

### v1.1 (in progress — April 2026)
- [x] **Weighted agent scoring** — `weight_in_scoring` per agent now applied as true weighted mean in `ScoreCalculator`
- [x] **Agent weight recalibration** — fear_greed 0.85→0.10, x_sentiment 0.70→0.10, market_regime 0.00→0.40, fundamental 0.80→0.40 (based on Brier scores)
- [x] **TimesFM disabled** — WR=0%, GTX 1050 Ti incompatible; re-enable on RTX 3060+ (`backend: gpu`)
- [x] **trend_4h filter** — ±8 pts in `_derive_market_score()` — avoids BUY during 4h downtrend
- [x] **buy_threshold raised** — ETH/SOL 60→63, forex/commodities 57-58→61 (reduces crash trades)
- [x] **Inter-asset SELL bug fixed** — `DecisionEngine._open_buys` now filtered by `self._asset`
- [x] **Session label fix** — XAU/XAG 0-7h UTC shows 🌙 calme (not ⚫ hors session)
- [x] **Dashboard: trades after last_decision** — reordered per-asset tab layout
- [x] **Dashboard: sortable global trades table** — HTML+JS clickable headers in Vue globale
- [x] **Custom DOM sidebar nav** — `_inject_custom_sidenav()` in `dashboard/multi_asset.py` replaces Streamlit native sidebar (localStorage persistence issue) and horizontal `st.tabs` in admin; fixed collapsible, tooltips, header-aware positioning
- [x] **Admin nav refactor** — `render_admin_panel()` uses `_inject_custom_sidenav` with 15 sections + `_atab` query param; `st.tabs` removed
- [ ] Polymarket smart money integration
- [ ] Telegram / Discord alerts
- [ ] Graph B: score distribution histogram per agent (per-asset)
- [ ] Graph C: correlation heatmap between agents

### v2.0 (future)
- [ ] Live trading (CCXT production, strict risk)
- [ ] Historical P&L fine-tuning of scoring model
- [ ] Cross-exchange arbitrage

---

## Security

- API keys exclusively in `.env` (never committed, `.gitignore`)
- Admin panel uses 2FA — credentials managed in dashboard user interface
- Crawler inputs sanitized before LLM injection (anti prompt-injection)
- OHLCV validation on CCXT side
- Strict timeout + domain whitelist on crawls

---

## License

Private project — internal use only.

---

*Built with 🤖 LangGraph · MiroFish · Claude · Streamlit*

