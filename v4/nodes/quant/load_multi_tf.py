"""
v4/nodes/quant/load_multi_tf.py — Nœud LoadMultiTF

Wrapper V4 autour de quant.data_loader.fetch_history.
Charge l'historique OHLCV 5m + 1h pour un actif donné.
Ne modifie pas data_loader.py.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from v4.core.node import Node, NodeMeta


class LoadMultiTF(Node):
    """
    Charge l'historique OHLCV multi-timeframe pour un actif.

    Params :
        symbol     : str  — ex. "BTC/USDT"
        days_5m    : int  — jours d'historique 5m (défaut 90)
        days_1h    : int  — jours d'historique 1h (défaut 100)
        exchange   : str  — exchange ccxt (défaut "binance")

    Outputs :
        ohlcv_5m   : DataFrame  — OHLCV 5 minutes
        ohlcv_1h   : DataFrame  — OHLCV 1 heure
    """

    @property
    def node_type(self) -> str:
        return "LoadMultiTF"

    @staticmethod
    def input_schema() -> dict[str, str]:
        # Accepts the symbol from an AssetDef node when wired
        return {"symbol": "str"}

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {"ohlcv_5m": "DataFrame", "ohlcv_1h": "DataFrame"}

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from quant.data_loader import fetch_history

        symbol   = inputs.get("symbol") or self.params.get("symbol", "BTC/USDT")
        days_5m  = self.params.get("days_5m", 90)
        days_1h  = self.params.get("days_1h", 100)
        exchange = self.params.get("exchange", "binance")

        ohlcv_5m = fetch_history(
            symbol=symbol, timeframe="5m", days=days_5m,
            exchange_name=exchange, cache=True,
        )
        ohlcv_1h = fetch_history(
            symbol=symbol, timeframe="1h", days=days_1h,
            exchange_name=exchange, cache=True,
        )
        return {"ohlcv_5m": ohlcv_5m, "ohlcv_1h": ohlcv_1h}
