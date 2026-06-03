/**
 * v4/frontend/src/store/priceStore.ts
 *
 * Stocke les prix reçus via SSE.
 * Composants isolés — jamais re-render de la page entière.
 * Usage : const price = usePriceStore((s) => s.prices["BTC/USDT"]?.price);
 */
import { create } from "zustand";

interface PriceRecord {
  symbol: string;
  price: number;
  ts: number;
}

interface PriceState {
  prices: Record<string, PriceRecord>;
  connected: boolean;
  update: (record: PriceRecord) => void;
  setConnected: (v: boolean) => void;
}

export const usePriceStore = create<PriceState>()((set) => ({
  prices: {},
  connected: false,

  update: (record) =>
    set((s) => ({
      prices: { ...s.prices, [record.symbol]: record },
    })),

  setConnected: (connected) => set({ connected }),
}));
