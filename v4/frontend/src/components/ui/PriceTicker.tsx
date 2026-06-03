/**
 * v4/frontend/src/components/ui/PriceTicker.tsx
 *
 * Affiche le prix d'un symbole en temps réel.
 * Composant isolé : seul ce composant re-render quand le prix change.
 */
"use client";

import { usePriceStore } from "@/store/priceStore";
import { cn } from "@/lib/utils";
import { useRef } from "react";

interface Props {
  symbol: string;
  className?: string;
}

export function PriceTicker({ symbol, className }: Props) {
  const record = usePriceStore((s) => s.prices[symbol]);
  const prevRef = useRef<number | null>(null);

  const price = record?.price ?? null;
  const direction =
    price === null || prevRef.current === null
      ? "neutral"
      : price > prevRef.current
      ? "up"
      : price < prevRef.current
      ? "down"
      : "neutral";

  if (price !== null) prevRef.current = price;

  return (
    <span
      className={cn(
        "font-mono tabular-nums text-sm transition-colors",
        direction === "up" && "text-canvas-success",
        direction === "down" && "text-canvas-danger",
        direction === "neutral" && "text-slate-300",
        className
      )}
    >
      {price !== null ? price.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "---"}
    </span>
  );
}
