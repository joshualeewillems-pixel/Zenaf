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
import type { FocusContext, FocusContextCore, FocusDescriptor, FocusGraphSlices } from './types'
import { resolveGraphSliceVE } from './graphSliceResolver'
import { resolveGraphSliceProfile } from './profileGraphSliceResolver'
import {
  resolveGraphSliceCouncil,
  resolveGraphSliceIntake,
  resolveGraphSliceStaging,
} from './graphSliceResolversStub'
import { useVisionExecutionGraphDataOptional } from './VisionExecutionGraphDataContext'
import { useVisionExecutionProfileGraphOptional } from './VisionExecutionProfileGraphDataContext'
import { focusFieldRegistryKey } from './focusRegistryKey'
import {
  applyValueToTextControl,
  domControlToFocusDescriptor,
  ensureDomFieldId,
  isEligibleDomTextControl,
} from './domShellField'
import { ATRIA_VE_FOCUS_INSERT_TEXT, insertTextAtSelection, type VeFocusInsertTextDetail } from './insertTextEvent'

type VisionExecutionFocusValue = {
  focus: FocusContext | null
  /** Debounced apply when a registered field receives focus */
  notifyFieldFocused: (desc: FocusDescriptor) => void
  /** Debounced clear when focus leaves registered subtree (unless bar interaction suppresses once) */
  notifyFieldBlurred: () => void
  /** Call on pointer down in the action bar (capture) so blur from field does not clear focus */
  onBarPointerDownCapture: () => void
  /** Cancel scheduled focus clear when focus moves into the bar via keyboard (Tab) */
  onBarFocusCapture: () => void
  /** Immediate clear (entity switch, leave VE) */
  clearFocus: () => void
  /** Register live text for the focused field (unsaved draft) for actions like Rewrite */
  registerFieldTextGetter: (key: string, getter: () => string) => void
  unregisterFieldTextGetter: (key: string) => void
  getFocusedFieldText: () => string
  /** Last known selection inside a registered text control (for voice insert-at-cursor) */
  recordFieldSelection: (key: string, start: number, end: number) => void
  /** Range for insert; defaults to end of current field text if unknown */
  getFocusedFieldInsertionRange: () => { start: number; end: number } | null
}

const VisionExecutionFocusContext = createContext<VisionExecutionFocusValue | null>(null)

const FOCUS_APPLY_MS = 170
const FOCUS_CLEAR_MS = 320

