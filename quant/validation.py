"""
quant/validation.py — Validation impitoyable (anti-overfit, anti-data-mining).

Outils :
- walk_forward_split : segmente une série temporelle en folds chronologiques.
- block_bootstrap_permutation_test : test de significativité préservant la corrélation.
- deflated_sharpe_ratio : corrige le Sharpe pour le multiple testing (Bailey & López).
- ablation_test : compare la stratégie complète à des variantes amputées.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np
import pandas as pd

logger = logging.getLogger("quant.validation")


def walk_forward_split(
    index: pd.DatetimeIndex,
    train_months: int = 6,
    test_months: int = 3,
    step_months: int | None = None,
) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    """Génère des paires (train_idx, test_idx) chronologiques sans overlap.

    Args:
        index: index temporel complet
        train_months: durée de la fenêtre d'entraînement
        test_months: durée de la fenêtre de test
        step_months: décalage entre folds (défaut = test_months pour folds disjoints)
    """
    if step_months is None:
        step_months = test_months
    start = index.min()
    end = index.max()
    cursor = start
    train_delta = pd.DateOffset(months=train_months)
    test_delta = pd.DateOffset(months=test_months)
    step_delta = pd.DateOffset(months=step_months)

    while cursor + train_delta + test_delta <= end:
        train_start = cursor
        train_end = cursor + train_delta
        test_start = train_end
        test_end = test_start + test_delta

        train_idx = index[(index >= train_start) & (index < train_end)]
        test_idx = index[(index >= test_start) & (index < test_end)]
        if len(train_idx) > 0 and len(test_idx) > 0:
            yield train_idx, test_idx
        cursor = cursor + step_delta


def block_bootstrap_permutation_test(
    returns: pd.Series,
    metric_fn: Callable[[pd.Series], float],
    n_permutations: int = 1000,
    block_size: int = 96,  # 1 jour en 15min
    seed: int = 42,
) -> dict:
    """Test de permutation par blocs (préserve l'autocorrélation locale).

    Hypothèse H0 : la séquence des rendements est interchangeable par blocs
    (i.e. la stratégie n'extrait aucun signal au-delà du hasard).

    Args:
        returns: série de rendements (de la stratégie)
        metric_fn: fonction qui calcule la métrique d'intérêt (ex. Sharpe)
        n_permutations: nombre de permutations
        block_size: taille des blocs (en barres) — préserve l'autocorrélation
        seed: graine RNG

    Returns:
        {observed, p_value, distribution_quantiles}
    """
    rng = np.random.default_rng(seed)
    observed = metric_fn(returns)
    rets = returns.dropna().values
    n = len(rets)
    n_blocks = max(1, n // block_size)

    perm_metrics = np.empty(n_permutations)
    for k in range(n_permutations):
        # Découpe en blocs, mélange
        block_starts = np.arange(0, n_blocks * block_size, block_size)
        rng.shuffle(block_starts)
        perm = np.concatenate([rets[s : s + block_size] for s in block_starts])
        perm_series = pd.Series(perm)
        perm_metrics[k] = metric_fn(perm_series)

    # p-value : prob qu'un tirage aléatoire fasse aussi bien ou mieux
    p_value = float(np.mean(perm_metrics >= observed))
    return {
        "observed": float(observed),
        "p_value": p_value,
        "quantiles": {
            "p05": float(np.quantile(perm_metrics, 0.05)),
            "p50": float(np.quantile(perm_metrics, 0.50)),
            "p95": float(np.quantile(perm_metrics, 0.95)),
        },
        "n_permutations": n_permutations,
    }


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    n_observations: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Sharpe dégonflé (Bailey & López de Prado, 2014).

    Corrige le biais lié au multiple testing et à la non-normalité des rendements.

    Returns:
        Probabilité que le Sharpe observé soit > 0 après ajustement (∈ [0, 1]).
    """
    from math import sqrt
    from scipy.stats import norm

    # Sharpe attendu maximum sous H0 (selon López de Prado)
    e = 0.5772156649  # Euler-Mascheroni
    sr_max_expected = sqrt(2 * np.log(max(n_trials, 1))) * (1 - e / sqrt(2 * np.log(max(n_trials, 1))) - e)
    # Z-score ajusté
    num = (observed_sharpe - sr_max_expected) * sqrt(n_observations - 1)
    den = sqrt(1 - skewness * observed_sharpe + (kurtosis - 1) / 4 * observed_sharpe ** 2)
    if den <= 0:
        return float("nan")
    return float(norm.cdf(num / den))


@dataclass
class AblationResult:
    name: str
    sharpe: float
    total_return: float
    max_dd: float
    n_trades: int


def ablation_test(
    run_variant: Callable[[str], "AblationResult"],
    variants: list[str] = None,
) -> pd.DataFrame:
    """Compare des variantes amputées au modèle complet.

    Args:
        run_variant: fonction qui prend un nom de variante et retourne un AblationResult
        variants: liste de variantes à tester (défaut : ['full', 'no_regime', 'no_signal', 'baseline'])

    Returns:
        DataFrame récapitulatif.
    """
    if variants is None:
        variants = ["full", "no_regime", "no_signal", "baseline_breakout"]
    rows = []
    for v in variants:
        try:
            r = run_variant(v)
            rows.append(
                {
                    "variant": r.name,
                    "sharpe": r.sharpe,
                    "total_return": r.total_return,
                    "max_dd": r.max_dd,
                    "n_trades": r.n_trades,
                }
            )
        except Exception as exc:
            logger.error(f"Variante {v} a échoué: {exc}")
            rows.append({"variant": v, "sharpe": np.nan, "error": str(exc)})
    return pd.DataFrame(rows)
