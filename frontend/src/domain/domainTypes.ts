/**
 * Shared domain types. Initiatives, projects, tasks, assets match Vision Execution API shape.
 * Inventory extends asset with stock/reorder fields for clinic operations.
 */

export type {
  Initiative,
  Project,
  Task,
  Asset,
} from '../vision-execution/types'

/** Inventory record: links to asset (and optionally initiative/project); used for Radar alerts. */
export interface InventoryItem {
  id: string
  asset_id: string
  name: string
  type: string
  category: string
  current_stock: number
  reorder_threshold: number
  reorder_status: 'ok' | 'low' | 'reorder_soon' | 'pending_order'
  related_initiative_id?: string
  related_project_id?: string
  unit: string
  notes?: string
}

/** Inbox/queue flag for Needs Attention (faux until intake is wired). */
export interface InboxFlag {
  id: string
  kind: 'email' | 'fax'
  subject_or_summary: string
  flagged: boolean
  needs_review: boolean
}

export interface DomainData {
  initiatives: import('../vision-execution/types').Initiative[]
  projects: import('../vision-execution/types').Project[]
  tasks: import('../vision-execution/types').Task[]
  assets: import('../vision-execution/types').Asset[]
  inventoryItems: InventoryItem[]
  inboxFlags: InboxFlag[]
  dailyOpsSeed: { appointmentsToday: number; consultsToday: number; followUpsPending: number; activeWorkInProgress: number }
}
