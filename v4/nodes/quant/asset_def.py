"""
v4/nodes/quant/asset_def.py — AssetDef node

Super-parameter of a canvas: defines an asset and exposes all its fields
as output ports. The downstream nodes (LoadMultiTF, RiskATR, AssetTemperature...)
connect to these ports — changing the asset reconfigures the whole canvas.
"""
from __future__ import annotations

from typing import Any

from v4.core.node import Node


class AssetDef(Node):
    """
    Source node that exposes the full definition of an asset.

    No inputs — root node of the canvas.

    Outputs :
        symbol    (str)
        exchange  (str)
        capital   (float)
        fraction  (float)
        fee_rate  (float)
        keywords  (list[str])

    Params (all the fields of the assets.json registry):
        symbol        : "BTC/USDT"
        exchange      : "binance"
        market_type   : "futures" | "spot"
        capital_usd   : 10000
        fraction      : 0.005
        fee_rate      : 0.0004
        min_notional  : 5
        keywords      : ["bitcoin", "BTC"]
        reddit        : ["bitcoin", "CryptoCurrency"]
        notes         : ""
    """

    @property
    def node_type(self) -> str:
        return "AssetDef"

    @staticmethod
    def input_schema() -> dict[str, str]:
        return {}  # root node — no inputs

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {
            "symbol":   "str",
            "exchange": "str",
            "capital":  "float",
            "fraction": "float",
            "fee_rate": "float",
            "keywords": "list",
            "max_positions": "int",
        }

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol":   self.params.get("symbol", "BTC/USDT"),
            "exchange": self.params.get("exchange", "binance"),
            "capital":  float(self.params.get("capital_usd", 10_000.0)),
            "fraction": float(self.params.get("fraction", 0.005)),
            "fee_rate": float(self.params.get("fee_rate", 0.0004)),
            "keywords": list(self.params.get("keywords", [])),
            "max_positions": int(self.params.get("max_positions", 3)),
        }
