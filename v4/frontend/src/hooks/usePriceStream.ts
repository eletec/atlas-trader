/**
 * v4/frontend/src/hooks/usePriceStream.ts
 *
 * S'abonne au SSE /prices/stream et met à jour le priceStore.
 * À monter UNE SEULE FOIS dans le layout (ou un composant root).
 * Reconnexion automatique à chaque perte de connexion.
 */
"use client";

import { useEffect, useRef } from "react";
import { usePriceStore } from "@/store/priceStore";
import { getApiUrl } from "@/lib/api-url";

const API_URL = getApiUrl();

export function usePriceStream(symbols: string[]) {
  const update = usePriceStore((s) => s.update);
  const setConnected = usePriceStore((s) => s.setConnected);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!symbols.length) return;

    const query = symbols.map(encodeURIComponent).join(",");
    const url = `${API_URL}/prices/stream?symbols=${query}`;

    let es: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (es) { es.close(); es = null; }
      if (timeoutId) clearTimeout(timeoutId);

      es = new EventSource(url);

      es.onopen = () => {
        setConnected(true);
        // Arrêter le polling si SSE actif
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      };

      es.addEventListener("price", (e) => {
        try {
          const record = JSON.parse((e as MessageEvent).data);
          update(record);
        } catch { /* ignore */ }
      });

      es.onerror = () => {
        setConnected(false);
        es?.close();
        es = null;
        // Démarrer le polling REST en fallback
        if (!pollTimer) {
          pollTimer = setInterval(async () => {
            try {
              const resp = await fetch(`${API_URL}/prices/snapshot`);
              if (resp.ok) {
                const snap = await resp.json();
                Object.entries(snap).forEach(([symbol, data]: [string, any]) => {
                  update({ symbol, ...data });
                });
                setConnected(true);
              }
            } catch { /* ignore */ }
          }, 10_000); // poll toutes les 10s
        }
        // Réessayer SSE après 15s
        timeoutId = setTimeout(connect, 15_000);
      };
    };

    connect();
    return () => {
      es?.close();
      if (pollTimer) clearInterval(pollTimer);
      if (timeoutId) clearTimeout(timeoutId);
      setConnected(false);
    };
  }, [symbols.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
}
