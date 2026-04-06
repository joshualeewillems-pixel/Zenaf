"""Precision integration: proposed vs committed VE writes."""
from __future__ import annotations

from unittest.mock import patch

from local_ai.integration_commit import (
    recover_pending_on_affirm_from_conversation_subject,
    extract_user_literal_for_pending_integration,
    assistant_has_nonempty_draft_value,
    assistant_uses_backtick_save_antipattern,
    build_integration_commit_sse_payload,
    build_ui_path_label,
    commit_precision,
    deterministic_commit_sse_extra_fields,
    deterministic_integration_ack_text,
    derive_integration_save_state,
    extract_draft_value_for_pending,
    infer_draft_value_from_context,
    raw_assistant_text_has_draft_value_open_tag,
    format_integration_save_state_trunk_overlay,
    format_last_integration_overlay,
    integration_event_requires_deterministic_ack,
    MISSING_DRAFT_VALUE_REPLY_NUDGE,
    prepare_pending_integration_payload,
    process_pending_integration,
    user_affirms_precision_commit,
    user_signals_execution_commit,
    infer_draft_value_from_execution_commit_reply,
    extract_assistant_quoted_proposal_for_text_field,
)


def test_extract_user_literal_for_brief_directive():
    q = (
        '"A collection of miscellaneous tasks that require attention but do not fit into other initiatives, '
        'allowing for flexible management of ancillary work." use this for the brief field'
    )
    v = extract_user_literal_for_pending_integration(q)
    assert v
    assert "miscellaneous tasks" in v
    assert "ancillary work" in v


def test_extract_user_literal_brief_directive_trailing_quote_only_no_opening_quote():
    """Users often paste prose then a single closing ``"`` before the directive."""
    q = (
        "A collection of miscellaneous tasks that require attention but do not fit into other initiatives, "
        'allowing for flexible management of ancillary work." use this for the brief field'
    )
    v = extract_user_literal_for_pending_integration(q)
    assert v
    assert "miscellaneous tasks" in v
    assert "ancillary work" in v
    assert not v.startswith('"')


def test_extract_user_literal_returns_none_without_directive():
    q = '"Some long quoted text that is not tied to a brief directive at all."'
    assert extract_user_literal_for_pending_integration(q) is None


def test_derive_save_state_proposed_includes_pending_value_as_recorded_text():
    st = derive_integration_save_state(
        integration_event=None,
        pending_integration={
            "integration_state": "proposed",
            "entity_type": "initiative",
            "entity_id": "x",
            "field": "brief",
            "field_label": "Brief",
            "entity_display_name": "junk drawer",
            "value": "hello brief body",
        },
        capture_target=None,
        last_integration_commit=None,
    )
    assert st["pending_confirm"] is True
    assert st["recorded_text"] == "hello brief body"


def test_assistant_has_nonempty_draft_rejects_backticks_even_with_tag():
    raw = "ok\n```\n```\n[DRAFT_VALUE: should be ignored when fences present]"
    assert assistant_uses_backtick_save_antipattern(raw)
    assert not assistant_has_nonempty_draft_value(raw)


def test_assistant_has_nonempty_accepts_plain_draft():
    assert assistant_has_nonempty_draft_value("[DRAFT_VALUE: discounted rate path]")


def test_assistant_uses_backtick_on_double_grave():
    assert assistant_uses_backtick_save_antipattern("I will save ``")
    assert not assistant_uses_backtick_save_antipattern("single backtick `inline` only")


def test_assistant_uses_backtick_on_quadruple_grave():
    assert assistant_uses_backtick_save_antipattern("empty `````\n")
    assert assistant_uses_backtick_save_antipattern("````")


def test_raw_assistant_text_has_draft_value_open_tag():
    assert raw_assistant_text_has_draft_value_open_tag("ok [DRAFT_VALUE: x]")
    assert raw_assistant_text_has_draft_value_open_tag("[draft_value: x]")
    assert not raw_assistant_text_has_draft_value_open_tag("no tag here")


def test_infer_draft_value_from_context_task_description_when_empty():
    with patch("local_ai.integration_commit.ve_storage.get_task") as m:
        m.return_value = {"id": "t1", "description": ""}
        out = infer_draft_value_from_context(
            entity_id="t1",
            entity_type="task",
            field="description",
            assistant_visible_text="Use OAuth and keep scope narrow.",
            user_id="u1",
        )
    assert out == "Use OAuth and keep scope narrow."


