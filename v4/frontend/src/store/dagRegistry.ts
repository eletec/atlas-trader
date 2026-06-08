/**
 * v4/frontend/src/store/dagRegistry.ts
 *
 * Registre multi-DAG — gère la liste des flows, création, renommage,
 * suppression, et bascule entre flows.
 * Chaque DAG est stocké dans localStorage sous "atlas_v4_dag_{id}".
 */
"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface DAGEntry {
  id: string;
  name: string;
  createdAt: number;
}

interface DAGRegistryState {
  dags: DAGEntry[];
  activeId: string;
  setActive: (id: string) => void;
  create: (name: string) => DAGEntry;
  rename: (id: string, name: string) => void;
  remove: (id: string) => void;
  ensureDefault: () => void;
}

// Clé localStorage pour le registre
const REGISTRY_KEY = "atlas_v4_dag_registry";

// Sauvegarder/charger un DAG complet depuis localStorage
export function saveDAG(id: string, data: { nodes: unknown[]; edges: unknown[]; asset: string }) {
  if (typeof window === "undefined") return;
  localStorage.setItem(`atlas_v4_dag_${id}`, JSON.stringify(data));
}

export function loadDAG(id: string): { nodes: unknown[]; edges: unknown[]; asset: string } | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(`atlas_v4_dag_${id}`);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function deleteDAGStorage(id: string) {
  if (typeof window === "undefined") return;
  localStorage.removeItem(`atlas_v4_dag_${id}`);
}

export const useDagRegistry = create<DAGRegistryState>()(
  persist(
    (set, get) => ({
      dags: [],
      activeId: "default",

      setActive: (id) => {
        // Sauvegarder l'actif courant avant de switcher
        const prevId = get().activeId;
        if (prevId && prevId !== id) {
          const prevRaw = localStorage.getItem("atlas_v4_dag");
          if (prevRaw) {
            localStorage.setItem(`atlas_v4_dag_${prevId}`, prevRaw);
          }
        }
        // Charger le nouveau
        const data = loadDAG(id);
        if (data) {
          localStorage.setItem("atlas_v4_dag", JSON.stringify(data));
        }
        set({ activeId: id });
      },

      create: (name) => {
        const entry: DAGEntry = {
          id: `dag_${Date.now()}`,
          name: name.trim() || "Nouveau flow",
          createdAt: Date.now(),
        };
        set((s) => ({ dags: [...s.dags, entry] }));
        return entry;
      },

      rename: (id, name) =>
        set((s) => ({
          dags: s.dags.map((d) => (d.id === id ? { ...d, name } : d)),
        })),

      remove: (id) => {
        deleteDAGStorage(id);
        set((s) => {
          const next = s.dags.filter((d) => d.id !== id);
          // Si on supprime l'actif, basculer sur le premier restant
          if (s.activeId === id && next.length > 0) {
            const newActive = next[0].id;
            const data = loadDAG(newActive);
            if (data) {
              localStorage.setItem("atlas_v4_dag", JSON.stringify(data));
            }
            return { dags: next, activeId: newActive };
          }
          return { dags: next };
        });
      },

      ensureDefault: () => {
        const { dags } = get();
        if (dags.length === 0) {
          set({
            dags: [
              { id: "default", name: "BTC/USDT", createdAt: Date.now() },
              { id: "eth",    name: "ETH/USDT", createdAt: Date.now() },
              { id: "sol",    name: "SOL/USDT", createdAt: Date.now() },
              { id: "bnb",    name: "BNB/USDT", createdAt: Date.now() },
              { id: "xrp",    name: "XRP/USDT", createdAt: Date.now() },
            ],
            activeId: "default",
          });
        }
      },
    }),
    {
      name: REGISTRY_KEY,
      partialize: (s) => ({ dags: s.dags, activeId: s.activeId }),
    }
  )
);
