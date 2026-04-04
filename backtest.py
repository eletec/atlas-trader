"""
backtest.py — Backtest vectorisé sur données OHLCV historiques réelles.

Usage :
    python backtest.py                          # BTC/USDT, 30 derniers jours
    python backtest.py --days 60 --tf 1h        # 60 jours, timeframe 1h
    python backtest.py --days 30 --no-ma50      # sans filtre MA50
    python backtest.py --days 30 --mode aggressive
    python backtest.py --with-regime            # overlay régime de marché + métriques par régime
    python backtest.py --with-regime --n-hmm-states 3   # test HMM 3 états
    python backtest.py --compare-states         # compare HMM 2 vs 3 états côte à côte

Données : téléchargées depuis Binance public (sans clé API, sans testnet).
Indicateurs : RSI-14, MACD, ATR-14, MA50 journalière — mêmes algos que le live.
News/LLM   : neutralisés à 50 (pas de données historiques disponibles).
             Le backtest mesure donc uniquement la qualité du signal technique.
"""
from __future__ import annotations

import argparse
import sys
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from datetime import timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ===========================================================
# TÉLÉCHARGEMENT DES DONNÉES HISTORIQUES
# ===========================================================

def fetch_ohlcv_history(symbol: str, timeframe: str, days: int) -> list[list]:
    """
    Télécharge les bougies OHLCV depuis Binance (mode public, pas de testnet).
    Retourne [[timestamp_ms, open, high, low, close, volume], ...]
    """
    try:
        import ccxt
    except ImportError:
        print("ERREUR: ccxt non installé. Installez-le avec : pip install ccxt")
        sys.exit(1)

    exchange = ccxt.binance({"enableRateLimit": True})
    # Pas de sandbox — données réelles publiques
    exchange.options.pop("sandboxMode", None)

    tf_ms = {
        "1m": 60_000, "5m": 300_000, "15m": 900_000,
        "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
    }
    candle_ms = tf_ms.get(timeframe, 900_000)
    total_candles = int(days * 24 * 3600 * 1000 / candle_ms)
    since_ms = int((_utcnow() - timedelta(days=days)).timestamp() * 1000)

    print(f"  Telechargement {total_candles} bougies {timeframe} ({days} jours)...", end="", flush=True)

    all_candles: list[list] = []
    since = since_ms

    while len(all_candles) < total_candles:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        all_candles.extend(batch)
        since = batch[-1][0] + candle_ms
        if since >= int(_utcnow().timestamp() * 1000):
            break

    print(f" {len(all_candles)} bougies recues.")
    return all_candles


def fetch_daily_closes(symbol: str, days: int) -> np.ndarray:
    """Télécharge les closes journaliers pour la MA50 (needs 50 extra days)."""
    try:
        import ccxt
        exchange = ccxt.binance({"enableRateLimit": True})
        since_ms = int((_utcnow() - timedelta(days=days + 60)).timestamp() * 1000)
        candles = exchange.fetch_ohlcv(symbol, "1d", since=since_ms, limit=days + 60)
        return np.array([c[4] for c in candles])
    except Exception:
        return np.array([])


# ===========================================================
# CALCULS D'INDICATEURS (identiques à MarketDataAgent)
# ===========================================================

def _rsi(closes: np.ndarray, period: int = 14) -> float:
    delta = np.diff(closes)
    gains = np.where(delta > 0, delta, 0)
    losses = np.where(delta < 0, -delta, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def _ema(data: np.ndarray, n: int) -> np.ndarray:
    k = 2 / (n + 1)
    result = np.empty(len(data))
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = data[i] * k + result[i - 1] * (1 - k)
    return result


def _macd(closes: np.ndarray) -> tuple[float, float]:
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    signal = _ema(macd_line, 9)
    return float(macd_line[-1]), float(signal[-1])


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))
    )
    return float(np.mean(tr[-period:]))


def compute_indicators(ohlcv_window: list[list], daily_closes: np.ndarray) -> dict:
    """
    Calcule les indicateurs techniques sur une fenêtre OHLCV (100 bougies).
    Identique à MarketDataAgent.get_indicators mais sur données historiques.
    """
    closes = np.array([c[4] for c in ohlcv_window])
    highs = np.array([c[2] for c in ohlcv_window])
    lows = np.array([c[3] for c in ohlcv_window])
    price = closes[-1]

    ma_50 = float(np.mean(daily_closes[-50:])) if len(daily_closes) >= 50 else 0.0

    macd_val, macd_sig = _macd(closes)
    return {
        "price": round(price, 2),
        "rsi_14": round(_rsi(closes, 14), 2),
        "macd": round(macd_val, 4),
        "macd_signal": round(macd_sig, 4),
        "atr_14": round(_atr(highs, lows, closes, 14), 2),
        "funding_rate": 0.0,   # non dispo en historique
        "ma_50": round(ma_50, 2),
        "above_ma50": bool(ma_50 > 0 and price > ma_50),
    }


