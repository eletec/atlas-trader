"""
graph/workflow.py — Orchestration LangGraph complète
Pipeline : Intelligence → Simulation → Analyse → Décision → Exécution

CA3 — NOTE ScheduleCronTool (Claude Agentique)
----------------------------------------------
Pour planifier des analyses ponctuelles ou declencher des re-parametrages
via Claude CLI, le pattern ScheduleCronTool peut etre utilise comme suit :

    from anthropic import Anthropic
    client = Anthropic()
    # Un agent Claude peut emettre un appel "schedule_next_analysis" via tool_use
    # pour demander au superviseur (APScheduler / cron / supervisord) de lancer
    # un cycle supplementaire a un moment specifique.
    #
    # Exemple de tool definition a injecter dans un agent:
    # {
    #   "name": "schedule_next_analysis",
    #   "description": "Planifie un cycle d'analyse supplementaire dans N minutes",
    #   "input_schema": {
    #     "type": "object",
    #     "properties": {
    #       "delay_minutes": {"type": "integer", "minimum": 5, "maximum": 1440},
    #       "reason": {"type": "string"}
    #     },
    #     "required": ["delay_minutes", "reason"]
    #   }
    # }
    #
    # Le handler cote Python appelle alors APScheduler :
    #   from apscheduler.schedulers.background import BackgroundScheduler
    #   scheduler.add_job(run_full_cycle, 'date',
    #                     run_date=datetime.now() + timedelta(minutes=delay_minutes),
    #                     id=f"emergeny_{cycle_id}")
    #
    # Cette approche permet a Claude de reagir a un evenement de marche critique
    # (ex : crash soudain) et de forcer un re-scan sans attendre le prochain cron.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TypedDict, Annotated
import operator
import uuid

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

logger = logging.getLogger("zeitgeist.workflow")


# ===========================================================
# MODÈLES DE DONNÉES (State + types internes)
# ===========================================================

class NewsItem(TypedDict):
    title: str
    source: str
    url: str
    published_at: str
    relevance_score: float
    summary: str


class AirDuTempsDoc(TypedDict):
    themes: list[str]
    full_text: str
    key_signals: list[str]
    generated_at: str


class MiroFishResult(TypedDict):
    score: float             # 0.0 - 100.0 — bullish conviction
    probas: dict             # {"bull": 0.6, "bear": 0.2, "neutral": 0.2}
    narratives: list[str]    # narratives dominantes
    dominant_narrative: str
    n_agents_used: int


class MarketIndicators(TypedDict):
    symbol: str
    price: float
    rsi_14: float
    macd: float
    macd_signal: float
    bb_upper: float
    bb_lower: float
    atr_14: float
    volume_24h: float
    funding_rate: float
    timestamp: str


class AgentAnalysis(TypedDict):
    agent_name: str
    score: float             # 0.0 - 100.0
    signal: str              # BULLISH | BEARISH | NEUTRAL
    summary: str
    confidence: float        # 0.0 - 1.0


class TradingDecision(TypedDict):
    action: str              # BUY | SELL | HOLD
    score: float
    position_size_usd: float
    entry_price: float
    sl_price: float
    tp_price: float
    explanation: str
    risks: list[str]
    catalysts: list[str]
    approved: bool           # False si human-in-the-loop en attente


class ZeitgeistState(TypedDict):
    """État partagé entre tous les nœuds du graphe LangGraph."""
    cycle_id: str
    timestamp: str
    asset: str

    # Couche Intelligence
    news_items: list[NewsItem]
    air_du_temps: AirDuTempsDoc | None
    crawler_status: str          # "ok" | "error" | "skipped"

    # Couche Simulation
    mirofish_result: MiroFishResult | None

    # Couche Analyse
    market_indicators: MarketIndicators | None
    agent_analyses: dict          # dict[str, AgentAnalysis]

    # Couche Décision
    global_score: float
    decision: TradingDecision | None

    # Couche Exécution
    trade_executed: bool
    trade_result: dict | None

    # Score breakdown (pour shadow profiles)
    score_breakdown: dict | None

    # Métadonnées
    errors: list[str]
    llm_tokens_used: int
    cycle_duration_ms: int


# ===========================================================
# NŒUDS DU GRAPHE
# ===========================================================

def node_fetch_news(state: ZeitgeistState) -> dict:
    """Nœud 1 : Collecte des news rapides (RSS + NewsAPI)."""
    from utils.logger import log_flux_metric
    import time

    t0 = time.time()
    logger.info(f"[{state['cycle_id']}] Starting news collection")

    try:
        from agents.fast_news_listener import FastNewsListener
        listener = FastNewsListener()
        news = listener.fetch_all(asset=state["asset"])
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("fast_news", "ok", latency_ms, len(news))
        logger.info(f"[{state['cycle_id']}] {len(news)} news collected in {latency_ms}ms")
        return {"news_items": news}
    except Exception as exc:
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("fast_news", "error", latency_ms, 0, str(exc))
        logger.error(f"[{state['cycle_id']}] News error: {exc}")
        return {"news_items": [], "errors": state.get("errors", []) + [f"news: {exc}"]}


def node_crawl_web(state: ZeitgeistState) -> dict:
    """Nœud 2 : Crawl thématique (Tavily/Firecrawl) → AirDuTemps."""
    from utils.logger import log_flux_metric
    import time

    t0 = time.time()
    logger.info(f"[{state['cycle_id']}] Starting web crawl")

    try:
        from agents.broad_web_crawler import BroadWebCrawler
        from agents.air_du_temps_builder import AirDuTempsBuilder
        crawler = BroadWebCrawler()
        raw_docs = crawler.crawl_themes(asset=state["asset"])
        builder = AirDuTempsBuilder()
        air_du_temps = builder.build(raw_docs, state["news_items"])
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("crawler", "ok", latency_ms, len(raw_docs))
        logger.info(f"[{state['cycle_id']}] AirDuTemps generated in {latency_ms}ms")
        return {"air_du_temps": air_du_temps, "crawler_status": "ok"}
    except Exception as exc:
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("crawler", "error", latency_ms, 0, str(exc))
        logger.warning(f"[{state['cycle_id']}] Crawl failed (degraded mode): {exc}")
        # Mode dégradé : AirDuTemps construit uniquement depuis les news
        from agents.air_du_temps_builder import AirDuTempsBuilder
        builder = AirDuTempsBuilder()
        air_du_temps = builder.build_from_news_only(state["news_items"])
        return {
            "air_du_temps": air_du_temps,
            "crawler_status": "error",
            "errors": state.get("errors", []) + [f"crawler: {exc}"]
        }


def node_run_mirofish(state: ZeitgeistState) -> dict:
    """Nœud 3 : Simulation swarm MiroFish."""
    from utils.logger import log_flux_metric
    import time

    t0 = time.time()
    logger.info(f"[{state['cycle_id']}] Starting MiroFish simulation")

    try:
        from agents.mirofish_wrapper import MiroFishWrapper
        wrapper = MiroFishWrapper(asset=state.get("asset"))
        seed = wrapper.prepare_seed(state["news_items"], state["air_du_temps"])
        result = wrapper.run_simulation(seed)
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("mirofish", "ok", latency_ms, result["n_agents_used"])
        logger.info(
            f"[{state['cycle_id']}] MiroFish score={result['score']:.1f} "
            f"bull={result['probas'].get('bull', 0):.0%} latency={latency_ms}ms"
        )
        return {"mirofish_result": result}
    except Exception as exc:
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("mirofish", "error", latency_ms, 0, str(exc))
        logger.error(f"[{state['cycle_id']}] MiroFish error: {exc}")
        # Score neutre en cas d'erreur
        fallback: MiroFishResult = {
            "score": 50.0, "probas": {"bull": 0.33, "bear": 0.33, "neutral": 0.34},
            "narratives": ["données indisponibles"], "dominant_narrative": "indisponible",
            "n_agents_used": 0
        }
        return {
            "mirofish_result": fallback,
            "errors": state.get("errors", []) + [f"mirofish: {exc}"]
        }


def node_fetch_market_data(state: ZeitgeistState) -> dict:
    """Nœud 4 : Récupération des données de marché (CCXT)."""
    from utils.logger import log_flux_metric
    import time

    t0 = time.time()
    logger.info(f"[{state['cycle_id']}] Fetching market data {state['asset']}")

    try:
        from agents.market_data_agent import MarketDataAgent
        agent = MarketDataAgent()
        indicators = agent.get_indicators(state["asset"])
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("market_data", "ok", latency_ms, 1)
        logger.info(
            f"[{state['cycle_id']}] Market data OK — "
            f"price={indicators['price']:.2f} RSI={indicators['rsi_14']:.1f}"
        )
        return {"market_indicators": indicators}
    except Exception as exc:
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("market_data", "error", latency_ms, 0, str(exc))
        logger.error(f"[{state['cycle_id']}] Market data error: {exc}")
        return {
            "market_indicators": None,
            "errors": state.get("errors", []) + [f"market_data: {exc}"]
        }


def node_analyze_agents(state: ZeitgeistState) -> dict:
    """Nœud 5 : Exécution parallèle des agents d'analyse (ThreadPoolExecutor)."""
    from agents.x_sentiment_agent import XSentimentAgent
    from agents.contrarian_agent import ContrarianAgent
    from agents.fear_greed_agent import FearGreedAgent
    from agents.polymarket_agent import PolymarketAgent
    from agents.timesfm_agent import TimesFMAgent
    from agents.kronos_agent import KronosAgent
    from agents.market_regime_agent import MarketRegimeAgent
    from utils.logger import log_flux_metric
    from utils.config import load_asset_config
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time

    t0 = time.time()
    asset = state.get("asset")
    settings = load_asset_config(asset)
    agent_cfg = settings.get("agents", {})
    analyses: dict = {}
    tokens_used = 0

    # --- Sélection de l'agent fondamental selon le provider configuré ---
    fund_cfg = agent_cfg.get("fundamental", {})
    _fund_provider = fund_cfg.get("provider", "blockchain_info")
    if _fund_provider == "eth_fundamental":
        from agents.eth_fundamental_agent import EthFundamentalAgent as _FundAgent
    elif _fund_provider == "gold_fundamental":
        from agents.gold_fundamental_agent import GoldFundamentalAgent as _FundAgent  # type: ignore[assignment]
    elif _fund_provider == "forex_fundamental":
        from agents.forex_fundamental_agent import ForexFundamentalAgent as _FundAgent  # type: ignore[assignment]
    else:
        from agents.fundamental_agent import FundamentalAgent as _FundAgent  # type: ignore[assignment]

    # --- XSentimentAgent : keywords depuis la config actif ---
    _xs_keywords = agent_cfg.get("x_sentiment", {}).get("keywords", None)

    # --- EconomicCalendarAgent ---
    _eco_cfg = agent_cfg.get("economic_calendar", {})
    _eco_enabled = _eco_cfg.get("enabled", False)
    if _eco_enabled:
        from agents.economic_calendar_agent import EconomicCalendarAgent as _EcoAgent
    else:
        _EcoAgent = None  # type: ignore[assignment]

    # --- CentralBankAgent ---
    _cb_cfg = agent_cfg.get("central_bank", {})
    _cb_enabled = _cb_cfg.get("enabled", False)
    if _cb_enabled:
        from agents.central_bank_agent import CentralBankAgent as _CbAgent
    else:
        _CbAgent = None  # type: ignore[assignment]

    agents_map = {
        "market_regime":      (MarketRegimeAgent, agent_cfg.get("market_regime", {}).get("enabled", True)),
        "fundamental":        (_FundAgent,        fund_cfg.get("enabled", True)),
        "x_sentiment":        (XSentimentAgent,   agent_cfg.get("x_sentiment",  {}).get("enabled", True)),
        "contrarian":         (ContrarianAgent,   agent_cfg.get("contrarian",   {}).get("enabled", True)),
        "fear_greed":         (FearGreedAgent,    agent_cfg.get("fear_greed",   {}).get("enabled", True)),
        "polymarket":         (PolymarketAgent,   agent_cfg.get("polymarket",   {}).get("enabled", True)),
        "timesfm":            (TimesFMAgent,      agent_cfg.get("timesfm",      {}).get("enabled", False)),
        "kronos":             (KronosAgent,       agent_cfg.get("kronos",       {}).get("enabled", True)),
        "economic_calendar":  (_EcoAgent,         _eco_enabled),
        "central_bank":       (_CbAgent,          _cb_enabled),
    }

    enabled_agents = {
        name: cls
        for name, (cls, enabled) in agents_map.items()
        if enabled and cls is not None
    }
    disabled = [name for name, (_, enabled) in agents_map.items() if not enabled]
    for name in disabled:
        logger.info(f"[{state['cycle_id']}] Agent {name} disabled")

    def _run_agent(name: str, AgentClass) -> tuple[str, dict]:
        _t = time.time()
        try:
            agent = AgentClass()
            # TimesFM / Kronos : hard timeout sur le thread (modèle lourd, peut figer)
            # IMPORTANT: ne PAS utiliser 'with ThreadPoolExecutor' — __exit__ bloque
            # sur shutdown(wait=True) si agent.analyze() est lui-même figé.
            if name in ("timesfm", "kronos"):
                import concurrent.futures as _cf
                _prefix = "tfm" if name == "timesfm" else "kronos"
                _p = _cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix=_prefix)
                _f = _p.submit(agent.analyze, state)
                try:
                    result = _f.result(timeout=180)
                except (_cf.TimeoutError, TimeoutError):
                    logger.warning(f"[{state['cycle_id']}] Agent {name} TIMEOUT 180s")
                    log_flux_metric(f"agent_{name}", "error", 180000, 0, "timeout 180s")
                    _p.shutdown(wait=False)
                    return name, AgentAnalysis(
                        agent_name=name, score=50.0,
                        signal="NEUTRAL", summary="timeout 180s", confidence=0.0
                    )
                _p.shutdown(wait=False)
            else:
                result = agent.analyze(state)
            _lat = int((time.time() - _t) * 1000)
            log_flux_metric(f"agent_{name}", "ok", _lat, 1)
            logger.info(f"[{state['cycle_id']}] Agent {name} completed in {_lat}ms — {result.get('signal', '?') if isinstance(result, dict) else '?'}")
            return name, result
        except Exception as exc:
            _lat = int((time.time() - _t) * 1000)
            logger.warning(f"[{state['cycle_id']}] Agent {name} failed in {_lat}ms: {exc}")
            log_flux_metric(f"agent_{name}", "error", _lat, 0, str(exc))
            return name, AgentAnalysis(
                agent_name=name, score=50.0,
                signal="NEUTRAL", summary="analyse indisponible", confidence=0.0
            )

    # Lancement parallèle — timeout 180s (TimesFM a son propre timeout à 120s)
    # IMPORTANT: ne PAS utiliser 'with ThreadPoolExecutor' — si as_completed() expire,
    # __exit__ appelle shutdown(wait=True) et attend les threads figés indéfiniment.
    pool = ThreadPoolExecutor(max_workers=len(enabled_agents), thread_name_prefix="agent")
    futures = {pool.submit(_run_agent, name, cls): name for name, cls in enabled_agents.items()}
    try:
        for future in as_completed(futures, timeout=180):
            name, result = future.result()
            analyses[name] = result
            tokens_used += result.get("tokens_used", 0) if isinstance(result, dict) else 0
    except TimeoutError:
        logger.error(f"[{state['cycle_id']}] Global agents timeout (180s) — some agents skipped")
        # Collecter les résultats déjà terminés
        for fut, fname in futures.items():
            if fut.done() and fname not in analyses:
                try:
                    _, result = fut.result(timeout=0)
                    analyses[fname] = result
                except Exception:
                    pass
    finally:
        pool.shutdown(wait=False)  # abandon les threads figés, ne jamais bloquer

    latency_ms = int((time.time() - t0) * 1000)
    logger.info(f"[{state['cycle_id']}] Agents completed in {latency_ms}ms (parallel) — {len(analyses)} active")

    # Persister la prédiction TimesFM pour suivi de performance
    tfm = analyses.get("timesfm")
    if isinstance(tfm, dict) and tfm.get("forecast_details"):
        try:
            from storage.database import log_timesfm_forecast
            log_timesfm_forecast(
                cycle_id=state["cycle_id"],
                asset=state.get("asset", "BTC/USDT"),
                forecast_details=tfm["forecast_details"],
                score=tfm.get("score", 50),
                signal=tfm.get("signal", "NEUTRAL"),
                confidence=tfm.get("confidence", 0),
            )
        except Exception as exc:
            logger.warning(f"Cannot log TimesFM forecast: {exc}")

    # Persister la prédiction Kronos pour suivi de performance
    kronos_res = analyses.get("kronos")
    if isinstance(kronos_res, dict) and kronos_res.get("forecast_details"):
        try:
            from storage.database import log_kronos_forecast
            log_kronos_forecast(
                cycle_id=state["cycle_id"],
                asset=state.get("asset", "BTC/USDT"),
                forecast_details=kronos_res["forecast_details"],
                score=kronos_res.get("score", 50),
                signal=kronos_res.get("signal", "NEUTRAL"),
                confidence=kronos_res.get("confidence", 0),
            )
        except Exception as exc:
            logger.warning(f"Cannot log Kronos forecast: {exc}")

    # CA6: CoordinatorAgent — pondération dynamique LLM après collecte des analyses
    # Cache 2 cycles : si le régime n'a pas changé, réutiliser le dernier résultat
    try:
        import time as _time
        from graph.coordinator import CoordinatorAgent
        _current_regime = analyses.get("market_regime", {}).get("regime", "UNKNOWN")
        _cached = _COORDINATOR_CACHE
        _cache_valid = (
            _cached.get("regime") == _current_regime
            and _cached.get("expires_at", 0) > _time.time()
        )
        if _cache_valid:
            coord_meta = _cached["meta"]
            logger.info(
                f"[{state['cycle_id']}] Coordinator (cache) consensus={coord_meta.get('consensus_signal')} "
                f"régime={_current_regime} (expire dans "
                f"{int(_cached['expires_at'] - _time.time())}s)"
            )
        else:
            coord_meta = CoordinatorAgent().coordinate(analyses)
            if coord_meta:
                _COORDINATOR_CACHE.clear()
                _COORDINATOR_CACHE.update({
                    "meta": coord_meta,
                    "regime": _current_regime,
                    "expires_at": _time.time() + _COORDINATOR_TTL_SECONDS,
                })
                logger.info(
                    f"[{state['cycle_id']}] Coordinator (fresh) consensus={coord_meta.get('consensus_signal')} "
                    f"outliers={coord_meta.get('outliers', [])}"
                )
        if coord_meta:
            analyses["coordinator_meta"] = coord_meta
    except Exception as _coord_exc:
        logger.debug("Coordinator skipped: %s", _coord_exc)

    return {
        "agent_analyses": analyses,
        "llm_tokens_used": state.get("llm_tokens_used", 0) + tokens_used
    }


