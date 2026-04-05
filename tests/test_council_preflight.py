"""Council preflight: enriched context (no run-level mode gate)."""

import local_ai.council_preflight as council_preflight_mod

from local_ai.council_preflight import (
    CONTEXT_LEGITIMACY_NOTE_MARKER,
    PRIMARY_CONTEXT_MARKER,
    SCOPED_DIGRESSION_BACKGROUND_MARKER,
    VE_WORKING_SET_MARKER,
    build_enriched_council_context,
    council_packet_has_primary_context,
    format_ve_working_set_snapshot_block,
    parse_preflight_from_request,
    question_has_explicit_grounding_cues,
    should_treat_primary_as_authoritative,
    split_enriched_council_context_for_seats,
    truncate_scoped_digression_background,
    slim_conversation_history_to_last_user_only,
    CouncilPreflight,
)


def test_parse_preflight_merges_council_preflight_dict():
    ctx = {
        "council_preflight": {
            "active_surface": "workspace",
            "workspace_topic_label": "MyFolder",
            "home_strip_label": "Radar Home",
            "ve_focus": {"entity_type": "task", "entity_id": "t1", "field_label": "Description"},
        },
        "context_block": "Mode: Analyze. Context: medical.",
    }
    p = parse_preflight_from_request(ctx, "Should we proceed?")
    assert p.active_surface == "workspace"
    assert p.view_label == "MyFolder"
    assert p.breadcrumb == "Radar Home"
    assert p.ve_focus is not None
    assert p.ve_focus.get("entity_id") == "t1"
    assert "Analyze" in (p.raw_context_block or "")


def test_parse_preflight_ingests_developmental_guidance():
    ctx = {
        "council_preflight": {
            "active_surface": "vision_map",
            "developmental_guidance": {
                "as_of": "2026-01-01T00:00:00Z",
                "evidence_refs": [{"source_type": "vision_map_triad", "source_id_or_key": "n1"}],
                "signals_summary": {"map_triad_water": 0.5},
                "hypotheses": [
                    {
                        "kind": "friction",
                        "statement": "Test hypothesis line",
                        "confidence": "high",
                        "basis": ["map_triad"],
                    }
                ],
                "suggested_guidance_style": "more_structure",
            },
        },
    }
    p = parse_preflight_from_request(ctx, "q")
    assert p.developmental_guidance is not None
    assert p.developmental_guidance["hypotheses"][0]["statement"] == "Test hypothesis line"


def test_developmental_guidance_packet_includes_work_guidance_lens():
    from local_ai.developmental_guidance import format_developmental_guidance_packet_block

    raw = {
        "as_of": "2026-01-01T00:00:00Z",
        "evidence_refs": [],
        "signals_summary": {"map_missing_dimensions": "fruit"},
        "hypotheses": [
            {
                "kind": "edge",
                "statement": "Placeholder hypothesis for normalize.",
                "confidence": "low",
                "basis": [],
            }
        ],
        "suggested_guidance_style": "neutral",
        "work_guidance_frame": {
            "stage": "branch",
            "primary_question": "What is the next shippable increment users can see?",
            "assessment_line": "Optional readiness check before rollout.",
            "missing_dimensions": ["fruit"],
        },
    }
    s = format_developmental_guidance_packet_block(raw)
    assert s
    assert "WORK GUIDANCE LENS" in s
    assert "branch" in s
    assert "next shippable" in s.lower()


def test_build_enriched_appends_developmental_guidance_after_runtime():
    p = CouncilPreflight(
        user_question="q",
        active_surface="workspace",
        developmental_guidance={
            "as_of": "2026-01-01T00:00:00Z",
            "evidence_refs": [],
            "signals_summary": {"map_missing_dimensions": "soil"},
            "hypotheses": [
                {
                    "kind": "strength",
                    "statement": "You may prefer concrete checklists.",
                    "confidence": "low",
                    "basis": [],
                }
            ],
            "suggested_guidance_style": "neutral",
        },
    )
    s = build_enriched_council_context(p, legacy_context_str=None, subject_ref=None, object_snapshot=None)
    assert "DEVELOPMENTAL GUIDANCE (hypotheses — uncertain, not diagnostic):" in s
    assert "You may prefer concrete checklists." in s
    assert "Interpretive axes" in s
    assert "clarity ↔ ambiguity" in s
    assert s.index("Runtime context") < s.index("DEVELOPMENTAL GUIDANCE")
    assert s.index("Interpretive axes") < s.index("Hypotheses:")


