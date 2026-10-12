/**
 * Living Tree — the home view. A functional family tree: the user at the
 * center of a braided trunk, trainable agents branching below as roots,
 * their markets opening above once there is training worth renting.
 *
 * Ported from the vanilla-JS/SVG prototype (treev3): golden-ratio layout
 * (each level shrinks length/width/spread by φ), leaf-count-weighted angular
 * sectors, a force-relaxation pass pulling toward φ anchors, an N-strand
 * braided trunk with analytically computed over-under weave, tap-to-bloom
 * nesting with +N buds, and solid-background label pills in a top SVG layer
 * so branch lines never cross text.
 *
 * Honest seed state: the 7 agents at 0% trained, no children, no markets,
 * no rentals, no dollar amounts. Training begins via "Upload source
 * materials".
 *
 * Rendering robustness: node positions live in React state (not a mutated
 * ref), and the initial state is the fully laid-out tree — so the SVG has
 * content on the very first paint, with no dependency on the animation loop
 * to populate it. Critical SVG sizing is inline so the graphic cannot
 * collapse even if the <style> block is ever stripped.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { BRAID_ORDER, STRANDS, strandColor, type StrandKey } from './strands'

const PHI = 1.618
const CX = 200
const TRUNK_TOP = 302
const TRUNK_BOTTOM = 438
const YOU_Y = 370

type TreeDatum = {
  id: string
  strand: StrandKey | null
  name: string
  /** Training percent 0–100, or null when not measurable. Honest seed: 0. */
  pct: number | null
  narrative: string
  kids?: TreeDatum[]
}

const NARRATIVES: Record<StrandKey, string> = {
  word: 'Your voice, unborrowed. Feed the Storyteller your writing — drafts, messages, the sentences you rewrote three times — and it learns how you actually sound. Right now it is a blank page.',
  number:
    'Your pattern-reader. The Patternist will learn how you weigh evidence and tradeoffs — but it has not seen your data yet.',
  image:
    'Your eye. The Seer will learn your visual taste — what you keep, what you cut — once you show it work you love.',
  sound:
    'Your ear. The Songwriter learns rhythm, cadence, and tone by listening to what you make and what moves you. Still silent.',
  body: 'Your hands. The Maker will learn how you build — your order of operations, what “done” means to you. No sawdust yet.',
  people:
    'Your way with people. The Mediator learns who you listen to, how you hold a room, what fairness costs you. No conversations yet.',
  self: 'Your compass. The Guide learns direction and leverage from the calls you have actually made. None logged yet.',
}

/** Roots: the 7 agents, ordered to follow the braid. Honest seed — 0%, no children. */
const DOWN: TreeDatum[] = BRAID_ORDER.map((key) => {
  const s = STRANDS.find((x) => x.key === key)!
  return { id: `agent-${key}`, strand: key, name: s.agentName, pct: 0, narrative: NARRATIVES[key], kids: [] }
})

/** Markets above the trunk. Honest seed — none yet; they open once there is training worth renting. */
const UP: TreeDatum[] = []

const YOU: TreeDatum = {
  id: 'you',
  strand: null,
  name: 'YOU',
  pct: null,
  narrative: 'Every decision you make trains the roots. Every rental grows the branches.',
  kids: [],
}