def test_infer_draft_value_from_context_none_when_description_exists():
    with patch("local_ai.integration_commit.ve_storage.get_task") as m:
        m.return_value = {"id": "t1", "description": "Already present"}
        out = infer_draft_value_from_context(
            entity_id="t1",
            entity_type="task",
            field="description",
            assistant_visible_text="new text",
            user_id="u1",
        )
    assert out is None


def test_missing_draft_nudge_is_user_safe():
    low = MISSING_DRAFT_VALUE_REPLY_NUDGE.lower()
    assert "draft_value" not in low
    assert "save" in low or "field" in low


def test_extract_draft_value_strips_tag_and_returns_inner():
    raw = 'Here is the save.\n[DRAFT_VALUE: direct input on design choices]\nSay yes to confirm.'
    vis, inner = extract_draft_value_for_pending(raw)
    assert "[DRAFT_VALUE" not in vis
    assert inner == "direct input on design choices"
    assert "direct input" in vis or "Say yes" in vis


def test_extract_draft_value_no_tag_returns_original():
    vis, inner = extract_draft_value_for_pending("No tag here.")
    assert vis == "No tag here."
    assert inner is None


def test_prepare_pending_integration_uses_proposed_value_override():
    pend, dis = prepare_pending_integration_payload(
        question="put that in completion criteria",
        capture_field="acceptance_criteria",
        capture_entity_label="Website",
        council_preflight_dict={
            "ve_focus": {"entity_id": "t1", "entity_type": "task"},
            "ve_focus_title": "Website",
        },
        merged_subject={"entity_id": "t1", "entity_type": "task", "entity_display_name": "Website"},
        proposed_value_override="User's exact phrase to store",
    )
    assert dis is None
    assert pend is not None
    assert pend["value"] == "User's exact phrase to store"


def test_recover_pending_on_affirm_from_conversation_subject():
    luc = (
        '"A collection of miscellaneous tasks that require attention but do not fit into other initiatives, '
        'allowing for flexible management of ancillary work." use this for the brief field'
    )
    ctx = {
        "conversation_subject": {
            "entity_id": "i1",
            "entity_type": "initiative",
            "entity_display_name": "junk drawer",
            "active_field": "brief",
            "last_user_contribution": luc,
            "confidence": "high",
        },
        "council_preflight": {
            "ve_focus": {"entity_id": "i1", "entity_type": "initiative"},
            "ve_focus_title": "junk drawer",
        },
    }
    got = recover_pending_on_affirm_from_conversation_subject(question="add it", context=ctx)
    assert got is not None
    assert got.get("integration_state") == "proposed"
    assert got.get("field") == "brief"
    assert "miscellaneous tasks" in str(got.get("value") or "")
    assert recover_pending_on_affirm_from_conversation_subject(question="maybe not", context=ctx) is None


def test_user_affirms_this_is_good_for_now():
    assert user_affirms_precision_commit("this is good for now")
    assert user_affirms_precision_commit("Yes, add it")
    assert user_affirms_precision_commit("confirm as is")
    assert user_affirms_precision_commit("leave as is")
    assert user_affirms_precision_commit("proceed with this update")
    assert user_affirms_precision_commit("please proceed")
    assert user_affirms_precision_commit("ok to add")
    assert user_affirms_precision_commit("proceed with this")
    assert user_affirms_precision_commit("proceed")
    assert not user_affirms_precision_commit("don't save yet")
    assert not user_affirms_precision_commit("")


def test_user_signals_execution_commit_phrases():
    assert user_signals_execution_commit("i like that go ahead and change it")
    assert user_signals_execution_commit("Go ahead and change it")
    assert user_signals_execution_commit("yes, change it")
    assert user_signals_execution_commit("yes, make the change")
    assert user_signals_execution_commit("go for it")
    assert user_signals_execution_commit("use that definition")
    assert user_signals_execution_commit("please apply that to the brief")
    assert not user_signals_execution_commit("what should we go ahead and do?")
    assert not user_signals_execution_commit("should we go ahead and change it?")
    assert not user_signals_execution_commit("don't go ahead and change it")


def test_extract_assistant_quoted_proposal_for_brief():
    raw = (
        'The **Title** is "Initiative · junk drawer." The current **Brief** is "todos\'." '
        'I will update the **Brief** to: "A collection of miscellaneous tasks that require attention '
        'but do not fit into other initiatives, allowing for flexible management of ancillary work." '
        "Shall I finalize this change?"
    )
    got = extract_assistant_quoted_proposal_for_text_field(
        assistant_raw=raw,
        entity_type="initiative",
        field_target="brief",
    )
    assert got
    assert "miscellaneous tasks" in got
    assert "ancillary work" in got