def test_build_enriched_primary_ve_first():
    p = CouncilPreflight(
        user_question="q",
        active_surface="vision_execution",
        ve_focus={
            "entity_type": "project",
            "entity_id": "p9",
            "field_label": "Brief",
            "parent": {"entity_type": "initiative", "entity_id": "i1", "label": "North star"},
            "lineage_labels": ["Initiatives", "North star", "Projects"],
        },
        raw_context_block="Recent conversation:\nUser: hi",
    )
    s = build_enriched_council_context(p, legacy_context_str=None, subject_ref=None, object_snapshot=None)
    assert "SYSTEM FAILURE STATE" not in s  # instruction layer only, not user Context
    assert s.index("PRIMARY CONTEXT") < s.index("Runtime context")
    assert "PRIMARY CONTEXT (authoritative):" in s
    assert "- Type: project" in s
    assert "- Initiative: North star" in s
    assert council_packet_has_primary_context(s)
    assert "p9" in s
    assert "North star" in s


def test_council_packet_has_primary_context_false_without_marker():
    assert not council_packet_has_primary_context("Runtime only")
    assert council_packet_has_primary_context("PRIMARY CONTEXT (authoritative):\n- Type: task")


def test_council_seat_limit_appends_primary_anchor():
    from local_ai.atria_tools import (
        COUNCIL_SEAT_CLARIFY_TEMPLATE,
        COUNCIL_SEAT_PRIMARY_ANCHOR,
        _council_seat_role_limit_for_context,
    )

    with_primary = _council_seat_role_limit_for_context("PRIMARY CONTEXT (authoritative):\n- Type: task")
    assert COUNCIL_SEAT_PRIMARY_ANCHOR in with_primary
    assert COUNCIL_SEAT_CLARIFY_TEMPLATE not in with_primary
    without = _council_seat_role_limit_for_context("Only runtime context here")
    assert COUNCIL_SEAT_PRIMARY_ANCHOR not in without
    assert COUNCIL_SEAT_CLARIFY_TEMPLATE not in without
    assert "OBJECT-FIRST FORMAT" in without

    with_note = _council_seat_role_limit_for_context(
        "CONTEXT NOTE (non-authoritative):\nDo not assume UI selection.\n\nRuntime context (from app): x"
    )
    assert with_note.strip() == COUNCIL_SEAT_CLARIFY_TEMPLATE.strip()
    assert COUNCIL_SEAT_PRIMARY_ANCHOR not in with_note
    assert "OBJECT-FIRST FORMAT" not in with_note
    assert "Format — exactly three labels" not in with_note


def test_supplemental_thread_labels_ground_seat_when_outside_primary_slice():
    """Project:/Title:/… lines after Runtime are supplemental phrases (run2-style harness)."""
    from local_ai.atria_tools import (
        _primary_field_grounding_phrases,
        _seat_body_passes_primary_postprocess_grounding,
    )

    ctx = """PRIMARY CONTEXT (authoritative):

- Type: project
- Title: (not provided — use Reference below: lineage, entity id, and field focus)
- Initiative: (see Reference if parent initiative or lineage is listed)
- Status: —
- Brief / description: —
- Expanded description: —

Reference (IDs, field focus, navigation):
• Focused entity: project (id: ovr-2)

Runtime context (from app):
Active surface: workspace_organizer

Project: Internal Workflow Cleanup
Constraint: stay within current Q3 scope.
"""
    d = _primary_field_grounding_phrases(ctx)
    assert "Internal Workflow Cleanup" in d["supplemental"]
    assert "stay within current Q3 scope." in d["supplemental"] or any(
        "Q3" in x for x in d["supplemental"]
    )
    body = "Core move: Sequence Internal Workflow Cleanup before LedgerBridge per Q3 scope."
    assert _seat_body_passes_primary_postprocess_grounding(body, validation_context=ctx)


def test_supplemental_skips_generic_title_project_and_dedupes_authoritative():
    from local_ai.atria_tools import _primary_field_grounding_phrases

    ctx = """PRIMARY CONTEXT (authoritative):

- Type: idea
- Title: Real Idea Name
- Brief / description: —
- Expanded description: —

Runtime context (from app):
Active surface: home

Title: Project
Summary: active work item
"""
    d = _primary_field_grounding_phrases(ctx)
    assert "Project" not in d["supplemental"]
    assert "active work item" in d["supplemental"]
    assert d["title"] == ["Real Idea Name"]


