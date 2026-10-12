# System utility convergence audit

**Status:** Discovery / naming (not a philosophy consolidation pass).  
**Scope:** Frontend-heavy with pointers to Python council preflight and trace paths.  
**Question addressed:** What is tab-specific today that should become a reusable cross-surface system utility?

---

## A. Shared utility candidates

| Utility name | Currently exists | Missing / weaker | Why global | Type |
|--------------|------------------|------------------|------------|------|
| **Council preflight composer** | `App.tsx` builds `council_preflight` for `POST /run` (VE focus, `ve_selection`, titles/briefs, `developmental_guidance`, scoped digression flags, integration payloads). Server: `local_ai/council_preflight.py` consumes it. | No equivalent composer for hypothetical “council from Content only” or “council from Radar drill-down”; Map re-supplies **fragments** (developmental snapshot, execution-flow readings) in parallel to App state, not via one module. | One contract (`council_preflight`) already gates Zenaf context; divergent client assembly → drift vs `build_enriched_council_context`. | Source-of-truth utility (client assembly should mirror server parser expectations). |
| **Scoped digression / sub-thread context** | `App.tsx` + `is_scoped_digression` / `digression_background`; `council_preflight.py` truncates and guards. | No shared hook for “open scoped thread from Map node” or “from meeting review row” without copying App patterns. | Behavioral law lives in one server path; every surface that starts a sub-thread should emit the same shape. | Shared interaction utility. |
| **Conversation subject + handoff** | Refs in `App.tsx` (`councilConversationSubjectRef`, pending integration, last commit); thread capture in `subjectThreadCapture.ts` (session heuristics). | Meeting staging (`VisionExecutionView`) uses a different model (structured staging, not thread handoff). | Same user intent (“this turn is about X”) appears as different mechanisms. | Shared interaction utility. |
| **AiActionTrace emission** | `workspaceRunWithTrace.ts`, `contentRunWithTrace.ts`, `meetingExtractionTrace.ts`, many call sites in `VisionExecutionView.tsx`, `App.tsx` (workout council). | No single registry of “which surface emits what”; duplicate `createAiActionTrace` + `pushAiActionTrace` patterns. | Matrix/charter expect trace parity; one helper layer reduces omissions. | Shared visibility/signal utility. |
| **Routing context builder** | `workspaceRunWithTrace.buildWorkspaceRunRoutingContext`, VE posts use `buildNodeTransformRoutingContext` / inline objects, content uses `contentRoutingContext`. | Consistent `RunRoutingContext` assembly across tabs is manual per feature. | Execution seam + trace law want stable `action_intent` / `surface` pairing. | Source-of-truth utility (thin wrapper over policy). |
| **Field / entity focus model** | `VisionExecutionFocusProvider` + `useVisionExecutionFocusOptional` (VE table/detail fields, council textarea bridge, voice insertion). | Workspace uses `folderPath` / `lastFolderPath` + workout thread — not the same focus API. Content brief editor has local focus, not wired to council preflight VE block. | “Where is the user working?” should be one conceptual model with adapters per surface. | Shared interaction utility. |
| **Developmental guidance context** | `buildDevelopmentalGuidanceContext.ts` (map triad, trace ring, execution-flow readings). Fed from `App.tsx` when building council; Map passes `mapDevelopmentalSnapshot` / flow readings into map chat seed. | Not automatically available if council were launched from a future “minimal shell”; duplicated wiring in App vs map paths. | Single assembler already documented as read-only v1 — callers should not fork. | Shared visibility/signal utility (read model). |
| **Execution-flow readings fetch** | `fetchExecutionFlowReadings.ts`; used in App for council entity ref and Map state. | Not surfaced in VE table row actions as a first-class “signal” chip unless manually wired. | Same API; reuse avoids N+1 fetch patterns per surface. | Shared visibility/signal utility. |
| **Growth triad / vitality** | Map: `mapTriadInspector`, `liveProjection`, `mapGrowthMetrics`; VE: props like live lists for triad when coming from map. | Radar has no triad; Content has no triad; council sees triad only via preflight when App wires it. | One interpretive lens (water/soil/fruit) should not be map-only in the long run. | Shared visibility/signal utility. |
| **Staging → review → commit (meeting-shaped)** | `VisionExecutionView` meeting capture: chunk extract, `stagingArea`, sessionStorage `STAGING_STORAGE_KEY`, interpret/review UI. | No shared “staging workspace” for other extractions (e.g. content deliverables) even if server shapes differ. | User mental model is identical; only payload types differ. | Shared review/interpretation utility (adapter layer). |
| **Bounded transform / evaluate short-circuit** | `boundedCouncilTransform.ts` + `POST /suggest-node-transform` from workspace path in `App.tsx`. | VE has rich evaluate/apply/dismiss flows (`VisionExecutionView`); not the same code path as bounded transform. | Same intent (“reshape this node”) split across stream council vs JSON endpoint. | Shared action utility (router + trace). |
| **Grouped questions / guide stack UI** | `ThreadInlineGuideStack.tsx` + `guideQuestionDisplay.ts` (conversation thread). | VE insight / evaluation panels use different presentation; not the same grouping component. | Consistent “framing vs risks” grouping reduces cognitive load across surfaces. | Shared interaction utility. |
| **Note append / record insight** | Patterns scattered (meeting notes, integration commit, digression summary in `zenaf_tools.py`). | No single client “recordInsight” API with trace + routing. | Handoff from chat → durable note should be one contract. | Shared action utility. |
| **Open entity / deep navigation** | `RadarHomePage` callbacks (`onOpenProject`, …); map `onOpenEntity`; VE internal tab switches. | Radar → VE transition depends on parent wiring; not a global router module. | “Open this id in the right tab” is repeated per surface. | Shared interaction utility. |