def node_debate(state: ZeitgeistState) -> dict:
    """Nœud 5b (optionnel) : Débat Bull vs Bear avant la synthèse.
    Désactivé par défaut (agents.bull_bear_debate.enabled: false).
    Le résultat est injecté dans agent_analyses["debate"] pour que
    SynthesisAgent puisse l'inclure dans son raisonnement narratif.
    """
    from utils.config import load_settings
    cfg = load_settings()
    if not cfg.get("agents", {}).get("bull_bear_debate", {}).get("enabled", False):
        return {}   # nœud transparent si désactivé

    from agents.bull_bear_debate_agent import BullBearDebateAgent
    import time

    t0 = time.time()
    logger.info(f"[{state['cycle_id']}] Bull vs Bear debate")
    agent  = BullBearDebateAgent()
    result = agent.analyze(state)

    analyses = dict(state.get("agent_analyses") or {})
    analyses["debate"] = result

    elapsed = time.time() - t0
    logger.info(f"[{state['cycle_id']}] Debate completed in {elapsed:.1f}s")
    return {"agent_analyses": analyses}


def node_synthesize(state: ZeitgeistState) -> dict:
    """Nœud 6 : Synthèse finale par SynthesisAgent (LLM).
    Utilise SynthesisAgentAgentic (CA4) si llm.agentic_synthesis=true.
    """
    # P4: importlib.reload supprimé — inutile en prod, +50ms/cycle + risque de leaks LangChain
    from agents.synthesis_agent import SynthesisAgent, SynthesisAgentAgentic
    from utils.config import load_settings
    from utils.logger import log_flux_metric
    import time

    t0 = time.time()
    logger.info(f"[{state['cycle_id']}] LLM synthesis")

    cfg = load_settings()
    llm_cfg = cfg.get("llm", {})
    use_agentic = (
        llm_cfg.get("provider", "anthropic") == "anthropic"
        and llm_cfg.get("agentic_synthesis", False)
    )

    try:
        if use_agentic:
            logger.info(f"[{state['cycle_id']}] Agentic mode CA4 (WebSearch enabled)")
            agent = SynthesisAgentAgentic()
        else:
            agent = SynthesisAgent()
        synthesis = agent.synthesize(state)
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("synthesis", "ok", latency_ms, 1)
        return {
            "agent_analyses": {**state.get("agent_analyses", {}), "synthesis": synthesis},
            "llm_tokens_used": state.get("llm_tokens_used", 0) + synthesis.get("tokens_used", 0)
        }
    except Exception as exc:
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("synthesis", "error", latency_ms, 0, str(exc))
        logger.error(f"[{state['cycle_id']}] Synthesis error: {exc}")
        return {"errors": state.get("errors", []) + [f"synthesis: {exc}"]}


