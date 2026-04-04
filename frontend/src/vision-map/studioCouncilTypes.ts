/**
 * Shape of rows from GET /studio/council/recent-runs (admin); optional for map projection.
 */

export type StudioCouncilRunRow = {
  id: string
  created_at?: string
  teacher_mode?: string
  teacher_enforcement_mode?: string
  teacher_vetoed?: boolean
  teacher_warning?: boolean
  teacher_final_source?: string
  teacher_reason_codes?: string[]
  teacher_notes?: string | null
  native_artifact?: {
    question?: string
    subject?: {
      entity_type?: string
      type?: string
      entity_id?: string
      title?: string
      summary?: string
    }
  }
}