---

## B. Tab-specific overfitting

### Vision Execution (table/detail)

- **Tab-specific today:** Full meeting pipeline (chunking, staging sessionStorage, harvest vs structured toggle), idea/initiative evaluate loops, field-level focus context, heavy `pushAiActionTrace` per action.
- **Legitimately local:** Entity-specific editors, table layout, initiative/project/task schemas.
- **Should extract/share:** Trace emission helpers per action family; “staging review” frame reused for any extraction-backed review; VE selection snapshot builder **called from** a shared preflight helper instead of only from `App.tsx` internals.

### Vision Map

- **Tab-specific today:** React Flow graph, `MapChatShell`, map-only triad inspector, client vitality on edges, `visionMapCouncilInteraction` seed alignment with preflight.
- **Legitimately local:** Layout, edge physics, map-only overlays.
- **Should extract/share:** Developmental snapshot + execution-flow bundle as a **portable package** any surface can attach to council; `onOpenEntity` should delegate to a **single navigation service** (VE tab + selection).

### Workspace (organizer)

- **Tab-specific today:** Folder path context, `workspaceRunWithTrace`, folder workflow kinds, council stream with folder advisor, bounded transform branch.
- **Legitimately local:** File tree, folder-scoped copy.
- **Should extract/share:** “Workspace context block” formatter + routing context should plug into the same **preflight composer** as VE (adapter), not a wholly separate mental model for “what council knows.”

### Council / chat panel

- **Tab-specific today:** Transcript UI, resonance bridge, workout council stream (Foundation), `CouncilTranscriptResonanceBridge` coupling to `mainView` + folder + VE hooks.
- **Legitimately local:** Seat rendering, streaming UX.
- **Should extract/share:** Any council launch should go through **one** “buildRunPayload” that always attaches preflight + routing_context + optional digression — today much of this is inline in `App.tsx`.

### Foundation / Perspectives

- **Tab-specific today:** Workout stream (`runWorkoutCouncilSingle`) with its own trace intent `perspective_workout_council_stream`; perspective definitions built ad hoc.
- **Legitimately local:** Workout pedagogy, slot wiring.
- **Should extract/share:** Same routing + trace + privacy defaults as main council; preflight may be empty but **shape** should be consistent.

### Meeting Capture (within VE)

- **Tab-specific today:** Chunk progress, retry, staging JSON shape, `_diagnostics` display.
- **Legitimately local:** Meeting-specific buckets (ideas/initiatives/tasks).
- **Should extract/share:** Generic “extract → stage → confirm” state machine and storage policy (session vs server).

### Content / transcript tools

- **Tab-specific today:** `contentRunWithTrace`, brief distill/sort/run modes, `TranscriptSorter`.
- **Legitimately local:** Brief schema, output tabs.
- **Should extract/share:** Run + trace + routing trinity already partially shared; **preflight** if Content ever participates in council with VE entities should reuse composer.

### Radar / “Executive” landing

