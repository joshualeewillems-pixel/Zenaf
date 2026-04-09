"""
Council preflight: merge UI/runtime hints into the council packet before seats run.
Does not force a single answer/clarify mode per run — seats judge independently.

Future: optional four-channel (water/soil/condition/fruit) summaries from the same
``UnifiedNodeAssessment`` contract as the vision map may augment grounding blocks here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Overwritten on each enriched council packet build (debug: inspect Notes / PRIMARY / working set).
_LAST_ENRICHED_PACKET_LOG = Path(__file__).resolve().parent.parent / "last_packet.txt"

from local_ai.developmental_guidance import (
    attach_resonance_escalation_to_developmental_guidance,
    format_developmental_guidance_packet_block,
)
from local_ai.vision_execution.ve_integration_schema import (
    hydration_field_block,
    hydration_inline_list,
    hydrated_structured_bullets as _hydrated_structured_bullets,
)


# Must match the header emitted by `_format_ve_focus_block` (used to attach stricter seat rules).
PRIMARY_CONTEXT_MARKER = "PRIMARY CONTEXT (authoritative):"
# When vague questions lack grounding signals, PRIMARY is omitted; seats see this instead (not split as primary).
CONTEXT_LEGITIMACY_NOTE_MARKER = "CONTEXT NOTE (non-authoritative):"
# Prepended to server-derived Vision & Execution lists in council Context (ideas/tasks/initiatives).
VE_WORKING_SET_MARKER = "VISION EXECUTION WORKING SET (live database snapshot for this user):"
# Narrow list for inventory questions when the user names one subject (replaces full working set for that turn).
VE_INVENTORY_SCOPE_MARKER = (
    "VISION EXECUTION WORKING SET (scoped — inventory question; this block is ONLY the named subject and linked work):"
)
# Prepended when client opens an intentional sub-thread (digression) — not authoritative vs PRIMARY.
SCOPED_DIGRESSION_BACKGROUND_MARKER = "BACKGROUND (parent thread — digression; last messages only):"

# Vague referents — ambiguous only when no explicit brief / id / name tie (see legitimacy helpers).
_VAGUE_REFERENT_RES = (
    re.compile(r"\bthis\s+project\b", re.I),
    re.compile(r"\bthe\s+project\b", re.I),
    re.compile(r"\bthis\s+initiative\b", re.I),
    re.compile(r"\bthe\s+initiative\b", re.I),
    re.compile(r"\bnext\s+step\b", re.I),
)
# Strong object / brief signals in the question text itself.
_EXPLICIT_ID_RE = re.compile(
    r"(?:\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b)"
    r'|(?:\b(?:entity|project|task|initiative)\s*[#:]?\s*[A-Za-z0-9_-]{6,}\b)',
    re.I,
)
_STOP_WORDS = frozenset(
    "the a an this that for with what when which who how why next step from your our their".split()
)


def _question_has_vague_referent(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    return any(p.search(q) for p in _VAGUE_REFERENT_RES)


def _question_appears_to_include_brief(question: str) -> bool:
    q = (question or "").strip()
    if len(q) >= 400:
        return True
    low = q.lower()
    if "\n" in q and ("outcome:" in low or "project:" in low or "initiative:" in low or "constraint" in low):
        return True
    return False


def question_has_explicit_grounding_cues(question: str) -> bool:
    """True when the question text alone supplies object scope (id, structured brief, etc.)."""
    q = (question or "").strip()
    if not q:
        return False
    if _question_appears_to_include_brief(q):
        return True
    if _EXPLICIT_ID_RE.search(q):
        return True
    return False


def _tokenize_for_overlap(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{3,}", text.lower())
    return {t for t in raw if t not in _STOP_WORDS}


def _question_aligns_with_ve_title(question: str, preflight: CouncilPreflight) -> bool:
    title = _s(preflight.ve_focus_title) or ""
    if not title:
        return False
    q_tokens = _tokenize_for_overlap(question)
    t_tokens = _tokenize_for_overlap(title)
    if not q_tokens or not t_tokens:
        return False
    return bool(q_tokens & t_tokens)


def grounding_signals_strong(
    preflight: CouncilPreflight,
    subject_ref: dict[str, Any] | None,
    object_snapshot: dict[str, Any] | None,
) -> tuple[bool, list[str]]:
    """
    Strong enough to treat Vision/Execution PRIMARY as authoritative.
    Returns (strong, reason_codes).
    """
    reasons: list[str] = []
    if preflight.grounding_explicit:
        reasons.append("grounding_explicit_ui")
        return True, reasons
    if question_has_explicit_grounding_cues(preflight.user_question):
        reasons.append("question_explicit_cues")
        return True, reasons
    if subject_ref and isinstance(subject_ref, dict):
        sid = _s(subject_ref.get("entity_id"))
        if sid:
            reasons.append("subject_ref_entity_id")
            return True, reasons
    if object_snapshot and isinstance(object_snapshot, dict):
        keys = {str(k).lower() for k in object_snapshot.keys()}
        if "title" in keys or "entity_id" in keys or "id" in keys:
            reasons.append("object_snapshot_ids")
            return True, reasons
        if len(object_snapshot) >= 2:
            reasons.append("object_snapshot_rich")
            return True, reasons
    if _question_aligns_with_ve_title(preflight.user_question, preflight):
        reasons.append("question_title_overlap")
        return True, reasons
    vf = preflight.ve_focus if isinstance(preflight.ve_focus, dict) else None
    if vf and _s(vf.get("entity_id")) and _s(vf.get("entity_type")):
        # Resolved record focus from the app: treat as authoritative grounding for this turn.
        reasons.append("ve_focus_resolved_entity")
        return True, reasons
    return False, reasons


def _raw_context_rejects_authoritative_primary(preflight: CouncilPreflight) -> bool:
    """
    Client/thread may explicitly say there is no authoritative object while ve_focus still exists
    (navigation hint only). Honor that unless grounding_signals_strong overrides.
    """
    raw = (preflight.raw_context_block or "").strip().lower()
    if not raw:
        return False
    needles = (
        "no authoritative object",
        "no authoritative primary",
    )
    return any(n in raw for n in needles)


def should_treat_primary_as_authoritative(
    preflight: CouncilPreflight,
    subject_ref: dict[str, Any] | None,
    object_snapshot: dict[str, Any] | None,
    *,
    question_kind: str | None = None,
) -> tuple[bool, str]:
    """
    If a PRIMARY block would be emitted, decide whether it may be authoritative.
    When false, PRIMARY is omitted in favor of CONTEXT NOTE + non-primary assembly.
    """
    q = (preflight.user_question or "").strip()
    primary_would_exist = bool(_format_ve_focus_block(preflight))
    if not primary_would_exist:
        return True, "no_primary_candidate"
    qk = (question_kind or "").strip()
    if qk in ("state_inventory", "missing_fields"):
        return True, "question_kind_inventory"
    if _raw_context_rejects_authoritative_primary(preflight):
        strong, _ = grounding_signals_strong(preflight, subject_ref, object_snapshot)
        if not strong:
            return False, "raw_context_rejects_authoritative_primary"
        # Thread text explicitly denied an authoritative object — honor unless UI flagged explicit grounding.
        if not preflight.grounding_explicit:
            return False, "raw_context_rejects_authoritative_primary"
    if not _question_has_vague_referent(q):
        return True, "question_not_vague"
    strong, _ = grounding_signals_strong(preflight, subject_ref, object_snapshot)
    if strong:
        return True, "grounding_strong"
    return False, "vague_question_weak_grounding"


def _context_legitimacy_note(preflight: CouncilPreflight) -> str:
    hints: list[str] = []
    title = _s(preflight.ve_focus_title)
    if title:
        hints.append(
            f'Possible UI focus (candidate only, not confirmed for this question): "{title[:200]}". '
            "Do not assume the user means this object."
        )
    vs = preflight.ve_selection if isinstance(preflight.ve_selection, dict) else None
    if vs:
        bits = []
        for key in ("initiativeId", "projectId", "taskId", "assetId"):
            if vs.get(key):
                bits.append(f"{key}={vs.get(key)}")
        if bits:
            hints.append("Navigation ids (candidates): " + ", ".join(bits))
    hint_body = "\n".join(f"• {h}" for h in hints) if hints else "• (No structured UI focus to list.)"
    return (
        f"{CONTEXT_LEGITIMACY_NOTE_MARKER}\n"
        "The user question uses vague referents (e.g. this project / next step) without tying them to a named object in the question. "
        "Do **not** treat any Vision & Execution selection as authoritative ground truth for what they mean.\n"
        "Prefer a response that: (1) when Runtime / folder / topic lines below name concrete work, offers **short next-move options** "
        "in that vocabulary (candidate labels, not asserted truth), then may lean toward one with a brief reason; "
        "(2) if those signals are absent, asks for missing brief fields or one clarifying question; "
        "(3) or lists candidate objects from Runtime/workflow as **options** without claiming which is correct.\n"
        f"{hint_body}"
    )
# Prepended to all enriched council context (before PRIMARY when present).
SYSTEM_FAILURE_STATE_MARKER = "SYSTEM FAILURE STATE:"
# Back-compat alias for tests and callers checking for the live-system block.
SYSTEM_STATE_MARKER = SYSTEM_FAILURE_STATE_MARKER

_GENERIC_LINEAGE_LABELS = frozenset(
    {
        "initiatives",
        "initiative",
        "projects",
        "project",
        "tasks",
        "task",
        "assets",
        "asset",
        "vision & execution",
        "vision and execution",
        "home",
    }
)


def council_packet_has_primary_context(context: str | None) -> bool:
    """True when enriched council context includes an authoritative Vision/Execution primary block."""
    return bool(context and PRIMARY_CONTEXT_MARKER in context)


def council_packet_has_system_state(context: str | None) -> bool:
    """True if `context` string embeds the system-failure block (legacy); no longer used in enriched Context."""
    return bool(context and SYSTEM_FAILURE_STATE_MARKER in context)


def council_system_failure_instruction_body() -> str:
    """
    System-failure baseline for council seats/synthesis instruction layer only.
    Must NOT appear inside the user Context packet (to avoid echo in model output).
    """
    return (
        "SYSTEM FAILURE STATE:\n"
        "- Outputs are repetitive across seats\n"
        "- Advice is generic (kickoff meetings, define roles, etc.)\n"
        "- Responses are not grounded in the current system\n"
        "- Synthesis summarizes instead of deciding\n"
        "- Responses are too verbose\n"
        "\n"
        "You are fixing **THIS** system. Do **NOT** give advice for building a council.\n"
        "Every council answer must directly address **at least one** failure listed above (by behavior, not by repeating these headings)."
    )


def _format_council_system_state_block() -> str:
    """Alias for instruction-layer body (not for embedding in Context)."""
    return council_system_failure_instruction_body()


def _lineage_meaningful_labels(lineage: list[Any]) -> list[str]:
    out: list[str] = []
    for x in lineage[:20]:
        s = str(x).strip()
        if not s or s.lower() in _GENERIC_LINEAGE_LABELS:
            continue
        out.append(s)
    return out


@dataclass
class CouncilPreflight:
    """Structured hints from the client (and optional server defaults)."""

    user_question: str = ""
    active_surface: str | None = None  # e.g. workspace, home, vision_execution
    view_label: str | None = None  # topic strip / folder name
    breadcrumb: str | None = None  # optional combined label (e.g. "Radar Home")
    workspace_mode_label: str | None = None  # e.g. Council, Analyze
    topic_summary: str | None = None  # short secondary line from UI
    folder_path: str | None = None
    # Vision & Execution: optional field focus (entity + field + lineage)
    ve_focus: dict[str, Any] | None = None
    # Vision & Execution: tab + selected entity ids from navigation
    ve_selection: dict[str, Any] | None = None
    # Open row / list selection (stable scope for Lane A); independent of field-level ve_focus.
    ve_selected_entity: dict[str, Any] | None = None
    # Optional client-enriched labels (title/brief/status/owner) when available
    ve_focus_title: str | None = None
    ve_focus_brief: str | None = None
    ve_focus_description: str | None = None
    ve_focus_status: str | None = None
    ve_focus_owner: str | None = None
    # Extra lines the client already merged (thread, workflow)
    raw_context_block: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    # Client/UI: user explicitly anchored council to current selection (bypass vague-question demotion).
    grounding_explicit: bool = False
    # Read model: client-assembled DevelopmentalGuidanceContext JSON (hypotheses, evidence refs).
    developmental_guidance: dict[str, Any] | None = None
    # User explicitly asked for guidance in this turn (client hint).
    explicit_guidance_request: bool = False
    # Intentional sub-thread: narrow model to one entity; omit working set and full thread.
    scoped_digression: bool = False
    # Client-formatted last messages from parent thread (shown only in Background block).
    digression_background_block: str | None = None
    # Scoped UI: user clicked "Record changes" — bias trunk toward capture / pending_integration.
    digression_record_intent: bool = False


def parse_preflight_from_request(
    context: dict[str, Any] | None,
    question: str,
) -> CouncilPreflight:
    """Read optional `council_preflight` from POST /run context."""
    q = (question or "").strip()
    out = CouncilPreflight(user_question=q)
    if not context:
        return out
    raw = context.get("council_preflight")
    if isinstance(raw, dict):
        out.active_surface = _s(raw.get("active_surface"))
        out.view_label = _s(raw.get("view_label") or raw.get("workspace_topic_label"))
        out.breadcrumb = _s(raw.get("breadcrumb") or raw.get("home_strip_label"))
        out.workspace_mode_label = _s(raw.get("workspace_mode_label"))
        out.topic_summary = _s(raw.get("topic_summary") or raw.get("workspace_topic_summary"))
        out.folder_path = _s(raw.get("folder_path"))
        vf = raw.get("ve_focus")
        if isinstance(vf, dict) and vf:
            out.ve_focus = vf
        vs = raw.get("ve_selection")
        if isinstance(vs, dict) and vs:
            out.ve_selection = vs
        vse = raw.get("ve_selected_entity")
        if isinstance(vse, dict) and vse:
            out.ve_selected_entity = vse
        out.ve_focus_title = _s(raw.get("ve_focus_title"))
        out.ve_focus_brief = _s(raw.get("ve_focus_brief"))
        out.ve_focus_description = _s(raw.get("ve_focus_description"))
        out.ve_focus_status = _s(raw.get("ve_focus_status"))
        out.ve_focus_owner = _s(raw.get("ve_focus_owner"))
        ge = raw.get("grounding_explicit")
        if ge is True or str(ge).lower() in ("1", "true", "yes"):
            out.grounding_explicit = True
        dg = raw.get("developmental_guidance")
        if isinstance(dg, dict) and dg:
            out.developmental_guidance = dg
        egr = raw.get("explicit_guidance_request")
        if egr is True or str(egr).lower() in ("1", "true", "yes"):
            out.explicit_guidance_request = True
        sd2 = raw.get("is_scoped_digression")
        if sd2 is True or str(sd2).lower() in ("1", "true", "yes"):
            out.scoped_digression = True
        dri = raw.get("digression_record_intent")
        if dri is True or str(dri).lower() in ("1", "true", "yes"):
            out.digression_record_intent = True
    # Legacy: folder at top level
    if not out.folder_path and context.get("folder_path"):
        out.folder_path = _s(context.get("folder_path"))
    if context.get("context_block") and isinstance(context["context_block"], str):
        out.raw_context_block = context["context_block"].strip()
    elif not out.raw_context_block and out.folder_path:
        out.raw_context_block = f"Folder: {out.folder_path}"
    sd = context.get("is_scoped_digression")
    if sd is True or str(sd).lower() in ("1", "true", "yes"):
        out.scoped_digression = True
    dbg = context.get("digression_background")
    if isinstance(dbg, str) and dbg.strip():
        out.digression_background_block = dbg.strip()
    return out


def _s(v: Any) -> str | None:
    if v is None:
        return None
    t = str(v).strip()
    return t or None


def _client_ve_field_weak(s: str | None) -> bool:
    """True when the client snapshot for a VE field is empty or a non-authoritative placeholder."""
    t = (s or "").strip()
    if not t or t in ("—", "-", "–"):
        return True
    low = t.lower()
    if "scoped sub-thread" in low and "vision & execution" in low:
        return True
    if low.startswith("(not provided"):
        return True
    return False


def _hydrate_preflight_ve_focus_from_storage(
    preflight: CouncilPreflight,
    user_id: str | None,
    *,
    user_question: str | None = None,
) -> None:
    """
    Merge SQLite row into council preflight when the client omitted or placeholder-filled snapshot fields.
    Ensures PRIMARY CONTEXT reflects persisted entity state, not only in-memory UI refs.
    """
    uid = (user_id or "").strip()
    if not uid:
        return
    vf = preflight.ve_focus if isinstance(preflight.ve_focus, dict) else None
    if not vf:
        return
    et = (_s(vf.get("entity_type")) or "").lower()
    eid = _s(vf.get("entity_id"))
    if not eid:
        return
    try:
        from local_ai.vision_execution import storage as ve_storage
    except Exception:
        return

    extras: list[str] = []

    if et == "idea":
        row = ve_storage.get_idea(eid, uid)
        if not row:
            return
        title = str(row.get("title") or "").strip()
        summary = str(row.get("summary") or "").strip()
        desc = str(row.get("description") or "").strip()
        status = str(row.get("status") or "").strip()
        desired = str(row.get("desired_outcome") or "").strip()
        notes = str(row.get("notes") or "").strip()
        if _client_ve_field_weak(preflight.ve_focus_title) and title:
            preflight.ve_focus_title = title
        if _client_ve_field_weak(preflight.ve_focus_brief) and summary:
            preflight.ve_focus_brief = summary
        if _client_ve_field_weak(preflight.ve_focus_description) and desc:
            preflight.ve_focus_description = desc
        if status and _client_ve_field_weak(preflight.ve_focus_status):
            preflight.ve_focus_status = status
        if desired:
            blk = hydration_field_block("idea", "desired_outcome", desired, max_body_len=8000)
            if blk:
                extras.append(blk)
        if notes:
            blk = hydration_field_block("idea", "notes", notes, max_body_len=2000)
            if blk:
                extras.append(blk)
        for k in ("linked_people", "linked_assets", "linked_ideas"):
            v = row.get(k)
            if isinstance(v, list) and v:
                line = hydration_inline_list("idea", k, [str(x) for x in v])
                if line:
                    extras.append(line)

    elif et == "project":
        row = ve_storage.get_project(eid, uid)
        if not row:
            return
        title = str(row.get("title") or "").strip()
        brief = str(row.get("brief") or "").strip()
        status = str(row.get("status") or "").strip()
        notes = str(row.get("notes") or "").strip()
        deliverables = str(row.get("deliverables") or "").strip()
        nxt = str(row.get("next_step_ai") or "").strip()
        if _client_ve_field_weak(preflight.ve_focus_title) and title:
            preflight.ve_focus_title = title
        if _client_ve_field_weak(preflight.ve_focus_brief) and brief:
            preflight.ve_focus_brief = brief
        if status and _client_ve_field_weak(preflight.ve_focus_status):
            preflight.ve_focus_status = status
        body_parts: list[str] = []
        if deliverables:
            blk = hydration_field_block("project", "deliverables", deliverables, max_body_len=3500)
            if blk:
                body_parts.append(blk)
        if nxt:
            blk = hydration_field_block("project", "next_step_ai", nxt, max_body_len=2000)
            if blk:
                body_parts.append(blk)
        if notes:
            blk = hydration_field_block("project", "notes", notes, max_body_len=2000)
            if blk:
                body_parts.append(blk)
        if body_parts and _client_ve_field_weak(preflight.ve_focus_description):
            preflight.ve_focus_description = "\n\n".join(body_parts)

    elif et == "initiative":
        row = ve_storage.get_initiative(eid, uid)
        if not row:
            return
        title = str(row.get("title") or "").strip()
        brief = str(row.get("brief") or "").strip()
        status = str(row.get("status") or "").strip()
        notes = str(row.get("notes") or "").strip()
        nxt = str(row.get("next_step_ai") or "").strip()
        dependencies = str(row.get("dependencies") or "").strip()
        risks = str(row.get("risks") or "").strip()
        recommendation = str(row.get("recommendation") or "").strip()
        if _client_ve_field_weak(preflight.ve_focus_title) and title:
            preflight.ve_focus_title = title
        if _client_ve_field_weak(preflight.ve_focus_brief) and brief:
            preflight.ve_focus_brief = brief
        if status and _client_ve_field_weak(preflight.ve_focus_status):
            preflight.ve_focus_status = status
        body_parts = []
        if nxt:
            blk = hydration_field_block("initiative", "next_step_ai", nxt, max_body_len=2000)
            if blk:
                body_parts.append(blk)
        if dependencies:
            blk = hydration_field_block("initiative", "dependencies", dependencies, max_body_len=3500)
            if blk:
                body_parts.append(blk)
        if risks:
            blk = hydration_field_block("initiative", "risks", risks, max_body_len=2500)
            if blk:
                body_parts.append(blk)
        if recommendation:
            blk = hydration_field_block("initiative", "recommendation", recommendation, max_body_len=2500)
            if blk:
                body_parts.append(blk)
        qlow = (user_question or "").lower()
        admin_notes_intent = any(
            k in qlow
            for k in (
                "diagnostic",
                "diagnostics",
                "admin notes",
                "admin note",
                "what's in notes",
                "whats in notes",
            )
        )
        brief_is_weak = not str(brief or "").strip()
        if notes:
            blk = hydration_field_block("initiative", "notes", notes, max_body_len=2000)
            if blk and (admin_notes_intent or brief_is_weak):
                body_parts.append(blk)
        if body_parts and _client_ve_field_weak(preflight.ve_focus_description):
            preflight.ve_focus_description = "\n\n".join(body_parts)

    elif et == "task":
        row = ve_storage.get_task(eid, uid)
        if not row:
            return
        title = str(row.get("title") or "").strip()
        description = str(row.get("description") or "").strip()
        status = str(row.get("status") or "").strip()
        criteria = str(row.get("completion_criteria") or "").strip()
        notes = str(row.get("notes") or "").strip()
        if _client_ve_field_weak(preflight.ve_focus_title) and title:
            preflight.ve_focus_title = title
        if _client_ve_field_weak(preflight.ve_focus_brief) and description:
            preflight.ve_focus_brief = description
        if status and _client_ve_field_weak(preflight.ve_focus_status):
            preflight.ve_focus_status = status
        body_parts = []
        if criteria:
            blk = hydration_field_block("task", "completion_criteria", criteria, max_body_len=3500)
            if blk:
                body_parts.append(blk)
        if notes:
            blk = hydration_field_block("task", "notes", notes, max_body_len=2000)
            if blk:
                body_parts.append(blk)
        if body_parts:
            base = (preflight.ve_focus_description or "").strip()
            addon = "\n\n".join(body_parts)
            if _client_ve_field_weak(preflight.ve_focus_description):
                preflight.ve_focus_description = (description + "\n\n" + addon).strip() if description else addon
            elif addon and addon not in base:
                preflight.ve_focus_description = f"{base}\n\n{addon}".strip()

    else:
        return

    if extras:
        base_desc = (preflight.ve_focus_description or "").strip()
        addon = "\n\n".join(extras)
        if addon and addon not in base_desc:
            preflight.ve_focus_description = f"{base_desc}\n\n{addon}".strip() if base_desc else addon


def _ve_ws_collapse(text: str | None) -> str:
    return " ".join(str(text or "").split()).strip()


def _ve_same_text(a: str | None, b: str | None) -> bool:
    return bool(_ve_ws_collapse(a)) and _ve_ws_collapse(a) == _ve_ws_collapse(b)


def _ui_field_schema_block(entity_type: str | None) -> str:
    """
    Authoritative list of real Vision & Execution UI surfaces for this entity type.
    Injected into PRIMARY so seats do not invent generic fields (e.g. “Expanded description” on initiatives).
    """
    et = (entity_type or "").strip().lower()
    if et == "initiative":
        return (
            "\n\n**UI FIELD SCHEMA (initiative — authoritative names only):**\n"
            "- **Identity / scope:** Title, Brief, Owner, Status, Source idea; linked projects (read-only list in panel).\n"
            "- **Risks (text):** Risks, Kill criteria (when present on the record).\n"
            "- **Decision / Summary:** Evaluation-driven fields (e.g. Recommendation, Estimated cost, Estimated timeframe, "
            "Strategic alignment (AI)); sliders such as Priority / Strategic value / Energy after evaluation.\n"
            "- **Execution:** Checklist rows (**Execution steps** — their own list; not a single free-text “Next steps” field). "
            "Legacy **Next step (AI)** text is transitional; canonical actionable steps are **Execution steps**.\n"
            "- **Risks / admin:** **Diagnostics / admin notes** (the `notes` column — not labeled “Notes” in the initiative UI). "
            "Do **not** treat this as the main description; primary prose belongs in **Brief**.\n"
            "**Hard rule:** Do **not** refer to **Expanded description** on initiatives (not in UI). Do **not** describe one "
            "editable field called **Next steps** — use **Execution steps** for checklist work or name specific **Decision** fields.\n"
            "**Concept map:** colloquial “description” / main prose → **Brief**; tactical checklist → **Execution steps**; "
            "evaluation narrative → **Decision fields**.\n"
            "**Mutation truth:** Never claim an Owner/Brief/Status/etc. change **succeeded** from chat prose alone. "
            "Only treat a write as confirmed when the packet includes **INTEGRATION COMMITTED** or a deterministic server line "
            "like **Recorded →** / **Created →** for this turn. Otherwise invite the user to verify in Vision & Execution.\n"
        )
    if et == "project":
        return (
            "\n\n**UI FIELD SCHEMA (project — authoritative names only):**\n"
            "- **Core:** Title, Brief (scope & outcomes), Status, Initiative, Owner, supporting owners, dates, priority, "
            "estimated weekly hours, Notes.\n"
            "- **Suggested work (AI):** Mediation lane (not the same as the main Brief).\n"
            "- **Next step (AI)** text on the record is optional/legacy; do not treat it as the primary “next steps” surface.\n"
            "**Hard rule:** Do **not** say **Expanded description** for projects; main prose is **Brief**.\n"
        )
    if et == "task":
        return (
            "\n\n**UI FIELD SCHEMA (task — authoritative names only):**\n"
            "- Title, Description, Assignee, Due date, Priority, Estimated hours, Status, Completion criteria, Notes.\n"
            "**Hard rule:** Do **not** invent **Expanded description** or initiative-style fields for tasks.\n"
        )
    if et == "idea":
        return (
            "\n\n**UI FIELD SCHEMA (idea — authoritative names only):**\n"
            "- Title, Short note, Expanded description, Intent / what this idea is trying to become, Notes; promotion / analysis "
            "sections as shown in app.\n"
            "**Note:** **Expanded description** is valid **only** for ideas — not for initiatives or projects.\n"
        )
    return ""


def _primary_bullets_initiative_or_project(
    entity_type: str,
    title: str | None,
    brief: str | None,
    expanded: str | None,
) -> list[str]:
    """PRIMARY lines for initiative/project — **Brief** only; never 'Expanded description'."""
    tit = _ve_ws_collapse(title)
    br = _s(brief)
    ex = _s(expanded)
    struct = _hydrated_structured_bullets(ex, entity_type)

    def trunc(s: str, n: int) -> str:
        return (s[: n - 1] + "…") if len(s) > n else s

    lines: list[str] = []
    if br and ex and not _ve_same_text(br, ex):
        b_n, e_n = _ve_ws_collapse(br), _ve_ws_collapse(ex)
        if e_n.startswith(b_n) and len(e_n) > len(b_n):
            lines.append(f"- Brief: {trunc(ex, 4000)}")
        else:
            lines.append(f"- Brief: {trunc(br, 2000)}")
            if struct:
                lines.extend(struct)
            else:
                lines.append(f"- Supplemental record text: {trunc(ex, 3000)}")
    elif br:
        lines.append(f"- Brief: {trunc(br, 4000)}")
        if ex and not _ve_same_text(br, ex) and struct:
            lines.extend(struct)
    elif ex:
        if struct:
            lines.append("- Brief: —")
            lines.extend(struct)
        else:
            lines.append(f"- Brief: {trunc(ex, 4000)}")
    else:
        lines.append("- Brief: —")

    out: list[str] = []
    for line in lines:
        if line.startswith("- Brief: "):
            body = line[len("- Brief: ") :].strip()
            body_n = _ve_ws_collapse(body)
            if tit and body_n and tit == body_n:
                continue
        elif line.startswith("- Supplemental record text: "):
            body = line[len("- Supplemental record text: ") :].strip()
            if tit and _ve_ws_collapse(body) == tit:
                continue
        out.append(line)
    return out if out else ["- Brief: —"]


def _primary_bullets_task(
    title: str | None,
    brief: str | None,
    expanded: str | None,
) -> list[str]:
    """Task PRIMARY uses **Description** (UI label), not idea-style Brief/Expanded."""
    tit = _ve_ws_collapse(title)
    br = _s(brief)
    ex = _s(expanded)
    struct = _hydrated_structured_bullets(ex, "task")

    def trunc(s: str, n: int) -> str:
        return (s[: n - 1] + "…") if len(s) > n else s

    lines: list[str] = []
    if br and ex and not _ve_same_text(br, ex):
        b_n, e_n = _ve_ws_collapse(br), _ve_ws_collapse(ex)
        if e_n.startswith(b_n) and len(e_n) > len(b_n):
            lines.append(f"- Description: {trunc(ex, 4000)}")
        else:
            lines.append(f"- Description: {trunc(br, 2000)}")
            if struct:
                lines.extend(struct)
            else:
                lines.append(f"- Supplemental record text: {trunc(ex, 3000)}")
    elif br:
        lines.append(f"- Description: {trunc(br, 4000)}")
        if ex and not _ve_same_text(br, ex) and struct:
            lines.extend(struct)
    elif ex:
        if struct:
            lines.append("- Description: —")
            lines.extend(struct)
        else:
            lines.append(f"- Description: {trunc(ex, 4000)}")
    else:
        lines.append("- Description: —")

    out: list[str] = []
    for line in lines:
        if line.startswith("- Description: "):
            body = line[len("- Description: ") :].strip()
            if tit and _ve_ws_collapse(body) == tit:
                continue
        elif line.startswith("- Supplemental record text: "):
            body = line[len("- Supplemental record text: ") :].strip()
            if tit and _ve_ws_collapse(body) == tit:
                continue
        out.append(line)
    return out if out else ["- Description: —"]


def _primary_content_bullets_for_entity(
    entity_type: str | None,
    title: str | None,
    brief: str | None,
    expanded: str | None,
) -> list[str]:
    et = (entity_type or "").strip().lower()
    if et == "idea":
        return _ve_description_bullets_for_focus(title, brief, expanded)
    if et in ("initiative", "project"):
        return _primary_bullets_initiative_or_project(et, title, brief, expanded)
    if et == "task":
        return _primary_bullets_task(title, brief, expanded)
    return _ve_description_bullets_for_focus(title, brief, expanded)


def _ve_description_bullets_for_focus(
    title: str | None,
    brief: str | None,
    expanded: str | None,
) -> list[str]:
    """
    One or two bullets for brief/expanded without repeating the same text twice
    or duplicating the title line (avoids model 'stutter' in replies).
    """
    tit = _ve_ws_collapse(title)
    br = _s(brief)
    ex = _s(expanded)
    if not br and not ex:
        return ["- Brief / description: —", "- Expanded description: —"]

    def trunc_b(s: str) -> str:
        return (s[:2000] + "…") if len(s) > 2000 else s

    def trunc_e(s: str) -> str:
        return (s[:4000] + "…") if len(s) > 4000 else s

    lines: list[str] = []
    if br and ex:
        if _ve_same_text(br, ex):
            one = trunc_b(br) if len(br) <= 2000 else trunc_e(br)
            lines.append(f"- Brief / description: {one}")
        else:
            b_n, e_n = _ve_ws_collapse(br), _ve_ws_collapse(ex)
            if b_n and e_n.startswith(b_n):
                lines.append(f"- Brief / description: {trunc_e(ex)}")
            elif e_n and b_n.startswith(e_n):
                lines.append(f"- Brief / description: {trunc_b(br)}")
            else:
                lines.append(f"- Brief / description: {trunc_b(br)}")
                lines.append(f"- Expanded description: {trunc_e(ex)}")
    elif br:
        lines.append(f"- Brief / description: {trunc_b(br)}")
    else:
        lines.append(f"- Brief / description: {trunc_e(ex)}")

    # Drop bullets whose body duplicates title (title already shown above).
    out: list[str] = []
    for line in lines:
        if line.startswith("- Brief / description: "):
            body = line[len("- Brief / description: ") :].strip()
        elif line.startswith("- Expanded description: "):
            body = line[len("- Expanded description: ") :].strip()
        else:
            out.append(line)
            continue
        body_n = _ve_ws_collapse(body)
        if tit and body_n and (tit == body_n or body in ("—",)):
            continue
        out.append(line)
    return out if out else ["- Brief / description: —", "- Expanded description: —"]


def _format_ve_focus_block(preflight: CouncilPreflight) -> str | None:
    """Primary Vision & Execution context: explicit authoritative block + reference IDs/lineage."""
    vf = preflight.ve_focus if isinstance(preflight.ve_focus, dict) else None
    vs = preflight.ve_selection if isinstance(preflight.ve_selection, dict) else None

    has_signal = bool(
        (vf and len(vf) > 0)
        or (vs and len(vs) > 0)
        or preflight.ve_focus_title
        or preflight.ve_focus_brief
        or preflight.ve_focus_description
        or preflight.ve_focus_status
        or preflight.ve_focus_owner
    )
    if not has_signal:
        return None

    et = _s(vf.get("entity_type")) if vf else None
    eid = _s(vf.get("entity_id")) if vf else None
    if not et and vs:
        if vs.get("taskId"):
            et = "task"
        elif vs.get("projectId"):
            et = "project"
        elif vs.get("initiativeId"):
            et = "initiative"
    type_display = et or "vision_execution_selection"

    title = _s(preflight.ve_focus_title)
    brief = _s(preflight.ve_focus_brief)
    expanded = _s(preflight.ve_focus_description)
    status = _s(preflight.ve_focus_status) or "—"
    owner = _s(preflight.ve_focus_owner)

    initiative_label: str | None = None
    lineage_meaningful: list[str] = []
    if vf:
        par = vf.get("parent")
        if isinstance(par, dict):
            pt = (_s(par.get("entity_type")) or "").lower()
            pl = _s(par.get("label"))
            if pt == "initiative" and pl:
                initiative_label = pl
        ll = vf.get("lineage_labels")
        if isinstance(ll, list) and ll:
            lineage_meaningful = _lineage_meaningful_labels(ll)
            if not initiative_label and lineage_meaningful:
                if (type_display or "").lower() in ("project", "task"):
                    initiative_label = lineage_meaningful[0]
                elif (type_display or "").lower() == "initiative":
                    initiative_label = lineage_meaningful[-1] or lineage_meaningful[0]

    if not title and lineage_meaningful:
        title = lineage_meaningful[-1]
    if (et or "").strip().lower() == "initiative" and title:
        from local_ai.vision_execution.initiative_completeness import normalize_initiative_display_title

        title = normalize_initiative_display_title(title) or title
    title_display = title or "(not provided — use Reference below: lineage, entity id, and field focus)"

    if (type_display or "").lower() == "initiative" and not initiative_label:
        initiative_label = title or (lineage_meaningful[-1] if lineage_meaningful else None)
    initiative_display = initiative_label or "(see Reference if parent initiative or lineage is listed)"

    et_norm = ((et or type_display or "").strip().lower())
    main_bullets: list[str] = [
        f"- Type: {type_display}",
        f"- Title: {title_display}",
        f"- Initiative: {initiative_display}",
        f"- Status: {status}",
        *_primary_content_bullets_for_entity(
            et_norm if et_norm in ("idea", "initiative", "project", "task") else None,
            title,
            brief,
            expanded,
        ),
    ]
    if owner:
        main_bullets.append(f"- Owner: {owner}")

    details: list[str] = []
    if vf and (eid or et):
        details.append(f"Focused entity: {et or 'entity'}" + (f" (id: {eid})" if eid else ""))
    if vf:
        fl = _s(vf.get("field_label"))
        fk = _s(vf.get("field_key"))
        if fl or fk:
            details.append(f"Field in focus: {fl or ''}" + (f" [{fk}]" if fk else ""))
        par = vf.get("parent")
        if isinstance(par, dict):
            pt = _s(par.get("entity_type"))
            pid = _s(par.get("entity_id"))
            pl = _s(par.get("label"))
            if pt or pid or pl:
                details.append(
                    "Parent: "
                    + (pt or "?")
                    + (f" (id: {pid})" if pid else "")
                    + (f" — {pl}" if pl else "")
                )
        ll = vf.get("lineage_labels")
        if isinstance(ll, list) and ll:
            details.append("Lineage: " + " → ".join(str(x) for x in ll[:12]))
    if vs:
        sel_bits: list[str] = []
        tab = _s(vs.get("tab"))
        if tab:
            sel_bits.append(f"tab={tab}")
        for key in ("initiativeId", "projectId", "taskId", "assetId"):
            v = vs.get(key)
            if v:
                sel_bits.append(f"{key}={v}")
        if sel_bits:
            details.append("Navigation selection: " + ", ".join(sel_bits))

    intro = (
        "**Authoritative snapshot:** The lines below are the application's record for the focused entity. "
        "When a line shows non-empty text, treat that as **verified state** — summarize or quote it faithfully. "
        "Do **not** claim a field is empty or missing if PRIMARY shows content for it.\n"
        "**Reply shape (mandatory):** (1) **State** — name or quote **Title** and every **non-empty** field line below. "
        "(2) **Sufficiency** — given the question and the **conversation thread**, judge whether this record is already a "
        "**valid configuration** for the user’s goal. **Draft** or a short brief does **not** automatically mean “must expand "
        "description”; role clarity can be enough. If the user states operational intent (e.g. catch-all, staging, bucket for "
        "ancillary work, intentionally loose), treat that as **authoritative** and pivot to **confirm + operationalize** "
        "(status change, 1–2 light guardrails, or leave as-is) — **not** repeated pressure to lengthen the brief.\n"
        "(3) **Gaps** — only if sufficiency is **actually** lacking for the stated goal. "
        "(4) **Move** — one clear recommendation or option set; **do not** re-issue the same “expand/refine description” "
        "advice after the user has already clarified role or asked to revise on those terms.\n"
        "The user's question is about THIS object unless they clearly refer to something else.\n"
        "**Type + field discipline:** Stay at the entity’s layer (initiative vs project vs task vs idea). Use **only** field "
        "names from **UI FIELD SCHEMA** and the bullets above — **do not** invent labels (e.g. **Expanded description** on "
        "initiatives/projects). For initiatives, tactical work belongs in **Execution steps** (checklist), not a generic "
        "“next steps” text field; decision narrative belongs in **Decision** fields.\n"
        "Avoid generic facilitation openers (“it seems you want…”, “this could involve…”, “to move forward…”); "
        "open with the entity itself.\n"
        "Treat every field above as ground truth. Ground your answer directly in that work — do not speak as if no subject were specified."
    )
    ref_block = ""
    if details:
        ref_block = "\n\nReference (IDs, field focus, navigation):\n" + "\n".join(f"• {d}" for d in details)

    schema_et = et_norm if et_norm in ("idea", "initiative", "project", "task") else ""
    schema_block = _ui_field_schema_block(schema_et)

    return PRIMARY_CONTEXT_MARKER + "\n\n" + intro + "\n\n" + "\n".join(main_bullets) + schema_block + ref_block


def _ve_one_line(text: str | None, max_len: int = 100) -> str:
    t = " ".join(str(text or "").split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _idea_tracked_field_gaps(idea: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if not str(idea.get("summary") or "").strip():
        gaps.append("summary")
    if not str(idea.get("description") or "").strip():
        gaps.append("description")
    if not str(idea.get("desired_outcome") or "").strip():
        gaps.append("desired_outcome")
    return gaps


def _initiative_tracked_field_gaps(init: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if not str(init.get("brief") or "").strip():
        gaps.append("brief")
    return gaps


def _project_tracked_field_gaps(project: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if not str(project.get("brief") or "").strip():
        gaps.append("brief")
    if not str(project.get("next_step_ai") or "").strip():
        gaps.append("next_step_ai")
    if not str(project.get("deliverables") or "").strip():
        gaps.append("deliverables")
    return gaps


def _extract_quoted_spans(question: str) -> list[str]:
    """Substrings inside '...' or \"...\" in the user question."""
    if not question:
        return []
    out: list[str] = []
    for m in re.finditer(r"'([^']{2,120})'|\"([^\"]{2,120})\"", question):
        bit = (m.group(1) or m.group(2) or "").strip()
        if bit:
            out.append(bit)
    return out


