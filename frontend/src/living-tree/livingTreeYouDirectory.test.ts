// @vitest-environment jsdom
/**
 * YOU directory composition rules (YOU menu Section A): pure-function
 * tests for buildYouDirectory — no rendering.
 *
 * The directory is navigation only: a universal section (5 working
 * destinations + 2 info rows), then seven seat groups in the accepted
 * map's order, each with its distinctive rows; every group's scoped
 * strip (Today / Review / Upload through the seat) is structural and
 * never appears as rows. 46 working actions in total for an admin
 * (5 universal + 20 distinctive + 7 strips × 3 chips). No planned
 * doorway (Commitments, growth, takeout/delete, mirror, steward
 * verdicts, disputes, twigs, convened sessions) appears anywhere.
 */
import { describe, it, expect } from 'vitest'
import { buildYouDirectory, type YouDirectoryRow } from './LivingTree'

const NODE_MENU_ITEM_IDS = [
  'today',
  'talk',
  'review',
  'upload',
  'mint',
  'projects',
  'settings',
  'content',
]
const SHEET_NAV_VIEWS = [
  'vision_map',
  'vision_execution',
  'provenance',
  'perspectives',
  'agent_intake',
  'signal_review',
  'workspace',
  'campaign_board',
  'bench',
]

function allRows(isAdmin: boolean): YouDirectoryRow[] {
  const d = buildYouDirectory({ isAdmin })
  return [...d.universal, ...d.groups.flatMap((g) => g.rows)]
}

function titles(rows: YouDirectoryRow[]): string[] {
  return rows.map((r) => r.title)
}

describe('buildYouDirectory', () => {
  it('the universal section holds the five universal destinations and two info rows — no seat-group rows leak up', () => {
    const { universal } = buildYouDirectory({ isAdmin: true })
    expect(titles(universal)).toEqual([
      'Today',
      'Talk',
      'Review',
      'Upload source materials',
      'Settings',
      'Snapshot era',
      'Log in / out',
    ])
    const destinations = universal.filter((r) => r.kind === 'sheet' || r.kind === 'nav')
    expect(destinations).toHaveLength(5)
    expect(universal.filter((r) => r.kind === 'info')).toHaveLength(2)
    // Projects, Content, Foundation and Stats live in their seat
    // groups now — never in the universal section.
    for (const absent of ['Projects', 'Content', 'Foundation (actors)', 'Stats']) {
      expect(titles(universal)).not.toContain(absent)
    }
  })

  it('groups come in the accepted map order, each with its verb and at least two distinctive rows', () => {
    const { groups } = buildYouDirectory({ isAdmin: true })
    expect(groups.map((g) => g.seatKey)).toEqual([
      'mentor',
      'champion',
      'guardian',
      'maverick',
      'ambassador',
      'conductor',
      'skeptic',
    ])
    expect(groups.map((g) => g.verb)).toEqual([
      'Cultivate',
      'Act',
      'Protect',
      'Create',
      'Connect',
      'Organize',
      'Examine',
    ])
    for (const g of groups) {
      expect(g.rows.length).toBeGreaterThanOrEqual(2)
    }
  })

  it('distinctive rows sit in exactly one group each', () => {
    const { groups } = buildYouDirectory({ isAdmin: true })
    const homes = (title: string) =>
      groups.filter((g) => titles(g.rows).includes(title)).map((g) => g.seatKey)
    expect(homes('Projects')).toEqual(['champion'])
    expect(homes('Content')).toEqual(['conductor'])
    expect(homes('Foundation (actors)')).toEqual(['conductor'])
    expect(homes('Stats')).toEqual(['mentor'])
    expect(homes('Vision map')).toEqual(['mentor'])
    expect(homes('Provenance')).toEqual(['guardian'])
    expect(homes('Signal review')).toEqual(['skeptic'])
    expect(homes('Mint')).toEqual(['maverick'])
  })

  it('totals 46 working actions for an admin: 5 universal + 20 distinctive + 21 strip chips', () => {
    const { universal, groups } = buildYouDirectory({ isAdmin: true })
    const universalActions = universal.filter((r) => r.kind === 'sheet' || r.kind === 'nav').length
    const distinctive = groups.reduce((n, g) => n + g.rows.length, 0)
    expect(universalActions).toBe(5)
    expect(distinctive).toBe(20)
    expect(universalActions + distinctive + groups.length * 3).toBe(46)
  })

  it('the scoped strip never appears as distinctive rows', () => {
    const { groups } = buildYouDirectory({ isAdmin: true })
    for (const g of groups) {
      for (const row of g.rows) {
        if (row.kind === 'sheet') {
          expect(['today', 'review', 'upload']).not.toContain(row.id)
        }
      }
    }
  })

  it('the Mint row is the only scoped distinctive row, scoped to the maverick', () => {
    const scoped = allRows(true).filter((r) => r.kind === 'sheet' && r.scopeSeat !== undefined)
    expect(scoped).toHaveLength(1)
    expect(scoped[0]).toMatchObject({ kind: 'sheet', id: 'mint', scopeSeat: 'maverick' })
  })

  it('the Invites row is present iff isAdmin', () => {
    expect(titles(allRows(true))).toContain('Invites')
    expect(titles(allRows(false))).not.toContain('Invites')
    // Without the admin row the ambassador group keeps its fan-out row.
    const { groups } = buildYouDirectory({ isAdmin: false })
    const ambassador = groups.find((g) => g.seatKey === 'ambassador')
    expect(ambassador?.rows).toHaveLength(1)
    expect(titles(ambassador?.rows ?? [])).toEqual(['Council fan-out'])
  })

  it('no planned doorway appears anywhere in the directory', () => {
    const serialized = JSON.stringify(buildYouDirectory({ isAdmin: true })).toLowerCase()
    for (const planned of [
      'commitment',
      'growth',
      'takeout',
      'delete',
      'mirror',
      'steward',
      'dispute',
      'twig',
      'convened',
    ]) {
      expect(serialized).not.toContain(planned)
    }
  })

  it('every row points at a mechanism that exists: sheet ids and nav targets are valid', () => {
    for (const row of allRows(true)) {
      if (row.kind === 'sheet') {
        expect(NODE_MENU_ITEM_IDS).toContain(row.id)
      }
      if (row.kind === 'nav') {
        expect(SHEET_NAV_VIEWS).toContain(row.nav)
      }
    }
  })
})
