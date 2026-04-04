# Atlas Trader 🤖

> Système de trading IA autonome — Paper Trading BTC/USDT  
> MiroFish Swarm · LangGraph Agents · HMM Market Regime · Kelly Sizing

---

## Vue d'ensemble

**Atlas Trader** est un système de paper-trading entièrement autonome qui combine plusieurs couches d'intelligence artificielle pour générer des signaux de trading à haute conviction sur BTC/USDT (Binance testnet).

Le système fonctionne en boucle de **15 minutes** par défaut :
1. Crawle le web pour capter l'*air du temps* (news, macro, social)
2. Simule un **swarm de 5 000 agents** (MiroFish) pour quantifier le sentiment
3. Lance un **pipeline LangGraph** d'agents LLM spécialisés (technique, fondamental, sentiment, contrarian)
4. Détecte le **régime de marché** (HMM + ADX + DI±) pour adapter les poids dynamiquement
5. Calcule un **score composite [0–100]** et décide BUY / SELL / HOLD
6. Gère le **risk management** (Kelly, ATR SL/TP, funding circuit breaker, MA50 filter)
7. Enregistre tout dans SQLite et affiche en temps réel sur un **dashboard Streamlit**

### Caractéristiques clés

| Feature | Description |
|---------|-------------|
| 🧠 **Multi-agent LLM** | 6 agents spécialisés orchestrés par LangGraph |
| 🐟 **MiroFish Swarm** | 5 000 agents simulés, score sentiment quantifié |
| 📡 **Web Crawling** | DuckDuckGo gratuit + Tavily/Firecrawl, 10 thèmes × 10 pages |
| 📊 **Market Regime** | HMM (hmmlearn) + ADX/DI± — 4 régimes : TRENDING/SIDEWAYS/HIGH_VOL |
| ⚖️ **Risk Engine** | Kelly fractionnel, sizing dynamique, 4 multiplicateurs de taille |
| 🛡️ **Circuit Breakers** | Funding rate (3 niveaux), drawdown max, filtre MA50 graduel |
| 📈 **Dashboard** | Streamlit temps réel, badge régime, P&L, logs, Admin protégé |
| 🐳 **Docker** | Supervisord multi-process, healthcheck, NAS-ready |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     INTELLIGENCE LAYER                          │
│  RSS & NewsAPI  ·  DuckDuckGo Crawler  ·  CCXT Market Data     │
└──────────────────────────┬──────────────────────────────────────┘
                           │ AirDuTemps JSON (contexte consolidé)
┌──────────────────────────▼──────────────────────────────────────┐
│                    SIMULATION LAYER                             │
│        MiroFish Swarm — 5 000 agents · 100 steps               │
│        Score sentiment + narratives + probabilités              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                  LANGGRAPH AGENT PIPELINE                       │
│  ┌──────────────┐  ┌────────────────┐  ┌────────────────────┐   │
│  │ MarketData   │  │  Fundamental   │  │  XSentiment        │   │
│  │ OHLCV·RSI    │  │  on-chain·macro│  │  Twitter·Reddit    │   │
│  └──────┬───────┘  └───────┬────────┘  └─────────┬──────────┘   │
│         │                  │                     │              │
│  ┌──────▼──────────────────▼──────────────────────▼──────────┐  │
│  │  CoordinatorAgent (Claude Haiku, cache 30min)             │  │
│  │  → injecte régime + DI± + multiplicateurs de poids        │  │
│  └──────────────────────────┬──────────────────────────────┘  │
│  ┌───────────────┐           │     ┌───────────────────────┐   │
│  │ Contrarian   │           │     │  MarketRegimeAgent    │   │
│  │ Fear & Greed │           │     │  HMM + ADX + DI±      │   │
│  └──────┬────────┘           │     │  (info-only)          │   │
│         └───────────────────▼─────└───────────────────────┘   │
│                    SynthesisAgent (Claude Sonnet)               │
└──────────────────────────┬──────────────────────────────────────┘
                           │ score_breakdown JSON