def _score_name_in_question(question: str, title: str) -> int:
    """Higher = stronger match between question text and entity title."""
    t = (title or "").strip()
    if not t:
        return 0
    low_q = question.lower()
    low_t = t.lower()
    score = 0
    for span in _extract_quoted_spans(question):
        s = span.strip().lower()
        if len(s) < 2:
            continue
        if s in low_t or low_t in s:
            score += 14
        else:
            st = _tokenize_for_overlap(s)
            tt = _tokenize_for_overlap(t)
            score += 5 * len(st & tt)
    qtok = _tokenize_for_overlap(question)
    ttok = _tokenize_for_overlap(t)
    score += len(qtok & ttok)
    if len(ttok) >= 1 and ttok.issubset(qtok):
        score += 8
    return score


def _ve_focus_alignment_bonus(preflight: CouncilPreflight, entity_type: str, entity_id: str) -> int:
    vf = preflight.ve_focus if isinstance(preflight.ve_focus, dict) else None
    if not vf:
        return 0
    et = _s(vf.get("entity_type")).lower()
    eid = _s(vf.get("entity_id"))
    if not eid:
        return 0
    if et == entity_type.lower() and eid == entity_id:
        return 12
    return 0


def _pick_scoped_ve_entity(
    user_id: str,
    question: str,
    preflight: CouncilPreflight,
) -> tuple[str, dict[str, Any]] | None:
    """
    Best-matching idea, project, or initiative row for inventory scoping.
    Returns None if ambiguous or too weak.
    """
    try:
        from local_ai.vision_execution import storage as ve_storage
    except Exception:
        return None

    q = (question or "").strip()
    if len(q) < 8:
        return None

    ideas = ve_storage.list_ideas(user_id)
    projects = ve_storage.list_projects(user_id)
    initiatives = ve_storage.list_initiatives(user_id)

    scored: list[tuple[str, dict[str, Any], int]] = []
    for idea in ideas:
        iid = str(idea.get("id") or "")
        tit = str(idea.get("title") or "")
        sc = _score_name_in_question(q, tit) + _ve_focus_alignment_bonus(preflight, "idea", iid)
        scored.append(("idea", idea, sc))
    for proj in projects:
        pid = str(proj.get("id") or "")
        tit = str(proj.get("title") or "")
        sc = _score_name_in_question(q, tit) + _ve_focus_alignment_bonus(preflight, "project", pid)
        scored.append(("project", proj, sc))
    for ini in initiatives:
        iid = str(ini.get("id") or "")
        tit = str(ini.get("title") or "")
        sc = _score_name_in_question(q, tit) + _ve_focus_alignment_bonus(preflight, "initiative", iid)
        scored.append(("initiative", ini, sc))

    scored.sort(key=lambda x: -x[2])
    if not scored or scored[0][2] < 4:
        return None
    top = scored[0][2]
    if len(scored) > 1 and scored[1][2] == top and top >= 10:
        return None
    return scored[0][0], scored[0][1]


