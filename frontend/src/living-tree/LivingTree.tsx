/**
 * Living Tree — the home view. A functional family tree: the user at the
 * center of a braided trunk, the 7 strands rooting below, and the 7 council
 * archetypes branching above.
 *
 * Branches are archetypes, not marketplace listings: Mentor, Champion,
 * Guardian, Maverick, Ambassador, Conductor, and the Skeptic. Each branch's
 * thickness is that archetype's training depth. Tapping a branch opens its
 * character panel — strand blend, twigs, recent stories — with marketplace
 * rental info one section deeper. Commerce lives in the panel, never on the
 * tree itself.
 *
 * Ported from the vanilla-JS/SVG prototype (treev3): golden-ratio layout
 * (each level shrinks length/width/spread by φ), leaf-count-weighted angular
 * sectors, a force-relaxation pass pulling toward φ anchors, an N-strand
 * braided trunk with analytically computed over-under weave, tap-to-bloom
 * nesting with +N buds, and solid-background label pills in a top SVG layer
 * so branch lines never cross text.
 *
 * Honest seed state: the 7 archetypes at 0 depth, no twigs, no rentals, no
 * dollar amounts. Training begins via "Upload source materials".
 *
 * Rendering robustness: node positions live in React state (not a mutated
 * ref), and the initial state is the fully laid-out tree — so the SVG has
 * content on the very first paint, with no dependency on the animation loop
 * to populate it. Critical SVG sizing is inline so the graphic cannot
 * collapse even if the <style> block is ever stripped.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { BRAID_ORDER, STRANDS, strandColor, type StrandKey } from './strands'
import {
  STOCK_ARCHETYPE_FALLBACK,
  dominantStrandKey,
  fetchArchetypeStatus,
  fetchKeystoneAttention,
  type ArchetypeStatus,
  type KeystoneAttention,
  type KeystoneAttentionReason,
} from './archetypes'
import { resolveSeatFace, resolveSeatPanel } from './seatFaces'
import { USER_WEAVE_COLOR } from '../components/VoiceWeave'
import { NodeSheet } from '../tree/NodeSheet'
import { YouEchoPanel } from './YouEchoPanel'

/* ------------------------------------------------------------------ */
/* Tree-as-organism: node sheets (phase 1)                             */
/* ------------------------------------------------------------------ */

/**
 * A tree node that can open a sheet: the central you, or a council seat
 * branch. Strand roots keep their inline narrative panels (for now).
 */
export type TreeNodeRef =
  | { kind: 'you' }
  | {
      kind: 'seat'
      /** Engine seat key, e.g. 'guardian' — passed as the Today `mode`. */
      seatKey: string
      /** Fellowship display name, e.g. 'The Bear'. */
      fellowshipName: string
      /** Archetype display name, e.g. 'Guardian'. */
      archetypeName: string
      avatarUrl?: string | null
    }

/** The one grammar every base node speaks. Later phases extend the menus. */
export type NodeMenuItemId =
  | 'today'
  | 'talk'
  | 'review'
  | 'upload'
  | 'projects'
  | 'settings'
  | 'character'

/**
 * Cross-component ask: jump the open seat sheet to that seat's review
 * (dispatched by the seat's Upload content after an intake completes).
 * Follows the codebase's window-CustomEvent pattern (cf. the vision
 * execution focus/insert-text event).
 */
export const OPEN_SEAT_REVIEW_EVENT = 'zenaf:open-seat-review'

/**
 * Phase-1 composition seam: the app shell provides the mounted view for a
 * (node, menu item) pair. Return null and the sheet shows an honest
 * "still growing" state — later phases fill those in without touching the
 * tree.
 */
export type NodeSheetContentProvider = (
  node: TreeNodeRef,
  item: NodeMenuItemId,
) => ReactNode | null

/** Engine seat key -> fellowship display name (mirrors TodayView's map). */
const FELLOWSHIP_NAMES: Record<string, string> = {
  mentor: 'The Gardener',
  champion: 'The Firebrand',
  guardian: 'The Bear',
  ambassador: 'The Bridge',
  conductor: 'The Weaver',
  skeptic: 'The Neighbor',
  maverick: 'The Fox',
}

/** Spoken form of a seat's attention marker, by reason. The intro line is
    Joshua's narrative: on a fresh tree only the Weaver carries the marker —
    "the Weaver wants to talk about something." */
function markerTitle(archetypeId: string, reason: KeystoneAttentionReason | null | undefined): string {
  const name = FELLOWSHIP_NAMES[archetypeId] ?? 'A seat'
  if (reason === 'intro') return `${name} wants to talk about something.`
  if (reason === 'recognition') return `${name} wants to talk about what it has discovered.`
  return `${name} wants to meet you.`
}

const PHI = 1.618
const CX = 200
const TRUNK_TOP = 302
const TRUNK_BOTTOM = 438
const YOU_Y = 370

type TreeDatum = {
  id: string
  strand: StrandKey | null
  name: string
  /** Training depth, unbounded ≥ 0. Infinite endeavor — there is no 100%. Honest seed: 0. */
  depth: number | null
  /** ISO timestamp of the last training investment, or null when never tended. */
  lastTended: string | null
  narrative: string
  kids?: TreeDatum[]
  /** Set on archetype branch nodes — drives the character panel, blend bars, and Skeptic styling. */
  archetype?: ArchetypeStatus
}

const NARRATIVES: Record<StrandKey, string> = {
  word: 'Your voice, unborrowed. Feed the Voice your writing — drafts, messages, the sentences you rewrote three times — and it learns how you actually sound. Right now it is a blank page.',
  number:
    'Your pattern-reader. The Logic will learn how you weigh evidence and tradeoffs — but it has not seen your data yet.',
  image:
    'Your eye. The Eye will learn your visual taste — what you keep, what you cut — once you show it work you love.',
  sound:
    'Your ear. The Ear learns rhythm, cadence, and tone by listening to what you make and what moves you. Still silent.',
  body: 'Your hands. The Hands will learn how you build — your order of operations, what “done” means to you. No sawdust yet.',
  people:
    'Your way with people. The Heart learns who you listen to, how you hold a room, what fairness costs you. No conversations yet.',
  self: 'Your compass. Compass learns direction and leverage from the calls you have actually made. None logged yet.',
}

/** Roots: the 7 agents, ordered to follow the braid. Honest seed — 0%, no children. */
const DOWN: TreeDatum[] = BRAID_ORDER.map((key) => {
  const s = STRANDS.find((x) => x.key === key)!
  return { id: `agent-${key}`, strand: key, name: s.agentName, depth: 0, lastTended: null, narrative: NARRATIVES[key], kids: [] }
})

