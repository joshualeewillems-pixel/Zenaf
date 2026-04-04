"""
Precision integration: commit capture-target text into Vision & Execution storage.

Client echoes ``pending_integration`` (proposed) on the next turn; on affirmation we call
``commit_precision`` and inject authoritative overlay + trunk context. No new DB layer.

User-visible field names come only from ``ve_integration_schema``; trunk tokens are internal.
"""
from __future__ import annotations

import re
from typing import Any, Literal, Mapping

from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as ve_storage
from local_ai.vision_execution.ve_integration_schema import (
    entity_type_ui_heading,
    field_disambiguation_user_message,
    normalize_trunk_token_to_storage_key,
    ui_label_for_storage_key,
)

IntegrationState = Literal["proposed", "committed"]

# Zenaf whispers exact save text here; stripped from user-visible reply, used as pending_integration.value.
_DRAFT_VALUE_RE = re.compile(r"\[(?:DRAFT_VALUE):\s*([^\]]+)\]", re.IGNORECASE)


def extract_draft_value_for_pending(assistant_text: str) -> tuple[str, str | None]:
    """
    Remove every ``[DRAFT_VALUE: ...]`` tag from assistant output; return (visible_text, first_payload_or_none).
    Payload cannot contain ``]``; keep tags short and literal.
    """
    t = (assistant_text or "").strip()
    if not t:
        return t, None
    found = [m.strip() for m in _DRAFT_VALUE_RE.findall(t) if m.strip()]
    visible = _DRAFT_VALUE_RE.sub("", t)
    visible = re.sub(r"\n{3,}", "\n\n", visible).strip()
    if not found:
        return visible, None
    return visible, found[0]


def infer_draft_value_from_context(
    *,
    entity_id: str,
    entity_type: str,
    field: str,
    assistant_visible_text: str,
    user_id: str | None,
) -> str | None:
    """
    Direct-injection fallback for missing ``[DRAFT_VALUE]``.

    Current policy is intentionally narrow: task description only, and only when the current
    description is blank. If those gates pass, use the assistant summary text as draft payload.
    """
    uid = (user_id or "").strip()
    if not uid:
        return None
    et = (entity_type or "").strip().lower()
    eid = (entity_id or "").strip()
    if not eid or et != "task":
        return None
    storage_key = normalize_trunk_token_to_storage_key(et, field)
    if storage_key != "description":
        return None
    row = ve_storage.get_task(eid, uid)
    if not isinstance(row, dict):
        return None
    cur = str(row.get("description") or "").strip()
    if cur:
        return None
    text = re.sub(r"\s+", " ", str(assistant_visible_text or "")).strip()
    if not text:
        return None
    return text[:12000]


def raw_assistant_text_has_draft_value_open_tag(raw: str) -> bool:
    """True if the model output contains an opening ``[DRAFT_VALUE:`` (case-insensitive)."""
    return "[draft_value:" in (raw or "").lower()


def assistant_uses_backtick_save_antipattern(raw: str) -> bool:
    """
    True if the model used Markdown code fences / empty-code patterns instead of ``[DRAFT_VALUE: …]``.
    Includes quadruple grave (````) and longer runs — treat as **failed** save channel so the nudge can fire.
    """
    t = raw or ""
    if "````" in t:
        return True
    if "```" in t:
        return True
    if "``" in t:
        return True
    return False


def assistant_has_nonempty_draft_value(raw: str) -> bool:
    """True if assistant text has a real ``[DRAFT_VALUE:`` payload — not backtick placeholders."""
    if assistant_uses_backtick_save_antipattern(raw):
        return False
    for inner in _DRAFT_VALUE_RE.findall(raw or ""):
        if inner.strip():
            return True
    return False


# Appended to Zenaf reply when a save-eligible turn cannot queue a pending write (no valid tag / payload).
MISSING_DRAFT_VALUE_REPLY_NUDGE = (
    "\n\nThanks for your patience — I wasn’t able to queue a save from that reply. "
    "A `[DRAFT_VALUE: …]` tag with the **exact** text to store is **required** (triple-backtick code fences and empty "
    "grave-accent blocks **do not** count). Please send your request again and I’ll include that tag."
)




