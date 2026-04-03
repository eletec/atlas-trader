"""
tests/test_decision_engine.py — Tests unitaires du core décisionnel (P8).
Couvre ScoreCalculator, ScoringWeights, RiskEngine et DecisionEngine.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ajoute le dossier parent au path pour les imports relatifs
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def default_settings():
    return {
        "scoring": {"weights": {"mirofish": 0.40, "market": 0.30,
                                "agents": 0.20, "contrarian": 0.10}},
        "risk": {"mode": "balanced", "kelly_max_fraction": 0.25,
                 "max_drawdown_pct": 15.0, "position_size_pct": 5.0,
                 "atr_multiplier_sl": 2.0, "atr_multiplier_tp": 3.0},
        "exchange": {"paper_capital_usd": 10000.0},
        "thresholds": {"buy": 62, "sell": 38},
    }


# ─── ScoringWeights ────────────────────────────────────────────────────────

def test_weights_sum_to_one():
    from decision_engine import ScoringWeights
    w = ScoringWeights(mirofish=0.40, market=0.30, agents=0.20, contrarian=0.10)
    w.validate()  # should not raise


def test_weights_invalid_sum_raises():
    from decision_engine import ScoringWeights
    w = ScoringWeights(mirofish=0.50, market=0.30, agents=0.20, contrarian=0.10)
    with pytest.raises(ValueError, match="sommer"):
        w.validate()


def test_weights_out_of_bounds_raises():
    from decision_engine import ScoringWeights
    # 0.70 > MAX (0.60)
    w = ScoringWeights(mirofish=0.70, market=0.10, agents=0.10, contrarian=0.10)
    with pytest.raises(ValueError, match="bornes"):
        w.validate()


# ─── ScoreCalculator ───────────────────────────────────────────────────────

def test_score_neutral_inputs(default_settings):
    """50/50/50/50 → score ~50."""
    from decision_engine import ScoreCalculator
    with patch("decision_engine.load_settings", return_value=default_settings):
        calc = ScoreCalculator()
    score, breakdown = calc.calculate(50.0, 50.0, {"a": 50.0, "b": 50.0}, 50.0)
    assert 48 <= score <= 52, f"Score neutre attendu ~50, obtenu {score}"


def test_score_full_bullish(default_settings):
    """100/100/100/100 → score = 100."""
    from decision_engine import ScoreCalculator
    with patch("decision_engine.load_settings", return_value=default_settings):
        calc = ScoreCalculator()
    score, _ = calc.calculate(100.0, 100.0, {"a": 100.0}, 100.0)
    assert score == 100.0


def test_score_full_bearish(default_settings):
    """0/0/0/0 → score = 0."""
    from decision_engine import ScoreCalculator
    with patch("decision_engine.load_settings", return_value=default_settings):
        calc = ScoreCalculator()
    score, _ = calc.calculate(0.0, 0.0, {"a": 0.0}, 0.0)
    assert score == 0.0


def test_score_clamped(default_settings):
    """Valeurs hors-limites restent dans [0, 100]."""
    from decision_engine import ScoreCalculator
    with patch("decision_engine.load_settings", return_value=default_settings):
        calc = ScoreCalculator()
    score, _ = calc.calculate(150.0, 120.0, {"a": 999.0}, 200.0)
    assert 0 <= score <= 100


def test_breakdown_keys(default_settings):
    from decision_engine import ScoreCalculator
    with patch("decision_engine.load_settings", return_value=default_settings):
        calc = ScoreCalculator()
    _, breakdown = calc.calculate(60.0, 55.0, {"mkt": 58.0}, 45.0)
    for key in ("mirofish", "market", "agents", "contrarian", "final_score"):
        assert key in breakdown


# ─── RiskEngine ────────────────────────────────────────────────────────────

def test_circuit_breaker_inactive_when_no_history(default_settings):
    from decision_engine import RiskEngine
    with patch("decision_engine.load_settings", return_value=default_settings), \
         patch("storage.database.get_pnl_history", return_value=[]):
        engine = RiskEngine()
    with patch("storage.database.get_pnl_history", return_value=[]):
        assert engine.is_circuit_breaker_active() is False


def test_circuit_breaker_active_on_high_drawdown(default_settings):
    """Cumulative PnL = -1600 sur capital 10 000 → drawdown 16% > max_dd 15%."""
    from decision_engine import RiskEngine
    fake_history = [{"result_24h": -1600}]
    with patch("decision_engine.load_settings", return_value=default_settings), \
         patch("storage.database.get_pnl_history", return_value=fake_history):
        engine = RiskEngine()
    with patch("storage.database.get_pnl_history", return_value=fake_history):
        assert engine.is_circuit_breaker_active() is True


def test_circuit_breaker_inactive_below_threshold(default_settings):
    """Cumulative PnL = -1400 sur 10 000 → drawdown 14% < max_dd 15%."""
    from decision_engine import RiskEngine
    fake_history = [{"result_24h": -1400}]
    with patch("decision_engine.load_settings", return_value=default_settings), \
         patch("storage.database.get_pnl_history", return_value=fake_history):
        engine = RiskEngine()
    with patch("storage.database.get_pnl_history", return_value=fake_history):
        assert engine.is_circuit_breaker_active() is False
