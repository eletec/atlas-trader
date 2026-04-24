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

INSTALLATION DU SOURCE KRONOS (dans le container) :
  Kronos n'est pas un package pip (pas de setup.py). Il faut copier le source :
  curl -fsSL https://github.com/shiyu-coder/Kronos/archive/refs/heads/master.tar.gz \\
    | tar -xz -C /app
  → crée /app/Kronos-master/ avec le dossier model/ dedans.
  Variable d'env optionnelle : KRONOS_ROOT=/app/Kronos-master

VRAIE API KRONOS (from model import ...):
  tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-2k")
  model     = Kronos.from_pretrained("NeoQuasar/Kronos-mini")
  predictor = KronosPredictor(model, tokenizer, max_context=2048)
  pred_df   = predictor.predict(df, x_timestamp, y_timestamp, pred_len, T, top_p, sample_count)
"""
from __future__ import annotations

import logging
import os
import threading as _threading
from pathlib import Path

import numpy as np

logger = logging.getLogger("zeitgeist.kronos")


# ── Mapping modèle → tokenizer + contexte max ────────────────────────────────
_TOKENIZER_MAP: dict[str, str] = {
    "NeoQuasar/Kronos-mini":  "NeoQuasar/Kronos-Tokenizer-2k",
    "NeoQuasar/Kronos-small": "NeoQuasar/Kronos-Tokenizer-base",
    "NeoQuasar/Kronos-base":  "NeoQuasar/Kronos-Tokenizer-base",
}
_MAX_CONTEXT_MAP: dict[str, int] = {
    "NeoQuasar/Kronos-mini":  2048,
    "NeoQuasar/Kronos-small": 512,
    "NeoQuasar/Kronos-base":  512,
}


def _get_kronos_root() -> str:
    """
    Localise le répertoire source Kronos (avec un sous-dossier model/).
    Cherche dans l'ordre : var d'env KRONOS_ROOT, /app/Kronos-master,
    /app/Kronos, dossier parent du projet (dev local).
    """
    env_path = os.environ.get("KRONOS_ROOT", "")
    candidates = [env_path] if env_path else []
    candidates += [
        "/app/Kronos-master",
        "/app/Kronos",
        str(Path(__file__).resolve().parent.parent.parent / "Kronos-master"),
        str(Path(__file__).resolve().parent.parent.parent / "Kronos"),
    ]
    for p in candidates:
        if p and Path(p, "model").is_dir():
            return p
    raise ImportError(
        "Kronos source introuvable (dossier 'model/' absent). "
        "Télécharger avec :\n"
        "  curl -fsSL https://github.com/shiyu-coder/Kronos/archive/refs/heads/master.tar.gz"
        " | tar -xz -C /app\n"
        "Puis définir KRONOS_ROOT=/app/Kronos-master si nécessaire."
    )


# ── Worker subprocess — au niveau MODULE pour être picklable (ProcessPool) ────

# Cache dans le processus ENFANT (survit entre les cycles)
_CHILD_MODEL: object | None = None
_CHILD_MODEL_NAME: str | None = None


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
    Le modèle + tokenizer sont chargés une seule fois par vie du processus enfant.

    Returns:
        {"predicted_closes": [...], "current_price": float, "current_ts_iso": str}
    """
    global _CHILD_MODEL, _CHILD_MODEL_NAME

    import sys
    import pandas as _pd
    import numpy as _np

    # Ajouter le source Kronos au path (processus enfant : path non hérité)
    kronos_root = _get_kronos_root()
    if kronos_root not in sys.path:
        sys.path.insert(0, kronos_root)

    # Import depuis le dossier model/ du source Kronos
    from model import Kronos, KronosTokenizer, KronosPredictor  # pylint: disable=import-error

    # Construire le DataFrame OHLCV (colonnes sans index timestamp)
    rows = ohlcv_list[-lookback:] if len(ohlcv_list) > lookback else ohlcv_list
    raw_df = _pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    raw_df["ts"] = _pd.to_datetime(raw_df["ts"], unit="ms", utc=True)
    raw_df = raw_df.dropna(subset=["open", "high", "low", "close"])
    raw_df = raw_df.reset_index(drop=True)

    if len(raw_df) < 10:
        raise ValueError(f"Insufficient OHLCV rows after cleaning: {len(raw_df)}")

    # Kronos attend df avec colonnes OHLCV (pas en index) + timestamps séparés
    x_df = raw_df[["open", "high", "low", "close", "volume"]].astype(float)
    x_timestamp = raw_df["ts"]  # pandas Series de Timestamp

    # Générer les timestamps futurs à partir du dernier timestamp + fréquence inférée
    freq_min = _infer_freq_minutes_from_series(raw_df["ts"])
    last_ts = raw_df["ts"].iloc[-1]
    y_timestamp = _pd.Series([
        last_ts + _pd.Timedelta(minutes=freq_min * i)
        for i in range(1, horizon + 1)
    ])

    # Charger le modèle si absent ou changé
    if _CHILD_MODEL is None or _CHILD_MODEL_NAME != model_name:
        tokenizer_name = _TOKENIZER_MAP.get(model_name, "NeoQuasar/Kronos-Tokenizer-2k")
        max_ctx = _MAX_CONTEXT_MAP.get(model_name, 2048)
        tokenizer = KronosTokenizer.from_pretrained(tokenizer_name)
        model_obj = Kronos.from_pretrained(model_name)
        _CHILD_MODEL = KronosPredictor(model_obj, tokenizer, max_context=max_ctx)
        _CHILD_MODEL_NAME = model_name

    # Appel Kronos — retourne un DataFrame OHLCV (horizon lignes)
    pred_df = _CHILD_MODEL.predict(
        df=x_df,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=horizon,
        T=T,
        top_p=top_p,
        sample_count=sample_count,
    )

    predicted_closes = pred_df["close"].values.tolist()
    current_price = float(raw_df["close"].iloc[-1])

    return {
        "predicted_closes": predicted_closes,
        "current_price": current_price,
        "current_ts_iso": str(last_ts),
    }