_AFFIRM_RE = re.compile(
    r"(?:"
    r"\b("
    r"yes|yeah|yep|yup|sure|ok(ay)?|go ahead|do it|please do|save it|lock it in|ship it|"
    r"confirm(ed)?|approved?|sounds good|looks good|that'?s good|this is good|good for now|"
    r"that works|all set|we'?re good|record it|add it|go for it|correct|exactly|precisely|spot on|"
    r"that'?s right|that is right|perfect|please add|works for me"
    r")\b"
    r"|just like that(?:\s*[!.])?"
    r")",
    re.I,
)
_DENY_RE = re.compile(
    r"\b(don'?t|do not|wait|hold on|not yet|cancel|stop|nope|no thanks|not now)\b",
    re.I,
)


def user_affirms_precision_commit(question: str) -> bool:
    q = (question or "").strip()
    if len(q) < 1:
        return False
    q = q.rstrip(".,!?;:…").strip()
    if len(q) < 1:
        return False
    low = q.lower()
    if _DENY_RE.search(low):
        return False
    if _AFFIRM_RE.search(low):
        return True
    if low in ("y", "k", "👍"):
        return True
    return False


def _storage_key_to_idea_update(storage_key: str, value: str) -> M.IdeaUpdate | None:
    v = (value or "").strip()
    if not v:
        return None
    sk = (storage_key or "").strip().lower()
    if sk == "desired_outcome":
        return M.IdeaUpdate(desired_outcome=v)
    if sk == "summary":
        return M.IdeaUpdate(summary=v)
    if sk == "description":
        return M.IdeaUpdate(description=v)
    if sk == "notes":
        return M.IdeaUpdate(notes=v)
    if sk == "title":
        return M.IdeaUpdate(title=v)
    return None


def _storage_key_to_initiative_update(storage_key: str, value: str) -> M.InitiativeUpdate | None:
    v = (value or "").strip()
    if not v:
        return None
    sk = (storage_key or "").strip().lower()
    if sk == "brief":
        return M.InitiativeUpdate(brief=v)
    if sk == "next_step_ai":
        return M.InitiativeUpdate(next_step_ai=v)
    if sk == "notes":
        return M.InitiativeUpdate(notes=v)
    if sk == "title":
        return M.InitiativeUpdate(title=v)
    return None


def _storage_key_to_project_update(storage_key: str, value: str) -> M.ProjectUpdate | None:
    v = (value or "").strip()
    if not v:
        return None
    sk = (storage_key or "").strip().lower()
    if sk == "brief":
        return M.ProjectUpdate(brief=v)
    if sk == "next_step_ai":
        return M.ProjectUpdate(next_step_ai=v)
    if sk == "notes":
        return M.ProjectUpdate(notes=v)
    if sk == "title":
        return M.ProjectUpdate(title=v)
    return None


def _storage_key_to_task_update(storage_key: str, value: str) -> M.TaskUpdate | None:
    v = (value or "").strip()
    if not v:
        return None
    sk = (storage_key or "").strip().lower()
    if sk == "description":
        return M.TaskUpdate(description=v)
    if sk == "completion_criteria":
        return M.TaskUpdate(completion_criteria=v)
    if sk == "notes":
        return M.TaskUpdate(notes=v)
    if sk == "title":
        return M.TaskUpdate(title=v)
    return None


def _patch_for_entity(entity_type: str, storage_key: str, value: str) -> Any | None:
    et = (entity_type or "").strip().lower()
    if et == "idea":
        return _storage_key_to_idea_update(storage_key, value)
    if et == "initiative":
        return _storage_key_to_initiative_update(storage_key, value)
    if et == "project":
        return _storage_key_to_project_update(storage_key, value)
    if et == "task":
        return _storage_key_to_task_update(storage_key, value)
    return None


def _read_back_value(entity_type: str, row: dict[str, Any], storage_key: str) -> str:
    sk = (storage_key or "").strip().lower()
    v = row.get(sk)
    return str(v if v is not None else "").strip()


