"""
agents/market_data_agent.py — Indicateurs techniques via CCXT.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime

import numpy as np

logger = logging.getLogger("zeitgeist.market_data")

# Buffer module-level : garde les 8 dernières valeurs de funding rate (≈ 2h à 15min/cycle)
# Permet au circuit breaker de détecter un funding élevé soutenu vs un pic isolé
_FUNDING_HISTORY: deque = deque(maxlen=8)

# Prix de référence pour la simulation (mock) — ordre de grandeur attendu par actif
_MOCK_PRICES: dict[str, float] = {
    "BTC/USDT": 70_000.0,
    "ETH/USDT":  2_200.0,
    "SOL/USDT":    85.0,
    "BNB/USDT":   600.0,
    "XAU/USD":  3_000.0,
    "XAG/USD":     30.0,
    "WTI/USD":     80.0,
    "EUR/USD":      1.09,
    "GBP/USD":      1.27,
    "USD/JPY":    150.0,
    "AUD/USD":      0.64,
}

# Plages de prix valides par actif — sert à détecter les données testnet aberrantes
_PRICE_SANITY: dict[str, tuple[float, float]] = {
    "BTC/USDT": (10_000, 250_000),
    "ETH/USDT":   (200,   20_000),
    "SOL/USDT":     (2,    2_000),
    "BNB/USDT":    (50,   10_000),
}

# Actifs non supportés par Binance CCXT → Yahoo Finance (clé API non requise)
_YAHOO_SYMBOLS: dict[str, str] = {
    "XAU/USD": "GC=F",       # Gold Futures
    "XAG/USD": "SI=F",       # Silver Futures
    "WTI/USD": "CL=F",       # WTI Crude Oil Futures
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "JPY=X",
    "AUD/USD": "AUDUSD=X",
}


class MarketDataAgent:
    """Récupère OHLCV et calcule les indicateurs techniques."""

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        self._exchange = self._init_ccxt(cfg.get("exchange", {}))

    def _init_ccxt(self, cfg: dict):
        try:
            import ccxt
            exchange_class = getattr(ccxt, cfg.get("name", "binance"))
            exchange = exchange_class({
                "enableRateLimit": True,
                "timeout": 30000,  # 30s hard timeout on all API calls
            })
            # Ne PAS utiliser le sandbox pour lire les données de marché :
            # le testnet Binance génère des prix synthétiques incohérents (ETH à ~65000).
            # Le sandbox est réservé à PaperTrader pour les ordres simulés.
            return exchange
        except Exception as exc:
            logger.warning(f"CCXT non disponible: {exc}")
            return None

    def get_indicators(self, symbol: str = "BTC/USDT") -> dict:
        """Récupère OHLCV et calcule RSI, MACD, BB, ATR."""
        # Actifs non-Binance → Yahoo Finance directement (pas de clé API requise)
        if symbol in _YAHOO_SYMBOLS:
            return self._yahoo_indicators(symbol)

        if self._exchange is None:
            return self._generate_mock(symbol)

        try:
            ohlcv = self._exchange.fetch_ohlcv(symbol, "15m", limit=100)
            ticker = self._exchange.fetch_ticker(symbol)

            closes = np.array([c[4] for c in ohlcv])
            highs = np.array([c[2] for c in ohlcv])
            lows = np.array([c[3] for c in ohlcv])
            volumes = np.array([c[5] for c in ohlcv])

            funding = 0.0
            try:
                fr = self._exchange.fetch_funding_rate(symbol)
                funding = float(fr.get("fundingRate", 0))
            except Exception:
                pass

            # Accumuler l'historique funding pour le circuit breaker soutenu
            _FUNDING_HISTORY.append(funding)

            # MA50 journalière (filtre de tendance macro)
            ma_50 = 0.0
            try:
                ohlcv_daily = self._exchange.fetch_ohlcv(symbol, "1d", limit=50)
                daily_closes = np.array([c[4] for c in ohlcv_daily])
                ma_50 = float(np.mean(daily_closes[-50:]))
            except Exception:
                pass

            price = float(ticker["last"])

            # Sanity check : le prix est-il cohérent avec l'actif ?
            _range = _PRICE_SANITY.get(symbol)
            if _range and not (_range[0] <= price <= _range[1]):
                logger.warning(
                    f"Prix CCXT incohérent pour {symbol}: {price:.2f} "
                    f"(attendu {_range[0]}-{_range[1]}) — fallback mock"
                )
                return self._generate_mock(symbol)

            rsi_raw = round(float(self._rsi(closes, 14)), 2)
            # Valeur aberrante = données testnet synthétiques → fallback mock
            if rsi_raw < 10 or rsi_raw > 95:
                logger.warning(f"RSI aberrant ({rsi_raw}) pour {symbol} — fallback mock")
                return self._generate_mock(symbol)

            # --- Multi-timeframe : 1h et 4h ---
            rsi_1h, rsi_4h, trend_4h = None, None, None
            try:
                ohlcv_1h = self._exchange.fetch_ohlcv(symbol, "1h", limit=50)
                closes_1h = np.array([c[4] for c in ohlcv_1h])
                rsi_1h = round(float(self._rsi(closes_1h, 14)), 1)
            except Exception:
                pass
            try:
                ohlcv_4h = self._exchange.fetch_ohlcv(symbol, "4h", limit=30)
                closes_4h = np.array([c[4] for c in ohlcv_4h])
                rsi_4h = round(float(self._rsi(closes_4h, 14)), 1)
                trend_4h = "UP" if closes_4h[-1] > closes_4h[-20] else "DOWN"
            except Exception:
                pass

            return {
                "symbol": symbol,
                "price": price,
                "rsi_14": rsi_raw,
                "rsi_1h": rsi_1h,
                "rsi_4h": rsi_4h,
                "trend_4h": trend_4h,
                "macd": round(float(self._macd(closes)[0]), 4),
                "macd_signal": round(float(self._macd(closes)[1]), 4),
                "bb_upper": round(float(self._bb(closes)[0]), 2),
                "bb_lower": round(float(self._bb(closes)[1]), 2),
                "atr_14": round(float(self._atr(highs, lows, closes, 14)), 2),
                "volume_24h": round(float(ticker.get("quoteVolume", 0)), 0),
                "funding_rate": round(funding, 6),
                "recent_funding_rates": list(_FUNDING_HISTORY),
                "ma_50": round(ma_50, 2),
                "above_ma50": bool(ma_50 > 0 and price > ma_50),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as exc:
            logger.error(f"Market data fetch error: {exc}")
            return self._generate_mock(symbol)

    # ---- Indicateurs TA ----

    def _yahoo_indicators(self, symbol: str) -> dict:
        """Fallback Yahoo Finance Chart API (sans clé API) pour XAU/USD, EUR/USD, etc."""
        import json
        import urllib.request as _ur

        ticker = _YAHOO_SYMBOLS.get(symbol, symbol)
        headers = {"User-Agent": "atlas-trader/2.0", "Accept": "application/json"}
        timeout = 15

        def _yget(url: str):
            req = _ur.Request(url, headers=headers)
            with _ur.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())

        try:
            data = _yget(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                f"?interval=15m&range=1d&includePrePost=false"
            )
            res   = data["chart"]["result"][0]
            meta  = res["meta"]
            quote = res["indicators"]["quote"][0]

            raw_c = quote.get("close", [])
            raw_h = quote.get("high",  [])
            raw_l = quote.get("low",   [])
            raw_v = quote.get("volume", [])
            closes  = np.array([c for c in raw_c if c is not None], dtype=float)
            highs   = np.array([c for c in raw_h if c is not None], dtype=float)
            lows    = np.array([c for c in raw_l if c is not None], dtype=float)
            volumes = np.array([c for c in raw_v if c is not None], dtype=float)

            price = float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0)

            # MA50 daily — utilise adjclose si dispo (gère les rolls futurs)
            ma_50 = 0.0
            try:
                d_data = _yget(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                    f"?interval=1d&range=3mo"
                )
                d_res = d_data["chart"]["result"][0]
                # adjclose corrige les discontinuités de roll pour les futures (CL=F, SI=F, GC=F)
                adjc_arr = d_res.get("indicators", {}).get("adjclose", [{}])
                dc_adj = (adjc_arr[0].get("adjclose", []) if adjc_arr else [])
                dc_raw = d_res["indicators"]["quote"][0].get("close", [])
                dc = dc_adj if dc_adj else dc_raw
                daily = np.array([c for c in dc if c is not None], dtype=float)
                if len(daily) >= 10:
                    ma_50 = float(np.mean(daily[-min(50, len(daily)):]))
            except Exception:
                pass

            rsi  = round(float(self._rsi(closes, 14)), 2) if len(closes) >= 15 else 50.0
            macd, macd_sig = (self._macd(closes) if len(closes) >= 26
                              else (0.0, 0.0))
            bb_u, bb_l = (self._bb(closes) if len(closes) >= 20
                          else (price * 1.02, price * 0.98))
            atr = (float(self._atr(highs, lows, closes, 14))
                   if len(closes) >= 15 and len(highs) >= 15 else 0.0)

            return {
                "symbol":               symbol,
                "price":                price,
                "rsi_14":               rsi,
                "rsi_1h":               None,
                "rsi_4h":               None,
                "trend_4h":             None,
                "macd":                 round(float(macd), 6),
                "macd_signal":          round(float(macd_sig), 6),
                "bb_upper":             round(float(bb_u), 6),
                "bb_lower":             round(float(bb_l), 6),
                "atr_14":               round(float(atr), 6),
                "volume_24h":           float(volumes.sum()) if len(volumes) else 0.0,
                "funding_rate":         0.0,
                "recent_funding_rates": [],
                "ma_50":                round(ma_50, 6),
                "above_ma50":           bool(ma_50 > 0 and price > ma_50),
                "timestamp":            datetime.utcnow().isoformat(),
                "_source":              "yahoo",
            }
        except Exception as exc:
            logger.warning(f"Yahoo Finance fallback failed for {symbol} ({ticker}): {exc}")
            return self._generate_mock(symbol)

    @staticmethod
    def _rsi(closes: np.ndarray, period: int = 14) -> float:
        delta = np.diff(closes)
        gains = np.where(delta > 0, delta, 0)
        losses = np.where(delta < 0, -delta, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _macd(closes: np.ndarray) -> tuple[float, float]:
        def ema(data, n):
            k = 2 / (n + 1)
            result = [data[0]]
            for v in data[1:]:
                result.append(v * k + result[-1] * (1 - k))
            return np.array(result)
        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        macd_line = ema12 - ema26
        signal = ema(macd_line, 9)
        return macd_line[-1], signal[-1]

    @staticmethod
    def _bb(closes: np.ndarray, period: int = 20) -> tuple[float, float]:
        sma = np.mean(closes[-period:])
        std = np.std(closes[-period:])
        return sma + 2 * std, sma - 2 * std

    @staticmethod
    def _atr(highs: np.ndarray, lows: np.ndarray,
              closes: np.ndarray, period: int = 14) -> float:
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1])
            )
        )
        return np.mean(tr[-period:])

    @staticmethod
    def _generate_mock(symbol: str) -> dict:
        """Données de marché simulées pour les tests."""
        import random
        base = _MOCK_PRICES.get(symbol, 65_000.0)
        price = base * (1 + random.uniform(-0.03, 0.03))
        ma_50 = price * 1.02  # simulation : prix légèrement sous la MA50
        return {
            "symbol": symbol,
            "price": round(price, 2),
            "rsi_14": round(random.uniform(30, 70), 2),
            "rsi_1h": round(random.uniform(30, 70), 1),
            "rsi_4h": round(random.uniform(30, 70), 1),
            "trend_4h": random.choice(["UP", "DOWN"]),
            "macd": round(random.uniform(-100, 100), 4),
            "macd_signal": round(random.uniform(-100, 100), 4),
            "bb_upper": round(price * 1.02, 2),
            "bb_lower": round(price * 0.98, 2),
            "atr_14": round(price * 0.015, 2),
            "volume_24h": round(random.uniform(1e9, 5e9), 0),
            "funding_rate": round(random.uniform(-0.01, 0.03), 6),
            "recent_funding_rates": [round(random.uniform(-0.01, 0.03), 6) for _ in range(4)],
            "ma_50": round(ma_50, 2),
            "above_ma50": bool(price > ma_50),
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    def analyze(self, state: dict) -> dict:
        """Interface compatible LangGraph — retourne un AgentAnalysis."""
        indicators = self.get_indicators(state.get("asset", "BTC/USDT"))
        rsi = indicators.get("rsi_14", 50)
        macd = indicators.get("macd", 0)
        signal_val = indicators.get("macd_signal", 0)

        # Score heuristique
        score = 50.0
        if rsi < 30: score += 25
        elif rsi > 70: score -= 25
        if macd > signal_val: score += 15
        else: score -= 15
        score = max(0, min(100, score))

        signal = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
        return {
            "agent_name": "market_data",
            "score": round(score, 1),
            "signal": signal,
            "summary": (
                f"RSI={rsi:.0f} MACD={'>' if macd > signal_val else '<'} signal "
                f"Price={indicators.get('price', 0):.0f}"
            ),
            "confidence": 0.8,
            "indicators": indicators,
        }
