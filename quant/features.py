"""
quant/features.py — Features OHLCV pures (sans look-ahead).

Toutes les features sont strictement causales : elles n'utilisent que les bougies
fermées jusqu'à l'instant t (inclus). Aucune feature à l'instant t ne dépend de t+1.

Features produites :
- log_return_1, log_return_4, log_return_24 — momentum multi-horizon
- atr_14, atr_pct — volatilité absolue et normalisée
- adx_14 — force de tendance directionnelle
- dist_ma50 — distance au MA50 en % (>0 = au-dessus)
- donchian_high_20, donchian_low_20 — breakout levels
- volume_z_20 — z-score du volume sur 20 bougies
- vol_of_vol_20 — volatilité de la volatilité (régime detection helper)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = _true_range(df)
    return tr.rolling(period, min_periods=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index — force de la tendance (0-100)."""
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = _true_range(df)
    atr_ = tr.rolling(period, min_periods=period).mean()

    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(period, min_periods=period).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(period, min_periods=period).mean() / atr_

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period, min_periods=period).mean()


def donchian_channels(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Donchian high/low sur N bougies PRÉCÉDENTES (shift(1) pour causalité stricte)."""
    high = df["high"].shift(1).rolling(period, min_periods=period).max()
    low = df["low"].shift(1).rolling(period, min_periods=period).min()
    return pd.DataFrame({"donchian_high": high, "donchian_low": low})


def compute_features(df: pd.DataFrame, extra_ohlcv: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """Calcule l'ensemble des features causales sur un OHLCV.

    Args:
        df: DataFrame OHLCV indexé timestamp (open/high/low/close/volume)
        extra_ohlcv: dictionnaire d'OHLCV supplémentaires, ex. {"dxy": dxy_df}
                     Utilisé pour les features inter-marchés (Q14).

    Returns:
        DataFrame de features alignées sur le même index. Les premières lignes
        contiennent des NaN tant que les fenêtres ne sont pas remplies — c'est voulu.
    """
    out = pd.DataFrame(index=df.index)

    close = df["close"]
    log_close = np.log(close)

    # Momentum multi-horizon (rendements logarithmiques)
    out["log_return_1"] = log_close.diff(1)
    out["log_return_4"] = log_close.diff(4)
    out["log_return_24"] = log_close.diff(24)

    # Volatilité
    atr_14 = atr(df, 14)
    out["atr_14"] = atr_14
    out["atr_pct"] = atr_14 / close

    # Force de tendance
    out["adx_14"] = adx(df, 14)

    # Distance au MA50 (en pourcentage)
    ma_50 = close.rolling(50, min_periods=50).mean()
    out["dist_ma50"] = (close - ma_50) / ma_50

    # Donchian breakout levels (déjà shift(1))
    donch = donchian_channels(df, 20)
    out["donchian_high_20"] = donch["donchian_high"]
    out["donchian_low_20"] = donch["donchian_low"]
    out["breakout_up"] = (close > donch["donchian_high"]).astype(int)
    out["breakout_dn"] = (close < donch["donchian_low"]).astype(int)

    # Volume z-score (sur 20 bougies passées strictement)
    vol_mean = df["volume"].shift(1).rolling(20, min_periods=20).mean()
    vol_std = df["volume"].shift(1).rolling(20, min_periods=20).std()
    out["volume_z_20"] = (df["volume"] - vol_mean) / vol_std.replace(0, np.nan)

    # Volatilité de la volatilité (régime helper)
    out["vol_of_vol_20"] = atr_14.pct_change().rolling(20, min_periods=20).std()

    # C.1 VWAP distance normalisée par ATR (causal — shift(1)) — 3/3 IA, haute priorité
    typical_price = (df["high"] + df["low"] + close) / 3.0
    vwap_num = (typical_price * df["volume"]).shift(1).rolling(20, min_periods=20).sum()
    vwap_den = df["volume"].shift(1).rolling(20, min_periods=20).sum()
    vwap_20 = vwap_num / (vwap_den + 1e-9)
    out["vwap_dist_20"] = (close - vwap_20) / (atr_14 + 1e-9)   # >0 = au-dessus du VWAP

    # C.2 Bollinger %b sur 20 barres (causal — shift(1)) — GPT + DeepSeek
    bb_mid = close.shift(1).rolling(20, min_periods=20).mean()
    bb_std = close.shift(1).rolling(20, min_periods=20).std()
    bb_upper = bb_mid + 2.0 * bb_std
    bb_lower = bb_mid - 2.0 * bb_std
    out["bb_pct_b"] = (close - bb_lower) / (bb_upper - bb_lower + 1e-9)  # ~[0,1]

    # C.3 OBV proxy rolling causal — ratio volume signé sur 20 barres (Grok + DeepSeek)
    # Pas d'OBV cumulatif (non-stationnaire) — proxy normalisé ∈ [-1, 1] approx.
    signed_vol = df["volume"] * np.sign(df["close"].diff())
    out["obv_proxy_20"] = (
        signed_vol.shift(1).rolling(20, min_periods=20).sum()
        / (df["volume"].shift(1).rolling(20, min_periods=20).sum() + 1e-9)
    )

    # Features calendaires — déterministes, strictement causales (Phase 3.1)
    # Index supposé DatetimeIndex
    try:
        hour = df.index.hour
        dow = df.index.dayofweek
        out["hour_sin"] = (np.sin(2 * np.pi * hour / 24) + 1.0) / 2.0   # ∈ [0, 1]
        out["hour_cos"] = (np.cos(2 * np.pi * hour / 24) + 1.0) / 2.0   # ∈ [0, 1]
        out["is_weekend"] = (dow >= 5).astype(float)                       # 0 ou 1

        # Q13 : Sessions de marché — toujours calculées (le modèle apprend les poids)
        out["session_london"]  = ((hour >= 8)  & (hour < 17)).astype(float)
        out["session_ny"]      = ((hour >= 13) & (hour < 22)).astype(float)
        out["session_overlap"] = ((hour >= 13) & (hour < 17)).astype(float)  # London∩NY
        out["session_asian"]   = (hour < 8).astype(float)
    except AttributeError:
        pass  # index non-temporel (tests unitaires)

    # Q14 : Features DXY inter-marché (si données disponibles dans extra_ohlcv)
    if extra_ohlcv and "dxy" in extra_ohlcv:
        dxy = extra_ohlcv["dxy"]
        if not dxy.empty:
            try:
                # Ré-indexer DXY sur l'index principal (forward-fill = causal)
                dxy_close = dxy["close"].reindex(df.index, method="ffill")
                dxy_atr = atr(dxy.reindex(df.index, method="ffill").ffill(), 14)

                dxy_log = np.log(dxy_close)
                out["dxy_return_1"]  = dxy_log.diff(1)
                out["dxy_return_24"] = dxy_log.diff(24)
                out["dxy_atr_pct"]   = dxy_atr / (dxy_close + 1e-9)
            except Exception:
                pass  # DXY incompatible avec cet index — features omises silencieusement

    return out


def make_target_direction(df: pd.DataFrame, horizon: int = 4) -> pd.Series:
    """Cible binaire : direction du prix dans `horizon` bougies (1 = up, 0 = down).

    NB : la dernière ligne de la cible est NaN (futur inconnu). Ces lignes
    doivent être exclues à l'entraînement.
    """
    fwd_return = df["close"].shift(-horizon) / df["close"] - 1.0
    return (fwd_return > 0).astype("float").where(fwd_return.notna())
