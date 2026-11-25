/**
 * Severine's Bench — the production surface.
 *
 * Tapping Severine lands here (founder, 2026-11-24): her world on
 * the left, her conversation on the right, in the shared SplitShell.
 * The world opens on the Shelf (§0 of the definitions): every root
 * in the user's Vision Execution record as a potted bonsai, grown —
 * not drawn — by the canonical growth grammar (growth.ts, proven
 * against growth_demo3.py), captioned with its true kind. Tapping a
 * tree brings it to the Bench at working size. The grammar is the
 * founder's (corrected 2026-11-24): a tree is an initiative, its
 * branches are the initiative's projects, and tasks branch off as
 * TWIGS (a project standing as its own tree carries its tasks as
 * twigs off the trunk). Wire is a recorded proposal awaiting a
 * verdict, in the proposing seat's colour, coiled on the record it
 * hangs on; jin is dropped material kept visible; foliage appears
 * ONLY where the record evidences another seat's material on the
 * task — on twigs, because both sources live at the task level —
 * in that seat's colour: the task's origin provenance (the
 * discussion it came out of), and, fetched when a tree is opened,
 * the seats whose steward readings name the task in their
 * evidence, under the pencil layer's gates; the footing triangle
 * is sized by the record's prose and opens the notebook.
 *
 * Verdicts take the existing governed path — the same approve /
 * decline proposal endpoints the chat proposal cards use. The Bench
 * invents no store: what it cannot reach, it does not draw.
 *
 * Governing definitions:
 * zenaf-bench-feature-visual-language-definitions-2026-11-21.md.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CouncilChat from '../chat/CouncilChat'
import SplitShell from '../components/SplitShell'
import { trunkPoint, PARAMS, type Pt } from './growth'
import { hexToRgb, type SceneModel } from './paint'
import BenchCanvas, { ShelfCanvas } from './BenchCanvas'
import { approveProposal, declineProposal, fetchBenchEntities, fetchBenchFoliage, fetchPendingProposals } from './benchApi'
import {
  buildIdeaTree,
  buildInitiativeTree,
  buildLooseTaskTree,
  buildProjectTree,
  buildShelf,
  NO_FOLIAGE,
  SEAT_COLOUR_BY_ARCHETYPE,
  SEAT_NAME_BY_ARCHETYPE,
  verdictLogEntry,
  type BenchBranch,
  type BenchEntities,
  type BenchProposal,
  type BenchTreeModel,
  type BenchTwig,
  type FoliageByTask,
  type RootKind,
  type ShelfItem,
  type VerdictLogEntry,
} from './benchLogic'

const NO_PROPOSALS = new Map<string, BenchProposal[]>()

function buildModelFor(
  kind: RootKind,
  id: string,
  entities: BenchEntities,
  proposalsByParent: ReadonlyMap<string, BenchProposal[]>,
  foliageByTask: FoliageByTask = NO_FOLIAGE,
): BenchTreeModel | null {
  if (kind === 'project') {
    const p = entities.projects.find((x) => x.id === id)
    return p ? buildProjectTree(p, entities, proposalsByParent, foliageByTask) : null
  }
  if (kind === 'initiative') {
    const i = entities.initiatives.find((x) => x.id === id)
    return i ? buildInitiativeTree(i, entities, proposalsByParent, foliageByTask) : null
  }
  if (kind === 'idea') {
    const i = entities.ideas.find((x) => x.id === id)
    return i ? buildIdeaTree(i, entities) : null
  }
  const t = entities.tasks.find((x) => x.id === id)
  return t ? buildLooseTaskTree(t, foliageByTask) : null
}

/** §9: strand weight IS thickness — the painted width the weight
 *  deals (1 = a twig, 10 = trunk thickness), as a scale over the
 *  grammar's register width. One deal for branches and twigs. */
function widthScaleFor(rec: { weight: number; geometryRegister: BenchBranch['geometryRegister'] }): number {
  const target = 1.1 + ((rec.weight - 1) / 9) * 9.4
  return target / PARAMS.woodW[rec.geometryRegister]
}

/** The grown path a record paints along: a branch's primary, or a
 *  twig's own path. */
function pathFor(tree: BenchTreeModel, id: string): Pt[] | undefined {
  return (
    tree.grown.primaries.get(id) ??
    tree.grown.recordTwigs.find((r) => r.handle === id)?.pts
  )
}

