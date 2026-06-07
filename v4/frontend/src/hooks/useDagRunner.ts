/**
 * v4/frontend/src/hooks/useDagRunner.ts
 *
 * Convertit l'état React Flow (nodes + edges) en payload API V4
 * et déclenche POST /dag/run ou POST /dag/schedule.
 */
"use client";

import { useDagStore } from "@/store/dagStore";
import type { NodeRunResult } from "@/store/dagStore";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Convertit les nœuds React Flow en NodeSpec[] pour l'API. */
function buildPayload(dagId: string, asset: string, nodes: any[], edges: any[]) {
  return {
    dag: {
      dag_id: dagId,
      asset,
      nodes: nodes.map((n) => ({
        id: n.id,
        type: n.type ?? n.data?.nodeType ?? "Unknown",
        params: n.data?.params ?? {},
        position: n.position ?? { x: 0, y: 0 },
        meta: {
          label: n.data?.label ?? "",
          group: n.data?.group ?? "",
          bypass: n.data?.bypass ?? false,
          cycle_interval_s: n.data?.cycleIntervalS ?? null,
        },
      })),
      edges: edges.map((e) => ({
        source_node: e.source,
        source_port: e.sourceHandle ?? "output",
        target_node: e.target,
        target_port: e.targetHandle ?? "input",
      })),
    },
  };
}

export function useDagRunner() {
  const { nodes, edges, dagId, asset, setResults, setRunning } = useDagStore();

  const runOnce = async (): Promise<Record<string, NodeRunResult>> => {
    setRunning(true);
    try {
      const payload = buildPayload(dagId, asset, nodes, edges);
      const resp = await fetch(`${API_URL}/dag/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const err = await resp.text();
        throw new Error(`API error ${resp.status}: ${err}`);
      }
      const data = await resp.json();
      setResults(data.results);
      return data.results;
    } finally {
      setRunning(false);
    }
  };

  const schedule = async (cycleS: number): Promise<void> => {
    const payload = { ...buildPayload(dagId, asset, nodes, edges), cycle_s: cycleS };
    const resp = await fetch(`${API_URL}/dag/schedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const err = await resp.text();
      throw new Error(`API error ${resp.status}: ${err}`);
    }
  };

  const stopDag = async (): Promise<void> => {
    const resp = await fetch(`${API_URL}/dag/${encodeURIComponent(dagId)}`, { method: "DELETE" });
    // 404 = déjà arrêté ou registre vidé par reload → ce n'est pas une erreur
    if (!resp.ok && resp.status !== 404) {
      const err = await resp.text();
      throw new Error(`Stop failed (${resp.status}): ${err}`);
    }
    // Même si 404, on considère le DAG comme arrêté
  };

  return { runOnce, schedule, stopDag };
}
