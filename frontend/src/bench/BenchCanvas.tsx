/**
 * The Bench scene on canvas: the grown tree painted by paint.ts
 * (the canonical machinery's geometry and painters), with the
 * prototype's tap geometry over it — a target at each branch's tip
 * and at its 75% point, at each twig's tip and 75% point, one at
 * each wire coil (branch or twig), one on the footing triangle,
 * one on the pencil stroke. The canvas is the interface;
 * the buttons are invisible, named, and keyboard-reachable.
 */
import { useEffect, useMemo, useRef } from 'react'
import { footingTriangle, paintScene, SCENE_H, SCENE_W, type SceneModel } from './paint'
import type { Pt } from './growth'

export interface TapTargets {
  branches: Array<{ id: string; name: string; tip: Pt; p75: Pt; coil: Pt | null }>
  twigs: Array<{ id: string; name: string; tip: Pt; p75: Pt; coil: Pt | null }>
  footing: { x: number; y: number; w: number; h: number } | null
  pencilMid: Pt | null
}

function pointAlong(pts: readonly Pt[], f: number): Pt {
  const i = Math.min(pts.length - 1, Math.max(0, Math.trunc(f * (pts.length - 1))))
  return pts[i]
}

export function buildTapTargets(
  model: SceneModel,
  branchNames: ReadonlyMap<string, string>,
): TapTargets {
  const branches: TapTargets['branches'] = []
  for (const b of model.branches) {
    const primary = model.grown.primaries.get(b.id)
    if (!primary || primary.length < 2) continue
    branches.push({
      id: b.id,
      name: branchNames.get(b.id) ?? b.id,
      tip: primary[primary.length - 1],
      p75: pointAlong(primary, 0.75),
      coil: b.wireSeatColour ? pointAlong(primary, 0.35) : null,
    })
  }
  const twigs: TapTargets['twigs'] = []
  for (const t of model.twigs) {
    const path = model.grown.recordTwigs.find((r) => r.handle === t.id)?.pts
    if (!path || path.length < 2) continue
    twigs.push({
      id: t.id,
      name: branchNames.get(t.id) ?? t.id,
      tip: path[path.length - 1],
      p75: pointAlong(path, 0.75),
      coil: t.wireSeatColour ? pointAlong(path, 0.35) : null,
    })
  }
  const ft = footingTriangle(model.footing)
  return {
    branches,
    twigs,
    footing: ft?.box ?? null,
    pencilMid: model.pencil
      ? [
          model.pencil.start[0] + model.pencil.u[0] * model.pencil.length * 0.5,
          model.pencil.start[1] + model.pencil.u[1] * model.pencil.length * 0.5,
        ]
      : null,
  }
}

const pct = (v: number, total: number) => `${(v / total) * 100}%`

