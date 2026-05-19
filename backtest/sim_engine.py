"""
backtest/sim_engine.py — Moteur de simulation V2.

Utilise le pipeline quantitatif V2 réel (quant/pipeline.run_pipeline) :
  features.py → regime.py (HMM 3 états) → signal_model.py (LogReg+Platt)
  → strategy.py (decide/decide_range) → backtest.py (SL/TP ATR-based)

Plus de scoring 0-100 ni de règles heuristiques V1.
Le moteur rejoue exactement la même logique que LiveRunner sur OHLCV historique.
Compatibilité backtest/report.py maintenue via SimTrade.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# Ajouter le parent du dossier backtest au path pour importer decision_engine
_APP_ROOT = str(Path(__file__).resolve().parent.parent)
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

logger = logging.getLogger("backtest.sim_engine")


# ── Dataclass résultat d'une simulation ──────────────────────────────────────

@dataclass
class SimTrade:
    cycle_id: str
    timestamp: datetime
    asset: str
    action: str           # LONG / SHORT / FLAT
    score: float
    entry_price: float
    sl_price: float
    tp_price: float
    position_size_usd: float
    atr: float
    regime: str
    result_24h: Optional[float] = None   # pnl_abs du Trade V2


# ── Moteur principal V2 ──────────────────────────────────────────────────────

class SimEngine:
    """
    Moteur de simulation V2 — wrapper autour de quant/pipeline.run_pipeline().
    100% standalone — ne touche pas la DB live ni les agents live.

    Paramètres supportés dans config :
        p_up_threshold : seuil P(up) LONG  (défaut : valeurs quant/config)
        p_dn_threshold : seuil P(up) SHORT (défaut : valeurs quant/config)
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def run_asset(
        self,
        symbol: str,
        ohlcv_df: pd.DataFrame,
        fng_df: pd.DataFrame | None = None,      # ignoré en V2
        funding_df: pd.DataFrame | None = None,  # ignoré en V2
        train_fraction: float = 0.70,
        cycle_step_candles: int = 1,             # compat signature runner
        min_context_candles: int = 200,          # compat signature runner
        show_progress: bool = True,
    ) -> list["SimTrade"]:
        """
        Rejoue le pipeline V2 sur l'historique OHLCV d'un actif.
        Fit sur train_fraction, évaluation OOS sur le reste.
        """
        from quant.pipeline import PipelineConfig, run_pipeline

        if ohlcv_df.empty or len(ohlcv_df) < 500:
            logger.warning(f"{symbol}: données insuffisantes ({len(ohlcv_df)} barres)")
            return []

        # S'assurer que l'index est un DatetimeIndex
        ohlcv = ohlcv_df.copy()
        if "timestamp" in ohlcv.columns and not isinstance(ohlcv.index, pd.DatetimeIndex):
            ohlcv = ohlcv.set_index(pd.DatetimeIndex(ohlcv["timestamp"]))
        elif not isinstance(ohlcv.index, pd.DatetimeIndex):
            logger.error(f"{symbol}: index non-datetime — backtest impossible.")
            return []

        split = int(len(ohlcv) * train_fraction)
        train_idx = ohlcv.index[:split]
        test_idx = ohlcv.index[split:]

        if len(train_idx) < 200 or len(test_idx) < 50:
            logger.warning(
                f"{symbol}: split trop court "
                f"(train={len(train_idx)}, test={len(test_idx)})"
            )
            return []

        cfg = PipelineConfig()
        if "p_up_threshold" in self.config:
            cfg.p_up_threshold = float(self.config["p_up_threshold"])
        if "p_dn_threshold" in self.config:
            cfg.p_dn_threshold = float(self.config["p_dn_threshold"])

        # Override par actif depuis settings.yaml → quant.asset_thresholds
        try:
            from utils.config import load_settings
            _asset_thr = load_settings().get("quant", {}).get("asset_thresholds", {})
            if symbol in _asset_thr:
                _thr = _asset_thr[symbol]
                if "p_up_threshold" in _thr:
                    cfg.p_up_threshold = float(_thr["p_up_threshold"])
                if "p_dn_threshold" in _thr:
                    cfg.p_dn_threshold = float(_thr["p_dn_threshold"])
        except Exception:
            pass

        if show_progress:
            logger.info(
                f"{symbol}: pipeline V2 | train={len(train_idx)}b test={len(test_idx)}b "
                f"P_up>{cfg.p_up_threshold:.2f} P_dn<{cfg.p_dn_threshold:.2f}"
            )

        try:
            artifacts = run_pipeline(ohlcv, train_idx, test_idx, cfg)
        except Exception as exc:
            logger.error(f"{symbol}: run_pipeline échec — {exc}", exc_info=True)
            return []

        trades = self._to_sim_trades(symbol, ohlcv, artifacts)
        logger.info(f"{symbol}: {len(trades)} trades V2 | {artifacts.backtest.to_summary()}")
        return trades

    def _to_sim_trades(
        self,
        symbol: str,
        ohlcv: pd.DataFrame,
        artifacts,
    ) -> list["SimTrade"]:
        """Convertit PipelineArtifacts → liste SimTrade (compatible report.py)."""
        regime_series = artifacts.regime
        proba_up = artifacts.proba_up
        feats = artifacts.features
        sim_trades: list[SimTrade] = []

        for i, t in enumerate(artifacts.backtest.trades):
            ts = t.entry_ts
            rv = regime_series.get(ts, float("nan"))
            if rv == 1.0:
                regime_str = "TREND"
            elif rv == 0.0:
                regime_str = "PANIC"
            elif rv == 0.5:
                regime_str = "RANGE"
            else:
                regime_str = "UNKNOWN"

            p_up = float(proba_up.get(ts, 0.5))
            atr_val = float(feats["atr_14"].get(ts, 0.0)) if "atr_14" in feats.columns else 0.0

            # SL/TP estimés pour l'affichage rapport
            atr_sl_est = atr_val * 2.5 if atr_val > 0 else t.entry_price * 0.025
            atr_tp_est = atr_val * 3.5 if atr_val > 0 else t.entry_price * 0.035
            if t.side == "long":
                sl_price = t.entry_price - atr_sl_est
                tp_price = t.entry_price + atr_tp_est
            else:
                sl_price = t.entry_price + atr_sl_est
                tp_price = t.entry_price - atr_tp_est

            sim = SimTrade(
                cycle_id=f"v2_{i}_{symbol.replace('/', '')}",
                timestamp=(
                    ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                ),
                asset=symbol,
                action="LONG" if t.side == "long" else "SHORT",
                score=round(p_up * 100, 1),
                entry_price=t.entry_price,
                sl_price=round(sl_price, 4),
                tp_price=round(tp_price, 4),
                position_size_usd=round(t.size_units * t.entry_price, 2),
                atr=round(atr_val, 6),
                regime=regime_str,
                result_24h=round(t.pnl_abs, 4),
            )
            sim_trades.append(sim)

        return sim_trades

