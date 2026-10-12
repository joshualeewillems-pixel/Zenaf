# Hierarchical Meeting Extraction (Long Meetings)

## Summary

For **long meeting transcripts** (>12k characters), extraction uses a **hierarchical strategy** instead of many full extraction calls per segment. This reduces failure points and produces one coherent result.

- **Short notes** (≤12k chars): single `POST /extract-meeting` (unchanged).
- **Long notes** (>12k chars): segment → lightweight summary per segment → **one** synthesis extraction → same review/commit flow.

## Flow (Long Meetings)

1. **Segment** the transcript (`segmentTranscript`), then **sort by topic** and take non-noise segments (`getSegmentsToExtract`).
2. **Per segment**: `POST /extract-segment-summary` with segment text. Response: `topic`, `briefSummary`, `candidateTasks`, `candidateEntities`, `candidateSignals`. Lightweight and less failure-prone than full extraction.
3. **Synthesis**: `POST /extract-meeting-synthesis` with the collected segment summaries and existing ExtractionContext. One LLM call outputs the normal structured result (ideas, initiatives, tasks) with optional `segmentId`/`segmentTitle` per item for traceability.
4. **Stage and review** the synthesized result exactly as for single-shot; no changes to staging, review UI, or commit.

## API

| Endpoint | Purpose |
|----------|--------|
| `POST /vision-execution/extract-meeting` | Single-shot full extraction (short notes). |
| `POST /vision-execution/extract-segment-summary` | Body: `{ notes: string }`. Lightweight summary for one segment. |
| `POST /vision-execution/extract-meeting-synthesis` | Body: `{ segmentSummaries: SegmentSummaryForSynthesis[], context?: ExtractionContext }`. One full extraction from summaries. |

## Traceability

- Synthesis prompt asks the model to set `segmentId` and `segmentTitle` on each item when it can attribute to a segment.
- Parser preserves these fields; review UI can show "From segment" as before.
- Source remains meeting-extraction; excerpts can come from segment summaries.

## Files

- **Backend**: `local_ai/vision_execution/meeting_extract.py` (`extract_segment_summary`, `extract_meeting_synthesis`), `api/routes/vision_execution.py` (new routes), `local_ai/vision_execution/models.py` (request models).
- **Frontend**: `frontend/src/vision-execution/VisionExecutionView.tsx` (long-meeting branch in `handleExtractMeeting`), `frontend/src/vision-execution/types.ts` (SegmentSummaryResponse, SegmentSummaryForSynthesis), `frontend/src/meeting-intelligence/extractionParser.ts` (preserve segmentId/segmentTitle from response).

---
## 2. Review UI Upgrade (merged from `MEETING_EXTRACTION_REVIEW_UPGRADE.md`)
The meeting extraction review flow was upgraded from a simple accept/reject screen into a lightweight human-judgment editor:
- Extracted candidates are editable before commit.
- Clear “Link” behavior via a `LinkChooser`:
  - “Use as existing (no duplicate)” skips creating a new entity.
  - “Place under as child” sets `parentLink` so commit creates the new entity with correct hierarchy.
- Hierarchy assignment by section:
  - initiative/asset/project/task/people/signals placement is handled through `parentLink` (parentType/parentId).
- People/assets assignment is stored in staging and used at commit time (MVP uses owner/assignee from the first selected person; assets mapping depends on entity type and commit path).
- Chunk progress UX simplification:
  - a single progress bar + short status text
  - detailed per-chunk diagnostics moved under a collapsible “Technical details” section.

Notable MVP limitations preserved by this consolidation:
- Type override exists in UI but commit routing can still be section-bound depending on the current staging/commit implementation.
- Assets are not universally passed into all create payloads in every commit path yet.

---
## 3. Extractor Phase 2 Delta (merged from `extractor-phase2-delta.md`)
Phase-2 focuses on closing the gap between “basic canonization works” and “strategic reader-friendly output”:
- Evidence-aware canonization:
  - Prefer broader/durable initiative/project titles when merging mentions.
  - Profile-driven naming / granularity rules influence canonization decisions.
- Prompting improvements:
  - Stronger guidance for project/signal detection and what evidence patterns to preserve.
  - Profile block must materially influence output.
- Diagnostics improvements:
  - Expanded/added fields to record when naming styles changed, when fragments were preserved/merged, and when generic→specific upgrades occurred.
- Rolling prior context operationalization for segment extraction:
  - Segment summaries build up “prior context” so later segments resolve names better and reduce drift.
  - Frontend hierarchical extraction path was updated to use the segment pipeline and then a synthesis call aligned with rolling prior usage.

---
## 4. Extractor Phase 3 Stabilization (merged from `extractor-phase3-stabilization.md`)
Phase-3 adds resilience and stability without redesign:
- JSON repair + one retry:
  - repair strips common invalid wrappers and trailing comma issues
  - if still invalid, retry once with strict “JSON only” instruction
  - pipeline returns a valid minimal structure plus `error` / diagnostics instead of crashing
- Fallback segment summaries:
  - when a segment fails, produce a rescue fallback summary so synthesis still receives one summary per segment
  - diagnostics track fallback and parse failure segment indices
- Pronoun/reference resolution:
  - lightweight replacement when rolling prior grounds exactly one entity
  - includes diagnostics for whether resolution occurred
- Initiative benchmark matching improvements:
  - phrase subsumption helps match extracted canonical titles even when one side is a super/sub-phrase.
- Expanded diagnostics and segment_diagnostics merging into synthesis diagnostics.