function sceneModelFor(
  tree: BenchTreeModel,
  opts: { showExploratory: boolean; selectedId: string | null; shelf: boolean },
): SceneModel {
  const branches = tree.branches.map((b) => {
    const live = b.proposals[0]
    return {
      id: b.id,
      jin: b.jin,
      widthScale: widthScaleFor(b),
      wireSeatColour:
        !opts.shelf && live ? hexToRgb(SEAT_COLOUR_BY_ARCHETYPE[live.seat] ?? '#b47333') : null,
    }
  })
  const twigs = tree.twigs.map((t) => {
    const live = t.proposals[0]
    return {
      id: t.id,
      jin: t.jin,
      widthScale: widthScaleFor(t),
      wireSeatColour:
        !opts.shelf && live ? hexToRgb(SEAT_COLOUR_BY_ARCHETYPE[live.seat] ?? '#b47333') : null,
    }
  })
  let pencil: SceneModel['pencil'] = null
  if (!opts.shelf) {
    const records: Array<{ id: string; state: string }> = [...tree.branches, ...tree.twigs]
    const considered =
      records.find((b) => b.id === opts.selectedId) ??
      records.find((b) => b.state === 'Todo' || b.state === 'Open') ??
      records[0]
    if (considered) {
      const start = trunkPoint(0.9).point
      const path = pathFor(tree, considered.id)
      const tip = path ? path[path.length - 1] : undefined
      if (tip) {
        const dx = tip[0] - start[0]
        const dy = tip[1] - start[1]
        const L = Math.hypot(dx, dy) || 1
        pencil = { start, u: [dx / L, dy / L] as Pt, length: 96 }
      }
    }
  }
  return {
    grown: tree.grown,
    register: tree.register,
    elementsByHandle: tree.elementsByHandle,
    discussion: tree.discussion,
    branches,
    twigs,
    footing: tree.footing,
    showExploratory: opts.showExploratory,
    selectedId: opts.selectedId,
    pencil,
  }
}

