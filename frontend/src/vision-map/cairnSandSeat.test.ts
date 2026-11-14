// @vitest-environment jsdom
/**
 * Cairn grounding (founder, 2026-11-14 — closing his October verdict
 * on the cairn study, "perfect, except for the floating shadows"):
 *
 * - NO SHADOW: the blurred black ground ellipse CairnNode used to
 *   paint beneath every pile is gone — for project cairns and garden
 *   stacks alike (one renderer). Grounding is the sand alone now.
 * - SAND RAISED: the raked garden rings' plane is raised
 *   (gardenSandPlaneY) so the innermost groove's front arc tucks
 *   SAND_TUCK_PX behind the base stone's bottom (layout.groundY IS
 *   the slab's bottom) — the cairn reads as seated IN the sand.
 *   Before the raise, that arc sat a full ry (≈24px on the fixture
 *   pile) BELOW the stone's bottom, with the shadow in between.
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 */
import { describe, expect, it } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { ReactFlowProvider } from '@xyflow/react'
import { CairnNode, gardenSandPlaneY, SAND_TUCK_PX } from './CairnNode'
import { towerLayoutForMembers, type CairnMemberInput } from './cairnTower'
import type { MapNodePayload } from './ontology'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const payload = (over: Record<string, unknown>): MapNodePayload =>
  ({
    kind: 'cairn',
    label: 'Project One',
    growth: 'growing',
    condition: 'healthy',
    condition_severity: 0,
    ref: { veType: 'project', id: 'p1' },
    summaryLines: [],
    water_level: 'medium',
    fertilizer_pulse: false,
    ...over,
  }) as MapNodePayload

const MEMBERS: CairnMemberInput[] = [
  { id: 'branch-p1', kind: 'branch', activity: 0.6, createdAt: '2026-01-02T00:00:00.000Z', growth: 'growing', parent: true },
  { id: 'flower-t1', kind: 'flower', activity: 0.5, createdAt: '2026-01-03T00:00:00.000Z', growth: 'germinating' },
  { id: 'flower-t2', kind: 'flower', activity: 0.4, createdAt: '2026-01-04T00:00:00.000Z', growth: 'dormant' },
]

let container: HTMLDivElement
let root: Root

function renderCairn(id: string, data: MapNodePayload) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => {
    root.render(
      React.createElement(
        ReactFlowProvider,
        null,
        React.createElement(CairnNode, {
          id,
          data,
          selected: false,
          type: 'cairn',
          dragging: false,
          draggable: false,
          selectable: true,
          deletable: false,
          zIndex: 0,
          isConnectable: true,
          positionAbsoluteX: 0,
          positionAbsoluteY: 0,
        }),
      ),
    )
  })
}

function cleanup() {
  act(() => {
    root.unmount()
  })
  container.remove()
}

function expectSeatedInSand(id: string, members: CairnMemberInput[]) {
  // No blurred shadow svg, no black-filled ground ellipse anywhere.
  expect(container.querySelector('svg[style*="blur"]')).toBeNull()
  expect(container.querySelector('ellipse[fill="#000000"]')).toBeNull()
  // The rings are present, on the raised plane: the innermost dark
  // groove's front arc (cy + ry) lands SAND_TUCK_PX above the slab's
  // bottom (the layout's groundY) — tucked behind the stone.
  const layout = towerLayoutForMembers(id, members)
  const ringsSvg = container.querySelector('.cairn-garden-rings')
  expect(ringsSvg).not.toBeNull()
  const dark = ringsSvg!.querySelector('ellipse[stroke="#120b06"]')!
  const cy = parseFloat(dark.getAttribute('cy')!)
  const ry = parseFloat(dark.getAttribute('ry')!)
  expect(cy).toBeCloseTo(gardenSandPlaneY(layout.groundY, layout.footprintHalfWidth), 4)
  expect(cy + ry).toBeCloseTo(layout.groundY - SAND_TUCK_PX, 4)
}

describe('cairn grounding — no shadow, sand raised to the stone (founder, 2026-11-14)', () => {
  it('project pile: no drop shadow; the sand tucks behind the base stone’s bottom', () => {
    renderCairn(
      'cairn-p1',
      payload({ cairnCount: 3, cairnPreview: [], cairnMembers: MEMBERS }),
    )
    expectSeatedInSand('cairn-p1', MEMBERS)
    cleanup()
  })

  it('garden stack: the same law — no drop shadow; the sand tucks behind the base stone’s bottom', () => {
    const stackMembers: CairnMemberInput[] = [
      { id: 'init-1', kind: 'tree', activity: 0.7, createdAt: '2026-01-01T00:00:00.000Z', growth: 'growing', parent: true },
      ...MEMBERS.map((m) => ({ ...m, parent: m.id === 'branch-p1' ? false : undefined })),
    ]
    renderCairn(
      'init-1',
      payload({
        label: 'Initiative One',
        gardenStack: true,
        cairnProjectId: null,
        cairnCount: 4,
        cairnPreview: [],
        cairnMembers: stackMembers,
        ref: { veType: 'initiative', id: 'i1' },
      }),
    )
    expectSeatedInSand('init-1', stackMembers)
    cleanup()
  })
})
