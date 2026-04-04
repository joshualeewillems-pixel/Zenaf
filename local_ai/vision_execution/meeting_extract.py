"""
Meeting → Intake extractor. Observation-only candidates; no storage.

Deterministic segmentation, per-segment LLM JSON (flat ``text`` + ``confidence`` rows),
Python dedupe and optional deterministic fallbacks, then API payload as ``candidates``
(legacy typed buckets empty). Optional polish LLM (opt-in) may refine summary
and insights only; default path skips it.

Optional extraction context: deterministic title similarity sets existing*MatchId when strong.

Long meetings: extract_segment_summary per segment, then extract_meeting_synthesis
(deterministic summaries → evidence rows → same reducer/canonize/polish).

Layer 1: universal core flow; Layer 2: domain profile guidance; Layer 3: org benchmarks only.
"""
import copy
import json
import logging
import re
from typing import Any, Literal

from local_ai.vision_execution.extraction_formation_summary import build_formation_summary_from_evidence_diag

logger = logging.getLogger(__name__)


def preclean_transcript(notes: str) -> str:
    """
    Modest pre-clean for transcript before extraction (Layer 1 generic).
    Normalize speaker labels, preserve proper names, remove obvious ASR garbage,
    avoid over-cleaning hesitation/repetition that may carry signal meaning.
    """
    from local_ai.vision_execution.meeting_proposition import normalize_speaker_timestamp_lines, strip_transcript_header

    if not notes or not notes.strip():
        return notes
    text = strip_transcript_header(notes.strip())
    text = normalize_speaker_timestamp_lines(text)
    lines = text.split("\n")
    out = []
    # Normalize speaker labels: "Speaker A:" -> "Speaker A:", "SPEAKER 1 -" -> "Speaker 1:"
    speaker_pattern = re.compile(
        r"^(speaker\s*[a-z0-9]+|SPEAKER\s*\d+)\s*[:\-]\s*",
        re.IGNORECASE,
    )
    asr_garbage = re.compile(
        r"^\[?(inaudible|crosstalk|laughter|applause|silence|background noise)\]?\s*$",
        re.IGNORECASE,
    )
    for line in lines:
        s = line.strip()
        if not s:
            out.append("")
            continue
        if asr_garbage.match(s):
            continue
        # Normalize "SPEAKER 1" to "Speaker 1:" for consistency; preserve rest of line
        m = speaker_pattern.match(s)
        if m:
            label = m.group(1)
            rest = s[m.end() :].strip()
            normalized_label = "Speaker " + re.sub(r"^(speaker|SPEAKER)\s*", "", label, flags=re.IGNORECASE).strip()
            if rest:
                out.append(f"{normalized_label}: {rest}")
            else:
                out.append(f"{normalized_label}:")
            continue
        out.append(line)
    return "\n".join(out).strip()


def _meeting_extract_blocked_response(message: str) -> dict[str, Any]:
    """Empty extraction shape + execution_blocked (no meeting_id / no staging)."""
    return {
        "candidates": [],
        "ideas": [],
        "initiatives": [],
        "tasks": [],
        "projects": [],
        "assets": [],
        "peopleReferences": [],
        "people": [],
        "signals": [],
        "insights": [],
        "summary": None,
        "error": "execution_blocked",
        "message": message,
        "execution_blocked": True,
    }


def _meeting_seam_blocked_response(meta: dict[str, Any]) -> dict[str, Any]:
    """Blocked from ``apply_seam_routing`` (privacy, missing OPENAI_API_KEY, unsupported provider)."""
    detail = (meta.get("error_detail") or "Execution blocked").strip()
    out = _meeting_extract_blocked_response(detail)
    pbr = meta.get("privacy_block_reason")
    if pbr:
        out["privacy_block_reason"] = pbr
    return out


def _meeting_execution_principal(user_id: str | None):
    """Account principal when ``user_id`` is set; else anonymous (env / local defaults only)."""
    from local_ai.llm.execution_principal import anonymous_account_principal, principal_for_vision_execution_user

    uid = (user_id or "").strip()
    if uid:
        return principal_for_vision_execution_user(uid)
    return anonymous_account_principal()


def _llm_generate(principal, *, task: str, prompt: str, timeout: int) -> str:
    from local_ai.llm.adapter import LLMRequest
    from local_ai.llm.resolver import get_llm_adapter_for_principal

    adapter = get_llm_adapter_for_principal(principal)
    return adapter.generate_text(LLMRequest(task=task, prompt=prompt, timeout=timeout))


# --- Segment summary (lightweight, for long-meeting hierarchical path) ---

SEGMENT_SUMMARY_PROMPT = """You are summarizing one segment of a long meeting transcript.
Output a compact JSON object only. No markdown, no explanation. Start with { and end with }.

Rules:
- topic: one short phrase (e.g. "Q4 planning", "Resource constraints").
- briefSummary: 2-4 sentences capturing the main points of this segment.
- candidateTasks: array of short task descriptions (one line each); omit if none.
- candidateEntities: array of strings like "Person Name - role" or "Project X" or "Initiative Y"; include workstreams even if not called "project" (e.g. building, implementing, refining something). Omit if none.
- candidateSignals: array of objects with "kind" (one of: attention, risk, opportunity, blocker), optional "label", optional "detail". Include signals from repeated uncertainty, role strain, dependency on person/system, unresolved issues, capacity or friction, ownership ambiguity, execution drift—not only explicit risk/opportunity statements. Omit if none.
- Use prior context only to resolve references (e.g. "the project" -> same project name as in prior; "she" -> name from prior when clear). Do not invent entities not in this segment or prior context. Prefer names/titles already seen when the segment clearly refers to them.

Output format (exactly this structure):
{
  "topic": "...",
  "briefSummary": "...",
  "candidateTasks": ["...", "..."],
  "candidateEntities": ["...", "..."],
  "candidateSignals": [{"kind": "risk", "label": "...", "detail": "..."}]
}

{prior_context_block}

Segment text:
---
{notes}
---

Respond with only the JSON object:"""

STRICT_JSON_ONLY_INSTRUCTION = """
CRITICAL: Return valid JSON only. No commentary, no markdown, no code fence. Start with { and end with }. Do not include trailing commas. Do not truncate the object.
"""


def _repair_json(raw: str) -> str:
    """Lightweight repair: trim non-JSON, recover outermost {}, remove trailing commas, fix common quoting."""
    s = raw.strip()
    if not s:
        return s
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    s = s.strip()
    if s and not s.startswith("{"):
        start = s.find("{")
        if start != -1:
            s = s[start:]
    if s and not s.rstrip().endswith("}"):
        end = s.rfind("}")
        if end != -1:
            s = s[: end + 1]
    s = s.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start : end + 1]
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


def _parse_json_with_fallback(raw: str) -> dict[str, Any] | None:
    """Try to parse JSON; repair pass (trim, outermost {}, trailing commas) then parse."""
    if not raw or not raw.strip():
        return None
    repaired = _repair_json(raw)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    return None


def _parse_json_with_repair_and_diagnostics(
    raw: str,
) -> tuple[dict[str, Any] | None, bool, str | None]:
    """
    Parse JSON with repair. Returns (parsed_dict or None, was_repaired, raw_sample_for_diagnostics).
    """
    if not raw or not raw.strip():
        return None, False, None
    repaired = _repair_json(raw)
    try:
        return json.loads(repaired), bool(repaired != raw.strip()), None
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(raw), False, None
    except json.JSONDecodeError:
        sample = (raw[:800] + ("..." if len(raw) > 800 else "")).replace("\r", "")
        return None, False, sample


def _apply_pronoun_resolution(
    segment_summary: dict[str, Any],
    prior_context: dict[str, Any] | None,
) -> tuple[dict[str, Any], bool, list[str]]:
    """
    Lightweight resolution: when prior has exactly one entity and segment candidate is a generic reference
    (she/he/they, that document, that system), replace with the prior entity. Only when grounded; never invent.
    Returns (updated_summary, resolution_occurred, list of "ref -> entity" for diagnostics).
    """
    if not prior_context or not isinstance(prior_context, dict):
        return segment_summary, False, []
    entities: list[str] = []
    for key in ("entities", "people", "assets"):
        items = prior_context.get(key) or []
        if not isinstance(items, list):
            continue
        for p in items[:5]:
            name = (p.get("name") or p.get("title")) if isinstance(p, dict) else str(p)
            if name and str(name).strip():
                entities.append(str(name).strip())
    if len(entities) != 1:
        return segment_summary, False, []
    single_entity = entities[0]
    raw = segment_summary.get("candidateEntities") or segment_summary.get("candidate_entities") or []
    candidates = list(raw)
    generic_refs = {"she", "he", "they", "that document", "that system", "that thing", "the document", "the system"}
    updated: list[Any] = []
    resolutions: list[str] = []
    for c in candidates:
        s = (c.get("name") if isinstance(c, dict) else c) or ""
        if isinstance(c, str):
            s = c
        s_clean = str(s).strip().lower()
        if s_clean in generic_refs:
            updated.append(single_entity)
            resolutions.append(f"{s_clean} -> {single_entity}")
        else:
            updated.append(c)
    if not resolutions:
        return segment_summary, False, []
    out = dict(segment_summary)
    out["candidateEntities"] = updated
    out["candidate_entities"] = updated
    return out, True, resolutions


