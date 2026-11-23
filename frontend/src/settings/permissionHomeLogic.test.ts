import { describe, expect, it } from 'vitest'
import type {
  PermissionHomeControl,
  PermissionHomeGroup,
  PermissionHomeState,
  PermissionHomeWriteReport,
} from './api'
import {
  FLAG_COPY,
  alwaysAsksText,
  controlLabel,
  flagCopy,
  intentOrder,
  repairFor,
  stateLabel,
  syncText,
} from './permissionHomeLogic'

function flagControl(key: string, on = false): PermissionHomeControl {
  return {
    id: `flag:${key}`,
    kind: 'flag',
    key,
    capability: null,
    row_key: null,
    label: null,
    covers: null,
    does_not_allow: null,
    state: on ? 'on' : 'off',
    display_state: on ? 'on' : 'off',
    value: on,
    stance: null,
    stance_source: null,
    supported_stances: [],
    critical: true,
    wording_pending: false,
  }
}

function group(partial: Partial<PermissionHomeGroup>): PermissionHomeGroup {
  return {
    id: 'story',
    state: 'off',
    sync: 'in_sync',
    writable_states: ['on', 'off'],
    has_rows: true,
    controls: [],
    diagnostics: null,
    ...partial,
  }
}

function writeReport(partial: Partial<PermissionHomeWriteReport>): PermissionHomeWriteReport {
  return {
    group: 'story',
    declared_target: 'on',
    read_back_state: 'custom',
    sync: 'out_of_sync',
    complete: false,
    revocation: null,
    still_on: [],
    failed_controls: [],
    repair: { group: 'story', state: 'on' },
    controls: [],
    ...partial,
  }
}

describe('flag copy', () => {
  it('carries the ten legacy rows plus the ruled fellowship wording', () => {
    expect(Object.keys(FLAG_COPY).sort()).toEqual(
      [
        'analytics_product_improvement',
        'aspiration_infer_suggestions',
        'aspiration_store_explicit',
        'aspiration_use_in_guidance',
        'behavioral_tracking',
        'fellowship_derivation',
        'interaction_pattern_storage',
        'personalization',
        'profile_learning',
        'steward_coordination',
        'steward_derivation',
      ].sort(),
    )
    expect(flagCopy(flagControl('personalization'))?.label).toContain(
      'Personalization',
    )
  })

  it('carries the founder-ruled fellowship wording verbatim (2026-11-22)', () => {
    const copy = flagCopy(flagControl('fellowship_derivation'))
    expect(copy?.label).toBe('Cross-conversation noticing')
    expect(copy?.hint).toBe(
      'Allow Zenaf to look across your conversations for things a seat would want to raise — each observation tied to the words it came from. You decide whether any of it matters.',
    )
    expect(controlLabel(flagControl('fellowship_derivation'))).toBe(
      'Cross-conversation noticing',
    )
    expect(controlLabel(flagControl('steward_derivation'))).toBe(
      'Narrative Steward derivation',
    )
  })
})

describe('state labels', () => {
  it('maps the four display states', () => {
    expect(stateLabel('on')).toBe('On')
    expect(stateLabel('off')).toBe('Off')
    expect(stateLabel('ask_me')).toBe('Ask me')
    expect(stateLabel('custom')).toBe('Custom')
  })
})

describe('sync text — the two Custom states stay distinct', () => {
  it('a mixed read with no write report is your granularity', () => {
    const g = group({ state: 'custom', sync: 'granularity' })
    expect(syncText(g, null)).toContain('your granularity')
    expect(repairFor(g, null)).toBeNull()
  })

  it('a failed opt-in is out of sync, names the control, offers repair', () => {
    const g = group({ state: 'custom' })
    const report = writeReport({
      failed_controls: ['flag:steward_derivation'],
      controls: [flagControl('steward_derivation')],
    })
    const text = syncText(g, report)
    expect(text).toContain('Out of sync')
    expect(text).toContain('Narrative Steward derivation')
    expect(repairFor(g, report)).toEqual({ group: 'story', state: 'on' })
  })

  it('an incomplete revocation is never phrased as turned off', () => {
    const g = group({ state: 'custom' })
    const report = writeReport({
      declared_target: 'off',
      revocation: 'incomplete',
      still_on: ['flag:steward_derivation'],
      failed_controls: ['flag:steward_derivation'],
      repair: { group: 'story', state: 'off' },
      controls: [flagControl('steward_derivation', true)],
    })
    const text = syncText(g, report)
    expect(text).toContain('incomplete revocation')
    expect(text).toContain('Still on')
    expect(text).not.toContain('turned off —')
  })

  it('a write report for another group does not leak', () => {
    const g = group({ id: 'connect', state: 'custom' })
    const report = writeReport({ group: 'story' })
    expect(syncText(g, report)).toContain('your granularity')
    expect(repairFor(g, report)).toBeNull()
  })

  it('a uniform group has no sync line', () => {
    expect(syncText(group({ state: 'on' }), null)).toBeNull()
  })
})

describe('intent order and always-asks', () => {
  it('orders the four intents as designed', () => {
    const state = {
      intents: [
        { id: 'suggest', groups: [], granular: [] },
        { id: 'remember', groups: [], granular: [] },
        { id: 'follow_through', groups: [], granular: [] },
        { id: 'connect', groups: [], granular: [] },
      ],
    } as unknown as PermissionHomeState
    expect(intentOrder(state)).toEqual([
      'remember',
      'connect',
      'suggest',
      'follow_through',
    ])
  })

  it('renders known always-asks classes and falls back plainly', () => {
    expect(alwaysAsksText('train')).toContain('per claim')
    expect(alwaysAsksText('spend')).toContain('always asks')
    expect(alwaysAsksText('mystery')).toBe('mystery — always asks.')
  })
})