/** Branches: the 7 council archetypes, built from live status (or the honest
seed fallback). Branch thickness is the archetype's training depth — its
weight vector applied to your per-strand depths. Twigs become bloomable
children; proposed twigs show as buds awaiting review. */
function buildArchetypeNodes(statuses: ArchetypeStatus[]): TreeDatum[] {
  return statuses.map((a) => {
    const domKey = dominantStrandKey(a)
    const strand = (STRANDS.some((s) => s.key === domKey) ? domKey : null) as StrandKey | null
    const kids: TreeDatum[] = (a.twigs ?? []).map((t) => ({
      id: `twig-${a.id}-${t.twig_id}`,
      strand,
      name: t.display_name,
      depth: 0,
      lastTended: null,
      narrative:
        t.status === 'proposed'
          ? `A proposed ${t.domain_label} specialization of ${a.display_name} — ${t.signal_count} signals clustered here. Review it to let it sprout.`
          : `A ${t.domain_label} specialization of ${a.display_name} — a sub-personality that sprouted where your training clustered (${t.signal_count} signals).`,
      kids: [],
    }))
    return {
      id: `arch-${a.id}`,
      strand,
      name: a.display_name,
      depth: a.depth,
      lastTended: null,
      narrative: a.prompt_frame,
      kids,
      archetype: a,
    }
  })
}

const YOU: TreeDatum = {
  id: 'you',
  strand: null,
  name: 'YOU',
  depth: null,
  lastTended: null,
  narrative: 'Every decision you make trains the roots below. Every branch above is a voice on your council.',
  kids: [],
}

/** The one grammar: the you-node's menu. Later phases extend, never replace. */
const YOU_MENU: Array<{ id: NodeMenuItemId; title: string; desc: string }> = [
  { id: 'today', title: 'Today', desc: "The council's briefing — three cards at a time, no more." },
  { id: 'talk', title: 'Talk', desc: 'Think something through with your whole council.' },
  { id: 'review', title: 'Review', desc: 'Moments awaiting your verdict before anything trains.' },
  { id: 'projects', title: 'Projects', desc: 'Everything in flight — ideas through tasks.' },
  { id: 'settings', title: 'Settings', desc: 'Account, model connections, consent.' },
]

/** The one grammar: a seat node's menu. Talk carries the seat's character card
    as its header — who you're talking to, then the conversation. */
const SEAT_MENU: Array<{ id: NodeMenuItemId; title: string; desc: string }> = [
  { id: 'today', title: 'Today', desc: 'The day through this seat’s eyes.' },
  { id: 'talk', title: 'Talk', desc: 'Meet the seat, then talk it through.' },
  { id: 'review', title: 'Review', desc: 'This seat’s moments awaiting your verdict.' },
  { id: 'upload', title: 'Upload', desc: 'Add source material from this seat — sorted by content; what reaches this seat lands in its review.' },
]

/**
 * Pre-sheet tree options — kept reachable in the you-sheet's second section
 * so nothing that existed is lost in the restructure.
 */
const LEGACY_YOU_ITEMS: Array<{ id: string; title: string; desc: string; cta?: 'agent_intake' }> = [
  {
    id: 'upload',
    title: 'Upload source materials',
    desc: 'Connect a ChatGPT or Claude conversation — paste a share link or send one from your browser. Uploading from YOU distributes across the whole council; uploading from a seat’s profile aims it there. Redaction happens at capture — nothing trains until you review and approve it.',
    cta: 'agent_intake',
  },
  { id: 'stats', title: 'Stats', desc: '' },
  {
    id: 'snapshot',
    title: 'Snapshot era',
    desc: 'Snapshots freeze your profile as a rentable era — automatic each year, plus after big training leaps. Nothing to snapshot yet: eras begin once training does.',
  },
  { id: 'login', title: 'Log in / out', desc: 'You are signed in on this device.' },
]

/* ------------------------------------------------------------------ */
/* Layout math (ported from the prototype)                             */
/* ------------------------------------------------------------------ */

const NSTRAND = BRAID_ORDER.length
const BRAID_W = 54 * Math.pow(NSTRAND / 3, 0.3)
const BRAID_A = 13 * Math.pow(NSTRAND / 3, 0.2)

function braidX(si: number, y: number): number {
  return CX + BRAID_A * Math.sin((2 * Math.PI * (y - TRUNK_TOP)) / BRAID_W + (si * 2 * Math.PI) / NSTRAND)
}

type Placed = {
  datum: TreeDatum
  x: number
  y: number
  px: number
  py: number
  depth: number
  side: 'c' | 'up' | 'dn'
  ang: number
  w: number
  par: string | null
  strand: StrandKey | null
  sidx: number
  kids: TreeDatum[]
}

function leafCount(n: TreeDatum, exp: Record<string, boolean>): number {
  const kids = exp[n.id] && n.kids ? n.kids : []
  if (!kids.length) return 1
  return kids.reduce((s, k) => s + leafCount(k, exp), 0)
}

function layout(exp: Record<string, boolean>, up: TreeDatum[]): Map<string, Placed> {
  const P = new Map<string, Placed>()
  const place = (
    n: TreeDatum,
    px: number,
    py: number,
    ang: number,
    len: number,
    spread: number,
    w: number,
    depth: number,
    side: 'c' | 'up' | 'dn',
    par: string | null,
    strand: StrandKey | null,
  ) => {
    const x = px + len * Math.cos(ang)
    const y = py + len * Math.sin(ang)
    const st = n.strand ?? strand
    const si = st ? BRAID_ORDER.indexOf(st) : -1
    const kids = n.kids ?? []
    P.set(n.id, { datum: n, x, y, px, py, depth, side, ang, w, par, strand: st, sidx: si, kids })
    const open = exp[n.id] && kids.length ? kids : []
    if (open.length) {
      const total = open.reduce((s, k) => s + leafCount(k, exp), 0)
      let acc = ang - spread / 2
      open.forEach((k) => {
        const frac = leafCount(k, exp) / total
        const a = acc + (spread * frac) / 2
        acc += spread * frac
        place(k, x, y, a, len / PHI, Math.max(0.45, spread * frac * 0.94), Math.max(1.1, w / PHI), depth + 1, side, n.id, st)
      })
    }
  }
  P.set(YOU.id, {
    datum: YOU,
    x: CX,
    y: YOU_Y,
    px: CX,
    py: YOU_Y,
    depth: 0,
    side: 'c',
    ang: 0,
    w: 7,
    par: null,
    strand: null,
    sidx: -1,
    kids: [],
  })
  const spreadFor = (n: number) => Math.min(2.9, 1.9 + 0.18 * (n - 3))
  const spU = spreadFor(up.length)
  const spD = spreadFor(DOWN.length)
  up.forEach((n, i) => {
    const a = -Math.PI / 2 - spU / 2 + (spU * i) / Math.max(1, up.length - 1)
    place(n, CX, TRUNK_TOP, a, 130, spU, 5, 1, 'up', 'you', n.strand)
  })
  DOWN.forEach((n, i) => {
    // Roots fan DOWNWARD from the trunk bottom (+π/2 in SVG coords, where +y is down).
    const a = Math.PI / 2 - spD / 2 + (spD * i) / Math.max(1, DOWN.length - 1)
    place(n, CX, TRUNK_BOTTOM, a, 120, spD, 4.6, 1, 'dn', 'you', n.strand)
  })
  return P
}

