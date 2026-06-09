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

    Optimisation : utilise NumPy sliding window + comparaison vectorisée
    au lieu de rolling().apply() + np.sort() qui est O(n × w log w).

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

    vals = series.values.astype(np.float64)
    n = len(vals)
    result = np.full(n, np.nan, dtype=np.float64)

    if n <= window:
        return pd.Series(result, index=series.index)

    # Approche vectorisée : pour chaque position i ≥ window,
    # percentile = proportion des valeurs passées < valeur courante
    # Utilise np.lib.stride_tricks.sliding_window_view pour O(1) extraction
    from numpy.lib.stride_tricks import sliding_window_view

    # Construire les fenêtres glissantes : shape (n - window, window)
    windows = sliding_window_view(vals, window_shape=window)

    # Pour chaque fenêtre, comparer chaque élément au dernier élément de la fenêtre SUIVANTE
    # La fenêtre i contient vals[i : i+window], on compare à vals[i+window]
    future_vals = vals[window:]  # shape (n - window,)

    # Comparaison vectorisée : pour chaque fenêtre, count < future_val
    # Petit hack pour éviter O(n*w) memory:
    # On traite par batch si nécessaire, mais pour crypto ~25K barres ça tient
    if n - window > 20000:
        # Gros dataset : traiter par blocs de 5000 fenêtres
        batch_size = 5000
        for start in range(0, n - window, batch_size):
            end = min(start + batch_size, n - window)
            batch_windows = windows[start:end]       # (batch, window)
            batch_future = future_vals[start:end]    # (batch,)
            # Pour chaque fenêtre, count past values < future value
            # On ignore NaN dans la fenêtre
            valid_mask = ~np.isnan(batch_windows)
            # Comparaison broadcast : (batch, window) < (batch, 1)
            less_than = (batch_windows < batch_future[:, np.newaxis]) & valid_mask
            valid_counts = valid_mask.sum(axis=1)  # (batch,)
            less_counts = less_than.sum(axis=1)    # (batch,)
            # Éviter division par zéro
            pct = np.where(
                valid_counts >= min_periods,
                less_counts / valid_counts,
                np.nan,
            )
            result[window + start:window + end] = pct
    else:
        # Petit dataset : tout en une fois
        valid_mask = ~np.isnan(windows)
        less_than = (windows < future_vals[:, np.newaxis]) & valid_mask
        valid_counts = valid_mask.sum(axis=1)
        less_counts = less_than.sum(axis=1)
        pct = np.where(
            valid_counts >= min_periods,
            less_counts / valid_counts,
            np.nan,
        )
        result[window:] = pct

    return pd.Series(result, index=series.index)


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
