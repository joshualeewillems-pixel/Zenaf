/**
 * Radar selectors: derive dashboard view models from shared domain data.
 * Domain data is VE-shaped (initiative_id, project_id, etc.); we map to panel types with source refs.
 */

import type { DomainData } from '../domain/domainTypes'
import { INITIATIVE_CLINIC } from '../domain/seedData'
import type {
  AttentionItem,
  OperationsMetric,
  QueueSummary,
  InventoryAlert,
  ProjectSummary,
  BlockedItem,
  AnnaRadarViewModel,
} from './types'

function projectStatusToRadar(s: string): 'not_started' | 'in_progress' | 'waiting' | 'done' {
  const lower = s.toLowerCase()
  if (lower === 'in progress' || lower === 'in_progress') return 'in_progress'
  if (lower === 'waiting') return 'waiting'
  if (lower === 'not started' || lower === 'not_started') return 'not_started'
  if (lower === 'done' || lower === 'completed') return 'done'
  return 'in_progress'
}

export function getProjectsByInitiativeId(domain: DomainData, initiativeId: string) {
  return domain.projects.filter((p) => p.initiative_id === initiativeId)
}

export function getTasksByProjectId(domain: DomainData, projectId: string) {
  return domain.tasks.filter((t) => t.project_id === projectId)
}

export function getTasksByInitiativeId(domain: DomainData, initiativeId: string) {
  const projectIds = new Set(getProjectsByInitiativeId(domain, initiativeId).map((p) => p.id))
  return domain.tasks.filter((t) => t.project_id != null && projectIds.has(t.project_id))
}

export function getInventoryAlertsForInitiative(domain: DomainData, initiativeId?: string): InventoryAlert[] {
  let items = domain.inventoryItems
  if (initiativeId) items = items.filter((i) => i.related_initiative_id === initiativeId)
  return items
    .filter((i) => i.reorder_status !== 'ok')
    .map((i) => ({
      id: i.id,
      itemName: i.name,
      status: i.reorder_status,
      detail: i.current_stock <= i.reorder_threshold ? `${i.current_stock} ${i.unit}` : undefined,
      relatedInitiativeId: i.related_initiative_id,
      relatedProjectId: i.related_project_id,
      sourceType: 'inventory' as const,
      sourceId: i.id,
      assetId: i.asset_id,
    }))
}

