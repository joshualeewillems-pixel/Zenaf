/**
 * One-time idempotent migration: pre-rename browser storage used `atria*` keys; current code uses `zenaf*`.
 * Runs once at app boot before React reads preferences. Safe to call repeatedly (only copies when dest empty).
 */

function migrateExactPairs(store: Storage, pairs: readonly (readonly [string, string])[]): void {
  for (const [oldKey, newKey] of pairs) {
    try {
      const v = store.getItem(oldKey)
      if (v == null) continue
      if (store.getItem(newKey) != null) {
        store.removeItem(oldKey)
        continue
      }
      store.setItem(newKey, v)
      store.removeItem(oldKey)
    } catch {
      /* quota / private mode */
    }
  }
}

function migrateKeyPrefix(store: Storage, oldPrefix: string, newPrefix: string): void {
  const keys: string[] = []
  try {
    for (let i = 0; i < store.length; i++) {
      const k = store.key(i)
      if (k && k.startsWith(oldPrefix)) keys.push(k)
    }
  } catch {
    return
  }
  for (const oldKey of keys) {
    try {
      const suffix = oldKey.slice(oldPrefix.length)
      const newKey = newPrefix + suffix
      const v = store.getItem(oldKey)
      if (v == null) continue
      if (store.getItem(newKey) != null) {
        store.removeItem(oldKey)
        continue
      }
      store.setItem(newKey, v)
      store.removeItem(oldKey)
    } catch {
      /* ignore */
    }
  }
}

const LOCAL_EXACT: (readonly [string, string])[] = [
  ['atria_workspace_identity_scan_roots', 'zenaf_workspace_identity_scan_roots'],
  ['atria-perspective-agents', 'zenaf-perspective-agents'],
  ['atria-execution-view-mode', 'zenaf-execution-view-mode'],
  ['atria-project-suggested-work-v1', 'zenaf-project-suggested-work-v1'],
  ['atria-entity-influences-v1', 'zenaf-entity-influences-v1'],
  ['atria_privacy_mode', 'zenaf_privacy_mode'],
]

const SESSION_EXACT: (readonly [string, string])[] = [
  ['atria_workspace_packet', 'zenaf_workspace_packet'],
  ['atria_workspace_identity_branch', 'zenaf_workspace_identity_branch'],
  ['atria-meeting-staging', 'zenaf-meeting-staging'],
  ['atria-meeting-show-review', 'zenaf-meeting-show-review'],
]

/** Prefix migrations: old key prefix → new prefix (same suffix). */
const LOCAL_PREFIXES: (readonly [string, string])[] = [
  ['atria-core-profile-conversation-', 'zenaf-core-profile-conversation-'],
  ['atria.visionMap.layout.v1.', 'zenaf.visionMap.layout.v1.'],
]

const SESSION_PREFIXES: (readonly [string, string])[] = [['atria.resonance.v1.', 'zenaf.resonance.v1.']]

export function migrateAtriaBrandedBrowserStorage(): void {
  if (typeof window === 'undefined') return

  try {
    migrateExactPairs(window.localStorage, LOCAL_EXACT)
    for (const [o, n] of LOCAL_PREFIXES) migrateKeyPrefix(window.localStorage, o, n)

    migrateExactPairs(window.sessionStorage, SESSION_EXACT)
    for (const [o, n] of SESSION_PREFIXES) migrateKeyPrefix(window.sessionStorage, o, n)
  } catch {
    /* ignore */
  }
}