# ===========================================================
# DÉRIVATION DU SCORE MARCHÉ (identique à workflow._derive_market_score)
# ===========================================================

def derive_market_score(indicators: dict) -> float:
    score = 50.0
    rsi = indicators.get("rsi_14", 50)
    macd = indicators.get("macd", 0)
    macd_signal = indicators.get("macd_signal", 0)
    funding = indicators.get("funding_rate", 0)

    if rsi < 30:
        score += 20
    elif rsi > 70:
        score -= 20
    else:
        score += (50 - rsi) * 0.4

    if macd > macd_signal:
        score += 15
    else:
        score -= 15

    if funding < -0.01:
        score += 10
    elif funding > 0.03:
        score -= 10

    return max(0.0, min(100.0, score))


# ===========================================================
# MOTEUR DE DÉCISION SIMPLIFIÉ (même logique que DecisionEngine)
# ===========================================================

@dataclass
class BacktestConfig:
    buy_threshold: float = 68.0
    sell_threshold: float = 35.0
    ma50_filter_mode: str = "gradual"        # off | block | gradual
    ma50_strong_threshold: float = 72.0
    ma50_size_factor: float = 0.5
    capital: float = 10_000.0
    position_size_pct: float = 5.0          # % du capital par trade
    kelly_max: float = 0.25
    atr_sl_mult: float = 2.0
    atr_tp_mult: float = 3.0
    # Poids du score global (news/mirofish neutralisés)
    # scoring: weights from settings — market seul car pas d'historique news
    mirofish_weight: float = 0.15
    market_weight: float = 0.45
    agents_weight: float = 0.25
    contrarian_weight: float = 0.15


def compute_global_score(market_score: float, cfg: BacktestConfig) -> float:
    """
    Score global avec mirofish=50 (neutre), agents=50 (neutre), contrarian=50.
    Seul le market_score varie — c'est ce que le backtest mesure.
    """
    total_weight = cfg.mirofish_weight + cfg.market_weight + cfg.agents_weight + cfg.contrarian_weight
    score = (
        50.0 * cfg.mirofish_weight
        + market_score * cfg.market_weight
        + 50.0 * cfg.agents_weight
        + 50.0 * cfg.contrarian_weight
    ) / total_weight
    return round(max(0.0, min(100.0, score)), 2)


def decide(score: float, indicators: dict, cfg: BacktestConfig) -> tuple[str, float]:
    """
    Retourne (action, size_usd).
    Logique identique à DecisionEngine.decide() + RiskEngine.
    """
    price = indicators["price"]
    atr = indicators["atr_14"]
    above_ma50 = indicators.get("above_ma50", True)
    ma_50 = indicators.get("ma_50", 0.0)

    if score >= cfg.buy_threshold:
        action = "BUY"
    elif score <= cfg.sell_threshold:
        action = "SELL"
    else:
        return "HOLD", 0.0

    # Filtre MA50
    if action == "BUY" and not above_ma50 and ma_50 > 0:
        if cfg.ma50_filter_mode == "block":
            return "HOLD", 0.0
        elif cfg.ma50_filter_mode == "gradual":
            if score < cfg.ma50_strong_threshold:
                return "HOLD", 0.0

    # Kelly sizing
    win_rate, rr_ratio = 0.55, 1.5
    kelly = (win_rate * rr_ratio - (1 - win_rate)) / rr_ratio
    kelly = max(0.0, min(kelly, cfg.kelly_max))
    max_size = cfg.capital * (cfg.position_size_pct / 100)
    base_size = min(cfg.capital * kelly, max_size)

    conviction = abs(score - 50.0) / 50.0
    conviction_mult = max(0.3, min(1.0, 0.3 + 0.7 * conviction))

    # MA50 size penalty
    if action == "BUY" and not above_ma50 and cfg.ma50_filter_mode == "gradual":
        conviction_mult *= cfg.ma50_size_factor

    size = round(base_size * conviction_mult, 2)
    return action, size


