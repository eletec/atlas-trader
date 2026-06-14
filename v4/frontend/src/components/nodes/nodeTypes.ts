/**
 * v4/frontend/src/components/nodes/nodeTypes.ts
 *
 * Registre React Flow — associe chaque node_type à un composant React.
 * Les nœuds non définis tombent sur BaseNode.
 */
import { BaseNode } from "./BaseNode";
import { AssetDefNode } from "./AssetDefNode";

export const nodeTypes = {
  // Nœud spécial
  AssetDef: AssetDefNode,

  // Tous les autres → BaseNode générique
  LoadMultiTF: BaseNode,
  ComputeFeatures: BaseNode,
  Normalize: BaseNode,
  RegimeHMM: BaseNode,
  RegimePassthrough: BaseNode,
  SignalLogReg: BaseNode,
  SignalConstant: BaseNode,
  TrendFilter: BaseNode,
  DirectionGate: BaseNode,
  MetaGate: BaseNode,
  CircuitBreaker: BaseNode,
  PortfolioRisk: BaseNode,
  RegimeDetector: BaseNode,
  SignalXGB: BaseNode,
  CrossTFArb: BaseNode,
  DebateNode: BaseNode,
  PositionManager: BaseNode,
  ReflectionNode: BaseNode,
  LLMNode: BaseNode,
  RiskATR: BaseNode,
  PaperTrader: BaseNode,
  AlertOnly: BaseNode,
  RecordDecision: BaseNode,
  FundingCarryNode: BaseNode,   // V7
};
