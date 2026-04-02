"""
agents/market_data_agent.py — Indicateurs techniques via CCXT.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

import numpy as np

logger = logging.getLogger("zeitgeist.market_data")


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
            exchange = exchange_class({"enableRateLimit": True})
            if cfg.get("testnet", True):
                exchange.set_sandbox_mode(True)
            return exchange
        except Exception as exc:
            logger.warning(f"CCXT non disponible: {exc}")
            return None

    def get_indicators(self, symbol: str = "BTC/USDT") -> dict:
        """Récupère OHLCV et calcule RSI, MACD, BB, ATR."""
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

            # MA50 journalière (filtre de tendance macro)
            ma_50 = 0.0
            try:
                ohlcv_daily = self._exchange.fetch_ohlcv(symbol, "1d", limit=50)
                daily_closes = np.array([c[4] for c in ohlcv_daily])
                ma_50 = float(np.mean(daily_closes[-50:]))
            except Exception:
                pass

            price = float(ticker["last"])
            rsi_raw = round(float(self._rsi(closes, 14)), 2)
            # Valeur aberrante = données testnet synthétiques → fallback mock
            if rsi_raw < 10 or rsi_raw > 95:
                logger.warning(f"RSI testnet aberrant ({rsi_raw}) — fallback mock")
                return self._generate_mock(symbol)
            return {
                "symbol": symbol,
                "price": price,
                "rsi_14": rsi_raw,
                "macd": round(float(self._macd(closes)[0]), 4),
                "macd_signal": round(float(self._macd(closes)[1]), 4),
                "bb_upper": round(float(self._bb(closes)[0]), 2),
                "bb_lower": round(float(self._bb(closes)[1]), 2),
                "atr_14": round(float(self._atr(highs, lows, closes, 14)), 2),
                "volume_24h": round(float(ticker.get("quoteVolume", 0)), 0),
                "funding_rate": round(funding, 6),
                "ma_50": round(ma_50, 2),
                "above_ma50": bool(ma_50 > 0 and price > ma_50),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as exc:
            logger.error(f"Erreur récupération market data: {exc}")
            return self._generate_mock(symbol)

    # ---- Indicateurs TA ----

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
        price = 65000 + random.uniform(-2000, 2000)
        ma_50 = price * 1.08  # simulation : prix sous la MA50 (contexte baissier)
        return {
            "symbol": symbol,
            "price": round(price, 2),
            "rsi_14": round(random.uniform(30, 70), 2),
            "macd": round(random.uniform(-100, 100), 4),
            "macd_signal": round(random.uniform(-100, 100), 4),
            "bb_upper": round(price * 1.02, 2),
            "bb_lower": round(price * 0.98, 2),
            "atr_14": round(price * 0.015, 2),
            "volume_24h": round(random.uniform(1e9, 5e9), 0),
            "funding_rate": round(random.uniform(-0.01, 0.03), 6),
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