export default function BenchCanvas({
  model,
  branchNames,
  selectedId,
  onSelectBranch,
  onSelectTwig,
  onTapWire,
  onTapFooting,
  onTapPencil,
}: {
  model: SceneModel
  branchNames: ReadonlyMap<string, string>
  selectedId: string | null
  onSelectBranch: (id: string) => void
  onSelectTwig: (id: string) => void
  onTapWire: (id: string) => void
  onTapFooting: () => void
  onTapPencil: () => void
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const targets = useMemo(() => buildTapTargets(model, branchNames), [model, branchNames])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return // jsdom / no-2d: the tap targets still carry the surface
    ctx.setTransform(2, 0, 0, 2, 0, 0)
    paintScene(ctx, model)
  }, [model])

  const selectedTip =
    targets.branches.find((b) => b.id === selectedId)?.tip ??
    targets.twigs.find((t) => t.id === selectedId)?.tip ??
    null

  return (
    <div className="relative w-full" style={{ aspectRatio: `${SCENE_W}/${SCENE_H}` }}>
      <canvas
        ref={canvasRef}
        width={SCENE_W * 2}
        height={SCENE_H * 2}
        className="absolute inset-0 w-full h-full block rounded-lg"
        role="img"
        aria-label="The tree on the bench"
      />
      {selectedTip && (
        <div
          aria-hidden="true"
          className="absolute rounded-full pointer-events-none"
          style={{
            left: pct(selectedTip[0], SCENE_W),
            top: pct(selectedTip[1], SCENE_H),
            width: '9%',
            aspectRatio: '1/1',
            transform: 'translate(-50%,-50%)',
            border: '2.5px solid #7c4a21',
            boxShadow: '0 0 0 2px rgba(255,250,240,.65)',
          }}
        />
      )}
      {targets.footing && (
        <button
          type="button"
          aria-label="Footing — open the notebook"
          data-tap="footing"
          onClick={onTapFooting}
          className="absolute bg-transparent border-0 cursor-pointer"
          style={{
            left: pct(targets.footing.x, SCENE_W),
            top: pct(targets.footing.y, SCENE_H),
            width: pct(targets.footing.w, SCENE_W),
            height: pct(targets.footing.h, SCENE_H),
          }}
        />
      )}
      {targets.branches.map((b) => (
        <span key={b.id}>
          {[b.tip, b.p75].map((p, i) => (
            <button
              key={i}
              type="button"
              aria-label={b.name}
              data-tap="branch"
              data-branch={b.id}
              onClick={() => onSelectBranch(b.id)}
              className="absolute bg-transparent border-0 rounded-full cursor-pointer"
              style={{
                left: pct(p[0], SCENE_W),
                top: pct(p[1], SCENE_H),
                width: '11%',
                aspectRatio: '1/1',
                transform: 'translate(-50%,-50%)',
              }}
            />
          ))}
          {b.coil && model.showExploratory && (
            <button
              type="button"
              aria-label={`Proposal on ${b.name}`}
              data-tap="wire"
              data-branch={b.id}
              onClick={() => onTapWire(b.id)}
              className="absolute bg-transparent border-0 rounded-full cursor-pointer"
              style={{
                left: pct(b.coil[0], SCENE_W),
                top: pct(b.coil[1], SCENE_H),
                width: '11%',
                aspectRatio: '1/1',
                transform: 'translate(-50%,-50%)',
              }}
            />
          )}
        </span>
      ))}
      {targets.twigs.map((t) => (
        <span key={t.id}>
          {[t.tip, t.p75].map((p, i) => (
            <button
              key={i}
              type="button"
              aria-label={t.name}
              data-tap="twig"
              data-twig={t.id}
              onClick={() => onSelectTwig(t.id)}
              className="absolute bg-transparent border-0 rounded-full cursor-pointer"
              style={{
                left: pct(p[0], SCENE_W),
                top: pct(p[1], SCENE_H),
                width: '9%',
                aspectRatio: '1/1',
                transform: 'translate(-50%,-50%)',
              }}
            />
          ))}
          {t.coil && model.showExploratory && (
            <button
              type="button"
              aria-label={`Proposal on ${t.name}`}
              data-tap="wire"
              data-twig={t.id}
              onClick={() => onTapWire(t.id)}
              className="absolute bg-transparent border-0 rounded-full cursor-pointer"
              style={{
                left: pct(t.coil[0], SCENE_W),
                top: pct(t.coil[1], SCENE_H),
                width: '9%',
                aspectRatio: '1/1',
                transform: 'translate(-50%,-50%)',
              }}
            />
          )}
        </span>
      ))}
      {targets.pencilMid && model.showExploratory && model.pencil && (
        <button
          type="button"
          aria-label="Being considered in this conversation"
          data-tap="pencil"
          onClick={onTapPencil}
          className="absolute bg-transparent border-0 rounded-full cursor-pointer"
          style={{
            left: pct(targets.pencilMid[0], SCENE_W),
            top: pct(targets.pencilMid[1], SCENE_H),
            width: '11%',
            aspectRatio: '1/1',
            transform: 'translate(-50%,-50%)',
          }}
        />
      )}
    </div>
  )
}

/** Shelf-scale render: the same grown scene, fitted into a small
 *  canvas (tree + pot + a strip of bench), no tap targets — the
 *  whole shelf tile is the button. */
export function ShelfCanvas({ model, label }: { model: SceneModel; label: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    // content bounds from the grown geometry + the pot/bench strip
    let minX = 330
    let maxX = 470
    let minY = 560
    let maxY = 606
    for (const w of model.grown.wood) {
      for (const [x, y] of w.pts) {
        if (x < minX) minX = x
        if (x > maxX) maxX = x
        if (y < minY) minY = y
      }
    }
    for (const t of model.grown.recordTwigs) {
      for (const [x, y] of t.pts) {
        if (x < minX) minX = x
        if (x > maxX) maxX = x
        if (y < minY) minY = y
      }
    }
    for (const pads of model.grown.padsByHandle.values()) {
      for (const p of pads) {
        minX = Math.min(minX, p.c[0] - p.rx)
        maxX = Math.max(maxX, p.c[0] + p.rx)
        minY = Math.min(minY, p.c[1] - p.ry)
      }
    }
    minX -= 14
    maxX += 14
    minY -= 12
    const bw = maxX - minX
    const bh = maxY - minY
    const W = 480
    const H = 360
    const scale = Math.min(W / bw, H / bh)
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.clearRect(0, 0, W, H)
    ctx.translate((W - bw * scale) / 2, (H - bh * scale) / 2)
    ctx.scale(scale, scale)
    ctx.translate(-minX, -minY)
    paintScene(ctx, model)
  }, [model])
  return (
    <canvas
      ref={canvasRef}
      width={480}
      height={360}
      className="block w-full h-full"
      role="img"
      aria-label={label}
    />
  )
}