def node_calculate_score(state: ZeitgeistState) -> dict:
    """Nœud 7 : Calcul du score global pondéré."""
    from decision_engine import ScoreCalculator
    import time

    t0 = time.time()
    calculator = ScoreCalculator(asset=state.get("asset"))

    mirofish_score = state.get("mirofish_result", {}).get("score", 50.0)
    mirofish_n_agents = state.get("mirofish_result", {}).get("n_agents_used", 0)
    market_score = _derive_market_score(state.get("market_indicators"))
    agents_scores = {k: v.get("score", 50.0) for k, v in state.get("agent_analyses", {}).items()}
    contrarian_score = agents_scores.pop("contrarian", 50.0)

    global_score, breakdown = calculator.calculate(
        mirofish_score=mirofish_score,
        market_score=market_score,
        agent_scores=agents_scores,
        contrarian_score=contrarian_score,
        mirofish_n_agents=mirofish_n_agents,
    )

    logger.info(
        f"[{state['cycle_id']}] Score global: {global_score:.1f} — "
        f"MiroFish={mirofish_score:.1f} Market={market_score:.1f} "
        f"Agents={sum(agents_scores.values())/max(len(agents_scores),1):.1f} "
        f"Contrarian={contrarian_score:.1f}"
    )

    # Conserver les scores bruts pour les shadow profiles
    score_breakdown = {
        "mirofish_score": mirofish_score,
        "market_score": market_score,
        "agent_scores": agents_scores,
        "contrarian_score": contrarian_score,
        "breakdown": breakdown,
        # Régime courant — persisté en DB pour lecture par le dashboard
        "regime": state.get("agent_analyses", {}).get("market_regime", {}).get("regime", "UNKNOWN"),
        "hmm_prob": state.get("agent_analyses", {}).get("market_regime", {}).get("hmm_prob", 0.5),
        "hmm_posteriors": state.get("agent_analyses", {}).get("market_regime", {}).get("hmm_posteriors", {}),
        "direction_pressure": state.get("agent_analyses", {}).get("market_regime", {}).get("direction_pressure", ""),
        "regime_features": state.get("agent_analyses", {}).get("market_regime", {}).get("features", {}),
    }

    return {"global_score": global_score, "score_breakdown": score_breakdown}


