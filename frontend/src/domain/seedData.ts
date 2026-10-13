/**
 * Shared **demo** seed: initiatives, projects, tasks, assets, inventory.
 * Fictional multi-vertical scenario for local UI — not a default real organization.
 * Shape matches Vision Execution API so existing VE views can display them.
 */

import type { Initiative, Project, Task, Asset } from '../vision-execution/types'
import type { InventoryItem, InboxFlag, DomainData } from './domainTypes'

const now = () => new Date().toISOString()
/** Return ISO date string for timeline seeding: base + weeks offset (date part only). */
function dateOffset(base: Date, weeks: number): string {
  const d = new Date(base)
  d.setDate(d.getDate() + weeks * 7)
  return d.toISOString().slice(0, 10)
}

function defaultInitiative(overrides: Partial<Initiative> & { id: string; title: string }): Initiative {
  const d: Initiative = {
    id: '',
    source_idea_id: null,
    title: '',
    brief: '',
    status: 'active',
    owner_id: null,
    evaluation_priority: null,
    estimated_cost_ai: '',
    estimated_timeframe_ai: '',
    philosophical_alignment_ai: '',
    next_step_ai: '',
    required_assets: [],
    dependencies: '',
    risks: '',
    recommendation: '',
    kill_criteria: '',
    notes: '',
    created_at: now(),
    updated_at: now(),
  }
  return { ...d, ...overrides }
}

function defaultProject(overrides: Partial<Project> & { id: string; title: string; initiative_id: string | null }): Project {
  const d: Project = {
    id: '',
    initiative_id: null,
    title: '',
    brief: '',
    status: 'In Progress',
    owner_id: null,
    supporting_owner_ids: [],
    priority: '',
    start_date: null,
    end_date: null,
    estimated_weekly_hours: null,
    next_step_ai: '',
    notes: '',
    created_at: now(),
    updated_at: now(),
  }
  return { ...d, ...overrides }
}

function defaultTask(overrides: Partial<Task> & { id: string; project_id: string; title: string }): Task {
  const d: Task = {
    id: '',
    project_id: '',
    parent_task_id: null,
    title: '',
    description: '',
    assignee_id: null,
    status: 'Todo',
    priority: '',
    estimated_hours: null,
    due_date: null,
    dependency_ids: [],
    completion_criteria: '',
    notes: '',
    created_at: now(),
    updated_at: now(),
  }
  return { ...d, ...overrides }
}

function defaultAsset(overrides: Partial<Asset> & { id: string; name: string }): Asset {
  const d: Asset = {
    id: '',
    name: '',
    asset_type: 'supply',
    owner_id: null,
    status: 'Available',
    availability: '',
    cost: '',
    time_availability: '',
    linked_idea_ids: [],
    linked_initiative_ids: [],
    linked_project_ids: [],
    notes: '',
    created_at: now(),
    updated_at: now(),
  }
  return { ...d, ...overrides }
}

// ---------- Initiative IDs ----------
export const INITIATIVE_CLINIC = 'initiative-clinic'
export const INITIATIVE_LIVING = 'initiative-living'

// ---------- Initiatives ----------
export const seedInitiatives: Initiative[] = [
  defaultInitiative({ id: INITIATIVE_CLINIC, title: 'Demo: Clinic & front-office operations', notes: 'Sample clinic spine (replace with your org)' }),
  defaultInitiative({ id: INITIATIVE_LIVING, title: 'Demo: Programs & community', notes: 'Sample program/content spine (replace with your org)' }),
]

// ---------- Project IDs ----------
export const PROJ_ACU = 'proj-acupuncture'
export const PROJ_HOLISTIC = 'proj-holistic'
export const PROJ_ACU_LANDING = 'proj-acu-landing'
export const PROJ_CLINIC_WEB = 'proj-clinic-website'
export const PROJ_SUPPLEMENT = 'proj-supplement'
export const PROJ_BOOK = 'proj-book'
export const PROJ_YOGURT = 'proj-yogurt'
export const PROJ_MEDITATION = 'proj-meditation'
export const PROJ_PEACE = 'proj-peace-walk'
export const PROJ_LFTH_LANDING = 'proj-lfth-landing'
export const PROJ_LFTH_WEB = 'proj-lfth-website'

