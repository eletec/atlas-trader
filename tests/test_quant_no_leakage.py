"""
tests/test_quant_no_leakage.py — Tests anti-fuite temporelle.

Garantit que :
1. Les features à l'instant t ne dépendent jamais de t+1.
2. La normalisation par quantiles glissants est strictement backward-looking.
3. Le détecteur de régime en fallback ne change pas son passé quand on ajoute du futur.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False
    class _PytestStub:
        @staticmethod
        def fixture(*args, **kwargs):
            def deco(fn):
                return fn
            return deco
    pytest = _PytestStub()

from quant.data_loader import synthetic_ohlcv
from quant.features import compute_features
from quant.normalization import rolling_quantile_normalize
from quant.regime import RegimeDetector


@pytest.fixture(scope="module")
def ohlcv():
    return synthetic_ohlcv(n_bars=1000, seed=7)


def test_features_no_future_dependency(ohlcv):
    """compute_features(df[:t]) doit égaler compute_features(df)[:t] sur les lignes communes."""
    cutoff = 600
    full = compute_features(ohlcv)
    partial = compute_features(ohlcv.iloc[:cutoff])
    common = partial.index.intersection(full.index)
    for col in partial.columns:
        full_vals = full.loc[common, col].dropna()
        part_vals = partial.loc[common, col].dropna()
        shared = full_vals.index.intersection(part_vals.index)
        if len(shared) == 0:
            continue
        np.testing.assert_allclose(
            full_vals.loc[shared].values,
            part_vals.loc[shared].values,
            rtol=1e-9,
            atol=1e-9,
            err_msg=f"Fuite future détectée sur {col}",
        )


def test_normalization_strictly_backward(ohlcv):
    """Le quantile à l'instant t doit être identique qu'on connaisse ou non t+1, t+2, …"""
    feats = compute_features(ohlcv)
    series = feats["log_return_1"].dropna()
    cutoff = 500
    full = rolling_quantile_normalize(series, window=100)
    partial = rolling_quantile_normalize(series.iloc[:cutoff], window=100)
    common = partial.index.intersection(full.index)
    np.testing.assert_allclose(
        full.loc[common].fillna(-1).values,
        partial.loc[common].fillna(-1).values,
        rtol=1e-9,
        atol=1e-9,
        err_msg="Quantile rolling contaminé par le futur",
    )


def test_regime_fallback_no_lookahead(ohlcv):
    """Le régime à t en mode threshold doit être stable quand on étend les données."""
    feats = compute_features(ohlcv)
    cutoff = 500
    full_reg = RegimeDetector(use_hmm=False).fit(feats.iloc[:cutoff]).predict(feats)
    partial_reg = RegimeDetector(use_hmm=False).fit(feats.iloc[:cutoff]).predict(feats.iloc[:cutoff])
    common = partial_reg.dropna().index.intersection(full_reg.dropna().index)
    np.testing.assert_array_equal(
        full_reg.loc[common].values,
        partial_reg.loc[common].values,
        err_msg="Détecteur de régime threshold a regardé le futur",
    )


def test_decide_dead_zone():
    from quant.strategy import Action, decide
    d = decide(probability_up=0.50, regime_trending=True)
    assert d.action == Action.FLAT
    d = decide(probability_up=0.60, regime_trending=True)
    assert d.action == Action.LONG
    d = decide(probability_up=0.40, regime_trending=True)
    assert d.action == Action.SHORT
    d = decide(probability_up=0.99, regime_trending=False)
    assert d.action == Action.FLAT  # mean-reverting → on ne trade pas


def test_risk_position_sizing():
    from quant.risk import RiskManager, RiskParams
    params = RiskParams()  # fraction=0.75%, SL=2.5×ATR, TP=3.5×ATR
    rm = RiskManager(params)
    pos = rm.compute_position(side="long", entry_price=50_000, atr_value=500, capital=10_000)
    # risque = 75€ (0.75%) / stop = 1250€ (2.5×ATR) → size = 0.06
    expected_size = (10_000 * params.fraction_per_trade) / (params.stop_loss_atr_mult * 500)
    assert abs(pos.size_units - expected_size) < 1e-9
    assert pos.stop_loss  == 50_000 - params.stop_loss_atr_mult   * 500
    assert pos.take_profit == 50_000 + params.take_profit_atr_mult * 500
