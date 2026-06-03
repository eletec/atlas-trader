/**
 * v4/frontend/src/lib/utils.ts
 * Helpers légers (cn pour clsx + tailwind-merge).
 */
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
