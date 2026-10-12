# Inbox Triage v1 — Design

Use meeting-intelligence infrastructure to **classify and stage** inbox items for review. No full VE extraction (ideas/initiatives/tasks) from every email in v1.

---

## 1. Reusable pieces map

| Piece | Reuse | Adapter / notes |
|-------|--------|------------------|
| **duplicateDetection** (`titleSimilarity`, `findBestMatch`) | As-is | Pass `subject` or `subject + snippet` as title; candidates = initiatives/projects/persons with id+title. Used to suggest "Possible related initiative/project/person." |
| **reviewPriority** | Adapter | Inbox items have `confidence`, optional `suggestedSignal` (kind + label), optional related-entity ids. Add `getInboxItemPriority(item)` that uses `confidenceOrder`, "has related match," urgency/blocker language in subject/body; or treat staged inbox items as generic items with `data: InboxClassification` and reuse `getItemPriority` by ensuring `data.confidence`, `data.relatedInitiativeId` etc. map to the same shape. `sortStagedItems(items, 'inbox')` with a new kind, or a thin wrapper that maps `StagedInboxItem` → priority score. |
| **reviewBatchActions** | Adapter | Same pattern: items with `approved`, `acceptedExistingId`-like (e.g. `acceptedInitiativeId`), `data.confidence`. Add inbox-specific batch helpers that work on `StagedInboxItem[]` (accept by category, by urgency, accept suggested links, clear links) or reuse generics by making inbox item `data` expose `confidence`, `existingInitiativeMatchId`-style fields. Easiest: new small `inboxBatchActions.ts` that mirrors batch helpers but for inbox shape; or reuse by normalizing inbox item to a minimal `StagedItem`-like shape for batch ops only. |
| **Traceability** (`withTraceability`, `parseTraceabilityFromNotes`) | As-is | When an inbox item is later used to create a task/idea (future), append `[Source: inbox-triage]` and `Quote: <snippet>`. For v1, store `sourceExcerpt` on the inbox item and optional "created from inbox item X" when triage leads to a single action (e.g. "Create task from this"). Parse for display in UI. |
| **contextBuilder** (`buildExtractionContext`) | As-is | Classifier API receives same context (initiatives, projects, persons) so it can suggest `relatedInitiativeId`, `relatedProjectId`, `relatedPersonId`. Same `ExtractionContext` type and `buildExtractionContext(...)` call; backend triage endpoint accepts `context` like extract-meeting. |
| **segmentation** (`segmentTranscript`) | Optional / adapter | For long email bodies, could segment to avoid sending 50k chars. v1: send subject + body snippet (e.g. first N chars) only; no segmentation. If needed later, reuse `segmentTranscript` on `body` and pass first segment or concatenate segment titles for classifier. |
| **segmentSorter** | Not used in v1 | Inbox items are one-per-email; no "segment" concept. Topic/keyword classification could be reused later for "inbox topic buckets" (e.g. operations, planning) without adopting segment types. |
| **Review UI patterns** | Adapter | Same patterns: section list, priority sort, confidence badge, "From segment" → "From inbox", batch buttons (Accept category, Accept urgency, Use suggested link, Clear link). New screen `ReviewInboxTriageScreen` with one section "Inbox items" and configurable columns (category, urgency, queue, related entity, signal). Reuse `StagedRow`-like row with approve checkbox, editable category/urgency/queue dropdowns, "Use suggested" for initiative/project/person, optional signal badge. No need to reuse `StagingArea` multi-section shape; single list of `StagedInboxItem` is enough. |

**Summary**

- **As-is:** duplicateDetection, traceability, contextBuilder (for classifier context).
- **Thin adapter:** reviewPriority (inbox item has confidence + related ids + optional signal → same priority logic); reviewBatchActions (inbox item shape with approved + accepted*Id fields → same batch patterns); review UI (one section, same row/batch/confidence patterns).
- **Not used in v1:** segmentation, segmentSorter (optional later).

---