/** Attention is the water: what you tend grows, what you ignore recedes.
Effective depth decays exponentially toward 0 with a ~90-day half-life, so a
neglected node visibly shrinks. Re-tending regrows from the decayed value —
like muscle memory, it comes back faster than it first grew. */
const ATTENTION_HALF_LIFE_DAYS = 90
function effectiveDepth(depth: number | null, lastTended: string | null): number {
  const d = Math.max(0, depth ?? 0)
  if (d <= 0 || !lastTended) return 0
  const days = (Date.now() - new Date(lastTended).getTime()) / 86400000
  if (days <= 0) return d
  return d * Math.pow(0.5, days / ATTENTION_HALF_LIFE_DAYS)
}

/** Node radius: investment made visible. Growth is asymptotic — the node
approaches its full size but never arrives, because the endeavor is infinite.
Neglect shrinks it. YOU stays fixed. Archetype branches carry a 0..100 depth
score (their weight vector applied to strand depths); strands use the raw
unbounded scale with attention decay. */
function nodeR(p: Placed): number {
  if (p.side === 'c') return 34
  const arch = p.datum.archetype
  if (arch) {
    const d = Math.max(0, Math.min(100, arch.depth)) / 25
    return 12 + 10 * (1 - Math.exp(-d))
  }
  return 12 + 10 * (1 - Math.exp(-effectiveDepth(p.datum.depth, p.datum.lastTended)))
}

function labelWidth(p: Placed): number {
  const fs = p.depth >= 3 ? 6.5 : 7.5
  return p.datum.name.length * fs * 0.56 + 14
}

/** Force-relaxation: push overlapping nodes apart, then pull back toward φ anchors. */
function relax(P: Map<string, Placed>): Map<string, Placed> {
  const ids = [...P.keys()]
  const home = new Map<string, { x: number; y: number }>()
  const need = new Map<string, number>()
  P.forEach((p, id) => {
    home.set(id, { x: p.x, y: p.y })
    need.set(id, id === 'you' ? 70 : nodeR(p) + 20 + labelWidth(p) * 0.58)
  })
  for (let it = 0; it < 140; it++) {
    for (let a = 0; a < ids.length; a++) {
      for (let b = a + 1; b < ids.length; b++) {
        const ia = ids[a]
        const ib = ids[b]
        const pa = P.get(ia)!
        const pb = P.get(ib)!
        const dx = pb.x - pa.x
        const dy = pb.y - pa.y
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01
        const want = (need.get(ia)! + need.get(ib)!) / 2
        if (d < want) {
          const push = (want - d) * 0.28
          const nx = dx / d
          const ny = dy / d
          if (ia !== 'you') {
            pa.x -= nx * push
            pa.y -= ny * push
          }
          if (ib !== 'you') {
            pb.x += nx * push
            pb.y += ny * push
          }
        }
      }
    }
    P.forEach((p, id) => {
      if (id === 'you') return
      const h = home.get(id)!
      p.x += (h.x - p.x) * 0.1
      p.y += (h.y - p.y) * 0.1
    })
  }
  return P
}

/** The Skeptic's hollow branch — the inverse voice, rendered in muted slate. */
const SKEPTIC_COLOR = '#6b6480'

function strandCol(p: { side: string; strand: StrandKey | null; datum?: TreeDatum }): string {
  if (p.side === 'c') return '#c9a86a'
  if (p.datum?.archetype?.is_skeptic) return SKEPTIC_COLOR
  if (!p.strand) return '#c9a86a'
  return strandColor(p.strand)
}

function pathD(x: number, y: number, px: number, py: number): string {
  const dx = x - px
  const dy = y - py
  const c1x = px + dx * 0.25
  const c1y = py + dy * 0.55
  const c2x = px + dx * 0.75
  const c2y = py + dy * 0.55
  return `M${px},${py} C${c1x},${c1y} ${c2x},${c2y} ${x},${y}`
}

/** Braid segments with analytically computed over-under crossings, parametric in strand count. */
function computeBraid(): Array<{ d: string; color: string; under: boolean }> {
  const N = NSTRAND
  const X = (i: number, y: number) => braidX(i, y)
  const cross: number[][] = Array.from({ length: N }, () => [])
  const NSAMP = 200
  for (let a = 0; a < N; a++) {
    for (let b = a + 1; b < N; b++) {
      let py = 0
      let pd = 0
      let first = true
      for (let s = 0; s <= NSAMP; s++) {
        const y = TRUNK_TOP + ((TRUNK_BOTTOM - TRUNK_TOP) * s) / NSAMP
        const d = X(a, y) - X(b, y)
        if (!first && d !== 0 && pd !== 0 && (d < 0) !== (pd < 0)) {
          const t = Math.abs(pd) / (Math.abs(pd) + Math.abs(d))
          const yc = py + (y - py) * t
          cross[a].push(yc)
          cross[b].push(yc)
        }
        py = y
        pd = d
        first = false
      }
    }
  }
  cross.forEach((c) => c.sort((x, y) => x - y))
  const cols = BRAID_ORDER.map(strandColor)
  const segs: Array<{ d: string; color: string; under: boolean }> = []
  for (let i = 0; i < N; i++) {
    const bounds = [TRUNK_TOP, ...cross[i], TRUNK_BOTTOM]
    for (let j = 0; j < bounds.length - 1; j++) {
      const y1 = bounds[j]
      const y2 = bounds[j + 1]
      let d = ''
      for (let y = y1; y < y2; y += 3) d += `${d ? 'L' : 'M'}${X(i, y).toFixed(1)},${y.toFixed(1)} `
      d += `L${X(i, y2).toFixed(1)},${y2.toFixed(1)}`
      segs.push({ d, color: cols[i], under: (j + i) % 2 !== 0 })
    }
  }
  // unders first so overs paint on top
  return [...segs.filter((s) => s.under), ...segs.filter((s) => !s.under)]
}