export default function BenchView() {
  const [entities, setEntities] = useState<BenchEntities | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [openRoot, setOpenRoot] = useState<{ kind: RootKind; id: string } | null>(null)
  const [proposalsByParent, setProposalsByParent] = useState<Map<string, BenchProposal[]>>(new Map())
  const [foliageByRoot, setFoliageByRoot] = useState<Map<string, FoliageByTask>>(new Map())
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null)
  const [showExploratory, setShowExploratory] = useState(true)
  const [notebookOpen, setNotebookOpen] = useState(false)
  const [openedWire, setOpenedWire] = useState<{ branchId: string; proposal: BenchProposal } | null>(null)
  const [verdictLog, setVerdictLog] = useState<VerdictLogEntry[]>([])
  const [logOpen, setLogOpen] = useState(false)
  const [verdictBusy, setVerdictBusy] = useState(false)
  const [verdictError, setVerdictError] = useState<string | null>(null)
  const [decidedWireIds, setDecidedWireIds] = useState<ReadonlySet<string>>(new Set())
  const loadSeq = useRef(0)

  const load = useCallback(async () => {
    const seq = ++loadSeq.current
    try {
      const data = await fetchBenchEntities()
      if (loadSeq.current !== seq) return
      setEntities(data)
      setLoadError(null)
    } catch {
      if (loadSeq.current !== seq) return
      setLoadError('The bench could not be set out — the record did not answer.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const shelf = useMemo(() => (entities ? buildShelf(entities) : []), [entities])
  const shelfTrees = useMemo(() => {
    if (!entities) return []
    return shelf
      .map((item) => ({ item, model: buildModelFor(item.kind, item.id, entities, NO_PROPOSALS) }))
      .filter((x): x is { item: ShelfItem; model: BenchTreeModel } => x.model !== null)
  }, [entities, shelf])

  const tree = useMemo(() => {
    if (!entities || !openRoot) return null
    const model = buildModelFor(
      openRoot.kind,
      openRoot.id,
      entities,
      proposalsByParent,
      foliageByRoot.get(`${openRoot.kind}:${openRoot.id}`) ?? NO_FOLIAGE,
    )
    if (!model) return null
    // Wires decided this session stay off the tree even before the
    // refetch lands (the durable record is the proposal row itself).
    const filteredBranches = model.branches.map((b) => ({
      ...b,
      proposals: b.proposals.filter((p) => !decidedWireIds.has(p.id)),
    }))
    const filteredTwigs = model.twigs.map((t) => ({
      ...t,
      proposals: t.proposals.filter((p) => !decidedWireIds.has(p.id)),
    }))
    return { ...model, branches: filteredBranches, twigs: filteredTwigs }
  }, [entities, openRoot, proposalsByParent, decidedWireIds, foliageByRoot])

  const openTree = useCallback(
    async (kind: RootKind, id: string) => {
      setOpenRoot({ kind, id })
      setSelectedBranchId(null)
      setOpenedWire(null)
      setNotebookOpen(false)
      if (!entities) return
      // Reading foliage (§7's second source) hangs on tasks too:
      // fetch it for the opened root alongside the wire. The read
      // is fail-closed — a closed steward gate arrives as an empty
      // map and the tree renders provenance foliage only.
      if (kind === 'initiative' || kind === 'project' || kind === 'task') {
        const foliage = await fetchBenchFoliage(kind, id)
        setFoliageByRoot((prev) => new Map(prev).set(`${kind}:${id}`, foliage))
      }
      // Wire hangs on tasks (twigs): fetch pending proposals for
      // every twig the opened tree will carry — a project's own
      // tasks, or every project's tasks under an initiative.
      let twigTasks: typeof entities.tasks = []
      if (kind === 'project') {
        twigTasks = entities.tasks.filter((t) => t.project_id === id && !t.parent_task_id)
      } else if (kind === 'initiative') {
        const projectIds = new Set(
          entities.projects.filter((p) => p.initiative_id === id).map((p) => p.id),
        )
        twigTasks = entities.tasks.filter(
          (t) => t.project_id !== null && projectIds.has(t.project_id) && !t.parent_task_id,
        )
      } else {
        return
      }
      const entries = await Promise.all(
        twigTasks.map(async (t) => [t.id, await fetchPendingProposals(t.id)] as const),
      )
      setProposalsByParent((prev) => {
        const next = new Map(prev)
        for (const [k, v] of entries) next.set(k, v)
        return next
      })
    },
    [entities],
  )

  const selectedBranch = tree?.branches.find((b) => b.id === selectedBranchId) ?? null
  const selectedTwig = tree?.twigs.find((t) => t.id === selectedBranchId) ?? null

  const applyVerdict = useCallback(
    async (kind: 'stand' | 'cut') => {
      if (!openedWire || !tree || verdictBusy) return
      const { branchId, proposal } = openedWire
      const branch =
        tree.branches.find((b) => b.id === branchId) ??
        tree.twigs.find((t) => t.id === branchId)
      setVerdictBusy(true)
      setVerdictError(null)
      try {
        if (kind === 'stand') await approveProposal(proposal.id)
        else await declineProposal(proposal.id)
        setDecidedWireIds((prev) => new Set(prev).add(proposal.id))
        setVerdictLog((prev) => [
          ...prev,
          verdictLogEntry({
            proposal,
            branchName: branch?.name ?? branchId,
            rootTitle: tree.title,
            kind,
            when: new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) + ', this session',
          }),
        ])
        setOpenedWire(null)
        // The record changed (stand creates the task): re-read it.
        await load()
        const fresh = await fetchPendingProposals(branchId)
        setProposalsByParent((prev) => new Map(prev).set(branchId, fresh))
      } catch {
        setVerdictError('The verdict did not reach the record. The coil stays where it was.')
      } finally {
        setVerdictBusy(false)
      }
    },
    [openedWire, tree, verdictBusy, load, openRoot],
  )

  /* ------------------------------ chat ------------------------------ */

  const conversationId = openRoot
    ? `bench:${openRoot.kind}:${openRoot.id}`
    : 'bench:shelf'
  const chatContext: Record<string, unknown> = openRoot
    ? {
        sheet_type: 'bench',
        entity_type: selectedTwig
          ? 'task'
          : selectedBranch?.task
            ? 'task'
            : openRoot.kind,
        entity_id: selectedTwig?.id ?? selectedBranch?.id ?? openRoot.id,
      }
    : { sheet_type: 'bench' }

  /* ------------------------------ render ---------------------------- */

  if (loadError) {
    return (
      <div className="flex-1 p-6">
        <p className="text-sm text-red-300">{loadError}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-3 min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold"
        >
          Try again
        </button>
      </div>
    )
  }
  if (!entities) {
    return (
      <div className="flex-1 p-6">
        <p className="text-sm text-stone-400">Setting out the bench…</p>
      </div>
    )
  }

  const benchScene = tree
    ? sceneModelFor(tree, { showExploratory, selectedId: selectedBranchId, shelf: false })
    : null
  const branchNames = new Map(
    [...(tree?.branches ?? []), ...(tree?.twigs ?? [])].map((b) => [b.id, b.name]),
  )

  const world = (
    <div className="p-3 lg:p-5 space-y-3">
      {!openRoot || !tree || !benchScene ? (
        <Shelf
          trees={shelfTrees}
          onOpen={(kind, id) => void openTree(kind, id)}
        />
      ) : (
        <section aria-label={`The Bench — ${tree.title}`}>
          <div className="flex items-center gap-2.5 flex-wrap mb-2">
            <button
              type="button"
              onClick={() => {
                setOpenRoot(null)
                setSelectedBranchId(null)
                setOpenedWire(null)
              }}
              className="min-h-[36px] px-3.5 rounded-full border border-stone-700/60 bg-stone-900/70 text-stone-200 text-sm"
            >
              ← Shelf
            </button>
            <h1 className="text-lg font-semibold text-stone-100 m-0">{tree.title}</h1>
            <span className="text-xs px-2.5 py-1 rounded-full border border-stone-700/60 text-stone-400">
              {tree.state} · {tree.rootKind}
            </span>
          </div>
          <div className="rounded-2xl overflow-hidden border border-[#9a7b24]/50 shadow-lg bg-[#f3ecd9] p-2">
            <BenchCanvas
              model={benchScene}
              branchNames={branchNames}
              selectedId={selectedBranchId}
              onSelectBranch={(id) => {
                setSelectedBranchId(id)
                setOpenedWire(null)
              }}
              onSelectTwig={(id) => {
                setSelectedBranchId(id)
                setOpenedWire(null)
              }}
              onTapWire={(id) => {
                setSelectedBranchId(id)
                const rec =
                  tree.branches.find((b) => b.id === id) ??
                  tree.twigs.find((t) => t.id === id)
                const proposal = rec?.proposals[0]
                if (proposal) setOpenedWire({ branchId: id, proposal })
              }}
              onTapFooting={() => setNotebookOpen(true)}
              onTapPencil={() => {
                const records = [...tree.branches, ...tree.twigs]
                const considered =
                  records.find((b) => b.state === 'Todo' || b.state === 'Open') ?? records[0]
                if (considered) setSelectedBranchId(considered.id)
              }}
            />
            <div className="flex gap-2 flex-wrap px-1 py-2">
              <button
                type="button"
                aria-pressed={showExploratory}
                onClick={() => setShowExploratory((v) => !v)}
                className={`min-h-[36px] px-3.5 rounded-full border border-stone-400/50 bg-[#fffaf0] text-stone-800 text-sm ${showExploratory ? '' : 'opacity-55'}`}
              >
                Show what's being considered
              </button>
              <button
                type="button"
                onClick={() => setLogOpen((v) => !v)}
                className="min-h-[36px] px-3.5 rounded-full border border-stone-400/50 bg-[#fffaf0] text-stone-800 text-sm"
              >
                Verdict log
              </button>
            </div>
            {logOpen && (
              <div className="border-t border-dashed border-stone-400/50 px-2 py-2 text-stone-800">
                <h3 className="text-xs uppercase tracking-widest text-stone-500 m-0 mb-1.5">Verdict log</h3>
                {verdictLog.length === 0 ? (
                  <p className="text-sm text-stone-500 m-0">No verdicts yet this session.</p>
                ) : (
                  <ul className="m-0 pl-4 text-sm space-y-1">
                    {verdictLog.map((v, i) => (
                      <li key={i}>
                        {v.text} <span className="text-stone-500">· {v.when}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <div className="border-t border-dashed border-stone-400/50 px-1 pt-2">
              <h3 className="text-xs uppercase tracking-widest text-stone-500 m-0 mb-1 px-1">On this tree</h3>
              {(() => {
                const dotFor = (rec: {
                  jin: boolean
                  proposals: BenchProposal[]
                  foliageSeats: Array<{ seatId: string }>
                }) =>
                  rec.jin
                    ? '#ddd2b2'
                    : rec.proposals[0]
                      ? (SEAT_COLOUR_BY_ARCHETYPE[rec.proposals[0].seat] ?? '#b47333')
                      : rec.foliageSeats[0]
                        ? (SEAT_COLOUR_BY_ARCHETYPE[rec.foliageSeats[0].seatId] ?? '#7a5638')
                        : '#7a5638'
                const branchRow = (b: BenchBranch) => (
                  <button
                    key={b.id}
                    type="button"
                    data-branch-row={b.id}
                    data-foliage-seat={b.foliageSeats.map((s) => s.seatId).join(',')}
                    onClick={() => {
                      setSelectedBranchId(b.id)
                      setOpenedWire(null)
                    }}
                    className={`flex w-full items-baseline gap-2 text-left px-1.5 py-2 border-b border-stone-400/30 text-stone-800 ${selectedBranchId === b.id ? 'bg-[#efe6cd]' : ''}`}
                  >
                    <span
                      className="w-2.5 h-2.5 rounded-full shrink-0 relative top-px"
                      style={{ background: dotFor(b) }}
                    />
                    <span className="flex-1 text-sm">{b.name}</span>
                    <span className="text-xs text-stone-500">{b.state}</span>
                  </button>
                )
                const twigRow = (t: BenchTwig) => (
                  <button
                    key={t.id}
                    type="button"
                    data-twig-row={t.id}
                    data-foliage-seat={t.foliageSeats.map((s) => s.seatId).join(',')}
                    onClick={() => {
                      setSelectedBranchId(t.id)
                      setOpenedWire(null)
                    }}
                    className={`flex w-full items-baseline gap-2 text-left pl-6 pr-1.5 py-1.5 border-b border-stone-400/20 text-stone-700 ${selectedBranchId === t.id ? 'bg-[#efe6cd]' : ''}`}
                  >
                    <span
                      className="w-2 h-2 rounded-full shrink-0 relative top-px"
                      style={{ background: dotFor(t) }}
                    />
                    <span className="flex-1 text-[0.83rem]">{t.name}</span>
                    <span className="text-xs text-stone-500">{t.state}</span>
                  </button>
                )
                return (
                  <>
                    {tree.branches.map((b) => (
                      <div key={b.id}>
                        {branchRow(b)}
                        {tree.twigs.filter((t) => t.parentId === b.id).map(twigRow)}
                      </div>
                    ))}
                    {tree.twigs.filter((t) => t.parentId === null).map(twigRow)}
                  </>
                )
              })()}
              {selectedBranch && (
                <BranchDetail
                  branch={selectedBranch}
                  onOpenWire={() => {
                    const proposal = selectedBranch.proposals[0]
                    if (proposal) setOpenedWire({ branchId: selectedBranch.id, proposal })
                  }}
                  onBringToBench={
                    selectedBranch.sourceKind === 'project'
                      ? () => void openTree('project', selectedBranch.id)
                      : undefined
                  }
                />
              )}
              {selectedTwig && (
                <TwigDetail
                  twig={selectedTwig}
                  onOpenWire={() => {
                    const proposal = selectedTwig.proposals[0]
                    if (proposal) setOpenedWire({ branchId: selectedTwig.id, proposal })
                  }}
                />
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  )

  const conversation = (
    <div className="p-3 space-y-3">
      {openedWire && tree && (
        <ProposalCard
          proposal={openedWire.proposal}
          branchName={
            tree.branches.find((b) => b.id === openedWire.branchId)?.name ??
            tree.twigs.find((t) => t.id === openedWire.branchId)?.name ??
            ''
          }
          busy={verdictBusy}
          error={verdictError}
          onStand={() => void applyVerdict('stand')}
          onCut={() => void applyVerdict('cut')}
          onClose={() => setOpenedWire(null)}
        />
      )}
      <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 p-2">
        <CouncilChat
          key={conversationId}
          environment="workspace"
          initialArchetypeId="skeptic"
          conversationId={conversationId}
          context={chatContext}
        />
      </div>
    </div>
  )

  return (
    <>
      <SplitShell left={world} right={conversation} storageKey="bench" />
      {notebookOpen && tree && (
        <NotebookOverlay tree={tree} onClose={() => setNotebookOpen(false)} />
      )}
    </>
  )
}

/* ================================================================== */
/* Shelf                                                               */
/* ================================================================== */

function Shelf({
  trees,
  onOpen,
}: {
  trees: Array<{ item: ShelfItem; model: BenchTreeModel }>
  onOpen: (kind: RootKind, id: string) => void
}) {
  const rows: Array<Array<{ item: ShelfItem; model: BenchTreeModel }>> = []
  for (let i = 0; i < trees.length; i += 3) rows.push(trees.slice(i, i + 3))
  return (
    <section aria-label="The Shelf">
      <div className="flex items-baseline justify-between gap-3 flex-wrap px-1 mb-1.5">
        <h1 className="text-lg font-semibold text-stone-100 m-0">The Shelf</h1>
        <p className="text-sm text-stone-400 m-0">Tap a tree to bring it to the bench.</p>
      </div>
      <div className="rounded-2xl border border-stone-700/60 p-3 space-y-3" style={{ background: 'linear-gradient(180deg,#efe6cd,#f7f1de 72%)' }}>
        {trees.length === 0 && (
          <p className="text-sm text-stone-600 m-0 px-1 py-2">The shelf is empty — no projects, initiatives, ideas or loose tasks in the record yet.</p>
        )}
        {rows.map((row, ri) => (
          <div key={ri}>
            <div className="grid grid-cols-3 gap-0 items-start">
              {row.map(({ item, model }) => (
                <button
                  key={item.id}
                  type="button"
                  data-shelf-item={item.id}
                  data-register={item.register}
                  aria-label={`Bring ${item.title} to the bench`}
                  onClick={() => onOpen(item.kind, item.id)}
                  className="bg-transparent border-0 p-1 cursor-pointer h-[150px] sm:h-[178px]"
                >
                  <ShelfCanvas
                    model={sceneModelFor(model, { showExploratory: false, selectedId: null, shelf: true })}
                    label={item.title}
                  />
                </button>
              ))}
            </div>
            <div
              aria-hidden="true"
              className="h-[15px] rounded-sm relative z-[2]"
              style={{
                background: 'linear-gradient(180deg,#a07c50 0 4px,#8a6a44 4px,#6e5233 100%)',
                boxShadow: '0 4px 6px rgba(60,40,10,.30), inset 0 1px 0 rgba(255,255,255,.35)',
              }}
            />
            <div className="grid grid-cols-3 gap-0 items-start">
              {row.map(({ item }) => (
                <button
                  key={item.id}
                  type="button"
                  aria-label={`Bring ${item.title} to the bench`}
                  onClick={() => onOpen(item.kind, item.id)}
                  className="bg-transparent border-0 px-1.5 pt-0 pb-1 cursor-pointer text-[#26241f]"
                >
                  <span className="block text-center text-[0.86rem] leading-tight pt-[7px] min-h-[2.3em]" style={{ fontFamily: 'Georgia, "Iowan Old Style", "Times New Roman", serif' }}>
                    {item.title}
                  </span>
                  <span className="block text-center text-[0.66rem] tracking-[0.14em] uppercase text-[#6f6350] pb-[3px]">
                    {item.kindLabel}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}
        <div className="mx-1.5 mt-1 h-11 rounded-lg border border-[#d8cba6] flex items-center justify-center text-[#5a5344] text-[0.82rem] tracking-[0.14em] uppercase" style={{ background: 'repeating-linear-gradient(0deg, rgba(120,95,50,.14) 0 3px, transparent 3px 7px), #efe6cd' }}>
          The bench
        </div>
      </div>
    </section>
  )
}

/* ================================================================== */
/* Branch inspection (§6/§8: provenance lives on inspection)           */
/* ================================================================== */

function BranchDetail({
  branch,
  onOpenWire,
  onBringToBench,
}: {
  branch: BenchBranch
  onOpenWire: () => void
  /** When the branch IS a project (a branch of its initiative's
   *  tree), the door that brings the BRANCH forward: the branch at
   *  working size, its twigs on it — the same branch nearer, not a
   *  separate tree. The shelf holds parents + loose only, so this
   *  is how an initiative's project fills the bench. */
  onBringToBench?: () => void
}) {
  const lines: string[] = []
  lines.push(`“${branch.name}” — ${branch.state.toLowerCase()} in the record.`)
  if (branch.sourceKind === 'project') {
    if (branch.subtaskCount > 0) {
      lines.push(
        `Its ${branch.subtaskCount === 1 ? 'task stands' : 'tasks stand'} as ${branch.subtaskCount === 1 ? 'a twig' : 'twigs'} on this branch — ${branch.subtaskCount} ${branch.subtaskCount === 1 ? 'twig' : 'twigs'} in the list above.`,
      )
    }
  } else if (branch.subtaskCount > 0) {
    lines.push(`${branch.subtaskCount} nested ${branch.subtaskCount === 1 ? 'task' : 'tasks'} under it.`)
  }
  if (branch.jin) {
    lines.push('It stands pale — deadwood kept in the tree’s shape, not tidied away.')
  }
  if (branch.sourceKind !== 'project') {
    // Foliage language belongs to tasks; a project branch's tasks
    // carry it on their twigs, so the branch itself says nothing.
    if (branch.foliageSeats.length) {
      for (const seat of branch.foliageSeats) {
        lines.push(
          seat.source === 'provenance'
            ? `It carries foliage in ${seat.seatName}’s colour, because it was discussed with ${seat.seatName} — the task came out of that recorded conversation.`
            : `It carries foliage in ${seat.seatName}’s colour — a steward reading in ${seat.seatName}’s voice names this task in its evidence.`,
        )
      }
    } else if (!branch.jin) {
      lines.push('It is bare — so far it has only been examined here, with Severine.')
    }
  }
  if (onBringToBench) {
    lines.push('Brought forward, this branch fills the bench at working size — branch and twigs together.')
  }
  return (
    <div className="px-1.5 py-2 text-sm text-stone-700 space-y-1.5" data-branch-detail={branch.id}>
      <p className="m-0">{lines.join(' ')}</p>
      <p className="m-0 text-xs text-stone-500">
        Strand weight {branch.weight} — {branch.weightRule}. Growth: {branch.geometryRule}.
      </p>
      {branch.proposals.length > 0 && (
        <button
          type="button"
          onClick={onOpenWire}
          className="min-h-[36px] px-3.5 rounded-full border border-[#7c4a21] text-[#7c4a21] text-sm bg-transparent"
        >
          Open the proposal on this branch
        </button>
      )}
      {onBringToBench && (
        <button
          type="button"
          onClick={onBringToBench}
          className="min-h-[36px] px-3.5 rounded-full border border-[#7c4a21] text-[#7c4a21] text-sm bg-transparent"
        >
          Bring this branch forward
        </button>
      )}
    </div>
  )
}

/* ================================================================== */
/* Twig inspection — a task on its branch (or on the trunk)            */
/* ================================================================== */

function TwigDetail({
  twig,
  onOpenWire,
}: {
  twig: BenchTwig
  onOpenWire: () => void
}) {
  const lines: string[] = []
  lines.push(`“${twig.name}” — a twig, ${twig.state.toLowerCase()} in the record.`)
  if (twig.subtaskCount > 0) {
    lines.push(
      `${twig.subtaskCount} nested ${twig.subtaskCount === 1 ? 'task' : 'tasks'} under it, carried in its weight — the growth grammar grows no finer level to draw them on.`,
    )
  }
  if (twig.jin) {
    lines.push('It stands pale — deadwood kept in the tree’s shape, not tidied away.')
  }
  if (twig.foliageSeats.length) {
    for (const seat of twig.foliageSeats) {
      lines.push(
        seat.source === 'provenance'
          ? `It carries foliage in ${seat.seatName}’s colour, because it was discussed with ${seat.seatName} — the task came out of that recorded conversation.`
          : `It carries foliage in ${seat.seatName}’s colour — a steward reading in ${seat.seatName}’s voice names this task in its evidence.`,
      )
    }
  } else if (!twig.jin) {
    lines.push('It is bare — so far it has only been examined here, with Severine.')
  }
  return (
    <div className="px-1.5 py-2 text-sm text-stone-700 space-y-1.5" data-twig-detail={twig.id}>
      <p className="m-0">{lines.join(' ')}</p>
      <p className="m-0 text-xs text-stone-500">
        Strand weight {twig.weight} — {twig.weightRule}. Growth: {twig.geometryRule}.
      </p>
      {twig.proposals.length > 0 && (
        <button
          type="button"
          onClick={onOpenWire}
          className="min-h-[36px] px-3.5 rounded-full border border-[#7c4a21] text-[#7c4a21] text-sm bg-transparent"
        >
          Open the proposal on this twig
        </button>
      )}
    </div>
  )
}

/* ================================================================== */
/* The proposal (§2)                                                   */
/* ================================================================== */

function ProposalCard({
  proposal,
  branchName,
  busy,
  error,
  onStand,
  onCut,
  onClose,
}: {
  proposal: BenchProposal
  branchName: string
  busy: boolean
  error: string | null
  onStand: () => void
  onCut: () => void
  onClose: () => void
}) {
  const seatName = SEAT_NAME_BY_ARCHETYPE[proposal.seat] ?? proposal.seat
  const seatColour = SEAT_COLOUR_BY_ARCHETYPE[proposal.seat] ?? '#b47333'
  return (
    <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 p-3.5 text-stone-200" data-proposal-card={proposal.id}>
      <div className="flex items-start gap-2">
        <span className="w-3 h-3 rounded-full shrink-0 mt-1" style={{ background: seatColour }} />
        <p className="m-0 text-sm flex-1">
          A proposal, recorded and awaiting your verdict — the coil wears {seatName}’s colour
          because {seatName} proposed it. On “{branchName}”: <b>{proposal.title}</b>
        </p>
        <button type="button" onClick={onClose} aria-label="Close the proposal" className="bg-transparent border-0 text-stone-400 cursor-pointer text-base leading-none">
          ×
        </button>
      </div>
      {proposal.evidence_quote && (
        <p className="m-0 mt-2 text-sm text-stone-300 italic">“{proposal.evidence_quote}”</p>
      )}
      {proposal.notes && <p className="m-0 mt-1.5 text-sm text-stone-300">{proposal.notes}</p>}
      <p className="m-0 mt-2 text-xs text-stone-500">
        The wire only holds the branch; it is not part of it. Rule on it when you are ready.
      </p>
      {error && <p className="m-0 mt-2 text-sm text-red-300">{error}</p>}
      <div className="flex gap-2 mt-3">
        <button
          type="button"
          disabled={busy}
          onClick={onStand}
          className="min-h-[40px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-50"
        >
          Let this stand
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onCut}
          className="min-h-[40px] px-4 rounded-full border border-stone-500 text-stone-200 text-sm bg-transparent disabled:opacity-50"
        >
          Cut this back
        </button>
      </div>
    </div>
  )
}

/* ================================================================== */
/* Notebook pop-up (§4/§11)                                            */
/* ================================================================== */

function NotebookOverlay({ tree, onClose }: { tree: BenchTreeModel; onClose: () => void }) {
  const footingNote =
    tree.footing.kind === 'documented'
      ? 'Documented footing — the fullest grip: verbatim-linked records stand under this tree.'
      : tree.footing.kind === 'reported'
        ? 'Reported footing — slighter grip: what stands under this one is the record’s own prose, as you’ve told it.'
        : 'No cited evidence in the record — this one stands as assumed, with nothing under the trunk.'
  return (
    <div
      className="fixed inset-0 z-40 flex items-end sm:items-center justify-center bg-black/55"
      role="dialog"
      aria-modal="true"
      aria-label={`Notebook — ${tree.title}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="bg-[#fffaf0] text-stone-800 w-full max-w-[560px] max-h-[86vh] overflow-y-auto rounded-t-2xl sm:rounded-2xl p-5 shadow-xl">
        <button
          type="button"
          onClick={onClose}
          className="float-right min-h-[36px] px-3.5 rounded-full border border-stone-300 bg-[#f7f1de] text-sm"
        >
          Close
        </button>
        <h2 className="m-0 text-lg font-semibold" style={{ fontFamily: 'Georgia, "Iowan Old Style", "Times New Roman", serif' }}>
          Notebook — {tree.title}
        </h2>
        <p className="m-0 mt-0.5 mb-3 text-sm text-stone-500">{footingNote}</p>
        {tree.notebook.length === 0 && (
          <p className="text-sm text-stone-500">The record holds nothing further for this tree.</p>
        )}
        {tree.notebook.map((e, i) => (
          <div key={i} className="border-t border-stone-300/70 py-2.5">
            <span className="text-[0.72rem] tracking-[0.12em] uppercase font-bold text-[#7c4a21]">{e.kind}</span>
            <span className="text-[0.72rem] text-stone-400 float-right">{e.date ? e.date.slice(0, 10) : ''}</span>
            <h4 className="m-0 mt-0.5 text-[0.98rem]" style={{ fontFamily: 'Georgia, "Iowan Old Style", "Times New Roman", serif' }}>
              {e.title}
            </h4>
            <p className="m-0 text-sm leading-relaxed">{e.body}</p>
            <p className="m-0 mt-1 text-xs text-stone-500 leading-relaxed">{e.custody}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