# ===========================================================
# SIMULATION DE PORTEFEUILLE
# ===========================================================

@dataclass
class Position:
    action: str          # BUY | SELL
    entry_price: float
    size_usd: float
    sl_price: float
    tp_price: float
    entry_ts: int        # candle timestamp ms
    qty: float = 0.0     # quantité en BTC
    regime: str = "UNKNOWN"  # régime au moment de l'entrée

    def __post_init__(self):
        if self.entry_price > 0:
            self.qty = self.size_usd / self.entry_price


@dataclass
class BacktestResult:
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    timestamps: list[int] = field(default_factory=list)
    regimes: list[str] = field(default_factory=list)   # régime par bougie


# ===========================================================
# DÉTECTION DE RÉGIME (optionnelle — nécessite hmmlearn)
# ===========================================================

def compute_regime_for_window(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    n_hmm_states: int = 2,
) -> str:
    """Classifie le régime courant via MarketRegimeAgent (déterministe sans HMM)."""
    try:
        from agents.market_regime_agent import MarketRegimeAgent
        agent = MarketRegimeAgent.__new__(MarketRegimeAgent)
        agent._n_hmm_states = n_hmm_states
        agent._vol_window   = 30
        agent._trend_window = 50
        agent._adx_period   = 18
        features = agent._compute_features(closes, highs, lows, volumes)
        return agent._classify_regime(features)
    except Exception:
        return "UNKNOWN"


def run_backtest(
    ohlcv: list[list],
    daily_closes_full: np.ndarray,
    cfg: BacktestConfig,
    capital_start: float,
    daily_ts_from_full: list[int],
    with_regime: bool = False,
    n_hmm_states: int = 2,
) -> BacktestResult:
    """
    Boucle principale du backtest.
    - 1 décision par bougie (après le préchauffage de 100 bougies)
    - Max 1 position ouverte à la fois (simplifié)
    - SL/TP vérifié sur le high/low de chaque bougie suivante
    """
    capital = capital_start
    result = BacktestResult()
    position: Optional[Position] = None
    warmup = 100  # bougies nécessaires pour les indicateurs
    closes_arr  = np.array([c[4] for c in ohlcv])
    highs_arr   = np.array([c[2] for c in ohlcv])
    lows_arr    = np.array([c[3] for c in ohlcv])
    volumes_arr = np.array([c[5] for c in ohlcv])

    for i in range(warmup, len(ohlcv)):
        candle = ohlcv[i]
        ts_ms = candle[0]
        high = candle[2]
        low = candle[3]
        close = candle[4]

        # --- Vérification SL/TP sur la bougie courante (si position ouverte) ---
        if position is not None:
            hit_sl = hit_tp = False
            exit_price = close

            if position.action == "BUY":
                if low <= position.sl_price:
                    hit_sl, exit_price = True, position.sl_price
                elif high >= position.tp_price:
                    hit_tp, exit_price = True, position.tp_price
            else:  # SELL
                if high >= position.sl_price:
                    hit_sl, exit_price = True, position.sl_price
                elif low <= position.tp_price:
                    hit_tp, exit_price = True, position.tp_price

            if hit_sl or hit_tp:
                if position.action == "BUY":
                    pnl = (exit_price - position.entry_price) * position.qty
                else:
                    pnl = (position.entry_price - exit_price) * position.qty

                capital += pnl
                reason = "TP" if hit_tp else "SL"
                result.trades.append({
                    "entry_ts": position.entry_ts,
                    "exit_ts": ts_ms,
                    "action": position.action,
                    "entry": position.entry_price,
                    "exit": exit_price,
                    "size_usd": position.size_usd,
                    "pnl": round(pnl, 2),
                    "reason": reason,
                    "capital_after": round(capital, 2),
                    "_regime_at_entry": position.regime,
                })
                position = None

        # --- Calcul indicateurs + décision (seulement si pas de position ouverte) ---
        # Régime courant (optionnel)
        if with_regime and i >= warmup + 30:
            regime = compute_regime_for_window(
                closes_arr[:i+1], highs_arr[:i+1],
                lows_arr[:i+1], volumes_arr[:i+1],
                n_hmm_states=n_hmm_states,
            )
        else:
            regime = "UNKNOWN"
        result.regimes.append(regime)

        if position is None:
            window = ohlcv[i - warmup: i + 1]

            # Trouver les closes journaliers jusqu'à cette bougie
            candle_day = ts_ms // 86_400_000
            daily_idx = [
                j for j, dts in enumerate(daily_ts_from_full)
                if dts // 86_400_000 <= candle_day
            ]
            if daily_idx:
                daily_slice = daily_closes_full[: daily_idx[-1] + 1]
            else:
                daily_slice = np.array([])

            indicators = compute_indicators(window, daily_slice)
            market_score = derive_market_score(indicators)
            global_score = compute_global_score(market_score, cfg)

            action, size_usd = decide(global_score, indicators, cfg)

            if action != "HOLD" and size_usd > 0 and size_usd <= capital:
                price = indicators["price"]
                atr = indicators["atr_14"]

                if action == "BUY":
                    sl = round(price - atr * cfg.atr_sl_mult, 2)
                    tp = round(price + atr * cfg.atr_tp_mult, 2)
                else:
                    sl = round(price + atr * cfg.atr_sl_mult, 2)
                    tp = round(price - atr * cfg.atr_tp_mult, 2)

                position = Position(
                    action=action, entry_price=price,
                    size_usd=size_usd, sl_price=sl, tp_price=tp,
                    entry_ts=ts_ms, regime=regime,
                )

        result.equity_curve.append(round(capital, 2))
        result.timestamps.append(ts_ms)

    # Clôture forcée de la position à la dernière bougie
    if position is not None:
        close_final = ohlcv[-1][4]
        if position.action == "BUY":
            pnl = (close_final - position.entry_price) * position.qty
        else:
            pnl = (position.entry_price - close_final) * position.qty
        capital += pnl
        result.trades.append({
            "entry_ts": position.entry_ts,
            "exit_ts": ohlcv[-1][0],
            "action": position.action,
            "entry": position.entry_price,
            "exit": close_final,
            "size_usd": position.size_usd,
            "pnl": round(pnl, 2),
            "reason": "END",
            "capital_after": round(capital, 2),
            "_regime_at_entry": position.regime,
        })

    return result