┌──────────────────────────▼──────────────────────────────────────┐
│                   DECISION ENGINE                               │
│  Score Calculator [0–100]                                       │
│    MiroFish 15% · Market 45% · Agents LLM 25% · Contrarian 15% │
│  ↓                                                              │
│  Decision Engine                                                │
│    BUY (score ≥ 68) · SELL (score < 52) · HOLD (sinon)         │
│    + Filtres : MA50 gradual · Funding CB · HIGH_VOL ×0.65       │
│  ↓                                                              │
│  Risk Engine → Kelly × conviction × ma50 × funding × high_vol  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                   EXECUTION LAYER                               │
│  Paper Trader (CCXT Binance testnet) · SQLite Logger            │
│  Post-Mortem Agent (+24h) · Streamlit Dashboard                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agents LLM (LangGraph)

| Agent | Rôle | Données |
|-------|------|---------|
| `MarketDataAgent` | Analyse technique | OHLCV, RSI, MACD, ATR, Bollinger, funding rate |
| `FundamentalAgent` | Analyse on-chain & macro | Hashrate, SOPR, macro US/EU |
| `XSentimentAgent` | Sentiment social | Twitter/X, Reddit, Fear & Greed Index |
| `ContrarianAgent` | Signal à contre-courant | Fear & Greed extrêmes, positions crowd |
| `MarketRegimeAgent` | Détection régime | HMM (hmmlearn) + ADX/DI± vectorisé |
| `SynthesisAgent` | Synthèse finale | Agrégation + scoring pondéré |
| `CoordinatorAgent` | Orchestration | Poids adaptatifs par régime, cache 30min |
| `PostMortemAgent` | Feedback 24h | P&L réel vs prédiction, ajustement poids |

---

## MarketRegimeAgent — Détection de régime

Combine un **GaussianHMM** (hmmlearn) et des features déterministes pour classer le marché en 4 régimes :

| Régime | Emoji | Score agent | Poids Coordinateur | Sizing |
|--------|-------|------------|---------------------|--------|
| `TRENDING_UP` | ▲ | 72 / BULLISH | timesfm×1.3, contrarian×1.2 | ×1.0 |
| `TRENDING_DOWN` | ▼ | 30 / BEARISH | contrarian×1.3, timesfm×0.7 | ×1.0 |
| `SIDEWAYS` | ↔ | 50 / NEUTRAL | fear_greed×1.3, timesfm×0.6 | ×1.0 |
| `HIGH_VOLATILITY` | ⚡ | 45 / NEUTRAL | contrarian×1.4, timesfm×0.4 | **×0.65** |

**Signaux de direction** (4 sources, seuil ≥2/4 pour TRENDING) :
- Momentum 20 bougies (> ±1 %)
- Momentum 50 bougies (> ±2 %)
- Gap SMA20/SMA50 (> ±0.5 %)
- **DI spread** DI+ − DI− (> ±5) ← source primaire de direction

---

## Risk Management

### Sizing formula
```
position_size = kelly_fraction
              × conviction_mult     (0.3 + 0.7 × |score-50|/50)
              × ma50_penalty        (1.0 ou 0.5 si prix < MA50)
              × funding_mult        (linéaire: 1.0 → 0.25 selon funding rate)
              × high_vol_mult       (0.65 si régime HIGH_VOLATILITY)
```

### Funding Rate Circuit Breaker

```
< 0.018 %  : normal          → ×1.0
0.018–0.045%: warning         → réduction linéaire jusqu'à ×0.25
≥ 0.045 %  : hard block       → BUY bloqué (×0.0)
             (0.035 % si régime HIGH_VOLATILITY)
< −0.025 % : funding négatif  → signal contrarian LONG bonus
```

Buffer : moyenne glissante sur 3 cycles (sustain), `deque(maxlen=8)`.

---

