"""
backtest/data_fetcher.py — Téléchargement et cache des données historiques.

Sources :
  - OHLCV 15min   : Binance CCXT (crypto) / yfinance (forex, commodités)
  - Fear & Greed  : alternative.me (API publique, historique depuis 2018)
  - Funding rate  : Binance Futures historique

Toutes les données sont cachées dans backtest/cache/ au format parquet/json
pour éviter de re-télécharger à chaque run.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("backtest.data_fetcher")

# Cache dir : préférer /app/data/backtest_cache/ (volume Docker persistant writable)
# si le dossier local backtest/cache/ n'est pas accessible en écriture (bind-mount :ro).
_LOCAL_CACHE = Path(__file__).parent / "cache"
_DOCKER_CACHE = Path("/app/data/backtest_cache")

def _resolve_cache_dir() -> Path:
    try:
        _LOCAL_CACHE.mkdir(exist_ok=True)
        # Vérifier l'accès en écriture
        _test = _LOCAL_CACHE / ".writable"
        _test.touch()
        _test.unlink()
        return _LOCAL_CACHE
    except OSError:
        _DOCKER_CACHE.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Cache backtest redirigé vers {_DOCKER_CACHE} (backtest/ en lecture seule)")
        return _DOCKER_CACHE

CACHE_DIR = _resolve_cache_dir()

# Actifs routés vers yfinance (pas sur Binance spot/futures)
_YAHOO_SYMBOLS: dict[str, str] = {
    "XAU/USD": "GC=F",
    "XAG/USD": "SI=F",
    "WTI/USD": "CL=F",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
}


# ── Helpers cache ─────────────────────────────────────────────────────────────

def _cache_path(name: str, ext: str = "parquet") -> Path:
    return CACHE_DIR / f"{name}.{ext}"


def _is_fresh(path: Path, max_age_hours: int = 1) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < max_age_hours * 3600


# ── OHLCV ─────────────────────────────────────────────────────────────────────

def fetch_ohlcv(
    symbol: str,
    timeframe: str = "15m",
    days: int = 730,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Retourne un DataFrame OHLCV avec colonnes : timestamp, open, high, low, close, volume.
    timestamp est un datetime UTC.
    Données cachées — re-télécharge seulement si le cache est plus vieux que 1h.
    """
    slug = symbol.replace("/", "_")
    cache_file = _cache_path(f"ohlcv_{slug}_{timeframe}_{days}d")

    if not force_refresh and cache_file.exists() and _is_fresh(cache_file, max_age_hours=2):
        logger.info(f"[cache] OHLCV {symbol} {timeframe} {days}d")
        return pd.read_parquet(cache_file)

    logger.info(f"[fetch] OHLCV {symbol} {timeframe} {days}d depuis {'Yahoo' if symbol in _YAHOO_SYMBOLS else 'Binance'}...")

    if symbol in _YAHOO_SYMBOLS:
        df = _fetch_yahoo_ohlcv(symbol, days, timeframe)
    else:
        df = _fetch_binance_ohlcv(symbol, timeframe, days)

    if df is not None and not df.empty:
        df.to_parquet(cache_file, index=False)
        logger.info(f"[fetch] {symbol}: {len(df)} candles téléchargées")
    else:
        logger.warning(f"[fetch] {symbol}: aucune donnée — retour DataFrame vide")
        df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    return df


