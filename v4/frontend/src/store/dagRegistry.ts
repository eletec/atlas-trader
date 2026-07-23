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
const VERSION_KEY = "atlas_v4_dag_version";
const CURRENT_VERSION = 17;  // bump → force clear localStorage, reload DAGs from API

// Force clear si version mismatch (V6 → V7)
if (typeof window !== "undefined") {
  const storedVersion = parseInt(localStorage.getItem(VERSION_KEY) || "0", 10);
  if (storedVersion < CURRENT_VERSION) {
    // Clear ALL atlas DAG data (registry + individual DAGs + old key)
    const keys = Object.keys(localStorage).filter(k => k.startsWith("atlas_v4_dag"));
    keys.forEach(k => localStorage.removeItem(k));
    // Also clear the zustand persist store for dagStore
    const zustandKeys = Object.keys(localStorage).filter(k => k.includes("dagStore") || k.includes("dag-store"));
    zustandKeys.forEach(k => localStorage.removeItem(k));
    localStorage.setItem(VERSION_KEY, String(CURRENT_VERSION));
    console.log("V7: cleared", keys.length, "old DAG keys from localStorage");
  }
}

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
        // V7 — 13 actifs (sync avec carry_assets.yaml)
        const required = [
          { id: "default", name: "BTC/USDT" },
          { id: "eth",     name: "ETH/USDT" },
          { id: "sol",     name: "SOL/USDT" },
          { id: "bnb",     name: "BNB/USDT" },
          { id: "xrp",     name: "XRP/USDT" },
          { id: "ada",     name: "ADA/USDT" },
          { id: "doge",    name: "DOGE/USDT" },
          { id: "avax",    name: "AVAX/USDT" },
          { id: "link",    name: "LINK/USDT" },
          { id: "dot",     name: "DOT/USDT" },
          { id: "ltc",     name: "LTC/USDT" },
          { id: "near",    name: "NEAR/USDT" },
          { id: "sui",     name: "SUI/USDT" },
        ];
        const existing = new Set(dags.map((d) => d.id));
        const missing = required.filter((r) => !existing.has(r.id));
        if (missing.length > 0) {
          const now = Date.now();
          set({
            dags: [...dags, ...missing.map((m) => ({ ...m, createdAt: now }))],
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
