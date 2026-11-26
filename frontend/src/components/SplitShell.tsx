/**
 * SplitShell — the seat-interface layout (founder, standing
 * direction 2026-11-19, restated 2026-11-24 and 2026-11-25): a
 * seat's world on the left, its conversation on the right, a
 * draggable divider between them. The split engages on wide /
 * landscape screens; each pane scrolls independently. On portrait /
 * narrow screens the panes stack and the surface scrolls as one.
 *
 * Shared by all five seat interfaces (Aria's Atelier, Severine's
 * Bench, Maeve's Living Palace, Valen's Campaign Board, Jynx's
 * Scroll) — the divider position is per-surface state, persisted
 * under `storageKey` when one is given so a seat remembers how its
 * visitor likes the conversation sized.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'

const WIDE_QUERY = '(min-width: 1024px)'
const LANDSCAPE_QUERY = '(orientation: landscape) and (min-width: 640px)'

/**
 * The one split-engagement rule (founder, 2026-11-25): the split
 * is engaged ⇔ the screen is wide (≥1024px) OR it is a landscape
 * screen at least 640px wide — so a phone held sideways splits,
 * while portrait (which may stay stacked) does not. No matchMedia
 * (older jsdom, SSR) means desktop behaviour — the same convention
 * as isCoarsePointer.
 */
export function useSplitScreen(): boolean {
  const compute = (): boolean => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true
    return (
      window.matchMedia(WIDE_QUERY).matches || window.matchMedia(LANDSCAPE_QUERY).matches
    )
  }
  const [split, setSplit] = useState<boolean>(compute)
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const wideMq = window.matchMedia(WIDE_QUERY)
    const landscapeMq = window.matchMedia(LANDSCAPE_QUERY)
    const onChange = () => setSplit(wideMq.matches || landscapeMq.matches)
    onChange()
    const removers: Array<() => void> = []
    for (const mq of [wideMq, landscapeMq]) {
      if (typeof mq.addEventListener === 'function') {
        mq.addEventListener('change', onChange)
        removers.push(() => mq.removeEventListener('change', onChange))
      }
    }
    return () => removers.forEach((remove) => remove())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return split
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
  const split = useSplitScreen()
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
      data-split={split ? 'true' : 'false'}
      className={
        split
          ? 'flex-1 flex flex-row min-h-0 overflow-hidden'
          : 'flex-1 flex flex-col min-h-0 overflow-y-auto'
      }
    >
      <div
        className={
          split ? 'flex-1 min-w-0 min-h-0 overflow-y-auto' : 'flex-1 min-w-0'
        }
      >
        {left}
      </div>
      {split && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the conversation pane"
          aria-valuenow={Math.round(chatWidth)}
          aria-valuemin={minChatWidth}
          aria-valuemax={maxChatWidth}
          tabIndex={0}
          data-testid="split-divider"
          className="flex w-2.5 shrink-0 cursor-col-resize touch-none select-none items-stretch justify-center group"
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
      )}
      <div
        className={
          split
            ? 'shrink-0 min-h-0 overflow-y-auto'
            : 'shrink-0 border-t border-stone-700/60'
        }
        style={split ? { width: chatWidth } : undefined}
        data-testid="split-right"
      >
        {right}
      </div>
    </div>
  )
}