// Base for timeline faux dates (start of current quarter)
const timelineBase = (() => {
  const d = new Date()
  d.setMonth(Math.floor(d.getMonth() / 3) * 3, 1)
  d.setHours(0, 0, 0, 0)
  return d
})()

// ---------- Projects ----------
export const seedProjects: Project[] = [
  defaultProject({ id: PROJ_ACU, initiative_id: INITIATIVE_CLINIC, title: 'Acupuncture', status: 'In Progress', start_date: dateOffset(timelineBase, 0), end_date: dateOffset(timelineBase, 12) }),
  defaultProject({ id: PROJ_HOLISTIC, initiative_id: INITIATIVE_CLINIC, title: 'Holistic Health Assessments', status: 'In Progress', start_date: dateOffset(timelineBase, 2), end_date: dateOffset(timelineBase, 10) }),
  defaultProject({ id: PROJ_ACU_LANDING, initiative_id: INITIATIVE_CLINIC, title: 'Acupuncture Landing Page', status: 'Waiting', start_date: dateOffset(timelineBase, 4), end_date: dateOffset(timelineBase, 8) }),
  defaultProject({ id: PROJ_CLINIC_WEB, initiative_id: INITIATIVE_CLINIC, title: 'Clinic Website', status: 'In Progress', start_date: dateOffset(timelineBase, 0), end_date: dateOffset(timelineBase, 16) }),
  defaultProject({ id: PROJ_SUPPLEMENT, initiative_id: INITIATIVE_CLINIC, title: 'Supplement Ordering Workflow', status: 'Not Started', start_date: dateOffset(timelineBase, 8), end_date: dateOffset(timelineBase, 14) }),
  defaultProject({ id: PROJ_BOOK, initiative_id: INITIATIVE_LIVING, title: 'Book', status: 'In Progress', start_date: dateOffset(timelineBase, 0), end_date: dateOffset(timelineBase, 24) }),
  defaultProject({ id: PROJ_YOGURT, initiative_id: INITIATIVE_LIVING, title: 'Yogurt Pamphlet', status: 'In Progress', start_date: dateOffset(timelineBase, 2), end_date: dateOffset(timelineBase, 6) }),
  defaultProject({ id: PROJ_MEDITATION, initiative_id: INITIATIVE_LIVING, title: 'Weekly Meditation Class', status: 'Not Started', start_date: dateOffset(timelineBase, 6), end_date: dateOffset(timelineBase, 12) }),
  defaultProject({ id: PROJ_PEACE, initiative_id: INITIATIVE_LIVING, title: 'Peace Walk', status: 'Not Started', start_date: dateOffset(timelineBase, 10), end_date: dateOffset(timelineBase, 14) }),
  defaultProject({ id: PROJ_LFTH_LANDING, initiative_id: INITIATIVE_LIVING, title: 'Demo: Program landing page', status: 'Waiting', start_date: dateOffset(timelineBase, 4), end_date: dateOffset(timelineBase, 8) }),
  defaultProject({ id: PROJ_LFTH_WEB, initiative_id: INITIATIVE_LIVING, title: 'Demo: Program website', status: 'In Progress', start_date: dateOffset(timelineBase, 2), end_date: dateOffset(timelineBase, 14) }),
]