def test_extract_assistant_quoted_proposal_none_without_field_cue():
    raw = '"A collection of miscellaneous tasks that require attention."'
    assert (
        extract_assistant_quoted_proposal_for_text_field(
            assistant_raw=raw,
            entity_type="initiative",
            field_target="brief",
        )
        is None
    )


def test_infer_draft_from_execution_commit_quoted_proposal():
    raw = (
        'I propose revising the brief to: "A collection of miscellaneous tasks that require attention." '
        "Shall I proceed?"
    )
    got = infer_draft_value_from_execution_commit_reply(
        assistant_raw=raw,
        user_question="go for it",
        entity_type="initiative",
        field="brief",
    )
    assert got == "A collection of miscellaneous tasks that require attention."
    assert (
        infer_draft_value_from_execution_commit_reply(
            assistant_raw=raw,
            user_question="what do you think?",
            entity_type="initiative",
            field="brief",
        )
        is None
    )


def test_process_pending_skipped_when_new_precision_turn():
    pending = {
        "integration_state": "proposed",
        "entity_id": "e1",
        "entity_type": "idea",
        "field": "desired_outcome",
        "value": "Ship v1",
    }
    ev, suf = process_pending_integration(
        question="Actually the desired outcome is different — launch in Q3 instead.",
        pending=pending,
        user_id="u1",
        skip_commit_because_new_precision=True,
    )
    assert ev is None
    assert not suf


def test_process_pending_commits_on_affirm_even_when_skip_flag():
    """Affirmation + stored candidate must commit even if classify_question_kind hinted skip."""
    pending = {
        "integration_state": "proposed",
        "entity_id": "e1",
        "entity_type": "idea",
        "field": "desired_outcome",
        "value": "Ship v1",
    }
    with patch("local_ai.integration_commit.ve_storage.update_idea") as m:
        m.return_value = {"title": "My idea", "id": "e1", "desired_outcome": "Ship v1"}
        ev, suf = process_pending_integration(
            question="yes please",
            pending=pending,
            user_id="u1",
            skip_commit_because_new_precision=True,
        )
    assert ev is not None and ev.get("kind") == "committed_ok"
    m.assert_called_once()


def test_process_pending_still_skips_when_new_precision_without_affirmation():
    pending = {
        "integration_state": "proposed",
        "entity_id": "e1",
        "entity_type": "idea",
        "field": "desired_outcome",
        "value": "Ship v1",
    }
    ev, suf = process_pending_integration(
        question="The desired outcome is to launch in Q2 with full QA.",
        pending=pending,
        user_id="u1",
        skip_commit_because_new_precision=True,
    )
    assert ev is None
    assert not suf


def test_process_pending_commits_on_affirmation():
    pending = {
        "integration_state": "proposed",
        "entity_id": "e1",
        "entity_type": "idea",
        "field": "desired_outcome",
        "value": "Ship v1",
    }
    with patch("local_ai.integration_commit.ve_storage.update_idea") as m:
        m.return_value = {"title": "My idea", "id": "e1", "desired_outcome": "Ship v1"}
        ev, suf = process_pending_integration(
            question="sounds good",
            pending=pending,
            user_id="u1",
            skip_commit_because_new_precision=False,
        )
    assert ev is not None
    assert ev.get("kind") == "committed_ok"
    assert ev.get("recorded_text") == "Ship v1"
    assert ev.get("field") == "desired_outcome"
    assert "Intent / what this idea is trying to become" in (ev.get("field_label") or "")
    assert ev.get("verified_match") is True
    assert "My idea" in suf
    m.assert_called_once()


def test_process_pending_auth_required_without_user():
    pending = {
        "integration_state": "proposed",
        "entity_id": "e1",
        "entity_type": "idea",
        "field": "desired_outcome",
        "value": "x",
    }
    ev, suf = process_pending_integration(
        question="yes",
        pending=pending,
        user_id=None,
        skip_commit_because_new_precision=False,
    )
    assert ev.get("kind") == "auth_required"
    assert "not signed in" in suf.lower() or "Sign in" in suf