def node_decide(state: ZeitgeistState) -> dict:
    """Nœud 8 : Prise de décision avec gestion du risque."""
    from decision_engine import DecisionEngine
    import time

    t0 = time.time()
    engine = DecisionEngine(asset=state.get("asset"))
    decision = engine.decide(
        score=state["global_score"],
        market_indicators=state.get("market_indicators"),
        agent_analyses=state.get("agent_analyses", {}),
        mirofish_result=state.get("mirofish_result")
    )
    latency_ms = int((time.time() - t0) * 1000)
    logger.info(
        f"[{state['cycle_id']}] Décision: {decision['action']} "
        f"size={decision['position_size_usd']:.0f}$ "
        f"SL={decision['sl_price']:.2f} TP={decision['tp_price']:.2f}"
    )
    return {"decision": decision}


def node_execute(state: ZeitgeistState) -> dict:
    """Nœud 9 : Exécution paper trade + log SQLite."""
    from execution.paper_trader import PaperTrader
    from storage.database import log_decision
    from utils.logger import log_flux_metric
    import time

    t0 = time.time()
    decision = state.get("decision")

    if not decision or decision.get("action") == "HOLD":
        latency_ms = int((time.time() - t0) * 1000)
        score = state.get("global_score", 50)
        log_flux_metric("paper_trader", "hold", latency_ms, 0)
        logger.info(f"[{state['cycle_id']}] HOLD — no execution (score={score:.1f})")
        log_decision(state["cycle_id"], state)
        return {"trade_executed": False}

    # Human-in-the-loop check
    if not decision.get("approved", True):
        log_flux_metric("paper_trader", "hold", 0, 0)
        logger.info(f"[{state['cycle_id']}] En attente validation humaine")
        return {"trade_executed": False}

    # ── SELL : clôture des positions longues ouvertes (spot long-only, pas de short) ──
    if decision.get("action") == "SELL":
        from storage.database import get_open_positions, close_position, update_decision_result
        asset = state.get("asset", "")
        price = float(decision.get("entry_price") or 0)
        open_buys = [
            p for p in get_open_positions()
            if p.get("action") == "BUY" and p.get("asset") == asset
        ]
        n_closed = 0
        for pos in open_buys:
            close_position(pos["cycle_id"], price, reason="EXIT_SIGNAL")
            n_closed += 1
            logger.info(
                f"[{state['cycle_id']}] Position BUY {pos['cycle_id']} clôturée "
                f"@ {price:.4f} (EXIT_SIGNAL, score={state.get('global_score', 0):.0f})"
            )
        # Logger le signal SELL comme décision narrative (P&L=0 sur cette ligne)
        # Le P&L réel est porté sur la/les ligne(s) BUY via close_position()
        log_decision(state["cycle_id"], state)
        update_decision_result(state["cycle_id"], 0.0)  # évite l'évaluation post-mortem
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("paper_trader", "sell_close", latency_ms, n_closed)
        logger.info(
            f"[{state['cycle_id']}] SELL — {n_closed} position(s) BUY clôturée(s) @ {price:.4f}"
        )
        return {"trade_executed": n_closed > 0}

    try:
        trader = PaperTrader()
        result = trader.execute(decision)
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("paper_trader", "ok", latency_ms, 1)
        log_decision(state["cycle_id"], state, result)

        # ── Audit log complet de l'ouverture de position ──────────────────
        fill  = result.get("fill_price", decision.get("entry_price", 0))
        size  = decision.get("position_size_usd", 0)
        sl    = decision.get("sl_price", 0)
        tp    = decision.get("tp_price", 0)
        score = state.get("global_score", 0)
        qty   = round(size / fill, 6) if fill > 0 else 0
        logger.info(
            f"TRADE OPEN  │ {state.get('asset','?')} │ {state['cycle_id'][:8]} │ "
            f"BUY fill={fill:.2f} │ "
            f"size=${size:.0f} qty={qty:.6f} │ "
            f"SL={sl:.2f} TP={tp:.2f} │ score={score:.0f}"
        )
        return {"trade_executed": True, "trade_result": result}
    except Exception as exc:
        log_flux_metric("paper_trader", "error", 0, 0, str(exc))
        logger.error(f"[{state['cycle_id']}] Execution error: {exc}")
        log_decision(state["cycle_id"], state)
        return {
            "trade_executed": False,
            "errors": state.get("errors", []) + [f"execution: {exc}"]
        }


