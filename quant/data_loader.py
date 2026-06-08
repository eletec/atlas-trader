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
DEFAULT_CACHE_DIR = Path("/app/data/ohlcv")  # volume Docker writable

# Actifs non disponibles sur Binance → routés vers yfinance
_YAHOO_SYMBOLS: dict[str, str] = {
    "XAU/USD": "GC=F",
    "XAG/USD": "SI=F",
    "WTI/USD": "CL=F",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "CHF/USD": "CHF=X",
}

# Symboles Twelve Data (même actifs + DXY)
_TWELVE_DATA_SYMBOLS: dict[str, str] = {
    "XAU/USD": "XAU/USD",
    "XAG/USD": "XAG/USD",
    "WTI/USD": "USOIL",
    "EUR/USD": "EUR/USD",
    "GBP/USD": "GBP/USD",
    "CHF/USD": "CHF/USD",
    "DXY":     "DXY",     # symbole natif Twelve Data (pas le ticker Yahoo "DX-Y.NYB")
}


def fetch_ohlcv(
    symbol: str = "BTC/USDT",
    timeframe: str = "15m",
    since_ms: int | None = None,
    limit: int = 1000,
    exchange_name: str = DEFAULT_EXCHANGE,
) -> pd.DataFrame:
    """Récupère un lot de bougies OHLCV depuis l'exchange.

    Routing :
    - Crypto → Binance ccxt
    - Forex/Commodités (XAU, XAG, WTI, EUR, GBP) → yfinance (dernières barres)

    Args:
        symbol: paire ex. "BTC/USDT"
        timeframe: "1m", "5m", "15m", "1h", "4h", "1d"
        since_ms: timestamp ms UTC à partir duquel charger (None = plus récent)
        limit: nombre de bougies max (≤1000 pour binance)
        exchange_name: nom ccxt de l'exchange

    Returns:
        DataFrame [open, high, low, close, volume] indexé timestamp UTC
    """
    # Routing : actifs non disponibles sur Binance → yfinance
    if symbol in _YAHOO_SYMBOLS:
        return _fetch_yahoo_latest(symbol, timeframe, limit)

    exchange = getattr(ccxt, exchange_name)({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)
    if not raw:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df


def _fetch_yahoo_latest(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """Récupère les dernières `limit` barres via yfinance pour les actifs non-Binance."""
    try:
        import yfinance as yf
        from datetime import datetime, timedelta, timezone

        yahoo_sym = _YAHOO_SYMBOLS[symbol]
        interval_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "1h", "1d": "1d"}
        interval = interval_map.get(timeframe, "15m")

        # Fenêtre : assez large pour couvrir `limit` barres + gaps weekend
        tf_minutes_map = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
        tf_min = tf_minutes_map.get(timeframe, 15)
        # Pour les TF intraday, yfinance limite à 59j ; on prend 5 jours pour les barres récentes
        fetch_days = max(5, (limit * tf_min) // (60 * 16) + 2)  # +2j de marge
        fetch_days = min(fetch_days, 59)

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=fetch_days)

        ticker = yf.Ticker(yahoo_sym)
        hist = ticker.history(start=start, end=end, interval=interval, timeout=15)

        if hist.empty:
            logger.warning(f"yfinance latest: no data for {symbol} ({yahoo_sym})")
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
        # Retourner uniquement les `limit` dernières barres
        return df.iloc[-limit:] if len(df) > limit else df
    except ImportError:
        logger.error("yfinance not installed — pip install yfinance")
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    except Exception as exc:
        logger.error(f"yfinance latest fetch failed for {symbol}: {exc}")
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def fetch_history(
    symbol: str = "BTC/USDT",
    timeframe: str = "15m",
    days: int = 90,
    exchange_name: str = DEFAULT_EXCHANGE,
    cache: bool = True,
) -> pd.DataFrame:
    """Récupère un historique de N jours en paginant les requêtes.

    Routing :
    - Crypto (Binance) → ccxt
    - Forex/Commodities → Twelve Data si clé disponible et provider != "yahoo",
      sinon fallback yfinance (limité à 59j intraday)
    """
    cache_dir = DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{symbol.replace('/', '')}_{timeframe}_{days}d.parquet"

    if cache and cache_file.exists():
        try:
            cached = pd.read_parquet(cache_file)
            if not cached.empty:
                logger.info(f"Cache hit: {cache_file.name} ({len(cached)} candles)")
                return cached
        except Exception as exc:
            logger.warning(f"Cache read failed ({exc}) — re-fetching.")

    # Routing : actifs non disponibles sur Binance → Twelve Data ou yfinance
    if symbol in _YAHOO_SYMBOLS:
        # Choisir le provider
        try:
            from quant.config import get_quant_cfg, get_twelve_data_key
            cfg_provider = get_quant_cfg().data_provider
        except Exception:
            cfg_provider = "auto"
            get_twelve_data_key = lambda: ""  # type: ignore[assignment]

        td_key = get_twelve_data_key()
        use_td = td_key and cfg_provider != "yahoo"

        if use_td:
            df = _fetch_twelve_data_history(symbol, timeframe, days, td_key)
            if df.empty:
                logger.warning(f"Twelve Data empty for {symbol} — fallback yfinance")
                df = _fetch_yahoo_history(symbol, timeframe, days)
        else:
            df = _fetch_yahoo_history(symbol, timeframe, days)

        if cache and not df.empty:
            try:
                df.to_parquet(cache_file)
                logger.info(f"Cache written: {cache_file.name} ({len(df)} candles)")
            except Exception as exc:
                logger.warning(f"Cache write failed: {exc}")
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
            logger.info(f"Cache written: {cache_file.name} ({len(df)} candles)")
        except Exception as exc:
            logger.warning(f"Cache write failed: {exc}")

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
        hist = ticker.history(start=start, end=end, interval=interval, timeout=15)

        if hist.empty:
            logger.warning(f"yfinance: no data for {symbol} ({yahoo_sym})")
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
        logger.error("yfinance not installed — pip install yfinance")
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    except Exception as exc:
        logger.error(f"yfinance fetch failed for {symbol}: {exc}")
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _fetch_twelve_data_history(
    symbol: str,
    timeframe: str,
    days: int,
    api_key: str,
) -> pd.DataFrame:
    """Récupère OHLCV via l'API REST Twelve Data (jusqu'à 5000 barres/call).

    Avantages vs yfinance :
    - Pas de limite 59j sur les données intraday
    - Données plus stables (pas de splits/dividendes parasites)
    - Forex/commodités en temps réel

    Args:
        symbol: ex. "XAU/USD", "EUR/USD"
        timeframe: ex. "15m", "1h"
        days: nombre de jours d'historique voulus
        api_key: clé API Twelve Data

    Returns:
        DataFrame OHLCV standard ou vide en cas d'erreur.
    """
    try:
        import requests

        td_sym = _TWELVE_DATA_SYMBOLS.get(symbol, symbol.replace("/", "_"))
        # Mapping timeframe ccxt → Twelve Data
        tf_map = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1day"}
        td_tf = tf_map.get(timeframe, "15min")

        # Twelve Data : max 5000 barres par requête (plan gratuit : 800/j)
        outputsize = min(5000, days * 96)  # 96 = barres 15min/jour
        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": td_sym,
            "interval": td_tf,
            "outputsize": outputsize,
            "apikey": api_key,
            "format": "JSON",
            "timezone": "UTC",
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") == "error":
            logger.warning(f"Twelve Data error [{symbol}]: {data.get('message', '?')}")
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        values = data.get("values", [])
        if not values:
            logger.warning(f"Twelve Data: no data for {symbol}")
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(values)
        df["ts"] = pd.to_datetime(df["datetime"], utc=True)
        df = df.set_index("ts").sort_index()
        df = df.rename(columns={"open": "open", "high": "high", "low": "low",
                                 "close": "close", "volume": "volume"})
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        # Le volume peut être absent pour le forex/commodités (= 0 dans TD)
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
        else:
            df["volume"] = 1.0  # proxy pour les actifs sans volume réel

        df = df[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
        df = df[~df.index.duplicated(keep="first")]
        logger.info(f"Twelve Data: {len(df)} bars for {symbol} ({timeframe}, {days}d)")
        return df

    except Exception as exc:
        logger.error(f"Twelve Data fetch failed for {symbol}: {exc}")
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def fetch_dxy_history(timeframe: str = "15m", days: int = 90) -> pd.DataFrame:
    """Récupère l'historique DXY (US Dollar Index) — Q14 feature inter-marché.

    Tente Twelve Data d'abord (meilleure fiabilité), sinon yfinance (DX-Y.NYB).

    Returns:
        DataFrame OHLCV DXY ou DataFrame vide si indisponible.
    """
    from quant.config import get_twelve_data_key
    td_key = get_twelve_data_key()
    if td_key:
        df = _fetch_twelve_data_history("DXY", timeframe, days, td_key)
        if not df.empty:
            return df

    # Fallback yfinance
    try:
        import yfinance as yf
        from datetime import datetime, timedelta, timezone

        tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "1h", "1d": "1d"}
        interval = tf_map.get(timeframe, "15m")
        actual_days = min(days, 59) if interval in ("1m", "5m", "15m", "1h") else days
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=actual_days)

        ticker = yf.Ticker("DX-Y.NYB")
        hist = ticker.history(start=start, end=end, interval=interval, timeout=15)
        if hist.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        hist = hist.reset_index()
        ts_col = "Datetime" if "Datetime" in hist.columns else "Date"
        hist["ts"] = pd.to_datetime(hist[ts_col], utc=True)
        hist = hist.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                     "Close": "close", "Volume": "volume"})
        df = hist.set_index("ts")[["open", "high", "low", "close", "volume"]].dropna()
        df["volume"] = df["volume"].fillna(1.0)
        df = df[~df.index.duplicated(keep="first")].sort_index()
        logger.info(f"DXY (yfinance): {len(df)} barres")
        return df
    except Exception as exc:
        logger.warning(f"DXY fetch failed (yfinance): {exc}")
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


