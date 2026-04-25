"""
backtest/sim_engine.py — Moteur de simulation standalone.

Reproduit le pipeline Atlas (agents quantitatifs uniquement, LLM neutralisé)
sur des données OHLCV historiques.

Agents simulés :
  ✅ market_data   : RSI, MACD, ATR, BB, MA50, régime HMM (recalculé sur historique)
  ✅ fear_greed    : depuis historique alternative.me
  ✅ contrarian    : score fixe 50 (pas d'historique L/S ratio Binance)
  ✅ fundamental   : rule-based uniquement (RSI + MACD + MA50)
  ✅ kronos        : DÉSACTIVÉ par défaut (trop lent en backtest, opt-in)
  🔒 synthesis     : NEUTRALISÉ → score = 50 (pas de LLM)
  🔒 x_sentiment   : NEUTRALISÉ → score = 50 (pas d'archive X)
  🔒 broad_crawler : NEUTRALISÉ → score = 50 (pas d'archive web)

Le ScoreCalculator original est réutilisé directement (poids depuis settings.yaml).
"""
from __future__ import annotations

import logging
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Ajouter le parent du dossier backtest au path pour importer decision_engine
_APP_ROOT = str(Path(__file__).resolve().parent.parent)
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

logger = logging.getLogger("backtest.sim_engine")


# ── Indicateurs techniques (recalculés sur OHLCV historique) ─────────────────

def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _ema(series: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1)
    ema = np.empty_like(series)
    ema[0] = series[0]
    for i in range(1, len(series)):
        ema[i] = alpha * series[i] + (1 - alpha) * ema[i - 1]
    return ema


def _macd(closes: np.ndarray) -> tuple[float, float]:
    if len(closes) < 26:
        return 0.0, 0.0
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    signal_line = _ema(macd_line, 9)
    return round(float(macd_line[-1]), 6), round(float(signal_line[-1]), 6)


def _bollinger(closes: np.ndarray, period: int = 20, std_mult: float = 2.0) -> tuple[float, float]:
    if len(closes) < period:
        return 0.0, 0.0
    window = closes[-period:]
    mid = np.mean(window)
    std = np.std(window)
    return round(float(mid + std_mult * std), 4), round(float(mid - std_mult * std), 4)


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return round(float(np.mean(trs[-period:])), 6)


def _ma(closes: np.ndarray, period: int = 50) -> float:
    if len(closes) < period:
        return float(closes[-1]) if len(closes) > 0 else 0.0
    return round(float(np.mean(closes[-period:])), 4)


def _hmm_regime(closes: np.ndarray, adx_period: int = 14) -> str:
    """
    Approximation légère du régime HMM via volatilité et ADX.
    Pas de dépendance à hmmlearn (évite la dépendance lourde en backtest).
    """
    if len(closes) < 50:
        return "UNKNOWN"
    returns = np.diff(np.log(closes[-50:]))
    vol = np.std(returns) * np.sqrt(252 * 96)  # annualisée (96 candles 15min/jour)

    # Tendance simple via pente de régression linéaire sur 20 candles
    x = np.arange(20)
    y = closes[-20:]
    slope = float(np.polyfit(x, y, 1)[0])
    slope_pct = slope / float(closes[-20]) * 100

    if vol > 0.80:
        return "HIGH_VOLATILITY"
    elif slope_pct > 0.15:
        return "TRENDING_UP"
    elif slope_pct < -0.15:
        return "TRENDING_DOWN"
    else:
        return "SIDEWAYS"


# ── Scores agents depuis indicateurs ────────────────────────────────────────

def _market_score(indicators: dict) -> float:
    """Reproduit la logique de MarketDataAgent._compute_score() (rule-based)."""
    rsi = indicators.get("rsi_14", 50)
    macd = indicators.get("macd", 0)
    macd_sig = indicators.get("macd_signal", 0)
    price = indicators.get("price", 0)
    bb_upper = indicators.get("bb_upper", 0)
    bb_lower = indicators.get("bb_lower", 0)
    atr = indicators.get("atr_14", 0)
    above_ma50 = indicators.get("above_ma50", True)

    score = 50.0

    # RSI contribution
    if rsi < 30:
        score += 15
    elif rsi < 40:
        score += 8
    elif rsi > 70:
        score -= 15
    elif rsi > 60:
        score -= 8

    # MACD
    if macd > macd_sig:
        score += 10
    else:
        score -= 10

    # Bollinger
    if price and bb_lower and bb_upper and bb_upper > bb_lower:
        bb_pos = (price - bb_lower) / (bb_upper - bb_lower)
        if bb_pos < 0.2:
            score += 10
        elif bb_pos > 0.8:
            score -= 10

    # MA50 trend
    if above_ma50:
        score += 5
    else:
        score -= 5

    return max(0.0, min(100.0, round(score, 1)))


