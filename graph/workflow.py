"""
graph/workflow.py — Orchestration LangGraph complète
Pipeline : Intelligence → Simulation → Analyse → Décision → Exécution
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
    logger.info(f"[{state['cycle_id']}] Démarrage collecte news")

    try:
        from agents.fast_news_listener import FastNewsListener
        listener = FastNewsListener()
        news = listener.fetch_all(asset=state["asset"])
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("fast_news", "ok", latency_ms, len(news))
        logger.info(f"[{state['cycle_id']}] {len(news)} news collectées en {latency_ms}ms")
        return {"news_items": news}
    except Exception as exc:
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("fast_news", "error", latency_ms, 0, str(exc))
        logger.error(f"[{state['cycle_id']}] Erreur news: {exc}")
        return {"news_items": [], "errors": state.get("errors", []) + [f"news: {exc}"]}


def node_crawl_web(state: ZeitgeistState) -> dict:
    """Nœud 2 : Crawl thématique (Tavily/Firecrawl) → AirDuTemps."""
    from utils.logger import log_flux_metric
    import time

    t0 = time.time()
    logger.info(f"[{state['cycle_id']}] Démarrage crawl web")

    try:
        from agents.broad_web_crawler import BroadWebCrawler
        from agents.air_du_temps_builder import AirDuTempsBuilder
        crawler = BroadWebCrawler()
        raw_docs = crawler.crawl_themes(asset=state["asset"])
        builder = AirDuTempsBuilder()
        air_du_temps = builder.build(raw_docs, state["news_items"])
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("crawler", "ok", latency_ms, len(raw_docs))
        logger.info(f"[{state['cycle_id']}] AirDuTemps généré en {latency_ms}ms")
        return {"air_du_temps": air_du_temps, "crawler_status": "ok"}
    except Exception as exc:
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("crawler", "error", latency_ms, 0, str(exc))
        logger.warning(f"[{state['cycle_id']}] Crawl échoué (mode dégradé): {exc}")
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
    logger.info(f"[{state['cycle_id']}] Démarrage simulation MiroFish")

    try:
        from agents.mirofish_wrapper import MiroFishWrapper
        wrapper = MiroFishWrapper()
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
        logger.error(f"[{state['cycle_id']}] Erreur MiroFish: {exc}")
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
    logger.info(f"[{state['cycle_id']}] Récupération market data {state['asset']}")

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
        logger.error(f"[{state['cycle_id']}] Erreur market data: {exc}")
        return {
            "market_indicators": None,
            "errors": state.get("errors", []) + [f"market_data: {exc}"]
        }


def node_analyze_agents(state: ZeitgeistState) -> dict:
    """Nœud 5 : Exécution parallèle des agents d'analyse (ThreadPoolExecutor)."""
    from agents.fundamental_agent import FundamentalAgent
    from agents.x_sentiment_agent import XSentimentAgent
    from agents.contrarian_agent import ContrarianAgent
    from agents.fear_greed_agent import FearGreedAgent
    from agents.polymarket_agent import PolymarketAgent
    from agents.timesfm_agent import TimesFMAgent
    from utils.logger import log_flux_metric
    from utils.config import load_settings
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time

    t0 = time.time()
    settings = load_settings()
    agent_cfg = settings.get("agents", {})
    analyses: dict = {}
    tokens_used = 0

    agents_map = {
        "fundamental": (FundamentalAgent,  agent_cfg.get("fundamental",  {}).get("enabled", True)),
        "x_sentiment": (XSentimentAgent,   agent_cfg.get("x_sentiment",  {}).get("enabled", True)),
        "contrarian":  (ContrarianAgent,   agent_cfg.get("contrarian",   {}).get("enabled", True)),
        "fear_greed":  (FearGreedAgent,    agent_cfg.get("fear_greed",   {}).get("enabled", True)),
        "polymarket":  (PolymarketAgent,   agent_cfg.get("polymarket",   {}).get("enabled", True)),
        "timesfm":     (TimesFMAgent,      agent_cfg.get("timesfm",      {}).get("enabled", False)),
    }

    enabled_agents = {
        name: cls for name, (cls, enabled) in agents_map.items() if enabled
    }
    disabled = [name for name, (_, enabled) in agents_map.items() if not enabled]
    for name in disabled:
        logger.info(f"[{state['cycle_id']}] Agent {name} désactivé")

    def _run_agent(name: str, AgentClass) -> tuple[str, dict]:
        _t = time.time()
        try:
            agent = AgentClass()
            # TimesFM gets its own hard timeout (model load + forecast can hang)
            if name == "timesfm":
                import concurrent.futures as _cf
                with _cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="tfm") as _p:
                    _f = _p.submit(agent.analyze, state)
                    try:
                        result = _f.result(timeout=180)
                    except (_cf.TimeoutError, TimeoutError):
                        logger.warning(f"[{state['cycle_id']}] Agent timesfm TIMEOUT 180s")
                        log_flux_metric("agent_timesfm", "error", 180000, 0, "timeout 180s")
                        return name, AgentAnalysis(
                            agent_name=name, score=50.0,
                            signal="NEUTRAL", summary="timeout 180s", confidence=0.0
                        )
            else:
                result = agent.analyze(state)
            _lat = int((time.time() - _t) * 1000)
            log_flux_metric(f"agent_{name}", "ok", _lat, 1)
            logger.info(f"[{state['cycle_id']}] Agent {name} terminé en {_lat}ms — {result.get('signal', '?') if isinstance(result, dict) else '?'}")
            return name, result
        except Exception as exc:
            _lat = int((time.time() - _t) * 1000)
            logger.warning(f"[{state['cycle_id']}] Agent {name} échoué en {_lat}ms: {exc}")
            log_flux_metric(f"agent_{name}", "error", _lat, 0, str(exc))
            return name, AgentAnalysis(
                agent_name=name, score=50.0,
                signal="NEUTRAL", summary="analyse indisponible", confidence=0.0
            )

    # Lancement parallèle — timeout 180s (TimesFM a son propre timeout à 120s)
    with ThreadPoolExecutor(max_workers=len(enabled_agents), thread_name_prefix="agent") as pool:
        futures = {pool.submit(_run_agent, name, cls): name for name, cls in enabled_agents.items()}
        try:
            for future in as_completed(futures, timeout=180):
                name, result = future.result()
                analyses[name] = result
                tokens_used += result.get("tokens_used", 0) if isinstance(result, dict) else 0
        except TimeoutError:
            logger.error(f"[{state['cycle_id']}] Agents timeout global (180s) — certains agents ignorés")
            # Collecter les résultats déjà terminés
            for fut, fname in futures.items():
                if fut.done() and fname not in analyses:
                    try:
                        _, result = fut.result(timeout=0)
                        analyses[fname] = result
                    except Exception:
                        pass

    latency_ms = int((time.time() - t0) * 1000)
    logger.info(f"[{state['cycle_id']}] Agents terminés en {latency_ms}ms (parallèle) — {len(analyses)} actifs")

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

    return {
        "agent_analyses": analyses,
        "llm_tokens_used": state.get("llm_tokens_used", 0) + tokens_used
    }