// ---------- Tasks (with due_date for timeline where useful) ----------
export const seedTasks: Task[] = [
  defaultTask({ id: 'task-acu-1', project_id: PROJ_ACU, title: "Review today's acupuncture appointments", status: 'In Progress', due_date: dateOffset(timelineBase, 1) }),
  defaultTask({ id: 'task-acu-2', project_id: PROJ_ACU, title: 'Confirm supply levels for needles', status: 'Todo', due_date: dateOffset(timelineBase, 2) }),
  defaultTask({ id: 'task-acu-3', project_id: PROJ_ACU, title: 'Follow up on acupuncture patient inquiries', status: 'Todo', due_date: dateOffset(timelineBase, 3) }),
  defaultTask({ id: 'task-acu-4', project_id: PROJ_ACU, title: 'Check incomplete SOAP notes', status: 'Todo', notes: 'Overdue', due_date: dateOffset(timelineBase, -1) }),
  defaultTask({ id: 'task-acu-5', project_id: PROJ_ACU, title: 'Review MediCal-related acupuncture documentation', status: 'Todo', due_date: dateOffset(timelineBase, 4) }),
  defaultTask({ id: 'task-hol-1', project_id: PROJ_HOLISTIC, title: 'Review pending assessment bookings', status: 'In Progress', due_date: dateOffset(timelineBase, 3) }),
  defaultTask({ id: 'task-hol-2', project_id: PROJ_HOLISTIC, title: 'Follow up on client intake forms', status: 'Todo', due_date: dateOffset(timelineBase, 4) }),
  defaultTask({ id: 'task-hol-3', project_id: PROJ_HOLISTIC, title: 'Confirm consult prep materials', status: 'Todo', due_date: dateOffset(timelineBase, 5) }),
  defaultTask({ id: 'task-hol-4', project_id: PROJ_HOLISTIC, title: 'Review overdue follow-up tasks', status: 'Todo', notes: 'Overdue', due_date: dateOffset(timelineBase, -1) }),
  defaultTask({ id: 'task-acul-1', project_id: PROJ_ACU_LANDING, title: 'Finish draft copy', status: 'Done', due_date: dateOffset(timelineBase, 5) }),
  defaultTask({ id: 'task-acul-2', project_id: PROJ_ACU_LANDING, title: 'Review services section', status: 'Done', due_date: dateOffset(timelineBase, 6) }),
  defaultTask({ id: 'task-acul-3', project_id: PROJ_ACU_LANDING, title: 'Add CTA language', status: 'Done', due_date: dateOffset(timelineBase, 6) }),
  defaultTask({ id: 'task-acul-4', project_id: PROJ_ACU_LANDING, title: 'Await stakeholder approval', status: 'Waiting', notes: 'Waiting on approval', due_date: dateOffset(timelineBase, 8) }),
  defaultTask({ id: 'task-cw-1', project_id: PROJ_CLINIC_WEB, title: 'Update acupuncture service page', status: 'In Progress', due_date: dateOffset(timelineBase, 2) }),
  defaultTask({ id: 'task-cw-2', project_id: PROJ_CLINIC_WEB, title: 'Add holistic assessment section', status: 'Todo', due_date: dateOffset(timelineBase, 6) }),
  defaultTask({ id: 'task-cw-3', project_id: PROJ_CLINIC_WEB, title: 'Review homepage messaging', status: 'Todo', due_date: dateOffset(timelineBase, 8) }),
  defaultTask({ id: 'task-cw-4', project_id: PROJ_CLINIC_WEB, title: 'Check contact / booking flow', status: 'Todo', due_date: dateOffset(timelineBase, 10) }),
  defaultTask({ id: 'task-sup-1', project_id: PROJ_SUPPLEMENT, title: 'Define reorder thresholds', status: 'Todo', due_date: dateOffset(timelineBase, 9) }),
  defaultTask({ id: 'task-sup-2', project_id: PROJ_SUPPLEMENT, title: 'List current suppliers', status: 'Todo', due_date: dateOffset(timelineBase, 10) }),
  defaultTask({ id: 'task-sup-3', project_id: PROJ_SUPPLEMENT, title: 'Confirm ordering cadence', status: 'Todo', due_date: dateOffset(timelineBase, 11) }),
  defaultTask({ id: 'task-sup-4', project_id: PROJ_SUPPLEMENT, title: 'Draft front-office process', status: 'Todo', due_date: dateOffset(timelineBase, 14) }),
  defaultTask({ id: 'task-book-1', project_id: PROJ_BOOK, title: 'Outline remaining chapters', status: 'In Progress', due_date: dateOffset(timelineBase, 8) }),
  defaultTask({ id: 'task-book-2', project_id: PROJ_BOOK, title: 'Review introduction', status: 'Done', due_date: dateOffset(timelineBase, 2) }),
  defaultTask({ id: 'task-book-3', project_id: PROJ_BOOK, title: 'Prepare excerpt for landing page', status: 'Todo', due_date: dateOffset(timelineBase, 6) }),
  defaultTask({ id: 'task-book-4', project_id: PROJ_BOOK, title: 'Identify next editorial step', status: 'Todo', due_date: dateOffset(timelineBase, 10) }),
  defaultTask({ id: 'task-yog-1', project_id: PROJ_YOGURT, title: 'Refine pamphlet copy', status: 'In Progress', due_date: dateOffset(timelineBase, 3) }),
  defaultTask({ id: 'task-yog-2', project_id: PROJ_YOGURT, title: 'Clarify wellness claims', status: 'Todo', due_date: dateOffset(timelineBase, 4) }),
  defaultTask({ id: 'task-yog-3', project_id: PROJ_YOGURT, title: 'Review formatting', status: 'Todo', due_date: dateOffset(timelineBase, 5) }),
  defaultTask({ id: 'task-yog-4', project_id: PROJ_YOGURT, title: 'Prepare print-ready version', status: 'Todo', due_date: dateOffset(timelineBase, 6) }),
  defaultTask({ id: 'task-med-1', project_id: PROJ_MEDITATION, title: 'Confirm weekly schedule', status: 'Todo', due_date: dateOffset(timelineBase, 7) }),
  defaultTask({ id: 'task-med-2', project_id: PROJ_MEDITATION, title: 'Draft announcement copy', status: 'Todo', due_date: dateOffset(timelineBase, 8) }),
  defaultTask({ id: 'task-med-3', project_id: PROJ_MEDITATION, title: 'Review class description', status: 'Todo', due_date: dateOffset(timelineBase, 9) }),
  defaultTask({ id: 'task-med-4', project_id: PROJ_MEDITATION, title: 'Create attendance tracking plan', status: 'Todo', due_date: dateOffset(timelineBase, 10) }),
  defaultTask({ id: 'task-pw-1', project_id: PROJ_PEACE, title: 'Draft event description', status: 'Todo', due_date: dateOffset(timelineBase, 11) }),
  defaultTask({ id: 'task-pw-2', project_id: PROJ_PEACE, title: 'Confirm route details', status: 'Todo', due_date: dateOffset(timelineBase, 12) }),
  defaultTask({ id: 'task-pw-3', project_id: PROJ_PEACE, title: 'Create outreach copy', status: 'Todo', due_date: dateOffset(timelineBase, 12) }),
  defaultTask({ id: 'task-pw-4', project_id: PROJ_PEACE, title: 'Identify required supplies', status: 'Todo', due_date: dateOffset(timelineBase, 13) }),
  defaultTask({ id: 'task-lfthl-1', project_id: PROJ_LFTH_LANDING, title: 'Finish intro copy', status: 'Done', due_date: dateOffset(timelineBase, 5) }),
  defaultTask({ id: 'task-lfthl-2', project_id: PROJ_LFTH_LANDING, title: 'Add program summary', status: 'Done', due_date: dateOffset(timelineBase, 5) }),
  defaultTask({ id: 'task-lfthl-3', project_id: PROJ_LFTH_LANDING, title: 'Add signup call-to-action', status: 'Done', due_date: dateOffset(timelineBase, 6) }),
  defaultTask({ id: 'task-lfthl-4', project_id: PROJ_LFTH_LANDING, title: 'Await content review', status: 'Waiting', notes: 'Waiting on content review', due_date: dateOffset(timelineBase, 8) }),
  defaultTask({ id: 'task-lfthw-1', project_id: PROJ_LFTH_WEB, title: 'Review site structure', status: 'In Progress', due_date: dateOffset(timelineBase, 4) }),
  defaultTask({ id: 'task-lfthw-2', project_id: PROJ_LFTH_WEB, title: 'Add class information', status: 'Todo', due_date: dateOffset(timelineBase, 6) }),
  defaultTask({ id: 'task-lfthw-3', project_id: PROJ_LFTH_WEB, title: 'Add peace walk section', status: 'Todo', due_date: dateOffset(timelineBase, 8) }),
  defaultTask({ id: 'task-lfthw-4', project_id: PROJ_LFTH_WEB, title: 'Review navigation and contact flow', status: 'Todo', due_date: dateOffset(timelineBase, 10) }),
]