def test_seat_postprocess_grounding_phrase_based_not_word_bag():
    """Operator-style answers can name the product without 3 junk-token overlap on the full corpus."""
    from local_ai.atria_tools import _seat_body_passes_primary_postprocess_grounding

    ctx = """PRIMARY CONTEXT (authoritative):

- Type: initiative
- Title: Secret Initiative X
- Brief / description: North star: do the thing
"""
    body = (
        "Core move: Fix council packet truncation so **Secret Initiative X** "
        "reaches the model (pipeline failure, not org process)."
    )
    assert _seat_body_passes_primary_postprocess_grounding(body, validation_context=ctx)
    assert not _seat_body_passes_primary_postprocess_grounding(
        "Core move: Generic vision without anchors.",
        validation_context=ctx,
    )


def test_seat_postprocess_grounding_accepts_explicit_question_brief_without_title_echo():
    """Case C-style: PRIMARY title generic; user embeds Aurora/cutover in Question — Operator may echo those."""
    from local_ai.atria_tools import _seat_body_passes_primary_postprocess_grounding

    ctx = """PRIMARY CONTEXT (authoritative):

- Type: project
- Title: Secret Initiative X
- Brief / description: Do the thing.
"""
    q = (
        "Project: Aurora migration\n"
        "Outcome: Cutover with zero data loss\n"
        "Note: API freeze Friday.\n\n"
        "What's the next step for this project?"
    )
    body = "Core move: Validate Aurora cutover sequencing against zero data loss before the API freeze."
    assert _seat_body_passes_primary_postprocess_grounding(
        body,
        validation_context=ctx,
        user_question=q,
    )


def test_operator_persona_swaps_executable_constraint_when_clarify_only():
    from local_ai.atria_tools import _built_in_persona_dict, _build_council_persona_block

    op = _built_in_persona_dict("operator")
    normal = _build_council_persona_block(op, council_clarify_only=False)
    clarify = _build_council_persona_block(op, council_clarify_only=True)
    assert "executable in this product today" in normal.lower()
    assert "executable in this product today" not in clarify.lower()
    assert "weak grounding run" in clarify.lower()


def test_compose_council_seat_shared_constraints_omits_primary_grounding_when_clarify_only():
    from local_ai.atria_tools import COUNCIL_SEAT_CLARIFY_TEMPLATE, _compose_council_seat_shared_constraints

    clarified = _compose_council_seat_shared_constraints(
        COUNCIL_SEAT_CLARIFY_TEMPLATE,
        clarify_only=True,
    )
    assert "GROUNDING REQUIREMENT (MANDATORY)" not in clarified
    standard = _compose_council_seat_shared_constraints("seat rules stub", clarify_only=False)
    assert "GROUNDING REQUIREMENT (MANDATORY)" in standard


def test_build_council_persona_block_primary_and_enforcement():
    from local_ai.atria_tools import _assemble_council_seat_prompt, _build_council_persona_block

    persona = _build_council_persona_block(
        {
            "name": "Tester",
            "purpose": "Test purpose",
            "values": ["rigor"],
            "aversions": ["hand-waving"],
            "decisionRule": "Prefer evidence",
        }
    )
    assert "YOUR PERSPECTIVE" in persona
    assert "Avoids / fears: hand-waving" in persona
    assert "You MUST think and respond according to this perspective" in persona
    full = _assemble_council_seat_prompt(
        primary_context_block="PRIMARY CONTEXT (authoritative):\n\n- Title: T",
        user_question="What?",
        persona_block=persona,
        shared_constraints="Shared: fmt",
        secondary_packet_tail="Secondary tail",
    )
    assert full.index("PRIMARY CONTEXT") < full.index("Question:")
    assert full.index("Question:") < full.index("YOUR PERSPECTIVE")
    assert full.index("YOUR PERSPECTIVE") < full.index("Shared:")
    assert full.index("Shared:") < full.index("Secondary tail")


