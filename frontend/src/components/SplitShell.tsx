/**
 * SplitShell — the seat-interface layout (founder, standing
 * direction 2026-11-19, restated 2026-11-24): a seat's world on the
 * left, its conversation on the right, a draggable divider between
 * them. The split engages on wide / landscape screens (the app's lg
 * breakpoint); each pane scrolls independently. On portrait / narrow
 * screens the panes stack and the surface scrolls as one.
 *
 * Shared by the seat interfaces (Aria's Atelier first; Valen's
 * Campaign Board and the Gardener's Bench adopt the same shell) —
 * the divider position is per-surface state, persisted under
 * `storageKey` when one is given so a seat remembers how its visitor
 * likes the conversation sized.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'

const WIDE_QUERY = '(min-width: 1024px)'

/** Wide enough for the split. No matchMedia (older jsdom, SSR) means
 *  desktop behaviour — the same convention as isCoarsePointer. */
function useWideScreen(): boolean {
  const [wide, setWide] = useState<boolean>(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true
    return window.matchMedia(WIDE_QUERY).matches
  })
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia(WIDE_QUERY)
    const onChange = () => setWide(mq.matches)
    onChange()
    if (typeof mq.addEventListener === 'function') {
      mq.addEventListener('change', onChange)
      return () => mq.removeEventListener('change', onChange)
    }
  }, [])
  return wide
}

function clampWidth(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n))
}

export default function SplitShell({
  left,
  right,
  storageKey,
  defaultChatWidth = 380,
  minChatWidth = 300,
  maxChatWidth = 680,
}: {
  /** The seat's world. */
  left: ReactNode
  /** The seat's conversation. */
  right: ReactNode
  /** When given, the divider position persists per surface. */
  storageKey?: string
  defaultChatWidth?: number
  minChatWidth?: number
  maxChatWidth?: number
}) {
  const wide = useWideScreen()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null)
  const [chatWidth, setChatWidth] = useState<number>(() => {
    if (storageKey && typeof window !== 'undefined') {
      try {
        const saved = Number(window.localStorage.getItem(`zenaf:split-chat-width:${storageKey}`))
        if (Number.isFinite(saved) && saved > 0) {
          return clampWidth(saved, minChatWidth, maxChatWidth)
        }
      } catch {
        /* storage is an enhancement; the default stands */
      }
    }
    return defaultChatWidth
  })

  const applyWidth = (n: number) => {
    const next = clampWidth(n, minChatWidth, maxChatWidth)
    setChatWidth(next)
    if (storageKey && typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(`zenaf:split-chat-width:${storageKey}`, String(next))
      } catch {
        /* persistence is an enhancement */
      }
    }
  }

  return (
    <div
      ref={containerRef}
      className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-y-auto lg:overflow-hidden"
    >
      <div className="flex-1 min-w-0 lg:min-h-0 lg:overflow-y-auto">{left}</div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize the conversation pane"
        aria-valuenow={Math.round(chatWidth)}
        aria-valuemin={minChatWidth}
        aria-valuemax={maxChatWidth}
        tabIndex={0}
        data-testid="split-divider"
        className="hidden lg:flex w-2.5 shrink-0 cursor-col-resize touch-none select-none items-stretch justify-center group"
        onPointerDown={(e) => {
          dragRef.current = { startX: e.clientX, startWidth: chatWidth }
          try {
            ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
          } catch {
            /* capture is an enhancement */
          }
        }}
        onPointerMove={(e) => {
          const drag = dragRef.current
          if (!drag) return
          applyWidth(drag.startWidth + (drag.startX - e.clientX))
        }}
        onPointerUp={() => {
          dragRef.current = null
        }}
        onPointerCancel={() => {
          dragRef.current = null
        }}
        onKeyDown={(e) => {
          const step = e.shiftKey ? 48 : 16
          if (e.key === 'ArrowLeft') {
            e.preventDefault()
            applyWidth(chatWidth + step)
          } else if (e.key === 'ArrowRight') {
            e.preventDefault()
            applyWidth(chatWidth - step)
          }
        }}
      >
        <span className="w-px bg-stone-700/60 group-hover:bg-amber-200/60 group-focus:bg-amber-200/60" />
      </div>
      <div
        className="shrink-0 lg:min-h-0 lg:overflow-y-auto border-t lg:border-t-0 border-stone-700/60"
        style={wide ? { width: chatWidth } : undefined}
        data-testid="split-right"
      >
        {right}
      </div>
    </div>
  )
}
