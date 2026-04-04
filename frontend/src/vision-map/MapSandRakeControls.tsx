import { useCallback } from 'react'
import type { RefObject } from 'react'
import type { ZenSandCanvasHandle } from './ZenSandCanvas'

const FADE_OPTIONS_SEC = [12, 16, 20] as const

type Props = {
  sandRef: RefObject<ZenSandCanvasHandle | null>
  rakeEnabled: boolean
  onRakeEnabledChange: (next: boolean) => void
  fadeSec: (typeof FADE_OPTIONS_SEC)[number]
  onFadeSecChange: (next: (typeof FADE_OPTIONS_SEC)[number]) => void
}

function IconClearSand({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 20h16M6 17h12l-1.2-9H7.2L6 17zM9 8V5h6v3M8 8h8"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function IconRake({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M5 19h14M7 15V5M10 15V6M13 15V5.5M16 15V6M19 15V5"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function IconFade({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 5c-4 3.5-6 6.2-6 8.5a6 6 0 1 0 12 0c0-2.3-2-5-6-8.5z"
        stroke="currentColor"
        strokeWidth="1.65"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

const btnIcon =
  'flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-zinc-950 transition-colors hover:bg-stone-400/35 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-amber-600/70 disabled:opacity-40'

const btnFade =
  'flex h-9 min-w-[3.75rem] shrink-0 items-center justify-center gap-1 rounded-md px-2 text-zinc-950 transition-colors hover:bg-stone-400/35 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-amber-600/70'

export function MapSandRakeControls({
  sandRef,
  rakeEnabled,
  onRakeEnabledChange,
  fadeSec,
  onFadeSecChange,
}: Props) {
  const clearSand = useCallback(() => {
    sandRef.current?.clearRakePaths()
  }, [sandRef])

  const cycleFade = useCallback(() => {
    const i = FADE_OPTIONS_SEC.indexOf(fadeSec)
    const next = FADE_OPTIONS_SEC[(i + 1) % FADE_OPTIONS_SEC.length]!
    onFadeSecChange(next)
  }, [fadeSec, onFadeSecChange])

  const fadePresetIndex = FADE_OPTIONS_SEC.indexOf(fadeSec)
  const fadeVersion = fadePresetIndex >= 0 ? fadePresetIndex + 1 : 1

  return (
    <div
      className="pointer-events-auto absolute top-4 right-4 z-[25] flex items-center gap-0.5 rounded-xl border border-stone-500/35 bg-[#ebe7df]/95 p-1 shadow-lg backdrop-blur-md"
      role="toolbar"
      aria-label="Sand rake"
    >
      <button
        type="button"
        className={btnIcon}
        onClick={clearSand}
        title="Clear sand — remove all rake marks"
        aria-label="Clear sand"
      >
        <IconClearSand />
      </button>
      <button
        type="button"
        className={`${btnIcon} ${rakeEnabled ? 'bg-amber-200/55 text-zinc-950 ring-1 ring-amber-600/35' : 'text-zinc-950/55'}`}
        onClick={() => onRakeEnabledChange(!rakeEnabled)}
        title={
          rakeEnabled
            ? 'Rake on — pointer over the map sculpts sand (no click)'
            : 'Rake off — pointer does not affect sand'
        }
        aria-label={rakeEnabled ? 'Turn rake off' : 'Turn rake on'}
        aria-pressed={rakeEnabled}
      >
        <IconRake />
      </button>
      <button
        type="button"
        className={btnFade}
        onClick={cycleFade}
        title={`Auto-fade preset ${fadeVersion} of ${FADE_OPTIONS_SEC.length}: ${fadeSec}s idle — click to cycle 12 / 16 / 20`}
        aria-label={`Auto-fade rake after ${fadeSec} seconds idle; click to cycle duration`}
      >
        <IconFade />
        <span className="text-[11px] font-semibold tabular-nums leading-none whitespace-nowrap">
          <span className="text-zinc-600">v{fadeVersion}</span>
          <span className="text-zinc-400 mx-0.5" aria-hidden>
            ·
          </span>
          <span className="text-zinc-950">{fadeSec}s</span>
        </span>
      </button>
    </div>
  )
}
