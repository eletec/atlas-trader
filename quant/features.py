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


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI causal — normalisé [0, 1]."""
    delta = close.diff(1)
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    rs = gain / (loss + 1e-9)
    return 1.0 / (1.0 + rs)   # ∈ [0,1] : 1=surachat, 0=survente


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
        extra_ohlcv: dictionnaire d'OHLCV supplémentaires, ex. {"dxy": dxy_df,
                     "funding": funding_df, "oi": oi_df}
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
    out["log_return_96"] = log_close.diff(96)   # 8h — moyen terme

    # RSI-14 — indicateur directionnel clé ∈ [0,1]
    out["rsi_14"] = rsi(close, 14)

    # MACD histogram causal (EMA12 - EMA26, signal EMA9) — direction + momentum
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
    out["macd_hist"] = (macd_line - macd_signal) / (close + 1e-9)  # normalisé par prix

    # EMA crossover : EMA9 vs EMA21 — signe de la tendance courte
    ema9  = _ema(close, 9)
    ema21 = _ema(close, 21)
    out["ema_cross"] = (ema9 - ema21) / (close + 1e-9)  # >0 = haussier, <0 = baissier

    # Rate of Change 12 barres (1h) — momentum normalisé
    out["roc_12"] = close.pct_change(12)

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
                # Normaliser les timezones avant reindex (Binance UTC-aware vs yfinance naive)
                _target_idx = df.index
                _dxy_close = dxy["close"].copy()
                if _target_idx.tz is not None and _dxy_close.index.tz is None:
                    _dxy_close.index = _dxy_close.index.tz_localize("UTC")
                elif _target_idx.tz is None and _dxy_close.index.tz is not None:
                    _dxy_close.index = _dxy_close.index.tz_localize(None)
                dxy_close = _dxy_close.reindex(_target_idx, method="ffill")
                _dxy_ohlcv = dxy.copy()
                if _target_idx.tz is not None and _dxy_ohlcv.index.tz is None:
                    _dxy_ohlcv.index = _dxy_ohlcv.index.tz_localize("UTC")
                elif _target_idx.tz is None and _dxy_ohlcv.index.tz is not None:
                    _dxy_ohlcv.index = _dxy_ohlcv.index.tz_localize(None)
                dxy_atr = atr(_dxy_ohlcv.reindex(_target_idx, method="ffill").ffill(), 14)

                dxy_log = np.log(dxy_close)
                out["dxy_return_1"]  = dxy_log.diff(1)
                out["dxy_return_24"] = dxy_log.diff(24)
                out["dxy_atr_pct"]   = dxy_atr / (dxy_close + 1e-9)
            except Exception:
                pass  # DXY incompatible avec cet index — features omises silencieusement

    # Q15 : Features d'order flow (CVD + funding rate + open interest)
    # Désactivées si use_order_flow_features=False dans la config (ex: grid search)
    try:
        from quant.config import get_quant_cfg as _get_qcfg
        _of_enabled = getattr(_get_qcfg(), 'use_order_flow_features', True)
    except Exception:
        _of_enabled = True
    if _of_enabled:
        _funding = extra_ohlcv.get("funding") if extra_ohlcv else None
        _oi      = extra_ohlcv.get("oi")      if extra_ohlcv else None
        add_order_flow_features(out, df, _funding, _oi)

    return out


# ── Order flow features (funding rate + open interest) ────────────────────────

def _align_series_to_index(
    series: "pd.Series",
    target_idx: "pd.Index",
) -> "pd.Series":
    """Ré-aligne une série sur target_idx avec forward-fill causal.

    Gère les mismatches timezone (Binance UTC-aware vs index naive).
    """
    s = series.copy()
    if target_idx.tz is not None and s.index.tz is None:
        s.index = s.index.tz_localize("UTC")
    elif target_idx.tz is None and s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s.reindex(target_idx, method="ffill")


def add_order_flow_features(
    out: "pd.DataFrame",
    df: "pd.DataFrame",
    funding_df: "pd.DataFrame | None",
    oi_df: "pd.DataFrame | None",
) -> None:
    """Ajoute les features d'order flow en place dans `out`.

    Features produites (toutes causales — shift(1) ou données publiées avant t) :
    - cvd_20            : Cumulative Volume Delta rolling 20h (dérivé OHLCV)
    - funding_rate      : taux de funding aligné (toutes les 8h, ffill → 1h)
    - funding_mom_3     : variation du funding sur 3 périodes (tendance sentiment)
    - oi_change_pct     : variation % de l'Open Interest sur 1 barre
    - oi_z_20           : z-score de l'OI rolling 20h (anomalie positionnement)
    - funding_oi_signal : funding_rate × oi_change_pct (liquidation imminente)
    """
    # ── CVD rolling 20h (causal — depuis volume OHLCV) ────────────────────
    # Approx causal : close > open = buy pressure, < = sell pressure
    bar_delta = df["volume"] * np.where(df["close"] >= df["open"], 1.0, -1.0)
    out["cvd_20"] = (
        bar_delta.shift(1).rolling(20, min_periods=10).sum()
        / (df["volume"].shift(1).rolling(20, min_periods=10).sum() + 1e-9)
    )  # ∈ [-1, 1] approx

    # ── Funding rate aligné ────────────────────────────────────────────────
    if funding_df is not None and not funding_df.empty and "funding_rate" in funding_df.columns:
        try:
            fr_series = funding_df.set_index("timestamp")["funding_rate"] \
                if "timestamp" in funding_df.columns else funding_df["funding_rate"]
            fr_aligned = _align_series_to_index(fr_series, df.index)
            # Décalage d'1 barre pour causalité stricte
            out["funding_rate"]  = fr_aligned.shift(1)
            out["funding_mom_3"] = fr_aligned.diff(3).shift(1)  # tendance sur 24h (3×8h)
        except Exception:
            pass  # données funding incompatibles — features omises

    # ── Open Interest ──────────────────────────────────────────────────────
    if oi_df is not None and not oi_df.empty and "open_interest" in oi_df.columns:
        try:
            oi_series = oi_df.set_index("timestamp")["open_interest"] \
                if "timestamp" in oi_df.columns else oi_df["open_interest"]
            oi_aligned = _align_series_to_index(oi_series, df.index)
            oi_shifted = oi_aligned.shift(1)  # causal
            out["oi_change_pct"] = oi_shifted.pct_change(1)  # variation % 1h
            oi_mean = oi_shifted.rolling(20, min_periods=10).mean()
            oi_std  = oi_shifted.rolling(20, min_periods=10).std()
            out["oi_z_20"] = (oi_shifted - oi_mean) / (oi_std + 1e-9)
        except Exception:
            pass

    # ── Signal combiné funding × oi_change ────────────────────────────────
    if "funding_rate" in out.columns and "oi_change_pct" in out.columns:
        out["funding_oi_signal"] = out["funding_rate"] * out["oi_change_pct"]


def make_target_direction(df: pd.DataFrame, horizon: int = 4) -> pd.Series:
    """Cible binaire : direction du prix dans `horizon` bougies (1 = up, 0 = down).

    NB : la dernière ligne de la cible est NaN (futur inconnu). Ces lignes
    doivent être exclues à l'entraînement.
    """
    fwd_return = df["close"].shift(-horizon) / df["close"] - 1.0
    return (fwd_return > 0).astype("float").where(fwd_return.notna())


def make_barrier_label(
    df: pd.DataFrame,
    sl_mult: float = 2.5,
    tp_mult: float = 3.5,
    max_horizon: int = 48,
    atr_col: str = "atr_14",
) -> pd.Series:
    """Label à barrière : 1 si TP touché avant SL dans la fenêtre, 0 sinon.

    Pour chaque barre t :
      - SL_price = close[t] - sl_mult × ATR[t]   (barrier basse)
      - TP_price = close[t] + tp_mult × ATR[t]   (barrier haute)
      - On cherche la 1ère barre dans [t+1, t+max_horizon] où high >= TP ou low <= SL.
      - y = 1 si TP touché en premier (ou en même bar avec hypothèse pessimiste SL avant TP).
      - y = 0 si SL touché en premier ou si aucune barrière touchée dans max_horizon bars.

    Ce label aligne directement l'entraînement avec les sorties SL/TP du backtest.
    """
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    atr = df[atr_col].values if atr_col in df.columns else np.full(len(df), np.nan)

    n = len(df)
    y = np.full(n, np.nan)

    for t in range(n - 1):
        if not np.isfinite(atr[t]) or atr[t] <= 0:
            continue
        sl_price = close[t] - sl_mult * atr[t]
        tp_price = close[t] + tp_mult * atr[t]
        result = 0.0  # défaut = 0 (SL ou pas de signal)
        for k in range(t + 1, min(t + max_horizon + 1, n)):
            sl_hit = low[k] <= sl_price
            tp_hit = high[k] >= tp_price
            if sl_hit and tp_hit:
                # Hypothèse pessimiste : SL avant TP
                result = 0.0
                break
            elif tp_hit:
                result = 1.0
                break
            elif sl_hit:
                result = 0.0
                break
        y[t] = result

    return pd.Series(y, index=df.index)