def _build_prior_context_block(prior_context: dict[str, Any] | None) -> str:
    """Build a short prior-context block for segment summary (reference continuity only)."""
    if not prior_context or not isinstance(prior_context, dict):
        return ""
    parts = []
    entities = prior_context.get("entities")
    if isinstance(entities, list) and entities:
        names = [str(x).strip() for x in entities[:20] if x is not None and str(x).strip()]
        if names:
            parts.append("Entities already seen: " + ", ".join(names[:15]))
    for key, label in [("people", "People"), ("assets", "Assets"), ("initiatives", "Initiatives"), ("projects", "Projects")]:
        items = prior_context.get(key)
        if isinstance(items, list) and items:
            names = []
            for it in items[:15]:
                if isinstance(it, dict):
                    names.append(it.get("title") or it.get("name") or it.get("id") or "")
                elif isinstance(it, str):
                    names.append(it)
            names = [n for n in names if n]
            if names:
                parts.append(f"{label} already seen: {', '.join(names[:10])}")
    if not parts:
        return ""
    return "Previously seen (for reference continuity only; do not invent these):\n" + "; ".join(parts) + "\n\n"


def _prior_context_from_segment_summary(segment_summary: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    """Build compact rolling prior_context from one segment summary. Merges into existing."""
    out = dict(existing) if existing else {}
    entities: list[str] = list(out.get("entities") or [])
    for key in ("candidateEntities", "candidate_entities"):
        items = segment_summary.get(key)
        if isinstance(items, list):
            for x in items:
                s = (x.get("name") if isinstance(x, dict) else x) or ""
                if isinstance(x, str):
                    s = x
                s = str(s).strip()
                if s and s not in entities:
                    entities.append(s)
    for key in ("candidateTasks", "candidate_tasks"):
        items = segment_summary.get(key)
        if isinstance(items, list):
            for x in items[:5]:
                s = str(x).strip() if isinstance(x, str) else (x.get("title") or x.get("summary") or "").strip()
                if s and s not in entities:
                    entities.append(s)
    for key in ("candidateSignals", "candidate_signals"):
        items = segment_summary.get(key)
        if isinstance(items, list):
            for x in items[:5]:
                if isinstance(x, dict):
                    s = (x.get("label") or x.get("detail") or "").strip()
                else:
                    s = str(x).strip()
                if s and s not in entities:
                    entities.append(s)
    out["entities"] = entities[:40]
    return out


SEGMENT_FALLBACK_PROMPT = """Summarize the key operational meaning of this meeting segment in 1-2 sentences. Focus on workstreams, initiatives, or tensions.
Return valid JSON only. No markdown. Start with { and end with }.
Format:
{
  "summary": "1-2 sentences",
  "possibleInitiatives": ["optional initiative name"],
  "possibleProjects": ["optional project/workstream name"],
  "possibleSignals": ["optional signal phrase"]
}

Segment:
---
{notes}
---
JSON:"""


def _fallback_segment_summary(notes: str, principal) -> dict[str, Any]:
    """Produce a minimal rescue summary when segment extraction fails. Low confidence; for synthesis as weaker evidence."""
    notes = (notes or "").strip()[:6000]
    if not notes:
        return {
            "topic": "unknown",
            "briefSummary": "",
            "candidateTasks": [],
            "candidateEntities": [],
            "candidateSignals": [],
            "_fallback": True,
            "confidence": "low",
        }
    try:
        raw = _llm_generate(
            principal,
            task="meeting_segment_fallback",
            prompt=SEGMENT_FALLBACK_PROMPT.replace("{notes}", notes),
            timeout=30,
        ).strip()
    except Exception as e:
        logger.warning("fallback_segment_summary: generate failed %s", e)
        return {
            "topic": "unknown",
            "briefSummary": notes[:500],
            "candidateTasks": [],
            "candidateEntities": [],
            "candidateSignals": [],
            "_fallback": True,
            "confidence": "low",
        }
    data = _parse_json_with_fallback(raw)
    if not data or not isinstance(data, dict):
        return {
            "topic": "unknown",
            "briefSummary": notes[:500],
            "candidateTasks": [],
            "candidateEntities": [],
            "candidateSignals": [],
            "_fallback": True,
            "confidence": "low",
        }
    summary = (data.get("summary") or "").strip() or notes[:300]
    inits = data.get("possibleInitiatives") or data.get("possible_initiatives") or []
    projs = data.get("possibleProjects") or data.get("possible_projects") or []
    sigs = data.get("possibleSignals") or data.get("possible_signals") or []
    if not isinstance(inits, list):
        inits = [inits] if inits else []
    if not isinstance(projs, list):
        projs = [projs] if projs else []
    if not isinstance(sigs, list):
        sigs = [sigs] if sigs else []
    entities = [str(x).strip() for x in (inits + projs) if x and str(x).strip()]
    signals_list = [{"kind": "attention", "label": str(s).strip(), "detail": None} for s in sigs[:5] if s]
    return {
        "topic": "unknown",
        "briefSummary": summary,
        "candidateTasks": [],
        "candidateEntities": entities[:15],
        "candidateSignals": signals_list,
        "_fallback": True,
        "confidence": "low",
    }


def extract_segments_with_rolling_prior_context(
    segment_texts: list[str],
    profile_id: str | None = None,
    return_diagnostics: bool = False,
    routing_context: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    """
    Run extract_segment_summary on each segment with rolling prior_context built from
    previous segment outputs. On segment failure, use fallback rescue summary so synthesis
    does not lose meaning. Returns (segment_summaries, prior_contexts_used, segment_diagnostics or None).

    When ``routing_context`` is provided, a single policy gate runs for the whole batch (not per segment).
    """
    from local_ai.vision_execution.meeting_extraction_execution import meeting_execution_seam

    with meeting_execution_seam(routing_context, mode="meeting_extract_chunks", user_id=user_id) as seam_meta:
        if routing_context and seam_meta.get("execution_blocked"):
            return [], [], {
                "execution_blocked": True,
                "error_detail": seam_meta.get("error_detail") or "Execution blocked",
            }

        summaries: list[dict[str, Any]] = []
        priors_used: list[dict[str, Any]] = []
        prior: dict[str, Any] = {}
        fallback_indices: list[int] = []
        parse_failure_indices: list[int] = []
        for i, text in enumerate(segment_texts):
            if not (text or "").strip():
                summaries.append({"topic": "", "briefSummary": "", "candidateTasks": [], "candidateEntities": [], "candidateSignals": []})
                priors_used.append(dict(prior))
                continue
            priors_used.append(dict(prior))
            seg = extract_segment_summary(
                text,
                prior_context=prior if prior else None,
                user_id=user_id,
            )
            if seg.get("error"):
                if seg.get("_parse_failure_raw_sample") and return_diagnostics:
                    parse_failure_indices.append(i)
                fallback = _fallback_segment_summary(text, _meeting_execution_principal(user_id))
                fallback["_segment_index"] = i
                summaries.append(fallback)
                fallback_indices.append(i)
                prior = _prior_context_from_segment_summary(fallback, prior)
            else:
                summaries.append(seg)
                prior = _prior_context_from_segment_summary(seg, prior)
        diag = None
        if return_diagnostics:
            pronoun_resolutions: list[dict[str, Any]] = []
            for idx, seg in enumerate(summaries):
                if seg.get("_pronoun_resolution"):
                    pronoun_resolutions.append({"segment_index": idx, "resolutions": seg["_pronoun_resolution"]})
            diag = {}
            if fallback_indices or parse_failure_indices:
                diag["fallback_segment_indices"] = fallback_indices
                diag["parse_failure_segment_indices"] = parse_failure_indices
            if pronoun_resolutions:
                diag["pronoun_resolution_occurred"] = True
                diag["pronoun_resolutions_by_segment"] = pronoun_resolutions
            if priors_used and any(p.get("entities") for p in priors_used):
                diag["prior_entities_used"] = True
            if not diag:
                diag = None
        return summaries, priors_used, diag
    
    
def extract_segment_summary(
    notes: str,
    prior_context: dict[str, Any] | None = None,
    routing_context: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Lightweight extraction for one transcript segment. Returns topic, briefSummary,
    candidateTasks, candidateEntities, candidateSignals. Used by hierarchical long-meeting flow.
    prior_context: optional dict with keys people, assets, initiatives, projects (lists of dicts with title/name/id)
    for reference continuity across chunks; used only to resolve references, not to invent entities.

    ``routing_context``: when set (e.g. standalone POST /extract-segment-summary), run execution policy gate.
    Internal batch calls pass ``routing_context=None`` after the batch gate in
    ``extract_segments_with_rolling_prior_context``.
    """
    notes = (notes or "").strip()
    notes = notes[:8000]  # guard: cap segment size for prompt
    prior_context_block = _build_prior_context_block(prior_context)
    logger.debug("[segment-summary] len=%s", len(notes))
    if not notes:
        return {"topic": "", "briefSummary": "", "candidateTasks": [], "candidateEntities": [], "candidateSignals": []}

    from local_ai.vision_execution.meeting_extraction_execution import meeting_execution_seam

    with meeting_execution_seam(routing_context, mode="meeting_extract_chunks", user_id=user_id) as seam_meta:
        if routing_context and seam_meta.get("execution_blocked"):
            return {
                "topic": "",
                "briefSummary": "",
                "candidateTasks": [],
                "candidateEntities": [],
                "candidateSignals": [],
                "error": seam_meta.get("error_detail") or "Execution blocked",
                "execution_blocked": True,
            }

        principal = _meeting_execution_principal(user_id)

        prompt = SEGMENT_SUMMARY_PROMPT.format(notes=notes, prior_context_block=prior_context_block)
        try:
            raw = _llm_generate(principal, task="meeting_segment_summary", prompt=prompt, timeout=45).strip()
        except Exception:
            return {
                "topic": "",
                "briefSummary": "",
                "candidateTasks": [],
                "candidateEntities": [],
                "candidateSignals": [],
                "error": "Segment summary failed. Try again.",
            }
    
        data, was_repaired, parse_failure_sample = _parse_json_with_repair_and_diagnostics(raw)
        if data is None:
            try:
                raw2 = _llm_generate(
                    principal,
                    task="meeting_segment_summary_retry",
                    prompt=prompt + STRICT_JSON_ONLY_INSTRUCTION,
                    timeout=45,
                ).strip()
                data = _parse_json_with_fallback(raw2)
            except Exception:
                data = None
            if data is None:
                sample = parse_failure_sample or (raw[:500] + ("..." if len(raw) > 500 else "")).replace("\r", "")
                logger.warning("extract_segment_summary: invalid JSON after retry. Sample: %s", sample[:300])
                return {
                    "topic": "",
                    "briefSummary": "",
                    "candidateTasks": [],
                    "candidateEntities": [],
                    "candidateSignals": [],
                    "error": "Invalid response from model.",
                    "_parse_failure_raw_sample": sample[:1000],
                }
    
        def _str_list(key: str) -> list[str]:
            val = data.get(key)
            if not isinstance(val, list):
                return []
            return [str(x).strip() for x in val if x is not None and str(x).strip()]
    
        def _signals_list() -> list[dict[str, Any]]:
            val = data.get("candidateSignals")
            if not isinstance(val, list):
                return []
            out = []
            valid_kinds = {"attention", "risk", "opportunity", "blocker"}
            for x in val:
                if not isinstance(x, dict):
                    continue
                kind = (x.get("kind") or "").strip().lower()
                if kind not in valid_kinds:
                    kind = "attention"
                out.append({
                    "kind": kind,
                    "label": _normalize_str(x.get("label")) or kind,
                    "detail": _normalize_str(x.get("detail")),
                })
            return out
    
        result = {
            "topic": _normalize_str(data.get("topic")),
            "briefSummary": _normalize_str(data.get("briefSummary")),
            "candidateTasks": _str_list("candidateTasks"),
            "candidateEntities": _str_list("candidateEntities"),
            "candidateSignals": _signals_list(),
        }
        seg_out, resolution_occurred, resolutions = _apply_pronoun_resolution(result, prior_context)
        if resolution_occurred and resolutions:
            seg_out["_pronoun_resolution"] = resolutions
        return seg_out


# --- Full extraction (single-shot or synthesis) ---

EXTRACT_PROMPT_BASE = """You are an intake assistant. Extract actionable items from meeting notes.

Definitions (use these distinctions strictly):
- Initiative: broader durable area of work or recurring strategic theme that groups related efforts (e.g. Clinic Operations, Patient Onboarding and Follow-Up). Not a single project or one-off idea.
- Project: concrete coordinated effort, workstream, or body of work—even if the notes do not use the word "project". Include whenever there is evidence of: building, refining, sequencing, operationalizing, implementing, packaging, integrating, or creating a workflow, tool, asset, document, or content sequence. Has a scope and outcome. Can sit under an initiative. Prefer preserving partial workstreams over dropping them.
- Task: specific actionable unit of work (who could do what by when, or a clear next step).
- Idea: raw possibility, opportunity, concept, or suggested direction (not yet a commitment).
- Signal: attention/risk/opportunity/blocker inferred from repeated concern, friction, ambiguity, dependency, hesitation, or drift—not only from explicit statements. Treat as signal evidence: repeated uncertainty; role strain or burden concentration; dependency on a person/system; repeated return to an unresolved issue; segmentation or handoff tension; enthusiasm or strong alignment; capacity mismatch; operational friction; ambiguity about ownership or process; scattered materials or poor accessibility; execution drift. Emit weak signal candidates when in doubt; downstream merge will consolidate.

Rules:
- The profile rules below must materially influence your output: initiative naming style, granularity, project detection, signal inference, asset specificity, and person reference.
- Prefer broader canonical initiative buckets over narrow paraphrases. Merge local themes into one durable initiative name when they clearly belong together.
- Preserve exact named entities (people, systems, documents) where they appear in the source text. Do not invent specifics not grounded in the notes. If a generic reference (e.g. "the document") is later named (e.g. "Q4 onboarding draft"), use the specific name when grounded in the text.
- Avoid generic assets like "document", "plan", "resource" unless no more specific asset can be supported by the text.
- Extract only meaningful, actionable items. Skip small talk and vague mentions.
- Suggest owner/assignee ONLY if clearly named or strongly implied. Otherwise use null.
- Keep titles and descriptions concise. For each item set "confidence" to "high"|"medium"|"low" and "sourceExcerpt" to a short verbatim snippet that supports it (omit if nothing fits).
- Merge overlapping or duplicate initiatives/projects/tasks into a single, well-formed item. When a local idea fits under a broader initiative, merge into that initiative.
- Assign projects under an initiative and tasks under a project or initiative when possible.
- Emit signals when risks, blockers, or opportunities are evident (including from repeated concern or friction). Use kind = "attention"|"risk"|"opportunity"|"blocker".
- People: only real identity, proper name, or meaningful role. Do NOT emit generic speaker labels (Speaker A/B/C). If a pronoun or role is resolvable from prior context in the notes, use the resolved name.
- Assets: prefer specific named tools, systems, documents, workflows. Avoid generic "AI Tool" or "AI Systems" unless no more specific name exists. Distinguish systems/platforms (e.g. named EMR/PM tools) from people when the text supports it.
- Output only a single JSON object. No markdown, no explanation. Start with { and end with }.
"""

EXTRACT_PROMPT_CONTEXT_RULES = """
When "Existing entities" are provided below:
- Prefer linking to existing entities where there is a clear match (same or very similar title/name).
- Only propose NEW initiatives, projects, tasks, assets, or people when no strong match exists in the list.
- When you link to an existing entity, set the corresponding existing*MatchId to that entity's id and set matchConfidence (0-1) to how strong the match is (e.g. 0.9 for same title).
- Preserve relationships when possible: e.g. a task under an existing project should set existingProjectMatchId to that project's id; a project under an existing initiative should set existingInitiativeMatchId.
"""

EXTRACT_PROMPT_FORMAT_NO_CONTEXT = """
Output format (exactly this structure, no other keys; fields may be empty when not applicable):
{
  "summary": { "text": "one-paragraph summary of the meeting", "confidence": "high"|"medium"|"low"|null } | null,
  "insights": [
    { "statement": "...", "sourceQuote": "...", "confidence": "high"|"medium"|"low"|null }
  ],
  "ideas": [
    { "title": "...", "summary": "...", "description": "...", "status": "Captured", "confidence": "high"|"medium"|"low", "sourceExcerpt": "..." }
  ],
  "initiatives": [
    { "title": "...", "brief": "...", "status": "Draft", "ownerName": null, "notes": "...", "confidence": "high"|"medium"|"low", "sourceExcerpt": "..." }
  ],
  "projects": [
    { "title": "...", "brief": "...", "status": "Draft", "initiativeTitle": "...", "confidence": "high"|"medium"|"low", "sourceExcerpt": "..." }
  ],
  "tasks": [
    { "title": "...", "description": "...", "status": "Todo", "assigneeName": null, "notes": "...", "confidence": "high"|"medium"|"low", "sourceExcerpt": "..." }
  ],
  "assets": [
    { "name": "...", "kind": "tool"|"system"|"document"|"inventory"|"other", "description": "...", "confidence": "high"|"medium"|"low"|null, "sourceExcerpt": "..." }
  ],
  "people": [
    { "name": "...", "role": "...", "context": "...", "confidence": "high"|"medium"|"low"|null, "sourceExcerpt": "..." }
  ],
  "signals": [
    { "kind": "attention"|"risk"|"opportunity"|"blocker", "label": "...", "detail": "...", "confidence": "high"|"medium"|"low"|null, "sourceExcerpt": "..." }
  ]
}
"""

EXTRACT_PROMPT_FORMAT_WITH_CONTEXT = """
Output format (exactly this structure; include optional existing*MatchId and matchConfidence when you link to an existing entity; fields may be empty when not applicable):
{
  "summary": { "text": "one-paragraph summary of the meeting", "confidence": "high"|"medium"|"low"|null } | null,
  "insights": [
    { "statement": "...", "sourceQuote": "...", "confidence": "high"|"medium"|"low"|null }
  ],
  "ideas": [
    { "title": "...", "summary": "...", "description": "...", "status": "Captured", "confidence": "high"|"medium"|"low", "sourceExcerpt": "..." }
  ],
  "initiatives": [
    { "title": "...", "brief": "...", "status": "Draft", "ownerName": null, "notes": "...", "confidence": "high"|"medium"|"low", "sourceExcerpt": "...", "existingInitiativeMatchId": "id-or-null", "matchConfidence": 0.0-1.0-or-null }
  ],
  "projects": [
    { "title": "...", "brief": "...", "status": "Draft", "initiativeTitle": "...", "confidence": "high"|"medium"|"low", "sourceExcerpt": "...", "existingInitiativeMatchId": "id-or-null", "existingProjectMatchId": "id-or-null", "matchConfidence": 0.0-1.0-or-null }
  ],
  "tasks": [
    { "title": "...", "description": "...", "status": "Todo", "assigneeName": null, "notes": "...", "confidence": "high"|"medium"|"low", "sourceExcerpt": "...", "existingProjectMatchId": "id-or-null", "existingTaskMatchId": "id-or-null", "existingPersonMatchId": "id-or-null", "matchConfidence": 0.0-1.0-or-null }
  ],
  "assets": [
    { "name": "...", "kind": "tool"|"system"|"document"|"inventory"|"other", "description": "...", "confidence": "high"|"medium"|"low"|null, "sourceExcerpt": "...", "existingAssetMatchId": "id-or-null", "matchConfidence": 0.0-1.0-or-null }
  ],
  "people": [
    { "name": "...", "role": "...", "context": "...", "confidence": "high"|"medium"|"low"|null, "sourceExcerpt": "...", "existingPersonMatchId": "id-or-null", "matchConfidence": 0.0-1.0-or-null }
  ],
  "signals": [
    { "kind": "attention"|"risk"|"opportunity"|"blocker", "label": "...", "detail": "...", "confidence": "high"|"medium"|"low"|null, "sourceExcerpt": "..." }
  ]
}
"""


def _normalize_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip() if isinstance(v, str) else str(v)


VALID_CONFIDENCE = frozenset({"high", "medium", "low"})


def _normalize_confidence(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower() if isinstance(v, str) else str(v).lower()
    return s if s in VALID_CONFIDENCE else None


MATCH_KEYS = (
    "existingInitiativeMatchId",
    "existingProjectMatchId",
    "existingTaskMatchId",
    "existingAssetMatchId",
    "existingPersonMatchId",
    "matchConfidence",
)


def _normalize_list(obj: Any, key: str, default: list) -> list[dict[str, Any]]:
    raw = obj.get(key) if isinstance(obj, dict) else None
    if not isinstance(raw, list):
        return default
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        row = {}
        for k, v in item.items():
            if k == "confidence":
                row[k] = _normalize_confidence(v)
            elif k == "sourceExcerpt":
                row[k] = _normalize_str(v) if (v is not None and str(v).strip()) else None
            elif k in MATCH_KEYS:
                if k == "matchConfidence":
                    try:
                        row[k] = float(v) if v is not None else None
                    except (TypeError, ValueError):
                        row[k] = None
                else:
                    row[k] = _normalize_str(v) if (v is not None and str(v).strip()) else None
            elif k == "harvestItemIds":
                if isinstance(v, list):
                    row[k] = [str(x).strip() for x in v if x is not None and str(x).strip()]
                else:
                    row[k] = []
            elif v is None:
                row[k] = None
            elif isinstance(v, str):
                row[k] = _normalize_str(v)
            else:
                row[k] = v
        out.append(row)
    return out


def _build_context_block(context: dict[str, Any] | None) -> str:
    if not context or not isinstance(context, dict):
        return ""
    parts = ["Existing entities (prefer linking to these when there is a clear match):"]
    for key in ("initiatives", "projects", "tasks", "assets", "people"):
        items = context.get(key) if isinstance(context.get(key), list) else []
        if not items:
            continue
        label = key.capitalize()
        lines = []
        for it in items[:50]:  # cap to avoid huge prompt
            if not isinstance(it, dict):
                continue
            id_ = it.get("id") or ""
            title = it.get("title") or it.get("name") or id_
            extra = ""
            if key == "projects":
                init_title = it.get("initiative_title") or it.get("initiativeTitle")
                if init_title:
                    extra = f" (initiative: {init_title})"
            elif key == "tasks":
                proj_title = it.get("project_title") or it.get("projectTitle")
                if proj_title:
                    extra = f" (project: {proj_title})"
            lines.append(f"  - id={id_!r} title={title!r}{extra}")
        if lines:
            parts.append(f"{label}:\n" + "\n".join(lines))
    if len(parts) <= 1:
        return ""
    return "\n\n".join(parts) + "\n\n"


def _workspace_mirror_prompt_block(workspace_packet: dict[str, Any] | None) -> str:
    """Compressed reasoning buffer from client workspace packet (no filesystem)."""
    if not workspace_packet or not isinstance(workspace_packet, dict):
        return ""
    cap = workspace_packet.get("reasoningCapsule") or workspace_packet.get("reasoning_capsule")
    if not isinstance(cap, dict):
        return ""
    lines: list[str] = []
    th = cap.get("themes") or []
    if isinstance(th, list) and th:
        parts = [str(x).strip() for x in th[:8] if str(x).strip()]
        if parts:
            lines.append("Themes: " + "; ".join(parts))
    np = cap.get("namedPrograms") or cap.get("named_programs") or []
    if isinstance(np, list) and np:
        parts = [str(x).strip() for x in np[:8] if str(x).strip()]
        if parts:
            lines.append("Named surfaces: " + "; ".join(parts))
    tg = cap.get("tags") or []
    if isinstance(tg, list) and tg:
        parts = [str(x).strip() for x in tg[:12] if str(x).strip()]
        if parts:
            lines.append("Tags: " + ", ".join(parts))
    if not lines:
        return ""
    return "\n".join(lines)[:1800]


# Layer 2 profile guidance. Optional keys (initiative_naming_style, etc.) can be set per profile
# for extraction quality; core defaults here are generic. Org-specific values belong in Layer 3.
PROFILE_GUIDANCE = {
    "clinic_operations": {
        "initiative": """Prefer 3–7 broad initiatives that summarize the main areas of work (durable operating areas), such as:
- Clinic Operations
- Patient Onboarding and Follow-Up
- Content and Program Development
- Community Events and Engagement
- Systems and Automation Infrastructure
When a local idea fits clearly under one of these or a similar broad area, merge it into that initiative instead of creating a new one.""",
        "signals": """Focus signals on operational friction, patient experience, financial clarity, and strategic expansion (e.g. manual workflows, incomplete onboarding/follow-up, unclear scope vs revenue).""",
        "assets": """Treat named systems, documents, workflows, and tools as assets (e.g. practice management / EMR, onboarding emails, patient education media, dashboards). Avoid generic labels like "AI tool" when a more specific name exists.""",
        "people": """Emit people only for real names and meaningful roles (e.g. clinic lead, front office, creative/community partner, billing company). Do NOT emit generic speaker labels like "Speaker A"/"Speaker B"/"Speaker C".""",
        "grouping": """Merge overlapping or duplicate initiatives/projects/tasks into single, well-formed items. Prefer canonical buckets over many narrow, local initiatives.""",
        "initiative_naming_style": "Broad, durable operating areas; 3–7 stable buckets.",
        "initiative_granularity_rule": "One initiative per major area of work; merge narrow themes into the closest bucket.",
        "project_detection_rule": "Concrete workstreams or coordinated efforts (e.g. onboarding flow, content program, event series) even if not called 'project'.",
        "signal_inference_rule": "Infer from repeated concern, friction, ambiguity, or hesitation; not only explicit risk/opportunity statements.",
        "asset_specificity_rule": "Prefer named systems, workflows, documents; avoid generic 'document' or 'resource'.",
        "person_reference_rule": "Real names and roles only; never Speaker A/B/C.",
    },
    "service_business": {
        "initiative": """Prefer 3–7 broad initiatives such as:
- Lead Generation and Marketing
- Sales Pipeline and Onboarding
- Service Delivery and Quality
- Client Success and Retention
- Internal Operations and Finance""",
        "signals": """Highlight revenue, client satisfaction, and delivery risks/opportunities (e.g. churn risk, pipeline gaps, process bottlenecks).""",
        "assets": """Treat CRM systems, templates, SOPs, and playbooks as assets when they are important to how work gets done.""",
        "people": """Focus on staff and client roles that influence decisions or execution (e.g. account managers, project leads, key client stakeholders).""",
        "grouping": """Merge duplicate or very similar initiatives/projects into canonical buckets representing core parts of the business.""",
        "initiative_naming_style": "Business-area buckets (lead gen, pipeline, delivery, success, operations).",
        "initiative_granularity_rule": "One initiative per major business function.",
        "project_detection_rule": "Client workstreams, internal efforts, campaigns—concrete bodies of work.",
        "signal_inference_rule": "Revenue, delivery, and relationship risks/opportunities from context and repetition.",
        "asset_specificity_rule": "Named CRMs, playbooks, templates when referenced.",
        "person_reference_rule": "Named staff and client roles only.",
    },
    "nonprofit_programs": {
        "initiative": """Prefer 3–7 program-like initiatives such as:
- Programs and Services
- Community Outreach and Engagement
- Fundraising and Partnerships
- Volunteer Management
- Operations and Compliance""",
        "signals": """Focus on risks/opportunities that affect impact, funding, sustainability, or community trust.""",
        "assets": """Treat grant trackers, donor CRMs, curricula, and shared resources as assets when they are repeatedly referenced.""",
        "people": """Emit program directors, board members, partners, and major donors with clear roles; ignore anonymous speakers without meaningful roles.""",
        "grouping": """Merge similar program ideas into stable, named initiatives rather than many small, overlapping ones.""",
        "initiative_naming_style": "Program and function areas (programs, outreach, fundraising, volunteer, operations).",
        "initiative_granularity_rule": "One initiative per major program or function.",
        "project_detection_rule": "Specific programs, campaigns, or coordinated efforts.",
        "signal_inference_rule": "Impact, funding, and sustainability signals from discussion.",
        "asset_specificity_rule": "Named trackers, CRMs, curricula when referenced.",
        "person_reference_rule": "Named roles and organizations only.",
    },
}


def _profile_block(profile_id: str | None) -> str:
    key = profile_id or "clinic_operations"
    cfg = PROFILE_GUIDANCE.get(key, PROFILE_GUIDANCE["clinic_operations"])
    parts = [
        "Profile (use these rules to drive naming, granularity, project detection, signals, assets, and people):",
        "",
        "Initiatives:",
        cfg["initiative"],
        "",
        "Signals:",
        cfg["signals"],
        "",
        "Assets:",
        cfg["assets"],
        "",
        "People:",
        cfg["people"],
        "",
        "Grouping:",
        cfg["grouping"],
    ]
    for opt_key, label in [
        ("initiative_naming_style", "Initiative naming style"),
        ("initiative_granularity_rule", "Initiative granularity"),
        ("project_detection_rule", "Project detection"),
        ("signal_inference_rule", "Signal inference"),
        ("asset_specificity_rule", "Asset specificity"),
        ("person_reference_rule", "Person reference"),
    ]:
        if cfg.get(opt_key):
            parts.append("")
            parts.append(f"{label}: {cfg[opt_key]}")
    return "\n".join(parts) + "\n\n"


def _guidance_dict_from_core_profile_row(row: dict[str, Any]) -> dict[str, Any]:
    """Layer 2 guidance biased by the user's canonical (or explicitly chosen) core row."""
    from local_ai.vision_execution.core_profile_context import build_core_profile_summary

    base = copy.deepcopy(PROFILE_GUIDANCE["clinic_operations"])
    summary = build_core_profile_summary(row)
    if summary:
        base["initiative"] = (
            str(base.get("initiative") or "")
            + "\n\nPrioritize naming, granularity, and emphasis consistent with this user core profile:\n"
            + summary
        )
        base["grouping"] = str(base.get("grouping") or "") + (
            "\nRespect the user's stated strategic filter, constraints, and non-negotiables when merging entities."
        )
    return base


def _resolve_profile_guidance(profile_id: str | None, user_id: str | None) -> dict[str, Any]:
    """
    Profile guidance for extraction/canonization.

    - Known template keys (e.g. clinic_operations) use static PROFILE_GUIDANCE.
    - Explicit UUID + authenticated user: load that row if owned.
    - No profile_id + authenticated user: use canonical core profile for this user.
    - Otherwise: clinic_operations template.
    """
    pid = str(profile_id).strip() if profile_id else None
    uid = str(user_id).strip() if user_id else None

    if pid and pid in PROFILE_GUIDANCE:
        return copy.deepcopy(PROFILE_GUIDANCE[pid])

    if pid and uid:
        from local_ai.vision_execution import storage as St

        row = St.get_core_profile(pid, uid)
        if row:
            return _guidance_dict_from_core_profile_row(row)

    if uid and not pid:
        from local_ai.vision_execution import service as VeSvc

        row = VeSvc.canonical_core_profile_for_user(uid)
        if row:
            return _guidance_dict_from_core_profile_row(row)

    if pid:
        return copy.deepcopy(PROFILE_GUIDANCE.get(pid, PROFILE_GUIDANCE["clinic_operations"]))

    return copy.deepcopy(PROFILE_GUIDANCE["clinic_operations"])


def extract_meeting(
    notes: str,
    context: dict[str, Any] | None = None,
    profile_id: str | None = None,
    return_diagnostics: bool = False,
    routing_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    *,
    skip_harvest: bool = False,
    evidence_extraction_preset: Literal["default", "fast_local", "exhaustive"] = "default",
    include_meeting_polish: bool = False,
    workspace_packet: dict[str, Any] | None = None,
    use_external_ai_extraction: bool = False,
    external_ai_engine: str | None = None,
    wash_data_for_call: bool = True,
) -> dict[str, Any]:
    """
    Run a single LLM call to extract ideas, initiatives, and tasks from meeting notes.
    If context is provided, prefer linking to existing entities and output existing*MatchId/matchConfidence.
    Notes are precleaned (speaker normalization, ASR garbage removal) then run through a post-merge
    canonization pass (Layer 1 generic, profile-driven). Returns proposed items only; does not persist.
    When return_diagnostics=True (e.g. benchmark runs), response includes diagnostics (raw vs canonical).

    Optional ``routing_context`` (from client) enables execution policy / privacy_mode alignment.

    When ``skip_harvest`` is False (default), returns a synthetic ``harvest_ledger`` built from
    per-segment evidence rows (legacy harvest/normalize LLM passes are not on the critical path).

    ``evidence_extraction_preset="fast_local"`` uses shorter per-segment LLM timeouts and smaller
    chunk targets for interactive runs; deterministic fallbacks are unchanged. Diagnostics record the
    preset and timeout (``evidence`` block when ``return_diagnostics=True``).

    Optional meeting polish (LLM summary/insights) is **off by default**; set
    ``include_meeting_polish=True`` for an explicit refinement pass. Polish is never run when
    ``evidence_extraction_preset`` is ``fast_local`` (interactive path stays evidence → reducer only).

    When ``use_external_ai_extraction=True``, the evidence-segment pipeline is skipped in favor of
    ``meeting_external_extract`` (single structured LLM call). ``external_ai_engine`` should be
    ``provider:model`` (e.g. ``openai:gpt-4.1-mini`` or ``ollama:qwen3:8b``). ``wash_data_for_call``
    controls ``prepare_council_contexts`` before the outbound prompt; unwashed cloud calls are blocked
    when policy/privacy disallow cloud outbound.
    """
    notes = (notes or "").strip()
    if not notes:
        return {
            "candidates": [],
            "ideas": [],
            "initiatives": [],
            "tasks": [],
            "projects": [],
            "assets": [],
            "peopleReferences": [],
            "people": [],
            "signals": [],
            "insights": [],
            "summary": None,
            "harvest_ledger": None,
        }

    from local_ai.vision_execution.meeting_extraction_execution import meeting_execution_seam

    with meeting_execution_seam(routing_context, mode="meeting_extract_single", user_id=user_id) as seam_meta:
        if routing_context and seam_meta.get("execution_blocked"):
            return _meeting_seam_blocked_response(seam_meta)

        import time
        from local_ai.activity import log_activity_simple, new_id, ActivityType, ActivityEntityType
        from local_ai.vision_execution.extraction_post_process import (
            PostProcessExtractionOptions,
            post_process_extraction,
            should_skip_document_budget_for_chunked_request,
        )
        from local_ai.vision_execution.graph_interpretation import interpret_against_graph

        t_start = time.time()
        meeting_id = new_id()
        logger.info("[extract-meeting] start")
    
        notes = preclean_transcript(notes)

        if use_external_ai_extraction:
            from local_ai.vision_execution.meeting_external_extract import extract_meeting_with_external_ai

            return extract_meeting_with_external_ai(
                notes,
                context=context,
                profile_id=profile_id,
                return_diagnostics=return_diagnostics,
                routing_context=routing_context,
                user_id=user_id,
                external_ai_engine=external_ai_engine,
                wash_data_for_call=wash_data_for_call,
                skip_harvest=skip_harvest,
                workspace_packet=workspace_packet if isinstance(workspace_packet, dict) else None,
                evidence_extraction_preset=str(evidence_extraction_preset),
            )

        input_len = len(notes)
        has_context = context is not None and bool(_build_context_block(context))
        logger.info("[extract-meeting] input_len=%s has_context=%s", input_len, has_context)

        principal = _meeting_execution_principal(user_id)

        from local_ai.vision_execution.harvest_substrate import HarvestLedger
        from local_ai.vision_execution.meeting_literal_anchors import literal_anchor_candidates_for_chunk
        from local_ai.vision_execution.meeting_evidence_pipeline import (
            CONFIDENCE_TIER_LEGEND,
            MEETING_EVIDENCE_ROLLING_PRIOR_FAST_LOCAL,
            SOURCE_STAGE_LITERAL_ANCHOR,
            SOURCE_STAGE_MODEL,
            attach_possible_matches_to_candidates,
            build_deterministic_summary_from_candidates,
            candidates_to_harvest_ledger,
            dedupe_candidates_ordered,
            extract_candidate_rows_all_segments,
            extraction_candidate_provenance_summary,
            extraction_candidate_to_api_dict,
            resolve_meeting_evidence_extraction_preset,
            run_optional_meeting_polish,
            segment_notes_for_evidence,
        )

        ev_timeout_s, ev_max_chunk, ev_preset_label, ev_min_merge = resolve_meeting_evidence_extraction_preset(
            evidence_extraction_preset
        )
        logger.info(
            "[extract-meeting] evidence_preset=%s segment_llm_timeout_s=%s segment_max_chunk=%s min_merge=%s",
            ev_preset_label,
            ev_timeout_s,
            ev_max_chunk,
            ev_min_merge,
        )

        def _gen_ev(**kw: Any) -> str:
            return _llm_generate(
                principal,
                task=str(kw.get("task") or "meeting_evidence_segment"),
                prompt=str(kw.get("prompt") or ""),
                timeout=int(kw.get("timeout") or ev_timeout_s),
            )

        ctx_dict = context if isinstance(context, dict) else None
        t_evidence_start = time.perf_counter()
        _, lit_meta = literal_anchor_candidates_for_chunk(
            notes,
            ctx_dict,
            workspace_packet=workspace_packet if isinstance(workspace_packet, dict) else None,
        )
        evidence_segments_planned = 0
        diag_chunk_id: str | None = None
        if isinstance(routing_context, dict):
            diag_chunk_id = routing_context.get("diagnosticsChunkId") or routing_context.get("chunkId")
            if diag_chunk_id is not None:
                diag_chunk_id = str(diag_chunk_id)

        segments = segment_notes_for_evidence(notes, max_chunk=ev_max_chunk, min_merge=ev_min_merge)
        evidence_segments_planned = len(segments)
        rolling_prior = (
            MEETING_EVIDENCE_ROLLING_PRIOR_FAST_LOCAL if ev_preset_label == "fast_local" else 2800
        )
        wm_block = _workspace_mirror_prompt_block(
            workspace_packet if isinstance(workspace_packet, dict) else None
        )
        cands, ev_diag = extract_candidate_rows_all_segments(
            segments,
            _gen_ev,
            task_name="meeting_evidence_segment",
            timeout=ev_timeout_s,
            rolling_prior_max_chars=rolling_prior,
            full_notes=notes,
            principal=principal,
            seam_routing_active=bool(routing_context),
            evidence_extraction_preset=ev_preset_label,
            evidence_segment_max_chunk=ev_max_chunk,
            workspace_mirror_block=wm_block,
        )
        ev_diag["literal_anchor_meta"] = lit_meta
        _ev_trace = ev_diag.get("evidence_extraction_trace_summary")
        if _ev_trace:
            logger.info(
                "[extract-meeting] evidence_extraction_trace meeting_id=%s chunk_id=%s %s",
                meeting_id,
                diag_chunk_id,
                json.dumps(_ev_trace, default=str),
            )

        attach_possible_matches_to_candidates(cands, ctx_dict)
        api_candidates = [extraction_candidate_to_api_dict(c) for c in cands]
        evidence_phase_ms = (time.perf_counter() - t_evidence_start) * 1000.0
        literal_cand_n = sum(1 for c in cands if c.internal_source_stage == SOURCE_STAGE_LITERAL_ANCHOR)
        model_cand_n = sum(1 for c in cands if c.internal_source_stage == SOURCE_STAGE_MODEL)
        llm_skipped = False
        logger.info(
            "[extract-meeting] pass0 chunk_id=%s has_literal_anchor_input=%s evidence_ms=%.1f literal_n=%s model_n=%s "
            "candidates=%s meeting_id=%s low_value_literal=%s capped=%s",
            diag_chunk_id,
            bool((lit_meta.get("raw_anchor_count") or 0) > 0),
            evidence_phase_ms,
            literal_cand_n,
            model_cand_n,
            len(cands),
            meeting_id,
            lit_meta.get("low_value_literal_anchor"),
            lit_meta.get("anchors_capped"),
        )

        ledger = HarvestLedger.empty(meeting_id) if skip_harvest else candidates_to_harvest_ledger(meeting_id, cands)

        if not cands:
            if ev_preset_label != "fast_local":
                logger.warning(
                    "[extract-meeting] no extraction candidates segments=%s failed=%s",
                    ev_diag.get("evidence_segments_total"),
                    ev_diag.get("evidence_segments_failed"),
                )
                out_fail: dict[str, Any] = {
                    "candidates": [],
                    "ideas": [],
                    "initiatives": [],
                    "tasks": [],
                    "projects": [],
                    "assets": [],
                    "peopleReferences": [],
                    "people": [],
                    "signals": [],
                    "summary": None,
                    "insights": [],
                    "meeting_id": meeting_id,
                    "error": "evidence_extraction_failed",
                    "message": "No durable observations could be extracted from any segment. Try again or use shorter notes.",
                    "harvest_ledger": ledger.to_json_dict(),
                }
                if return_diagnostics:
                    out_fail["_diagnostics"] = {
                        "evidence": ev_diag,
                        "formation_summary": build_formation_summary_from_evidence_diag(ev_diag),
                        "parse_failure": False,
                    }
                return out_fail
            logger.info(
                "[extract-meeting] fast_local: no durable candidates (empty success) segments=%s",
                ev_diag.get("evidence_segments_total"),
            )

        logger.info(
            "[extract-meeting] candidates=%s evidence_segments_planned=%s wall_s=%.2fs",
            len(cands),
            evidence_segments_planned,
            time.time() - t_start,
        )

        ev_diag["reducer"] = {
            "promotions": [],
            "promotion_count": 0,
            "candidate_observation_only": True,
            "confidence_tier_legend": CONFIDENCE_TIER_LEGEND,
        }
        formation_summary = build_formation_summary_from_evidence_diag(ev_diag)
        if (ev_diag.get("evidence_segments_failed") or 0) > 0:
            logger.warning(
                "[extract-meeting] evidence segment failure(s): %s",
                formation_summary.get("one_line", ""),
            )
        raw_out: dict[str, Any] = {
            "summary": build_deterministic_summary_from_candidates(api_candidates),
            "insights": [],
            "ideas": [],
            "initiatives": [],
            "projects": [],
            "tasks": [],
            "assets": [],
            "peopleReferences": [],
            "signals": [],
            "meeting_id": meeting_id,
            "candidates": api_candidates,
        }
        if ev_preset_label == "fast_local" and not api_candidates:
            raw_out["noDurableCandidates"] = True
            raw_out["message"] = "No durable candidates found for this chunk."
        if ev_preset_label == "fast_local":
            raw_out["extractionMeta"] = {
                "evidenceSegmentsPlanned": evidence_segments_planned,
                "evidenceSegmentsProcessed": int(ev_diag.get("evidence_internal_segments_processed") or 0),
                "evidenceLlmMsTotal": float(ev_diag.get("evidence_llm_ms_total") or 0.0),
                "evidencePostProcessMs": float(ev_diag.get("evidence_post_process_ms") or 0.0),
                "interactiveStopReason": ev_diag.get("interactive_stop_reason"),
                "interactiveEarlyStop": bool(ev_diag.get("interactive_early_stop_triggered")),
                "literalAnchorOnly": bool(ev_diag.get("literal_anchor_only")),
                "literalAnchorCount": int((ev_diag.get("literal_anchor_meta") or {}).get("count") or 0),
                "literalAnchorRawCount": int((ev_diag.get("literal_anchor_meta") or {}).get("raw_anchor_count") or 0),
                "literalAnchorsCapped": bool((ev_diag.get("literal_anchor_meta") or {}).get("anchors_capped")),
                "skipLLM": llm_skipped,
                "llmSkippedCount": 1 if llm_skipped else 0,
                "evidencePhaseMs": round(evidence_phase_ms, 1),
                "candidateCountPerChunk": len(api_candidates),
                "literalCandidateCount": literal_cand_n,
                "modelCandidateCount": model_cand_n,
                "lowValueLiteralAnchor": bool(lit_meta.get("low_value_literal_anchor")),
                "diagnosticsChunkId": diag_chunk_id,
            }
            logger.info(
                "[extract-meeting] fast_local_timing planned=%s processed=%s llm_ms=%s post_ms=%s stop=%s early_cap=%s "
                "literal_anchor_skip_disabled=%s evidence_phase_ms=%.1f lit/model=%s/%s",
                evidence_segments_planned,
                ev_diag.get("evidence_internal_segments_processed"),
                ev_diag.get("evidence_llm_ms_total"),
                ev_diag.get("evidence_post_process_ms"),
                ev_diag.get("interactive_stop_reason"),
                ev_diag.get("interactive_early_stop_triggered"),
                True,
                evidence_phase_ms,
                literal_cand_n,
                model_cand_n,
            )
        profile_guidance = _resolve_profile_guidance(profile_id, user_id)
        pp_opts = PostProcessExtractionOptions(
            profile_guidance=profile_guidance,
            return_diagnostics=return_diagnostics,
            apply_document_budget=not should_skip_document_budget_for_chunked_request(
                routing_context if isinstance(routing_context, dict) else None
            ),
        )
        out, diagnostics = post_process_extraction(raw_out, notes, context, pp_opts)
        interpret_against_graph(out, ctx_dict, notes)

        pdiag: dict[str, Any]
        run_polish = bool(include_meeting_polish) and ev_preset_label != "fast_local"
        if not run_polish:
            skip_reason = "fast_local" if ev_preset_label == "fast_local" else "disabled_by_default"
            pdiag = {"polish_skipped": True, "polish_skip_reason": skip_reason}
            logger.info("[extract-meeting] meeting_polish=off reason=%s", skip_reason)
        else:
            polish, pdiag = run_optional_meeting_polish(
                lambda **kw: _llm_generate(
                    principal,
                    task=str(kw.get("task") or "meeting_extract_polish"),
                    prompt=str(kw.get("prompt") or ""),
                    timeout=int(kw.get("timeout") or 50),
                ),
                out,
            )
            if isinstance(polish, dict):
                summ = polish.get("summary")
                if isinstance(summ, dict) and (summ.get("text") or "").strip():
                    out["summary"] = {
                        "text": _normalize_str(summ.get("text")),
                        "confidence": _normalize_confidence(summ.get("confidence")) or "medium",
                    }
                ins_raw = polish.get("insights")
                if isinstance(ins_raw, list) and ins_raw:
                    insights_out: list[dict[str, Any]] = []
                    for x in ins_raw:
                        if isinstance(x, dict) and (x.get("statement") or "").strip():
                            insights_out.append(
                                {
                                    "statement": _normalize_str(x.get("statement")),
                                    "sourceQuote": _normalize_str(x.get("sourceQuote")) if x.get("sourceQuote") else None,
                                    "confidence": _normalize_confidence(x.get("confidence")),
                                }
                            )
                    if insights_out:
                        out["insights"] = insights_out

        ideas = out.get("ideas") or []
        initiatives = out.get("initiatives") or []
        tasks = out.get("tasks") or []
        projects = out.get("projects") or []
        assets = out.get("assets") or []
        people = out.get("peopleReferences") or out.get("people") or []
        signals = out.get("signals") or []
        candidates = out.get("candidates") or []

        for x in candidates:
            if isinstance(x, dict):
                x.setdefault("id", "")
                x.setdefault("kind", "candidate")
                x.setdefault("text", "")
                x.setdefault("confidence", None)
                x.setdefault("confidenceLabel", None)
                x.setdefault("sourceStage", None)
                x.setdefault("segmentId", None)
                x.setdefault("sourceExcerpt", None)
                x.setdefault("possibleMatches", None)

        for i in ideas:
            if isinstance(i, dict):
                i.setdefault("title", "")
                i.setdefault("summary", "")
                i.setdefault("description", "")
                i.setdefault("status", "Captured")
                i.setdefault("confidence", None)
                i.setdefault("sourceExcerpt", None)
                i.setdefault("segmentId", None)
                i.setdefault("segmentTitle", None)
                i.setdefault("harvestItemIds", [])
        for i in initiatives:
            if isinstance(i, dict):
                i.setdefault("title", "")
                i.setdefault("brief", "")
                i.setdefault("status", "Draft")
                i.setdefault("ownerName", None)
                i.setdefault("notes", "")
                i.setdefault("confidence", None)
                i.setdefault("sourceExcerpt", None)
                i.setdefault("segmentId", None)
                i.setdefault("segmentTitle", None)
                i.setdefault("existingInitiativeMatchId", None)
                i.setdefault("matchConfidence", None)
                i.setdefault("harvestItemIds", [])
        for t in tasks:
            if isinstance(t, dict):
                t.setdefault("title", "")
                t.setdefault("description", "")
                t.setdefault("status", "Todo")
                t.setdefault("assigneeName", None)
                t.setdefault("notes", "")
                t.setdefault("confidence", None)
                t.setdefault("sourceExcerpt", None)
                t.setdefault("segmentId", None)
                t.setdefault("segmentTitle", None)
                t.setdefault("existingProjectMatchId", None)
                t.setdefault("existingTaskMatchId", None)
                t.setdefault("existingPersonMatchId", None)
                t.setdefault("matchConfidence", None)
                t.setdefault("harvestItemIds", [])
        for _proj in projects:
            if isinstance(_proj, dict):
                _proj.setdefault("segmentId", None)
                _proj.setdefault("segmentTitle", None)
                _proj.setdefault("harvestItemIds", [])
        for _a in assets:
            if isinstance(_a, dict):
                _a.setdefault("segmentId", None)
                _a.setdefault("segmentTitle", None)
                _a.setdefault("harvestItemIds", [])
        for _p in people:
            if isinstance(_p, dict):
                _p.setdefault("segmentId", None)
                _p.setdefault("segmentTitle", None)
                _p.setdefault("harvestItemIds", [])
        for _s in signals:
            if isinstance(_s, dict):
                _s.setdefault("segmentId", None)
                _s.setdefault("segmentTitle", None)
                _s.setdefault("harvestItemIds", [])

        out["ideas"] = ideas
        out["initiatives"] = initiatives
        out["tasks"] = tasks
        out["projects"] = projects
        out["assets"] = assets
        out["peopleReferences"] = people
        out["people"] = people
        out["signals"] = signals
        out["candidates"] = candidates

        if return_diagnostics:
            diag = diagnostics if isinstance(diagnostics, dict) else {}
            diag["parse_repaired"] = False
            diag["evidence"] = ev_diag
            diag["formation_summary"] = formation_summary
            diag["polish"] = pdiag
            out["_diagnostics"] = diag
        out.setdefault("meeting_id", meeting_id)
        out["harvest_ledger"] = ledger.to_json_dict()
        elapsed = time.time() - t_start
        logger.info("[extract-meeting] return (%.2fs)", elapsed)
        try:
            log_activity_simple(
                type=ActivityType.MEETING_PROCESSED.value,
                entity_type=ActivityEntityType.MEETING.value,
                entity_id=meeting_id,
                source="meeting-extraction",
                detail=f"len={input_len} profile={profile_id or 'default'} elapsed={elapsed:.2f}s",
            )
        except Exception:
            logger.debug("Failed to log meeting_processed activity", exc_info=True)
        return out


def extract_meeting_synthesis(
    segment_summaries: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
    profile_id: str | None = None,
    return_diagnostics: bool = False,
    used_rolling_prior: bool = False,
    segment_diagnostics: dict[str, Any] | None = None,
    routing_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    *,
    skip_harvest: bool = False,
    include_meeting_polish: bool = False,
) -> dict[str, Any]:
    """
    Build a full meeting extraction from per-segment summary JSON (long-meeting path).

    Structure is produced deterministically from summary fields (evidence-style rows),
    then clustered and canonized in Python. Optional polish LLM (``include_meeting_polish=True``)
    may refine summary/insights only; it is **off by default**.
    Legacy monolithic synthesis + harvest map calls are not on the critical path.

    When return_diagnostics=True, response includes _diagnostics (raw vs canonical plus evidence meta).
    When used_rolling_prior=True and return_diagnostics=True, _diagnostics includes prior_context_contributed=True.
    When segment_diagnostics is provided (e.g. from extract_segments_with_rolling_prior_context), it is merged into _diagnostics.

    Optional ``routing_context`` enables execution policy / privacy_mode alignment.
    """
    if not segment_summaries:
        return {
            "candidates": [],
            "ideas": [],
            "initiatives": [],
            "tasks": [],
            "projects": [],
            "error": "No segment summaries provided.",
        }

    from local_ai.vision_execution.meeting_extraction_execution import meeting_execution_seam

    with meeting_execution_seam(routing_context, mode="meeting_extract_synthesis", user_id=user_id) as seam_meta:
        if routing_context and seam_meta.get("execution_blocked"):
            return _meeting_seam_blocked_response(seam_meta)

        principal = _meeting_execution_principal(user_id)

        from local_ai.activity import new_id
        from local_ai.vision_execution.extraction_post_process import PostProcessExtractionOptions, post_process_extraction
        from local_ai.vision_execution.graph_interpretation import interpret_against_graph
        from local_ai.vision_execution.harvest_substrate import HarvestLedger
        from local_ai.vision_execution.meeting_evidence_pipeline import (
            CONFIDENCE_TIER_LEGEND,
            attach_possible_matches_to_candidates,
            build_deterministic_summary_from_candidates,
            candidates_to_harvest_ledger,
            dedupe_candidates_ordered,
            extraction_candidate_provenance_summary,
            extraction_candidate_to_api_dict,
            extraction_candidate_from_evidence_row,
            run_optional_meeting_polish,
            summaries_to_evidence_rows,
        )

        meeting_id = new_id()
        rows = summaries_to_evidence_rows(segment_summaries)
        cands = [extraction_candidate_from_evidence_row(r) for r in rows]
        cands = dedupe_candidates_ordered(cands, sim_threshold=0.72)
        ctx_dict = context if isinstance(context, dict) else None
        attach_possible_matches_to_candidates(cands, ctx_dict)
        api_candidates = [extraction_candidate_to_api_dict(c) for c in cands]

        ev_diag: dict[str, Any] = {
            "synthesis_path": "deterministic_summaries_to_candidates",
            "evidence_row_count": len(cands),
            **extraction_candidate_provenance_summary(cands),
            "evidence_rows": [extraction_candidate_to_api_dict(c) for c in cands][:400],
            "evidence_rows_truncated": len(cands) > 400,
            "confidence_tier_legend": CONFIDENCE_TIER_LEGEND,
            "candidate_observation_only": True,
        }
        if len(cands) > 400:
            ev_diag["evidence_rows_omitted_count"] = len(cands) - 400
        ledger = HarvestLedger.empty(meeting_id) if skip_harvest else candidates_to_harvest_ledger(meeting_id, cands)

        if not cands:
            logger.warning("extract_meeting_synthesis: no candidates from %s segment summaries", len(segment_summaries))
            return {
                "candidates": [],
                "ideas": [],
                "initiatives": [],
                "tasks": [],
                "projects": [],
                "assets": [],
                "peopleReferences": [],
                "people": [],
                "signals": [],
                "summary": None,
                "insights": [],
                "error": "synthesis_evidence_empty",
                "message": "Segment summaries yielded no extractable observations.",
                "harvest_ledger": ledger.to_json_dict(),
                "meeting_id": meeting_id,
            }

        ev_diag["reducer"] = {
            "promotions": [],
            "promotion_count": 0,
            "candidate_observation_only": True,
            "confidence_tier_legend": CONFIDENCE_TIER_LEGEND,
        }
        formation_summary = build_formation_summary_from_evidence_diag(ev_diag)
        raw_out: dict[str, Any] = {
            "summary": build_deterministic_summary_from_candidates(api_candidates),
            "insights": [],
            "ideas": [],
            "initiatives": [],
            "projects": [],
            "tasks": [],
            "assets": [],
            "peopleReferences": [],
            "signals": [],
            "meeting_id": meeting_id,
            "candidates": api_candidates,
        }
        profile_guidance = _resolve_profile_guidance(profile_id, user_id)
        budget_chars = 0
        for s in segment_summaries:
            if isinstance(s, dict):
                budget_chars += len(str(s.get("briefSummary") or s.get("brief_summary") or ""))
                budget_chars += len(str(s.get("topic") or ""))
        budget_chars = max(budget_chars, 1)
        pp_opts = PostProcessExtractionOptions(
            profile_guidance=profile_guidance,
            return_diagnostics=return_diagnostics,
            document_budget_char_length=budget_chars,
        )
        out, diagnostics = post_process_extraction(raw_out, "", context, pp_opts)
        interpret_against_graph(out, ctx_dict, "")

        pdiag: dict[str, Any]
        if not include_meeting_polish:
            pdiag = {"polish_skipped": True, "polish_skip_reason": "disabled_by_default"}
            logger.info("[extract-meeting-synthesis] meeting_polish=off reason=disabled_by_default")
        else:
            polish, pdiag = run_optional_meeting_polish(
                lambda **kw: _llm_generate(
                    principal,
                    task=str(kw.get("task") or "meeting_extract_polish"),
                    prompt=str(kw.get("prompt") or ""),
                    timeout=int(kw.get("timeout") or 50),
                ),
                out,
            )
            if isinstance(polish, dict):
                summ = polish.get("summary")
                if isinstance(summ, dict) and (summ.get("text") or "").strip():
                    out["summary"] = {
                        "text": _normalize_str(summ.get("text")),
                        "confidence": _normalize_confidence(summ.get("confidence")) or "medium",
                    }
                ins_raw = polish.get("insights")
                if isinstance(ins_raw, list) and ins_raw:
                    insights_out: list[dict[str, Any]] = []
                    for x in ins_raw:
                        if isinstance(x, dict) and (x.get("statement") or "").strip():
                            insights_out.append(
                                {
                                    "statement": _normalize_str(x.get("statement")),
                                    "sourceQuote": _normalize_str(x.get("sourceQuote")) if x.get("sourceQuote") else None,
                                    "confidence": _normalize_confidence(x.get("confidence")),
                                }
                            )
                    if insights_out:
                        out["insights"] = insights_out

        ideas = out.get("ideas") or []
        initiatives = out.get("initiatives") or []
        projects = out.get("projects") or []
        tasks = out.get("tasks") or []
        assets = out.get("assets") or []
        people = out.get("peopleReferences") or out.get("people") or []
        signals = out.get("signals") or []
        candidates = out.get("candidates") or []

        for x in candidates:
            if isinstance(x, dict):
                x.setdefault("id", "")
                x.setdefault("kind", "candidate")
                x.setdefault("text", "")
                x.setdefault("confidence", None)
                x.setdefault("confidenceLabel", None)
                x.setdefault("sourceStage", None)
                x.setdefault("segmentId", None)
                x.setdefault("sourceExcerpt", None)
                x.setdefault("possibleMatches", None)

        for i in ideas:
            if isinstance(i, dict):
                i.setdefault("title", "")
                i.setdefault("summary", "")
                i.setdefault("description", "")
                i.setdefault("status", "Captured")
                i.setdefault("confidence", None)
                i.setdefault("sourceExcerpt", None)
                i.setdefault("segmentId", None)
                i.setdefault("segmentTitle", None)
                i.setdefault("harvestItemIds", [])
        for i in initiatives:
            if isinstance(i, dict):
                i.setdefault("title", "")
                i.setdefault("brief", "")
                i.setdefault("status", "Draft")
                i.setdefault("ownerName", None)
                i.setdefault("notes", "")
                i.setdefault("confidence", None)
                i.setdefault("sourceExcerpt", None)
                i.setdefault("segmentId", None)
                i.setdefault("segmentTitle", None)
                i.setdefault("existingInitiativeMatchId", None)
                i.setdefault("matchConfidence", None)
                i.setdefault("harvestItemIds", [])
        for p in projects:
            if isinstance(p, dict):
                p.setdefault("title", "")
                p.setdefault("brief", "")
                p.setdefault("status", "Draft")
                p.setdefault("initiativeTitle", None)
                p.setdefault("confidence", None)
                p.setdefault("sourceExcerpt", None)
                p.setdefault("segmentId", None)
                p.setdefault("segmentTitle", None)
                p.setdefault("existingInitiativeMatchId", None)
                p.setdefault("existingProjectMatchId", None)
                p.setdefault("matchConfidence", None)
                p.setdefault("harvestItemIds", [])
        for t in tasks:
            if isinstance(t, dict):
                t.setdefault("title", "")
                t.setdefault("description", "")
                t.setdefault("status", "Todo")
                t.setdefault("assigneeName", None)
                t.setdefault("notes", "")
                t.setdefault("confidence", None)
                t.setdefault("sourceExcerpt", None)
                t.setdefault("segmentId", None)
                t.setdefault("segmentTitle", None)
                t.setdefault("existingProjectMatchId", None)
                t.setdefault("existingTaskMatchId", None)
                t.setdefault("existingPersonMatchId", None)
                t.setdefault("matchConfidence", None)
                t.setdefault("harvestItemIds", [])
        for a in assets:
            if isinstance(a, dict):
                a.setdefault("name", "")
                a.setdefault("kind", "other")
                a.setdefault("description", None)
                a.setdefault("confidence", None)
                a.setdefault("sourceExcerpt", None)
                a.setdefault("segmentId", None)
                a.setdefault("segmentTitle", None)
                a.setdefault("harvestItemIds", [])
        for p in people:
            if isinstance(p, dict):
                p.setdefault("name", "")
                p.setdefault("role", None)
                p.setdefault("context", None)
                p.setdefault("confidence", None)
                p.setdefault("sourceExcerpt", None)
                p.setdefault("segmentId", None)
                p.setdefault("segmentTitle", None)
                p.setdefault("existingPersonMatchId", None)
                p.setdefault("matchConfidence", None)
                p.setdefault("harvestItemIds", [])
        for s in signals:
            if isinstance(s, dict):
                s.setdefault("kind", "attention")
                s.setdefault("label", s.get("kind", "attention"))
                s.setdefault("detail", None)
                s.setdefault("confidence", None)
                s.setdefault("sourceExcerpt", None)
                s.setdefault("segmentId", None)
                s.setdefault("segmentTitle", None)
                s.setdefault("harvestItemIds", [])

        out["ideas"] = ideas
        out["initiatives"] = initiatives
        out["projects"] = projects
        out["tasks"] = tasks
        out["assets"] = assets
        out["peopleReferences"] = people
        out["people"] = people
        out["signals"] = signals
        out["candidates"] = candidates

        if return_diagnostics:
            diag = diagnostics if isinstance(diagnostics, dict) else {}
            diag["parse_repaired"] = False
            diag["evidence"] = ev_diag
            diag["formation_summary"] = formation_summary
            diag["polish"] = pdiag
            if used_rolling_prior:
                diag["prior_context_contributed"] = True
            if segment_diagnostics:
                diag["segment_fallbacks"] = segment_diagnostics.get("fallback_segment_indices", [])
                diag["segment_parse_failures"] = segment_diagnostics.get("parse_failure_segment_indices", [])
                if segment_diagnostics.get("pronoun_resolution_occurred"):
                    diag["pronoun_resolution_occurred"] = True
                    diag["pronoun_resolutions_by_segment"] = segment_diagnostics.get("pronoun_resolutions_by_segment", [])
                if segment_diagnostics.get("prior_entities_used"):
                    diag["prior_entities_used"] = True
            out["_diagnostics"] = diag

        out["harvest_ledger"] = ledger.to_json_dict()
        out["meeting_id"] = meeting_id
        return out