def format_ve_working_set_scoped_inventory_block(
    user_id: str | None,
    question: str,
    preflight: CouncilPreflight,
    *,
    max_chars: int = 4200,
) -> str | None:
    """
    When an inventory-style question names one subject, emit only that entity + linked child work.
    Returns None to fall back to the full working set snapshot.
    """
    uid = (user_id or "").strip()
    if not uid:
        return None
    picked = _pick_scoped_ve_entity(uid, question, preflight)
    if not picked:
        return None
    kind, row = picked
    try:
        from local_ai.vision_execution import storage as ve_storage
    except Exception:
        return None

    parts: list[str] = []
    budget = max_chars - len(VE_INVENTORY_SCOPE_MARKER) - 40
    rid = str(row.get("id") or "")

    if kind == "idea":
        title = _ve_one_line(row.get("title"), 100) or "(untitled idea)"
        gaps = _idea_tracked_field_gaps(row)
        st = str(row.get("status") or "").strip() or "—"
        line = f"Idea: {title} (id: {rid}) — status: {st}"
        if gaps:
            line += f" — missing tracked fields: {', '.join(gaps)}"
        else:
            line += " — tracked idea fields filled"
        parts.append(line)

        inits = [i for i in ve_storage.list_initiatives(uid) if str(i.get("source_idea_id") or "") == rid]
        if inits:
            sub = ["Linked initiatives (from this idea):"]
            for ini in inits[:6]:
                it = _ve_one_line(ini.get("title"), 90) or "(untitled)"
                ig = _initiative_tracked_field_gaps(ini)
                ist = str(ini.get("status") or "").strip() or "—"
                sub.append(
                    f"• {it} (id: {ini.get('id')}) — "
                    + (f"missing: {', '.join(ig)}" if ig else "brief present")
                    + f" — status: {ist}"
                )
            parts.append("\n".join(sub))

        all_projs = ve_storage.list_projects(uid)
        iids = {str(i.get("id")) for i in inits}
        child_projs = [p for p in all_projs if str(p.get("initiative_id") or "") in iids]
        if child_projs:
            sub = ["Projects under those initiatives:"]
            for p in child_projs[:10]:
                pt = _ve_one_line(p.get("title"), 90) or "(untitled)"
                pg = _project_tracked_field_gaps(p)
                pst = str(p.get("status") or "").strip() or "—"
                sub.append(
                    f"• {pt} (id: {p.get('id')}) — "
                    + (f"missing: {', '.join(pg)}" if pg else "key fields present")
                    + f" — status: {pst}"
                )
            parts.append("\n".join(sub))

        pids = [str(p.get("id")) for p in child_projs if p.get("id")]
        if pids:
            sub = ["Open tasks on those projects (not done/closed):"]
            any_task = False
            for pid in pids[:12]:
                for t in ve_storage.list_tasks(user_id=uid, project_id=pid):
                    if str(t.get("status") or "").strip().lower() in _TASK_TERMINAL_STATUSES:
                        continue
                    any_task = True
                    tt = _ve_one_line(t.get("title"), 90) or "(untitled)"
                    tst = str(t.get("status") or "").strip() or "—"
                    sub.append(f"• {tt} — status: {tst}")
                    if sum(len(x) + 1 for x in sub) > budget * 0.45:
                        sub.append("• … (more tasks omitted)")
                        break
            if any_task:
                parts.append("\n".join(sub))

    elif kind == "project":
        title = _ve_one_line(row.get("title"), 100) or "(untitled project)"
        pg = _project_tracked_field_gaps(row)
        st = str(row.get("status") or "").strip() or "—"
        line = f"Project: {title} (id: {rid}) — status: {st}"
        line += f" — missing: {', '.join(pg)}" if pg else " — key project fields present"
        parts.append(line)
        sub = ["Open tasks for this project:"]
        any_task = False
        for t in ve_storage.list_tasks(user_id=uid, project_id=rid):
            if str(t.get("status") or "").strip().lower() in _TASK_TERMINAL_STATUSES:
                continue
            any_task = True
            tt = _ve_one_line(t.get("title"), 90) or "(untitled)"
            tst = str(t.get("status") or "").strip() or "—"
            sub.append(f"• {tt} — status: {tst}")
        if any_task:
            parts.append("\n".join(sub))

    elif kind == "initiative":
        title = _ve_one_line(row.get("title"), 100) or "(untitled initiative)"
        ig = _initiative_tracked_field_gaps(row)
        st = str(row.get("status") or "").strip() or "—"
        line = f"Initiative: {title} (id: {rid}) — status: {st}"
        line += f" — missing: {', '.join(ig)}" if ig else " — brief present"
        parts.append(line)
        projs = [p for p in ve_storage.list_projects(uid) if str(p.get("initiative_id") or "") == rid]
        if projs:
            sub = ["Projects under this initiative:"]
            for p in projs[:10]:
                pt = _ve_one_line(p.get("title"), 90) or "(untitled)"
                pg = _project_tracked_field_gaps(p)
                pst = str(p.get("status") or "").strip() or "—"
                sub.append(
                    f"• {pt} (id: {p.get('id')}) — "
                    + (f"missing: {', '.join(pg)}" if pg else "key fields present")
                    + f" — status: {pst}"
                )
            parts.append("\n".join(sub))
        sub = ["Open tasks under this initiative (via projects):"]
        any_task = False
        for t in ve_storage.list_tasks(user_id=uid, initiative_id=rid):
            if str(t.get("status") or "").strip().lower() in _TASK_TERMINAL_STATUSES:
                continue
            any_task = True
            tt = _ve_one_line(t.get("title"), 90) or "(untitled)"
            tst = str(t.get("status") or "").strip() or "—"
            sub.append(f"• {tt} — status: {tst}")
        if any_task:
            parts.append("\n".join(sub))

    if not parts:
        return None
    body = "\n\n".join(parts)
    if len(body) > max_chars:
        body = body[: max_chars - 20] + "\n… (truncated)"
    return f"{VE_INVENTORY_SCOPE_MARKER}\n{body}"


