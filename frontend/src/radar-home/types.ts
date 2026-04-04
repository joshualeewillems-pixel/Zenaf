/**
 * Radar Home — domain and view-model types for the role-specific dashboard.
 * Structured so real backend data can replace faux data later.
 */

export type RadarRole = 'anna-admin' | 'phil-program-content' | 'josh-executive-builder'

// ----- Domain (seed / backend) -----

export interface Initiative {
  id: string
  title: string
  status: 'active' | 'paused' | 'done'
  category: string
  owner?: string
}

export interface Project {
  id: string
  initiativeId: string
  title: string
  status: 'not_started' | 'in_progress' | 'waiting' | 'done'
  owner?: string
}

export interface Task {
  id: string
  projectId: string
  title: string
  status: 'todo' | 'in_progress' | 'waiting' | 'done'
  dueDate?: string
  overdue?: boolean
  waitingOn?: string
}

export interface InventoryItem {
  id: string
  name: string
  type: string
  category: string
  currentStock: number
  reorderThreshold: number
  reorderStatus: 'ok' | 'low' | 'reorder_soon' | 'pending_order'
  relatedInitiativeId?: string
  relatedProjectId?: string
  unit: string
  notes?: string
}

// Faux inbox/fax flags for Needs Attention
export interface InboxFlag {
  id: string
  kind: 'email' | 'fax'
  subjectOrSummary: string
  flagged: boolean
  needsReview: boolean
}

// ----- View models (for dashboard panels) — include source refs for navigation -----

export interface AttentionItem {
  id: string
  label: string
  count?: number
  severity: 'high' | 'medium' | 'low'
  kind: 'fax' | 'email' | 'task' | 'doc' | 'other'
  /** Source entity for navigation */
  sourceType?: 'inbox' | 'task' | 'doc'
  sourceId?: string
  initiativeId?: string
  projectId?: string
  taskId?: string
}

export interface OperationsMetric {
  id: string
  label: string
  value: string
  hint?: string
}

export interface QueueSummary {
  totalUnreviewed: number
  emailCount: number
  faxCount: number
  flaggedCount: number
}

export interface InventoryAlert {
  id: string
  itemName: string
  status: 'ok' | 'low' | 'reorder_soon' | 'pending_order'
  detail?: string
  relatedInitiativeId?: string
  relatedProjectId?: string
  /** Asset/inventory entity id for navigation */
  sourceType: 'inventory'
  sourceId: string
  assetId?: string
}

export interface ProjectSummary {
  id: string
  title: string
  status: 'not_started' | 'in_progress' | 'waiting' | 'done'
  owner?: string
  note?: string
  initiativeId?: string
  sourceType: 'project'
  sourceId: string
  projectId: string
}

export interface BlockedItem {
  id: string
  label: string
  waitingOn: string
  note?: string
  sourceType: 'task'
  sourceId: string
  taskId: string
  projectId?: string
  initiativeId?: string
}

export interface AnnaRadarViewModel {
  attentionItems: AttentionItem[]
  operationsMetrics: OperationsMetric[]
  queueSummary: QueueSummary
  inventoryAlerts: InventoryAlert[]
  activeProjects: ProjectSummary[]
  blockedItems: BlockedItem[]
}