function ease(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

type LiveNode = Placed & { op: number }

function findDatum(id: string, up: TreeDatum[]): TreeDatum | null {
  if (id === YOU.id) return YOU
  const walk = (list: TreeDatum[]): TreeDatum | null => {
    for (const n of list) {
      if (n.id === id) return n
      if (n.kids) {
        const f = walk(n.kids)
        if (f) return f
      }
    }
    return null
  }
  return walk(up) ?? walk(DOWN)
}

/** The ??? placeholder: a gray silhouette for a seat whose face is undiscovered.
    This is the UI expression of the same concept the comic-strip renderer
    draws as an amorphous cloud — an undiscovered face, mysterious and
    inviting, never broken-looking. */
function AvatarPlaceholder({ size = 72 }: { size?: number }) {
  return (
    <div
      className="lavatar-ph"
      style={{ width: size, height: size }}
      role="img"
      aria-label="Undiscovered face"
    >
      <svg viewBox="0 0 72 72" width={size} height={size} aria-hidden="true">
        <circle cx="36" cy="36" r="34" fill="rgba(245,240,232,0.06)" />
        <circle cx="36" cy="28" r="11" fill="rgba(245,240,232,0.28)" />
        <path
          d="M14 62c3-12 12-19 22-19s19 7 22 19"
          fill="rgba(245,240,232,0.28)"
        />
      </svg>
      <span className="lavatar-qqq">???</span>
    </div>
  )
}

/** A seat's avatar: the unlocked custom image, or the ??? placeholder. */
function SeatAvatar({
  avatarUrl,
  displayName,
  size = 72,
}: {
  avatarUrl: string | null | undefined
  displayName: string
  size?: number
}) {
  if (avatarUrl) {
    return (
      <img
        className="lavatar-img"
        src={avatarUrl}
        alt={`${displayName} avatar`}
        style={{ width: size, height: size }}
      />
    )
  }
  return <AvatarPlaceholder size={size} />
}

/** Avatar unlock section for an archetype's character panel. */
function AvatarSection({
  arch,
  onChanged,
}: {
  arch: ArchetypeStatus
  onChanged: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [urlInput, setUrlInput] = useState('')
  const [showUpload, setShowUpload] = useState(false)

  const putAvatar = async (body: { avatar_url?: string; generate?: boolean }) => {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(
        `/council/archetypes/${encodeURIComponent(arch.id)}/avatar`,
        {
          method: 'PUT',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }
      )
      if (res.status === 501) {
        setError('AI generation is not available yet — paste an image URL instead.')
        return
      }
      if (!res.ok) {
        const j = await res.json().catch(() => null)
        const msg =
          (j && (j.detail?.message || j.detail)) || `Could not set avatar (${res.status}).`
        setError(typeof msg === 'string' ? msg : 'Could not set avatar.')
        return
      }
      setShowUpload(false)
      setUrlInput('')
      onChanged()
    } catch {
      setError('Network error — try again.')
    } finally {
      setBusy(false)
    }
  }

  const face = resolveSeatFace(arch)
  const panelArt = resolveSeatPanel(arch)
  return (
    <div className="lavatar-sect">
      <div className="lsect">Face</div>
      <div className="lavatar-row">
        <SeatAvatar avatarUrl={face} displayName={arch.display_name} />
        <div className="lavatar-meta">
          {arch.avatar_url ? (
            <p className="lnote">
              This is {arch.display_name}'s face — the one you've earned the right to see.
            </p>
          ) : arch.avatar_unlocked ? (
            <p className="lnote">
              The fellowship's face for {arch.display_name}, revealed through training.
              Generate or upload an image to replace it with your own.
            </p>
          ) : (
            <p className="lnote">
              <strong>???</strong> — this seat's face is still undiscovered. Train it
              ({arch.avatar_signals_to_unlock} more depth to go) and you'll earn the
              right to see it.
            </p>
          )}
          {error && <p className="lavatar-err">{error}</p>}
        </div>
      </div>
      {panelArt && (
        <img
          className="lavatar-panel"
          src={panelArt}
          alt={`${arch.display_name} — full portrait`}
        />
      )}
      {arch.avatar_unlocked && !showUpload && (
        <div className="lavatar-btns">
          <button
            type="button"
            className="lcta"
            disabled={busy}
            onClick={() => putAvatar({ generate: true })}
          >
            {busy ? 'Working…' : arch.avatar_url ? 'Regenerate' : 'Generate face'}
          </button>
          <button
            type="button"
            className="lcta"
            disabled={busy}
            onClick={() => setShowUpload(true)}
          >
            {arch.avatar_url ? 'Change' : 'Upload image'}
          </button>
        </div>
      )}
      {arch.avatar_unlocked && showUpload && (
        <div className="lavatar-upload">
          <input
            type="url"
            className="lavatar-input"
            placeholder="https://… image URL"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            aria-label="Avatar image URL"
          />
          <div className="lavatar-btns">
            <button
              type="button"
              className="lcta"
              disabled={busy || !urlInput.trim()}
              onClick={() => putAvatar({ avatar_url: urlInput.trim() })}
            >
              {busy ? 'Saving…' : 'Set face'}
            </button>
            <button
              type="button"
              className="lback"
              onClick={() => {
                setShowUpload(false)
                setUrlInput('')
                setError(null)
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** Visual strand-blend bars for an archetype's character panel. */
function StrandBlendBars({ weights }: { weights: Record<string, number> }) {
  const entries = Object.entries(weights ?? {})
    .filter(([, w]) => w >= 0.05)
    .sort(([, a], [, b]) => b - a)
  if (!entries.length) return null
  return (
    <div className="lblend">
      <div className="lsect">Strand blend</div>
      {entries.map(([key, w]) => {
        const s = STRANDS.find((x) => x.key === key)
        if (!s) return null
        const pct = Math.round(w * 100)
        return (
          <div key={key} className="lstat">
            <span className="ldot" style={{ background: s.color }} />
            <span className="lname">{s.agentName}</span>
            <div className="lbar">
              <div className="lfill" style={{ width: `${pct}%`, background: s.color }} />
            </div>
            <span className="lpct">{pct}%</span>
          </div>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export function LivingTreeView({
  onNavigate,
  initials,
  renderSheetContent,
}: {
  /** Navigate the app shell (e.g. onNavigate('agent_intake') to connect a conversation). */
  onNavigate: (view: 'vision_map' | 'agent_intake') => void
  /** Initials rendered on the central profile node; defaults to "YOU". */
  initials?: string
  /** App-shell provider: the mounted view for a (node, menu item) pair. */
  renderSheetContent?: NodeSheetContentProvider
}) {
  const [sel, setSel] = useState<string | null>(null)
  const [exp, setExp] = useState<Record<string, boolean>>({})
  /** Open node sheet (phase 1: the tree is the app; nodes open in place). */
  const [sheetNode, setSheetNode] = useState<TreeNodeRef | null>(null)
  /** Null = the node's menu; otherwise the mounted menu item. */
  const [sheetItem, setSheetItem] = useState<NodeMenuItemId | null>(null)
  /** Seat whose full character panel is expanded inside its Talk tab. */
  const [charExpandedSeat, setCharExpandedSeat] = useState<string | null>(null)

  // A seat's Upload content asks to land in that seat's review when an
  // intake completes (OPEN_SEAT_REVIEW_EVENT). Only the sheet that is
  // open on that seat answers; anything else ignores the event.
  useEffect(() => {
    const onOpenSeatReview = (e: Event) => {
      const seatKey = (e as CustomEvent<{ seatKey?: string }>).detail?.seatKey
      if (!seatKey) return
      if (sheetNode?.kind === 'seat' && sheetNode.seatKey === seatKey) {
        setSheetItem('review')
      }
    }
    window.addEventListener(OPEN_SEAT_REVIEW_EVENT, onOpenSeatReview)
    return () => window.removeEventListener(OPEN_SEAT_REVIEW_EVENT, onOpenSeatReview)
  }, [sheetNode])
  /** Legacy tree-options row expanded inline in the you-sheet. */
  const [legacyOpen, setLegacyOpen] = useState<string | null>(null)

  // Archetype branches: live status from the backend, honest seed fallback
  // while loading or when unreachable. The tree renders on first paint;
  // depths animate in when the fetch resolves.
  const [archetypes, setArchetypes] = useState<ArchetypeStatus[]>(STOCK_ARCHETYPE_FALLBACK)
  const refreshArchetypes = () => {
    fetchArchetypeStatus().then((s) => {
      if (s && s.length) setArchetypes(s)
    })
  }
  useEffect(() => {
    let cancelled = false
    fetchArchetypeStatus().then((s) => {
      if (!cancelled && s && s.length) setArchetypes(s)
    })
    return () => {
      cancelled = true
    }
  }, [])

  // Keystone attention markers ("!"): a seat that wants the user carries a
  // small badge over its node — narrative guidance that waits on the tree,
  // never a push. Null/empty (unseeded account, backend unreachable) simply
  // means no markers.
  const [attention, setAttention] = useState<KeystoneAttention | null>(null)
  useEffect(() => {
    let cancelled = false
    fetchKeystoneAttention().then((a) => {
      if (!cancelled && a) setAttention(a)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const up = useMemo(() => buildArchetypeNodes(archetypes), [archetypes])

  const braid = useMemo(() => computeBraid(), [])
  // Target positions, recomputed synchronously whenever expansion or the
  // archetype list changes.
  const target = useMemo(() => relax(layout(exp, up)), [exp, up])

  // Displayed nodes live in state and are seeded with the fully laid-out
  // tree, so the SVG renders content on the very first paint. The effect
  // below only animates transitions between layouts.
  const [nodes, setNodes] = useState<LiveNode[]>(() =>
    [...target.values()].map((p) => ({ ...p, op: 1 })),
  )
  const nodesRef = useRef(nodes)
  nodesRef.current = nodes

  useEffect(() => {
    const from = new Map(nodesRef.current.map((n) => [n.datum.id, n]))
    // Skip the animation when nothing moved (e.g. first mount: display
    // already equals target).
    let moved = from.size !== target.size
    if (!moved) {
      for (const [id, p] of target) {
        const f = from.get(id)
        if (!f || Math.abs(f.x - p.x) > 0.01 || Math.abs(f.y - p.y) > 0.01) {
          moved = true
          break
        }
      }
    }
    if (!moved) return
    const t0 = performance.now()
    const DUR = 480
    let raf = 0
    let cancelled = false
    const frame = (t: number) => {
      if (cancelled) return
      const k = ease(Math.min(1, (t - t0) / DUR))
      const next: LiveNode[] = []
      target.forEach((p, id) => {
        const f = from.get(id)
        next.push({
          ...p,
          x: f ? f.x + (p.x - f.x) * k : p.px,
          y: f ? f.y + (p.y - f.y) * k : p.py,
          op: f ? f.op + (1 - f.op) * k : k,
        })
      })
      setNodes(next)
      if (k < 1) raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => {
      cancelled = true
      cancelAnimationFrame(raf)
    }
  }, [target])

  const openSheet = (node: TreeNodeRef) => {
    setSheetItem(null)
    setLegacyOpen(null)
    setSheetNode(node)
  }
  const closeSheet = () => {
    setSheetNode(null)
    setSheetItem(null)
    setLegacyOpen(null)
    // A seat's character now lives in its sheet — clear its highlight too.
    setSel((s) => {
      if (!s) return s
      const d = findDatum(s, up)
      return d?.archetype ? null : s
    })
  }

  const onTap = (id: string) => {
    if (id === 'you') {
      setSel(null)
      openSheet({ kind: 'you' })
      return
    }
    const live = nodesRef.current.find((n) => n.datum.id === id)
    if (live && live.kids.length) {
      setExp((e) => {
        const next = { ...e }
        if (next[id]) delete next[id]
        else next[id] = true
        return next
      })
    }
    const datum = live?.datum ?? findDatum(id, up)
    const arch = datum?.archetype
    if (arch) {
      // Seat branches open their sheet (menu: Today / Talk / Review).
      setSel(id)
      openSheet({
        kind: 'seat',
        seatKey: arch.id,
        fellowshipName: FELLOWSHIP_NAMES[arch.id] ?? arch.display_name,
        archetypeName: arch.display_name,
        avatarUrl: arch.avatar_url,
      })
      return
    }
    // Strand roots keep their inline narrative panels.
    setSel((s) => (s === id ? null : id))
  }

  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.datum.id, n])), [nodes])

  // Dynamic viewBox fitted to the actual content (nodes + braid + labels),
  // computed from the stable target layout so it doesn't jitter mid-animation.
  // The honest seed state is compact; a fixed tall viewBox left the tree tiny
  // in a sea of empty space.
  const viewBox = useMemo(() => {
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity
    target.forEach((p) => {
      const r = p.side === 'c' ? 44 : nodeR(p) + 10
      minX = Math.min(minX, p.x - r - 34)
      maxX = Math.max(maxX, p.x + r + 34)
      minY = Math.min(minY, p.y - r - 18)
      maxY = Math.max(maxY, p.y + r + 18)
    })
    minX = Math.min(minX, CX - BRAID_A - 34)
    maxX = Math.max(maxX, CX + BRAID_A + 34)
    minY = Math.min(minY, TRUNK_TOP - 28)
    maxY = Math.max(maxY, TRUNK_BOTTOM + 28)
    const pad = 14
    const vx = Math.floor(minX - pad)
    const vy = Math.floor(minY - pad)
    const vw = Math.ceil(maxX - minX + pad * 2)
    const vh = Math.ceil(maxY - minY + pad * 2)
    return `${vx} ${vy} ${vw} ${vh}`
  }, [target])

  /** Council-depth stats — shared by the you-sheet's Tree options. */
  const renderStatsBlock = () => (
    <div className="lstats">
      <p className="lnote">
        Council depth — each branch deepens as its strands are trained. No rentals yet — training comes
        first.
      </p>
      {archetypes.map((a) => {
        const domKey = dominantStrandKey(a)
        const s = STRANDS.find((x) => x.key === domKey)
        const col = a.is_skeptic ? SKEPTIC_COLOR : (s?.color ?? '#c9a86a')
        return (
          <div key={a.id} className="lstat">
            <span className="ldot" style={{ background: col }} />
            <span className="lname">{a.display_name}</span>
            <span className="lpct">{a.depth <= 0 ? 'seed' : `${a.depth}%`}</span>
            <div className="lbar">
              <div className="lfill" style={{ width: `${a.depth}%`, background: col }} />
            </div>
          </div>
        )
      })}
    </div>
  )

  /**
   * Talk + Character, one tab: the seat's character card is the head of the
   * conversation. Compact by default so the composer stays within a short
   * scroll; the full panel expands inline via disclosure.
   */
  const renderCompactSeatHead = (arch: ArchetypeStatus) => {
    const isSeed = arch.depth <= 0
    const tag = isSeed ? 'SEED' : arch.band.toUpperCase()
    const col = arch.is_skeptic ? SKEPTIC_COLOR : '#c9a86a'
    const expanded = charExpandedSeat === arch.id
    return (
      <div>
        <div className="lavatar-head">
          <SeatAvatar avatarUrl={resolveSeatFace(arch)} displayName={arch.display_name} size={44} />
          <div>
            <h3 style={{ margin: 0 }}>{arch.display_name}</h3>
            <div className="ltag" style={{ color: col }}>
              {arch.is_skeptic ? 'THE SKEPTIC · ' : ''}{tag}
            </div>
          </div>
        </div>
        <p>“{arch.prompt_frame}”</p>
        <div className="lstat">
          <span className="lname">Viability</span>
          <span className="lpct">{arch.depth}%</span>
          {isSeed && <span className="lnote"> — training comes first</span>}
        </div>
        <button
          type="button"
          className="lback"
          aria-expanded={expanded}
          onClick={() => setCharExpandedSeat(expanded ? null : arch.id)}
        >
          {expanded ? 'Hide full character ↑' : 'Full character →'}
        </button>
        {expanded && renderSeatCharacterBody(arch)}
      </div>
    )
  }

  /** The full character panel body — face unlock, strand blend, twigs,
      marketplace. Shown via the Talk tab's "Full character" disclosure. */
  const renderSeatCharacterBody = (arch: ArchetypeStatus) => {
    const isSeed = arch.depth <= 0
    return (
      <div>
        <AvatarSection arch={arch} onChanged={refreshArchetypes} />
        <StrandBlendBars weights={arch.strand_weights} />
        {(arch.twigs ?? []).length > 0 ? (
          <div className="ltwigs">
            <div className="lsect">Sub-personalities</div>
            {(arch.twigs ?? []).map((t) => (
              <div key={t.twig_id} className="ltwig">
                <span className="lname">{t.display_name}</span>
                <span className="ldomain">
                  {t.domain_label}
                  {t.status === 'proposed' ? ' · proposed' : ''}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="lsub">
            No sub-personalities yet — they sprout when your training clusters in a specific domain.
          </p>
        )}
        <div className="lmarket">
          <div className="lsect">Marketplace</div>
          <div className="lstat">
            <span className="lname">Viability</span>
            <div className="lbar">
              <div className="lfill" style={{ width: `${arch.depth}%`, background: arch.is_skeptic ? SKEPTIC_COLOR : '#c9a86a' }} />
            </div>
            <span className="lpct">{arch.depth}%</span>
          </div>
          <p className="lnote">
            {isSeed
              ? 'Nothing to rent yet — training comes first. You set the price when there is something worth renting.'
              : 'No rental price set yet — you set the price per archetype when there is training worth renting.'}
          </p>
        </div>
        <YouEchoPanel
          archetypeId={arch.id}
          character={FELLOWSHIP_NAMES[arch.id] ?? arch.display_name}
        />
        {isSeed && (
          <button
            type="button"
            className="lcta"
            onClick={() => {
              closeSheet()
              onNavigate('agent_intake')
            }}
          >
            Upload source materials to begin training ›
          </button>
        )}
      </div>
    )
  }

  /** Inline narrative panel under the tree — strand roots only, now that the
      you-node and the seats open sheets. */
  const renderPanel = () => {
    const d = sel ? findDatum(sel, up) : null
    if (!d || d.archetype) {
      return (
        <div className="lhint">
          Tap the trunk for your options — tap any branch to meet its character.
        </div>
      )
    }
    const live = nodeById.get(sel!)
    const col = live ? strandCol(live) : '#c9a86a'
    const raw = Math.max(0, d.depth ?? 0)
    const eff = effectiveDepth(d.depth, d.lastTended)
    const fallow = raw > 0.3 && eff < raw * 0.4
    const tag =
      d.id === 'you' ? 'THE SOURCE' : raw <= 0 ? 'SEED' : fallow ? 'FALLOW' : 'DEEPENING'
    return (
      <div>
        <h3>{d.name}</h3>
        <div className="ltag" style={{ color: col }}>
          {tag}
        </div>
        <p>“{d.narrative}”</p>
        {fallow && (
          <p className="lsub">You used to tend this — it is waiting, not gone. Pick it back up and it returns faster than it first grew.</p>
        )}
        {d.id !== 'you' && (
          <button
            type="button"
            className="lcta"
            onClick={() => onNavigate('agent_intake')}
          >
            Upload source materials to begin training ›
          </button>
        )}
      </div>
    )
  }

  /* ---------------- node sheet: menus + mounted views ---------------- */

  /** The node's menu — the one grammar. Tapping a row mounts its view. */
  const renderNodeMenu = (node: TreeNodeRef) => {
    const items = node.kind === 'you' ? YOU_MENU : SEAT_MENU
    return (
      <div>
        {items.map((m) => (
          <button
            key={m.id}
            type="button"
            className="lrow"
            onClick={() => setSheetItem(m.id)}
          >
            <span>
              <span className="lrow-t">{m.title}</span>
              <span className="lrow-d">{m.desc}</span>
            </span>
            <span className="lchev">›</span>
          </button>
        ))}
        {node.kind === 'you' && (
          <div className="llegacy">
            <div className="lsect">Tree options</div>
            {LEGACY_YOU_ITEMS.map((m) => {
              const open = legacyOpen === m.id
              return (
                <div key={m.id}>
                  <button
                    type="button"
                    className="lrow"
                    onClick={() => {
                      if (m.cta === 'agent_intake') {
                        closeSheet()
                        onNavigate('agent_intake')
                        return
                      }
                      setLegacyOpen(open ? null : m.id)
                    }}
                  >
                    <span>{m.title}</span>
                    <span className="lchev">{m.cta || !open ? '›' : '‹'}</span>
                  </button>
                  {open && m.id === 'stats' && renderStatsBlock()}
                  {open && m.id !== 'stats' && m.desc && <p className="lsub">{m.desc}</p>}
                </div>
              )
            })}
          </div>
        )}
      </div>
    )
  }

  /** Honest empty state: no fake content, no demo data — later phases fill in. */
  const renderStillGrowing = (node: TreeNodeRef, item: NodeMenuItemId) => {
    const copy: Partial<Record<NodeMenuItemId, string>> = {}
    return (
      <div className="lgrow">
        <p className="lgrow-t">Still growing.</p>
        <p>{copy[item] ?? 'This corner of the tree is still growing.'}</p>
      </div>
    )
  }

  const renderSheetBody = () => {
    if (!sheetNode) return null
    if (!sheetItem) return renderNodeMenu(sheetNode)
    if (sheetItem === 'talk' && sheetNode.kind === 'seat') {
      // Merged Talk + Character: the seat's character card heads the conversation.
      const arch = archetypes.find((a) => a.id === sheetNode.seatKey)
      if (!arch) return renderStillGrowing(sheetNode, sheetItem)
      const chat = renderSheetContent?.(sheetNode, 'talk')
      return (
        <div>
          {renderCompactSeatHead(arch)}
          {chat ? <div className="lsheet-view">{chat}</div> : renderStillGrowing(sheetNode, 'talk')}
        </div>
      )
    }
    const content = renderSheetContent?.(sheetNode, sheetItem)
    if (content) return <div className="lsheet-view">{content}</div>
    return renderStillGrowing(sheetNode, sheetItem)
  }

  const sheetTitle = !sheetNode
    ? ''
    : sheetNode.kind === 'you'
      ? (initials ?? 'You')
      : sheetNode.fellowshipName
  const sheetSubtitle = !sheetNode || sheetNode.kind === 'you'
    ? 'The source'
    : sheetNode.archetypeName

  return (
    <div
      className="ltree"
      style={{ boxSizing: 'border-box', width: '100%', maxWidth: 430, margin: '0 auto' }}
    >
      <style>{`
.ltree{box-sizing:border-box;width:100%;max-width:430px;margin:0 auto;background:#0b0a09;border:1px solid rgba(201,168,106,.25);border-radius:20px;padding:18px 12px 14px;color:#f5f0e8;font-family:system-ui,-apple-system,sans-serif;user-select:none;-webkit-user-select:none;-webkit-tap-highlight-color:transparent;overflow-x:clip}
.ltree *{box-sizing:border-box}
.lhead{text-align:center}
.lhead h2{margin:0;font-size:18px;font-weight:650}
.lhead h2 em{color:#c9a86a;font-style:italic}
.lhead p{margin:6px 8px 0;font-size:11.5px;color:rgba(245,240,232,.6);line-height:1.55;overflow-wrap:break-word}
.llegend{display:flex;flex-wrap:wrap;justify-content:center;gap:4px 10px;margin:10px 4px 0;font-size:10px;color:rgba(245,240,232,.55)}
.llegend span{display:inline-flex;align-items:center;gap:4px}
.llegend i{width:8px;height:8px;border-radius:50%;display:inline-block}
.lsvg{display:block;width:100%;height:auto}
.lnode{cursor:pointer}
.lnode circle.face{fill:#141210;stroke-width:1.8}
.lnode text{fill:#f5f0e8;text-anchor:middle;pointer-events:none}
.lnode .nm{font-size:9px;font-weight:700}
.lnode .bud{fill:#0b0a09;stroke-width:1.2}
.lnode .budt{font-size:8px;font-weight:800}
.lnarr{margin:10px 4px 0;background:rgba(245,240,232,.05);border:1px solid rgba(201,168,106,.3);border-radius:14px;padding:12px 14px;min-height:120px}
.lnarr h3{margin:0 0 3px;font-size:13.5px}
.lnarr .ltag{font-size:10.5px;font-weight:700;letter-spacing:.08em;margin-bottom:5px}
.lnarr p{margin:0;font-size:12px;line-height:1.6;color:rgba(245,240,232,.82);font-style:italic;overflow-wrap:break-word}
.lnarr .lhint{color:rgba(245,240,232,.45);font-style:normal;text-align:center;padding:12px 0 4px;font-size:12px}
.lnarr .lnote{font-style:normal;color:rgba(245,240,232,.6);font-size:11.5px;margin-bottom:8px}
.lrow{display:flex;align-items:center;justify-content:space-between;width:100%;background:rgba(245,240,232,.05);border:1px solid rgba(201,168,106,.25);border-radius:10px;color:#f5f0e8;font-size:13px;font-weight:600;padding:10px 12px;min-height:44px;margin:0 0 6px;cursor:pointer;font-family:inherit;text-align:left}
.lrow:active{background:rgba(201,168,106,.15)}
.lrow .lchev{color:#c9a86a;font-weight:400}
.lback{background:none;border:none;color:#c9a86a;font-size:12px;font-weight:700;padding:2px 0 8px;min-height:44px;cursor:pointer;font-family:inherit}
.lcta{display:inline-flex;align-items:center;gap:6px;margin-top:10px;background:rgba(201,168,106,.12);border:1px solid rgba(201,168,106,.5);border-radius:10px;color:#f5f0e8;font-size:12.5px;font-weight:700;padding:10px 14px;min-height:44px;cursor:pointer;font-family:inherit}
.lcta:active{background:rgba(201,168,106,.25)}
.lsub{margin-top:10px;font-size:12px;color:rgba(245,240,232,.55);font-style:italic}
.lstats{margin-top:2px}
.lstat{display:flex;align-items:center;gap:8px;margin:7px 0;font-style:normal}
.lstat .ldot{width:9px;height:9px;border-radius:50%;flex:none}
.lstat .lname{font-size:12px;font-weight:600;color:#f5f0e8;min-width:86px}
.lstat .lpct{font-size:11px;color:rgba(245,240,232,.55);min-width:30px;text-align:right}
.lstat .lbar{flex:1;height:6px;border-radius:3px;background:rgba(245,240,232,.1);overflow:hidden}
.lstat .lfill{height:100%;border-radius:3px}
.lsect{margin:12px 0 4px;font-size:10.5px;font-weight:700;letter-spacing:.1em;color:rgba(201,168,106,.85);text-transform:uppercase}
.lblend{margin-top:2px}
.ltwigs{margin-top:2px}
.ltwig{display:flex;align-items:center;justify-content:space-between;background:rgba(245,240,232,.05);border:1px solid rgba(201,168,106,.2);border-radius:8px;padding:8px 10px;margin:5px 0;min-height:44px}
.ltwig .lname{font-size:12.5px;font-weight:600;color:#f5f0e8}
.ltwig .ldomain{font-size:11px;color:rgba(245,240,232,.55);font-style:italic}
.lmarket{margin-top:4px;border-top:1px solid rgba(201,168,106,.2);padding-top:2px}
.lavatar-sect{margin-top:2px}
.lavatar-row{display:flex;gap:12px;align-items:center;margin:6px 0}
.lavatar-ph{position:relative;flex:none;border-radius:50%;overflow:hidden}
.lavatar-qqq{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:800;letter-spacing:.08em;color:rgba(245,240,232,.75)}
.lavatar-img{flex:none;border-radius:50%;object-fit:cover;border:2px solid rgba(201,168,106,.5)}
.lavatar-panel{display:block;width:100%;max-height:340px;object-fit:cover;object-position:top center;border-radius:12px;border:1px solid rgba(201,168,106,.25);margin:8px 0 2px}
.lavatar-meta{flex:1;min-width:0}
.lavatar-meta .lnote{margin:0}
.lavatar-btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}
.lavatar-btns .lcta{margin-top:6px}
.lavatar-upload{margin-top:8px}
.lavatar-input{width:100%;background:#0b0b0f;border:1px solid rgba(242,240,234,.2);border-radius:10px;padding:10px 14px;color:#f5f0e8;font-size:13px;font-family:inherit;min-height:44px;box-sizing:border-box}
.lavatar-input:focus{border-color:#e8c476;outline:none}
.lavatar-err{font-style:normal;color:#e89a9a;font-size:11.5px;margin:6px 0 0}
.lnarr{max-height:340px;overflow-y:auto}
.lfoot{margin:10px 6px 0;text-align:center;font-size:10.5px;color:rgba(245,240,232,.45);line-height:1.6}
.lrow-t{display:block;font-size:13.5px;font-weight:700;color:#f5f0e8}
.lrow-d{display:block;font-size:11.5px;font-weight:400;color:rgba(245,240,232,.55);margin-top:2px;line-height:1.45}
.llegacy{margin-top:6px}
.lgrow{padding:18px 6px;text-align:center}
.lgrow .lgrow-t{font-size:15px;font-weight:700;font-style:normal;color:#f5f0e8;margin-bottom:8px}
.lgrow p{font-style:normal;color:rgba(245,240,232,.6);font-size:13px;line-height:1.65;max-width:300px;margin-left:auto;margin-right:auto}
.lsheet-view{min-height:200px}
.lsheet-view .lsub{font-style:normal}
.lavatar-head{display:flex;gap:12px;align-items:center;margin-bottom:2px}
.lavatar-head h3{margin:0}
.nsh-panel{user-select:text;-webkit-user-select:text}
      `}</style>
      <div className="lhead">
        <h2>
          The <em>Living Tree</em>
        </h2>
        <p>
          Seven strands braid through the trunk and root below. Your council branches above — Mentor, Champion,
          Guardian, Maverick, Ambassador, Conductor, and the Skeptic. Tap a branch to meet its character; the
          marketplace lives one tap deeper, inside each branch.
        </p>
        <div className="llegend" aria-hidden="true">
          {BRAID_ORDER.map((key) => {
            const s = STRANDS.find((x) => x.key === key)!
            return (
              <span key={key}>
                <i style={{ background: s.color }} />
                {s.agentName}
              </span>
            )
          })}
        </div>
      </div>
      <svg
        className="lsvg"
        viewBox={viewBox}
        role="img"
        aria-label="Braided living tree"
        style={{ display: 'block', width: '100%', height: 'auto', minHeight: 200 }}
      >
        {/* braided trunk */}
        <g>
          {braid.map((s, i) => (
            <g key={i}>
              <path d={s.d} fill="none" stroke="#241d12" strokeWidth={7} strokeLinecap="round" />
              <path d={s.d} fill="none" stroke={s.color} strokeWidth={4} strokeLinecap="round" opacity={0.9} />
            </g>
          ))}
        </g>
        {/* branches */}
        <g>
          {nodes.flatMap((p) => {
            if (!p.par) return []
            const par = nodeById.get(p.par)
            if (!par) return []
            const col = strandCol(p)
            const isSkeptic = p.datum.archetype?.is_skeptic
            let sx = par.x
            let sy = par.y
            if (p.depth === 1) {
              sx = braidX(p.sidx, p.side === 'up' ? TRUNK_TOP : TRUNK_BOTTOM)
              sy = p.side === 'up' ? TRUNK_TOP : TRUNK_BOTTOM
            }
            const d = pathD(p.x, p.y, sx, sy)
            const key = `${p.par}>${p.datum.id}`
            return [
              <path key={`${key}-u`} d={d} fill="none" stroke="#241d12" strokeWidth={p.w + 4} strokeLinecap="round" opacity={p.op * 0.9} />,
              <path
                key={`${key}-m`}
                d={d}
                fill="none"
                stroke={col}
                strokeWidth={p.w}
                strokeLinecap="round"
                strokeDasharray={isSkeptic ? '7 5' : undefined}
                opacity={p.op * (isSkeptic ? 0.75 : 1)}
              />,
            ]
          })}
        </g>
        {/* nodes */}
        <g>
          {nodes.map((p) => {
            const col = strandCol(p)
            const selected = sel === p.datum.id
            const isYou = p.side === 'c'
            const isSkeptic = p.datum.archetype?.is_skeptic
            const collapsed = p.kids.length > 0 && !exp[p.datum.id]
            const faceR = nodeR(p)
            const initialsText = isYou ? initials ?? 'YOU' : p.datum.name.split(' ')[0].slice(0, 2).toUpperCase()
            // Keystone attention: a seat that wants the user carries a small
            // "!" badge at its top-right, in the app's amber attention
            // accent. Decorative — it lives inside the node's own <g>, so
            // the full node stays the tap target (44px rule untouched).
            const attnMarker = p.datum.archetype ? attention?.markers[p.datum.archetype.id] : undefined
            const showMarker = !!attnMarker?.attention
            return (
              <g
                key={p.datum.id}
                className="lnode"
                transform={`translate(${p.x},${p.y})`}
                opacity={p.op}
                onClick={() => onTap(p.datum.id)}
              >
                <circle
                  className="face"
                  r={faceR}
                  stroke={col}
                  strokeWidth={selected ? 3 : 1.8}
                  strokeDasharray={isSkeptic ? '5 4' : undefined}
                  fill={isSkeptic ? '#0b0a09' : undefined}
                  style={selected ? { filter: `drop-shadow(0 0 8px ${col})` } : undefined}
                />
                <text className="nm" y={isYou ? 7 : 4} style={{ fontSize: isYou ? '15px' : '9px' }}>
                  {initialsText}
                </text>
                {showMarker && (
                  <g
                    className="attn"
                    transform={`translate(${faceR * 0.78}, ${-faceR * 0.78})`}
                    role="img"
                    aria-label={markerTitle(p.datum.archetype!.id, attnMarker.reason)}
                  >
                    <title>{markerTitle(p.datum.archetype!.id, attnMarker.reason)}</title>
                    <circle className="attndot" r={7.5} fill={USER_WEAVE_COLOR} stroke="#0b0a09" strokeWidth={1.5} />
                    <text className="attnt" y={3.8} style={{ fontSize: '10.5px', fontWeight: 800, fill: '#0b0a09' }}>!</text>
                  </g>
                )}
                {collapsed && (
                  <>
                    <circle
                      className="bud"
                      r={7}
                      cx={Math.cos(p.ang) * 26}
                      cy={Math.sin(p.ang) * 26}
                      stroke={col}
                    />
                    <text
                      className="budt"
                      x={Math.cos(p.ang) * 26}
                      y={Math.sin(p.ang) * 26 + 3}
                    >{`+${p.kids.length}`}</text>
                  </>
                )}
              </g>
            )
          })}
        </g>
        {/* label pills — top layer so branch lines never cross text */}
        <g>
          {nodes.map((p) => {
            const col = strandCol(p)
            const isYou = p.side === 'c'
            const label = isYou ? 'YOU · TAP FOR OPTIONS' : p.datum.name
            const fs = isYou ? 8 : p.depth >= 3 ? 6.5 : 7.5
            const rlx = isYou ? 0 : Math.cos(p.ang) * 36
            const rly = isYou ? 56 : Math.sin(p.ang) * 36
            const tw = label.length * fs * 0.56 + 14
            return (
              <g key={`lbl-${p.datum.id}`} opacity={p.op} style={{ pointerEvents: 'none' }}>
                <rect
                  x={p.x + rlx - tw / 2}
                  y={p.y + rly - 8}
                  width={tw}
                  height={16}
                  rx={8}
                  fill="#0b0a09"
                  stroke={col}
                  strokeWidth={0.8}
                />
                <text
                  x={p.x + rlx}
                  y={p.y + rly + 2.5}
                  textAnchor="middle"
                  fill="#f5f0e8"
                  style={{ fontSize: `${fs}px`, pointerEvents: 'none' }}
                >
                  {label}
                </text>
              </g>
            )
          })}
        </g>
      </svg>
      <div className="lnarr">{renderPanel()}</div>
      <div className="lfoot">
        Training first, rent later —<br />
        the tree is yours; the marketplace is a lens on it, one tap deep.
      </div>
      <NodeSheet
        open={!!sheetNode}
        onClose={closeSheet}
        onBack={sheetItem ? () => setSheetItem(null) : null}
        backLabel="Back to menu"
        title={sheetTitle}
        subtitle={sheetSubtitle}
      >
        {renderSheetBody()}
      </NodeSheet>
    </div>
  )
}
