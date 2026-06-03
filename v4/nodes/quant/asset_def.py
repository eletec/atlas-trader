"""
v4/nodes/quant/asset_def.py — Nœud AssetDef

Super-paramètre d'un canvas : définit un actif et expose tous ses champs
en ports de sortie. Les nœuds en aval (LoadMultiTF, RiskATR, AssetTemperature...)
se branchent sur ces ports — changer l'actif reconfigure tout le canvas.
"""
from __future__ import annotations

from typing import Any

from v4.core.node import Node


class AssetDef(Node):
    """
    Nœud source qui expose la définition complète d'un actif.

    Pas d'inputs — nœud racine du canvas.

    Outputs :
        symbol    (str)
        exchange  (str)
        capital   (float)
        fraction  (float)
        fee_rate  (float)
        keywords  (list[str])

    Params (tous les champs du registre assets.json) :
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
        return {}  # nœud racine — pas d'inputs

    @staticmethod
    def output_schema() -> dict[str, str]:
        return {
            "symbol":   "str",
            "exchange": "str",
            "capital":  "float",
            "fraction": "float",
            "fee_rate": "float",
            "keywords": "list",
        }

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol":   self.params.get("symbol", "BTC/USDT"),
            "exchange": self.params.get("exchange", "binance"),
            "capital":  float(self.params.get("capital_usd", 10_000.0)),
            "fraction": float(self.params.get("fraction", 0.005)),
            "fee_rate": float(self.params.get("fee_rate", 0.0004)),
            "keywords": list(self.params.get("keywords", [])),
        }