/** Default Radar role: derive dashboard from shared domain (demo clinic + program seed). */
export function getRadarSummaryForRole(domain: DomainData, role: 'anna-admin'): AnnaRadarViewModel {
  if (role !== 'anna-admin') {
    return {
      attentionItems: [],
      operationsMetrics: [],
      queueSummary: { totalUnreviewed: 0, emailCount: 0, faxCount: 0, flaggedCount: 0 },
      inventoryAlerts: [],
      activeProjects: [],
      blockedItems: [],
    }
  }

  const clinicProjects = getProjectsByInitiativeId(domain, INITIATIVE_CLINIC)
  const clinicProjectIds = new Set(clinicProjects.map((p) => p.id))
  const clinicTasks = domain.tasks.filter((t) => t.project_id != null && clinicProjectIds.has(t.project_id))
  const { inboxFlags, dailyOpsSeed } = domain

  // Needs Attention: inbox, overdue tasks (notes contain "Overdue"), waiting approval, incomplete docs
  const faxNeedingReview = inboxFlags.filter((f) => f.kind === 'fax' && f.needs_review)
  const emailNeedingReview = inboxFlags.filter((f) => f.kind === 'email' && f.needs_review)
  const overdueTasks = clinicTasks.filter((t) => /overdue/i.test(t.notes || ''))
  const waitingApproval = clinicTasks.filter((t) => t.status === 'Waiting' && /approval|review|stakeholder/i.test(t.notes || ''))
  const incompleteDocTasks = clinicTasks.filter(
    (t) => t.status !== 'Done' && /SOAP|documentation|charting|notes/i.test(t.title)
  )

  const attentionItems: AttentionItem[] = []
  faxNeedingReview.forEach((f) =>
    attentionItems.push({
      id: f.id,
      label: f.subject_or_summary,
      severity: 'high',
      kind: 'fax',
      sourceType: 'inbox',
      sourceId: f.id,
    })
  )
  if (emailNeedingReview.length)
    attentionItems.push({
      id: 'email-needs-response',
      label: 'Important emails needing response',
      count: emailNeedingReview.length,
      severity: 'high',
      kind: 'email',
      sourceType: 'inbox',
      sourceId: 'email-needs-response',
    })
  overdueTasks.forEach((t) =>
    attentionItems.push({
      id: t.id,
      label: t.title,
      severity: 'high',
      kind: 'task',
      sourceType: 'task',
      sourceId: t.id,
      taskId: t.id,
      projectId: t.project_id ?? undefined,
    })
  )
  waitingApproval.forEach((t) =>
    attentionItems.push({
      id: t.id,
      label: t.title,
      severity: 'medium',
      kind: 'task',
      sourceType: 'task',
      sourceId: t.id,
      taskId: t.id,
      projectId: t.project_id ?? undefined,
    })
  )
  if (incompleteDocTasks.length)
    attentionItems.push({
      id: 'incomplete-docs',
      label: 'Incomplete documentation / charting items',
      count: incompleteDocTasks.length,
      severity: 'medium',
      kind: 'doc',
      sourceType: 'doc',
      sourceId: 'incomplete-docs',
    })

  const operationsMetrics: OperationsMetric[] = [
    { id: 'appts', label: 'Appointments today', value: String(dailyOpsSeed.appointmentsToday) },
    { id: 'consults', label: 'Consults today', value: String(dailyOpsSeed.consultsToday) },
    { id: 'followups', label: 'Follow-ups pending', value: String(dailyOpsSeed.followUpsPending), hint: 'Needs scheduling' },
    { id: 'wip', label: 'Active work in progress', value: String(dailyOpsSeed.activeWorkInProgress) },
  ]

  const totalUnreviewed = inboxFlags.filter((f) => f.needs_review).length
  const queueSummary: QueueSummary = {
    totalUnreviewed,
    emailCount: inboxFlags.filter((f) => f.kind === 'email').length,
    faxCount: inboxFlags.filter((f) => f.kind === 'fax').length,
    flaggedCount: inboxFlags.filter((f) => f.flagged).length,
  }

  const inventoryAlerts = getInventoryAlertsForInitiative(domain, INITIATIVE_CLINIC)

  const activeProjects: ProjectSummary[] = clinicProjects
    .filter((p) => p.status === 'In Progress' || p.status === 'Waiting')
    .map((p) => ({
      id: p.id,
      title: p.title,
      status: projectStatusToRadar(p.status),
      initiativeId: p.initiative_id ?? undefined,
      note: p.status === 'Waiting' ? 'Waiting on review or input' : undefined,
      sourceType: 'project',
      sourceId: p.id,
      projectId: p.id,
    }))

  const blockedTasks = domain.tasks.filter((t) => t.status === 'Waiting' && t.notes)
  const blockedItems: BlockedItem[] = blockedTasks
    .filter((t) => t.project_id != null && clinicProjectIds.has(t.project_id))
    .map((t) => {
      const proj = t.project_id ? domain.projects.find((p) => p.id === t.project_id) : undefined
      return {
        id: t.id,
        label: t.title,
        waitingOn: /waiting on[:\s]*/i.test(t.notes || '') ? (t.notes || '').replace(/^.*waiting on[:\s]*/i, '').trim() : (t.notes || 'Unknown'),
        note: undefined,
        sourceType: 'task',
        sourceId: t.id,
        taskId: t.id,
        projectId: t.project_id ?? undefined,
        initiativeId: proj?.initiative_id ?? undefined,
      }
    })

  return {
    attentionItems,
    operationsMetrics,
    queueSummary,
    inventoryAlerts,
    activeProjects,
    blockedItems,
  }
}
