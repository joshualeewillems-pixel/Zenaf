import type { DevelopmentalGuidanceContext } from '../developmentalGuidance/types'
import { VISION_EXECUTION_API } from './types'

export type PromptSignalAction = 'engaged' | 'dismissed' | 'deferred'

export type DeferredPromptItem = {
  id: string
  prompt_id: string
  prompt_summary: string
  deferred_until: string | null
  created_at: string
}

const JSON_HDR = { 'Content-Type': 'application/json' }

async function parseErr(res: Response): Promise<string> {
  const t = await res.text().catch(() => res.statusText)
  try {
    const j = JSON.parse(t) as { detail?: string }
    if (typeof j.detail === 'string') return j.detail
  } catch {
    /* ignore */
  }
  return t || res.statusText
}

/**
 * Vision Map developmental guidance — narrow prompt identity for dismiss/defer (not global profile).
 * Changing fingerprint rules yields new prompt_ids; prior dismiss rows no longer suppress reinjection.
 */
const VISION_MAP_GUIDANCE_NAMESPACE = 'dm:vm'
const HASH_PREFIX = '/h'

type NormalizedKeyValuePairs = Record<string, string>

type NormalizedHypothesis = { c: string; k: string; s: string }
type NormalizedAxis = { n: string; t: string }

/** Sort embeddings instead of object key order — stable fingerprint across JS engines. */
function normalizedDevelopmentalMapEmbedding(
  ctx: DevelopmentalGuidanceContext | null | undefined,
): NormalizedKeyValuePairs {
  if (!ctx || typeof ctx !== 'object') return {}
  const out: NormalizedKeyValuePairs = {}
  const vmType = ctx.vm_entity_type
  const vmId = ctx.vm_entity_id
  if (typeof vmType === 'string' && vmType.trim()) out.vm_entity_type = vmType.trim()
  if (typeof vmId === 'string' && vmId.trim()) out.vm_entity_id = vmId.trim()
  const style = ctx.suggested_guidance_style
  if (typeof style === 'string' && style.trim()) out.style = style.trim()
  const variant = (ctx as { variant?: string }).variant
  if (typeof variant === 'string' && variant.trim()) out.variant = variant.trim()

  const hyps = Array.isArray(ctx.hypotheses) ? ctx.hypotheses : []
  const axes = Array.isArray(ctx.axes) ? ctx.axes : []
  const nh: NormalizedHypothesis[] = hyps.map((h) => ({
    c: String((h as { confidence?: string }).confidence ?? '').trim(),
    k: String((h as { kind?: string }).kind ?? '').trim(),
    s: String((h as { statement?: string }).statement ?? '').trim().replace(/\s+/g, ' '),
  }))
  nh.sort((a, b) => {
    const x = `${a.s}\x1e${a.k}\x1e${a.c}`
    const y = `${b.s}\x1e${b.k}\x1e${b.c}`
    return x < y ? -1 : x > y ? 1 : 0
  })
  if (nh.length) out._hyp = JSON.stringify(nh)

  const na: NormalizedAxis[] = axes.map((a) => ({
    n: String((a as { name?: string }).name ?? '').trim(),
    t: String((a as { tilt?: string }).tilt ?? '').trim(),
  }))
  na.sort((a, b) => {
    const x = `${a.n}\x1e${a.t}`
    const y = `${b.n}\x1e${b.t}`
    return x < y ? -1 : x > y ? 1 : 0
  })
  if (na.length) out._ax = JSON.stringify(na)

  return out
}

function buildDevelopmentalMapFingerprintText(ctx: DevelopmentalGuidanceContext | null | undefined): string {
  const norm = normalizedDevelopmentalMapEmbedding(ctx)
  const keys = Object.keys(norm).sort()
  const parts: string[] = []
  for (const k of keys) {
    parts.push(`${k}=${norm[k]}`)
  }
  return parts.join('\n')
}

function dualHashHexStable(text: string): string {
  const s = text.replace(/\r\n/g, '\n')
  let h32 = 0x811c9dc5 >>> 0
  for (let i = 0; i < s.length; i++) {
    h32 ^= s.charCodeAt(i)
    h32 = Math.imul(h32, 0x01000193) >>> 0
  }
  let djb = 5381 >>> 0
  for (let i = 0; i < s.length; i++) {
    djb = (Math.imul(31, djb) + s.charCodeAt(i)) >>> 0
  }
  const hi = (h32 >>> 0).toString(16).padStart(8, '0')
  const lo = (djb >>> 0).toString(16).padStart(8, '0')
  return `${hi}${lo}`
}