# ===========================================================
# ROUTAGE CONDITIONNEL
# ===========================================================

def should_continue_after_news(state: ZeitgeistState) -> str:
    """Si pas de news ET pas d'AirDuTemps en cache → abort (seulement si des keywords sont configurés)."""
    if state.get("news_items") or state.get("air_du_temps"):
        return "continue"
    # Vérifier si cet actif a des keywords de news configurés
    # Si non (forex, matières premières), continuer sur les indicateurs de marché seuls
    try:
        from utils.config import load_asset_config
        asset = state.get("asset", "")
        asset_cfg = load_asset_config(asset) if asset else {}
        has_kw = bool(
            asset_cfg.get("news", {}).get("sources_per_asset", {}).get(asset, {}).get("keywords")
            or asset_cfg.get("agents", {}).get("x_sentiment", {}).get("keywords")
        )
        if not has_kw:
            logger.info(
                f"[{state['cycle_id']}] Aucune news pour {asset} "
                "(pas de keywords configurés) — cycle continue sur indicateurs marché"
            )
            return "continue"
    except Exception:
        pass
    logger.warning(f"[{state['cycle_id']}] No data — cycle aborted")
    return "abort"


def node_log_hold(state: ZeitgeistState) -> dict:
    """Nœud terminal HOLD : log la décision sans exécuter de trade.
    Route d'arrivée quand circuit breaker actif ou score insuffisant.
    Sans ce nœud le branchement 'hold → END' court-circuitait log_decision.
    """
    from storage.database import log_decision
    from utils.logger import log_flux_metric
    # S'assurer qu'il y a un objet decision HOLD minimal dans le state
    if not state.get("decision"):
        state = {**state, "decision": {
            "action": "HOLD", "position_size_usd": 0,
            "sl_price": 0, "tp_price": 0, "entry_price": 0,
        }}
    try:
        log_decision(state["cycle_id"], state)
        log_flux_metric("paper_trader", "hold", 0, 0)
    except Exception as exc:
        logger.error(f"[{state['cycle_id']}] node_log_hold — log_decision failed: {exc}")
    return {"trade_executed": False}


