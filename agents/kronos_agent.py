"""
agents/kronos_agent.py — Kronos OHLCV foundation model forecasting agent.

Uses the Kronos model (NeoQuasar/Kronos-mini|small|base on HuggingFace,
accepted at AAAI 2026) to forecast future OHLCV from price history.

Returns a score 0-100 based on predicted close price direction and magnitude.

ARCHITECTURE — subprocess isolation :
  Kronos charge un Transformer PyTorch (4M–102M params). Sur NAS GX10 le
  kernel OOM-killer peut envoyer SIGKILL — aucun try/except ne l'intercepte.
  Solution identique à TimesFM : ProcessPoolExecutor(spawn) = processus ENFANT
  isolé. Si l'enfant est tué, le daemon parent survit.
  Un seul pool partagé entre tous les actifs (5 actifs × RAM sinon OOM).
  Sémaphore(1) garantit un seul appel Kronos en parallèle.
"""
from __future__ import annotations

import logging
import time
import threading as _threading

import numpy as np

logger = logging.getLogger("zeitgeist.kronos")


# ── Worker subprocess — au niveau MODULE pour être picklable (ProcessPool) ────

# Cache dans le processus ENFANT (survit entre les cycles)
_CHILD_MODEL: object | None = None
_CHILD_MODEL_NAME: str | None = None  # track quel modèle est chargé


def _kronos_worker(
    ohlcv_list: list,      # [[ts_ms, open, high, low, close, volume], ...]
    model_name: str,       # "NeoQuasar/Kronos-mini"
    horizon: int,          # candles à prédire
    lookback: int,         # max candles contexte
    T: float,              # sampling temperature
    top_p: float,          # nucleus sampling
    sample_count: int,     # trajectoires probabilistes
) -> dict:
    """
    S'exécute dans un processus ENFANT (ProcessPoolExecutor, spawn).
    Si PyTorch OOM / segfault → seul cet enfant meurt, le daemon survit.
    Le modèle est chargé une seule fois par vie du processus enfant.

    Returns:
        {
            "predicted_closes": [float, ...],   # liste des closes prédits (len=horizon)
            "current_price": float,             # close[-1] du contexte
            "current_ts_iso": str,              # timestamp ISO du dernier candle
        }
    """
    global _CHILD_MODEL, _CHILD_MODEL_NAME

    import pandas as _pd
    import numpy as _np
    from datetime import timedelta

    # Construire le DataFrame OHLCV (Kronos attend open/high/low/close + timestamp index)
    rows = ohlcv_list[-lookback:] if len(ohlcv_list) > lookback else ohlcv_list
    # rows = [[ts_ms, open, high, low, close, volume], ...]
    df = _pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = _pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df.dropna(subset=["open", "high", "low", "close"])

    if len(df) < 10:
        raise ValueError(f"Insufficient OHLCV rows after cleaning: {len(df)}")

    # Charger le modèle si absent ou changé
    if _CHILD_MODEL is None or _CHILD_MODEL_NAME != model_name:
        from kronos import KronosPredictor  # pylint: disable=import-error
        _CHILD_MODEL = KronosPredictor(model_name)
        _CHILD_MODEL_NAME = model_name

    predictor = _CHILD_MODEL

    # Timestamps prédiction
    x_timestamp = df.index[-1]
    # On suppose candles 15 min (atlas standard)
    freq_min = _infer_freq_minutes(df)
    y_timestamp = x_timestamp + timedelta(minutes=freq_min * horizon)

    # Appel Kronos — retourne un DataFrame OHLCV horizon×5
    forecast_df = predictor.predict(
        df,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=horizon,
        T=T,
        top_p=top_p,
        sample_count=sample_count,
    )

    # Extraire les closes prédits (si sample_count > 1, la moyenne est attendue)
    predicted_closes = forecast_df["close"].values.tolist()
    current_price = float(df["close"].iloc[-1])

    return {
        "predicted_closes": predicted_closes,
        "current_price": current_price,
        "current_ts_iso": str(x_timestamp),
    }


def _infer_freq_minutes(df) -> int:
    """Infère la fréquence des candles en minutes depuis l'index DatetimeIndex."""
    if len(df) < 2:
        return 15  # atlas default
    import pandas as _pd
    median_delta = _pd.Series(df.index).diff().dropna().median()
    return max(1, int(median_delta.total_seconds() / 60))


# ── Pool de processus persistant — SINGLETON partagé entre tous les actifs ───
_PROC_POOL = None
_POOL_LOCK = _threading.Lock()
_KRONOS_SEMAPHORE = _threading.Semaphore(1)  # 1 seul appel Kronos en parallèle