/** Canonical fingerprint for dedupe + logging; stable for a given guidance snapshot. */
export function buildDevelopmentalMapFingerprint(ctx: DevelopmentalGuidanceContext | null | undefined): string {
  return `${VISION_MAP_GUIDANCE_NAMESPACE}:${HASH_PREFIX}:${dualHashHexStable(buildDevelopmentalMapFingerprintText(ctx))}`
}

/** Server prompt_id for Vision Map developmental guidance — specific snapshot, not a broad class. */
export function developmentalMapVisionMapPromptId(
  ctx: DevelopmentalGuidanceContext | null | undefined,
): string | null {
  const fp = buildDevelopmentalMapFingerprint(ctx)
  const tail = fp.split(':').pop()
  if (!tail || tail.length < 8) return null
  return `${VISION_MAP_GUIDANCE_NAMESPACE}:g:${tail}`
}

/** When developmental context is unavailable, stable id from map row + seeded text (dismiss/defer still work). */
export function fallbackMapGuidePromptId(
  veType: string,
  entityId: string,
  kind: string,
  combinedGuideText: string,
): string {
  const text = [
    VISION_MAP_GUIDANCE_NAMESPACE,
    'thread_seed',
    veType,
    entityId,
    kind,
    combinedGuideText.slice(0, 3000),
  ].join('\n')
  const fp = `${VISION_MAP_GUIDANCE_NAMESPACE}:${HASH_PREFIX}:${dualHashHexStable(text)}`
  const tail = fp.split(':').pop()!
  return `${VISION_MAP_GUIDANCE_NAMESPACE}:g:${tail}`
}

/** Legacy guide rows without promptSignal — one id per distinct body so dismiss targets one bubble. */
export function ephemeralGuidePromptIdFromContent(content: string): string {
  const fp = `${VISION_MAP_GUIDANCE_NAMESPACE}:${HASH_PREFIX}:${dualHashHexStable(`orphan_thread\n${content.slice(0, 4000)}`)}`
  const tail = fp.split(':').pop()!
  return `${VISION_MAP_GUIDANCE_NAMESPACE}:g:${tail}`
}

export async function checkPromptShouldShow(promptId: string): Promise<boolean> {
  const q = new URLSearchParams({ prompt_id: promptId })
  const res = await fetch(`${VISION_EXECUTION_API}/prompt-signals/check?${q}`, { credentials: 'include' })
  if (!res.ok) return true
  const j = (await res.json()) as { show?: boolean }
  return j.show !== false
}

export async function postPromptSignal(payload: {
  prompt_id: string
  action: PromptSignalAction
  entity_type?: string | null
  entity_id?: string | null
  prompt_summary?: string
  deferred_until?: string | null
}): Promise<void> {
  const res = await fetch(`${VISION_EXECUTION_API}/prompt-signals`, {
    method: 'POST',
    credentials: 'include',
    headers: JSON_HDR,
    body: JSON.stringify({
      prompt_id: payload.prompt_id,
      action: payload.action,
      entity_type: payload.entity_type ?? null,
      entity_id: payload.entity_id ?? null,
      prompt_summary: payload.prompt_summary ?? '',
      deferred_until: payload.deferred_until ?? null,
    }),
  })
  if (!res.ok) throw new Error(await parseErr(res))
}

export async function fetchDeferredPrompts(
  entityType: string,
  entityId: string,
): Promise<DeferredPromptItem[]> {
  const q = new URLSearchParams({ entity_type: entityType, entity_id: entityId })
  const res = await fetch(`${VISION_EXECUTION_API}/prompt-signals/deferred?${q}`, { credentials: 'include' })
  if (!res.ok) throw new Error(await parseErr(res))
  const j = (await res.json()) as { items?: DeferredPromptItem[] }
  return Array.isArray(j.items) ? j.items : []
}

export const WORKSPACE_DEFER_ENTITY = { entity_type: 'workspace', entity_id: 'vision_map' } as const
