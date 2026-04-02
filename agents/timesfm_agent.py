"""
agents/timesfm_agent.py — TimesFM price forecasting agent.
Uses Google's TimesFM (1.3.x package, 2.0-500m model)
to forecast BTC price from OHLCV history.

Returns a score 0-100 based on predicted price direction,
magnitude, and quantile-based confidence intervals.
"""
from __future__ import annotations

import logging
import time

import numpy as np

logger = logging.getLogger("zeitgeist.timesfm")

# Lazy-loaded singleton to avoid reloading model every cycle
_MODEL = None


def _get_model(backend: str = "cpu", horizon: int = 128):
    """Load TimesFM model once (lazy singleton)."""
    global _MODEL
    if _MODEL is not None:
        logger.debug("TimesFM model already loaded (singleton)")
        return _MODEL

    import timesfm

    logger.info("="*60)
    logger.info("TimesFM: PREMIER CHARGEMENT — téléchargement du modèle 500M...")
    logger.info("  Repo: google/timesfm-2.0-500m-pytorch")
    logger.info(f"  Backend: {backend} | Horizon: {horizon}")
    logger.info("  Ceci peut prendre 2-5 min au premier lancement.")
    logger.info("="*60)

    t0 = time.time()

    logger.info("TimesFM: Initialisation TimesFmHparams...")
    hparams = timesfm.TimesFmHparams(
        backend=backend,
        per_core_batch_size=32,
        horizon_len=horizon,
        num_layers=50,
        use_positional_embedding=False,
        context_len=2048,
    )
    logger.info(f"TimesFM: Hparams OK ({time.time()-t0:.1f}s)")

    logger.info("TimesFM: Téléchargement/chargement checkpoint HuggingFace...")
    t_dl = time.time()
    checkpoint = timesfm.TimesFmCheckpoint(
        huggingface_repo_id="google/timesfm-2.0-500m-pytorch",
    )
    logger.info(f"TimesFM: Checkpoint référencé ({time.time()-t_dl:.1f}s)")

    logger.info("TimesFM: Construction du modèle (TimesFm)...")
    t_build = time.time()
    model = timesfm.TimesFm(hparams=hparams, checkpoint=checkpoint)
    logger.info(f"TimesFM: Modèle construit et prêt ({time.time()-t_build:.1f}s)")

    elapsed = time.time() - t0
    logger.info(f"TimesFM: CHARGEMENT TERMINÉ en {elapsed:.1f}s")

    _MODEL = model
    return model


