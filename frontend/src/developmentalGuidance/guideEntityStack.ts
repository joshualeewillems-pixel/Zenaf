import type { VESelection } from '../vision-execution/VisionExecutionView'
import type { MapTriadDevelopmentalSnapshot } from './types'
import { formatSystemPromptContextTitle } from './systemPromptTitle'

export type GuideEntityKey = { type: string; id: string }

export const VISION_MAP_WORKSPACE_STACK_KEY: GuideEntityKey = { type: 'workspace', id: 'vision_map' }
export const APP_WORKSPACE_STACK_KEY: GuideEntityKey = { type: 'workspace', id: 'app' }

export function entityKeyFromVeSelection(sel: VESelection | null): GuideEntityKey | null {
  if (!sel) return null
  if (sel.ideaId) return { type: 'idea', id: sel.ideaId }
  if (sel.initiativeId) return { type: 'initiative', id: sel.initiativeId }
  if (sel.projectId) return { type: 'project', id: sel.projectId }
  if (sel.taskId) return { type: 'task', id: sel.taskId }
  return null
}

/** Stack bucket for prompts: VE row when selected, else map workspace, else app workspace. */
export function effectiveGuideStackKey(sel: VESelection | null, mainView: string): GuideEntityKey {
  const k = entityKeyFromVeSelection(sel)
  if (k) return { type: k.type.toLowerCase(), id: k.id }
  if (mainView === 'vision_map') return VISION_MAP_WORKSPACE_STACK_KEY
  return APP_WORKSPACE_STACK_KEY
}

export function entityKeyFromPromptSignal(signal: {
  vm_entity_type?: string
  vm_entity_id?: string
} | undefined): GuideEntityKey | null {
  const t = signal?.vm_entity_type?.trim()
  const id = signal?.vm_entity_id?.trim()
  if (!t || !id) return null
  return { type: t.toLowerCase(), id }
}

export function guideEntityKeysEqual(a: GuideEntityKey, b: GuideEntityKey): boolean {
  return a.type.toLowerCase() === b.type.toLowerCase() && a.id === b.id
}

/** Grouping + display for structured questions in the in-thread stack. */
export type GuideQuestionOrigin =
  | 'framing'
  | 'risks'
  | 'drift_change'
  | 'execution'
  | 'clarification'

/** Map ontology kind ↔ VE ref type (prompt signals may use either). */
function mapKindAlignsWithVmType(vmType: string, mapKind: string): boolean {
  const v = vmType.toLowerCase()
  const m = mapKind.toLowerCase()
  if (v === m) return true
  const pairs: [string, string][] = [
    ['idea', 'seed'],
    ['initiative', 'tree'],
    ['project', 'branch'],
    ['task', 'flower'],
    ['outcome', 'fruit'],
  ]
  return pairs.some(([a, b]) => (v === a && m === b) || (v === b && m === a))
}

export type GuideThreadMessage = {
  role: 'user' | 'agent' | 'guide'
  content: string
  agentLabel?: string
  promptSignal?: {
    kind: 'developmental_map'
    /** Canonical id for prompt-signals API (defer / engaged / dismiss). */
    promptId: string
    /** When several thread rows share one canonical promptId, unique UI row + dedupe key. */
    stackRowId?: string
    summaryLine: string
    questionOrigin?: GuideQuestionOrigin
    /** Short user-facing question; derived at render if omitted. */
    questionText?: string
    vm_entity_type?: string
    vm_entity_id?: string
  }
  promptUiHidden?: boolean
  promptContextTitle?: string
}

export function guideBelongsToStackKey(
  message: GuideThreadMessage,
  stackKey: GuideEntityKey,
  mapSnap: MapTriadDevelopmentalSnapshot | null,
): boolean {
  if (message.role !== 'guide') return false
  const gk = entityKeyFromPromptSignal(message.promptSignal)
  if (gk && guideEntityKeysEqual(gk, stackKey)) return true
  if (
    mapSnap &&
    gk &&
    gk.id === mapSnap.node_id &&
    mapKindAlignsWithVmType(gk.type, mapSnap.node_kind)
  ) {
    return true
  }
  // Orphans (no vm on signal): only workspace-level stacks — avoid cross-entity leakage
  if (!gk) {
    return (
      guideEntityKeysEqual(stackKey, VISION_MAP_WORKSPACE_STACK_KEY) ||
      guideEntityKeysEqual(stackKey, APP_WORKSPACE_STACK_KEY)
    )
  }
  return false
}

export function buildStackedGuidesForKey(
  thread: GuideThreadMessage[],
  stackKey: GuideEntityKey,
  getPromptId: (m: GuideThreadMessage) => string,
  mapSnap: MapTriadDevelopmentalSnapshot | null,
): GuideThreadMessage[] {
  const candidates: GuideThreadMessage[] = []
  for (let i = 0; i < thread.length; i++) {
    const m = thread[i]
    if (guideBelongsToStackKey(m, stackKey, mapSnap)) candidates.push(m)
  }
  // Dedupe by prompt_id (keep last occurrence in thread order)
  const seen = new Set<string>()
  const out: GuideThreadMessage[] = []
  for (let i = candidates.length - 1; i >= 0; i--) {
    const m = candidates[i]
    const pid = getPromptId(m)
    if (!pid || seen.has(pid)) continue
    seen.add(pid)
    out.unshift(m)
  }
  return out
}

export function formatGuideStackBarSubtitle(
  stackKey: GuideEntityKey,
  mapSnap: MapTriadDevelopmentalSnapshot | null,
  mainView: string,
): string {
  if (guideEntityKeysEqual(stackKey, VISION_MAP_WORKSPACE_STACK_KEY)) return 'Map'
  if (guideEntityKeysEqual(stackKey, APP_WORKSPACE_STACK_KEY)) return 'Workspace'
  const label =
    mapSnap?.node_id === stackKey.id ? (mapSnap.node_label ?? '').trim() || null : null
  return formatSystemPromptContextTitle({
    mainView,
    mapNodeKind: mapSnap?.node_id === stackKey.id ? mapSnap.node_kind : null,
    veType: stackKey.type,
    nodeLabel: label,
    nestAggregate: mapSnap?.node_kind === 'nest' && mapSnap.node_id === stackKey.id,
  })
}