_TASK_TERMINAL_STATUSES = frozenset(
    {
        "done",
        "complete",
        "completed",
        "cancelled",
        "canceled",
        "closed",
        "archived",
    }
)


def format_ve_working_set_snapshot_block(
    user_id: str | None,
    *,
    max_chars: int = 4800,
    max_ideas: int = 18,
    max_tasks: int = 14,
    max_initiatives: int = 10,
) -> str | None:
    """
    Compact Vision & Execution facts from SQLite for council Context so Zenaf can name real titles
    and missing fields (not paraphrase the question). No-op when user_id is missing or lists are empty.
    """
    uid = (user_id or "").strip()
    if not uid:
        return None
    try:
        from local_ai.vision_execution import storage as ve_storage
    except Exception:
        return None

    parts: list[str] = []
    char_budget = max_chars - len(VE_WORKING_SET_MARKER) - 20

    _peer_note = " - NOTE: This is a separate, distinct work item."

    ideas = ve_storage.list_ideas(uid)[:max_ideas]
    if ideas:
        sub = [
            "OTHER IDEAS (For reference only; do NOT blend these into the PRIMARY focus):",
        ]
        for idea in ideas:
            title = _ve_one_line(idea.get("title"), 90) or "(untitled)"
            gaps = _idea_tracked_field_gaps(idea)
            st = str(idea.get("status") or "").strip() or "—"
            iid = str(idea.get("id") or "").strip() or "—"
            if gaps:
                sub.append(
                    f"• {title} [ID: {iid}] (Status: {st}) — missing: {', '.join(gaps)}{_peer_note}"
                )
            else:
                sub.append(
                    f"• {title} [ID: {iid}] (Status: {st}) — tracked fields filled{_peer_note}"
                )
            if sum(len(x) + 1 for x in sub) > char_budget * 0.55:
                sub.append("• … (more ideas omitted for length)")
                break
        parts.append("\n".join(sub))

    tasks = ve_storage.list_tasks(uid)[: max_tasks * 2]
    open_tasks = [
        t
        for t in tasks
        if str(t.get("status") or "").strip().lower() not in _TASK_TERMINAL_STATUSES
    ][:max_tasks]
    if open_tasks:
        sub = [
            "OTHER OPEN ITEMS (For reference only; do NOT blend these into the PRIMARY focus):",
        ]
        for t in open_tasks:
            title = _ve_one_line(t.get("title"), 90) or "(untitled)"
            st = str(t.get("status") or "").strip() or "—"
            tid = str(t.get("id") or "").strip() or "—"
            sub.append(f"• {title} [ID: {tid}] (Status: {st}){_peer_note}")
            if sum(len(x) + 1 for x in sub) > char_budget * 0.35:
                sub.append("• … (more tasks omitted for length)")
                break
        parts.append("\n".join(sub))

    inits = ve_storage.list_initiatives(uid)[:max_initiatives]
    if inits:
        sub = [
            "OTHER INITIATIVES (For reference only; do NOT blend these into the PRIMARY focus):",
        ]
        for init in inits:
            title = _ve_one_line(init.get("title"), 90) or "(untitled)"
            gaps = _initiative_tracked_field_gaps(init)
            st = str(init.get("status") or "").strip() or "—"
            nid = str(init.get("id") or "").strip() or "—"
            if gaps:
                sub.append(
                    f"• {title} [ID: {nid}] (Status: {st}) — missing: {', '.join(gaps)}{_peer_note}"
                )
            else:
                sub.append(
                    f"• {title} [ID: {nid}] (Status: {st}) — brief present{_peer_note}"
                )
            if sum(len(x) + 1 for x in sub) > char_budget * 0.35:
                sub.append("• … (more initiatives omitted for length)")
                break
        parts.append("\n".join(sub))

    if not parts:
        return None

    body = "\n\n".join(parts)
    if len(body) > max_chars:
        body = body[: max_chars - 20] + "\n… (truncated)"
    return f"{VE_WORKING_SET_MARKER}\n{body}"


