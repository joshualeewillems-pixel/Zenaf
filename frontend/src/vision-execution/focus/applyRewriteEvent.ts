/** Dispatched on `window` when user applies a Context Bar rewrite to the matching VE form field */
export const ZENAF_VE_FOCUS_APPLY_REWRITE = 'zenaf-ve-focus-apply-rewrite'

export type VeFocusApplyRewriteDetail = {
  entity_type: string
  entity_id: string
  field_key: string
  text: string
}
