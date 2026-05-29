"""
quant/features_daily.py — Features OHLCV causales pour timeframe DAILY (1d).

Conçu pour XAU/USD, XAG/USD, WTI/USD, EUR/USD, GBP/USD via yfinance daily.
Remplace features.py sur ce timeframe : les features intraday (hour_sin, session_*,
volume_z_20, vwap_dist) sont absentes ou inutiles sur une barre journalière.

Features produites (15 features) :
  Momentum :
    log_return_1d   — rendement du jour
    log_return_5d   — momentum 1 semaine
    log_return_20d  — momentum 1 mois

  Volatilité :
    atr_14          — ATR 14 jours (absolu)
    atr_pct         — ATR / close (normalisé)
    vol_of_vol_20   — volatilité de la volatilité (régime helper)

  Tendance :
    adx_14          — ADX 14 jours
    dist_ma50       — distance MA50 (%)
    dist_ma200      — distance MA200 (%) — tendance long terme

  Oscillateurs :
    rsi_14          — RSI 14 jours
    macd_signal     — MACD(12,26,9) − Signal line
    bb_pct_b        — Bollinger %b (20 barres)

  Structure de marché :
    donchian_high_20  — plus haut des 20 barres précédentes
    donchian_low_20   — plus bas des 20 barres précédentes

  Saisonnalité weekly :
    day_sin, day_cos  — encodage cyclique du jour de semaine (0=lun … 4=ven)

Toutes les features sont strictement causales (shift(1) ou rolling terminé à t-1).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ─── Primitives partagées avec features.py ────────────────────────────────────

def _true_range(df: pd.DataFrame) -> pd.Series:
    high, low, prev_close = df["high"], df["low"], df["close"].shift(1)
    return pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return _true_range(df).rolling(period, min_periods=period).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move   = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm  = np.where((up_move > down_move)   & (up_move > 0),   up_move,   0.0)
    minus_dm = np.where((down_move > up_move)   & (down_move > 0), down_move, 0.0)
    tr   = _true_range(df)
    atr_ = tr.rolling(period, min_periods=period).mean()
    plus_di  = 100 * pd.Series(plus_dm,  index=df.index).rolling(period, min_periods=period).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(period, min_periods=period).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period, min_periods=period).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False, min_periods=period).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False, min_periods=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def _macd_histogram(close: pd.Series,
                    fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    """MACD − Signal line (histogram). Valeur > 0 = momentum haussier."""
    ema_fast   = close.ewm(span=fast,   adjust=False, min_periods=fast).mean()
    ema_slow   = close.ewm(span=slow,   adjust=False, min_periods=slow).mean()
    macd_line  = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return macd_line - signal_line


# ─── API principale ───────────────────────────────────────────────────────────

def compute_features_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule les features causales pour timeframe daily.

    Args:
        df: DataFrame OHLCV indexé DatetimeIndex, colonnes [open, high, low, close, volume].
            Le volume peut être NaN/0 pour FX/métaux — aucune feature de volume n'est calculée.

    Returns:
        DataFrame de features alignées sur le même index.
        Les premières ~200 lignes contiennent des NaN (warmup des fenêtres).
    """
    out = pd.DataFrame(index=df.index)
    close = df["close"]
    log_close = np.log(close.replace(0, np.nan))

    # ── Momentum ──────────────────────────────────────────────────────────────
    out["log_return_1d"]  = log_close.diff(1)
    out["log_return_5d"]  = log_close.diff(5)
    out["log_return_20d"] = log_close.diff(20)

    # ── Volatilité ────────────────────────────────────────────────────────────
    atr14 = _atr(df, 14)
    out["atr_14"]       = atr14
    out["atr_pct"]      = atr14 / close.replace(0, np.nan)
    out["vol_of_vol_20"] = atr14.pct_change().rolling(20, min_periods=20).std()

    # ── Tendance ──────────────────────────────────────────────────────────────
    out["adx_14"] = _adx(df, 14)

    ma50  = close.rolling(50,  min_periods=50).mean()
    ma200 = close.rolling(200, min_periods=200).mean()
    out["dist_ma50"]  = (close - ma50)  / ma50.replace(0, np.nan)
    out["dist_ma200"] = (close - ma200) / ma200.replace(0, np.nan)

    # ── Oscillateurs ──────────────────────────────────────────────────────────
    out["rsi_14"]      = _rsi(close, 14)
    out["macd_signal"] = _macd_histogram(close, 12, 26, 9)

    # Bollinger %b — causal : shift(1) sur la fenêtre
    bb_mid = close.shift(1).rolling(20, min_periods=20).mean()
    bb_std = close.shift(1).rolling(20, min_periods=20).std()
    bb_upper = bb_mid + 2.0 * bb_std
    bb_lower = bb_mid - 2.0 * bb_std
    out["bb_pct_b"] = (close - bb_lower) / (bb_upper - bb_lower + 1e-9)

    # ── Structure de marché ───────────────────────────────────────────────────
    # Donchian sur les 20 barres précédentes (shift(1) = causal strict)
    out["donchian_high_20"] = df["high"].shift(1).rolling(20, min_periods=20).max()
    out["donchian_low_20"]  = df["low"].shift(1).rolling(20, min_periods=20).min()

    # ── Saisonnalité weekly ───────────────────────────────────────────────────
    try:
        dow = df.index.dayofweek.astype(float)  # 0=lun … 4=ven (5,6 = weekend)
        out["day_sin"] = (np.sin(2 * np.pi * dow / 5) + 1.0) / 2.0
        out["day_cos"] = (np.cos(2 * np.pi * dow / 5) + 1.0) / 2.0
    except AttributeError:
        pass

    return out


def make_target_direction_daily(df: pd.DataFrame, horizon: int = 5) -> pd.Series:
    """Cible binaire : direction du prix dans `horizon` jours (1 = up, 0 = down).

    Args:
        df: OHLCV daily
        horizon: nombre de barres journalières (défaut 5 = 1 semaine)

    Returns:
        Série binaire ; la fin de la série est NaN (futur inconnu à exclure du train).
    """
    fwd = df["close"].shift(-horizon) / df["close"] - 1.0
    return (fwd > 0).astype("float").where(fwd.notna())


# ─── Colonnes utilisées par le SignalModel daily ──────────────────────────────
DAILY_FEATURE_COLS = [
    # Normalisées (_q suffix ajouté par normalize_features)
    "log_return_1d_q", "log_return_5d_q", "log_return_20d_q",
    "atr_pct_q", "adx_14_q", "vol_of_vol_20_q",
    "dist_ma50_q", "dist_ma200_q",
    "rsi_14_q", "macd_signal_q", "bb_pct_b_q",
    # Brutes (causalité structurelle, pas besoin de normalisation)
    "day_sin", "day_cos",
]

DAILY_NORM_COLS = [
    "log_return_1d", "log_return_5d", "log_return_20d",
    "atr_pct", "adx_14", "vol_of_vol_20",
    "dist_ma50", "dist_ma200",
    "rsi_14", "macd_signal", "bb_pct_b",
]