def commit_precision(
    entity_id: str,
    entity_type: str,
    field: str,
    value: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    """
    Persist captured field text to the user's VE row. Returns a JSON-serializable result dict.

    ``field`` may be a trunk token or canonical storage key; it is normalized via the integration schema.
    ``field`` in the result is always the canonical storage key; ``field_label`` is the schema UI label.
    """
    eid = (entity_id or "").strip()
    uid = (user_id or "").strip()
    if not eid or not uid:
        return {"ok": False, "error": "missing_entity_or_user"}
    et = (entity_type or "").strip().lower()
    S = ve_storage

    storage_key = normalize_trunk_token_to_storage_key(et, field)
    if not storage_key:
        return {
            "ok": False,
            "error": "field_unresolved",
            "field": (field or "").strip(),
            "entity_id": eid,
            "entity_type": et,
        }

    ui_label = ui_label_for_storage_key(et, storage_key)
    if not ui_label:
        return {
            "ok": False,
            "error": "unsupported_storage_field",
            "field": storage_key,
            "entity_id": eid,
            "entity_type": et,
        }

    patch = _patch_for_entity(et, storage_key, value)
    if patch is None:
        return {"ok": False, "error": "unsupported_field_for_entity", "field": storage_key, "entity_type": et}

    dump = patch.model_dump(exclude_unset=True)
    if not dump:
        return {"ok": False, "error": "empty_patch", "field": storage_key, "entity_type": et}

    def _do_write() -> dict[str, Any] | None:
        if et == "idea":
            return S.update_idea(eid, patch, uid)  # type: ignore[arg-type]
        if et == "initiative":
            return S.update_initiative(eid, patch, uid)  # type: ignore[arg-type]
        if et == "project":
            return S.update_project(eid, patch, uid)  # type: ignore[arg-type]
        if et == "task":
            return S.update_task(eid, patch, uid)  # type: ignore[arg-type]
        return None

    out = _do_write()
    if out is None:
        err = (
            "idea_not_found"
            if et == "idea"
            else "initiative_not_found"
            if et == "initiative"
            else "project_not_found"
            if et == "project"
            else "task_not_found"
            if et == "task"
            else "entity_not_found"
        )
        return {"ok": False, "error": err, "entity_id": eid, "entity_type": et, "field": storage_key}

    primary_written = next(iter(dump.keys()))
    recorded = str(value or "").strip()
    verified_match = _read_back_value(et, out, primary_written) == recorded

    ui_surface = {
        "idea": "Vision & Execution → Ideas → open this idea",
        "initiative": "Vision & Execution → Initiatives → open this initiative",
        "project": "Vision & Execution → Projects → open this project",
        "task": "Vision & Execution → Tasks / project task list → open this task",
    }.get(et, "Vision & Execution")

    return {
        "ok": True,
        "write_applied": True,
        "verified_match": verified_match,
        "resolved_storage_field": storage_key,
        "entity_id": eid,
        "entity_type": et,
        "field": storage_key,
        "field_label": ui_label,
        "entity_title": (out.get("title") or "")[:200],
        "ui_surface": ui_surface,
    }


def format_committed_authoritative_overlay(result: dict[str, Any]) -> str:
    """Inject after PRIMARY so the model may state the save factually."""
    if not result.get("ok"):
        return ""
    title = (result.get("entity_title") or "item").strip() or "item"
    fl = (result.get("field_label") or "").strip() or "field"
    ui = (result.get("ui_surface") or "Vision & Execution").strip()
    return (
        "\n\n**INTEGRATION COMMITTED (authoritative — already written to your database this request):**\n"
        f"- Entity: **{title}** (`{result.get('entity_type')}` id `{result.get('entity_id')}`)\n"
        f"- Field updated: **{fl}**\n"
        f"- Where to find it: {ui}\n"
        "- You **may** confirm this in plain language; **do not** imply it is still only proposed.\n"
    )


def format_last_integration_overlay(last: dict[str, Any] | None) -> str:
    """When user asks “where does this live?”, client echoes ``last_integration_commit``."""
    if not last or not last.get("ok"):
        return ""
    title = (last.get("entity_title") or "item").strip() or "item"
    fl = (last.get("field_label") or "field").strip()
    ui = (last.get("ui_surface") or "Vision & Execution").strip()
    path = build_ui_path_label(str(last.get("entity_type") or ""), title, ui_field_label=fl)
    return (
        "\n\n**LAST INTEGRATION (authoritative — use for “where is this?”):**\n"
        f"- Entity: **{title}** (`{last.get('entity_type')}` id `{last.get('entity_id')}`)\n"
        f"- Field: **{fl}**\n"
        f"- Path: `{path}`\n"
        f"- Where to find it in the app: {ui}\n"
    )


def prepare_pending_integration_payload(
    *,
    question: str,
    capture_field: str,
    capture_entity_label: str | None,
    council_preflight_dict: dict[str, Any] | None,
    merged_subject: dict[str, Any] | None,
    proposed_value_override: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Build client-echo payload (proposed) or return disambiguation text.

    Returns ``(pending_dict, None)``, ``(None, None)`` if entity unknown, or ``(None, disambiguation_message)``
    when the entity is known but the field token does not resolve.
    """
    from local_ai.council_preflight import parse_preflight_from_request

    ctx: dict[str, Any] | None = None
    if isinstance(council_preflight_dict, dict) and council_preflight_dict:
        ctx = {"council_preflight": council_preflight_dict}
    pf = parse_preflight_from_request(ctx, question or "")
    vf = pf.ve_focus if isinstance(pf.ve_focus, dict) else None
    eid = str(vf["entity_id"]).strip() if vf and vf.get("entity_id") else None
    et = str(vf["entity_type"]).strip().lower() if vf and vf.get("entity_type") else None
    if merged_subject:
        if merged_subject.get("entity_id"):
            eid = str(merged_subject["entity_id"]).strip()
        if merged_subject.get("entity_type"):
            et = str(merged_subject["entity_type"]).strip().lower()
    if not eid or not et:
        return None, None

    disp = (
        capture_entity_label
        or (merged_subject or {}).get("entity_display_name")
        or pf.ve_focus_title
        or ""
    )
    name = str(disp).strip()[:500] if disp else ""

    sk = normalize_trunk_token_to_storage_key(et, capture_field)
    if not sk:
        return None, field_disambiguation_user_message(et, name or "this item")

    ui = ui_label_for_storage_key(et, sk)
    if not ui:
        return None, field_disambiguation_user_message(et, name or "this item")

    ov = (proposed_value_override or "").strip()
    stored_value = (ov if ov else (question or "").strip())[:12000]

    return (
        {
            "integration_state": "proposed",
            "entity_id": eid,
            "entity_type": et,
            "field": sk,
            "field_label": ui,
            "value": stored_value,
            "entity_display_name": name,
        },
        None,
    )


def build_pending_integration_payload(
    *,
    question: str,
    capture_field: str,
    capture_entity_label: str | None,
    council_preflight_dict: dict[str, Any] | None,
    merged_subject: dict[str, Any] | None,
    proposed_value_override: str | None = None,
) -> dict[str, Any] | None:
    """Backward-compatible: proposed payload only (no disambiguation)."""
    p, _ = prepare_pending_integration_payload(
        question=question,
        capture_field=capture_field,
        capture_entity_label=capture_entity_label,
        council_preflight_dict=council_preflight_dict,
        merged_subject=merged_subject,
        proposed_value_override=proposed_value_override,
    )
    return p


def process_pending_integration(
    *,
    question: str,
    pending: dict[str, Any] | None,
    user_id: str | None,
    skip_commit_because_new_precision: bool,
) -> tuple[dict[str, Any] | None, str]:
    """
    If the user affirms a prior proposed integration, commit and return (event, packet_suffix).

    ``integration_event`` is passed to trunk instructions; ``packet_suffix`` is factual overlay.

    **Deterministic path:** When a full proposal exists (``field`` + ``value``) and the user affirms,
    we always attempt commit — even if the caller heuristic set ``skip_commit_because_new_precision``.
    That flag is only for *non-affirming* new-precision turns so we do not overwrite the stored
    candidate with unrelated capture text.
    """
    proposed = isinstance(pending, dict) and pending.get("integration_state") == "proposed"
    field_ok = str(pending.get("field") or "").strip() if proposed else ""
    value_ok = str(pending.get("value") or "").strip() if proposed else ""
    affirms = user_affirms_precision_commit(question)
    force_commit = proposed and affirms and bool(field_ok) and bool(value_ok)

    if skip_commit_because_new_precision and not force_commit:
        return None, ""
    if not proposed:
        return None, ""
    if not affirms:
        return None, ""

    uid = (user_id or "").strip()
    if not uid:
        return (
            {
                "kind": "auth_required",
                "message": "Sign in to save changes to Vision & Execution.",
            },
            "\n\n**INTEGRATION (blocked):** User is not signed in — no row was written. "
            "Say they can sign in and try again; do **not** claim the save happened.\n",
        )

    raw_field = str(pending.get("field") or "")
    # Echoed from last proposal (often assistant DRAFT_VALUE); not the current affirmation line.
    res = commit_precision(
        str(pending.get("entity_id") or ""),
        str(pending.get("entity_type") or ""),
        raw_field,
        str(pending.get("value") or ""),
        user_id=uid,
    )
    if res.get("ok"):
        recorded = str(pending.get("value") or "").strip()
        ev: dict[str, Any] = {"kind": "committed_ok", **res, "recorded_text": recorded[:12000]}
        if res.get("verified_match") is False:
            ev["verification_warning"] = "read_after_write_mismatch"
        return (ev, format_committed_authoritative_overlay(res))
    return (
        {
            "kind": "committed_failed",
            "message": res.get("error") or "commit_failed",
            "detail": res,
        },
        "\n\n**INTEGRATION (failed):** The save did **not** complete. "
        f"Reason: {res.get('error', 'unknown')}. Do **not** say it was saved.\n",
    )


def serializable_commit_for_client(result: dict[str, Any]) -> dict[str, Any]:
    """Strip for SSE / POST echo (``last_integration_commit``)."""
    keys = (
        "ok",
        "error",
        "entity_id",
        "entity_type",
        "field",
        "field_label",
        "entity_title",
        "ui_surface",
        "write_applied",
        "verified_match",
        "resolved_storage_field",
        "recorded_text",
    )
    out = {k: result[k] for k in keys if k in result}
    rt = str(out.get("recorded_text") or "").strip()
    if rt:
        out["candidate_payload"] = rt[:12000]
    elif "candidate_payload" in result:
        out["candidate_payload"] = str(result.get("candidate_payload") or "")[:12000]
    rsf = str(out.get("resolved_storage_field") or "").strip()
    if rsf:
        out["resolved_field"] = rsf
    return out


def thinking_partner_meta_for_terminal_integration_event(
    integration_event_dict: dict[str, Any] | None,
    *,
    council_preflight_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Metadata merged into Thinking Partner ``run_meta`` when integration finished without an LLM."""
    meta: dict[str, Any] = {}
    if not isinstance(integration_event_dict, dict):
        return meta
    if integration_event_dict.get("kind") != "committed_ok":
        return meta
    _clean = {kk: vv for kk, vv in integration_event_dict.items() if kk != "kind"}
    meta["last_integration_commit"] = serializable_commit_for_client(_clean)
    _ic = build_integration_commit_sse_payload(integration_event_dict)
    if _ic:
        meta["integration_commit"] = _ic
    meta["pending_integration"] = None
    if isinstance(council_preflight_dict, dict) and council_preflight_dict.get("is_scoped_digression"):
        meta["digression_summary"] = build_digression_summary_line_for_committed_event(integration_event_dict)
    return meta


def build_ui_path_label(entity_type: str | None, entity_name: str, *, ui_field_label: str) -> str:
    et = entity_type_ui_heading(entity_type)
    name = (entity_name or "").strip() or "item"
    fl = (ui_field_label or "").strip() or "field"
    return f"{et} → {name} → {fl}"


def _field_label_human_for_entity_storage(entity_type: str, storage_key: str) -> str:
    ul = ui_label_for_storage_key((entity_type or "").strip().lower(), (storage_key or "").strip().lower())
    return ul or "this detail"


def _last_save_blurb(last: dict[str, Any] | None) -> str | None:
    if not isinstance(last, dict) or not last.get("ok"):
        return None
    title = (last.get("entity_title") or "item").strip() or "item"
    fl = (last.get("field_label") or "").strip() or "field"
    path = build_ui_path_label(str(last.get("entity_type") or ""), title, ui_field_label=fl)
    ui = (last.get("ui_surface") or "").strip()
    tail = f" Path: `{path}`." if path else ""
    tail2 = f" Where to find it: {ui}." if ui else ""
    return f"Last successful save in this thread: **{title}**, **{fl}**.{tail}{tail2}"


def derive_integration_save_state(
    *,
    integration_event: dict[str, Any] | None,
    pending_integration: dict[str, Any] | None,
    capture_target: Mapping[str, Any] | None,
    last_integration_commit: dict[str, Any] | None,
    conversation_entity_type: str | None = None,
) -> dict[str, Any]:
    """
    Derived persistence truth for trunk + status replies (no new storage).

    Returns: status, entity_display_name, entity_type, field_key, field_label_human,
    ui_path_label, recorded_text, pending_confirm, last_save_blurb.
    """
    ev = integration_event if isinstance(integration_event, dict) else None
    if ev and ev.get("kind") == "committed_ok":
        et = str(ev.get("entity_type") or "")
        title = (ev.get("entity_title") or ev.get("entity_display_name") or "").strip() or "item"
        fk = str(ev.get("field") or ev.get("resolved_storage_field") or "")
        fl = (ev.get("field_label") or "").strip() or _field_label_human_for_entity_storage(et, fk)
        return {
            "status": "committed",
            "entity_display_name": title,
            "entity_type": et,
            "field_key": fk,
            "field_label_human": fl,
            "ui_path_label": build_ui_path_label(et, title, ui_field_label=fl),
            "recorded_text": str(ev.get("recorded_text") or "").strip()[:12000],
            "pending_confirm": False,
            "last_save_blurb": None,
        }

    pend = pending_integration if isinstance(pending_integration, dict) else None
    if pend and pend.get("integration_state") == "proposed":
        et = str(pend.get("entity_type") or "")
        disp = (pend.get("entity_display_name") or pend.get("entity_title") or "").strip()
        title = disp or "this item"
        fk = str(pend.get("field") or "")
        fl = (pend.get("field_label") or "").strip() or _field_label_human_for_entity_storage(et, fk)
        return {
            "status": "candidate_target",
            "entity_display_name": title,
            "entity_type": et,
            "field_key": fk,
            "field_label_human": fl,
            "ui_path_label": build_ui_path_label(et, title, ui_field_label=fl),
            "recorded_text": "",
            "pending_confirm": True,
            "last_save_blurb": _last_save_blurb(last_integration_commit),
        }

    ct = capture_target if isinstance(capture_target, Mapping) else None
    conf = str(ct.get("capture_confidence") or "low") if ct else "low"
    ft = str(ct.get("field_target") or "unknown") if ct else "unknown"
    ent = (str(ct.get("entity_target") or "").strip() if ct else "") or ""
    et_hint = (conversation_entity_type or "").strip() or None

    if ct and conf in ("high", "medium") and (ent or ft != "unknown") and et_hint:
        title = ent or "this item"
        sk = normalize_trunk_token_to_storage_key(et_hint, ft)
        fl = ui_label_for_storage_key(et_hint, sk) if sk else None
        if not fl:
            fl = "this detail"
        fk = sk or ft
        return {
            "status": "candidate_target",
            "entity_display_name": title,
            "entity_type": et_hint or "",
            "field_key": fk,
            "field_label_human": fl,
            "ui_path_label": build_ui_path_label(et_hint, title, ui_field_label=fl),
            "recorded_text": "",
            "pending_confirm": False,
            "last_save_blurb": _last_save_blurb(last_integration_commit),
        }

    return {
        "status": "captured_only",
        "entity_display_name": "",
        "entity_type": "",
        "field_key": "",
        "field_label_human": "",
        "ui_path_label": "",
        "recorded_text": "",
        "pending_confirm": False,
        "last_save_blurb": _last_save_blurb(last_integration_commit),
    }


def format_integration_save_state_trunk_overlay(state: Mapping[str, Any]) -> str:
    """Authoritative SAVE STATE block for Zenaf trunk (all turns; especially integration_status)."""
    st = str(state.get("status") or "captured_only")
    title = (state.get("entity_display_name") or "").strip()
    fl = (state.get("field_label_human") or "").strip()
    ui_path = (state.get("ui_path_label") or "").strip()
    pending_confirm = bool(state.get("pending_confirm"))
    last_blurb = state.get("last_save_blurb")
    last_line = f"\n- {last_blurb}" if isinstance(last_blurb, str) and last_blurb.strip() else ""

    if st == "committed" and title and fl:
        return (
            "\n\n**SAVE STATE (authoritative — for “did you save?”, “where does this live?”, “what changed?”):**\n"
            f"- Status: **saved** (written to Vision & Execution this request).\n"
            f"- Target: **{fl}** on **{title}**.\n"
            + (f"- Path: `{ui_path}`.\n" if ui_path else "")
            + "- **First sentence** of the user-visible answer **must** state save status (yes + where); "
            "**no** decision-axis, coaching, or trade-offs.\n"
            + last_line
        )

    if st == "candidate_target" and title and fl:
        if pending_confirm:
            pref = (
                "- Status: **not saved yet** — a **proposed** write is waiting for an explicit yes.\n"
                f"- Would save to: **{fl}** for **{title}**.\n"
            )
        else:
            pref = (
                "- Status: **not saved** — only inferred target from context / thread (no write yet).\n"
                f"- Likely field: **{fl}** for **{title}**.\n"
            )
        return (
            "\n\n**SAVE STATE (authoritative — for persistence questions):**\n"
            + pref
            + (f"- Path if saved: `{ui_path}`.\n" if ui_path else "")
            + "- **Do not** say it was saved. For the preferred shape: if not pending_confirm, you may ask **one** short "
            "yes/no to save; if pending_confirm, tell them it saves when they confirm.\n"
            + last_line
        )

    base = (
        "\n\n**SAVE STATE (authoritative — for persistence questions):**\n"
        "- Status: **not saved** — text exists **only in this conversation** right now (no Vision & Execution write "
        "from this channel on this turn).\n"
        "- **Do not** imply a database update happened.\n"
    )
    return base + last_line


def integration_event_requires_deterministic_ack(event: dict[str, Any] | None) -> bool:
    """True when ``process_pending_integration`` produced a terminal outcome that must not pass through an LLM."""
    return isinstance(event, dict) and event.get("kind") in (
        "committed_ok",
        "auth_required",
        "committed_failed",
    )


def deterministic_integration_ack_text(event: dict[str, Any]) -> str:
    """Fixed user-visible line after server-side commit/auth/failure (council bypass path)."""
    if not isinstance(event, dict):
        return ""
    k = event.get("kind")
    if k == "committed_ok":
        et_h = entity_type_ui_heading(str(event.get("entity_type") or ""))
        fl = (event.get("field_label") or "").strip() or "that field"
        return f"Recorded → {et_h} → {fl}"
    if k == "auth_required":
        return "Sign in to save changes to Vision & Execution, then confirm again."
    if k == "committed_failed":
        msg = str(event.get("message") or "error").strip()
        return f"Save didn't complete — nothing was written ({msg})."
    return ""


def build_digression_summary_line_for_committed_event(event: dict[str, Any]) -> str:
    """Single user-visible / meta line after a successful scoped sub-thread commit."""
    et_h = entity_type_ui_heading(str(event.get("entity_type") or ""))
    fl = (event.get("field_label") or "").strip() or "a field"
    ttl = (event.get("entity_title") or "").strip() or "the focused item"
    return f'In the sub-thread for {et_h} "{ttl}", the user finalized **{fl}**.'


def _request_context_is_scoped_digression(ctx: dict[str, Any] | None) -> bool:
    if not isinstance(ctx, dict):
        return False
    if ctx.get("is_scoped_digression") is True or str(ctx.get("is_scoped_digression") or "").lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    cp = ctx.get("council_preflight")
    if isinstance(cp, dict):
        v = cp.get("is_scoped_digression")
        if v is True or str(v or "").lower() in ("1", "true", "yes"):
            return True
    return False


def deterministic_commit_sse_extra_fields(
    event: dict[str, Any],
    *,
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """SSE metadata alongside ``chunk``/``done`` for deterministic integration turns."""
    out: dict[str, Any] = {"synthesis_type": "conversational_partner"}
    k = event.get("kind")
    if k == "committed_ok":
        _clean = {kk: vv for kk, vv in event.items() if kk != "kind"}
        out["last_integration_commit"] = serializable_commit_for_client(_clean)
        _ic = build_integration_commit_sse_payload(event)
        if _ic:
            out["integration_commit"] = _ic
        out["pending_integration"] = None
        if _request_context_is_scoped_digression(request_context):
            out["digression_summary"] = build_digression_summary_line_for_committed_event(event)
    return out


def build_integration_commit_sse_payload(integration_event: dict[str, Any] | None) -> dict[str, Any] | None:
    """Structured SSE metadata when a VE write succeeded (Thinking Partner / council stream done)."""
    if not isinstance(integration_event, dict) or integration_event.get("kind") != "committed_ok":
        return None
    et = str(integration_event.get("entity_type") or "")
    eid = str(integration_event.get("entity_id") or "")
    title = (integration_event.get("entity_title") or integration_event.get("entity_display_name") or "").strip()
    fk = str(integration_event.get("field") or integration_event.get("resolved_storage_field") or "")
    fl = (integration_event.get("field_label") or "").strip() or _field_label_human_for_entity_storage(et, fk)
    rec = str(integration_event.get("recorded_text") or "").strip()
    ui = build_ui_path_label(et, title, ui_field_label=fl)
    out: dict[str, Any] = {
        "status": "committed",
        "entity_id": eid,
        "entity_type": et,
        "entity_display_name": title,
        "field": fk,
        "field_label": fl,
        "recorded_text": rec[:4000],
        "ui_path_label": ui,
    }
    vm = integration_event.get("verified_match")
    if vm is not None:
        out["verified_match"] = bool(vm)
    return out


def format_integration_trunk_mandate(event: dict[str, Any] | None) -> str:
    """
    Appended to Zenaf trunk when an integration event occurred this HTTP request
    (commit success/failure/auth), including on turns classified as reflective.
    """
    if not event or not isinstance(event, dict):
        return ""
    k = event.get("kind")
    if k == "committed_ok":
        title = (event.get("entity_title") or "the item").strip()
        fl = (event.get("field_label") or "field").strip()
        ui = (event.get("ui_surface") or "Vision & Execution").strip()
        return (
            "\n\n**THIS TURN — INTEGRATION RESULT (mandatory; overrides generic chat tone):**\n"
            "- A database **write already succeeded** this request.\n"
            f"- **MUST** reply in **≤2 short sentences** using **past or present tense** (e.g. “Added to **{fl}** for **{title}**.”).\n"
            f"- **MUST** tell them where to find it: **{ui}**.\n"
            "- **MUST NOT** say “I’ll record,” “I will add,” or ask them to confirm saving again for this same write.\n"
        )
    if k == "auth_required":
        return (
            "\n\n**THIS TURN — INTEGRATION RESULT (mandatory):**\n"
            "- **No row was written** — user is not signed in.\n"
            "- **MUST** say so plainly in ≤2 sentences; invite sign-in to enable saves.\n"
            "- **MUST NOT** claim the text was stored.\n"
        )
    if k == "committed_failed":
        return (
            "\n\n**THIS TURN — INTEGRATION RESULT (mandatory):**\n"
            f"- Save **failed** ({event.get('message', 'error')}).\n"
            "- **MUST NOT** claim success.\n"
        )
    return ""
