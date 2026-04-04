"""
External meeting extraction: one structured LLM call producing typed ``ideas`` / ``initiatives`` /
``projects`` / ``tasks`` arrays aligned with the Vision Execution staging model (not a flat candidate pool).

Legacy fallback: if the model returns only a flat ``candidates`` array (old schema), it is still parsed.

Uses the same resolver/adapter stack as segment extraction (``get_llm_adapter_for_principal``) after
optional per-call engine overrides. Washing uses ``prepare_council_contexts`` when requested; unwashed
cloud outbound is blocked when execution policy disallows cloud.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

EXTERNAL_MEETING_TASK = "meeting_extract_external_typed"
EXTERNAL_LLM_TIMEOUT_S = 120
SEGMENT_ID_EXTERNAL = "external"


def _repair_json(raw: str) -> str:
    """Trim fences / outer object (aligned with meeting_extract)."""
    import re

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
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


def parse_external_ai_engine(raw: str | None) -> tuple[str, str] | None:
    """``provider:model`` or bare ``model`` (ollama). Returns lowercase provider."""
    s = (raw or "").strip()
    if not s:
        return None
    if ":" in s:
        p, m = s.split(":", 1)
        p, m = p.strip().lower(), m.strip()
        if p and m:
            return p, m
    return ("ollama", s)


def _build_external_extraction_prompt(
    meeting_text: str,
    *,
    workspace_mirror_block: str,
) -> str:
    mirror = (workspace_mirror_block or "").strip()
    mirror_section = f"\nOptional workspace orientation (known initiatives/projects/tasks only — do not invent facts from this):\n{mirror}\n" if mirror else ""
    return f"""You populate a constrained Vision Execution planning model from meeting notes or a transcript.

You are NOT doing open-ended semantic extraction. You are filling typed planning objects only where each row truly deserves objecthood in the system.

There are NO separate buckets for casual notes, observations, or signals in this output. If something is only context, tension, or a sub-detail, fold it into a parent row's description, brief, notes, or sourceExcerpt — do NOT emit a sibling row.

OUTPUT: Return ONE JSON object only. No markdown, no code fence, no commentary. Start with {{ and end with }}.

Required top-level shape (four arrays; use [] if none):
{{
  "ideas": [],
  "initiatives": [],
  "projects": [],
  "tasks": []
}}

Do NOT return a flat "candidates" array. Use the four typed arrays only.

--- Type meanings (choose the highest appropriate level; one row per distinct object) ---

**ideas** — Meaningful direction or possible line of work not yet concrete enough to be an initiative, project, or task.
Do not use for: items that are clearly an initiative/project/task; pure notes or concerns.

**initiatives** — Substantial stream of work or strategic thrust; likely spans multiple projects/tasks; broader than one build.

**projects** — Bounded deliverable or build effort; can plausibly contain multiple tasks; more than a single next action.

**tasks** — Directly executable next action a person could do; not a topic or vague concern.

--- Elevation rules (critical) ---

1. Only emit a row if it deserves objecthood in this planning system.
2. Prefer fewer, fuller rows over many thin rows.
3. If several details belong under one initiative, project, or task, emit ONE parent row and put detail in "description", "brief", and/or "notes".
4. Do NOT create sibling rows for subpoints, evidence fragments, or "also mentioned" items.
5. sourceExcerpt grounds the row; it is NOT a reason to add another row.
6. When in doubt, merge into a parent row instead of elevating.

--- Field contracts (camelCase preferred; snake_case accepted) ---

**ideas** objects:
- Required: "title" (short, specific; max ~100 chars).
- Optional: "description", "summary", "status", "confidence" (0–1 number), "sourceExcerpt" or "evidence_quote", "segmentId", "segmentTitle", "anchorRole", "proposedType" (usually omit or "idea").

**initiatives** objects:
- Required: "title".
- Optional: "description", "brief", "status", "ownerName", "notes", "confidence", "sourceExcerpt"/"evidence_quote", "existingInitiativeMatchId", "matchConfidence", "segmentId", "segmentTitle", "anchorRole".

**projects** objects:
- Required: "title".
- Optional: "initiativeTitle", "initiativeId", "brief", "status", "confidence", "sourceExcerpt"/"evidence_quote", "existingInitiativeMatchId", "existingProjectMatchId", "matchConfidence", "segmentId", "segmentTitle", "anchorRole".

**tasks** objects:
- Required: "title".
- Optional: "projectTitle", "projectId", "initiativeTitle", "initiativeId", "description", "status", "suggestedOwner", "assigneeName", "notes", "confidence", "sourceExcerpt"/"evidence_quote", "existingProjectMatchId", "existingTaskMatchId", "existingPersonMatchId", "matchConfidence", "segmentId", "segmentTitle", "anchorRole".