def should_execute(state: ZeitgeistState) -> str:
    """Si circuit breaker actif → forcer HOLD."""
    from decision_engine import RiskEngine
    engine = RiskEngine()
    if engine.is_circuit_breaker_active(state.get("market_indicators")):
        logger.warning(f"[{state['cycle_id']}] Circuit breaker actif — HOLD forcé")
        return "hold"
    if state.get("global_score", 50) != 50 or state.get("decision"):
        return "execute"
    return "hold"


# ===========================================================
# CONSTRUCTION DU GRAPHE
# ===========================================================

def build_workflow() -> StateGraph:
    """Construit et compile le graphe LangGraph complet."""

    graph = StateGraph(ZeitgeistState)

    # Ajout des nœuds
    graph.add_node("fetch_news", node_fetch_news)
    graph.add_node("crawl_web", node_crawl_web)
    graph.add_node("run_mirofish", node_run_mirofish)
    graph.add_node("fetch_market_data", node_fetch_market_data)
    graph.add_node("analyze_agents", node_analyze_agents)
    graph.add_node("debate", node_debate)
    graph.add_node("synthesize", node_synthesize)
    graph.add_node("calculate_score", node_calculate_score)
    graph.add_node("decide", node_decide)
    graph.add_node("execute", node_execute)
    graph.add_node("log_hold", node_log_hold)

    # Point d'entrée
    graph.set_entry_point("fetch_news")

    # Edges séquentiels
    graph.add_conditional_edges(
        "fetch_news",
        should_continue_after_news,
        {"continue": "crawl_web", "abort": END}
    )
    graph.add_edge("crawl_web", "run_mirofish")
    graph.add_edge("run_mirofish", "fetch_market_data")
    graph.add_edge("fetch_market_data", "analyze_agents")
    graph.add_edge("analyze_agents", "debate")
    graph.add_edge("debate", "synthesize")
    graph.add_edge("synthesize", "calculate_score")
    graph.add_edge("calculate_score", "decide")
    graph.add_conditional_edges(
        "decide",
        should_execute,
        {"execute": "execute", "hold": "log_hold"}
    )
    graph.add_edge("log_hold", END)
    graph.add_edge("execute", END)

    return graph.compile()


