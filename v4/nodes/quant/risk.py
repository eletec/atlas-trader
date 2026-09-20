"""
v4/nodes/quant/risk.py — Nœud RiskATR

Wrapper V4 autour de quant.risk.RiskManager.
Calcule le sizing, SL et TP à partir de l'ATR 1h.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from v4.core.node import Node
from v4.nodes.config_loader import load_v4_config


class RiskATR(Node):
    """
    Calcule la position (size, SL, TP) basée sur l'ATR du timeframe 1h.

    Inputs  :
        signal    (str   — "long" | "short" | "flat")
        ohlcv_1h  (DataFrame — OHLCV 1h pour calcul ATR)
        capital   (float — capital disponible en USD, optionnel si dans params)

    Outputs :
        decision  (dict  — {action, size_usd, entry_price, stop_loss, take_profit, reason})

    Params (priorité: DAG > settings.yaml global > settings.yaml symbole > défaut) :
        sl_mult    : float — multiplicateur ATR pour SL
        tp_mult    : float — multiplicateur ATR pour TP
        fraction   : float — fraction max du capital par trade
        capital    : float — capital en USD
        risk_pct   : float — % du capital risqué par trade
    """

    @property
    def node_type(self) -> str:
        return "RiskATR"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {"signal": "str", "ohlcv_1h": "DataFrame", "capital": "float"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"decision": "dict"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from quant.risk import RiskManager, RiskParams

        signal: str    = inputs.get("signal", "flat")
        ohlcv_1h: pd.DataFrame = inputs["ohlcv_1h"]
        capital: float = float(inputs.get("capital") or self.params.get("capital", 10_000.0))

        # -- Parameters: DAG first -> settings.yaml -> default --
        symbol = self.params.get("symbol", "")
        _cfg = load_v4_config(symbol, "risk", {
            "capital": 10_000, "max_fraction": 0.02, "risk_pct": 1.0,
            "sl_mult": 2.0, "tp_mult": 4.0,
        })
        sl_mult  = float(self.params.get("sl_mult", _cfg["sl_mult"]))
        tp_mult  = float(self.params.get("tp_mult", _cfg["tp_mult"]))
        fraction = float(self.params.get("fraction", _cfg["max_fraction"]))
        risk_pct = float(self.params.get("risk_pct", _cfg["risk_pct"]))
        if not capital or capital <= 0:
            capital = float(_cfg.get("capital", 10_000))

        if signal == "flat" or ohlcv_1h is None or ohlcv_1h.empty:
            return {"decision": {"action": "flat", "reason": "signal_flat"}}

        # 1h ATR (14-period window)
        high = ohlcv_1h["high"]
        low  = ohlcv_1h["low"]
        close = ohlcv_1h["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])

        entry_price = float(close.iloc[-1])

        # -- Contextual sizing based on risk --
        # Risque max par trade = risk_pct% du capital
        max_risk_usd = capital * (risk_pct / 100.0)
        # Risque unitaire = distance SL / prix (en %)
        if entry_price > 0 and atr > 0:
            risk_per_unit = (sl_mult * atr) / entry_price  # % loss if the stop is hit
        else:
            risk_per_unit = 0.01  # fallback 1%
        # Risk-based size: risk at most max_risk_usd over the stop distance
        risk_based_size = max_risk_usd / risk_per_unit if risk_per_unit > 0 else capital * fraction
        # Capital fraction cap (the only limit; risk is already handled by risk_based_size)
        size_usd = min(risk_based_size, capital * fraction)
        # $10 minimum to avoid insignificant trades
        size_usd = max(size_usd, 10.0)

        # -- V6: Kelly sizing (half-Kelly for crypto) --
        kelly_enabled = bool(self.params.get("use_kelly", True))
        if kelly_enabled:
            # Estimate the edge and variance from the signal
            prob_up = float(inputs.get("prob_up", 0.5))
            confidence = abs(prob_up - 0.5) * 2.0  # 0-1
            # Kelly f* = edge / variance, with edge = confidence x (win_rate_estimate - 0.5)
            # Simplified: f* ~ (2 x prob_up - 1) if long, (1 - 2 x prob_up) if short
            if signal == "long":
                kelly_f = max(0, 2 * prob_up - 1)  # ex: prob_up=0.60 → f*=0.20
            else:
                kelly_f = max(0, 1 - 2 * prob_up)  # ex: prob_up=0.40 → f*=0.20
            # Half-Kelly (more conservative, recommended for crypto)
            kelly_fraction = float(self.params.get("kelly_fraction", 0.5))
            kelly_f *= kelly_fraction
            # Apply Kelly to the sizing: size x (1 + kelly_f x confidence)
            kelly_mult = 1.0 + kelly_f * confidence
            kelly_mult = min(kelly_mult, 2.0)  # cap at 2x the base sizing
            size_usd *= kelly_mult
            size_usd = min(size_usd, capital * fraction)  # respect the cap
            size_usd = max(size_usd, 10.0)

        if signal == "long":
            stop_loss   = entry_price - sl_mult * atr
            take_profit = entry_price + tp_mult * atr
        else:  # short
            stop_loss   = entry_price + sl_mult * atr
            take_profit = entry_price - tp_mult * atr

        size_units = size_usd / entry_price

        return {
            "decision": {
                "action":      signal,
                "entry_price": entry_price,
                "stop_loss":   round(stop_loss, 4),
                "take_profit": round(take_profit, 4),
                "size_usd":    round(size_usd, 2),
                "size_units":  round(size_units, 6),
                "atr":         round(float(atr), 4),
                "reason":      f"atr_sl{sl_mult}_tp{tp_mult}",
            }
        }
