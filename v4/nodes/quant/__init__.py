"""
v4/nodes/quant/__init__.py — Export de tous les nœuds quant V4 + V7
"""
from v4.nodes.quant.asset_def import AssetDef
from v4.nodes.quant.compute_features import ComputeFeatures, Normalize
from v4.nodes.quant.cross_tf import CrossTFArb
from v4.nodes.quant.direction_gate import DirectionGate
from v4.nodes.quant.load_multi_tf import LoadMultiTF
from v4.nodes.quant.output import AlertOnly, PaperTrader, RecordDecision
from v4.nodes.quant.position_manager import PositionManager
from v4.nodes.quant.reflection import ReflectionNode
from v4.nodes.quant.regime_detector import RegimeDetector
from v4.nodes.quant.regime import RegimeHMM, RegimePassthrough
from v4.nodes.quant.risk import RiskATR
from v4.nodes.quant.signal import SignalLogReg
from v4.nodes.quant.signal_constant import SignalConstant
from v4.nodes.quant.signal_xgb import SignalXGB
from v4.nodes.quant.trend_filter import TrendFilter

# V7 nodes
try:
    from v7.nodes.funding_carry_node import FundingCarryNode
    _has_v7 = True
except ImportError:
    FundingCarryNode = None
    _has_v7 = False

__all__ = [
    "AssetDef",
    "ComputeFeatures",
    "CrossTFArb",
    "DirectionGate",
    "LoadMultiTF",
    "Normalize",
    "RegimeHMM",
    "RegimePassthrough",
    "RegimeDetector",
    "RiskATR",
    "SignalConstant",
    "SignalLogReg",
    "SignalXGB",
    "PaperTrader",
    "AlertOnly",
    "RecordDecision",
    "PositionManager",
    "ReflectionNode",
    "TrendFilter",
    "FundingCarryNode",
]

# Registre global des types de nœuds — utilisé par le DAGExecutor pour instancier depuis JSON
_registry_classes = [
    AssetDef, LoadMultiTF, ComputeFeatures, Normalize,
    CrossTFArb,
    DirectionGate, RegimeHMM, RegimePassthrough, RegimeDetector,
    SignalConstant, SignalLogReg, SignalXGB,
    RiskATR, PaperTrader, AlertOnly, RecordDecision,
    PositionManager,
    ReflectionNode,
    TrendFilter,
]
if _has_v7 and FundingCarryNode is not None:
    _registry_classes.append(FundingCarryNode)

NODE_REGISTRY: dict[str, type] = {
    cls.__name__: cls
    for cls in _registry_classes
}