class TimesFMAgent:
    """
    Agent TimesFM — forecast prix BTC via foundation model.

    Prend les N dernières candles OHLCV 15min du MarketDataAgent,
    génère un forecast multi-horizon avec quantiles,
    et retourne un score de conviction basé sur :
      - direction prédite (hausse/baisse)
      - magnitude du mouvement attendu
      - largeur de l'intervalle de confiance (incertitude)
    """

    def __init__(self):
        from utils.config import load_settings
        cfg = load_settings()
        self._tfm_cfg = cfg.get("timesfm", {})
        self._horizon = int(self._tfm_cfg.get("forecast_horizon", 24))  # candles
        self._backend = self._tfm_cfg.get("backend", "cpu")

    def analyze(self, state: dict) -> dict:
        """Run TimesFM forecast and return agent analysis dict."""
        t0 = time.time()

        try:
            logger.info("TimesFM: Récupération des prix close...")
            closes = self._get_close_prices(state)
            if closes is None or len(closes) < 50:
                return self._fallback("insufficient OHLCV data")
            logger.info(f"TimesFM: {len(closes)} candles récupérées (last={closes[-1]:.2f})")

            logger.info("TimesFM: Chargement du modèle...")
            model = _get_model(backend=self._backend, horizon=self._horizon)

            logger.info(f"TimesFM: Lancement forecast (horizon={self._horizon})...")
            t_fc = time.time()
            # freq=0 → high-frequency (sub-daily) data
            # Timeout 120s pour éviter les blocages
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
                _fut = _pool.submit(model.forecast, [closes], freq=[0])
                try:
                    point_forecast, quantile_forecast = _fut.result(timeout=120)
                except concurrent.futures.TimeoutError:
                    return self._fallback("forecast timeout (120s)")
            logger.info(f"TimesFM: Forecast terminé en {time.time()-t_fc:.1f}s")

            result = self._interpret(closes, point_forecast[0], quantile_forecast[0])
            elapsed_ms = int((time.time() - t0) * 1000)

            logger.info(
                f"TimesFM forecast: direction={result['direction']} "
                f"change={result['pct_change']:.2f}% "
                f"score={result['score']:.0f} "
                f"confidence={result['confidence']:.2f} "
                f"({elapsed_ms}ms)"
            )

            return {
                "agent_name": "timesfm",
                "score": result["score"],
                "signal": result["direction"],
                "summary": result["summary"],
                "confidence": result["confidence"],
                "forecast_details": {
                    "horizon_candles": self._horizon,
                    "current_price": float(closes[-1]),
                    "predicted_price": float(result["predicted_price"]),
                    "pct_change": result["pct_change"],
                    "q10": float(result["q10"]),
                    "q90": float(result["q90"]),
                    "latency_ms": elapsed_ms,
                },
            }

        except Exception as exc:
            logger.error(f"TimesFM error: {exc}")
            return self._fallback(str(exc))

    def _get_close_prices(self, state: dict) -> np.ndarray | None:
        """Extract close prices from market_indicators or fetch directly."""
        indicators = state.get("market_indicators") or {}

        # Try to get OHLCV from market data agent's raw data
        ohlcv_raw = indicators.get("ohlcv_raw")
        if ohlcv_raw is not None and len(ohlcv_raw) > 50:
            return np.array([c[4] for c in ohlcv_raw], dtype=np.float64)

        # Fallback: fetch directly via CCXT (mainnet for real prices)
        try:
            import ccxt
            exchange = ccxt.binance({"enableRateLimit": True})
            asset = state.get("asset", "BTC/USDT")
            ohlcv = exchange.fetch_ohlcv(asset, "15m", limit=500)
            return np.array([c[4] for c in ohlcv], dtype=np.float64)
        except Exception as exc:
            logger.warning(f"CCXT fallback failed: {exc}")
            return None

    def _interpret(
        self,
        closes: np.ndarray,
        point_forecast: np.ndarray,
        quantile_forecast: np.ndarray,
    ) -> dict:
        """
        Convert raw forecast into a trading score.

        point_forecast shape: (horizon,)
        quantile_forecast shape: (horizon, num_quantiles) — experimental quantile heads
        """
        current_price = float(closes[-1])
        predicted_price = float(point_forecast[-1])  # end of horizon
        pct_change = ((predicted_price - current_price) / current_price) * 100

        # Quantiles at end of horizon: index 1 = 10th, index 9 = 90th
        q10 = float(quantile_forecast[-1, 1]) if quantile_forecast.ndim == 2 else predicted_price * 0.97
        q90 = float(quantile_forecast[-1, -2]) if quantile_forecast.ndim == 2 else predicted_price * 1.03

        # Confidence = inverse of relative spread (tighter = more confident)
        spread = (q90 - q10) / current_price if current_price > 0 else 0.1
        confidence = max(0.1, min(1.0, 1.0 - spread * 10))

        # Score mapping:
        # Strong up (>2%)   → 75-90
        # Moderate up (0.5-2%) → 60-75
        # Flat (-0.5 to 0.5%) → 45-55
        # Moderate down (-2 to -0.5%) → 25-40
        # Strong down (<-2%) → 10-25
        if pct_change >= 2.0:
            score = min(90, 75 + pct_change * 2)
        elif pct_change >= 0.5:
            score = 60 + (pct_change - 0.5) * 10
        elif pct_change >= -0.5:
            score = 50 + pct_change * 10
        elif pct_change >= -2.0:
            score = 40 + (pct_change + 0.5) * 10
        else:
            score = max(10, 25 + pct_change * 2)

        score = max(0, min(100, score))

        direction = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")

        summary = (
            f"TimesFM forecast: {pct_change:+.2f}% over {self._horizon} candles "
            f"(${current_price:,.0f} → ${predicted_price:,.0f}). "
            f"CI: [${q10:,.0f}, ${q90:,.0f}]. "
            f"Confidence: {confidence:.0%}."
        )

        return {
            "score": round(score, 1),
            "direction": direction,
            "confidence": round(confidence, 2),
            "pct_change": round(pct_change, 2),
            "predicted_price": predicted_price,
            "q10": q10,
            "q90": q90,
            "summary": summary,
        }

    def _fallback(self, reason: str) -> dict:
        logger.warning(f"TimesFM fallback: {reason}")
        return {
            "agent_name": "timesfm",
            "score": 50.0,
            "signal": "NEUTRAL",
            "summary": f"TimesFM unavailable ({reason})",
            "confidence": 0.0,
        }