RECENT_CONVERSATION_HEADER = "Recent conversation:"


def slim_conversation_history_to_last_user_only(
    merged: str,
    *,
    fallback_user_question: str,
) -> str:
    """
    For priority-resolution turns: **clean slate** — the model must not see prior Agent echoes (pattern loop).

    If ``fallback_user_question`` is non-empty, the thread is **only** that current turn:
    ``Recent conversation:\\n\\nUser: {that question}`` — not the last block copied from a long thread
    (avoids stale or duplicate user lines). Prefix lines before ``Recent conversation:`` (e.g. Folder) are kept.

    If there is no current question string, fall back to the last ``User:`` block in the merged text.
    """
    t = (merged or "").strip()
    q = (fallback_user_question or "").strip()
    low = RECENT_CONVERSATION_HEADER.lower()
    idx = t.lower().find(low)
    before = t[:idx].rstrip() if idx >= 0 else ""

    if q:
        thread_out = f"{RECENT_CONVERSATION_HEADER}\n\nUser: {q}"
        if before:
            return f"{before}\n\n{thread_out}"
        return thread_out

    if idx < 0:
        blocks = [b.strip() for b in re.split(r"\n{2,}", t) if b.strip()]
        user_blocks = [b for b in blocks if re.match(r"(?is)^User:\s*", b)]
        if user_blocks:
            return f"{RECENT_CONVERSATION_HEADER}\n\n{user_blocks[-1]}"
        return t

    after = t[idx + len(low) :].lstrip(" \n:：")
    blocks = [b.strip() for b in re.split(r"\n{2,}", after) if b.strip()]
    user_blocks = [b for b in blocks if re.match(r"(?is)^User:\s*", b)]
    if not user_blocks:
        return t
    last_u = user_blocks[-1]
    thread_out = f"{RECENT_CONVERSATION_HEADER}\n\n{last_u}"
    if before:
        return f"{before}\n\n{thread_out}"
    return thread_out


