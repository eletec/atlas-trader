"""
agents/timesfm_agent.py — TimesFM price forecasting agent.
Uses Google's TimesFM (1.3.x package, 2.0-500m model)
to forecast BTC price from OHLCV history.

Returns a score 0-100 based on predicted price direction,
magnitude, and quantile-based confidence intervals.

ARCHITECTURE — subprocess isolation :
  TimesFM charge un modèle PyTorch de ~2GB en RAM. Sur NAS, le kernel
  OOM-killer envoie SIGKILL au process Python — aucun try/except ne peut
  l'intercepter. Solution : exécuter PyTorch dans un processus ENFANT séparé
  (ProcessPoolExecutor, spawn). Si l'enfant est tué, le daemon parent survit.
  Le modèle est mis en cache dans le processus enfant (persist entre cycles).
"""
from __future__ import annotations

import logging
import time

import numpy as np

logger = logging.getLogger("zeitgeist.timesfm")


# ── Worker subprocess — doit être au niveau module pour être picklable ────────

# Cache du modèle dans le processus ENFANT (survit entre les cycles)
_CHILD_MODEL = None


def _timesfm_worker(closes_list: list, backend: str, horizon: int) -> tuple[list, list]:
    """
    S'exécute dans un processus ENFANT (ProcessPoolExecutor, spawn).
    Si PyTorch OOM / segfault → seul cet enfant meurt, le daemon survit.
    Le modèle est chargé une seule fois par vie du processus enfant.
    """
    global _CHILD_MODEL
    import timesfm as _tfm
    import numpy as _np

    if _CHILD_MODEL is None:
        hparams = _tfm.TimesFmHparams(
            backend=backend,
            per_core_batch_size=1,   # 1 seule série par cycle — réduit la RAM de ~4GB à ~500MB
            horizon_len=horizon,
            num_layers=50,
            use_positional_embedding=False,
            context_len=512,         # 512 candles suffisent (était 2048) — réduit les activations x4
        )
        checkpoint = _tfm.TimesFmCheckpoint(
            huggingface_repo_id="google/timesfm-2.0-500m-pytorch",
        )
        _CHILD_MODEL = _tfm.TimesFm(hparams=hparams, checkpoint=checkpoint)

    closes = _np.array(closes_list, dtype=_np.float64)
    point_forecast, quantile_forecast = _CHILD_MODEL.forecast([closes], freq=[0])
    return point_forecast[0].tolist(), quantile_forecast[0].tolist()


# ── Pool de processus persistant (1 worker — modèle reste en mémoire) ────────
_PROC_POOL = None


def _get_pool():
    """Retourne le pool existant ou en crée un nouveau."""
    global _PROC_POOL
    if _PROC_POOL is None:
        import multiprocessing as _mp
        from concurrent.futures import ProcessPoolExecutor
        _PROC_POOL = ProcessPoolExecutor(
            max_workers=1,
            mp_context=_mp.get_context("spawn"),  # toujours spawn — évite fork+PyTorch
        )
    return _PROC_POOL


def _reset_pool():
    """Détruit le pool crashé et en crée un neuf."""
    global _PROC_POOL
    if _PROC_POOL is not None:
        try:
            _PROC_POOL.shutdown(wait=False)
        except Exception:
            pass
    import multiprocessing as _mp
    from concurrent.futures import ProcessPoolExecutor
    _PROC_POOL = ProcessPoolExecutor(
        max_workers=1,
        mp_context=_mp.get_context("spawn"),
    )


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
        """Run TimesFM forecast in a child process and return agent analysis dict."""
        from concurrent.futures import BrokenProcessPool
        t0 = time.time()

        try:
            logger.info("TimesFM: Récupération des prix close...")
            closes = self._get_close_prices(state)
            if closes is None or len(closes) < 50:
                return self._fallback("insufficient OHLCV data")
            logger.info(f"TimesFM: {len(closes)} candles récupérées (last={closes[-1]:.2f})")

            # Soumettre au processus enfant (spawn) — isolé du daemon
            # Premier appel : enfant démarre + charge le modèle (~2-5 min)
            # Appels suivants : enfant réutilisé, modèle déjà en mémoire (cache)
            logger.info("TimesFM: Soumission au processus enfant (subprocess isolé)...")
            pool = _get_pool()
            fut = pool.submit(_timesfm_worker, closes.tolist(), self._backend, self._horizon)
            try:
                point_list, quant_list = fut.result(timeout=300)
            except BrokenProcessPool:
                # L'enfant a été tué (OOM/segfault) — on recrée le pool, daemon intact
                logger.error("TimesFM: processus enfant tué (OOM/segfault) — pool réinitialisé")
                _reset_pool()
                return self._fallback("subprocess killed (OOM/segfault)")
            except TimeoutError:
                logger.error("TimesFM: timeout 300s — pool réinitialisé")
                _reset_pool()
                return self._fallback("subprocess timeout (300s)")

            point_forecast = np.array(point_list)
            quantile_forecast = np.array(quant_list)
            t_fc = time.time()
            logger.info(f"TimesFM: Forecast reçu en {t_fc - t0:.1f}s total")

            result = self._interpret(closes, point_forecast, quantile_forecast)
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

        except BaseException as exc:
            logger.error(f"TimesFM error ({type(exc).__name__}): {exc}")
            _reset_pool()
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
