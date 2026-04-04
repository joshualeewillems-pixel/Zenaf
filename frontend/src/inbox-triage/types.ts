/**
 * Inbox Triage v1 types.
 * Classify and stage inbox items for review; no full VE extraction.
 * See docs/INBOX_TRIAGE_V1_DESIGN.md.
 */

/** Raw inbox item (from API or ingest). */
export interface InboxItem {
  id: string
  subject: string
  body: string
  snippet?: string
  sender: string
  receivedAt: string
  source?: string
  externalId?: string
}

/** Category suggested by classifier. */
export type InboxCategory =
  | 'request'
  | 'follow_up'
  | 'info'
  | 'urgent'
  | 'reference'
  | 'other'

/** Urgency level. */
export type InboxUrgency = 'high' | 'medium' | 'low'

/** Queue/lane name (e.g. "intake", "ops"); configurable. */
export type InboxQueue = string

/** Signal kind for optional Radar push. */
export type InboxSignalKind = 'attention' | 'risk' | 'opportunity' | 'blocker'

/** Classifier suggestion for one inbox item. */
export interface InboxSignalSuggestion {
  kind: InboxSignalKind
  label: string
  detail?: string
}

/** Classifier output (suggestions only). */
export interface InboxClassification {
  id: string
  inboxItemId: string
  category: InboxCategory
  urgency: InboxUrgency
  suggestedQueue: string
  relatedInitiativeId?: string | null
  relatedProjectId?: string | null
  relatedPersonId?: string | null
  suggestedSignal?: InboxSignalSuggestion | null
  sourceExcerpt?: string | null
  confidence?: 'high' | 'medium' | 'low' | null
}

/** Staged for review: classification + approval and link state. */
export interface StagedInboxItem {
  id: string
  approved: boolean
  edited?: boolean
  acceptedInitiativeId?: string | null
  acceptedProjectId?: string | null
  acceptedPersonId?: string | null
  data: InboxClassification & {
    subject: string
    sender: string
    receivedAt: string
    snippet?: string
  }
}

/** Full staging state for inbox triage review. */
export interface InboxTriageStaging {
  items: StagedInboxItem[]
}