def truncate_scoped_digression_background(text: str | None, *, max_turns: int = 2) -> str:
    """
    Keep only the last ``max_turns`` conversation segments (User:/Assistant: blocks separated by blank lines).
    Each segment is typically one role line; 2 turns ≈ last 4 segments when alternating.
    """
    t = (text or "").strip()
    if not t:
        return ""
    segments = [s.strip() for s in re.split(r"\n{2,}", t) if s.strip()]
    keep = max(1, max_turns) * 2
    if len(segments) <= keep:
        return "\n\n".join(segments)
    return "\n\n".join(segments[-keep:])


def format_scoped_digression_guardrail_note() -> str:
    """Injected into enriched context for intentional sub-threads (inventory-like discipline)."""
    return (
        "SCOPED DIGRESSION (guardrails):\n"
        "- You are in a **narrow sub-thread** focused on the PRIMARY entity only.\n"
        "- **Name the work** using the **Title** (and type) from PRIMARY CONTEXT — **do not** echo raw UUIDs or generic "
        "“Entity abc123…” labels in user-facing prose when PRIMARY gives a real title.\n"
        "- **Do not** propose creating **new peer** tasks, ideas, or initiatives here; return to the main thread for that.\n"
        "- You **may** edit fields on the PRIMARY object (notes, description, completion criteria, etc.) per user intent.\n"
        "- Treat BACKGROUND lines as **context only** — PRIMARY is authoritative for what to edit."
    )


