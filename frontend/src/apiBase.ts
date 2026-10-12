/**
 * Base URL for backend API fetches.
 *
 * - Production build: bake in VITE_API_BASE="" (empty = same origin; the
 *   backend serves this SPA in hosted mode).
 * - Local dev: leave VITE_API_BASE unset → absolute http://127.0.0.1:8010,
 *   so the session cookie host matches the API (see vite.config.ts;
 *   localhost:5173 would not send cookies to 127.0.0.1:8010).
 *
 * Centralize all absolute backend URLs behind this helper. Relative-URL
 * fetches (e.g. `/vision-execution/...`) already work in both modes.
 */
export function apiBase(): string {
  const v = import.meta.env.VITE_API_BASE;
  if (v !== undefined) return v;
  return 'http://127.0.0.1:8010';
}
