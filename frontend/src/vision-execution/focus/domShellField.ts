/**
 * Discover plain <input>/<textarea> controls for shell-wide focus + voice insert.
 * Skips regions already handled by {@link TranscribableFieldRegion} (`data-atria-transcribe-region`).
 */

import type { EntityType, FieldKind, FocusDescriptor, FocusSurface } from './types'

const ALLOWED_INPUT_TYPES = new Set(['text', 'search', 'url', 'tel', 'email', ''])

export function isEligibleDomTextControl(
  el: EventTarget | null,
): el is HTMLInputElement | HTMLTextAreaElement {
  if (!(el instanceof HTMLTextAreaElement) && !(el instanceof HTMLInputElement)) return false
  if (el.disabled) return false
  if (el.closest('[data-atria-transcribe-off]')) return false
  if (el.closest('[data-atria-transcribe-region]')) return false
  if (el instanceof HTMLTextAreaElement) return !el.readOnly
  if (el.readOnly) return false
  const t = (el.getAttribute('type') ?? 'text').toLowerCase()
  return ALLOWED_INPUT_TYPES.has(t)
}

function randomDomId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `dom_${crypto.randomUUID()}`
  }
  return `dom_${Date.now()}_${Math.random().toString(36).slice(2, 12)}`
}

export function ensureDomFieldId(el: HTMLElement, map: WeakMap<HTMLElement, string>): string {
  let id = map.get(el)
  if (!id) {
    id = randomDomId()
    map.set(el, id)
  }
  return id
}

function parseSurface(raw: string | null | undefined): FocusSurface | undefined {
  if (!raw) return undefined
  if (
    raw === 'vision_execution' ||
    raw === 'vision_map' ||
    raw === 'core_profile' ||
    raw === 'workspace' ||
    raw === 'shell'
  ) {
    return raw
  }
  return undefined
}

function parseEntityType(raw: string | null | undefined): EntityType | undefined {
  if (!raw) return undefined
  const allowed: EntityType[] = [
    'idea',
    'initiative',
    'project',
    'task',
    'council',
    'core_profile',
    'app_field',
  ]
  return allowed.includes(raw as EntityType) ? (raw as EntityType) : undefined
}

function parseFieldKind(raw: string | null | undefined): FieldKind | undefined {
  if (!raw) return undefined
  const allowed: FieldKind[] = [
    'long_form_strategy',
    'dependencies_scope',
    'evaluation_narrative',
    'idea_body',
  ]
  return allowed.includes(raw as FieldKind) ? (raw as FieldKind) : undefined
}

/** Build a focus descriptor from a native control (optional `data-atria-*` overrides). */
export function domControlToFocusDescriptor(
  el: HTMLInputElement | HTMLTextAreaElement,
  stableEntityId: string,
): FocusDescriptor {
  const fieldKey =
    el.getAttribute('data-atria-field-key')?.trim() ||
    (el.name && el.name.trim()) ||
    (el.id && el.id.trim()) ||
    'text'
  const labelAttr = el.getAttribute('data-atria-field-label')?.trim()
  const aria = el.getAttribute('aria-label')?.trim()
  const ph = (el.getAttribute('placeholder') ?? '').trim()
  const fieldLabel = labelAttr || aria || (ph ? ph.slice(0, 80) : fieldKey)
  const fieldKind = parseFieldKind(el.getAttribute('data-atria-field-kind')) ?? 'idea_body'
  const entityType = parseEntityType(el.getAttribute('data-atria-entity-type')) ?? 'app_field'
  const entityId = el.getAttribute('data-atria-entity-id')?.trim() || stableEntityId
  const surface = parseSurface(el.getAttribute('data-atria-surface')) ?? 'shell'

  return {
    surface,
    entity_type: entityType,
    entity_id: entityId,
    field_key: fieldKey,
    field_label: fieldLabel,
    field_kind: fieldKind,
  }
}

/** Best-effort sync for React-controlled inputs. */
export function applyValueToTextControl(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
  setter?.call(el, value)
  el.dispatchEvent(new Event('input', { bubbles: true }))
}
