"""
test_run_full_cycle.py — Test d'intégration du cycle complet
"""
import pytest
import sys
import os

# Ajout du répertoire racine au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ===========================================================
# FIXTURES
# ===========================================================

@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    """Injecte des variables d'environnement de test."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setenv("BINANCE_API_KEY", "test-binance-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "test-binance-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "testpassword")


@pytest.fixture
def sample_state():
    """État de test minimal."""
    from graph.workflow import create_initial_state
    return create_initial_state("BTC/USDT")


# ===========================================================
# TESTS UNITAIRES
# ===========================================================

class TestScoreCalculator:
    def test_basic_score(self):
        from decision_engine import ScoreCalculator
        calc = ScoreCalculator()
        score, breakdown = calc.calculate(
            mirofish_score=70.0,
            market_score=65.0,
            agent_scores={"fundamental": 60.0, "sentiment": 55.0},
            contrarian_score=50.0,
        )
        assert 0 <= score <= 100
        assert "mirofish" in breakdown
        assert "final_score" in breakdown

    def test_score_bounds(self):
        from decision_engine import ScoreCalculator
        calc = ScoreCalculator()
        score_max, _ = calc.calculate(100.0, 100.0, {"a": 100.0}, 100.0)
        score_min, _ = calc.calculate(0.0, 0.0, {"a": 0.0}, 0.0)
        assert score_max <= 100.0
        assert score_min >= 0.0

    def test_neutral_score(self):
        from decision_engine import ScoreCalculator
        calc = ScoreCalculator()
        score, _ = calc.calculate(50.0, 50.0, {"a": 50.0}, 50.0)
        assert 48 <= score <= 52  # autour de 50


class TestRiskEngine:
    def test_circuit_breaker_not_active_empty_history(self):
        from decision_engine import RiskEngine
        engine = RiskEngine()
        # Avec une DB vide ou inexistante, ne doit pas crasher
        result = engine.is_circuit_breaker_active()
        assert isinstance(result, bool)

    def test_position_sizing(self):
        from decision_engine import RiskEngine
        engine = RiskEngine()
        size = engine.calculate_position_size(price=65000.0)
        assert size >= 0
        assert size <= engine.capital  # jamais plus que le capital total

    def test_sl_tp_buy(self):
        from decision_engine import RiskEngine
        engine = RiskEngine()
        sl, tp = engine.calculate_sl_tp(entry_price=65000, action="BUY", atr=1000)
        assert sl < 65000  # SL en dessous pour BUY
        assert tp > 65000  # TP au-dessus pour BUY

    def test_sl_tp_sell(self):
        from decision_engine import RiskEngine
        engine = RiskEngine()
        sl, tp = engine.calculate_sl_tp(entry_price=65000, action="SELL", atr=1000)
        assert sl > 65000  # SL au-dessus pour SELL
        assert tp < 65000  # TP en dessous pour SELL


class TestDecisionEngine:
    def test_decision_buy_above_threshold(self):
        from decision_engine import DecisionEngine
        engine = DecisionEngine()
        engine.buy_threshold = 70
        engine.sell_threshold = 30
        decision = engine.decide(
            score=80.0, market_indicators={"price": 65000, "atr_14": 1000},
            agent_analyses={}, mirofish_result=None
        )
        assert decision["action"] == "BUY"

    def test_decision_sell_below_threshold(self):
        from decision_engine import DecisionEngine
        engine = DecisionEngine()
        decision = engine.decide(
            score=20.0, market_indicators={"price": 65000, "atr_14": 1000},
            agent_analyses={}, mirofish_result=None
        )
        assert decision["action"] == "SELL"

    def test_decision_hold_neutral(self):
        from decision_engine import DecisionEngine
        engine = DecisionEngine()
        decision = engine.decide(
            score=50.0, market_indicators={"price": 65000, "atr_14": 1000},
            agent_analyses={}, mirofish_result=None
        )
        assert decision["action"] == "HOLD"

    def test_decision_has_explanation(self):
        from decision_engine import DecisionEngine
        engine = DecisionEngine()
        decision = engine.decide(
            score=75.0, market_indicators={"price": 65000, "atr_14": 1000},
            agent_analyses={"synthesis": {"summary": "test summary", "risks": [], "catalysts": []}},
            mirofish_result={"score": 70, "dominant_narrative": "haussier"}
        )
        assert len(decision["explanation"]) > 20


class TestMiroFishWrapper:
    def test_prepare_seed(self):
        from agents.mirofish_wrapper import MiroFishWrapper
        wrapper = MiroFishWrapper()
        news = [{"title": "Bitcoin up", "source": "Test", "summary": "BTC rising"}]
        adt = {"themes": ["crypto"], "full_text": "Market is bullish"}
        seed = wrapper.prepare_seed(news, adt)
        assert len(seed) > 10
        assert "Bitcoin up" in seed or "Market is bullish" in seed

    def test_fallback_simulation_returns_valid_result(self):
        from agents.mirofish_wrapper import MiroFishWrapper
        wrapper = MiroFishWrapper()
        result = wrapper._run_fallback("Bitcoin is rallying hard with institutional adoption")
        assert 0 <= result["score"] <= 100
        assert "bull" in result["probas"]
        assert "bear" in result["probas"]
        assert result["n_agents_used"] == 0  # 0 = mode fallback

    def test_fallback_deterministic(self):
        from agents.mirofish_wrapper import MiroFishWrapper
        wrapper = MiroFishWrapper()
        seed = "Test seed for determinism check"
        r1 = wrapper._run_fallback(seed)
        r2 = wrapper._run_fallback(seed)
        assert r1["score"] == r2["score"]


class TestMarketDataAgent:
    def test_mock_returns_valid_structure(self):
        from agents.market_data_agent import MarketDataAgent
        indicators = MarketDataAgent._generate_mock("BTC/USDT")
        required_keys = ["symbol", "price", "rsi_14", "macd", "atr_14"]
        for key in required_keys:
            assert key in indicators, f"Clé manquante: {key}"
        assert 0 < indicators["rsi_14"] <= 100
        assert indicators["atr_14"] > 0

    def test_rsi_bounds(self):
        import numpy as np
        from agents.market_data_agent import MarketDataAgent
        closes = np.array([100 + i * 0.5 for i in range(30)])
        rsi = MarketDataAgent._rsi(closes, 14)
        assert 0 <= rsi <= 100


class TestDatabase:
    def test_init_db(self, tmp_path):
        from storage.database import init_db, log_flux_metric
        db_path = tmp_path / "test.db"
        init_db(db_path)
        assert db_path.exists()

    def test_log_flux_metric(self, tmp_path):
        from storage.database import init_db, log_flux_metric, _DB_PATH
        import storage.database as db_module
        db_path = tmp_path / "test.db"
        db_module._DB_PATH = db_path
        init_db(db_path)
        # Ne doit pas lever d'exception
        log_flux_metric("test_flux", "ok", 150, 10)


# ===========================================================
# TEST D'INTÉGRATION : cycle complet (mode mock)
# ===========================================================

class TestFullCycle:
    def test_create_initial_state(self):
        from graph.workflow import create_initial_state
        state = create_initial_state("BTC/USDT")
        assert state["asset"] == "BTC/USDT"
        assert state["global_score"] == 50.0
        assert state["trade_executed"] is False

    def test_derive_market_score(self):
        from graph.workflow import _derive_market_score
        # RSI survendu + MACD > signal → haussier
        indicators = {
            "rsi_14": 25.0, "macd": 100.0, "macd_signal": 50.0, "funding_rate": 0.0
        }
        score = _derive_market_score(indicators)
        assert score > 50  # doit être haussier

    def test_derive_market_score_none(self):
        from graph.workflow import _derive_market_score
        score = _derive_market_score(None)
        assert score == 50.0  # score neutre par défaut


# ===========================================================
# ENTRY POINT
# ===========================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