# ── Funding rate + Open Interest (migrés depuis backtest/data_fetcher.py) ─────

def fetch_funding_history(
    symbol: str = "BTC/USDT",
    days: int = 730,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Funding rate historique Binance Futures (toutes les 8h).

    Uniquement pour les paires crypto USDT. Retourne [timestamp, funding_rate].
    """
    from datetime import datetime, timedelta, timezone

    slug = symbol.replace("/", "_")
    cache_file = DEFAULT_CACHE_DIR / f"funding_{slug}_{days}d.parquet"

    if not force_refresh and cache_file.exists():
        age_h = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_h < 8:
            logger.info(f"[cache] funding {symbol}")
            return pd.read_parquet(cache_file)

    if not symbol.endswith("/USDT"):
        return pd.DataFrame(columns=["timestamp", "funding_rate"])

    logger.info(f"[fetch] Funding rate historique {symbol}...")
    try:
        exchange = ccxt.binanceusdm({"enableRateLimit": True, "timeout": 30000})

        since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
        all_rates: list = []
        current_since = since_ms

        while True:
            try:
                rates = exchange.fetch_funding_rate_history(symbol, since=current_since, limit=1000)
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

        rows = [{
            "timestamp": pd.Timestamp(r["timestamp"], unit="ms", tz="UTC"),
            "funding_rate": float(r.get("fundingRate", 0)),
        } for r in all_rates]

        df = pd.DataFrame(rows).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
        DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_file, index=False)
        logger.info(f"[fetch] Funding {symbol}: {len(df)} entrées")
        return df

    except Exception as e:
        logger.warning(f"Funding history {symbol}: {e}")
        return pd.DataFrame(columns=["timestamp", "funding_rate"])


def fetch_open_interest_history(
    symbol: str = "BTC/USDT",
    days: int = 730,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Open Interest historique Binance Futures (résolution 1h).

    Uniquement pour paires *USDT perpetual futures. Max 29 jours d'historique.
    Retourne [timestamp, open_interest].
    """
    from datetime import datetime, timedelta, timezone

    slug = symbol.replace("/", "_")
    cache_file = DEFAULT_CACHE_DIR / f"oi_{slug}_{days}d.parquet"

    if not force_refresh and cache_file.exists():
        age_h = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_h < 8:
            logger.info(f"[cache] OI {symbol}")
            return pd.read_parquet(cache_file)

    if not symbol.endswith("/USDT"):
        return pd.DataFrame(columns=["timestamp", "open_interest"])

    logger.info(f"[fetch] Open Interest historique {symbol}...")
    try:
        exchange = ccxt.binanceusdm({"enableRateLimit": True, "timeout": 30000})

        OI_MAX_DAYS = 29
        effective_days = min(days, OI_MAX_DAYS)
        since_ms = int((datetime.now(timezone.utc) - timedelta(days=effective_days)).timestamp() * 1000)
        all_oi: list = []
        current_since = since_ms

        while True:
            try:
                batch = exchange.fetch_open_interest_history(symbol, "1h", since=current_since, limit=500)
            except Exception as e:
                logger.warning(f"OI fetch batch {symbol}: {e}")
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
        DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_file, index=False)
        logger.info(f"[fetch] OI {symbol}: {len(df)} entrées")
        return df

    except Exception as e:
        logger.warning(f"Open Interest history {symbol}: {e}")
        return pd.DataFrame(columns=["timestamp", "open_interest"])
