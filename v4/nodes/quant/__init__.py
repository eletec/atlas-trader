"""
v4/nodes/quant/__init__.py — Export de tous les nœuds quant V4
"""
from v4.nodes.quant.asset_def import AssetDef
from v4.nodes.quant.compute_features import ComputeFeatures, Normalize
from v4.nodes.quant.load_multi_tf import LoadMultiTF
from v4.nodes.quant.output import AlertOnly, PaperTrader, RecordDecision
from v4.nodes.quant.regime import RegimeHMM, RegimePassthrough
from v4.nodes.quant.risk import RiskATR
from v4.nodes.quant.signal import SignalLogReg

__all__ = [
    "AssetDef",
    "LoadMultiTF",
    "ComputeFeatures",
    "Normalize",
    "RegimeHMM",
    "RegimePassthrough",
    "SignalLogReg",
    "RiskATR",
    "PaperTrader",
    "AlertOnly",
    "RecordDecision",
]

# Registre global des types de nœuds — utilisé par le DAGExecutor pour instancier depuis JSON
NODE_REGISTRY: dict[str, type] = {
    cls.__name__: cls
    for cls in [
        AssetDef, LoadMultiTF, ComputeFeatures, Normalize,
        RegimeHMM, RegimePassthrough, SignalLogReg,
        RiskATR, PaperTrader, AlertOnly, RecordDecision,
    ]
}