def test_split_enriched_council_context_for_seats():
    p = CouncilPreflight(
        user_question="q",
        active_surface="vision_execution",
        ve_focus={"entity_type": "task", "entity_id": "t1"},
        ve_focus_title="My task",
        ve_focus_brief="Short brief here",
        raw_context_block="Thread: user said hello",
    )
    enriched = build_enriched_council_context(p, legacy_context_str=None, subject_ref=None, object_snapshot=None)
    primary, secondary = split_enriched_council_context_for_seats(enriched)
    assert primary is not None
    assert "PRIMARY CONTEXT (authoritative):" in primary
    assert "My task" in primary
    assert "Runtime context" in secondary
    assert "Thread:" in secondary


def test_build_enriched_includes_runtime_block():
    p = CouncilPreflight(
        user_question="q",
        active_surface="home",
        breadcrumb="Radar Home",
        raw_context_block="Recent conversation:\nUser: hi",
    )
    s = build_enriched_council_context(p, legacy_context_str=None, subject_ref=None, object_snapshot=None)
    assert "SYSTEM FAILURE STATE" not in s
    assert "Runtime context (from app):" in s
    assert "Radar Home" in s
    assert "Recent conversation" in s


def test_vague_question_demotes_primary_to_context_note():
    p = CouncilPreflight(
        user_question="What's the next step for this project?",
        active_surface="vision_execution",
        ve_focus={
            "entity_type": "project",
            "entity_id": "p9",
            "lineage_labels": ["Initiatives", "North star", "Projects"],
        },
        ve_focus_title="Secret Initiative X",
    )
    ok, reason = should_treat_primary_as_authoritative(p, subject_ref=None, object_snapshot=None)
    assert ok is False
    assert reason == "vague_question_weak_grounding"

    s = build_enriched_council_context(p, legacy_context_str=None, subject_ref=None, object_snapshot=None)
    assert PRIMARY_CONTEXT_MARKER not in s
    assert CONTEXT_LEGITIMACY_NOTE_MARKER in s
    assert "Secret Initiative X" in s
    assert not council_packet_has_primary_context(s)
    primary, secondary = split_enriched_council_context_for_seats(s)
    assert primary is None
    assert CONTEXT_LEGITIMACY_NOTE_MARKER in secondary


def test_subject_ref_entity_id_keeps_authoritative_primary():
    p = CouncilPreflight(
        user_question="What's the next step for this project?",
        ve_focus={"entity_type": "project", "entity_id": "p9"},
        ve_focus_title="Alpha",
    )
    ok, _ = should_treat_primary_as_authoritative(
        p,
        subject_ref={"entity_type": "project", "entity_id": "p9"},
        object_snapshot=None,
    )
    assert ok is True
    s = build_enriched_council_context(
        p,
        legacy_context_str=None,
        subject_ref={"entity_type": "project", "entity_id": "p9"},
        object_snapshot=None,
    )
    assert PRIMARY_CONTEXT_MARKER in s
    assert council_packet_has_primary_context(s)


def test_grounding_explicit_in_preflight_parses():
    ctx = {"council_preflight": {"grounding_explicit": True, "ve_focus_title": "T", "ve_focus": {"entity_id": "1"}}}
    p = parse_preflight_from_request(ctx, "What's the next step for this project?")
    assert p.grounding_explicit is True
    ok, _ = should_treat_primary_as_authoritative(p, None, None)
    assert ok is True


def test_question_explicit_cues_not_ambiguous_for_primary():
    q = (
        "Project: Improve grounding.\nOutcome: All runs include truth-source order.\nWhat's the next step?"
    )
    assert question_has_explicit_grounding_cues(q) is True
    p = CouncilPreflight(
        user_question=q,
        ve_focus={"entity_type": "initiative", "entity_id": "i1"},
        ve_focus_title="Other thing",
    )
    ok, reason = should_treat_primary_as_authoritative(p, None, None)
    assert ok is True
    assert reason == "grounding_strong"


def test_raw_context_denial_demotes_primary_when_question_not_vague():
    """Harness run6_no_primary: ve_focus + non-vague question but explicit no-authoritative-object line."""
    p = CouncilPreflight(
        user_question="What do you think?",
        active_surface="vision_execution",
        ve_focus={"entity_type": "idea", "entity_id": "weak-6"},
        raw_context_block="Background notes only. No authoritative object provided.\n",
    )
    ok, reason = should_treat_primary_as_authoritative(p, None, None)
    assert ok is False
    assert reason == "raw_context_rejects_authoritative_primary"
    s = build_enriched_council_context(p, legacy_context_str=None, subject_ref=None, object_snapshot=None)
    assert PRIMARY_CONTEXT_MARKER not in s
    assert CONTEXT_LEGITIMACY_NOTE_MARKER in s
    assert not council_packet_has_primary_context(s)