- **Tab-specific today:** `RadarHomePage` demo domain, role summaries, navigation callbacks supplied by parent.
- **Legitimately local:** Demo seed presentation.
- **Should extract/share:** When Radar becomes real, it needs the same **open entity**, **trace**, and optionally **signal** utilities as VE/Map — currently it bypasses most system utilities.

### App-level orchestration

- **Tab-specific today:** `App.tsx` is the implicit integration layer (refs for council subject, digression, preflight merge, `mainView` switches).
- **Legitimately local:** Top-level layout, tab chrome.
- **Should extract/share:** Extract **CouncilRunOrchestrator** (or similar) module: inputs = { mainView, veSelection, folderPath, mapPayload, … } → outputs = { preflight, routingContext, flags }.

---

## C. Strongest asymmetries (top 10)

| # | “Real” version | Weaker / divergent | Gap |
|---|----------------|--------------------|-----|
| 1 | **App.tsx council preflight** (full VE + developmental + digression) | Map map-chat seed (partial mirror for `prompt_id` race) | Risk of subtle mismatch when map and main council disagree on “what Zenaf saw.” |
| 2 | **VisionExecutionFocusProvider** (field-level + voice) | Workspace / Content text areas (no shared focus registry) | Council “insert at focus” only well-defined for VE + council textarea bridge. |
| 3 | **VE evaluate / apply / dismiss** with traces | **Bounded transform** JSON path (`suggest-node-transform`) | Two maturity levels for “AI suggested change to entity.” |
| 4 | **Meeting staging + interpret** in `VisionExecutionView` | **subjectThreadCapture** heuristics in chat | Same “capture intent,” no shared review pipeline. |
| 5 | **workspaceRunWithTrace** (consistent workspace traces) | Inline trace construction in App workout + various VE branches | Duplication; easier to miss `action_intent` consistency. |
| 6 | **Map triad + execution-flow readings** wired into developmental context | Radar / Content / Foundation without triad or flow readings | Operator sees rich signals only if they live on Map or trigger council from App with refs set. |
| 7 | **ThreadInlineGuideStack** grouped questions | VE panels list insights/evaluations without that grouping model | Inconsistent “guide” UX between chat and entity review. |
| 8 | **Integration commit + pending payload** (council → durable write) | Meeting commit path (different API and UI) | Two “human confirms structured write” stories. |
| 9 | **Trace ring + `getRecentAiActionTraces`** feeding developmental guidance | Surfaces that never push traces (Radar, inert demo flows) | Guidance context silently biased toward VE/workspace-heavy users. |
| 10 | **Server `council_preflight` + `build_enriched_council_context`** (canonical) | Any future client that skips fields (e.g. missing `ve_selection`) | Server has fallbacks, but product semantics drift when clients omit blocks. |

---

## D. Convergence recommendations

| Candidate | Recommend | Dependency order | Likely owner module(s) |
|-----------|-----------|-------------------|------------------------|
| Council preflight composer | **Globalize later** (high value, high risk) | 1) Document input model; 2) extract from `App.tsx`; 3) Map/Content adapters; 4) server parser tests unchanged | `frontend/src/council/` or `frontend/src/ai-actions/councilPreflightComposer.ts` + `App.tsx` slim-down |
| Scoped digression flags | **Globalize later** | After composer — single `startScopedDigression({ entity, background })` | Same + `council_preflight.py` (unchanged contract) |
| AiActionTrace factory per surface | **Globalize now** (low risk) | Unify `createAiActionTrace` call sites behind `emitTraceForSurface(surface, intent, …)` | `frontend/src/ai-actions/traceEmitters.ts` |
| Routing context | **Globalize now** (low risk) | Align `action_intent` enum usage with `workspaceRunWithTrace` | `workspaceRunWithTrace.ts`, `contentRoutingContext.ts`, small VE helper |
| VisionExecutionFocus vs workspace focus | **Globalize later** | Define `FocusAnchor` union { veField, workspacePath, contentField } then adapters | `VisionExecutionFocusContext.tsx`, new `SystemFocusContext.tsx` |
| Developmental guidance bundle | **Globalize now** (medium) | Export `useDevelopmentalBundleForCouncil()` hook fed by Map/App | `developmentalGuidance/buildDevelopmentalGuidanceContext.ts` + hook |
| Execution-flow readings | **Globalize later** | Dedupe fetch + cache key by entity | `fetchExecutionFlowReadings.ts` + small cache layer |
| Meeting staging frame | **Globalize later** | Extract UI state machine; plug meeting adapter | `vision-execution/meetingCapture/` module |
| Bounded transform vs evaluate | **Leave local** short term; **globalize later** | Product decision on single endpoint vs router | `boundedCouncilTransform.ts`, `VisionExecutionView` API layer |
| Grouped questions UI | **Globalize later** | Extract presentational component; feed from VE data mappers | `conversation/ThreadInlineGuideStack.tsx` → shared `GuideQuestionGroups.tsx` |
| Radar navigation | **Globalize when Radar is real** | Introduce `navigation/openEntity.ts` | `App.tsx` + `RadarHomePage.tsx` |

