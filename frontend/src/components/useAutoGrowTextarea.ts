import { useEffect, useRef } from 'react'

/** Max composer height: about five lines of text. Past that the box scrolls. */
export const MAX_COMPOSER_HEIGHT_PX = 140

/**
 * Auto-growing textarea for the chat composers (MeetingView, CouncilChat).
 *
 * The box grows with its content up to the cap, then scrolls — so a
 * multi-paragraph message can be composed in place instead of in a
 * single-line input. Pass the current value; the height resets when
 * the value is cleared (send). The textarea keeps min-h-[44px] from
 * its className, so it never shrinks below one line.
 */
export function useAutoGrowTextarea(value: string) {
  const ref = useRef<HTMLTextAreaElement | null>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_COMPOSER_HEIGHT_PX)}px`
  }, [value])
  return ref
}