## 2. Inbox Triage v1 types

```ts
// --- Raw inbox item (from API or ingest) ---
export interface InboxItem {
  id: string
  subject: string
  body: string           // full or truncated; v1 often snippet
  snippet?: string       // short preview (e.g. first 200 chars)
  sender: string
  receivedAt: string     // ISO datetime
  source?: string        // e.g. "email", "fax"
  externalId?: string    // e.g. message-id, fax id
}

// --- Classifier output (suggestions only) ---
export type InboxCategory = 
  | 'request' | 'follow_up' | 'info' | 'urgent' | 'reference' | 'other'

export type InboxUrgency = 'high' | 'medium' | 'low'

export type InboxQueue = string  // e.g. "intake", "ops", "sales"; configurable

export type InboxSignalKind = 'attention' | 'risk' | 'opportunity' | 'blocker'

export interface InboxClassification {
  id: string
  inboxItemId: string
  category: InboxCategory
  urgency: InboxUrgency
  suggestedQueue: string
  relatedInitiativeId?: string | null
  relatedProjectId?: string | null
  relatedPersonId?: string | null
  suggestedSignal?: { kind: InboxSignalKind; label: string; detail?: string } | null
  sourceExcerpt?: string | null   // snippet supporting the suggestion
  confidence?: 'high' | 'medium' | 'low' | null
}

// --- Staged for review (classification + approval state) ---
export interface StagedInboxItem {
  id: string
  approved: boolean
  edited?: boolean
  /** When set, triage will assign this initiative (user accepted suggestion or picked) */
  acceptedInitiativeId?: string | null
  acceptedProjectId?: string | null
  acceptedPersonId?: string | null
  /** Inbox item + classification; user can override category/urgency/queue */
  data: InboxClassification & {
    subject: string
    sender: string
    receivedAt: string
    snippet?: string
  }
}

export interface InboxTriageStaging {
  items: StagedInboxItem[]
}
```

**Field usage**

- `InboxItem`: what we ingest (API or file).
- `InboxClassification`: what the classifier returns; merged with minimal inbox fields for display.
- `StagedInboxItem`: one per inbox item; `data` = classification + subject/sender/receivedAt/snippet for the row; `approved` = include in triage result; `accepted*Id` = user confirmed link to existing entity.
- No `ideas`/`initiatives`/`tasks` arrays; triage output is "per-item category, urgency, queue, and optional links/signal."

---

## 3. Minimal implementation path (v1 only)

### 3.1 Ingest

- **Source:** In v1, support at least one of: (a) GET inbox API that returns `InboxItem[]`, or (b) paste/upload of a list (e.g. CSV/JSON) that maps to `InboxItem[]`.
- **No new pipeline:** Ingest produces a list of `InboxItem`; no need for real-time sync or webhooks in v1.

### 3.2 Classify

- **Backend:** New endpoint `POST /inbox/classify` or `POST /vision-execution/classify-inbox` with body `{ items: InboxItem[], context?: ExtractionContext }`.
- **Response:** `{ items: InboxClassification[] }` (one per input item). Classifier (single LLM call or rule-based) returns category, urgency, suggestedQueue, optional relatedInitiativeId/projectId/personId, optional suggestedSignal, sourceExcerpt, confidence.
- **Context:** Reuse `buildExtractionContext(initiatives, projects, tasks, assets, persons)` and pass to the endpoint so the model can suggest related entities by id.

### 3.3 Stage for review

- **Frontend:** Map `InboxClassification[]` + `InboxItem[]` (by id) → `StagedInboxItem[]` (id, approved: false, data = classification + subject/sender/receivedAt/snippet). Store in state as `InboxTriageStaging` (e.g. `items: StagedInboxItem[]`).
- **Sort:** Use priority sort (urgency + confidence + suggested links) — reuse or adapt `getItemPriority` / `sortStagedItems` for inbox items.

### 3.4 Review UI

