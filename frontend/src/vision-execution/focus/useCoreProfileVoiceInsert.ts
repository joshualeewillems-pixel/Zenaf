import { useEffect, type Dispatch, type SetStateAction } from 'react'
import { ATRIA_VE_FOCUS_INSERT_TEXT, insertTextAtSelection, type VeFocusInsertTextDetail } from './insertTextEvent'

const CORE_PROFILE_FIELDS = [
  'name',
  'core_definition',
  'current_goals',
  'growth_focus_12_months',
  'economic_engine',
  'non_negotiables',
  'strategic_filter',
  'current_constraints',
  'capacity_limit',
  'kill_philosophy',
  'strength_positioning',
] as const

/** Draft-create row uses this id until a profile is persisted. */
export const CORE_PROFILE_CREATE_ENTITY_ID = '__core_profile_create__'

/**
 * Route voice transcript inserts into core profile form / training notes / proposed row.
 */
export function useCoreProfileVoiceInsert(params: {
  profileId: string
  setForm: Dispatch<SetStateAction<Record<string, string>>>
  setNotes: Dispatch<SetStateAction<string>>
  setProposed?: Dispatch<SetStateAction<Record<string, string> | null>>
  setChatInput?: Dispatch<SetStateAction<string>>
}): void {
  const { profileId, setForm, setNotes, setProposed, setChatInput } = params

  useEffect(() => {
    const onInsert = (e: Event) => {
      const d = (e as CustomEvent<VeFocusInsertTextDetail>).detail
      if (!d?.text || d.entity_type !== 'core_profile' || d.entity_id !== profileId) return
      const { field_key: fk, text, selectionStart, selectionEnd } = d
      const start = selectionStart ?? 0
      const end = selectionEnd ?? 0
      if (fk === 'training_inputs' || fk === 'raw_notes') {
        setNotes((prev) => insertTextAtSelection(prev, text, start, end))
        return
      }
      if (fk.startsWith('proposed_') && setProposed) {
        const k = fk.slice('proposed_'.length)
        setProposed((prev) => {
          if (!prev) return prev
          const cur = prev[k] ?? ''
          return { ...prev, [k]: insertTextAtSelection(cur, text, start, end) }
        })
        return
      }
      if (fk === 'training_conversation_draft' && setChatInput) {
        setChatInput((prev) => insertTextAtSelection(prev, text, start, end))
        return
      }
      if ((CORE_PROFILE_FIELDS as readonly string[]).includes(fk)) {
        setForm((prev) => {
          const cur = prev[fk] ?? ''
          return { ...prev, [fk]: insertTextAtSelection(cur, text, start, end) }
        })
      }
    }
    window.addEventListener(ATRIA_VE_FOCUS_INSERT_TEXT, onInsert)
    return () => window.removeEventListener(ATRIA_VE_FOCUS_INSERT_TEXT, onInsert)
  }, [profileId, setForm, setNotes, setProposed, setChatInput])
}