def node_synthesize(state: ZeitgeistState) -> dict:
    """Nœud 6 : Synthèse finale par SynthesisAgent (LLM)."""
    import importlib
    import sys
    import agents.synthesis_agent as _sa_mod
    importlib.reload(_sa_mod)  # recharge le module à chaque cycle → pickup des changements sans restart
    SynthesisAgent = _sa_mod.SynthesisAgent
    from utils.logger import log_flux_metric
    import time

    t0 = time.time()
    logger.info(f"[{state['cycle_id']}] Synthèse LLM")

    try:
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
        logger.error(f"[{state['cycle_id']}] Erreur synthèse: {exc}")
        return {"errors": state.get("errors", []) + [f"synthesis: {exc}"]}


def node_calculate_score(state: ZeitgeistState) -> dict:
    """Nœud 7 : Calcul du score global pondéré."""
    from decision_engine import ScoreCalculator
    import time

    t0 = time.time()
    calculator = ScoreCalculator()

    mirofish_score = state.get("mirofish_result", {}).get("score", 50.0)
    market_score = _derive_market_score(state.get("market_indicators"))
    agents_scores = {k: v.get("score", 50.0) for k, v in state.get("agent_analyses", {}).items()}
    contrarian_score = agents_scores.pop("contrarian", 50.0)

    global_score, breakdown = calculator.calculate(
        mirofish_score=mirofish_score,
        market_score=market_score,
        agent_scores=agents_scores,
        contrarian_score=contrarian_score
    )

    logger.info(
        f"[{state['cycle_id']}] Score global: {global_score:.1f} — "
        f"MiroFish={mirofish_score:.1f} Market={market_score:.1f} "
        f"Agents={sum(agents_scores.values())/max(len(agents_scores),1):.1f} "
        f"Contrarian={contrarian_score:.1f}"
    )
    return {"global_score": global_score}


