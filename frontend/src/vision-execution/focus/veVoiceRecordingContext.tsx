import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useVisionExecutionFocus } from './VisionExecutionFocusContext'
import {
  ZENAF_VE_FOCUS_INSERT_TEXT,
  ZENAF_VOICE_TRANSCRIPT_DOM_FIRST,
  type VeFocusInsertTextDetail,
} from './insertTextEvent'
import type { FocusContext, FocusContextCore } from './types'
import { focusFieldRegistryKey } from './focusRegistryKey'

const TRANSCRIBE_URL = '/api/transcribe'

export type VoicePhase = 'idle' | 'recording' | 'transcribing'

function transcribeErrorMessage(data: unknown, status: number): string {
  if (data && typeof data === 'object' && 'detail' in data) {
    const d = (data as { detail: unknown }).detail
    if (typeof d === 'string') return d
    if (Array.isArray(d) && d.length > 0 && typeof d[0] === 'object' && d[0] !== null && 'msg' in d[0]) {
      return String((d[0] as { msg?: string }).msg ?? `Request failed (${status})`)
    }
  }
  return `Transcription failed (${status})`
}

type VeVoiceRecordingValue = {
  voicePhase: VoicePhase
  voiceError: string | null
  startVoiceRecording: () => void
  stopVoiceRecording: () => void
}

const VeVoiceRecordingContext = createContext<VeVoiceRecordingValue | null>(null)