## Stack Technique

```
Python 3.11+
├── LangGraph 0.2+      — orchestration agent state machine
├── LangChain 0.3+      — abstractions LLM + outils
├── Anthropic SDK       — Claude 3.5 Sonnet/Haiku
├── CCXT 4.x            — market data + paper trading (Binance testnet)
├── hmmlearn            — GaussianHMM pour détection de régime
├── Streamlit 1.35+     — dashboard temps réel
├── SQLite              — stockage décisions, logs, snapshots
├── PyYAML              — configuration hot-reload
└── Docker + supervisord — déploiement production
```

---

## Installation

### Prérequis
- Python 3.11+
- Compte Binance testnet (gratuit)
- Clé API Anthropic (Claude)
- Docker (pour déploiement production)

### Dev local

```bash
git clone https://github.com/eletec/atlas-trader.git
cd atlas-trader

pip install -r requirements.txt

cp .env.example .env
# Remplir les clés dans .env :
#   ANTHROPIC_API_KEY=...
#   BINANCE_TESTNET_API_KEY=...
#   BINANCE_TESTNET_SECRET=...

# Lancer un cycle unique (test)
python main.py --run-once

# Lancer en boucle démon
python main.py --daemon

# Lancer le dashboard
streamlit run dashboard/streamlit_app.py
```

### Variables d'environnement (`.env`)

```env
# Variables d'environnement — COPIER EN .env ET REMPLIR
# NE JAMAIS COMMITTER LE FICHIER .env

# ---- LLM Providers (renseigner AU MOINS UN) ----
ANTHROPIC_API_KEY=sk-ant-...           # https://console.anthropic.com
DEEPSEEK_API_KEY=sk-                   # https://platform.deepseek.com  ← recommandé
GITHUB_TOKEN=ghp_...                   # https://github.com/settings/tokens
OPENAI_API_KEY=sk-...                  # optionnel
XAI_API_KEY=xai-...                    # optionnel Grok
OLLAMA_BASE_URL=                       # Ollama 

# ---- Web Crawling ----
TAVILY_API_KEY=tvly-...
FIRECRAWL_API_KEY=fc-...
SERPAPI_API_KEY=...           # fallback

# ---- Exchange ----
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_TESTNET=true          # toujours true pour paper trading

# ---- News ----
NEWSAPI_KEY=

# ---- Notifications (optionnel) ----
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...


# ---- App ----
LOG_LEVEL=INFO
ENVIRONMENT=development       # development | production

---

## Docker (Production)

```bash
# Build & lancer
docker compose up -d

# Ou sur NAS (Synology / QNAP) :
# 1. Copier les fichiers via deploy.ps1 (Windows)
# 2. Monter le volume /app dans Docker
docker exec atlas-trader-app supervisorctl restart all
```

`supervisord` lance deux processus :
- `trader` — `python main.py --daemon` (boucle 15min)
- `dashboard` — `streamlit run dashboard/streamlit_app.py --server.port 8501`

Les deux redémarrent automatiquement (`startretries=100`).

---

## Configuration (`config/settings.yaml`)

Tous les paramètres sont modifiables en live via l'**interface Admin** du dashboard.

```yaml
project:
  asset: "BTC/USDT"
  loop_interval_seconds: 900    # 15 min

scoring:
  weights:
    mirofish: 0.15
    market: 0.45
    agents: 0.25
    contrarian: 0.15

risk:
  mode: balanced                 # conservative | balanced | aggressive
  buy_threshold: 68
  exit_threshold: 52
  kelly_max_fraction: 0.25
  position_size_pct: 5.0
  max_open_positions: 3
  ma50_filter_mode: gradual

circuit_breaker:
  funding_block: 0.00045         # 0.045 %
  sustain_period_cycles: 3

market_regime:
  adx_period: 18                 # recommandé BTC 15min
  vol_window: 30
  n_hmm_states: 2