def create_initial_state(asset: str) -> ZeitgeistState:
    """Crée l'état initial pour un nouveau cycle."""
    return ZeitgeistState(
        cycle_id=str(uuid.uuid4())[:8],
        timestamp=datetime.utcnow().isoformat(),
        asset=asset,
        news_items=[],
        air_du_temps=None,
        crawler_status="pending",
        mirofish_result=None,
        market_indicators=None,
        agent_analyses={},
        global_score=50.0,
        decision=None,
        trade_executed=False,
        trade_result=None,
        score_breakdown=None,
        errors=[],
        llm_tokens_used=0,
        cycle_duration_ms=0,
    )


# Workflow compilé une seule fois — évite la fuite mémoire LangGraph par cycle
_COMPILED_WORKFLOW = None

# Cache CoordinatorAgent — valide pendant 2 cycles (30 min) pour éviter un appel LLM inutile
# Structure : {"meta": dict, "expires_at": float (epoch)}
_COORDINATOR_CACHE: dict = {}
_COORDINATOR_TTL_SECONDS = 1800  # 2 × 15 min


def _get_workflow():
    global _COMPILED_WORKFLOW
    if _COMPILED_WORKFLOW is None:
        _COMPILED_WORKFLOW = build_workflow()
    return _COMPILED_WORKFLOW


