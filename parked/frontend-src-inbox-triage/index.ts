/**
 * Inbox Triage v1.
 * Classify and stage inbox items for review; reuse meeting-intelligence patterns.
 * No full VE extraction from emails in v1.
 *
 * See docs/INBOX_TRIAGE_V1_DESIGN.md.
 */

export type {
  InboxItem,
  InboxCategory,
  InboxUrgency,
  InboxQueue,
  InboxSignalKind,
  InboxSignalSuggestion,
  InboxClassification,
  StagedInboxItem,
  InboxTriageStaging,
} from './types'