---

## E. Convergence map

| Utility | Current owner(s) | Should become global? | Priority | Why |
|---------|------------------|----------------------|----------|-----|
| Council preflight assembly | `App.tsx`, bits in `vision-map/visionMapCouncilInteraction.ts` | Yes | P0 | Single Zenaf input contract. |
| Scoped digression | `App.tsx`, `local_ai/council_preflight.py` | Yes | P1 | Safety/guardrails are server-side; client must be uniform. |
| AiActionTrace emission | `workspaceRunWithTrace.ts`, `contentRunWithTrace.ts`, `VisionExecutionView.tsx`, `App.tsx` | Yes | P1 | Trace law + developmental inputs. |
| Run routing context | Per-surface builders | Yes | P1 | Seam + privacy consistency. |
| VE field focus | `VisionExecutionFocusContext.tsx` | Partial | P2 | VE-specific UI can stay; **selection snapshot for council** should be global. |
| Developmental guidance context | `buildDevelopmentalGuidanceContext.ts`, `App.tsx` wiring | Yes | P2 | Already designed as shared read model. |
| Execution-flow readings | `fetchExecutionFlowReadings.ts`, `App.tsx` | Partial | P2 | Dedupe fetch; optional everywhere. |
| Meeting staging / review | `VisionExecutionView.tsx` | Partial | P2 | Frame global, meeting schema local. |
| Bounded transform | `boundedCouncilTransform.ts`, `App.tsx` | Later | P3 | Needs product convergence with evaluate. |
| Grouped guide questions | `ThreadInlineGuideStack.tsx` | Later | P3 | UX polish, lower structural risk. |
| Radar drill-down | `RadarHomePage.tsx`, parent callbacks | Later | P3 | Demo surface today. |
| Workout council trace | `App.tsx` | Partial | P2 | Align intents with matrix; reuse trace helper. |

---

## Final answer

> If Zenaf were treated as **one system** rather than a collection of tabs, what utilities would clearly need to become shared infrastructure?

1. **Council context assembly** — one client-side **preflight composer** (and optional digression/subject helpers) that all surfaces use before `POST /run` / stream, matching `council_preflight.parse_preflight_from_request` and `build_enriched_council_context` on the server.

2. **Trace + routing emission** — one thin layer so every AI-touching action produces a consistent `AiActionTrace` + `RunRoutingContext` (surface, `action_intent`, privacy/allows_externalization) without each tab re-implementing `createAiActionTrace`.

3. **Focus / selection snapshot for “where the user is working”** — a small **system focus model** with VE, workspace, and (later) content adapters, so council and voice and future features agree on the active anchor.

4. **Read models for signals** — **developmental guidance bundle** and **execution-flow readings** as reusable packages, not App-only or Map-only wiring.

5. **Review / staging frame** — a shared **extract → stage → human confirm** interaction pattern (meeting is the first instance; thread handoff and content extractions should plug into the same frame over time).

6. **Navigation / open-entity** — a single **deep link or open handler** so Radar, Map, and search results do not each invent callback shapes.

**Explicitly remain local:** graph layout, folder file tree, brief editor layout, demo Radar copy, perspective workout pedagogy — as long as they **call into** the shared infrastructure above for context, trace, and navigation.

---

*Audit method: repository search and spot reads of `App.tsx`, `VisionExecutionView.tsx`, `council_preflight.py`, `buildDevelopmentalGuidanceContext.ts`, `workspaceRunWithTrace.ts`, `contentRunWithTrace.ts`, `boundedCouncilTransform.ts`, `RadarHomePage.tsx`, `ThreadInlineGuideStack.tsx`, `subjectThreadCapture.ts`, map triad / execution-flow modules. No product redesign performed.*
