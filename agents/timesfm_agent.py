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
# SINGLETON : un seul pool partagé entre tous les actifs (5 assets × 2GB = OOM sinon)
# Le sémaphore garantit qu'un seul actif soumet au worker à la fois.
import threading as _threading
_PROC_POOL = None
_POOL_LOCK = _threading.Lock()           # protège la création du pool
_TFM_SEMAPHORE = _threading.Semaphore(1) # 1 seul appel TimesFM en parallèle


def _get_pool():
    """Retourne le pool singleton (crée-le si besoin, thread-safe)."""
    global _PROC_POOL
    if _PROC_POOL is None:
        with _POOL_LOCK:
            if _PROC_POOL is None:  # double-check sous lock
                import multiprocessing as _mp
                from concurrent.futures import ProcessPoolExecutor
                _PROC_POOL = ProcessPoolExecutor(
                    max_workers=1,
                    mp_context=_mp.get_context("spawn"),  # toujours spawn — évite fork+PyTorch
                )
    return _PROC_POOL


def _reset_pool():
    """Détruit le pool crashé et en crée un neuf (thread-safe)."""
    global _PROC_POOL
    with _POOL_LOCK:
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
    Agent TimesFM — forecast prix via foundation model.

    Prend les N dernières candles OHLCV 15min,
    génère un forecast multi-horizon avec quantiles,
    et retourne un score de conviction basé sur :
      - direction prédite (hausse/baisse)
      - magnitude du mouvement attendu
      - largeur de l'intervalle de confiance (incertitude)
    """

    # Symboles Yahoo Finance pour les actifs non-crypto
    _YF_MAP = {
        "XAU/USD": "GC=F",
        "EUR/USD": "EURUSD=X",
        "GBP/USD": "GBPUSD=X",
        "USD/JPY": "JPY=X",
    }

    def __init__(self):
        # Config chargée au moment de analyze() pour respecter le per-asset
        self._horizon = 24
        self._backend = "cpu"

    def _load_config(self, asset: str | None) -> None:
        """Charge horizon et backend depuis la config per-asset si dispo."""
        try:
            if asset:
                from utils.config import load_asset_config
                cfg = load_asset_config(asset)
            else:
                from utils.config import load_settings
                cfg = load_settings()
            tfm_cfg = cfg.get("timesfm", {})
            self._horizon = int(tfm_cfg.get("forecast_horizon", 24))
            self._backend = tfm_cfg.get("backend", "cpu")
        except Exception:
            pass  # garder les valeurs par défaut

    def analyze(self, state: dict) -> dict:
        """Run TimesFM forecast in a child process and return agent analysis dict."""
        try:
            from concurrent.futures import BrokenProcessPool
        except ImportError:
            from concurrent.futures.process import BrokenProcessPool
        t0 = time.time()
        asset = state.get("asset", "BTC/USDT")
        self._load_config(asset)

        try:
            closes = self._get_close_prices(state)
            if closes is None or len(closes) < 50:
                return self._fallback("insufficient OHLCV data")
            logger.info(f"TimesFM [{asset}]: {len(closes)} candles (last={closes[-1]:.4f})")

            # Soumettre au processus enfant (spawn) — isolé du daemon
            # Sémaphore global : 1 seul actif à la fois utilise le worker
            # (évite 5×2GB RAM en simultané avec 5 actifs parallèles)
            logger.info(f"TimesFM [{asset}]: attente sémaphore (1 worker partagé)...")
            acquired = _TFM_SEMAPHORE.acquire(timeout=360)  # attend max 6min
            if not acquired:
                logger.warning(f"TimesFM [{asset}]: timeout sémaphore 360s — fallback")
                return self._fallback("semaphore timeout")
            try:
                logger.info(f"TimesFM [{asset}]: sémaphore acquis — soumission au worker...")
                pool = _get_pool()
                fut = pool.submit(_timesfm_worker, closes.tolist(), self._backend, self._horizon)
                try:
                    point_list, quant_list = fut.result(timeout=300)
                except BrokenProcessPool:
                    logger.error("TimesFM: processus enfant tué (OOM/segfault) — pool réinitialisé")
                    _reset_pool()
                    return self._fallback("subprocess killed (OOM/segfault)")
                except TimeoutError:
                    logger.error("TimesFM: timeout 300s — pool réinitialisé")
                    _reset_pool()
                    return self._fallback("subprocess timeout (300s)")
            finally:
                _TFM_SEMAPHORE.release()
                logger.info(f"TimesFM [{asset}]: sémaphore libéré")

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
        """Extract close prices (500 candles) — CCXT pour crypto, Yahoo Finance pour le reste."""
        indicators = state.get("market_indicators") or {}
        asset = state.get("asset", "BTC/USDT")

        # Récupérer depuis le cache ohlcv_raw si disponible
        ohlcv_raw = indicators.get("ohlcv_raw")
        if ohlcv_raw is not None and len(ohlcv_raw) >= 50:
            return np.array([c[4] for c in ohlcv_raw], dtype=np.float64)

        # Actifs crypto — CCXT Binance (500 candles 15m)
        if asset not in self._YF_MAP:
            try:
                import ccxt
                exchange = ccxt.binance({"enableRateLimit": True})
                ohlcv = exchange.fetch_ohlcv(asset, "15m", limit=500)
                return np.array([c[4] for c in ohlcv], dtype=np.float64)
            except Exception as exc:
                logger.warning(f"TimesFM CCXT fallback échoué ({asset}): {exc}")
                return None

        # Actifs non-crypto (XAU, EUR, GBP) — Yahoo Finance 15m (5 jours ≈ 480 candles)
        try:
            import json
            import urllib.request as _ur
            yf_ticker = self._YF_MAP[asset]
            req = _ur.Request(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_ticker}"
                f"?interval=15m&range=5d&includePrePost=false",
                headers={"User-Agent": "atlas-trader/2.0"},
            )
            with _ur.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            raw_c = data["chart"]["result"][0]["indicators"]["quote"][0].get("close", [])
            closes = np.array([c for c in raw_c if c is not None], dtype=np.float64)
            if len(closes) >= 50:
                return closes
            logger.warning(f"TimesFM Yahoo Finance trop peu de candles ({len(closes)}) pour {asset}")
            return None
        except Exception as exc:
            logger.warning(f"TimesFM Yahoo Finance fallback échoué ({asset}): {exc}")
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
