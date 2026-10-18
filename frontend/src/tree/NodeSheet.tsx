import { useEffect, type ReactNode } from 'react'

/**
 * NodeSheet — the tree-as-organism surface (phase 1).
 *
 * Tapping a tree node opens this instead of navigating to a page: a bottom
 * sheet on phone widths, a side panel on desktop. Closing returns to the
 * tree — there are no breadcrumbs because you never left.
 *
 * Composition, not rewrite: it mounts arbitrary children (the real existing
 * views), so later phases slot new node menus in without touching the tree.
 *
 * Load-bearing rules: no badge counts, no red dots anywhere; every touch
 * target >= 44px; animation subtle and fast.
 */
export function NodeSheet({
  open,
  onClose,
  title,
  subtitle,
  onBack,
  backLabel,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: string
  /** When set, a back chevron appears in the header (sheet-internal navigation). */
  onBack?: (() => void) | null
  backLabel?: string
  children: ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="nsh-root" role="dialog" aria-modal="true" aria-label={title}>
      <style>{`
.nsh-root{position:fixed;inset:0;z-index:60;font-family:system-ui,-apple-system,sans-serif;-webkit-tap-highlight-color:transparent}
.nsh-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.55);animation:nsh-fade .22s ease-out}
.nsh-panel{position:absolute;left:0;right:0;bottom:0;max-height:88vh;max-height:88dvh;display:flex;flex-direction:column;background:#0b0a09;border:1px solid rgba(201,168,106,.3);border-bottom:none;border-radius:20px 20px 0 0;color:#f5f0e8;animation:nsh-up .24s ease-out;box-shadow:0 -12px 48px rgba(0,0,0,.5)}
.nsh-grab{width:40px;height:4px;border-radius:2px;background:rgba(245,240,232,.25);margin:10px auto 0;flex:none}
.nsh-head{display:flex;align-items:center;gap:10px;padding:8px 12px 10px;border-bottom:1px solid rgba(201,168,106,.18);flex:none}
.nsh-titles{flex:1;min-width:0}
.nsh-titles h2{margin:0;font-size:16px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nsh-titles p{margin:2px 0 0;font-size:11.5px;color:rgba(245,240,232,.55);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nsh-back,.nsh-close{flex:none;min-width:44px;min-height:44px;display:inline-flex;align-items:center;justify-content:center;background:rgba(245,240,232,.06);border:1px solid rgba(201,168,106,.25);border-radius:12px;color:#f5f0e8;font-size:20px;line-height:1;cursor:pointer;font-family:inherit;padding:0}
.nsh-back:active,.nsh-close:active{background:rgba(201,168,106,.18)}
.nsh-body{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;padding:14px 14px 24px;-webkit-overflow-scrolling:touch;overscroll-behavior:contain}
@keyframes nsh-up{from{transform:translateY(24px);opacity:.55}to{transform:none;opacity:1}}
@keyframes nsh-fade{from{opacity:0}to{opacity:1}}
@media (min-width:1024px){
  .nsh-panel{left:auto;top:0;bottom:0;right:0;width:min(480px,44vw);max-height:none;border-radius:0;border-right:none;border-top:none;border-bottom:none;animation:nsh-in .24s ease-out}
  .nsh-grab{display:none}
}
@keyframes nsh-in{from{transform:translateX(32px);opacity:.55}to{transform:none;opacity:1}}
@media (prefers-reduced-motion:reduce){
  .nsh-backdrop,.nsh-panel{animation:none}
}
      `}</style>
      <div className="nsh-backdrop" onClick={onClose} aria-hidden="true" />
      <section className="nsh-panel">
        <div className="nsh-grab" aria-hidden="true" />
        <header className="nsh-head">
          {onBack ? (
            <button
              type="button"
              className="nsh-back"
              onClick={onBack}
              aria-label={backLabel ?? 'Back to menu'}
            >
              ‹
            </button>
          ) : null}
          <div className="nsh-titles">
            <h2>{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          <button
            type="button"
            className="nsh-close"
            onClick={onClose}
            aria-label="Close panel"
          >
            ×
          </button>
        </header>
        <div className="nsh-body">{children}</div>
      </section>
    </div>
  )
}