// ---------- Assets (clinic inventory as assets + inventory items for stock) ----------
const ASSET_NEEDLES = 'asset-needles'
const ASSET_WIPES = 'asset-wipes'
const ASSET_MAG = 'asset-mag'
const ASSET_VITD = 'asset-vitd'
const ASSET_ADAPTOGEN = 'asset-adaptogen'
const ASSET_DEVICE = 'asset-device'

export const seedAssets: Asset[] = [
  defaultAsset({ id: ASSET_NEEDLES, name: 'Acupuncture needles', asset_type: 'supply', linked_initiative_ids: [INITIATIVE_CLINIC], linked_project_ids: [PROJ_ACU], notes: 'Standard gauge' }),
  defaultAsset({ id: ASSET_WIPES, name: 'Alcohol wipes', asset_type: 'supply', linked_initiative_ids: [INITIATIVE_CLINIC], notes: '' }),
  defaultAsset({ id: ASSET_MAG, name: 'Magnesium supplement', asset_type: 'supplement', linked_initiative_ids: [INITIATIVE_CLINIC], linked_project_ids: [PROJ_SUPPLEMENT], notes: '' }),
  defaultAsset({ id: ASSET_VITD, name: 'Vitamin D supplement', asset_type: 'supplement', linked_initiative_ids: [INITIATIVE_CLINIC], linked_project_ids: [PROJ_SUPPLEMENT], notes: '' }),
  defaultAsset({ id: ASSET_ADAPTOGEN, name: 'Herbal/adaptogen supplement', asset_type: 'supplement', linked_initiative_ids: [INITIATIVE_CLINIC], notes: '' }),
  defaultAsset({ id: ASSET_DEVICE, name: 'Treatment room device', asset_type: 'equipment', linked_initiative_ids: [INITIATIVE_CLINIC], notes: 'Awaiting vendor confirmation' }),
]