def test_slim_conversation_history_keeps_only_last_user_with_recent_header():
    merged = (
        "Folder: /x\n\n"
        "Recent conversation:\n\n"
        "User: first ask\n\n"
        "Agent (Council): bad echo with ```\n\n"
        "User: stale last line in thread"
    )
    out = slim_conversation_history_to_last_user_only(
        merged,
        fallback_user_question="whats the priority right now?",
    )
    assert "bad echo" not in out
    assert "first ask" not in out
    assert "stale last line" not in out
    assert "whats the priority right now?" in out
    assert "Folder: /x" in out


def test_build_enriched_omits_thread_for_priority_resolution(monkeypatch):
    import local_ai.vision_execution.storage as ve_storage

    monkeypatch.setattr(ve_storage, "list_ideas", lambda uid: [])
    monkeypatch.setattr(ve_storage, "list_tasks", lambda uid: [])
    monkeypatch.setattr(ve_storage, "list_initiatives", lambda uid: [])
    p = CouncilPreflight(
        user_question="whats the priority right now?",
        active_surface="workspace",
        raw_context_block=(
            "Recent conversation:\n\nUser: old\n\nAgent (Council): ```\n\nUser: whats the priority right now?"
        ),
    )
    s = build_enriched_council_context(
        p,
        legacy_context_str=None,
        subject_ref=None,
        object_snapshot=None,
        resonance_user_id=None,
        question_kind="priority_resolution",
    )
    assert "Recent conversation" not in s
    assert "Agent (Council)" not in s
    assert "```" not in s


def test_truncate_scoped_digression_background_keeps_last_two_turns():
    long_bg = (
        "User: a1\n\nAssistant: b1\n\nUser: a2\n\nAssistant: b2\n\nUser: a3\n\nAssistant: b3"
    )
    out = truncate_scoped_digression_background(long_bg, max_turns=2)
    assert "a1" not in out
    assert "a3" in out and "b3" in out
    assert "a2" in out


def test_format_ve_working_set_snapshot_requires_user():
    assert format_ve_working_set_snapshot_block(None) is None
    assert format_ve_working_set_snapshot_block("") is None


def test_format_ve_working_set_snapshot_lists_ideas_and_tasks(monkeypatch):
    import local_ai.vision_execution.storage as ve_storage

    def fake_list_ideas(uid):
        assert uid == "user-ve-1"
        return [
            {
                "id": "idea-open-1",
                "title": "Zenaf behavior",
                "summary": "",
                "description": "body",
                "desired_outcome": "",
                "status": "Captured",
            },
        ]

    def fake_list_tasks(uid):
        assert uid == "user-ve-1"
        return [{"id": "task-open-1", "title": "Stabilize streaming path", "status": "In Progress"}]

    def fake_list_initiatives(uid):
        assert uid == "user-ve-1"
        return [
            {
                "id": "init-open-1",
                "title": "Launch prep",
                "brief": "x",
                "status": "Active",
            },
        ]

    monkeypatch.setattr(ve_storage, "list_ideas", fake_list_ideas)
    monkeypatch.setattr(ve_storage, "list_tasks", fake_list_tasks)
    monkeypatch.setattr(ve_storage, "list_initiatives", fake_list_initiatives)

    block = format_ve_working_set_snapshot_block("user-ve-1")
    assert block is not None
    assert VE_WORKING_SET_MARKER in block
    assert "Zenaf behavior" in block
    assert "OTHER IDEAS (For reference only; do NOT blend these into the PRIMARY focus):" in block
    assert "[ID: idea-open-1]" in block
    assert "missing: summary, desired_outcome" in block
    assert "OTHER OPEN ITEMS (For reference only; do NOT blend these into the PRIMARY focus):" in block
    assert "Stabilize streaming path" in block
    assert "[ID: task-open-1]" in block
    assert "OTHER INITIATIVES (For reference only; do NOT blend these into the PRIMARY focus):" in block
    assert "Launch prep" in block
    assert "[ID: init-open-1]" in block
    assert block.count("separate, distinct work item") >= 3