def _infer_freq_minutes_from_series(ts_series) -> int:
    """Infère la fréquence des candles en minutes depuis une Series de timestamps."""
    import pandas as _pd
    if len(ts_series) < 2:
        return 15  # atlas default
    deltas = _pd.Series(ts_series.values).diff().dropna()
    median_s = deltas.median().total_seconds()
    return max(1, int(median_s / 60))


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
    Agent Kronos — forecast prix via foundation model OHLCV (AAAI 2026).

    Prend les N dernières candles OHLCV 15min, génère un forecast probabiliste,
    et retourne un score de conviction basé sur direction + magnitude du mouvement.
    Tous les paramètres sont configurables depuis le panneau admin.
    """

    def __init__(self):
        self._model_name = "NeoQuasar/Kronos-mini"
        self._horizon = 96          # 96 × 15min = 24h
        self._lookback = 400        # candles contexte (≤ 2048 pour mini)
        self._T = 1.0               # temperature
        self._top_p = 0.9           # nucleus sampling
        self._sample_count = 1      # trajectoires
        self._timeout = 120         # secondes

    def _load_config(self, asset: str | None) -> None:
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
            pass

    def analyze(self, state: dict) -> dict:
        """Run Kronos forecast in a child process — returns standard agent dict."""
        import time
        try:
            from concurrent.futures import BrokenProcessPool
        except ImportError:
            from concurrent.futures.process import BrokenProcessPool

        t0 = time.time()
        asset = state.get("asset", "BTC/USDT")
        self._load_config(asset)

        # Vérification immédiate du source — fail-fast SANS spawner de process
        # Évite l'accumulation de threads zombies sur multi-actifs si source absent
        try:
            _get_kronos_root()
        except ImportError as _no_src:
            logger.warning(f"Kronos [{asset}]: source absent — {_no_src}")
            return self._fallback("source Kronos absent (voir INSTALLATION dans kronos_agent.py)")

        try:
            ohlcv_raw = self._get_ohlcv_raw(state)
            if ohlcv_raw is None or len(ohlcv_raw) < 20:
                return self._fallback("insufficient OHLCV data")

            logger.info(
                f"Kronos [{asset}]: {len(ohlcv_raw)} candles, "
                f"model={self._model_name}, horizon={self._horizon}, "
                f"lookback={self._lookback}, T={self._T}, top_p={self._top_p}"
            )

            # Timeout court : si source absent, le spawn échoue en <30s
            # → évite d'accumuler des zombie threads sur multi-actifs
            acquired = _KRONOS_SEMAPHORE.acquire(timeout=90)
            if not acquired:
                return self._fallback("semaphore timeout (autre actif Kronos en cours)")

            try:
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

            result = self._interpret(
                worker_result["current_price"],
                worker_result["predicted_closes"],
            )
            elapsed_ms = int((time.time() - t0) * 1000)

            logger.info(
                f"Kronos [{asset}]: direction={result['direction']} "
                f"change={result['pct_change']:+.2f}% score={result['score']:.0f} "
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
        indicators = state.get("market_indicators") or {}
        ohlcv_raw = indicators.get("ohlcv_raw")
        if ohlcv_raw is not None and len(ohlcv_raw) >= 20:
            return ohlcv_raw
        logger.warning(f"Kronos: ohlcv_raw absent ou insuffisant ({len(ohlcv_raw or [])} rows)")
        return None

    def _interpret(self, current_price: float, predicted_closes: list) -> dict:
        """
        Convertit le forecast Kronos en score 0-100 (identique TimesFM).
          > +2%     → 75–90  (forte hausse)
          0.5–2%   → 60–75
          ±0.5%    → 45–55  (flat)
          -2% à -0.5% → 25–40
          < -2%    → 10–25  (forte baisse)
        """
        if not predicted_closes or current_price <= 0:
            return self._interpret_neutral(current_price)

        closes_arr = np.array(predicted_closes, dtype=float)
        predicted_price = float(closes_arr[-1])
        pct_change = ((predicted_price - current_price) / current_price) * 100

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

        if len(closes_arr) > 1:
            rel_std = float(np.std(closes_arr) / current_price)
            confidence = float(np.clip(1.0 - rel_std * 20, 0.05, 1.0))
        else:
            confidence = 0.5

        direction = "BULLISH" if score > 60 else ("BEARISH" if score < 40 else "NEUTRAL")
        model_short = self._model_name.split("/")[-1]
        summary = (
            f"Kronos ({model_short}): {pct_change:+.2f}% sur {self._horizon} candles "
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