def node_decide(state: ZeitgeistState) -> dict:
    """Nœud 8 : Prise de décision avec gestion du risque."""
    from decision_engine import DecisionEngine
    import time

    t0 = time.time()
    engine = DecisionEngine()
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
        logger.info(f"[{state['cycle_id']}] HOLD — pas d'exécution (score={score:.1f})")
        log_decision(state["cycle_id"], state)
        return {"trade_executed": False}

    # Human-in-the-loop check
    if not decision.get("approved", True):
        log_flux_metric("paper_trader", "hold", 0, 0)
        logger.info(f"[{state['cycle_id']}] En attente validation humaine")
        return {"trade_executed": False}

    try:
        trader = PaperTrader()
        result = trader.execute(decision)
        latency_ms = int((time.time() - t0) * 1000)
        log_flux_metric("paper_trader", "ok", latency_ms, 1)
        log_decision(state["cycle_id"], state, result)
        logger.info(
            f"[{state['cycle_id']}] Trade exécuté — "
            f"{decision['action']} fill={result.get('fill_price', 0):.2f}"
        )
        return {"trade_executed": True, "trade_result": result}
    except Exception as exc:
        log_flux_metric("paper_trader", "error", 0, 0, str(exc))
        logger.error(f"[{state['cycle_id']}] Erreur exécution: {exc}")
        log_decision(state["cycle_id"], state)
        return {
            "trade_executed": False,
            "errors": state.get("errors", []) + [f"execution: {exc}"]
        }


# ===========================================================
# ROUTAGE CONDITIONNEL
# ===========================================================

def should_continue_after_news(state: ZeitgeistState) -> str:
    """Si pas de news ET pas d'AirDuTemps en cache → abort."""
    if not state.get("news_items") and not state.get("air_du_temps"):
        logger.warning(f"[{state['cycle_id']}] Aucune donnée — cycle annulé")
        return "abort"
    return "continue"


def should_execute(state: ZeitgeistState) -> str:
    """Si circuit breaker actif → forcer HOLD."""
    from decision_engine import RiskEngine
    engine = RiskEngine()
    if engine.is_circuit_breaker_active():
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
    graph.add_node("synthesize", node_synthesize)
    graph.add_node("calculate_score", node_calculate_score)
    graph.add_node("decide", node_decide)
    graph.add_node("execute", node_execute)

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
    graph.add_edge("analyze_agents", "synthesize")
    graph.add_edge("synthesize", "calculate_score")
    graph.add_edge("calculate_score", "decide")
    graph.add_conditional_edges(
        "decide",
        should_execute,
        {"execute": "execute", "hold": END}
    )
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
        errors=[],
        llm_tokens_used=0,
        cycle_duration_ms=0,
    )


def run_cycle(asset: str = "BTC/USDT", trigger: str = "scheduled") -> ZeitgeistState:
    """Exécute un cycle complet et retourne l'état final."""
    import time
    from utils.cycle_lock import try_acquire, release

    if not try_acquire(owner=f"daemon-{trigger}"):
        logger.warning(f"Cycle skipped — another cycle is already running (trigger={trigger})")
        return create_initial_state(asset)

    try:
        workflow = build_workflow()
        initial_state = create_initial_state(asset)
        t0 = time.time()
        start_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        logger.info(f"=== CYCLE {initial_state['cycle_id']} DÉBUT à {start_ts} — type: {trigger} ({asset}) ===")
        final_state = workflow.invoke(initial_state)
        duration_ms = int((time.time() - t0) * 1000)
        end_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        final_state["cycle_duration_ms"] = duration_ms
        logger.info(
            f"=== CYCLE {initial_state['cycle_id']} FIN à {end_ts} — "
            f"{duration_ms}ms | score={final_state.get('global_score', 0):.1f} | "
            f"decision={final_state.get('decision', {}).get('action', 'N/A')} | "
            f"tokens={final_state.get('llm_tokens_used', 0)} | "
            f"erreurs={len(final_state.get('errors', []))} ==="
        )
        return final_state
    finally:
        release()


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

    # RSI contribution (±20 points)
    if rsi < 30:
        score += 20   # survente → haussier
    elif rsi > 70:
        score -= 20   # surachat → baissier
    else:
        score += (50 - rsi) * 0.4

    # MACD contribution (±15 points)
    if macd > macd_signal:
        score += 15
    else:
        score -= 15

    # Funding rate contribution (±10 points)
    if funding < -0.01:
        score += 10   # funding négatif → shorts surpayés → haussier
    elif funding > 0.03:
        score -= 10   # funding très élevé → longs surpayés → baissier

    return max(0.0, min(100.0, score))
