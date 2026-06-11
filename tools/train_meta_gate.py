#!/usr/bin/env python
"""
tools/train_meta_gate.py — Entraîne les modèles MetaGate V5 par actif.

Pour chaque actif (BTC, ETH, SOL, BNB, XRP, ADA, DOGE) :
1. Charge 180j d'OHLCV 5m + 1h via Binance
2. Calcule features, trend (SMA crossover 1h), régime (ADX + Choppiness)
3. Entraîne XGBoost pour obtenir prob_up (signal brut)
4. Labelise : 1 si retour forward 48 barres > 0
5. Entraîne LogisticRegression(C=0.1, class_weight='balanced')
6. Sauvegarde /app/data/models/meta_{btc,eth,...}.pkl

Usage :
    docker exec atlas-v4-api python tools/train_meta_gate.py
    docker exec atlas-v4-api python tools/train_meta_gate.py --asset BTC/USDT
"""
from __future__ import annotations

import argparse
import logging
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_meta_gate")

# ── Constantes ──
ASSETS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
DAYS = 180
HORIZON_BARS = 48  # 4h à 5min
OUT_DIR = Path(os.environ.get("MODELS_DIR", "/app/data/models"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Features ──────────────────────────────────────────────────────────────────

def _true_range(df: pd.DataFrame) -> pd.Series:
    high, low, prev_close = df["high"], df["low"], df["close"].shift(1)
    return pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = _true_range(df)
    atr_s = tr.rolling(period, min_periods=period).mean()
    di_p = 100 * plus_dm.rolling(period, min_periods=period).mean() / atr_s
    di_m = 100 * minus_dm.rolling(period, min_periods=period).mean() / atr_s
    dx = 100 * (di_p - di_m).abs() / (di_p + di_m + 1e-10)
    return dx.rolling(period, min_periods=period).mean()


def compute_choppiness(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = _true_range(df)
    atr_sum = tr.rolling(period, min_periods=period).sum()
    highest = df["high"].rolling(period, min_periods=period).max()
    lowest = df["low"].rolling(period, min_periods=period).min()
    chop = 100 * np.log10(atr_sum / (highest - lowest + 1e-10)) / np.log10(period)
    return chop.clip(0, 100)


def compute_features_5m(df: pd.DataFrame) -> pd.DataFrame:
    """Features légères sur 5m pour XGBoost."""
    close = df["close"]
    feats = pd.DataFrame(index=df.index)
    feats["rsi_14"] = _rsi(close, 14)
    feats["log_ret_1"] = np.log(close / close.shift(1))
    feats["log_ret_4"] = np.log(close / close.shift(4))
    feats["log_ret_24"] = np.log(close / close.shift(24))
    feats["vol_ret"] = feats["log_ret_1"].rolling(20).std()
    feats["atr_pct"] = _true_range(df).rolling(14).mean() / close
    feats["dist_ma20"] = close / close.rolling(20).mean() - 1
    feats["dist_ma50"] = close / close.rolling(50).mean() - 1
    feats["volume_z"] = (df["volume"] - df["volume"].rolling(20).mean()) / df["volume"].rolling(20).std()
    # Donchian
    feats["donchian_high"] = df["high"].shift(1).rolling(20).max()
    feats["donchian_low"] = df["low"].shift(1).rolling(20).min()
    feats["donchian_pos"] = (close - feats["donchian_low"]) / (feats["donchian_high"] - feats["donchian_low"] + 1e-10)
    feats["adx_14"] = compute_adx(df, 14)
    return feats


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    rs = gain / (loss + 1e-9)
    return 1.0 / (1.0 + rs)  # 0-1: 1=surachat


# ── Trend ─────────────────────────────────────────────────────────────────────

def compute_trend(df_1h: pd.DataFrame) -> pd.Series:
    """SMA20/SMA50 sur 1h. 1=bullish, 0=neutral, -1=bearish."""
    sma20 = df_1h["close"].rolling(20, min_periods=20).mean()
    sma50 = df_1h["close"].rolling(50, min_periods=50).mean()
    trend = pd.Series(0, index=df_1h.index)
    trend[sma20 > sma50 * 1.005] = 1
    trend[sma20 < sma50 * 0.995] = -1
    return trend


# ── Régime ────────────────────────────────────────────────────────────────────

def compute_regime(df_1h: pd.DataFrame) -> pd.Series:
    """TREND / RANGE / CHOP sur 1h (ADX 14 + Choppiness 14)."""
    adx = compute_adx(df_1h, 14)
    chop = compute_choppiness(df_1h, 14)
    regime = pd.Series("RANGE", index=df_1h.index)
    regime[(adx > 25) & (chop < 61.8)] = "TREND"
    regime[(adx < 20) | (chop > 61.8)] = "CHOP"
    return regime


# ── XGBoost signal ────────────────────────────────────────────────────────────

def train_xgb_signal(feats: pd.DataFrame, labels: pd.Series) -> pd.Series:
    """Entraîne XGBoost en walk-forward simplifié pour obtenir prob_up."""
    try:
        from xgboost import XGBClassifier
    except ImportError:
        logger.warning("XGBoost indisponible — fallback LogisticRegression")
        from sklearn.linear_model import LogisticRegression

    feature_cols = [c for c in feats.columns if feats[c].notna().sum() > 100]
    prob_up = pd.Series(0.5, index=feats.index, dtype=float)

    # Aligner features et labels sur un index commun sans NaN
    common = feats[feature_cols].notna().all(axis=1) & labels.notna()
    feats_clean = feats.loc[common, feature_cols]
    labs_clean = labels.loc[common]

    if len(feats_clean) < 100:
        return prob_up
    if len(np.unique(labs_clean)) < 2:
        return prob_up

    # Walk-forward: train 70%, predict 30%
    split = int(len(feats_clean) * 0.70)
    X_train = feats_clean.iloc[:split].values.astype(np.float64)
    y_train = labs_clean.iloc[:split].values.astype(int)
    X_pred = feats_clean.iloc[split:].values.astype(np.float64)
    pred_idx = feats_clean.iloc[split:].index

    if len(y_train) < 50 or len(X_pred) < 10:
        return prob_up

    try:
        model = XGBClassifier(
            n_estimators=100, max_depth=5, learning_rate=0.05,
            objective="binary:logistic", verbosity=0, random_state=42,
        )
        model.fit(X_train, y_train)
        prob_up.loc[pred_idx] = model.predict_proba(X_pred)[:, 1]
    except Exception as e:
        logger.warning("XGB train failed: %s — fallback LR", e)
        from sklearn.linear_model import LogisticRegression
        lr = LogisticRegression(C=0.1, max_iter=300, random_state=42)
        try:
            lr.fit(X_train, y_train)
            prob_up.loc[pred_idx] = lr.predict_proba(X_pred)[:, 1]
        except Exception as e2:
            logger.warning("Fallback LR also failed: %s", e2)

    return prob_up.clip(0.01, 0.99)


# ── Label ─────────────────────────────────────────────────────────────────────

def make_labels(df_5m: pd.DataFrame, horizon: int = HORIZON_BARS) -> pd.Series:
    """1 si retour forward > 0, 0 sinon."""
    fwd = df_5m["close"].shift(-horizon) / df_5m["close"] - 1
    return (fwd > 0).astype(int)


# ── Entraînement MetaGate ─────────────────────────────────────────────────────

def train_meta_gate(symbol: str, days: int = DAYS) -> tuple[object, dict] | None:
    """Entraîne un LogisticRegression pour MetaGate. Retourne (model, metrics)."""
    from quant.data_loader import fetch_ohlcv
    from sklearn.linear_model import LogisticRegression

    pfx = symbol.split("/")[0].lower()[:3]
    logger.info("=== Training MetaGate for %s (%s) ===", symbol, pfx)

    # 1. Charger OHLCV (paginé pour dépasser la limite 1000 bougies Binance)
    logger.info("Loading OHLCV 5m + 1h (%d days)...", days)
    try:
        from quant.data_loader import fetch_history
        df_5m = fetch_history(symbol, timeframe="5m", days=days, cache=True)
        df_1h = fetch_history(symbol, timeframe="1h", days=days, cache=True)
    except Exception as e:
        logger.error("OHLCV fetch failed for %s: %s", symbol, e)
        return None

    if len(df_5m) < 500:
        logger.error("Not enough 5m data for %s (%d bars)", symbol, len(df_5m))
        return None

    # 2. Features + labels (5m)
    logger.info("Computing features...")
    feats = compute_features_5m(df_5m)
    labels = make_labels(df_5m)

    # 3. XGBoost prob_up
    logger.info("Training XGBoost signal...")
    prob_up = train_xgb_signal(feats, labels)

    # 4. Trend (1h) → resample to 5m
    trend_1h = compute_trend(df_1h)
    trend_5m = trend_1h.reindex(df_5m.index, method="ffill").fillna(0)

    # 5. Regime (1h) → resample to 5m
    regime_1h = compute_regime(df_1h)
    regime_5m = regime_1h.reindex(df_5m.index, method="ffill").fillna("RANGE")

    # 6. Build training dataset
    logger.info("Building MetaGate training set...")
    data = pd.DataFrame({
        "prob_up": prob_up,
        "trend_bull": (trend_5m == 1).astype(int),
        "trend_bear": (trend_5m == -1).astype(int),
        "regime_TREND": (regime_5m == "TREND").astype(int),
        "regime_RANGE": (regime_5m == "RANGE").astype(int),
        "regime_CHOP": (regime_5m == "CHOP").astype(int),
        "label": labels,
    }, index=df_5m.index)

    # Remove NaN rows
    data = data.dropna()
    if len(data) < 100:
        logger.error("Not enough training data for %s (%d rows)", symbol, len(data))
        return None

    # 7. Train/Test split (time-series: first 80% train, last 20% test)
    split = int(len(data) * 0.80)
    train = data.iloc[:split]
    test = data.iloc[split:]

    feature_cols = ["prob_up", "trend_bull", "trend_bear", "regime_TREND", "regime_RANGE", "regime_CHOP"]
    X_tr, y_tr = train[feature_cols].values, train["label"].values
    X_te, y_te = test[feature_cols].values, test["label"].values

    if len(np.unique(y_tr)) < 2:
        logger.error("Single class in training labels for %s", symbol)
        return None

    # 8. Train LogisticRegression
    model = LogisticRegression(C=0.1, max_iter=500, class_weight="balanced", random_state=42)
    model.fit(X_tr, y_tr)

    # 9. Evaluate
    from sklearn.metrics import accuracy_score, f1_score
    y_pred = model.predict(X_te)
    acc = accuracy_score(y_te, y_pred)
    f1 = f1_score(y_te, y_pred, zero_division=0)
    proba = model.predict_proba(X_te)
    classes = list(model.classes_)

    # Simulated MetaGate scoring
    if 1 in classes and 0 in classes:
        p_long = proba[:, classes.index(1)]
        p_short = proba[:, classes.index(0)]
        scores = p_long - (1 - p_long)  # proxy: P(long) - P(not long)
    else:
        scores = np.zeros(len(y_te))

    # Count decisions at various thresholds
    thresholds = [0.10, 0.15, 0.20, 0.25, 0.30]
    decisions = {}
    for th in thresholds:
        n_long = int((scores > th).sum())
        n_short = int((scores < -th).sum())
        n_flat = len(scores) - n_long - n_short
        decisions[f"th_{th:.0f}"] = f"L={n_long} S={n_short} F={n_flat}"

    metrics = {
        "symbol": symbol,
        "train_rows": len(train),
        "test_rows": len(test),
        "accuracy": round(acc, 4),
        "f1_score": round(f1, 4),
        "class_balance": round(float(y_tr.mean()), 3),
        "coef": {feature_cols[i]: round(float(model.coef_[0][i]), 4) for i in range(len(feature_cols))},
        "intercept": round(float(model.intercept_[0]), 4),
        "decisions": decisions,
    }

    # 10. Save model
    out_path = OUT_DIR / f"meta_{pfx}.pkl"
    with open(out_path, "wb") as fh:
        pickle.dump(model, fh)
    logger.info("Model saved: %s", out_path)

    return model, metrics


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Train MetaGate V5 models")
    parser.add_argument("--asset", type=str, default=None, help="Single asset (e.g. BTC/USDT)")
    parser.add_argument("--days", type=int, default=DAYS, help="Days of history")
    args = parser.parse_args()

    assets = [args.asset] if args.asset else ASSETS

    all_metrics = []
    for symbol in assets:
        try:
            result = train_meta_gate(symbol, days=args.days)
            if result:
                _, metrics = result
                all_metrics.append(metrics)
                logger.info("✅ %s — acc=%.3f f1=%.3f train=%d test=%d",
                            symbol, metrics["accuracy"], metrics["f1_score"],
                            metrics["train_rows"], metrics["test_rows"])
                # Print coefficients
                coef = metrics["coef"]
                logger.info("   coef: prob=%.3f bull=%.3f bear=%.3f TREND=%.3f RANGE=%.3f CHOP=%.3f int=%.3f",
                            coef["prob_up"], coef["trend_bull"], coef["trend_bear"],
                            coef["regime_TREND"], coef["regime_RANGE"], coef["regime_CHOP"],
                            metrics["intercept"])
            else:
                logger.warning("❌ %s — SKIPPED (not enough data)", symbol)
        except Exception as e:
            logger.exception("❌ %s — FAILED: %s", symbol, e)

    # Summary table
    if all_metrics:
        print("\n" + "=" * 80)
        print(f"{'Symbol':<12} {'Train':>8} {'Test':>8} {'Acc':>8} {'F1':>8} {'Bal':>8} {'th_0.10':>20} {'th_0.20':>20}")
        print("-" * 80)
        for m in all_metrics:
            print(f"{m['symbol']:<12} {m['train_rows']:>8} {m['test_rows']:>8} "
                  f"{m['accuracy']:>8.3f} {m['f1_score']:>8.3f} {m['class_balance']:>8.3f} "
                  f"{m['decisions'].get('th_0.10', '?'):>20} {m['decisions'].get('th_0.20', '?'):>20}")
        print("=" * 80)
        logger.info("Done. %d/%d models trained.", len(all_metrics), len(assets))
    else:
        logger.warning("No models trained.")


if __name__ == "__main__":
    main()
