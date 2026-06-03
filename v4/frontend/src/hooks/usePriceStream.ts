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

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function usePriceStream(symbols: string[]) {
  const update = usePriceStore((s) => s.update);
  const setConnected = usePriceStore((s) => s.setConnected);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!symbols.length) return;

    const query = symbols.map(encodeURIComponent).join(",");
    const url = `${API_URL}/prices/stream?symbols=${query}`;

    const connect = () => {
      if (esRef.current) {
        esRef.current.close();
      }
      const es = new EventSource(url);
      esRef.current = es;

      es.onopen = () => setConnected(true);

      es.addEventListener("price", (e) => {
        try {
          const record = JSON.parse((e as MessageEvent).data);
          update(record);
        } catch {
          // ignore malformed messages
        }
      });

      es.onerror = () => {
        setConnected(false);
        es.close();
        // Reconnect après 5s
        setTimeout(connect, 5_000);
      };
    };

    connect();
    return () => {
      esRef.current?.close();
      setConnected(false);
    };
  }, [symbols.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
}
