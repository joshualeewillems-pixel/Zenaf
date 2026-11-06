/**
 * True when the primary pointer is coarse (touch) — a phone or tablet.
 *
 * Chat composers use this to decide what the Enter key does: on a
 * desktop (fine pointer) Enter sends and Shift+Enter inserts a newline;
 * on a phone there is no Shift key, so Enter must insert a newline and
 * only the Send button sends (2026-11-05, Joshua: "there is no shift
 * on the phone... there's a button to send we don't need enter to send").
 *
 * Guarded for environments without matchMedia (older jsdom, SSR): no
 * matchMedia means "not coarse", i.e. desktop behavior.
 */
export function isCoarsePointer(): boolean {
  if (typeof window === 'undefined') return false
  const mm = window.matchMedia
  if (typeof mm !== 'function') return false
  return mm('(pointer: coarse)').matches
}