```

---

## Dashboard

Le dashboard Streamlit (`http://localhost:8501`) expose :

**Vue User (lecture seule)**
- Score composite + décision en cours
- Badge régime de marché avec :
  - Emoji · régime · probabilité HMM
  - ADX · DI+ / DI− · direction pressure
  - Vol. relative & annualisée
  - Posteriors HMM (Low-vol / High-vol)
  - Historique des 5 derniers cycles
- P&L paper + courbe de performance
- Flux de logs temps réel (50 dernières lignes)
- Bouton « Force Run »

**Vue Admin (mot de passe)**
- Tous les paramètres `settings.yaml` éditables
- Activation / désactivation par agent
- Monitoring coût LLM (tokens / cycle)
- Gestion templates crawler

---

## Structure du projet

```
zeitgeist-trader/
├── main.py                  # Point d'entrée + boucle principale
├── decision_engine.py       # Score Calculator + Decision + Risk Engine
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
│
├── agents/
│   ├── market_data_agent.py     # Indicateurs techniques + funding CB
│   ├── fundamental_agent.py     # On-chain + macro
│   ├── x_sentiment_agent.py     # Sentiment social
│   ├── contrarian_agent.py      # Fear & Greed contrarian
│   ├── market_regime_agent.py   # HMM + ADX/DI± regime detection
│   ├── synthesis_agent.py       # Agrégation LLM finale
│   ├── broad_web_crawler.py     # Crawler multi-sources
│   ├── fast_news_listener.py    # RSS + NewsAPI
│   ├── air_du_temps_builder.py  # Consolidation contexte
│   └── post_mortem_agent.py     # Feedback 24h
│
├── graph/
│   └── workflow.py              # LangGraph state machine
│
├── execution/
│   └── paper_trader.py          # CCXT Binance testnet
│
├── storage/
│   └── database.py              # SQLite (décisions + logs)
│
├── dashboard/
│   ├── streamlit_app.py         # UI principale
│   └── flux_manager.py          # Gestion flux temps réel
│
├── mirofish/
│   └── core.py                  # Wrapper simulation swarm
│
├── config/
│   ├── settings.yaml            # Configuration principale
│   └── prompts.yaml             # Templates prompts LLM
│
└── utils/
    ├── config.py                # Chargement + validation config
    ├── logger.py                # Logging structuré
    └── i18n.py                  # Internationalisation dashboard
```

---

## Modèle de données

### `score_breakdown` (persisté dans SQLite)

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

### `decision` retourné par DecisionEngine

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

## Statut & Roadmap

### MVP v1.0 (actuel)
- [x] Pipeline LangGraph complet
- [x] MiroFish swarm integration
- [x] MarketRegimeAgent (HMM + ADX/DI±)
- [x] Funding rate circuit breaker (3 niveaux)
- [x] Kelly sizing avec 4 multiplicateurs
- [x] Dashboard Streamlit avec badge régime temps réel
- [x] Post-mortem agent +24h
- [x] Docker + supervisord

### v1.1 (prochain)
- [ ] TimesFM price forecasting (réactivation isolée, CPU off-load)
- [ ] Polymarket smart money integration
- [ ] Backtesting engine sur données historiques
- [ ] Alertes Telegram / Discord

### v2.0 (futur)
- [ ] Multi-assets (ETH, SOL, alts)
- [ ] Live trading (CCXT production, risk strict)
- [ ] Fine-tuning du modèle de scoring sur P&L historique
- [ ] Arbitage inter-exchanges

---

## Sécurité

- Clés API exclusivement dans `.env` (jamais committées)
- Mot de passe Admin : hash SHA-256 en session state
- Inputs crawler sanitisés avant injection LLM (anti prompt-injection)
- Validation OHLCV côté CCXT
- Timeout + domaine whitelist sur les crawls

---

## Licence

Projet privé — usage interne uniquement.

---

*Développé avec 🤖 LangGraph · MiroFish · Claude · Streamlit*