def build_enriched_council_context(
    preflight: CouncilPreflight,
    *,
    legacy_context_str: str | None,
    subject_ref: dict[str, Any] | None,
    object_snapshot: dict[str, Any] | None,
    resonance_user_id: str | None = None,
    aspiration_user_id: str | None = None,
    question_kind: str | None = None,
) -> str:
    """
    Single string passed to build_council_decision_packet as `context`.
    Order: PRIMARY (when present and legitimate) → runtime → workflow/thread.
    Vague questions without grounding signals omit authoritative PRIMARY; see CONTEXT NOTE.
    SYSTEM FAILURE STATE lives only in the instruction layer (see zenaf_tools), not here.
    When ``scoped_digression`` is True: BACKGROUND (optional) → PRIMARY → slim runtime + guardrails;
    Vision Execution working set, aspiration, developmental guidance, and full thread merge are omitted.

    When ``question_kind`` is ``\"priority_resolution\"`` (or classifies as such from ``user_question``) and not scoped,
    **no** merged thread / ``Recent conversation`` block is appended (**zero** prior messages) — the model must rely on
    trunk + PRIMARY + runtime; the live user message is still supplied separately in the seat prompt.
    """
    from local_ai.conversation_trunk import classify_question_kind

    ve_uid_early = (resonance_user_id or aspiration_user_id or "").strip() or None
    if ve_uid_early:
        _hydrate_preflight_ve_focus_from_storage(preflight, ve_uid_early, user_question=preflight.user_question)

    blocks: list[str] = []
    scoped = bool(getattr(preflight, "scoped_digression", False))
    uq = (preflight.user_question or "").strip()
    effective_qk = (question_kind or "").strip() or classify_question_kind(uq)
    dbg = _s(getattr(preflight, "digression_background_block", None))
    if scoped and dbg:
        dbg_trim = truncate_scoped_digression_background(dbg, max_turns=2)[:8000]
        blocks.append(f"{SCOPED_DIGRESSION_BACKGROUND_MARKER}\n{dbg_trim}")

    primary_candidate = _format_ve_focus_block(preflight)
    if primary_candidate:
        if scoped:
            use_authoritative = True
        else:
            use_authoritative, _ = should_treat_primary_as_authoritative(
                preflight,
                subject_ref,
                object_snapshot,
                question_kind=effective_qk,
            )
        if use_authoritative:
            blocks.append(primary_candidate)
        else:
            blocks.append(_context_legitimacy_note(preflight))

    if (
        ve_uid_early
        and effective_qk in ("state_inventory", "missing_fields")
        and not scoped
    ):
        vf_inv = preflight.ve_focus if isinstance(preflight.ve_focus, dict) else None
        et_inv = (_s(vf_inv.get("entity_type")) if vf_inv else "").strip().lower()
        eid_inv = _s(vf_inv.get("entity_id")) if vf_inv else None
        if et_inv == "initiative" and eid_inv:
            try:
                from local_ai.vision_execution import storage as ve_storage
                from local_ai.vision_execution.initiative_completeness import (
                    build_initiative_completeness_block,
                )

                row = ve_storage.get_initiative(eid_inv, ve_uid_early)
                if row:
                    n_steps = ve_storage.count_execution_steps("initiative", eid_inv, ve_uid_early)
                    blocks.append(
                        build_initiative_completeness_block(
                            row,
                            user_id=ve_uid_early,
                            execution_step_count=n_steps,
                        )
                    )
            except Exception:
                pass

    runtime_lines: list[str] = []
    if preflight.active_surface:
        runtime_lines.append(f"Active surface: {preflight.active_surface}")
    if preflight.breadcrumb:
        runtime_lines.append(f"App context: {preflight.breadcrumb}")
    if preflight.view_label:
        runtime_lines.append(f"Current topic / focus: {preflight.view_label}")
    if preflight.workspace_mode_label:
        runtime_lines.append(f"Workspace mode (last run): {preflight.workspace_mode_label}")
    if preflight.topic_summary:
        runtime_lines.append(f"Topic summary: {preflight.topic_summary}")
    if preflight.folder_path:
        raw_prev = (preflight.raw_context_block or "")
        if preflight.folder_path not in raw_prev:
            runtime_lines.append(f"Folder: {preflight.folder_path}")

    if subject_ref and isinstance(subject_ref, dict):
        st = _s(subject_ref.get("title"))
        et = _s(subject_ref.get("entity_type"))
        sid = _s(subject_ref.get("entity_id"))
        sm = _s(subject_ref.get("summary"))
        if st or et or sid:
            bits = []
            if et:
                bits.append(et)
            if st:
                bits.append(st)
            line = "Subject under review: " + " — ".join(bits)
            if sid:
                line += f" (id: {sid})"
            runtime_lines.append(line)
        if sm and sm not in (legacy_context_str or ""):
            runtime_lines.append(f"Subject notes: {sm[:500]}")

    if object_snapshot and isinstance(object_snapshot, dict):
        ot = _s(object_snapshot.get("title"))
        ost = _s(object_snapshot.get("status"))
        if ot:
            runtime_lines.append(f"Object snapshot: {ot}" + (f" — status: {ost}" if ost else ""))

    if runtime_lines:
        blocks.append("Runtime context (from app):\n" + "\n".join(runtime_lines))

    if scoped:
        blocks.append(format_scoped_digression_guardrail_note())

    ve_uid = ve_uid_early
    if ve_uid and not scoped:
        if effective_qk in ("state_inventory", "missing_fields"):
            ve_scoped = format_ve_working_set_scoped_inventory_block(
                ve_uid,
                preflight.user_question or "",
                preflight,
            )
            if ve_scoped:
                blocks.append(ve_scoped)
            else:
                ve_snap = format_ve_working_set_snapshot_block(ve_uid)
                if ve_snap:
                    blocks.append(ve_snap)
        else:
            ve_snap = format_ve_working_set_snapshot_block(ve_uid)
            if ve_snap:
                blocks.append(ve_snap)

    dev_guidance = preflight.developmental_guidance
    if resonance_user_id:
        dev_guidance = attach_resonance_escalation_to_developmental_guidance(
            dev_guidance, resonance_user_id
        )
    if dev_guidance and not scoped:
        dev_block = format_developmental_guidance_packet_block(dev_guidance)
        if dev_block:
            blocks.append(dev_block)

    aid = (aspiration_user_id or "").strip()
    if aid and not scoped:
        from local_ai.aspiration_layer import format_aspiration_augmentation_block

        asp_block, _exp = format_aspiration_augmentation_block(
            aid,
            preflight=preflight,
            explicit_guidance_request=bool(getattr(preflight, "explicit_guidance_request", False)),
        )
        if asp_block:
            blocks.append(asp_block)

    base = (legacy_context_str or "").strip()
    raw = (preflight.raw_context_block or "").strip()
    merged_workflow = raw if raw else base
    # Priority: selective amnesia — omit entire thread so the model cannot echo broken backtick templates.
    if merged_workflow and not scoped and effective_qk != "priority_resolution":
        blocks.append(merged_workflow)

    out = "\n\n".join(blocks).strip()
    try:
        _LAST_ENRICHED_PACKET_LOG.write_text(out, encoding="utf-8")
    except OSError:
        pass
    return out


def split_enriched_council_context_for_seats(enriched: str | None) -> tuple[str | None, str]:
    """
    Split enriched council context for seat prompt assembly.

    Returns (primary_block, secondary_block):
    - primary_block: PRIMARY CONTEXT (authoritative) section only, or None if absent.
    - secondary_block: runtime + workflow/thread content (everything after PRIMARY), may be empty.
    """
    if not enriched or not enriched.strip():
        return None, ""
    s = enriched.strip()
    p = s.find(PRIMARY_CONTEXT_MARKER)
    if p < 0:
        return None, s
    prefix = s[:p].strip()
    rest = s[p:]
    rt = rest.find("\n\nRuntime context")
    if rt >= 0:
        primary = rest[:rt].strip()
        secondary = rest[rt:].strip()
    else:
        primary = rest.strip()
        secondary = ""
    if prefix:
        secondary = "\n\n".join(x for x in (prefix, secondary) if x)
    return primary, secondary