def _fear_greed_score(fng_value: int) -> float:
    """Reproduit FearGreedAgent (signal contrarien)."""
    if fng_value <= 25:
        return 75 + (25 - fng_value)
    elif fng_value <= 45:
        return 55 + (45 - fng_value) / 2
    elif fng_value <= 55:
        return 50.0
    elif fng_value <= 75:
        return 45 - (fng_value - 55) / 2
    else:
        return max(20, 40 - (fng_value - 75))


def _fundamental_rule_score(indicators: dict) -> float:
    """Reproduit FundamentalAgent._rule_based() (sans LLM)."""
    rsi = indicators.get("rsi_14", 50)
    macd = indicators.get("macd", 0)
    macd_sig = indicators.get("macd_signal", 0)
    above_ma50 = indicators.get("above_ma50", True)
    funding = indicators.get("funding_rate", 0)

    score = 50.0

    if rsi < 35:
        score += 12
    elif rsi > 65:
        score -= 12

    if macd > macd_sig:
        score += 8
    else:
        score -= 8

    if above_ma50:
        score += 6
    else:
        score -= 6

    if funding > 0.0003:
        score -= 10
    elif funding < -0.0001:
        score += 5

    return max(0.0, min(100.0, round(score, 1)))


# ── Dataclass résultat d'une simulation ──────────────────────────────────────

@dataclass
class SimTrade:
    cycle_id: str
    timestamp: datetime
    asset: str
    action: str           # BUY / SELL / HOLD
    score: float
    entry_price: float
    sl_price: float
    tp_price: float
    position_size_usd: float
    atr: float
    regime: str
    indicators: dict = field(default_factory=dict)
    agent_scores: dict = field(default_factory=dict)
    score_breakdown: dict = field(default_factory=dict)
    result_24h: Optional[float] = None   # rempli après simulation P&L


# ── Moteur principal ─────────────────────────────────────────────────────────

