/**
 * CairnStoneSprite — one painted sumi-e stone of a cairn pile.
 *
 * Rendering law (cairn port spec §4, learned on-device 2026-11-13):
 * the tint stack is a grayscale sprite image plus two blend layers
 * clipped by the sprite's own alpha (CSS mask). The construction that
 * PAINTS in WKWebView is the isolation test's row E: the stack exists
 * as document structure first, and a script assigns each blend layer's
 * mask + tint background AFTER the nodes are in the document. The
 * failing construction (row G) assigned masks to script-built nodes
 * while they were still detached. React builds DOM with script, so
 * this component follows row E's ordering inside React: render passes
 * structure only (img + two empty layers, NO mask/tint inline styles),
 * and a layout effect — which runs once the nodes are committed to
 * the document — assigns mask and background, exactly like the study
 * pages' post-parse cairnTintInit script.
 *
 * Layers: base grayscale img (the stone's own light and shadow),
 * `.cairn-tint-layer` (mix-blend-mode: color — the pile wash with
 * per-stone jitter, luminance preserved), `.cairn-soft-layer`
 * (mix-blend-mode: soft-light at 0.5 — depth). Both blend layers are
 * masked by the sprite's alpha so tint never escapes the silhouette.
 */
import { useLayoutEffect, useRef } from 'react'

export type CairnStoneSpriteProps = {
  /** Sprite image URL (vite asset). Also the mask source. */
  src: string
  /** This stone's tint (pile wash + member-keyed jitter), hex. */
  tint: string
}

export function CairnStoneSprite({ src, tint }: CairnStoneSpriteProps) {
  const stackRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const stack = stackRef.current
    if (!stack) return
    // Post-mount assignment (isolation row E): the shorthand mask, set
    // on both vendor forms, exactly as the proven study script does.
    const mask = `url("${src}") 0 0 / 100% 100% no-repeat`
    stack.querySelectorAll<HTMLElement>('.cairn-tint-layer, .cairn-soft-layer').forEach((l) => {
      l.style.webkitMask = mask
      l.style.mask = mask
      l.style.background = tint
    })
  }, [src, tint])

  return (
    <div ref={stackRef} className="cairn-tint-stack" data-tint={tint}>
      <img className="cairn-stone-base" src={src} alt="" draggable={false} />
      <div className="cairn-tint-layer" aria-hidden="true" />
      <div className="cairn-soft-layer" aria-hidden="true" />
    </div>
  )
}