def test_format_last_integration_overlay():
    s = format_last_integration_overlay(
        {
            "ok": True,
            "entity_title": "Alpha",
            "entity_type": "idea",
            "entity_id": "i9",
            "field_label": "Intent / what this idea is trying to become",
            "ui_surface": "Vision & Execution → Ideas",
        }
    )
    assert "Alpha" in s
    assert "Intent / what this idea is trying to become" in s
    assert "desired_outcome" not in s
    assert "i9" in s


def test_commit_precision_idea_maps_desired_outcome():
    with patch("local_ai.integration_commit.ve_storage.update_idea") as m:
        m.return_value = {"title": "T", "id": "id1", "desired_outcome": "goal text"}
        r = commit_precision("id1", "idea", "desired_outcome", "  goal text  ", user_id="u1")
    assert r["ok"] is True
    assert r["entity_type"] == "idea"
    assert r["field"] == "desired_outcome"
    assert r["field_label"] == "Intent / what this idea is trying to become"
    assert r.get("verified_match") is True
    call = m.call_args
    assert call[0][0] == "id1"
    assert call[0][2] == "u1"
    patch_obj = call[0][1]
    assert getattr(patch_obj, "desired_outcome", None) == "goal text"


def test_build_ui_path_label():
    s = build_ui_path_label(
        "idea",
        "Finalize Website Approach",
        ui_field_label="Intent / what this idea is trying to become",
    )
    assert "Idea" in s
    assert "Finalize Website Approach" in s
    assert "Intent / what this idea is trying to become" in s
    assert "desired_outcome" not in s


def test_derive_integration_save_state_committed():
    st = derive_integration_save_state(
        integration_event={
            "kind": "committed_ok",
            "ok": True,
            "entity_id": "e1",
            "entity_type": "idea",
            "field": "desired_outcome",
            "field_label": "Intent / what this idea is trying to become",
            "entity_title": "My idea",
            "recorded_text": "hello",
        },
        pending_integration=None,
        capture_target=None,
        last_integration_commit=None,
    )
    assert st["status"] == "committed"
    assert st["entity_display_name"] == "My idea"
    assert "SAVE STATE" in format_integration_save_state_trunk_overlay(st)


def test_derive_integration_save_state_pending_is_candidate():
    st = derive_integration_save_state(
        integration_event=None,
        pending_integration={
            "integration_state": "proposed",
            "entity_id": "e1",
            "entity_type": "idea",
            "field": "desired_outcome",
            "entity_display_name": "My idea",
            "value": "x",
        },
        capture_target=None,
        last_integration_commit=None,
    )
    assert st["status"] == "candidate_target"
    assert st["pending_confirm"] is True
    ov = format_integration_save_state_trunk_overlay(st)
    assert "not saved" in ov.lower()


def test_build_integration_commit_sse_payload():
    p = build_integration_commit_sse_payload(
        {
            "kind": "committed_ok",
            "entity_id": "e1",
            "entity_type": "idea",
            "entity_title": "T",
            "field": "desired_outcome",
            "field_label": "Intent / what this idea is trying to become",
            "recorded_text": "body",
        }
    )
    assert p is not None
    assert p["status"] == "committed"
    assert p["recorded_text"] == "body"
    assert "Idea" in (p.get("ui_path_label") or "")
    assert "desired_outcome" not in (p.get("ui_path_label") or "").lower()
    assert "Intent / what this idea is trying to become" in (p.get("ui_path_label") or "")


def test_integration_event_requires_deterministic_ack():
    assert not integration_event_requires_deterministic_ack(None)
    assert not integration_event_requires_deterministic_ack({})
    assert integration_event_requires_deterministic_ack({"kind": "committed_ok"})
    assert integration_event_requires_deterministic_ack({"kind": "auth_required"})
    assert integration_event_requires_deterministic_ack({"kind": "committed_failed"})


def test_deterministic_integration_ack_text():
    assert (
        deterministic_integration_ack_text(
            {
                "kind": "committed_ok",
                "entity_type": "idea",
                "entity_title": "Create a mailing list",
                "field_label": "Intent / what this idea is trying to become",
            }
        )
        == "Recorded → Idea → Intent / what this idea is trying to become"
    )
    assert deterministic_integration_ack_text({"kind": "auth_required"}).startswith("Sign in")
    assert "nothing was written" in deterministic_integration_ack_text(
        {"kind": "committed_failed", "message": "db down"}
    )