def _get_pool():
    """Retourne le pool singleton (le crée si nécessaire, thread-safe)."""
    global _PROC_POOL
    if _PROC_POOL is None:
        with _POOL_LOCK:
            if _PROC_POOL is None:
                import multiprocessing as _mp
                from concurrent.futures import ProcessPoolExecutor
                _PROC_POOL = ProcessPoolExecutor(
                    max_workers=1,
                    mp_context=_mp.get_context("spawn"),
                )
    return _PROC_POOL


def _reset_pool():
    """Détruit le pool crashé et en recrée un (thread-safe)."""
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


# ── Agent class ───────────────────────────────────────────────────────────────


class KronosAgent:
    """
    Agent Kronos — forecast prix via foundation model OHLCV.

    Prend les N dernières candles OHLCV 15min, génère un forecast probabiliste
    avec Kronos (transformer décoder-only, AAAI 2026), et retourne un score de
    conviction basé sur la direction et magnitude du mouvement prédit.

    Tous les paramètres sont configurables depuis le panneau admin.
    """

    def __init__(self):
        # Valeurs par défaut (écrasées par _load_config)
        self._model_name = "NeoQuasar/Kronos-mini"
        self._horizon = 96          # 96 × 15min = 24h
        self._lookback = 400        # candles de contexte
        self._T = 1.0               # temperature
        self._top_p = 0.9           # nucleus sampling
        self._sample_count = 1      # trajectoires (1 = déterministe, ≥3 = probabiliste)
        self._timeout = 120         # secondes max pour le worker

    def _load_config(self, asset: str | None) -> None:
        """Charge les paramètres Kronos depuis la config per-asset ou global."""
        try:
            if asset:
                from utils.config import load_asset_config
                cfg = load_asset_config(asset)
            else:
                from utils.config import load_settings
                cfg = load_settings()
            k = cfg.get("kronos", {})
            self._model_name = str(k.get("model_name", self._model_name))
            self._horizon = int(k.get("forecast_horizon", self._horizon))
            self._lookback = int(k.get("lookback", self._lookback))
            self._T = float(k.get("temperature", self._T))
            self._top_p = float(k.get("top_p", self._top_p))
            self._sample_count = int(k.get("sample_count", self._sample_count))
            self._timeout = int(k.get("timeout_seconds", self._timeout))
        except Exception:
            pass  # conserver les valeurs par défaut

    def analyze(self, state: dict) -> dict:
        """Run Kronos forecast in a child process — returns standard agent dict."""
        try:
            from concurrent.futures import BrokenProcessPool
        except ImportError:
            from concurrent.futures.process import BrokenProcessPool

        t0 = time.time()
        asset = state.get("asset", "BTC/USDT")
        self._load_config(asset)

        try:
            ohlcv_raw = self._get_ohlcv_raw(state)
            if ohlcv_raw is None or len(ohlcv_raw) < 20:
                return self._fallback("insufficient OHLCV data")

            logger.info(
                f"Kronos [{asset}]: {len(ohlcv_raw)} candles, "
                f"model={self._model_name}, horizon={self._horizon}, "
                f"lookback={self._lookback}, T={self._T}, top_p={self._top_p}, "
                f"sample_count={self._sample_count}"
            )

            logger.info(f"Kronos [{asset}]: attente sémaphore (1 worker partagé)...")
            acquired = _KRONOS_SEMAPHORE.acquire(timeout=360)
            if not acquired:
                logger.warning(f"Kronos [{asset}]: timeout sémaphore 360s — fallback")
                return self._fallback("semaphore timeout")

            try:
                logger.info(f"Kronos [{asset}]: sémaphore acquis — soumission au worker...")
                pool = _get_pool()
                fut = pool.submit(
                    _kronos_worker,
                    ohlcv_raw,
                    self._model_name,
                    self._horizon,
                    self._lookback,
                    self._T,
                    self._top_p,
                    self._sample_count,
                )
                try:
                    worker_result = fut.result(timeout=self._timeout)
                except BrokenProcessPool:
                    logger.error("Kronos: processus enfant tué (OOM/segfault) — pool réinitialisé")
                    _reset_pool()
                    return self._fallback("subprocess killed (OOM/segfault)")
                except TimeoutError:
                    logger.error(f"Kronos: timeout {self._timeout}s — pool réinitialisé")
                    _reset_pool()
                    return self._fallback(f"subprocess timeout ({self._timeout}s)")
            finally:
                _KRONOS_SEMAPHORE.release()
                logger.info(f"Kronos [{asset}]: sémaphore libéré")

            t_fc = time.time()
            logger.info(f"Kronos: forecast reçu en {t_fc - t0:.1f}s total")

            result = self._interpret(
                worker_result["current_price"],
                worker_result["predicted_closes"],
            )
            elapsed_ms = int((time.time() - t0) * 1000)

            logger.info(
                f"Kronos forecast [{asset}]: direction={result['direction']} "
                f"change={result['pct_change']:+.2f}% "
                f"score={result['score']:.0f} "
                f"confidence={result['confidence']:.2f} "
                f"({elapsed_ms}ms)"
            )

            return {
                "agent_name": "kronos",
                "score": result["score"],
                "signal": result["direction"],
                "summary": result["summary"],
                "confidence": result["confidence"],
                "forecast_details": {
                    "model_name": self._model_name,
                    "horizon_candles": self._horizon,
                    "current_price": worker_result["current_price"],
                    "predicted_price": float(result["predicted_price"]),
                    "pct_change": result["pct_change"],
                    "latency_ms": elapsed_ms,
                    "current_ts": worker_result.get("current_ts_iso", ""),
                },
            }

        except BaseException as exc:
            logger.error(f"Kronos error ({type(exc).__name__}): {exc}")
            _reset_pool()
            return self._fallback(str(exc))

    def _get_ohlcv_raw(self, state: dict) -> list | None:
        """Extrait la liste OHLCV depuis state["market_indicators"]["ohlcv_raw"]."""
        indicators = state.get("market_indicators") or {}
        ohlcv_raw = indicators.get("ohlcv_raw")
        if ohlcv_raw is not None and len(ohlcv_raw) >= 20:
            return ohlcv_raw  # [[ts_ms, open, high, low, close, volume], ...]
        logger.warning(f"Kronos: ohlcv_raw absent ou insuffisant dans state ({len(ohlcv_raw or [])} rows)")
        return None

    def _interpret(self, current_price: float, predicted_closes: list) -> dict:
        """
        Convertit le forecast Kronos en score de trading.

        Utilise le close prédit en fin d'horizon (ou la moyenne si multi-sample).
        Le score suit la même table que TimesFM :
          Forte hausse (>2%)    → 75-90
          Hausse modérée (0.5%) → 60-75
          Flat (±0.5%)          → 45-55
          Baisse modérée (-2%)  → 25-40
          Forte baisse (<-2%)   → 10-25
        """
        if not predicted_closes:
            return self._interpret_neutral(current_price)

        closes_arr = np.array(predicted_closes, dtype=float)
        predicted_price = float(closes_arr[-1])  # fin d'horizon

        if current_price <= 0:
            return self._interpret_neutral(current_price)

        pct_change = ((predicted_price - current_price) / current_price) * 100

        # Mapping pct_change → score
        if pct_change >= 2.0:
            score = min(90.0, 75 + pct_change * 2)
        elif pct_change >= 0.5:
            score = 60.0 + (pct_change - 0.5) * 10
        elif pct_change >= -0.5:
            score = 50.0 + pct_change * 10
        elif pct_change >= -2.0:
            score = 40.0 + (pct_change + 0.5) * 10
        else:
            score = max(10.0, 25 + pct_change * 2)

        score = float(np.clip(score, 0, 100))

        # Confidence = régularité de la trajectoire prédite
        # Variance faible des closes prédits → confiance haute
        if len(closes_arr) > 1:
            rel_std = float(np.std(closes_arr) / current_price) if current_price > 0 else 0.1
            confidence = float(np.clip(1.0 - rel_std * 20, 0.05, 1.0))
        else:
            confidence = 0.5

        direction = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")

        summary = (
            f"Kronos ({self._model_name.split('/')[-1]}): {pct_change:+.2f}% sur "
            f"{self._horizon} candles "
            f"(${current_price:,.2f} → ${predicted_price:,.2f}). "
            f"Confiance: {confidence:.0%}."
        )

        return {
            "score": round(score, 1),
            "direction": direction,
            "confidence": round(confidence, 2),
            "pct_change": round(pct_change, 2),
            "predicted_price": predicted_price,
            "summary": summary,
        }

    def _interpret_neutral(self, current_price: float) -> dict:
        return {
            "score": 50.0,
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "pct_change": 0.0,
            "predicted_price": current_price,
            "summary": "Kronos: données insuffisantes pour forecast.",
        }

    def _fallback(self, reason: str) -> dict:
        logger.warning(f"Kronos fallback: {reason}")
        return {
            "agent_name": "kronos",
            "score": 50.0,
            "signal": "NEUTRAL",
            "summary": f"Kronos unavailable ({reason})",
            "confidence": 0.0,
        }
