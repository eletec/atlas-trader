"""
quant/normalization.py — Normalisation par quantiles glissants STRICTEMENT backward-looking.

Critique DeepSeek + ChatGPT + Grok : la normalisation à l'instant t doit utiliser
EXCLUSIVEMENT les valeurs ≤ t-1. Un quantile centré ou même incluant t lui-même
contamine le test OOS.

Implémentation : pour chaque point t, calcule le rang percentile de x[t] dans la
fenêtre [t-window, t-1]. Le shift(1) avant rolling est crucial.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_quantile_normalize(
    series: pd.Series,
    window: int = 30 * 96,  # 30 jours × 96 bougies 15min
    min_periods: int | None = None,
) -> pd.Series:
    """Transforme une série en son rang percentile glissant ∈ [0, 1].

    Pour chaque point t : rang de x[t] parmi les `window` valeurs précédentes
    (strictement antérieures à t, pas de leakage).

    Args:
        series: série d'entrée
        window: taille de la fenêtre glissante (en nombre de barres)
        min_periods: minimum de points requis pour calculer (défaut: window // 4)

    Returns:
        Série de mêmes dimensions, valeurs ∈ [0, 1] (ou NaN tant que la fenêtre
        n'est pas remplie).
    """
    if min_periods is None:
        min_periods = max(30, window // 4)

    # ATTENTION : rank() inclut la valeur courante. On veut le rang de x[t] dans
    # l'historique STRICTEMENT antérieur. On utilise donc une rolling-apply qui,
    # pour chaque fenêtre [t-window+1 : t] (incluant t), calcule le rang de x[t]
    # parmi les valeurs PRÉCÉDENTES uniquement.
    def _rank_of_last(window_vals: np.ndarray) -> float:
        if len(window_vals) < 2:
            return np.nan
        current = window_vals[-1]
        past = window_vals[:-1]
        valid = past[~np.isnan(past)]
        if len(valid) < min_periods - 1:
            return np.nan
        if np.isnan(current):
            return np.nan
        # rang percentile de `current` parmi `valid`
        return float(np.searchsorted(np.sort(valid), current, side="right")) / len(valid)

    return series.rolling(window=window + 1, min_periods=min_periods + 1).apply(
        _rank_of_last, raw=True
    )


def normalize_features(
    features: pd.DataFrame,
    window: int = 30 * 96,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Applique `rolling_quantile_normalize` à un ensemble de colonnes.

    Args:
        features: DataFrame de features brutes
        window: taille de la fenêtre glissante
        columns: liste de colonnes à normaliser (défaut : toutes)

    Returns:
        DataFrame de mêmes dimensions, suffixe "_q" ajouté aux colonnes normalisées.
    """
    cols = columns or list(features.columns)
    out = pd.DataFrame(index=features.index)
    for col in cols:
        out[f"{col}_q"] = rolling_quantile_normalize(features[col], window=window)
    return out