def test_deterministic_commit_sse_extra_fields_committed_ok():
    extra = deterministic_commit_sse_extra_fields(
        {
            "kind": "committed_ok",
            "entity_id": "e1",
            "entity_type": "idea",
            "entity_title": "T",
            "field": "desired_outcome",
            "field_label": "Intent / what this idea is trying to become",
            "recorded_text": "x",
        }
    )
    assert extra.get("synthesis_type") == "conversational_partner"
    assert extra.get("pending_integration") is None
    assert extra.get("integration_commit") is not None
    assert extra.get("last_integration_commit") is not None


def test_commit_precision_task_maps_desired_outcome_to_description():
    with patch("local_ai.integration_commit.ve_storage.update_task") as m:
        m.return_value = {"title": "Design flow", "id": "t1", "description": "hello"}
        r = commit_precision("t1", "task", "desired_outcome", "hello", user_id="u1")
    assert r["ok"] is True
    assert r["field"] == "description"
    assert r["field_label"] == "Description"
    assert r.get("verified_match") is True
    patch_obj = m.call_args[0][1]
    assert getattr(patch_obj, "description", None) == "hello"


def test_commit_precision_field_unresolved():
    r = commit_precision("t1", "task", "not_a_real_token_qqq", "v", user_id="u1")
    assert r["ok"] is False
    assert r.get("error") == "field_unresolved"


def test_prepare_pending_normalizes_task_field():
    pend, dis = prepare_pending_integration_payload(
        question="some text",
        capture_field="desired_outcome",
        capture_entity_label="Design flow",
        council_preflight_dict={
            "ve_focus": {"entity_id": "t1", "entity_type": "task"},
            "ve_focus_title": "Design flow",
        },
        merged_subject={"entity_id": "t1", "entity_type": "task", "entity_display_name": "Design flow"},
    )
    assert dis is None
    assert pend is not None
    assert pend["field"] == "description"
    assert pend["field_label"] == "Description"
    assert "desired_outcome" not in pend["field"]


def test_prepare_pending_unknown_field_returns_disambiguation():
    pend, dis = prepare_pending_integration_payload(
        question="x",
        capture_field="not_a_real_trunk_field_xyz",
        capture_entity_label="Task A",
        council_preflight_dict={
            "ve_focus": {"entity_id": "t1", "entity_type": "task"},
            "ve_focus_title": "Task A",
        },
        merged_subject={"entity_id": "t1", "entity_type": "task", "entity_display_name": "Task A"},
    )
    assert pend is None
    assert dis is not None
    assert "Description" in dis
    assert "Notes" in dis
    assert "don't have a clear field" in dis.lower()


def test_prepare_pending_initiative_unknown_token_disambiguates_not_notes():
    pend, dis = prepare_pending_integration_payload(
        question="some text",
        capture_field="unknown",
        capture_entity_label="junk drawer",
        council_preflight_dict={
            "ve_focus": {"entity_id": "in1", "entity_type": "initiative"},
            "ve_focus_title": "junk drawer",
        },
        merged_subject={"entity_id": "in1", "entity_type": "initiative", "entity_display_name": "junk drawer"},
    )
    assert pend is None
    assert dis is not None
    assert "Brief" in dis
    assert "Diagnostics / admin notes" in dis


def test_prepare_pending_initiative_description_maps_to_brief():
    pend, dis = prepare_pending_integration_payload(
        question="updated brief body",
        capture_field="description",
        capture_entity_label="junk drawer",
        council_preflight_dict={
            "ve_focus": {"entity_id": "in1", "entity_type": "initiative"},
            "ve_focus_title": "junk drawer",
        },
        merged_subject={"entity_id": "in1", "entity_type": "initiative", "entity_display_name": "junk drawer"},
    )
    assert dis is None
    assert pend is not None
    assert pend["field"] == "brief"
    assert pend["field_label"] == "Brief"


def test_deterministic_commit_sse_includes_digression_summary_when_scoped():
    event = {
        "kind": "committed_ok",
        "entity_type": "task",
        "entity_id": "e1",
        "entity_title": "My task",
        "field_label": "Completion criteria",
    }
    out = deterministic_commit_sse_extra_fields(
        event,
        request_context={"is_scoped_digression": True},
    )
    assert out.get("digression_summary")
    assert "My task" in str(out["digression_summary"])
    assert "Completion criteria" in str(out["digression_summary"])


def test_deterministic_commit_sse_omits_digression_summary_when_not_scoped():
    event = {
        "kind": "committed_ok",
        "entity_type": "task",
        "entity_id": "e1",
        "entity_title": "My task",
        "field_label": "Completion criteria",
    }
    out = deterministic_commit_sse_extra_fields(event, request_context=None)
    assert "digression_summary" not in out