# ===========================================================
# MÉTRIQUES DE PERFORMANCE
# ===========================================================

def _regime_breakdown(trades: list[dict]) -> dict:
    """Métriques par régime si les trades ont la clé '_regime_at_entry'."""
    by_regime: dict[str, list[float]] = {}
    for t in trades:
        reg = t.get("_regime_at_entry", "UNKNOWN")
        if reg == "UNKNOWN":
            continue
        by_regime.setdefault(reg, []).append(t["pnl"])
    result = {}
    for reg, pnls in sorted(by_regime.items()):
        wins = sum(1 for p in pnls if p > 0)
        result[reg] = {
            "n": len(pnls),
            "win_rate": round(wins / max(len(pnls), 1), 3),
            "avg_pnl": round(float(np.mean(pnls)), 2),
            "total_pnl": round(float(sum(pnls)), 2),
        }
    return result


def compute_metrics(result: BacktestResult, capital_start: float, symbol: str,
                    start_dt: datetime, end_dt: datetime) -> dict:
    trades = result.trades
    equity = np.array(result.equity_curve) if result.equity_curve else np.array([capital_start])

    n_trades = len(trades)
    if n_trades == 0:
        return {"error": "Aucun trade execute - seuils trop restrictifs ou donnees insuffisantes."}

    pnls = [t["pnl"] for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p <= 0]

    total_pnl = sum(pnls)
    win_rate = len(winners) / n_trades * 100 if n_trades else 0
    avg_win = sum(winners) / len(winners) if winners else 0
    avg_loss = sum(losers) / len(losers) if losers else 0
    profit_factor = abs(sum(winners) / sum(losers)) if losers else float("inf")

    # Max Drawdown
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Sharpe (simplifié — rendements par trade)
    if len(pnls) > 1:
        returns = np.array(pnls) / capital_start
        sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252) if np.std(returns) > 0 else 0
    else:
        sharpe = 0.0

    final_capital = equity[-1]
    total_return_pct = (final_capital - capital_start) / capital_start * 100

    # Buy & Hold comparaison
    first_price = None
    last_price = None
    if result.trades:
        first_price = result.trades[0]["entry"]
        last_price = result.trades[-1]["exit"]
    bh_return = ((last_price - first_price) / first_price * 100) if first_price else 0

    return {
        "symbol": symbol,
        "period": f"{start_dt.date()} → {end_dt.date()}",
        "n_trades": n_trades,
        "win_rate_pct": round(win_rate, 1),
        "total_pnl_usd": round(total_pnl, 2),
        "total_return_pct": round(total_return_pct, 2),
        "buy_hold_return_pct": round(bh_return, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "sharpe_ratio": round(sharpe, 3),
        "capital_start": capital_start,
        "capital_end": round(final_capital, 2),
        "n_wins": len(winners),
        "n_losses": len(losers),
        "by_regime": _regime_breakdown(trades),
    }


# ===========================================================
# AFFICHAGE
# ===========================================================

def print_report(metrics: dict, trades: list[dict]) -> None:
    if "error" in metrics:
        print(f"\n  RESULTAT : {metrics['error']}\n")
        return

    sep = "=" * 56
    print(f"\n{sep}")
    print(f"  BACKTEST ATLAS TRADER - {metrics['symbol']}")
    print(f"  Periode : {metrics['period']}")
    print(sep)
    print(f"  Trades          : {metrics['n_trades']:>8}")
    print(f"  Win rate        : {metrics['win_rate_pct']:>7.1f}%  ({metrics['n_wins']}W / {metrics['n_losses']}L)")
    print(f"  {'-'*52}")
    print(f"  P&L total       : {metrics['total_pnl_usd']:>+9.2f} USD")
    print(f"  Rendement       : {metrics['total_return_pct']:>+8.2f}%")
    print(f"  Buy & Hold ref  : {metrics['buy_hold_return_pct']:>+8.2f}% (BH)")
    print(f"  {'-'*52}")
    print(f"  Max Drawdown    : {metrics['max_drawdown_pct']:>8.2f}%")
    print(f"  Profit Factor   : {metrics['profit_factor']:>8.2f}")
    print(f"  Sharpe (annuel) : {metrics['sharpe_ratio']:>8.3f}")
    print(f"  Gain moyen      : {metrics['avg_win_usd']:>+9.2f} USD")
    print(f"  Perte moyenne   : {metrics['avg_loss_usd']:>+9.2f} USD")
    print(f"  {'-'*52}")
    print(f"  Capital initial : {metrics['capital_start']:>9.2f} USD")
    print(f"  Capital final   : {metrics['capital_end']:>9.2f} USD")
    print(sep)

    # Métriques par régime
    br = metrics.get("by_regime", {})
    if br:
        print(f"\n  Métriques par régime de marché :")
        print(f"  {'Régime':<22} {'N':>5} {'Win%':>6} {'Avg P&L':>9} {'Total P&L':>11}")
        print(f"  {'─'*22} {'─'*5} {'─'*6} {'─'*9} {'─'*11}")
        for reg, m in sorted(br.items()):
            print(
                f"  {reg:<22} {m['n']:>5} {m['win_rate']:>6.1%} "
                f"{m['avg_pnl']:>+9.2f} {m['total_pnl']:>+11.2f}"
            )
        print()

    # Detail des 10 derniers trades
    if trades:
        print(f"\n  Derniers trades ({min(10, len(trades))}/{len(trades)}) :")
        print(f"  {'Date':>10}  {'Action':>4}  {'Entree':>9}  {'Sortie':>9}  {'P&L':>8}  {'Raison':>5}")
        print(f"  {'-'*54}")
        for t in trades[-10:]:
            dt = datetime.fromtimestamp(t["entry_ts"] / 1000).strftime("%Y-%m-%d")
            print(
                f"  {dt:>10}  {t['action']:>4}  "
                f"{t['entry']:>9.2f}  {t['exit']:>9.2f}  "
                f"{t['pnl']:>+8.2f}  {t['reason']:>5}"
            )
    print()


# ===========================================================
# POINT D'ENTRÉE
# ===========================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest Atlas Trader")
    parser.add_argument("--days", type=int, default=30, help="Nombre de jours (défaut: 30)")
    parser.add_argument("--tf", type=str, default="15m",
                        choices=["5m", "15m", "30m", "1h", "4h"],
                        help="Timeframe (défaut: 15m)")
    parser.add_argument("--symbol", type=str, default="BTC/USDT")
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--mode", type=str, default="balanced",
                        choices=["conservative", "balanced", "aggressive"])
    parser.add_argument("--no-ma50", action="store_true",
                        help="Désactive le filtre MA50 (mode 'off')")
    parser.add_argument("--buy-threshold", type=float, default=None,
                        help="Seuil BUY (override settings.yaml)")
    parser.add_argument("--sell-threshold", type=float, default=None,
                        help="Seuil SELL (override settings.yaml)")
    parser.add_argument("--with-regime", action="store_true",
                        help="Active la détection de régime (MarketRegimeAgent)")
    parser.add_argument("--n-hmm-states", type=int, default=2, choices=[2, 3],
                        help="Nombre d'états HMM (2=LOW/HIGH, 3=LOW/MED/HIGH)")
    parser.add_argument("--compare-states", action="store_true",
                        help="Compare HMM 2 vs 3 états (2 passes, avec --with-regime)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Charger les seuils depuis settings.yaml si pas overridés
    try:
        from utils.config import load_settings
        s = load_settings()
        risk = s.get("risk", {})
        scoring_w = s.get("scoring", {}).get("weights", {})
    except Exception:
        risk = {}
        scoring_w = {}

    mode_mult = {"conservative": 0.5, "balanced": 1.0, "aggressive": 1.5}.get(args.mode, 1.0)

    cfg = BacktestConfig(
        buy_threshold=args.buy_threshold or float(risk.get("buy_threshold", 68)),
        sell_threshold=args.sell_threshold or float(risk.get("sell_threshold", 35)),
        ma50_filter_mode="off" if args.no_ma50 else risk.get("ma50_filter_mode", "gradual"),
        ma50_strong_threshold=float(risk.get("ma50_strong_signal_threshold", 72)),
        ma50_size_factor=float(risk.get("ma50_gradual_size_factor", 0.5)),
        capital=args.capital,
        position_size_pct=float(risk.get("position_size_pct", 5.0)) * mode_mult,
        kelly_max=float(risk.get("kelly_max_fraction", 0.25)) * mode_mult,
        atr_sl_mult=float(risk.get("atr_multiplier_sl", 2.0)),
        atr_tp_mult=float(risk.get("atr_multiplier_tp", 3.0)),
        mirofish_weight=float(scoring_w.get("mirofish", 0.15)),
        market_weight=float(scoring_w.get("market", 0.45)),
        agents_weight=float(scoring_w.get("agents", 0.25)),
        contrarian_weight=float(scoring_w.get("contrarian", 0.15)),
    )

    print(f"\n  Atlas Trader - Backtest")
    print(f"  Symbole  : {args.symbol}")
    print(f"  Periode  : {args.days} jours | timeframe {args.tf}")
    print(f"  Mode     : {args.mode} | MA50 filtre : {cfg.ma50_filter_mode}")
    print(f"  Seuils   : BUY >= {cfg.buy_threshold} | SELL <= {cfg.sell_threshold}")
    print(f"  Capital  : {cfg.capital:,.0f} USD\n")

    end_dt = _utcnow()
    start_dt = end_dt - timedelta(days=args.days)

    print("  [1/3] Telechargement des donnees intraday...")
    ohlcv = fetch_ohlcv_history(args.symbol, args.tf, args.days)
    if len(ohlcv) < 150:
        print("  ERREUR: données insuffisantes (< 150 bougies).")
        sys.exit(1)

    print("  [2/3] Telechargement des closes journaliers (MA50)...")
    daily_ohlcv_full = []
    try:
        import ccxt
        exchange = ccxt.binance({"enableRateLimit": True})
        since_ms = int((_utcnow() - timedelta(days=args.days + 60)).timestamp() * 1000)
        daily_ohlcv_full = exchange.fetch_ohlcv(args.symbol, "1d", since=since_ms, limit=args.days + 60)
    except Exception as exc:
        print(f"  Avertissement MA50 : {exc}")

    daily_closes_full = np.array([c[4] for c in daily_ohlcv_full])
    daily_ts_from_full = [c[0] for c in daily_ohlcv_full]

    use_regime = args.with_regime or args.compare_states

    if args.compare_states:
        print("  [3/3] Comparaison HMM 2 vs 3 états...")
        for n_states in (2, 3):
            print(f"\n  --- HMM n_hmm_states={n_states} ---")
            r = run_backtest(ohlcv, daily_closes_full, cfg, args.capital,
                             daily_ts_from_full, with_regime=True, n_hmm_states=n_states)
            m = compute_metrics(r, args.capital, args.symbol, start_dt, end_dt)
            print_report(m, r.trades)
    else:
        print(f"  [3/3] Simulation en cours{' (avec régime)' if use_regime else ''}...")
        result = run_backtest(
            ohlcv, daily_closes_full, cfg, args.capital, daily_ts_from_full,
            with_regime=use_regime, n_hmm_states=args.n_hmm_states,
        )
        metrics = compute_metrics(result, args.capital, args.symbol, start_dt, end_dt)
        print_report(metrics, result.trades)


if __name__ == "__main__":
    main()