class SimEngine:
    """
    Simule les décisions Atlas sur données OHLCV historiques.
    100% standalone — ne touche pas à la DB live ni aux agents live.
    """

    def __init__(self, config: dict | None = None):
        """
        config : dict de surcharge des paramètres (pour l'optimisation).
        Si None, charge settings.yaml de l'app.
        """
        self.config = config or self._load_default_config()
        self._risk = self.config.get("risk", {})
        self._scoring_weights = self.config.get("scoring", {}).get("weights", {})

    def _load_default_config(self) -> dict:
        try:
            from utils.config import load_settings
            return load_settings()
        except Exception:
            # Fallback si lancé hors du contexte app
            return {
                "risk": {
                    "buy_threshold": 62, "exit_threshold": 45,
                    "position_size_pct": 5.0, "kelly_max_fraction": 0.25,
                    "atr_multiplier_sl": 2.0, "atr_multiplier_tp": 3.0,
                    "paper_capital_usd": 10000,
                },
                "scoring": {
                    "weights": {
                        "mirofish": 0.12, "market": 0.50,
                        "agents": 0.20, "contrarian": 0.18,
                    }
                },
            }

    def run_asset(
        self,
        symbol: str,
        ohlcv_df: pd.DataFrame,
        fng_df: pd.DataFrame,
        funding_df: pd.DataFrame,
        cycle_step_candles: int = 24,  # 1 cycle = 24 candles × 15min = 6h
        min_context_candles: int = 200,
        show_progress: bool = True,
    ) -> list[SimTrade]:
        """
        Rejoue les décisions sur l'historique OHLCV d'un actif.

        cycle_step_candles : espacement entre deux cycles (24 = 6h, 4 = 1h)
        min_context_candles : candles nécessaires avant le premier cycle
        """
        if ohlcv_df.empty or len(ohlcv_df) < min_context_candles + cycle_step_candles:
            logger.warning(f"{symbol}: données insuffisantes ({len(ohlcv_df)} candles)")
            return []

        trades: list[SimTrade] = []
        risk = self._risk
        buy_thr = float(risk.get("buy_threshold", 62))
        exit_thr = float(risk.get("exit_threshold", 45))
        pos_pct = float(risk.get("position_size_pct", 5.0)) / 100
        capital = float(risk.get("paper_capital_usd", 10_000))
        atr_sl = float(risk.get("atr_multiplier_sl", 2.0))
        atr_tp = float(risk.get("atr_multiplier_tp", 3.0))

        closes = ohlcv_df["close"].values.astype(float)
        highs = ohlcv_df["high"].values.astype(float)
        lows = ohlcv_df["low"].values.astype(float)
        timestamps = ohlcv_df["timestamp"].values

        total_cycles = (len(ohlcv_df) - min_context_candles) // cycle_step_candles
        processed = 0

        for i in range(min_context_candles, len(ohlcv_df), cycle_step_candles):
            ctx_closes = closes[:i]
            ctx_highs = highs[:i]
            ctx_lows = lows[:i]
            current_price = float(closes[i - 1])
            current_ts = pd.Timestamp(timestamps[i - 1]).to_pydatetime()
            if current_ts.tzinfo is None:
                current_ts = current_ts.replace(tzinfo=timezone.utc)

            # ── Indicateurs techniques ─────────────────────────────────────
            rsi_val = _rsi(ctx_closes, 14)
            macd_val, macd_sig = _macd(ctx_closes)
            bb_upper, bb_lower = _bollinger(ctx_closes)
            atr_val = _atr(ctx_highs, ctx_lows, ctx_closes, 14)

            # MA50 journalière (approximée sur 50 × 96 candles 15min = 4800 candles)
            ma50_ctx = max(1, min(len(ctx_closes), 4800))
            daily_closes = ctx_closes[-ma50_ctx::96]  # 1 point par jour
            ma50 = _ma(daily_closes, 50)
            above_ma50 = current_price > ma50 if ma50 > 0 else True

            # Régime de marché
            regime = _hmm_regime(ctx_closes)

            indicators = {
                "price": current_price,
                "rsi_14": rsi_val,
                "macd": macd_val,
                "macd_signal": macd_sig,
                "bb_upper": bb_upper,
                "bb_lower": bb_lower,
                "atr_14": atr_val,
                "ma_50": ma50,
                "above_ma50": above_ma50,
                "funding_rate": 0.0,  # mis à jour ci-dessous
            }

            # Funding rate (seulement crypto USDT)
            if not funding_df.empty:
                indicators["funding_rate"] = 0.0
                try:
                    indicators["funding_rate"] = float(
                        funding_df.loc[funding_df["timestamp"] <= current_ts, "funding_rate"].iloc[-1]
                    )
                except Exception:
                    pass

            # ── Scores agents ────────────────────────────────────────────────
            fng_val = 50
            if not fng_df.empty:
                try:
                    fng_val = int(fng_df.loc[fng_df["date"] <= current_ts.date(), "fng_value"].iloc[-1])
                except Exception:
                    pass

            agent_scores = {
                "market_data":  _market_score(indicators),
                "fear_greed":   _fear_greed_score(fng_val),
                "fundamental":  _fundamental_rule_score(indicators),
                "contrarian":   50.0,   # pas d'historique L/S ratio
                "synthesis":    50.0,   # LLM neutralisé
            }

            # ── Score global ─────────────────────────────────────────────────
            w = self._scoring_weights
            # MiroFish absent → poids redistribué sur market
            w_market = w.get("market", 0.50) + w.get("mirofish", 0.12)
            w_agents = w.get("agents", 0.20)
            w_contra = w.get("contrarian", 0.18)
            total_w = w_market + w_agents + w_contra
            w_market /= total_w
            w_agents /= total_w
            w_contra /= total_w

            agents_mean = (
                agent_scores["market_data"] * 0.5
                + agent_scores["fear_greed"] * 0.2
                + agent_scores["fundamental"] * 0.3
            )

            global_score = round(
                agents_mean * w_agents
                + agent_scores["market_data"] * w_market
                + agent_scores["contrarian"] * w_contra,
                2,
            )
            global_score = max(0.0, min(100.0, global_score))

            # ── Filtre régime ─────────────────────────────────────────────
            if regime == "TRENDING_DOWN" and global_score >= buy_thr:
                action = "HOLD"  # BUY bloqué en tendance baissière
            elif global_score >= buy_thr:
                action = "BUY"
            elif global_score < exit_thr:
                action = "SELL"
            else:
                action = "HOLD"

            # ── Sizing + SL/TP ────────────────────────────────────────────
            pos_size = capital * pos_pct
            sl = current_price - atr_sl * atr_val if action == "BUY" else current_price + atr_sl * atr_val
            tp = current_price + atr_tp * atr_val if action == "BUY" else current_price - atr_tp * atr_val

            trade = SimTrade(
                cycle_id=f"{symbol}_{i}",
                timestamp=current_ts,
                asset=symbol,
                action=action,
                score=global_score,
                entry_price=current_price,
                sl_price=round(sl, 4),
                tp_price=round(tp, 4),
                position_size_usd=round(pos_size, 2),
                atr=round(atr_val, 6),
                regime=regime,
                indicators=indicators,
                agent_scores=agent_scores,
                score_breakdown={
                    "market": agent_scores["market_data"],
                    "fear_greed": agent_scores["fear_greed"],
                    "fundamental": agent_scores["fundamental"],
                    "regime": regime,
                    "above_ma50": above_ma50,
                },
            )
            trades.append(trade)

            processed += 1
            if show_progress and processed % 100 == 0:
                pct = processed / max(total_cycles, 1) * 100
                logger.info(f"{symbol}: {processed}/{total_cycles} cycles ({pct:.0f}%)")

        # ── Calcul P&L 24h après ouverture (sur les candles suivantes) ───────
        trades = self._compute_pnl(trades, closes, ohlcv_df, cycle_step_candles)

        logger.info(f"{symbol}: {len(trades)} cycles, {sum(1 for t in trades if t.action == 'BUY')} BUY, {sum(1 for t in trades if t.action == 'SELL')} SELL")
        return trades

    def _compute_pnl(
        self,
        trades: list[SimTrade],
        closes: np.ndarray,
        ohlcv_df: pd.DataFrame,
        cycle_step: int,
    ) -> list[SimTrade]:
        """
        Calcule le P&L de chaque trade BUY/SELL :
        - exit = clôture de la candle 24h après l'entrée (96 candles × 15min)
        - si SL ou TP touché avant → exit anticipé
        """
        closes_list = closes.tolist()
        highs_list = ohlcv_df["high"].values.tolist()
        lows_list = ohlcv_df["low"].values.tolist()

        for t in trades:
            if t.action == "HOLD":
                t.result_24h = 0.0
                continue

            # Index de l'entrée dans le tableau closes
            try:
                entry_idx = ohlcv_df.index[
                    ohlcv_df["timestamp"] == pd.Timestamp(t.timestamp)
                ].tolist()[0]
            except (IndexError, KeyError):
                t.result_24h = 0.0
                continue

            exit_idx = min(entry_idx + 96, len(closes_list) - 1)  # +24h
            exit_price = closes_list[exit_idx]

            # Vérifier SL / TP sur les candles intermédiaires
            for j in range(entry_idx + 1, exit_idx + 1):
                h = highs_list[j]
                l = lows_list[j]
                if t.action == "BUY":
                    if l <= t.sl_price:
                        exit_price = t.sl_price
                        break
                    if h >= t.tp_price:
                        exit_price = t.tp_price
                        break
                else:  # SELL
                    if h >= t.sl_price:
                        exit_price = t.sl_price
                        break
                    if l <= t.tp_price:
                        exit_price = t.tp_price
                        break

            qty = t.position_size_usd / t.entry_price if t.entry_price > 0 else 0
            if t.action == "BUY":
                pnl = (exit_price - t.entry_price) * qty
            else:
                pnl = (t.entry_price - exit_price) * qty

            t.result_24h = round(pnl, 4)

        return trades
