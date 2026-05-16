"""
Atlas Trader V2 — Quant Core
=============================

Module quantitatif isolé, construit selon les recommandations consensuelles
des 5 IA (Grok, ChatGPT, Claude Opus 4.7, Gemini Pro 3.1, DeepSeek).

Principes fondateurs :
- Minimalisme : 3 couches seulement (régime, signal, décision).
- Causalité stricte : aucune fuite temporelle (HMM filtering, quantiles backward).
- Pas de LLM dans la boucle de décision.
- Validation OOS avant tout passage live (walk-forward + block bootstrap).
"""

from quant.features import compute_features
from quant.normalization import rolling_quantile_normalize
from quant.regime import RegimeDetector
from quant.signal_model import SignalModel
from quant.strategy import BaselineStrategy, decide
from quant.risk import RiskManager
from quant.backtest import Backtester, BacktestResult, buy_and_hold
from quant.pipeline import PipelineConfig, PipelineArtifacts, run_pipeline, run_baseline
from quant.validation import (
    walk_forward_split,
    block_bootstrap_permutation_test,
    deflated_sharpe_ratio,
    ablation_test,
)

__all__ = [
    "compute_features",
    "rolling_quantile_normalize",
    "RegimeDetector",
    "SignalModel",
    "BaselineStrategy",
    "decide",
    "RiskManager",
    "Backtester",
    "BacktestResult",
    "buy_and_hold",
    "PipelineConfig",
    "PipelineArtifacts",
    "run_pipeline",
    "run_baseline",
    "walk_forward_split",
    "block_bootstrap_permutation_test",
    "deflated_sharpe_ratio",
    "ablation_test",
]

__version__ = "2.0.0-dev"