def run_cycle(asset: str = "BTC/USDT", trigger: str = "scheduled") -> ZeitgeistState:
    """Exécute un cycle complet et retourne l'état final."""
    import time
    from utils.cycle_lock import try_acquire, release

    if not try_acquire(owner=f"daemon-{trigger}", asset=asset):
        logger.warning(f"Cycle skipped — another cycle is already running for {asset} (trigger={trigger})")
        raise RuntimeError(f"cycle_lock_busy (trigger={trigger})")

    try:
        workflow = _get_workflow()
        initial_state = create_initial_state(asset)
        t0 = time.time()
        start_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        logger.info(f"=== CYCLE {initial_state['cycle_id']} START at {start_ts} — type: {trigger} ({asset}) ===")
        final_state = workflow.invoke(initial_state)
        if not final_state:
            logger.warning(
                f"[{initial_state['cycle_id']}] workflow.invoke() vide/None pour {asset} — cycle skippé"
            )
            return {**initial_state, "global_score": 50.0,
                    "decision": {"action": "HOLD", "position_size_usd": 0,
                                 "sl_price": 0, "tp_price": 0},
                    "errors": initial_state.get("errors", []) + ["workflow_returned_empty"],
                    "cycle_duration_ms": 0}
        duration_ms = int((time.time() - t0) * 1000)
        end_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        final_state["cycle_duration_ms"] = duration_ms
        logger.info(
            f"=== CYCLE {initial_state['cycle_id']} FIN à {end_ts} — "
            f"{duration_ms}ms | score={final_state.get('global_score', 0):.1f} | "
            f"decision={(final_state.get('decision') or {}).get('action', 'N/A')} | "
            f"tokens={final_state.get('llm_tokens_used', 0)} | "
            f"erreurs={len(final_state.get('errors', []))} ==="
        )

        # Évaluer les shadow profiles (ne bloque pas le cycle)
        try:
            _run_shadow_profiles(final_state)
        except Exception as exc:
            logger.warning(f"Shadow profiles ignorés : {exc}")

        return final_state
    finally:
        release(asset=asset)


# ===========================================================
# UTILITAIRE : dérivation score marché depuis indicateurs
# ===========================================================

def _derive_market_score(indicators: MarketIndicators | None) -> float:
    """Dérive un score [0-100] depuis les indicateurs techniques."""
    if indicators is None:
        return 50.0

    score = 50.0
    rsi = indicators.get("rsi_14", 50)
    macd = indicators.get("macd", 0)
    macd_signal = indicators.get("macd_signal", 0)
    funding = indicators.get("funding_rate", 0)
    price = indicators.get("price", 0.0)
    ma_50 = indicators.get("ma_50", 0.0)

    # RSI contribution (±20 points)
    if rsi < 30:
        score += 20   # survente → haussier
    elif rsi > 70:
        score -= 20   # surachat → baissier
    else:
        score += (50 - rsi) * 0.4

    # MACD contribution (±8 points) — indicateur retardataire, poids réduit
    if macd > macd_signal:
        score += 8
    else:
        # Pas de pénalité MACD si RSI en zone survente (signal RSI prioritaire)
        if rsi >= 30:
            score -= 8

    # Distance MA50 daily (±12 points) — proximité/croisement de la MA50
    if ma_50 > 0 and price > 0:
        pct_vs_ma50 = (price - ma_50) / ma_50  # ex: +0.039 = +3.9%
        # Linéaire : ±2% → ±4 pts, ±5% → ±10 pts, ±6%+ → ±12 pts (plafonné)
        ma50_contrib = max(-12.0, min(12.0, pct_vs_ma50 * 200))
        score += ma50_contrib

    # Momentum 4h (±8 points) — filtre tendance intermédiaire
    # trend_4h="DOWN" en marché baissier → pénalité pour éviter BUY en free-fall
    trend_4h = indicators.get("trend_4h")
    if trend_4h == "DOWN":
        score -= 8
    elif trend_4h == "UP":
        score += 8

    # Funding rate contribution (±10 points)
    if funding < -0.01:
        score += 10   # funding négatif → shorts surpayés → haussier
    elif funding > 0.03:
        score -= 10   # funding très élevé → longs surpayés → baissier

    return max(0.0, min(100.0, score))


# ===========================================================
# SHADOW PROFILES — évaluation en fin de cycle
# ===========================================================

def _run_shadow_profiles(state: ZeitgeistState) -> None:
    """Évalue les profils shadow avec les mêmes scores bruts."""
    breakdown = state.get("score_breakdown")
    if not breakdown:
        logger.debug("Pas de score_breakdown — shadow profiles ignorés")
        return

    from comparison.shadow_runner import evaluate_shadow_profiles

    results = evaluate_shadow_profiles(
        cycle_id=state["cycle_id"],
        asset=state.get("asset", "BTC/USDT"),
        timestamp=state.get("timestamp", ""),
        mirofish_score=breakdown["mirofish_score"],
        market_score=breakdown["market_score"],
        agent_scores=breakdown["agent_scores"],
        contrarian_score=breakdown["contrarian_score"],
        market_indicators=state.get("market_indicators"),
    )

    if results:
        actions_summary = " | ".join(
            f"{r['profile']}={r['action']}({r['score']:.0f})" for r in results
        )
        logger.info(f"Shadow profiles: {actions_summary}")
