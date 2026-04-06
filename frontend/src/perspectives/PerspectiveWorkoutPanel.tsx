import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import type { PerspectiveAgent } from './types'
import type { WorkoutMessage } from './workoutTypes'
import { AvatarDisplay } from '../components/AvatarDisplay'
import { ResonanceSlider } from '../components/ResonanceSlider'
import { appendChatDroppedFiles, dataTransferHasFiles } from '../conversation/chatFileDrop'

export function PerspectiveWorkoutPanel({
  perspective,
  thread,
  input,
  onInputChange,
  onSendSeat1,
  onInvokeSeat,
  invokingSeatId,
  availableSeats,
  onRequestExit,
}: {
  perspective: PerspectiveAgent
  thread: WorkoutMessage[]
  input: string
  onInputChange: (v: string) => void
  onSendSeat1: () => void
  onInvokeSeat: (agent: PerspectiveAgent) => void
  invokingSeatId: string | null
  availableSeats: PerspectiveAgent[]
  onRequestExit: () => void
}) {
  const threadEndRef = useRef<HTMLDivElement | null>(null)
  const pName = (perspective.name || 'Perspective').trim() || 'Perspective'
  const [dragActive, setDragActive] = useState(false)
  const inputRef = useRef(input)
  inputRef.current = input

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [thread.length, invokingSeatId])

  const busy = invokingSeatId != null

  const onWorkoutDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    if (!dataTransferHasFiles(e.dataTransfer)) return
    e.preventDefault()
    e.stopPropagation()
    e.dataTransfer.dropEffect = 'copy'
    setDragActive(true)
  }, [])

  const onWorkoutDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    const t = e.currentTarget
    const rel = e.relatedTarget as Node | null
    if (rel && t.contains(rel)) return
    setDragActive(false)
  }, [])

  const onWorkoutDrop = useCallback(
    async (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      e.stopPropagation()
      setDragActive(false)
      if (busy) return
      const files = e.dataTransfer.files
      if (!files?.length) return
      const next = await appendChatDroppedFiles(inputRef.current, files)
      onInputChange(next)
      requestAnimationFrame(() => {
        const el = document.getElementById('workout-reply') as HTMLTextAreaElement | null
        if (!el) return
        el.focus()
        const len = el.value.length
        el.setSelectionRange(len, len)
      })
    },
    [busy, onInputChange],
  )

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden bg-stone-900/40">
      <div className="shrink-0 p-3 border-b border-stone-700 space-y-1">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onRequestExit}
            className="shrink-0 text-stone-300 hover:text-stone-100 text-lg leading-none px-1 py-0.5 rounded"
            title="End workout"
            aria-label="Back, end workout"
          >
            ←
          </button>
          <AvatarDisplay agent={perspective} size="md" className="text-stone-200 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium text-amber-200/90 uppercase tracking-wide">Workout</p>
            <p className="text-sm font-semibold text-stone-100 truncate" title={pName}>
              {pName}
            </p>
          </div>
        </div>
        <p className="text-xs text-warm-white/40 pl-8">
          Seat 1 · {pName}
        </p>
      </div>

      <div className="shrink-0 px-3 pt-3">
        <div className="rounded-lg bg-surface-raised border border-[color:var(--color-accent)] px-3 py-2 flex items-center gap-2">
          <AvatarDisplay agent={perspective} size="sm" className="text-stone-200 shrink-0" />
          <div className="min-w-0">
            <p className="text-xs font-medium text-stone-100 truncate">{pName}</p>
            {perspective.role ? (
              <p className="text-[10px] text-stone-500 truncate">{perspective.role}</p>
            ) : null}
          </div>
        </div>
      </div>

      <div
        className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden p-3 space-y-3 overscroll-contain"
        onDragOver={onWorkoutDragOver}
        onDragLeave={onWorkoutDragLeave}
        onDrop={(e) => void onWorkoutDrop(e)}
      >
        {thread.length === 0 ? (
          <div className="flex flex-col items-center justify-center min-h-[120px] text-center px-4">
            <p className="text-sm text-warm-white/30">
              Describe a scenario or ask {pName} something
            </p>
          </div>
        ) : null}
        {thread.map((m) => {
          if (m.kind === 'user') {
            return (
              <div key={m.id} className="flex justify-end">
                <div className="max-w-[92%] rounded-lg px-3 py-2 text-xs bg-surface-raised text-stone-100 whitespace-pre-wrap border border-stone-600/80">
                  {m.content}
                </div>
              </div>
            )
          }
          if (m.kind === 'perspective') {
            return (
              <div key={m.id} className="flex justify-start w-full">
                <div
                  className="max-w-[92%] rounded-lg px-3 py-2 text-xs text-stone-100 whitespace-pre-wrap w-full min-w-0 border border-stone-600/50 border-l-2 border-l-[color:var(--color-accent)]"
                  style={{ background: 'var(--color-zenaf-glow)' }}
                >
                  {m.content}
                  <ResonanceSlider
                    responseId={m.responseId}
                    seatId={perspective.id}
                    contextKind="perspective_workout"
                    entityType="perspective"
                    entityId={perspective.id}
                    subjectPerspectiveId={perspective.id}
                  />
                </div>
              </div>
            )
          }
          const seatAgent = availableSeats.find((a) => a.id === m.seatId) ?? null
          return (
            <div key={m.id} className="flex justify-start w-full">
              <div className="max-w-[92%] rounded-lg px-3 py-2 text-xs text-stone-100 whitespace-pre-wrap border border-stone-600/60 w-full min-w-0 bg-surface-raised/80">
                <div className="flex items-center gap-2 mb-1.5 pb-1 border-b border-stone-600/40">
                  {seatAgent ? (
                    <AvatarDisplay agent={seatAgent} size="sm" className="text-stone-200 shrink-0" />
                  ) : null}
                  <span className="text-[10px] font-medium text-amber-200/85 uppercase tracking-wide">
                    {m.seatName ?? m.seatId ?? 'Seat'}
                  </span>
                </div>
                {m.content}
                <ResonanceSlider
                  responseId={m.responseId}
                  seatId={m.seatId}
                  contextKind="perspective_workout"
                  entityType="perspective"
                  entityId={perspective.id}
                  subjectPerspectiveId={perspective.id}
                />
              </div>
            </div>
          )
        })}
        <div ref={threadEndRef} />
      </div>

      <div
        className={`shrink-0 p-3 border-t border-stone-700 space-y-2 bg-stone-800/80 rounded-b-lg ${
          dragActive ? 'ring-2 ring-amber-500/75 ring-inset' : ''
        }`}
        onDragOver={onWorkoutDragOver}
        onDragLeave={onWorkoutDragLeave}
        onDrop={(e) => void onWorkoutDrop(e)}
      >
        <label className="sr-only" htmlFor="workout-reply">
          Message to {pName}
        </label>
        <textarea
          id="workout-reply"
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          rows={2}
          disabled={busy}
          placeholder={`Talk to ${pName} or describe a scenario…`}
          className="w-full px-3 py-2 rounded-lg bg-stone-900 border border-stone-600 text-stone-100 text-sm placeholder-stone-500 focus:outline-none focus:ring-1 focus:ring-yellow-700 resize-none leading-relaxed disabled:opacity-50"
        />
        <button
          type="button"
          onClick={() => void onSendSeat1()}
          disabled={busy || !input.trim()}
          className="w-full px-3 py-2 rounded-lg bg-accent hover:opacity-90 disabled:opacity-50 text-warm-white text-sm font-medium"
        >
          {busy && invokingSeatId === '__seat1__' ? 'Sending…' : 'Send'}
        </button>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-stone-500 mb-2">Other perspectives</p>
          <div className="flex flex-wrap gap-2">
            {availableSeats.map((a) => {
              const loading = busy && invokingSeatId === a.id
              return (
                <button
                  key={a.id}
                  type="button"
                  disabled={busy}
                  onClick={() => onInvokeSeat(a)}
                  className={`inline-flex items-center gap-1.5 px-2 py-1.5 rounded-lg border border-stone-600 bg-stone-900/80 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-45 disabled:cursor-not-allowed ${
                    loading ? 'ring-1 ring-yellow-600/60' : ''
                  }`}
                >
                  <AvatarDisplay agent={a} size="sm" className="text-stone-200" />
                  <span className="truncate max-w-[120px]">{a.name}</span>
                  {loading ? (
                    <span
                      className="inline-block h-3 w-3 border-2 border-stone-500 border-t-yellow-400 rounded-full animate-spin shrink-0"
                      aria-hidden
                    />
                  ) : null}
                </button>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