export function VisionExecutionFocusProvider({
  children,
  focusHostActive,
}: {
  children: ReactNode
  /** When false, timers are cleared and shell field listeners detach (e.g. logged-out shell). */
  focusHostActive: boolean
}) {
  const [focusCore, setFocusCore] = useState<FocusContextCore | null>(null)
  const focusCoreRef = useRef<FocusContextCore | null>(null)
  focusCoreRef.current = focusCore
  const graphData = useVisionExecutionGraphDataOptional()
  const graphSnapshot = graphData?.snapshot ?? null
  const profileSnapshot = useVisionExecutionProfileGraphOptional()

  const focus = useMemo((): FocusContext | null => {
    if (!focusCore) return null
    const graphs: FocusGraphSlices = {}
    const ve = resolveGraphSliceVE(focusCore, graphSnapshot)
    if (ve) graphs.ve = ve
    const profile = resolveGraphSliceProfile(profileSnapshot)
    if (profile) graphs.profile = profile
    const staging = resolveGraphSliceStaging()
    if (staging) graphs.staging = staging
    const intake = resolveGraphSliceIntake()
    if (intake) graphs.intake = intake
    const council = resolveGraphSliceCouncil()
    if (council) graphs.council = council
    return { core: focusCore, graphs }
  }, [focusCore, graphSnapshot, profileSnapshot])
  const applyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const clearTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const suppressBlurOnceRef = useRef(false)
  const focusVersionRef = useRef(0)
  const fieldTextGettersRef = useRef<Map<string, () => string>>(new Map())
  const fieldSelectionRef = useRef<Map<string, { start: number; end: number }>>(new Map())
  const shellDomElRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null)
  const shellRegistryKeyRef = useRef<string | null>(null)
  const domFieldIdMapRef = useRef(new WeakMap<HTMLElement, string>())

  const clearAllTimers = useCallback(() => {
    if (applyTimerRef.current != null) {
      clearTimeout(applyTimerRef.current)
      applyTimerRef.current = null
    }
    if (clearTimerRef.current != null) {
      clearTimeout(clearTimerRef.current)
      clearTimerRef.current = null
    }
  }, [])

  const clearFocus = useCallback(() => {
    clearAllTimers()
    suppressBlurOnceRef.current = false
    setFocusCore(null)
  }, [clearAllTimers])

  const cancelPendingFocusClear = useCallback(() => {
    if (clearTimerRef.current != null) {
      clearTimeout(clearTimerRef.current)
      clearTimerRef.current = null
    }
  }, [])

  const registerFieldTextGetter = useCallback((key: string, getter: () => string) => {
    fieldTextGettersRef.current.set(key, getter)
  }, [])

  const unregisterFieldTextGetter = useCallback((key: string) => {
    fieldTextGettersRef.current.delete(key)
  }, [])

  const getFocusedFieldText = useCallback(() => {
    if (!focus) return ''
    return fieldTextGettersRef.current.get(focusFieldRegistryKey(focus.core))?.() ?? ''
  }, [focus])

  const recordFieldSelection = useCallback((key: string, start: number, end: number) => {
    fieldSelectionRef.current.set(key, { start, end })
  }, [])

  const getFocusedFieldInsertionRange = useCallback((): { start: number; end: number } | null => {
    if (!focus) return null
    const key = focusFieldRegistryKey(focus.core)
    const cur = fieldTextGettersRef.current.get(key)?.() ?? ''
    const len = cur.length
    const stored = fieldSelectionRef.current.get(key)
    if (
      stored &&
      Number.isFinite(stored.start) &&
      Number.isFinite(stored.end) &&
      stored.start >= 0 &&
      stored.end >= 0 &&
      stored.start <= len &&
      stored.end <= len
    ) {
      return { start: stored.start, end: stored.end }
    }
    return { start: len, end: len }
  }, [focus])

  useEffect(() => {
    if (!focusHostActive) clearFocus()
  }, [focusHostActive, clearFocus])

  const onBarPointerDownCapture = useCallback(() => {
    suppressBlurOnceRef.current = true
    cancelPendingFocusClear()
  }, [cancelPendingFocusClear])

  const onBarFocusCapture = useCallback(() => {
    cancelPendingFocusClear()
  }, [cancelPendingFocusClear])

  const notifyFieldBlurred = useCallback(() => {
    if (suppressBlurOnceRef.current) {
      suppressBlurOnceRef.current = false
      return
    }
    clearAllTimers()
    clearTimerRef.current = setTimeout(() => {
      setFocusCore(null)
      clearTimerRef.current = null
    }, FOCUS_CLEAR_MS)
  }, [clearAllTimers])

  const notifyFieldFocused = useCallback(
    (desc: FocusDescriptor) => {
      clearAllTimers()
      focusVersionRef.current += 1
      const v = focusVersionRef.current
      applyTimerRef.current = setTimeout(() => {
        if (focusVersionRef.current !== v) return
        setFocusCore({
          ...desc,
          surface: desc.surface ?? 'vision_execution',
          focus_version: v,
        })
        applyTimerRef.current = null
      }, FOCUS_APPLY_MS)
    },
    [clearAllTimers],
  )

  useEffect(() => {
    const onInsert = (ev: Event) => {
      const d = (ev as CustomEvent<VeFocusInsertTextDetail>).detail
      if (!d?.text || d.entity_type !== 'app_field') return
      const fc = focusCoreRef.current
      if (!fc || fc.entity_type !== 'app_field') return
      if (fc.entity_id !== d.entity_id || fc.field_key !== d.field_key) return
      const el = shellDomElRef.current
      if (!el || !isEligibleDomTextControl(el)) return
      const next = insertTextAtSelection(el.value, d.text, d.selectionStart, d.selectionEnd)
      const a = Math.max(0, Math.min(Math.floor(d.selectionStart), el.value.length))
      const b = Math.max(0, Math.min(Math.floor(d.selectionEnd), el.value.length))
      const lo = Math.min(a, b)
      const caret = lo + d.text.length
      applyValueToTextControl(el, next)
      try {
        el.setSelectionRange(caret, caret)
      } catch {
        /* ignore */
      }
    }
    window.addEventListener(ATRIA_VE_FOCUS_INSERT_TEXT, onInsert)
    return () => window.removeEventListener(ATRIA_VE_FOCUS_INSERT_TEXT, onInsert)
  }, [])

  useEffect(() => {
    if (!focusHostActive) return

    const syncShellSelection = () => {
      const el = document.activeElement
      if (!isEligibleDomTextControl(el) || el.closest('[data-atria-transcribe-region]')) return
      const sk = shellRegistryKeyRef.current
      if (!sk || el !== shellDomElRef.current) return
      recordFieldSelection(sk, el.selectionStart ?? 0, el.selectionEnd ?? 0)
    }

    const onDocFocusIn = (e: FocusEvent) => {
      const el = e.target
      if (!isEligibleDomTextControl(el)) return
      clearAllTimers()
      const stableId = ensureDomFieldId(el, domFieldIdMapRef.current)
      const desc = domControlToFocusDescriptor(el, stableId)
      const key = focusFieldRegistryKey({
        surface: desc.surface ?? 'shell',
        entity_type: desc.entity_type,
        entity_id: desc.entity_id,
        field_key: desc.field_key,
      })
      const prevKey = shellRegistryKeyRef.current
      if (prevKey && prevKey !== key) {
        unregisterFieldTextGetter(prevKey)
        fieldSelectionRef.current.delete(prevKey)
      }
      shellRegistryKeyRef.current = key
      shellDomElRef.current = el
      registerFieldTextGetter(key, () => shellDomElRef.current?.value ?? '')
      recordFieldSelection(key, el.selectionStart ?? 0, el.selectionEnd ?? 0)
      notifyFieldFocused(desc)
    }

    const onDocFocusOut = (e: FocusEvent) => {
      const t = e.target
      if (!isEligibleDomTextControl(t)) return
      if (t.closest('[data-atria-transcribe-region]')) return
      const sk = shellRegistryKeyRef.current
      if (sk) {
        unregisterFieldTextGetter(sk)
        fieldSelectionRef.current.delete(sk)
      }
      shellRegistryKeyRef.current = null
      shellDomElRef.current = null
      notifyFieldBlurred()
    }

    document.addEventListener('focusin', onDocFocusIn, true)
    document.addEventListener('focusout', onDocFocusOut, true)
    document.addEventListener('selectionchange', syncShellSelection)
    return () => {
      document.removeEventListener('focusin', onDocFocusIn, true)
      document.removeEventListener('focusout', onDocFocusOut, true)
      document.removeEventListener('selectionchange', syncShellSelection)
      const sk = shellRegistryKeyRef.current
      if (sk) {
        unregisterFieldTextGetter(sk)
        fieldSelectionRef.current.delete(sk)
      }
      shellRegistryKeyRef.current = null
      shellDomElRef.current = null
    }
  }, [
    focusHostActive,
    clearAllTimers,
    notifyFieldFocused,
    notifyFieldBlurred,
    registerFieldTextGetter,
    unregisterFieldTextGetter,
    recordFieldSelection,
  ])

  const value = useMemo(
    () => ({
      focus,
      notifyFieldFocused,
      notifyFieldBlurred,
      onBarPointerDownCapture,
      onBarFocusCapture,
      clearFocus,
      registerFieldTextGetter,
      unregisterFieldTextGetter,
      getFocusedFieldText,
      recordFieldSelection,
      getFocusedFieldInsertionRange,
    }),
    [
      focus,
      notifyFieldFocused,
      notifyFieldBlurred,
      onBarPointerDownCapture,
      onBarFocusCapture,
      clearFocus,
      registerFieldTextGetter,
      unregisterFieldTextGetter,
      getFocusedFieldText,
      recordFieldSelection,
      getFocusedFieldInsertionRange,
    ],
  )

  return <VisionExecutionFocusContext.Provider value={value}>{children}</VisionExecutionFocusContext.Provider>
}

export function useVisionExecutionFocus(): VisionExecutionFocusValue {
  const ctx = useContext(VisionExecutionFocusContext)
  if (!ctx) {
    throw new Error('useVisionExecutionFocus must be used within VisionExecutionFocusProvider')
  }
  return ctx
}

/** Safe for optional use (returns null outside provider) */
export function useVisionExecutionFocusOptional(): VisionExecutionFocusValue | null {
  return useContext(VisionExecutionFocusContext)
}