def test_build_enriched_includes_ve_snapshot_when_user_id(monkeypatch):
    import local_ai.vision_execution.storage as ve_storage

    monkeypatch.setattr(ve_storage, "list_ideas", lambda uid: [])
    monkeypatch.setattr(
        ve_storage,
        "list_tasks",
        lambda uid: [{"id": "t-only", "title": "Only task", "status": "Todo"}],
    )
    monkeypatch.setattr(ve_storage, "list_initiatives", lambda uid: [])

    p = CouncilPreflight(user_question="What should I do?", active_surface="workspace")
    s = build_enriched_council_context(
        p,
        legacy_context_str=None,
        subject_ref=None,
        object_snapshot=None,
        resonance_user_id="u-snap",
    )
    assert VE_WORKING_SET_MARKER in s
    assert "Only task" in s


def test_parse_preflight_scoped_digression_and_background():
    ctx = {
        "is_scoped_digression": True,
        "digression_background": "User: prior turn\n\nAssistant: agreed",
        "council_preflight": {"ve_focus": {"entity_type": "task", "entity_id": "abc"}},
    }
    p = parse_preflight_from_request(ctx, "refine criteria")
    assert p.scoped_digression is True
    assert p.digression_background_block and "prior turn" in p.digression_background_block


def test_build_enriched_scoped_omits_working_set_and_merged_thread(monkeypatch):
    import local_ai.vision_execution.storage as ve_storage

    monkeypatch.setattr(
        ve_storage,
        "list_ideas",
        lambda uid: [
            {
                "title": "Idea X",
                "summary": "",
                "description": "",
                "desired_outcome": "",
                "status": "Captured",
            },
        ],
    )
    monkeypatch.setattr(ve_storage, "list_tasks", lambda uid: [{"title": "T1", "status": "Todo"}])
    monkeypatch.setattr(ve_storage, "list_initiatives", lambda uid: [])

    p = CouncilPreflight(
        user_question="tighten criteria",
        active_surface="workspace",
        scoped_digression=True,
        digression_background_block="User: what's next?",
        ve_focus={"entity_type": "task", "entity_id": "t-focus"},
        ve_focus_title="Focus task",
        ve_focus_brief="Brief",
        ve_focus_description="Desc",
        developmental_guidance={
            "as_of": "2026-01-01T00:00:00Z",
            "evidence_refs": [],
            "signals_summary": {},
            "hypotheses": [
                {
                    "kind": "friction",
                    "statement": "Should not appear in scoped build",
                    "confidence": "high",
                    "basis": [],
                }
            ],
            "suggested_guidance_style": "neutral",
        },
        raw_context_block="FULL THREAD THAT MUST BE STRIPPED",
    )
    s = build_enriched_council_context(
        p,
        legacy_context_str="LEGACY_THREAD",
        subject_ref=None,
        object_snapshot=None,
        resonance_user_id="u-snap",
    )
    assert SCOPED_DIGRESSION_BACKGROUND_MARKER in s
    assert "what's next?" in s
    assert VE_WORKING_SET_MARKER not in s
    assert "FULL THREAD THAT MUST BE STRIPPED" not in s
    assert "LEGACY_THREAD" not in s
    assert "Should not appear in scoped build" not in s
    assert "SCOPED DIGRESSION (guardrails):" in s
    assert PRIMARY_CONTEXT_MARKER in s


def test_format_ve_focus_block_dedupes_identical_brief_and_description():
    p = CouncilPreflight(
        ve_focus={"entity_type": "idea", "entity_id": "i1"},
        ve_focus_title="Heart signup",
        ve_focus_brief="Create a mailing list signup linked from the Heart page",
        ve_focus_description="Create a mailing list signup linked from the Heart page",
    )
    block = council_preflight_mod._format_ve_focus_block(p)
    assert block
    assert block.count("Create a mailing list signup linked from the Heart page") == 1


def test_format_ve_focus_block_prefix_description_emits_single_brief_line():
    p = CouncilPreflight(
        ve_focus={"entity_type": "project", "entity_id": "p1"},
        ve_focus_title="Site",
        ve_focus_brief="Launch",
        ve_focus_description="Launch with booking",
    )
    block = council_preflight_mod._format_ve_focus_block(p)
    assert block
    assert "Expanded description:" not in block
    assert "Launch with booking" in block