const MENU: Array<{ id: string; title: string; desc: string; cta?: 'vision_map' }> = [
  {
    id: 'upload',
    title: 'Upload source materials',
    desc: 'Drop in your ChatGPT, Claude, or X exports. Redaction happens at capture — nothing trains until you review and approve it.',
  },
  {
    id: 'projects',
    title: 'Current projects',
    desc: 'Your projects live in the Vision Map — open it to see everything in flight.',
    cta: 'vision_map',
  },
  { id: 'stats', title: 'Stats', desc: '' },
  {
    id: 'snapshot',
    title: 'Snapshot era',
    desc: 'Snapshots freeze your profile as a rentable era — automatic each year, plus after big training leaps. Nothing to snapshot yet: eras begin once training does.',
  },
  { id: 'login', title: 'Log in / out', desc: 'You are signed in on this device.' },
  {
    id: 'settings',
    title: 'Settings',
    desc: 'Consent scopes, cross-zone transfer asks, snapshot rhythm, actor attribution.',
  },
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

function layout(exp: Record<string, boolean>): Map<string, Placed> {
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
  const spU = spreadFor(UP.length)
  const spD = spreadFor(DOWN.length)
  UP.forEach((n, i) => {
    const a = -Math.PI / 2 - spU / 2 + (spU * i) / Math.max(1, UP.length - 1)
    place(n, CX, TRUNK_TOP, a, 130, spU, 5, 1, 'up', 'you', n.strand)
  })
  DOWN.forEach((n, i) => {
    const a = -Math.PI / 2 - spD / 2 + (spD * i) / Math.max(1, DOWN.length - 1)
    place(n, CX, TRUNK_BOTTOM, a, 120, spD, 4.6, 1, 'dn', 'you', n.strand)
  })
  return P
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
    need.set(id, id === 'you' ? 70 : 32 + labelWidth(p) * 0.58)
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

function strandCol(p: { side: string; strand: StrandKey | null }): string {
  if (p.side === 'c' || !p.strand) return '#c9a86a'
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

function findDatum(id: string): TreeDatum | null {
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
  return walk(UP) ?? walk(DOWN)
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export function LivingTreeView({
  onNavigate,
  initials,
}: {
  /** Navigate the app shell (e.g. onNavigate('vision_map') for Current projects). */
  onNavigate: (view: 'vision_map') => void
  /** Initials rendered on the central profile node; defaults to "YOU". */
  initials?: string
}) {
  const [sel, setSel] = useState<string | null>(null)
  const [exp, setExp] = useState<Record<string, boolean>>({})
  const [view, setView] = useState<'tree' | 'menu'>('tree')
  const [menuItem, setMenuItem] = useState<string | null>(null)

  const braid = useMemo(() => computeBraid(), [])
  // Target positions, recomputed synchronously whenever expansion changes.
  const target = useMemo(() => relax(layout(exp)), [exp])

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

  const onTap = (id: string) => {
    if (id === 'you') {
      setView((v) => (v === 'menu' ? 'tree' : 'menu'))
      setMenuItem(null)
      setSel(null)
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
    setSel((s) => (s === id ? null : id))
  }

  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.datum.id, n])), [nodes])

  const renderPanel = () => {
    if (view === 'menu') {
      if (menuItem) {
        const m = MENU.find((x) => x.id === menuItem)
        if (!m) return null
        return (
          <div>
            <button type="button" className="lback" onClick={() => setMenuItem(null)}>
              ‹ All options
            </button>
            <h3>{m.title}</h3>
            {m.id === 'stats' ? (
              <div className="lstats">
                <p className="lnote">
                  No rentals yet — training comes first. You set the price per zone when there is something worth
                  renting.
                </p>
                {STRANDS.map((s) => (
                  <div key={s.key} className="lstat">
                    <span className="ldot" style={{ background: s.color }} />
                    <span className="lname">{s.agentName}</span>
                    <span className="lpct">0%</span>
                    <div className="lbar">
                      <div className="lfill" style={{ width: '0%', background: s.color }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p>{m.desc}</p>
            )}
            {m.cta === 'vision_map' && (
              <button type="button" className="lcta" onClick={() => onNavigate('vision_map')}>
                Open the Vision Map ›
              </button>
            )}
          </div>
        )
      }
      return (
        <div>
          {MENU.map((m) => (
            <button key={m.id} type="button" className="lrow" onClick={() => setMenuItem(m.id)}>
              <span>{m.title}</span>
              <span className="lchev">›</span>
            </button>
          ))}
        </div>
      )
    }
    const d = sel ? findDatum(sel) : null
    if (!d) return <div className="lhint">Tap any node to read its story.</div>
    const live = nodeById.get(sel!)
    const col = live ? strandCol(live) : '#c9a86a'
    const tag = d.id === 'you' ? 'THE SOURCE' : d.pct == null ? 'NOT YET TRAINED' : `${d.pct}% TRAINED`
    return (
      <div>
        <h3>{d.name}</h3>
        <div className="ltag" style={{ color: col }}>
          {tag}
        </div>
        <p>“{d.narrative}”</p>
        {d.id !== 'you' && (
          <button
            type="button"
            className="lcta"
            onClick={() => {
              setView('menu')
              setMenuItem('upload')
            }}
          >
            Upload source materials to begin training ›
          </button>
        )}
      </div>
    )
  }

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
.lstats{margin-top:2px}
.lstat{display:flex;align-items:center;gap:8px;margin:7px 0;font-style:normal}
.lstat .ldot{width:9px;height:9px;border-radius:50%;flex:none}
.lstat .lname{font-size:12px;font-weight:600;color:#f5f0e8;min-width:86px}
.lstat .lpct{font-size:11px;color:rgba(245,240,232,.55);min-width:30px;text-align:right}
.lstat .lbar{flex:1;height:6px;border-radius:3px;background:rgba(245,240,232,.1);overflow:hidden}
.lstat .lfill{height:100%;border-radius:3px}
.lfoot{margin:10px 6px 0;text-align:center;font-size:10.5px;color:rgba(245,240,232,.45);line-height:1.6}
      `}</style>
      <div className="lhead">
        <h2>
          The <em>Living Tree</em>
        </h2>
        <p>
          Seven strands braid through the trunk — word, number, image, sound, body, people, self. Your roots grow
          below; their markets open above, once there is training worth renting. Tap a node to read its story; tap
          yourself for options.
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
        viewBox="-30 0 460 790"
        role="img"
        aria-label="Braided living tree"
        style={{ display: 'block', width: '100%', height: 'auto', aspectRatio: '460 / 790', minHeight: 200 }}
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
              <path key={`${key}-m`} d={d} fill="none" stroke={col} strokeWidth={p.w} strokeLinecap="round" opacity={p.op} />,
            ]
          })}
        </g>
        {/* nodes */}
        <g>
          {nodes.map((p) => {
            const col = strandCol(p)
            const selected = sel === p.datum.id
            const isYou = p.side === 'c'
            const collapsed = p.kids.length > 0 && !exp[p.datum.id]
            const faceR = isYou ? 34 : 12
            const initialsText = isYou ? initials ?? 'YOU' : p.datum.name.split(' ')[0].slice(0, 2).toUpperCase()
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
                  style={selected ? { filter: `drop-shadow(0 0 8px ${col})` } : undefined}
                />
                <text className="nm" y={isYou ? 7 : 4} style={{ fontSize: isYou ? '15px' : '9px' }}>
                  {initialsText}
                </text>
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
        follow a color upward and you will see which root earned, once they start earning.
      </div>
    </div>
  )
}
