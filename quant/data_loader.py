"""
quant/data_loader.py — Chargement OHLCV via ccxt (Binance par défaut).

Sortie : DataFrame indexé par timestamp UTC (tz-aware), colonnes [open, high, low, close, volume].
Garantit l'ordre chronologique et l'absence de doublons.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import ccxt
import pandas as pd

logger = logging.getLogger("zeitgeist.quant.data_loader")

DEFAULT_EXCHANGE = "binance"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "ohlcv"

# Actifs non disponibles sur Binance → routés vers yfinance
_YAHOO_SYMBOLS: dict[str, str] = {
    "XAU/USD": "GC=F",
    "XAG/USD": "SI=F",
    "WTI/USD": "CL=F",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
}


def fetch_ohlcv(
    symbol: str = "BTC/USDT",
    timeframe: str = "15m",
    since_ms: int | None = None,
    limit: int = 1000,
    exchange_name: str = DEFAULT_EXCHANGE,
) -> pd.DataFrame:
    """Récupère un lot de bougies OHLCV depuis l'exchange.

    Args:
        symbol: paire ex. "BTC/USDT"
        timeframe: "1m", "5m", "15m", "1h", "4h", "1d"
        since_ms: timestamp ms UTC à partir duquel charger (None = plus récent)
        limit: nombre de bougies max (≤1000 pour binance)
        exchange_name: nom ccxt de l'exchange

    Returns:
        DataFrame [open, high, low, close, volume] indexé timestamp UTC
    """
    exchange = getattr(ccxt, exchange_name)({"enableRateLimit": True})
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)
    if not raw:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df


def fetch_history(
    symbol: str = "BTC/USDT",
    timeframe: str = "15m",
    days: int = 90,
    exchange_name: str = DEFAULT_EXCHANGE,
    cache: bool = True,
) -> pd.DataFrame:
    """Récupère un historique de N jours en paginant les requêtes."""
    cache_dir = DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{symbol.replace('/', '')}_{timeframe}_{days}d.parquet"

    if cache and cache_file.exists():
        try:
            cached = pd.read_parquet(cache_file)
            if not cached.empty:
                logger.info(f"Cache hit: {cache_file.name} ({len(cached)} bougies)")
                return cached
        except Exception as exc:
            logger.warning(f"Lecture cache échouée ({exc}) — re-fetch.")

    # Routing : actifs non disponibles sur Binance → yfinance
    if symbol in _YAHOO_SYMBOLS:
        df = _fetch_yahoo_history(symbol, timeframe, days)
        if cache and not df.empty:
            try:
                df.to_parquet(cache_file)
                logger.info(f"Cache écrit: {cache_file.name} ({len(df)} bougies)")
            except Exception as exc:
                logger.warning(f"Écriture cache échouée: {exc}")
        return df

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    tf_minutes = _timeframe_to_minutes(timeframe)
    bar_ms = tf_minutes * 60 * 1000

    all_chunks: list[pd.DataFrame] = []
    cursor = start_ms
    while cursor < end_ms:
        chunk = fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            since_ms=cursor,
            limit=1000,
            exchange_name=exchange_name,
        )
        if chunk.empty:
            break
        all_chunks.append(chunk)
        last_ts_ms = int(chunk.index[-1].timestamp() * 1000)
        next_cursor = last_ts_ms + bar_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(0.2)  # respect rate limit

    if not all_chunks:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.concat(all_chunks)
    df = df[~df.index.duplicated(keep="first")].sort_index()

    if cache:
        try:
            df.to_parquet(cache_file)
            logger.info(f"Cache écrit: {cache_file.name} ({len(df)} bougies)")
        except Exception as exc:
            logger.warning(f"Écriture cache échouée: {exc}")

    return df


def _fetch_yahoo_history(symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    """Récupère OHLCV via yfinance pour les actifs non disponibles sur Binance."""
    try:
        import yfinance as yf
        from datetime import datetime, timedelta, timezone

        yahoo_sym = _YAHOO_SYMBOLS[symbol]
        interval_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "1h", "1d": "1d"}
        interval = interval_map.get(timeframe, "15m")
        # yfinance limite les données intraday à ~60 jours
        actual_days = min(days, 59) if interval in ("1m", "5m", "15m", "1h") else days

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=actual_days)

        ticker = yf.Ticker(yahoo_sym)
        hist = ticker.history(start=start, end=end, interval=interval)

        if hist.empty:
            logger.warning(f"yfinance: aucune donnée pour {symbol} ({yahoo_sym})")
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        hist = hist.reset_index()
        ts_col = "Datetime" if "Datetime" in hist.columns else "Date"
        hist["ts"] = pd.to_datetime(hist[ts_col], utc=True)
        hist = hist.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
        df = hist.set_index("ts")[["open", "high", "low", "close", "volume"]].dropna()
        df.index.name = "ts"
        df = df[~df.index.duplicated(keep="first")].sort_index()
        return df
    except ImportError:
        logger.error("yfinance non installé — pip install yfinance")
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    except Exception as exc:
        logger.error(f"yfinance fetch échoué pour {symbol}: {exc}")
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _timeframe_to_minutes(timeframe: str) -> int:
    unit = timeframe[-1]
    n = int(timeframe[:-1])
    if unit == "m":
        return n
    if unit == "h":
        return n * 60
    if unit == "d":
        return n * 60 * 24
    raise ValueError(f"Timeframe non supporté: {timeframe}")


def synthetic_ohlcv(
    n_bars: int = 2000,
    start_price: float = 50_000.0,
    vol: float = 0.005,
    seed: int = 42,
    freq_minutes: int = 15,
) -> pd.DataFrame:
    """Génère un OHLCV synthétique reproductible pour tests offline (random walk gaussien)."""
    import numpy as np

    rng = np.random.default_rng(seed)
    returns = rng.normal(0, vol, size=n_bars)
    close = start_price * (1 + returns).cumprod()
    high = close * (1 + rng.uniform(0, vol, size=n_bars))
    low = close * (1 - rng.uniform(0, vol, size=n_bars))
    open_ = pd.Series(close).shift(1).fillna(start_price).values
    volume = rng.uniform(10, 100, size=n_bars)

    ts = pd.date_range(
        end=pd.Timestamp.utcnow().floor(f"{freq_minutes}min"),
        periods=n_bars,
        freq=f"{freq_minutes}min",
        tz="UTC",
    )
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=ts,
    )