export function VeVoiceRecordingProvider({ children }: { children: ReactNode }) {
  const { focus, getFocusedFieldInsertionRange } = useVisionExecutionFocus()
  const [voicePhase, setVoicePhase] = useState<VoicePhase>('idle')
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const mediaChunksRef = useRef<Blob[]>([])
  const recordStreamRef = useRef<MediaStream | null>(null)
  const voiceInsertTargetRef = useRef<{
    entity_type: string
    entity_id: string
    field_key: string
    selectionStart: number
    selectionEnd: number
  } | null>(null)
  /** Field we started recording on (stop still works if focus briefly flickers). */
  const recordingTargetRef = useRef<Pick<
    FocusContextCore,
    'surface' | 'entity_type' | 'entity_id' | 'field_key'
  > | null>(null)

  const stopRecordStream = useCallback(() => {
    recordStreamRef.current?.getTracks().forEach((t) => t.stop())
    recordStreamRef.current = null
  }, [])

  useEffect(() => {
    setVoiceError(null)
    const rec = mediaRecorderRef.current
    if (rec && rec.state === 'recording') {
      voiceInsertTargetRef.current = null
      recordingTargetRef.current = null
      try {
        rec.stop()
      } catch {
        /* ignore */
      }
    }
    setVoicePhase((p) => (p === 'recording' ? 'idle' : p))
  }, [focus?.core.entity_id, focus?.core.field_key, focus?.core.focus_version])

  useEffect(() => {
    return () => {
      recordStreamRef.current?.getTracks().forEach((t) => t.stop())
      recordStreamRef.current = null
      const rec = mediaRecorderRef.current
      if (rec && rec.state === 'recording') {
        try {
          rec.stop()
        } catch {
          /* ignore */
        }
      }
      mediaRecorderRef.current = null
    }
  }, [])

  const startVoiceRecording = useCallback(async () => {
    if (!focus || voicePhase !== 'idle') return
    setVoiceError(null)
    recordingTargetRef.current = {
      surface: focus.core.surface,
      entity_type: focus.core.entity_type,
      entity_id: focus.core.entity_id,
      field_key: focus.core.field_key,
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      recordStreamRef.current = stream
      const mime =
        typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
          ? 'audio/webm;codecs=opus'
          : typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported('audio/webm')
            ? 'audio/webm'
            : ''
      const rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream)
      mediaChunksRef.current = []
      rec.ondataavailable = (ev) => {
        if (ev.data.size > 0) mediaChunksRef.current.push(ev.data)
      }
      rec.onstop = () => {
        stopRecordStream()
        const blob = new Blob(mediaChunksRef.current, { type: rec.mimeType || 'audio/webm' })
        mediaChunksRef.current = []
        mediaRecorderRef.current = null
        const target = voiceInsertTargetRef.current
        voiceInsertTargetRef.current = null
        recordingTargetRef.current = null
        if (!target) {
          setVoicePhase('idle')
          return
        }
        setVoicePhase('transcribing')
        void (async () => {
          try {
            const fd = new FormData()
            fd.append('file', blob, 'recording.webm')
            // ai-trace-exempt: voice_transcribe_only (see AI_ACTION_TRACE_EXEMPTS)
            const res = await fetch(TRANSCRIBE_URL, { method: 'POST', body: fd, credentials: 'include' })
            const data = (await res.json().catch(() => ({}))) as unknown
            if (!res.ok) {
              setVoiceError(transcribeErrorMessage(data, res.status))
              return
            }
            const transcript =
              data && typeof data === 'object' && data !== null && 'transcript' in data
                ? String((data as { transcript?: unknown }).transcript ?? '')
                : ''
            const clean = transcript.trim()
            if (!clean) return
            const preempt = new CustomEvent(ZENAF_VOICE_TRANSCRIPT_DOM_FIRST, {
              cancelable: true,
              detail: { text: clean },
            })
            const fallThroughToVe = window.dispatchEvent(preempt)
            if (!fallThroughToVe) return
            const detail: VeFocusInsertTextDetail = {
              entity_type: target.entity_type,
              entity_id: target.entity_id,
              field_key: target.field_key,
              text: clean,
              selectionStart: target.selectionStart,
              selectionEnd: target.selectionEnd,
            }
            window.dispatchEvent(new CustomEvent(ZENAF_VE_FOCUS_INSERT_TEXT, { detail }))
          } finally {
            setVoicePhase('idle')
          }
        })()
      }
      mediaRecorderRef.current = rec
      rec.start(250)
      setVoicePhase('recording')
    } catch (e) {
      recordingTargetRef.current = null
      setVoiceError(e instanceof Error ? e.message : 'Could not access microphone')
      stopRecordStream()
      setVoicePhase('idle')
    }
  }, [focus, voicePhase, stopRecordStream])

  const stopVoiceRecording = useCallback(() => {
    const rec = mediaRecorderRef.current
    if (!rec || rec.state !== 'recording') return
    const anchor = recordingTargetRef.current
    if (!anchor) return
    let range: { start: number; end: number } = { start: 0, end: 0 }
    if (focus && focusFieldRegistryKey(focus.core) === focusFieldRegistryKey(anchor)) {
      const r = getFocusedFieldInsertionRange()
      if (r) range = r
    }
    voiceInsertTargetRef.current = {
      entity_type: anchor.entity_type,
      entity_id: anchor.entity_id,
      field_key: anchor.field_key,
      selectionStart: range.start,
      selectionEnd: range.end,
    }
    try {
      rec.stop()
    } catch {
      voiceInsertTargetRef.current = null
      recordingTargetRef.current = null
      setVoicePhase('idle')
    }
  }, [focus, getFocusedFieldInsertionRange])

  const value = useMemo(
    () => ({
      voicePhase,
      voiceError,
      startVoiceRecording,
      stopVoiceRecording,
    }),
    [voicePhase, voiceError, startVoiceRecording, stopVoiceRecording],
  )

  return <VeVoiceRecordingContext.Provider value={value}>{children}</VeVoiceRecordingContext.Provider>
}

export function useVeVoiceRecording(): VeVoiceRecordingValue {
  const ctx = useContext(VeVoiceRecordingContext)
  if (!ctx) {
    throw new Error('useVeVoiceRecording must be used within VeVoiceRecordingProvider')
  }
  return ctx
}
