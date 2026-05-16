"""
quant/pipeline.py — Pipeline complet bout en bout.

Compose toutes les briques en un seul appel : fetch → features → régime →
signal → décisions → backtest. Sert d'orchestrateur unique pour les tests
walk-forward et l'inférence live future.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

import pandas as pd

from quant.backtest import Backtester, BacktestResult, buy_and_hold
from quant.features import compute_features, make_target_direction
from quant.normalization import normalize_features
from quant.regime import RegimeDetector
from quant.risk import RiskManager, RiskParams
from quant.signal_model import SignalModel
from quant.strategy import Action, BaselineStrategy, decide

logger = logging.getLogger("quant.pipeline")


DEFAULT_FEATURE_COLS = [
    "log_return_1_q",
    "log_return_4_q",
    "log_return_24_q",
    "atr_pct_q",
    "adx_14_q",
    "dist_ma50_q",
    "volume_z_20_q",
]


@dataclass
class PipelineConfig:
    horizon_bars: int = 4
    norm_window: int = 30 * 96
    p_up_threshold: float = 0.55
    p_dn_threshold: float = 0.45
    use_hmm: bool = True
    use_signal_model: bool = True
    feature_cols: Sequence[str] = field(default_factory=lambda: list(DEFAULT_FEATURE_COLS))
    initial_capital: float = 10_000.0
    fee_rate: float = 0.0005
    slippage_rate: float = 0.0002


@dataclass
class PipelineArtifacts:
    features: pd.DataFrame
    features_norm: pd.DataFrame
    regime: pd.Series
    proba_up: pd.Series
    actions: pd.Series
    backtest: BacktestResult


def run_pipeline(
    ohlcv: pd.DataFrame,
    train_idx: pd.DatetimeIndex,
    test_idx: pd.DatetimeIndex,
    config: PipelineConfig | None = None,
) -> PipelineArtifacts:
    """Exécute pipeline sur train (fit) puis test (predict + backtest).

    Args:
        ohlcv: OHLCV complet couvrant train + test
        train_idx: index des barres d'entraînement
        test_idx: index des barres de test (OOS)
        config: configuration

    Returns:
        Artefacts pipeline + résultat backtest sur test_idx uniquement.
    """
    cfg = config or PipelineConfig()

    # 1. Features (sur tout l'historique pour éviter cold start sur test)
    feats_raw = compute_features(ohlcv)
    feats_norm = normalize_features(
        feats_raw,
        window=cfg.norm_window,
        columns=["log_return_1", "log_return_4", "log_return_24", "atr_pct", "adx_14", "dist_ma50", "volume_z_20"],
    )
    feats = pd.concat([feats_raw, feats_norm], axis=1)

    # 2. Détecteur de régime — FIT sur train uniquement
    regime = RegimeDetector(use_hmm=cfg.use_hmm).fit(feats.loc[train_idx])
    regime_series = regime.predict(feats)

    # 3. Modèle de signal — FIT sur train uniquement
    proba_up = pd.Series(index=feats.index, dtype="float64")
    if cfg.use_signal_model:
        y = make_target_direction(ohlcv, horizon=cfg.horizon_bars)
        X_train = feats.loc[train_idx, cfg.feature_cols]
        y_train = y.loc[train_idx]
        # Exclure les barres dont la cible n'est pas observable (fin de train)
        valid = X_train.notna().all(axis=1) & y_train.notna()
        try:
            model = SignalModel(feature_cols=cfg.feature_cols).fit(
                X_train.loc[valid], y_train.loc[valid]
            )
            proba_up = model.predict_proba(feats[cfg.feature_cols])
        except Exception as exc:
            logger.error(f"SignalModel échec ({exc}) — fallback P=0.5.")
            proba_up.loc[:] = 0.5
    else:
        proba_up.loc[:] = 0.5

    # 4. Décisions barre par barre
    actions = pd.Series(index=feats.index, dtype="object")
    for ts in feats.index:
        d = decide(
            probability_up=float(proba_up.loc[ts]) if pd.notna(proba_up.loc[ts]) else None,
            regime_trending=bool(regime_series.loc[ts] == 1.0) if pd.notna(regime_series.loc[ts]) else False,
            upper_threshold=cfg.p_up_threshold,
            lower_threshold=cfg.p_dn_threshold,
        )
        actions.loc[ts] = d.action

    # 5. Backtest sur test_idx uniquement
    test_ohlcv = ohlcv.loc[test_idx]
    test_actions = actions.loc[test_idx]
    test_atr = feats["atr_14"].loc[test_idx]

    bt = Backtester(
        initial_capital=cfg.initial_capital,
        fee_rate=cfg.fee_rate,
        slippage_rate=cfg.slippage_rate,
        risk_manager=RiskManager(RiskParams()),
    )
    result = bt.run(test_ohlcv, test_actions, test_atr)

    return PipelineArtifacts(
        features=feats_raw,
        features_norm=feats_norm,
        regime=regime_series,
        proba_up=proba_up,
        actions=actions,
        backtest=result,
    )


def run_baseline(ohlcv: pd.DataFrame) -> BacktestResult:
    """Stratégie baseline ultra-simple (breakout Donchian) sans modèle ni régime."""
    feats = compute_features(ohlcv)
    actions = BaselineStrategy().signals(feats)
    bt = Backtester()
    return bt.run(ohlcv, actions, feats["atr_14"])