export const seedInventoryItems: InventoryItem[] = [
  { id: 'inv-needles', asset_id: ASSET_NEEDLES, name: 'Acupuncture needles', type: 'supply', category: 'clinic', current_stock: 8, reorder_threshold: 15, reorder_status: 'low', related_initiative_id: INITIATIVE_CLINIC, related_project_id: PROJ_ACU, unit: 'boxes', notes: 'Standard gauge' },
  { id: 'inv-wipes', asset_id: ASSET_WIPES, name: 'Alcohol wipes', type: 'supply', category: 'clinic', current_stock: 42, reorder_threshold: 20, reorder_status: 'ok', related_initiative_id: INITIATIVE_CLINIC, unit: 'boxes' },
  { id: 'inv-mag', asset_id: ASSET_MAG, name: 'Magnesium supplement', type: 'supplement', category: 'clinic', current_stock: 12, reorder_threshold: 25, reorder_status: 'reorder_soon', related_initiative_id: INITIATIVE_CLINIC, related_project_id: PROJ_SUPPLEMENT, unit: 'bottles' },
  { id: 'inv-vitd', asset_id: ASSET_VITD, name: 'Vitamin D supplement', type: 'supplement', category: 'clinic', current_stock: 5, reorder_threshold: 15, reorder_status: 'low', related_initiative_id: INITIATIVE_CLINIC, related_project_id: PROJ_SUPPLEMENT, unit: 'bottles' },
  { id: 'inv-adaptogen', asset_id: ASSET_ADAPTOGEN, name: 'Herbal/adaptogen supplement', type: 'supplement', category: 'clinic', current_stock: 28, reorder_threshold: 20, reorder_status: 'ok', related_initiative_id: INITIATIVE_CLINIC, unit: 'bottles' },
  { id: 'inv-device', asset_id: ASSET_DEVICE, name: 'Treatment room device', type: 'equipment', category: 'clinic', current_stock: 1, reorder_threshold: 1, reorder_status: 'pending_order', related_initiative_id: INITIATIVE_CLINIC, unit: 'units', notes: 'Awaiting vendor confirmation' },
]

export const seedInboxFlags: InboxFlag[] = [
  { id: 'fax-1', kind: 'fax', subject_or_summary: 'Insurance prior auth — specialty visit', flagged: true, needs_review: true },
  { id: 'fax-2', kind: 'fax', subject_or_summary: 'Patient referral — Holistic assessment', flagged: false, needs_review: true },
  { id: 'email-1', kind: 'email', subject_or_summary: 'Supplier quote — needles (urgent)', flagged: true, needs_review: true },
  { id: 'email-2', kind: 'email', subject_or_summary: 'Patient inquiry — appointment change', flagged: false, needs_review: true },
]

export const seedDailyOps = {
  appointmentsToday: 14,
  consultsToday: 3,
  followUpsPending: 7,
  activeWorkInProgress: 6,
}

export function getSeedDomain(): DomainData {
  return {
    initiatives: seedInitiatives,
    projects: seedProjects,
    tasks: seedTasks,
    assets: seedAssets,
    inventoryItems: seedInventoryItems,
    inboxFlags: seedInboxFlags,
    dailyOpsSeed: seedDailyOps,
  }
}
