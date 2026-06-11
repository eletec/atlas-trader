/**
 * lib/api-url.ts — URL de l'API Atlas.
 *
 * Priorité :
 * 1. Variable d'env NEXT_PUBLIC_API_URL (build-time)
 * 2. Dérivé de window.location (runtime) : même hostname, port 8000
 * 3. Fallback localhost:8000 (dev local)
 *
 * Permet au frontend de fonctionner quel que soit l'IP du serveur.
 */

export function getApiUrl(): string {
  // Build-time override (ex: pour du staging)
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }

  // Runtime : dériver l'URL API depuis l'URL de la page
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    // En dev local (localhost), l'API est sur le même host
    // En prod, l'API est sur le même host que le frontend, port 8000
    return `${window.location.protocol}//${host}:8000`;
  }

  // SSR fallback
  return "http://localhost:8000";
}

/** URL du frontend (port 3000), dérivée de la page. */
export function getFrontendUrl(): string {
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:3000`;
  }
  return "http://localhost:3000";
}