def _fetch_binance_ohlcv(symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    try:
        import ccxt
        exchange = ccxt.binance({"enableRateLimit": True, "timeout": 30000})

        since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
        all_candles: list = []
        batch_limit = 1000
        current_since = since_ms

        while True:
            try:
                candles = exchange.fetch_ohlcv(symbol, timeframe, since=current_since, limit=batch_limit)
            except Exception as e:
                logger.warning(f"Binance fetch error {symbol}: {e}")
                break
            if not candles:
                break
            all_candles.extend(candles)
            if len(candles) < batch_limit:
                break
            current_since = candles[-1][0] + 1
            time.sleep(0.3)  # rate limit respectueux

        if not all_candles:
            return pd.DataFrame()

        df = pd.DataFrame(all_candles, columns=["ts_ms", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
        df = df.drop(columns=["ts_ms"]).dropna().reset_index(drop=True)
        return df

    except ImportError:
        logger.error("ccxt non installé. pip install ccxt")
        return pd.DataFrame()


def _fetch_yahoo_ohlcv(symbol: str, days: int, timeframe: str) -> pd.DataFrame:
    try:
        import yfinance as yf

        yahoo_sym = _YAHOO_SYMBOLS[symbol]
        # yfinance interval mapping
        interval_map = {"15m": "15m", "1h": "1h", "4h": "1h", "1d": "1d"}
        interval = interval_map.get(timeframe, "15m")

        # yfinance limite les données intraday à 60 jours
        actual_days = min(days, 59) if interval in ("15m", "1h") else days

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=actual_days)

        ticker = yf.Ticker(yahoo_sym)
        hist = ticker.history(start=start, end=end, interval=interval)

        if hist.empty:
            return pd.DataFrame()

        hist = hist.reset_index()
        ts_col = "Datetime" if "Datetime" in hist.columns else "Date"
        hist["timestamp"] = pd.to_datetime(hist[ts_col], utc=True)
        hist = hist.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
        return hist[["timestamp", "open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)

    except ImportError:
        logger.error("yfinance non installé. pip install yfinance")
        return pd.DataFrame()


# ── Fear & Greed historique ──────────────────────────────────────────────────

def fetch_fear_greed_history(days: int = 730, force_refresh: bool = False) -> pd.DataFrame:
    """
    Retourne un DataFrame index=date, colonne=fng_value (0-100).
    API alternative.me permet de récupérer jusqu'à ~2000 jours.
    """
    cache_file = _cache_path(f"fear_greed_{days}d")

    if not force_refresh and cache_file.exists() and _is_fresh(cache_file, max_age_hours=24):
        logger.info("[cache] Fear & Greed history")
        return pd.read_parquet(cache_file)

    logger.info(f"[fetch] Fear & Greed historique {days} jours...")
    try:
        import requests
        resp = requests.get(
            f"https://api.alternative.me/fng/?limit={days}&format=json",
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            return pd.DataFrame(columns=["date", "fng_value"])

        rows = []
        for entry in data:
            ts = int(entry["timestamp"])
            value = int(entry["value"])
            rows.append({
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).date(),
                "fng_value": value,
            })

        df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date").reset_index(drop=True)
        df.to_parquet(cache_file, index=False)
        logger.info(f"[fetch] Fear & Greed: {len(df)} jours téléchargés")
        return df

    except Exception as e:
        logger.warning(f"Fear & Greed historique indisponible: {e}")
        return pd.DataFrame(columns=["date", "fng_value"])


# ── Funding rate historique ──────────────────────────────────────────────────

def fetch_funding_history(symbol: str = "BTC/USDT", days: int = 730, force_refresh: bool = False) -> pd.DataFrame:
    """
    Retourne un DataFrame avec colonnes: timestamp (UTC), funding_rate.
    Binance publie le funding rate toutes les 8h (3x/jour).
    Uniquement disponible pour les paires Futures (crypto USDT).
    """
    slug = symbol.replace("/", "_")
    cache_file = _cache_path(f"funding_{slug}_{days}d")

    if not force_refresh and cache_file.exists() and _is_fresh(cache_file, max_age_hours=8):
        logger.info(f"[cache] funding {symbol}")
        return pd.read_parquet(cache_file)

    # Seulement les cryptos USDT ont un funding rate
    if not symbol.endswith("/USDT"):
        return pd.DataFrame(columns=["timestamp", "funding_rate"])

    logger.info(f"[fetch] Funding rate historique {symbol}...")
    try:
        import ccxt
        # Futures USDM uniquement (pas Binance spot)
        exchange = ccxt.binanceusdm({"enableRateLimit": True, "timeout": 30000})

        since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
        all_rates: list = []
        current_since = since_ms

        while True:
            try:
                rates = exchange.fetch_funding_rate_history(
                    symbol, since=current_since, limit=1000
                )
            except Exception as e:
                logger.warning(f"Funding batch {symbol}: {e}")
                break
            if not rates:
                break
            all_rates.extend(rates)
            if len(rates) < 1000:
                break
            current_since = rates[-1]["timestamp"] + 1
            time.sleep(0.2)

        if not all_rates:
            return pd.DataFrame(columns=["timestamp", "funding_rate"])

        rows = []
        for r in all_rates:
            rows.append({
                "timestamp": pd.Timestamp(r["timestamp"], unit="ms", tz="UTC"),
                "funding_rate": float(r.get("fundingRate", 0)),
            })

        df = pd.DataFrame(rows).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
        df.to_parquet(cache_file, index=False)
        logger.info(f"[fetch] Funding {symbol}: {len(df)} entrées")
        return df

    except Exception as e:
        logger.warning(f"Funding history {symbol}: {e}")
        return pd.DataFrame(columns=["timestamp", "funding_rate"])


# ── Lookup helpers ────────────────────────────────────────────────────────────

# ── Open Interest historique ─────────────────────────────────────────────────

def fetch_open_interest_history(symbol: str = "BTC/USDT", days: int = 730, force_refresh: bool = False) -> pd.DataFrame:
    """
    Retourne un DataFrame avec colonnes: timestamp (UTC), open_interest.
    Open interest en unités de contrat (Binance Futures).
    Résolution : 1h. Uniquement pour paires *USDT perpetual futures.
    """
    slug = symbol.replace("/", "_")
    cache_file = _cache_path(f"oi_{slug}_{days}d")

    if not force_refresh and cache_file.exists() and _is_fresh(cache_file, max_age_hours=8):
        logger.info(f"[cache] OI {symbol}")
        return pd.read_parquet(cache_file)

    if not symbol.endswith("/USDT"):
        return pd.DataFrame(columns=["timestamp", "open_interest"])

    logger.info(f"[fetch] Open Interest historique {symbol}...")
    try:
        import ccxt
        # Futures USDM uniquement
        exchange = ccxt.binanceusdm({"enableRateLimit": True, "timeout": 30000})

        since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
        all_oi: list = []
        current_since = since_ms

        while True:
            try:
                # fetch_open_interest_history: interval 1h, limit 500 par batch
                batch = exchange.fetch_open_interest_history(
                    futures_symbol, "1h", since=current_since, limit=500
                )
            except Exception as e:
                logger.debug(f"OI fetch batch {symbol}: {e}")
                break
            if not batch:
                break
            all_oi.extend(batch)
            if len(batch) < 500:
                break
            current_since = batch[-1]["timestamp"] + 1
            time.sleep(0.3)

        if not all_oi:
            return pd.DataFrame(columns=["timestamp", "open_interest"])

        rows = []
        for r in all_oi:
            ts = r.get("timestamp") or r.get("time")
            oi = r.get("openInterestAmount") or r.get("openInterest") or 0
            if ts and oi:
                rows.append({
                    "timestamp": pd.Timestamp(ts, unit="ms", tz="UTC"),
                    "open_interest": float(oi),
                })

        if not rows:
            return pd.DataFrame(columns=["timestamp", "open_interest"])

        df = pd.DataFrame(rows).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
        df.to_parquet(cache_file, index=False)
        logger.info(f"[fetch] OI {symbol}: {len(df)} entrées")
        return df

    except Exception as e:
        logger.warning(f"Open Interest history {symbol}: {e}")
        return pd.DataFrame(columns=["timestamp", "open_interest"])


def get_fng_at_date(fng_df: pd.DataFrame, dt: datetime) -> int:
    """Retourne la valeur Fear & Greed au jour dt (approximation par le dernier connu)."""
    if fng_df.empty:
        return 50
    target_date = dt.date() if hasattr(dt, "date") else dt
    # Trouver la dernière valeur connue avant ou égale à target_date
    mask = fng_df["date"] <= target_date
    if not mask.any():
        return 50
    return int(fng_df.loc[mask].iloc[-1]["fng_value"])


def get_funding_at_ts(funding_df: pd.DataFrame, ts: pd.Timestamp) -> float:
    """Retourne le funding rate le plus proche avant ts."""
    if funding_df.empty:
        return 0.0
    mask = funding_df["timestamp"] <= ts
    if not mask.any():
        return 0.0
    return float(funding_df.loc[mask].iloc[-1]["funding_rate"])
