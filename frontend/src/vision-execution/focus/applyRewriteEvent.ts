/** Dispatched on `window` when user applies a Context Bar rewrite to the matching VE form field */
export const ATRIA_VE_FOCUS_APPLY_REWRITE = 'atria-ve-focus-apply-rewrite'

export type VeFocusApplyRewriteDetail = {
  entity_type: string
  entity_id: string
  field_key: string
  text: string
}