--- Linkage fields (existing system IDs) ---

When the optional workspace/context block lists real entities with ids, you MAY set existingInitiativeMatchId, existingProjectMatchId, existingTaskMatchId, or existingPersonMatchId only when the meeting text clearly refers to that same entity (or the context id is an obvious match). Use exact string ids from context. If unsure, omit (null). Never invent ids.

initiativeId / projectId: only when the meeting or context explicitly ties the row to that parent id.

--- Volume ---

Across ALL four arrays combined, target roughly 6–14 substantial rows for a typical meeting; fewer is better. Hard cap mindset: do not exceed ~18 total rows except for very long transcripts. Quality over recall.

--- Mechanical rules ---

- No transcript filler as titles (no "uh", long quotes, or bare speaker labels).
- sourceExcerpt / evidence_quote should be a substring of the meeting text when possible (short paraphrase only if needed).
- confidence: JSON number 0–1; be conservative.

{mirror_section}
Meeting text:
---
{meeting_text}
---

Respond with only the JSON object."""


def _pick_str(d: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _pick_opt_float(d: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _pick_opt_str_id(d: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if len(s) >= 8 and len(s) <= 80:
            return s
    return None


def _dedupe_dict_rows_by_title(rows: list[dict[str, Any]], *, title_key: str = "title") -> list[dict[str, Any]]:
    from local_ai.vision_execution.extraction_canonization import _title_similarity

    out: list[dict[str, Any]] = []
    for r in rows:
        t = str(r.get(title_key) or "").strip()
        if len(t) < 3:
            continue
        if any(_title_similarity(t, str(o.get(title_key) or "").strip()) >= 0.72 for o in out):
            continue
        out.append(r)
    return out


def _confidence_api_fields(raw: float | None) -> tuple[float | None, str | None]:
    from local_ai.vision_execution.meeting_evidence_pipeline import (
        SOURCE_STAGE_MODEL,
        effective_confidence,
        normalize_confidence_label,
        public_source_stage_for_internal,
    )

    cr = 0.55 if raw is None else max(0.0, min(1.0, float(raw)))
    pub = public_source_stage_for_internal(SOURCE_STAGE_MODEL)
    eff = effective_confidence(cr, pub)
    return eff, normalize_confidence_label(eff)


def _row_to_idea_api(d: dict[str, Any], *, segment_id: str) -> dict[str, Any] | None:
    title = _pick_str(d, "title", "text")
    if len(title) < 3:
        return None
    excerpt = _pick_str(d, "sourceExcerpt", "source_excerpt", "evidence_quote", "evidenceQuote") or title[:800]
    desc = _pick_str(d, "description") or None
    summ = _pick_str(d, "summary") or None
    body = desc or summ or title
    eff, label = _confidence_api_fields(_pick_opt_float(d, "confidence"))
    row: dict[str, Any] = {
        "title": title[:2000],
        "description": body[:4000] if body else title[:2000],
        "summary": (summ or body)[:2000] if (summ or body) else title[:2000],
        "status": _pick_str(d, "status") or "Captured",
        "confidence": eff,
        "confidenceLabel": label,
        "sourceExcerpt": excerpt[:2000],
        "segmentId": _pick_str(d, "segmentId", "segment_id") or segment_id,
        "segmentTitle": _pick_str(d, "segmentTitle", "segment_title") or None,
        "sourceStage": "model",
        "anchorRole": _pick_str(d, "anchorRole", "anchor_role") or None,
    }
    if row["segmentTitle"] is None:
        del row["segmentTitle"]
    if row["anchorRole"] is None:
        del row["anchorRole"]
    return row


def _row_to_initiative_api(d: dict[str, Any], *, segment_id: str) -> dict[str, Any] | None:
    title = _pick_str(d, "title", "text")
    if len(title) < 3:
        return None
    excerpt = _pick_str(d, "sourceExcerpt", "source_excerpt", "evidence_quote", "evidenceQuote") or title[:800]
    brief = _pick_str(d, "brief", "summary", "description") or title
    desc = _pick_str(d, "description") or brief
    eff, label = _confidence_api_fields(_pick_opt_float(d, "confidence"))
    row: dict[str, Any] = {
        "title": title[:2000],
        "brief": brief[:4000],
        "description": desc[:4000],
        "status": _pick_str(d, "status") or "Captured",
        "ownerName": _pick_str(d, "ownerName", "owner_name") or None,
        "notes": _pick_str(d, "notes") or None,
        "confidence": eff,
        "confidenceLabel": label,
        "sourceExcerpt": excerpt[:2000],
        "segmentId": _pick_str(d, "segmentId", "segment_id") or segment_id,
        "segmentTitle": _pick_str(d, "segmentTitle", "segment_title") or None,
        "existingInitiativeMatchId": _pick_opt_str_id(d, "existingInitiativeMatchId", "existing_initiative_match_id"),
        "matchConfidence": _pick_opt_float(d, "matchConfidence", "match_confidence"),
        "anchorRole": _pick_str(d, "anchorRole", "anchor_role") or None,
    }
    for opt in ("ownerName", "notes", "segmentTitle", "existingInitiativeMatchId", "matchConfidence", "anchorRole"):
        if row.get(opt) is None:
            row.pop(opt, None)
    return row


def _row_to_project_api(d: dict[str, Any], *, segment_id: str) -> dict[str, Any] | None:
    title = _pick_str(d, "title", "text")
    if len(title) < 3:
        return None
    excerpt = _pick_str(d, "sourceExcerpt", "source_excerpt", "evidence_quote", "evidenceQuote") or title[:800]
    brief = _pick_str(d, "brief", "description", "summary") or None
    eff, label = _confidence_api_fields(_pick_opt_float(d, "confidence"))
    row: dict[str, Any] = {
        "title": title[:2000],
        "initiativeTitle": _pick_str(d, "initiativeTitle", "initiative_title") or None,
        "initiativeId": _pick_opt_str_id(d, "initiativeId", "initiative_id"),
        "brief": (brief or title)[:4000],
        "status": _pick_str(d, "status") or "Captured",
        "confidence": eff,
        "confidenceLabel": label,
        "sourceExcerpt": excerpt[:2000],
        "segmentId": _pick_str(d, "segmentId", "segment_id") or segment_id,
        "segmentTitle": _pick_str(d, "segmentTitle", "segment_title") or None,
        "existingInitiativeMatchId": _pick_opt_str_id(d, "existingInitiativeMatchId", "existing_initiative_match_id"),
        "existingProjectMatchId": _pick_opt_str_id(d, "existingProjectMatchId", "existing_project_match_id"),
        "matchConfidence": _pick_opt_float(d, "matchConfidence", "match_confidence"),
        "anchorRole": _pick_str(d, "anchorRole", "anchor_role") or None,
    }
    for opt in (
        "initiativeTitle",
        "initiativeId",
        "segmentTitle",
        "existingInitiativeMatchId",
        "existingProjectMatchId",
        "matchConfidence",
        "anchorRole",
    ):
        if row.get(opt) is None:
            row.pop(opt, None)
    return row


def _row_to_task_api(d: dict[str, Any], *, segment_id: str) -> dict[str, Any] | None:
    title = _pick_str(d, "title", "text")
    if len(title) < 3:
        return None
    excerpt = _pick_str(d, "sourceExcerpt", "source_excerpt", "evidence_quote", "evidenceQuote") or title[:800]
    eff, label = _confidence_api_fields(_pick_opt_float(d, "confidence"))
    row: dict[str, Any] = {
        "title": title[:2000],
        "projectTitle": _pick_str(d, "projectTitle", "project_title") or None,
        "projectId": _pick_opt_str_id(d, "projectId", "project_id"),
        "initiativeTitle": _pick_str(d, "initiativeTitle", "initiative_title") or None,
        "initiativeId": _pick_opt_str_id(d, "initiativeId", "initiative_id"),
        "description": _pick_str(d, "description", "summary", "notes") or None,
        "status": _pick_str(d, "status") or "Captured",
        "suggestedOwner": _pick_str(d, "suggestedOwner", "suggested_owner", "assigneeName", "assignee_name") or None,
        "assigneeName": _pick_str(d, "assigneeName", "assignee_name") or None,
        "notes": _pick_str(d, "notes") or None,
        "confidence": eff,
        "confidenceLabel": label,
        "sourceExcerpt": excerpt[:2000],
        "segmentId": _pick_str(d, "segmentId", "segment_id") or segment_id,
        "segmentTitle": _pick_str(d, "segmentTitle", "segment_title") or None,
        "existingProjectMatchId": _pick_opt_str_id(d, "existingProjectMatchId", "existing_project_match_id"),
        "existingTaskMatchId": _pick_opt_str_id(d, "existingTaskMatchId", "existing_task_match_id"),
        "existingPersonMatchId": _pick_opt_str_id(d, "existingPersonMatchId", "existing_person_match_id"),
        "matchConfidence": _pick_opt_float(d, "matchConfidence", "match_confidence"),
        "anchorRole": _pick_str(d, "anchorRole", "anchor_role") or None,
    }
    for opt in (
        "projectTitle",
        "projectId",
        "initiativeTitle",
        "initiativeId",
        "description",
        "suggestedOwner",
        "assigneeName",
        "notes",
        "segmentTitle",
        "existingProjectMatchId",
        "existingTaskMatchId",
        "existingPersonMatchId",
        "matchConfidence",
        "anchorRole",
    ):
        if row.get(opt) is None:
            row.pop(opt, None)
    return row


def _summary_from_typed_buckets(
    ideas: list[dict[str, Any]],
    initiatives: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    parts: list[str] = []
    for arr in (ideas, initiatives, projects, tasks):
        for x in arr[:8]:
            t = str(x.get("title") or "").strip()
            if t:
                parts.append(t)
    if not parts:
        return None
    return {"text": ("Meeting extract: " + "; ".join(parts[:18]))[:2000], "confidence": "medium"}


def _harvest_candidates_from_typed_rows(
    ideas: list[dict[str, Any]],
    initiatives: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    *,
    segment_id: str,
) -> list[Any]:
    from local_ai.vision_execution.meeting_evidence_pipeline import (
        SOURCE_STAGE_MODEL,
        ExtractionCandidate,
    )

    out: list[Any] = []
    for rows, ptype in (
        (ideas, None),
        (initiatives, "initiative"),
        (projects, "project"),
        (tasks, "task"),
    ):
        for d in rows:
            title = str(d.get("title") or "").strip()
            if len(title) < 3:
                continue
            eq = str(d.get("sourceExcerpt") or d.get("source_excerpt") or title).strip()[:2000]
            cr = d.get("confidence")
            try:
                crf = float(cr) if cr is not None else 0.55
            except (TypeError, ValueError):
                crf = 0.55
            crf = max(0.0, min(1.0, crf))
            summ = str(d.get("brief") or d.get("description") or d.get("summary") or "").strip()[:2000] or None
            out.append(
                ExtractionCandidate(
                    id=uuid.uuid4().hex[:12],
                    segment_id=segment_id,
                    text=title[:2000],
                    evidence_quote=eq,
                    confidence_raw=crf,
                    internal_source_stage=SOURCE_STAGE_MODEL,
                    possible_matches=None,
                    summary_text=summ,
                    anchor_role=str(d.get("anchorRole") or d.get("anchor_role") or "").strip() or None,
                    proposed_type=ptype,
                )
            )
    return out


def _parse_typed_external_extraction(
    parsed_obj: dict[str, Any] | None,
    *,
    segment_id: str,
    diag: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[Any],
    bool,
]:
    """Parse ideas/initiatives/projects/tasks from model JSON. Returns (ideas, ini, proj, tasks, harvest_cands, used_typed_path)."""
    if not isinstance(parsed_obj, dict):
        return [], [], [], [], [], False

    raw_ideas = [x for x in (parsed_obj.get("ideas") or []) if isinstance(x, dict)]
    raw_ini = [x for x in (parsed_obj.get("initiatives") or []) if isinstance(x, dict)]
    raw_proj = [x for x in (parsed_obj.get("projects") or []) if isinstance(x, dict)]
    raw_tasks = [x for x in (parsed_obj.get("tasks") or []) if isinstance(x, dict)]
    typed_nonempty = bool(raw_ideas or raw_ini or raw_proj or raw_tasks)
    if not typed_nonempty:
        return [], [], [], [], [], False

    ideas = _dedupe_dict_rows_by_title([r for r in (_row_to_idea_api(x, segment_id=segment_id) for x in raw_ideas) if r])
    initiatives = _dedupe_dict_rows_by_title([r for r in (_row_to_initiative_api(x, segment_id=segment_id) for x in raw_ini) if r])
    projects = _dedupe_dict_rows_by_title([r for r in (_row_to_project_api(x, segment_id=segment_id) for x in raw_proj) if r])
    tasks = _dedupe_dict_rows_by_title([r for r in (_row_to_task_api(x, segment_id=segment_id) for x in raw_tasks) if r])

    diag["typed_ideas_raw"] = len(raw_ideas)
    diag["typed_initiatives_raw"] = len(raw_ini)
    diag["typed_projects_raw"] = len(raw_proj)
    diag["typed_tasks_raw"] = len(raw_tasks)
    diag["typed_ideas_after_dedupe"] = len(ideas)
    diag["typed_initiatives_after_dedupe"] = len(initiatives)
    diag["typed_projects_after_dedupe"] = len(projects)
    diag["typed_tasks_after_dedupe"] = len(tasks)
    diag["external_typed_buckets"] = True

    harvest = _harvest_candidates_from_typed_rows(ideas, initiatives, projects, tasks, segment_id=segment_id)
    return ideas, initiatives, projects, tasks, harvest, True


_EXECUTION_EXTERNAL_CLOUD_IDS = frozenset({"openai", "anthropic", "google", "xai"})


class _ExplicitCloudProviderShim:
    """Same ``generate(prompt, *, timeout=)`` contract as ``OpenAIProvider`` for policy override."""

    __slots__ = ("model", "_provider_id", "_api_key")

    def __init__(self, provider_id: str, api_key: str, model: str):
        self._provider_id = provider_id
        self._api_key = api_key
        self.model = (model or "").strip()

    def generate(self, prompt: str, *, timeout: int | None = None) -> str:
        to = int(timeout if timeout is not None else 120)
        pid = self._provider_id
        if pid == "openai":
            from local_ai.providers import openai as p

            return p.generate(self._api_key, prompt, model=self.model or None, timeout=to)
        if pid == "anthropic":
            from local_ai.providers import anthropic as p

            return p.generate(self._api_key, prompt, model=self.model or None, timeout=to)
        if pid == "google":
            from local_ai.providers import google_genai as p

            return p.generate(self._api_key, prompt, model=self.model or None, timeout=to)
        if pid == "xai":
            from local_ai.providers import xai as p

            return p.generate(self._api_key, prompt, model=self.model or None, timeout=to)
        raise RuntimeError(f"Unknown cloud provider {pid!r}")


@contextmanager
def _temporary_llm_engine_override(principal: Any, engine: tuple[str, str] | None) -> Iterator[None]:
    """Stack provider/model for one generate call; restore prior contextvar state."""
    from local_ai.execution_policy.run_context import (
        push_ollama_model_override,
        push_policy_provider_override,
        reset_ollama_model_override,
        reset_policy_provider_override,
    )

    if not engine:
        yield
        return
    prov, model = engine
    if prov == "ollama":
        pass
    elif prov in _EXECUTION_EXTERNAL_CLOUD_IDS:
        pass
    else:
        raise ValueError(
            f"Unsupported external AI provider {prov!r}; use ollama, openai, anthropic, google, or xai."
        )

    tokens: list[tuple[str, Any]] = []
    pol_clear = push_policy_provider_override(None)
    tokens.append(("pol_clear", pol_clear))
    try:
        if prov == "ollama":
            om_tok = push_ollama_model_override(model)
            tokens.append(("ollama", om_tok))
        elif prov == "openai":
            from local_ai.execution_policy.openai_credentials import resolve_openai_api_key_for_principal
            from local_ai.providers.openai import OpenAIProvider

            key, _src = resolve_openai_api_key_for_principal(principal)
            if not key:
                raise RuntimeError("OpenAI API key is not configured for this account.")
            op = OpenAIProvider(model=model, api_key=key)
            pp_tok = push_policy_provider_override(op)
            tokens.append(("policy", pp_tok))
        else:
            from local_ai.llm.credentials import resolve_cloud_api_key

            key, _src = resolve_cloud_api_key(principal, prov)
            if not key:
                raise RuntimeError(f"No API key for {prov} is configured for this account.")
            shim = _ExplicitCloudProviderShim(prov, key, model)
            pp_tok = push_policy_provider_override(shim)
            tokens.append(("policy", pp_tok))
        yield
    finally:
        for kind, tok in reversed(tokens):
            if kind == "ollama":
                reset_ollama_model_override(tok)
            else:
                reset_policy_provider_override(tok)


def _llm_generate(principal: Any, *, task: str, prompt: str, timeout: int) -> str:
    from local_ai.llm.adapter import LLMRequest
    from local_ai.llm.resolver import get_llm_adapter_for_principal

    adapter = get_llm_adapter_for_principal(principal)
    return adapter.generate_text(LLMRequest(task=task, prompt=prompt, timeout=timeout))


def _policy_allows_unwashed_cloud(
    routing_context: dict[str, Any] | None,
    *,
    requested_provider: str,
) -> tuple[bool, str | None]:
    """False + reason when sending raw (unwashed) text to the requested provider is disallowed."""
    from local_ai.execution_policy.privacy_apply import (
        ExecutionPolicyBlocked,
        merge_privacy_policy_input,
        privacy_mode_to_partial,
        provider_execution_tier,
    )
    from local_ai.execution_policy.resolve import resolve_execution_policy_for_action
    from local_ai.execution_policy.types import ActionRoutingContext

    rc = routing_context if isinstance(routing_context, dict) else {}
    ctx = ActionRoutingContext(
        surface=str(rc.get("surface") or "meeting_extraction").strip() or "meeting_extraction",
        action_kind=str(rc.get("action_kind") or "suggestion_batch").strip() or "suggestion_batch",
        action_intent=(str(rc.get("action_intent") or "meeting_extract_single").strip() or None),
        streaming=rc.get("streaming"),
        sensitivity=(str(rc.get("sensitivity") or "").strip() or None) if rc.get("sensitivity") else None,
    )
    pm_raw = rc.get("privacy_mode")
    pm_part = privacy_mode_to_partial(str(pm_raw).strip() if pm_raw is not None else None)
    merged_privacy = merge_privacy_policy_input(False, pm_part)
    if merged_privacy.require_local and provider_execution_tier(requested_provider) == "cloud":
        return False, "Privacy mode requires local execution; unwashed meeting text cannot be sent to a cloud engine."

    outcome = resolve_execution_policy_for_action(ctx, legacy_route="default", privacy=pm_part)
    if isinstance(outcome, ExecutionPolicyBlocked):
        return False, outcome.detail or "Execution blocked by policy"
    if provider_execution_tier(requested_provider) == "cloud" and not outcome.allow_cloud:
        return False, "Policy does not allow cloud outbound; unwashed meeting text cannot be sent to a cloud model."
    return True, None


def extract_meeting_with_external_ai(
    notes_precleaned: str,
    *,
    context: dict[str, Any] | None = None,
    profile_id: str | None = None,
    return_diagnostics: bool = False,
    routing_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    external_ai_engine: str | None = None,
    wash_data_for_call: bool = True,
    skip_harvest: bool = False,
    workspace_packet: dict[str, Any] | None = None,
    evidence_extraction_preset: str = "default",
) -> dict[str, Any]:
    """
    Single-call external extraction. ``notes_precleaned`` must already pass ``preclean_transcript``.
    """
    import time as time_mod

    from local_ai.activity import ActivityEntityType, ActivityType, log_activity_simple, new_id
    from local_ai.council_wash import prepare_council_contexts
    from local_ai.execution_policy.privacy_apply import provider_execution_tier
    from local_ai.llm.execution_principal import anonymous_account_principal, principal_for_vision_execution_user
    from local_ai.llm.resolver import describe_llm_adapter_routing, get_llm_adapter_for_principal
    from local_ai.vision_execution.extraction_formation_summary import build_formation_summary_from_evidence_diag
    from local_ai.vision_execution.extraction_post_process import (
        PostProcessExtractionOptions,
        post_process_extraction,
        should_skip_document_budget_for_chunked_request,
    )
    from local_ai.vision_execution.graph_interpretation import interpret_against_graph
    from local_ai.vision_execution.harvest_substrate import HarvestLedger
    from local_ai.vision_execution.meeting_evidence_pipeline import (
        CONFIDENCE_TIER_LEGEND,
        attach_possible_matches_to_candidates,
        build_deterministic_summary_from_candidates,
        candidates_to_harvest_ledger,
        dedupe_candidates_ordered,
        extraction_candidate_from_llm_row,
        extraction_candidate_to_api_dict,
    )
    from local_ai.vision_execution.meeting_extract import (
        _resolve_profile_guidance,
        _workspace_mirror_prompt_block,
    )

    t_start = time_mod.time()
    meeting_id = new_id()
    principal = principal_for_vision_execution_user(user_id) if (user_id or "").strip() else anonymous_account_principal()

    diag: dict[str, Any] = {
        "extraction_engine_type": "external",
        "selected_external_ai_engine": (external_ai_engine or "").strip() or None,
        "wash_data_for_call": bool(wash_data_for_call),
        "evidence_extraction_preset_note": evidence_extraction_preset,
        "policy_blocked_unwashed_outbound": False,
        "wash_trace": None,
        "cloud_payload_source": None,
        "parse_outcome": None,
        "candidates_raw_count": 0,
        "candidates_after_dedupe": 0,
        "prompt_char_len": 0,
        "adapter_routing": None,
        "resolved_provider_used": None,
        "resolved_model_used": None,
    }

    parsed_engine = parse_external_ai_engine(external_ai_engine)
    if not parsed_engine:
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
            "meeting_id": meeting_id,
            "error": "external_engine_required",
            "message": "Select an AI engine (provider:model) for external extraction, or turn off external AI extraction.",
            "harvest_ledger": HarvestLedger.empty(meeting_id).to_json_dict(),
            **({"_diagnostics": {**diag, "parse_outcome": "no_engine"}} if return_diagnostics else {}),
        }

    prov, _model_part = parsed_engine
    native_text = notes_precleaned
    prompt_body = native_text

    if wash_data_for_call:
        _, cloud_body, wash_trace = prepare_council_contexts(native_text)
        diag["wash_trace"] = wash_trace
        diag["cloud_payload_source"] = wash_trace.get("cloud_payload_source")
        if cloud_body is None or not str(cloud_body).strip():
            diag["parse_outcome"] = "wash_blocked_unsafe_or_empty"
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
                "meeting_id": meeting_id,
                "error": "wash_failed",
                "message": "Data washing did not produce a safe cloud payload. Cannot send this content to the model with washing enabled.",
                "harvest_ledger": HarvestLedger.empty(meeting_id).to_json_dict(),
                **({"_diagnostics": diag} if return_diagnostics else {}),
            }
        prompt_body = cloud_body
    else:
        if provider_execution_tier(prov) == "cloud":
            ok, reason = _policy_allows_unwashed_cloud(routing_context, requested_provider=prov)
            if not ok:
                diag["policy_blocked_unwashed_outbound"] = True
                diag["parse_outcome"] = "unwashed_cloud_blocked"
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
                    "meeting_id": meeting_id,
                    "error": "execution_blocked",
                    "message": reason or "Unwashed outbound to cloud is not permitted for this privacy/policy profile.",
                    "execution_blocked": True,
                    "harvest_ledger": HarvestLedger.empty(meeting_id).to_json_dict(),
                    **({"_diagnostics": diag} if return_diagnostics else {}),
                }

    wm = _workspace_mirror_prompt_block(workspace_packet if isinstance(workspace_packet, dict) else None)
    prompt = _build_external_extraction_prompt(prompt_body, workspace_mirror_block=wm)
    diag["prompt_char_len"] = len(prompt)

    raw = ""
    parse_ok = False
    parsed_obj: dict[str, Any] | None = None
    try:
        with _temporary_llm_engine_override(principal, parsed_engine):
            adapter = get_llm_adapter_for_principal(principal)
            routing_snap = describe_llm_adapter_routing(adapter)
            diag["adapter_routing"] = routing_snap
            diag["resolved_provider_used"] = routing_snap.get("effective_provider")
            diag["resolved_model_used"] = routing_snap.get("effective_model")
            raw = _llm_generate(
                principal,
                task=EXTERNAL_MEETING_TASK,
                prompt=prompt,
                timeout=EXTERNAL_LLM_TIMEOUT_S,
            )
    except Exception as e:
        logger.exception("[extract-meeting-external] LLM failure")
        diag["parse_outcome"] = f"llm_error:{type(e).__name__}"
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
            "meeting_id": meeting_id,
            "error": "external_llm_failed",
            "message": str(e)[:500] if str(e) else "External extraction failed.",
            "harvest_ledger": HarvestLedger.empty(meeting_id).to_json_dict(),
            **({"_diagnostics": diag} if return_diagnostics else {}),
        }

    repaired = _repair_json(raw)
    try:
        parsed_obj = json.loads(repaired)
        parse_ok = True
        diag["parse_repaired"] = repaired != raw.strip()
    except json.JSONDecodeError:
        try:
            parsed_obj = json.loads(raw)
            parse_ok = True
            diag["parse_repaired"] = False
        except json.JSONDecodeError:
            parsed_obj = None
            diag["parse_outcome"] = "json_parse_failed"
            diag["raw_response_sample"] = (raw[:800] + ("..." if len(raw) > 800 else "")).replace("\r", "")

    typed_ideas: list[dict[str, Any]] = []
    typed_initiatives: list[dict[str, Any]] = []
    typed_projects: list[dict[str, Any]] = []
    typed_tasks: list[dict[str, Any]] = []
    cands: list[Any] = []
    used_typed_path = False
    if isinstance(parsed_obj, dict):
        typed_ideas, typed_initiatives, typed_projects, typed_tasks, harvest_from_typed, used_typed_path = (
            _parse_typed_external_extraction(parsed_obj, segment_id=SEGMENT_ID_EXTERNAL, diag=diag)
        )
        if used_typed_path:
            cands = harvest_from_typed
            diag["candidates_raw_count"] = len(cands)
            diag["candidates_after_dedupe"] = len(cands)
            diag["parse_outcome"] = (
                "ok"
                if parse_ok and (typed_ideas or typed_initiatives or typed_projects or typed_tasks)
                else (diag.get("parse_outcome") or "empty_typed_buckets")
            )
        else:
            rows_raw: list[Any] = []
            cr = parsed_obj.get("candidates")
            if isinstance(cr, list):
                rows_raw = cr
            diag["candidates_raw_count"] = len(rows_raw)
            for r in rows_raw:
                if isinstance(r, dict):
                    c = extraction_candidate_from_llm_row(r, segment_id=SEGMENT_ID_EXTERNAL)
                    if c:
                        cands.append(c)
            cands = dedupe_candidates_ordered(cands)
            diag["candidates_after_dedupe"] = len(cands)
            diag["parse_outcome"] = "ok" if parse_ok and rows_raw else (diag.get("parse_outcome") or "empty_candidates")

    ctx_dict = context if isinstance(context, dict) else None
    attach_possible_matches_to_candidates(cands, ctx_dict)
    api_candidates = [extraction_candidate_to_api_dict(c) for c in cands]

    ledger = HarvestLedger.empty(meeting_id) if skip_harvest else candidates_to_harvest_ledger(meeting_id, cands)

    ev_diag_stub: dict[str, Any] = {
        "external_ai_path": True,
        "reducer": {
            "promotions": [],
            "promotion_count": 0,
            "candidate_observation_only": not used_typed_path,
            "confidence_tier_legend": CONFIDENCE_TIER_LEGEND,
        },
    }
    formation_summary = build_formation_summary_from_evidence_diag(ev_diag_stub)

    if used_typed_path:
        summary_obj = _summary_from_typed_buckets(typed_ideas, typed_initiatives, typed_projects, typed_tasks)
    else:
        summary_obj = build_deterministic_summary_from_candidates(api_candidates)

    raw_out: dict[str, Any] = {
        "summary": summary_obj,
        "insights": [],
        "ideas": typed_ideas if used_typed_path else [],
        "initiatives": typed_initiatives if used_typed_path else [],
        "projects": typed_projects if used_typed_path else [],
        "tasks": typed_tasks if used_typed_path else [],
        "assets": [],
        "peopleReferences": [],
        "signals": [],
        "meeting_id": meeting_id,
        "candidates": [] if used_typed_path else api_candidates,
        "extractionMeta": {
            "extractionEngineType": "external",
            "selectedExternalAiEngine": diag["selected_external_ai_engine"],
            "washDataForCall": wash_data_for_call,
            "resolvedProviderUsed": diag.get("resolved_provider_used"),
            "resolvedModelUsed": diag.get("resolved_model_used"),
            "promptCharLen": diag.get("prompt_char_len"),
            "parseOutcome": diag.get("parse_outcome"),
            "candidatesRawCount": diag.get("candidates_raw_count"),
            "candidatesAfterDedupe": diag.get("candidates_after_dedupe"),
            "policyBlockedUnwashedOutbound": diag.get("policy_blocked_unwashed_outbound"),
            "diagnosticsChunkId": (routing_context or {}).get("diagnosticsChunkId") if isinstance(routing_context, dict) else None,
            "externalTypedBuckets": used_typed_path,
            "typedIdeasCount": len(typed_ideas) if used_typed_path else None,
            "typedInitiativesCount": len(typed_initiatives) if used_typed_path else None,
            "typedProjectsCount": len(typed_projects) if used_typed_path else None,
            "typedTasksCount": len(typed_tasks) if used_typed_path else None,
        },
    }

    profile_guidance = _resolve_profile_guidance(profile_id, user_id)
    pp_opts = PostProcessExtractionOptions(
        profile_guidance=profile_guidance,
        return_diagnostics=return_diagnostics,
        apply_document_budget=not should_skip_document_budget_for_chunked_request(
            routing_context if isinstance(routing_context, dict) else None
        ),
    )
    out, diag_bundle = post_process_extraction(raw_out, notes_precleaned, context, pp_opts)
    interpret_against_graph(out, ctx_dict, notes_precleaned)
    canon_diag = diag_bundle if return_diagnostics else {}

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
            x.setdefault("proposedType", None)

    out["ideas"] = ideas
    out["initiatives"] = initiatives
    out["tasks"] = tasks
    out["projects"] = projects
    out["assets"] = assets
    out["peopleReferences"] = people
    out["people"] = people
    out["signals"] = signals
    out["candidates"] = candidates
    out.setdefault("meeting_id", meeting_id)
    out["harvest_ledger"] = ledger.to_json_dict()

    if return_diagnostics:
        diag["formation_summary"] = formation_summary
        diag["evidence"] = ev_diag_stub
        if isinstance(canon_diag, dict):
            diag.update(canon_diag)
        diag["polish"] = {"polish_skipped": True, "polish_skip_reason": "external_ai_path"}
        out["_diagnostics"] = diag

    elapsed = time_mod.time() - t_start
    if diag.get("external_typed_buckets"):
        logger.info(
            "[extract-meeting-external] done meeting_id=%s typed i=%s ini=%s p=%s t=%s elapsed=%.2fs",
            meeting_id,
            len(ideas),
            len(initiatives),
            len(projects),
            len(tasks),
            elapsed,
        )
    else:
        logger.info("[extract-meeting-external] done meeting_id=%s candidates=%s elapsed=%.2fs", meeting_id, len(candidates), elapsed)
    try:
        log_activity_simple(
            type=ActivityType.MEETING_PROCESSED.value,
            entity_type=ActivityEntityType.MEETING.value,
            entity_id=meeting_id,
            source="meeting-extraction-external",
            detail=f"engine={diag.get('selected_external_ai_engine')} wash={wash_data_for_call} elapsed={elapsed:.2f}s",
        )
    except Exception:
        logger.debug("activity log failed", exc_info=True)

    return out