- **Screen:** `ReviewInboxTriageScreen`: single list of `StagedInboxItem`, each row shows subject, sender, receivedAt, category, urgency, queue, related initiative/project/person (with "Use suggested" if present), optional signal. Editable dropdowns for category, urgency, queue; approve checkbox; batch actions (Accept high urgency, Accept suggested links, Reject low confidence, etc.).
- **Duplicate/match:** For "related" suggestions, show "Possible match: Initiative X" using `findBestMatch(subject, initiatives)` when no classifier suggestion; "Use suggested" sets `acceptedInitiativeId` etc.

### 3.5 Approve and apply

- **v1 "commit":** No automatic creation of VE entities. On "Apply triage":
  - Persist triage result: each approved item gets its **category, urgency, queue, and accepted initiative/project/person ids** saved (e.g. PATCH inbox item or write to a triage_results store). Optionally push **suggested signal** to Radar when approved (same pattern as meeting signals → `POST /radar/items`).
- **Traceability:** When saving triage result, store `sourceExcerpt` (and optional `[Source: inbox-triage]` in a notes field on the inbox record if it exists). No `withTraceability` on VE entities in v1 unless a single "Create task from this" action is added later.

### 3.6 Optional signal

- If `data.suggestedSignal` is present and user approves the item, call `POST /radar/items` with the signal (same as meeting extraction). Optional in v1 (can be a checkbox "Push to Radar").

**Order of work**

1. Define types (frontend + API contract).
2. Backend: `POST /classify-inbox` (or equivalent) with `items` + `context`; return classifications.
3. Frontend: Inbox triage tab or section — load or paste inbox items → "Classify" → stage → `ReviewInboxTriageScreen` → "Apply triage" (save triage result + optional Radar).
4. Reuse: contextBuilder, duplicateDetection, traceability; adapt priority sort and batch actions for inbox shape; new review screen patterned after ReviewExtractionScreen but single section.

---

## 4. Explicitly out of scope for Inbox Triage v1

- **Full VE extraction from every email:** Do not call extract-meeting or create ideas/initiatives/tasks from email content in v1. Triage = classify + assign queue/category/links; no automatic creation of VE entities.
- **Automatic commit:** Every triage result is reviewed; no "auto-apply" by confidence.
- **Semantic / vector search:** Matching to initiatives/projects/persons is by classifier output + optional `findBestMatch` on title/subject only. No embeddings or vector index.
- **Generalized ontology:** Inbox types (category, urgency, queue) are inbox-specific. No change to VE entity types or staging area shape for meeting extraction.
- **Real-time sync or webhooks:** Ingest = explicit load or paste. No mailbox polling or push in v1.
- **Segmentation of email body:** Send subject + body (or snippet) as one blob to the classifier. No chunking into segments for v1.
- **Multi-agent or multi-step extraction:** Single classify call per batch; no chained "then extract tasks" step in v1.
- **Changing meeting-intelligence types:** Inbox triage has its own types (`InboxItem`, `InboxClassification`, `StagedInboxItem`); meeting pipeline remains unchanged.

---

## 5. File layout (scaffold)

- `frontend/src/inbox-triage/types.ts` — InboxItem, InboxClassification, StagedInboxItem, InboxTriageStaging, enums. **Done.**
- `frontend/src/inbox-triage/context.ts` — Re-export or wrap `buildExtractionContext` for classifier context.
- `frontend/src/inbox-triage/reviewInboxPriority.ts` — (optional) priority for inbox items; or reuse meeting-intelligence with adapter.
- `frontend/src/inbox-triage/reviewInboxBatchActions.ts` — (optional) accept by urgency/category, accept suggested links, clear links; or thin wrapper over generic batch helpers.
- `frontend/src/inbox-triage/ReviewInboxTriageScreen.tsx` — Review UI (single list, editable fields, batch buttons).
- API: `api/routes/` + `local_ai/` classifier for inbox (single endpoint, returns InboxClassification[]).

This keeps v1 minimal, reusable, and clearly bounded.
