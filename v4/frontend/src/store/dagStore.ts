/**
 * v4/frontend/src/store/dagStore.ts
 *
 * État global du canvas : nœuds React Flow, edges, résultats d'exécution.
 * Persiste le DAG JSON dans localStorage (clé "atlas_v4_dag").
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  Node as RFNode,
  Edge as RFEdge,
  NodeChange,
  EdgeChange,
  Connection,
} from "@xyflow/react";
import { applyNodeChanges, applyEdgeChanges, addEdge } from "@xyflow/react";

export interface NodeRunResult {
  node_id: string;
  status: "idle" | "running" | "done" | "error" | "bypassed" | "stale";
  outputs: Record<string, unknown>;
  error?: string | null;
  duration_ms: number;
  ai_used: boolean;
}

interface DAGState {
  nodes: RFNode[];
  edges: RFEdge[];
  dagId: string;
  asset: string;
  results: Record<string, NodeRunResult>;
  isRunning: boolean;

  // Actions
  setNodes: (nodes: RFNode[]) => void;
  setEdges: (edges: RFEdge[]) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  setAsset: (asset: string) => void;
  setDagId: (id: string) => void;
  setResults: (results: Record<string, NodeRunResult>) => void;
  setRunning: (v: boolean) => void;
  reset: () => void;
}

export const useDagStore = create<DAGState>()(
  persist(
    (set) => ({
      nodes: [],
      edges: [],
      dagId: "default",
      asset: "BTC/USDT",
      results: {},
      isRunning: false,

      setNodes: (nodes) => set({ nodes }),
      setEdges: (edges) => set({ edges }),

      onNodesChange: (changes) =>
        set((s) => ({ nodes: applyNodeChanges(changes, s.nodes) })),

      onEdgesChange: (changes) =>
        set((s) => ({ edges: applyEdgeChanges(changes, s.edges) })),

      onConnect: (connection) =>
        set((s) => ({ edges: addEdge(connection, s.edges) })),

      setAsset: (asset) => set({ asset }),
      setDagId: (dagId) => set({ dagId }),
      setResults: (results) => set({ results }),
      setRunning: (isRunning) => set({ isRunning }),

      reset: () => set({ nodes: [], edges: [], results: {} }),
    }),
    {
      name: "atlas_v4_dag",
      partialize: (s) => ({ nodes: s.nodes, edges: s.edges, dagId: s.dagId, asset: s.asset }),
    }
  )
);
