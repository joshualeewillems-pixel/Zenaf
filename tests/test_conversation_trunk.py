"""Conversation trunk: classification, output contract, mediation profile, Zenaf instruction block."""
from __future__ import annotations

from local_ai.conversation_trunk import (
    GLOBAL_EXTERNAL_VOICE_HEADING,
    MEDIATION_CONTROL_HEADING,
    MODE_LOCK_HEADING,
    PROGRESS_BIAS_HEADING,
    classify_question_kind,
    conversational_partner_trunk_instructions,
    derive_capture_target,
    derive_mediation_profile,
    merge_conversation_subject,
    parse_conversation_subject,
    resolve_query_scope,
    select_output_contract,
)
from local_ai.council_preflight import PRIMARY_CONTEXT_MARKER


def _trunk_block_for_question(
    q: str,
    *,
    aspiration_context_available: bool = False,
    packet: str | None = None,
    council_preflight_dict: dict | None = None,
    conversation_subject_previous: dict | None = None,
) -> str:
    kind = classify_question_kind(q)
    contract = select_output_contract(kind)
    profile = derive_mediation_profile(q, kind, contract)
    _capture = (
        derive_capture_target(q, packet=packet, council_preflight_dict=council_preflight_dict)
        if contract in ("confirm_and_integrate", "direct_integration")
        else None
    )
    _prev = parse_conversation_subject(conversation_subject_previous) if conversation_subject_previous else None
    _merged = merge_conversation_subject(
        previous=_prev,
        question=q,
        question_kind=kind,
        output_contract=contract,
        capture_target=_capture,
        council_preflight_dict=council_preflight_dict,
        packet=packet,
    )
    _scope = resolve_query_scope(
        question=q,
        question_kind=kind,
        conversation_subject=_merged,
        council_preflight_dict=council_preflight_dict,
        packet=packet,
    )
    if _scope["retrieval_mode"] == "full_inventory" and kind not in (
        "state_inventory",
        "missing_fields",
        "priority_resolution",
        "resolution_collapse",
        "field_update_direct",
        "user_correcting_model",
        "integration_status",
        "integration_confirm",
    ):
        kind = "state_inventory"
        contract = select_output_contract(kind)
        profile = derive_mediation_profile(q, kind, contract)
        _capture = (
            derive_capture_target(q, packet=packet, council_preflight_dict=council_preflight_dict)
            if contract in ("confirm_and_integrate", "direct_integration")
            else None
        )
        _merged = merge_conversation_subject(
            previous=_prev,
            question=q,
            question_kind=kind,
            output_contract=contract,
            capture_target=_capture,
            council_preflight_dict=council_preflight_dict,
            packet=packet,
        )
        _scope = resolve_query_scope(
            question=q,
            question_kind=kind,
            conversation_subject=_merged,
            council_preflight_dict=council_preflight_dict,
            packet=packet,
        )
    return conversational_partner_trunk_instructions(
        question_kind=kind,
        output_contract=contract,
        mediation_profile=profile,
        aspiration_context_available=aspiration_context_available,
        user_question=q,
        packet=packet,
        council_preflight_dict=council_preflight_dict,
        capture_target=_capture,
        conversation_subject=_merged,
        query_scope=_scope,
    )


def test_finalize_website_acceptance_question_is_inventory_only():
    q = "what do we still need to do to the 'finalize website' idea?"
    kind = classify_question_kind(q)
    assert kind == "state_inventory"
    contract = select_output_contract(kind)
    assert contract == "inventory_only"
    profile = derive_mediation_profile(q, kind, contract)
    assert profile["mediation_move"] == "sequence_precision_layers"
    assert profile["resolution_mode"] == "compress"
    block = conversational_partner_trunk_instructions(
        question_kind=kind,
        output_contract=contract,
        mediation_profile=profile,
        user_question=q,
    )
    assert MEDIATION_CONTROL_HEADING in block
    assert "inventory_only" in block
    assert "MUST NOT" in block
    assert "multi-option" in block.lower() or "action menu" in block.lower()
    assert "sequence_precision_layers" in block
    assert "non-overlapping" in block.lower() or "layers" in block.lower()
    # Executor must not push generic three-option posture for this mediation.
    assert "small set of clear options" not in block
    assert "option list" in block.lower()


def test_secondary_compression_bullet_in_trunk_block():
    block = _trunk_block_for_question("what do we still need to do to the finalize website idea?")
    assert "Secondary compression" in block
    assert "same underlying gap" in block.lower() or "core gap" in block.lower()


def test_precision_mediation_compression_prompt_contract():
    """Case 1 — layered inventory, no option menu in instructions."""
    q = "what do we still need to do to the finalize website idea?"
    block = _trunk_block_for_question(q)
    assert derive_mediation_profile(q, classify_question_kind(q), select_output_contract(classify_question_kind(q)))[
        "mediation_move"
    ] == "sequence_precision_layers"
    assert "Mediation (sequence_precision_layers)" in block
    assert "option list" in block.lower() or "No" in block
    assert "small set of clear options" not in block
    assert GLOBAL_EXTERNAL_VOICE_HEADING in block
    assert "synthesized" in block.lower() or "compressed" in block.lower()


def test_precision_mediation_decision_prompt_contract():
    """Case 2 — priority_resolution: resolve_priority, natural integrated justification (no lens dump)."""
    q = "what should we do first?"
    assert classify_question_kind(q) == "priority_resolution"
    assert select_output_contract("priority_resolution") == "three_options_then_lean"
    profile = derive_mediation_profile(q, "priority_resolution", "three_options_then_lean")
    assert profile["mediation_move"] == "resolve_priority"
    assert profile["ambiguity_type"] == "competing_priorities"
    assert profile["resolution_mode"] == "decide"
    block = _trunk_block_for_question(q)
    assert "resolve_priority" in block
    assert "Mediation (`resolve_priority`)" in block
    assert "from a … perspective" in block or "standpoint" in block
    assert "lens labels" in block.lower() or "lenses" in block.lower()
    assert GLOBAL_EXTERNAL_VOICE_HEADING in block
    assert MODE_LOCK_HEADING in block
    assert "trade-off framing" in block.lower()
    assert "consider" in block.lower() and "you might" in block.lower()
    assert "on one hand" in block.lower()
    assert "small set of clear options" not in block


def test_precision_mediation_enumerate_prompt_contract():
    """Case 3 — expansion only when mediation_move is enumerate."""
    q = "give me options"
    assert classify_question_kind(q) == "option_generation"
    profile = derive_mediation_profile(q, "option_generation", "three_options_then_lean")
    assert profile["mediation_move"] == "enumerate"
    assert profile["resolution_mode"] == "expand"
    block = _trunk_block_for_question(q)
    assert "Mediation (enumerate)" in block
    assert "2–4" in block or "distinct" in block.lower()


def test_next_step_maps_to_three_options_contract_and_mediation():
    assert classify_question_kind("What should I do next?") == "next_step"
    assert select_output_contract("next_step") == "three_options_then_lean"
    p = derive_mediation_profile("x", "next_step", "three_options_then_lean")
    assert p["mediation_move"] == "recommend_first_collapse"


def test_priority_resolution_classify_what_matters_most():
    q = "what matters most right now?"
    assert classify_question_kind(q) == "priority_resolution"
    assert select_output_contract("priority_resolution") == "three_options_then_lean"
    p = derive_mediation_profile(q, "priority_resolution", "three_options_then_lean")
    assert p["mediation_move"] == "resolve_priority"
    assert p["ambiguity_type"] == "competing_priorities"


def test_priority_resolution_classify_whats_priority_without_the():
    """'whats priority right now?' must not fall through to reflective_inquiry (missing 'the' vs 'whats the priority')."""
    q = "whats priority right now?"
    assert classify_question_kind(q) == "priority_resolution"


def test_priority_resolution_classify_doing_today_agenda_focus():
    for q in (
        "what are we doing today?",
        "what's our agenda for this session?",
        "whats on the agenda?",
        "what's the focus for today?",
    ):
        assert classify_question_kind(q) == "priority_resolution"
        assert select_output_contract("priority_resolution") == "three_options_then_lean"
        p = derive_mediation_profile(q, "priority_resolution", "three_options_then_lean")
        assert p["resolution_mode"] == "decide"
        assert p["mediation_move"] == "resolve_priority"


def test_field_update_direct_put_that_in_routes_to_recommend_first_collapse():
    q = "yes put that in completion criteria"
    assert classify_question_kind(q) == "field_update_direct"
    assert select_output_contract("field_update_direct") == "three_options_then_lean"
    p = derive_mediation_profile(q, "field_update_direct", "three_options_then_lean")
    assert p["mediation_move"] == "recommend_first_collapse"
    assert p["resolution_mode"] == "decide"


def test_resolution_collapse_finalize_verbs_route_to_recommend_first_collapse():
    for q in (
        "ok great lets finalize the website requirements",
        "help me solidify the scope",
        "we need to nail down the copy",
    ):
        assert classify_question_kind(q) == "resolution_collapse"
        assert select_output_contract("resolution_collapse") == "three_options_then_lean"
        p = derive_mediation_profile(q, "resolution_collapse", "three_options_then_lean")
        assert p["mediation_move"] == "recommend_first_collapse"
        assert p["resolution_mode"] == "decide"


def test_user_correcting_model_classify_contract_and_mediation():
    q = "there is already a website, it just needs to be redesigned for intake"
    assert classify_question_kind(q) == "user_correcting_model"
    assert select_output_contract("user_correcting_model") == "refine_and_continue"
    p = derive_mediation_profile(q, "user_correcting_model", "refine_and_continue")
    assert p["mediation_move"] == "update_and_continue"
    assert p["resolution_mode"] == "compress"
    block = _trunk_block_for_question(q)
    assert "refine_and_continue" in block
    assert "update_and_continue" in block
    assert "Refinement mode" in block
    assert "would you like" in block.lower()
    assert GLOBAL_EXTERNAL_VOICE_HEADING in block
    assert "Secondary compression" not in block


def test_user_correcting_model_overrides_priority_signals():
    assert classify_question_kind("no actually what matters most is fixing intake") == "user_correcting_model"


def test_progress_bias_heading_in_trunk_block():
    block = _trunk_block_for_question("what should we do first?")
    assert PROGRESS_BIAS_HEADING in block
    assert "PROGRESS OVER EXPLORATION" in block
    assert "CAPTURE BIAS" in block


def test_integration_confirm_contract_commit_and_confirm_mediation():
    q = "yes"
    kind = "integration_confirm"
    assert select_output_contract(kind) == "direct_integration_commit"
    profile = derive_mediation_profile(q, kind, "direct_integration_commit")
    assert profile["mediation_move"] == "commit_and_confirm"
    block = conversational_partner_trunk_instructions(
        question_kind=kind,
        output_contract="direct_integration_commit",
        mediation_profile=profile,
        user_question=q,
    )
    assert "commit_and_confirm" in block
    assert "direct_integration_commit" in block
    assert "MUST NOT" in block


def test_integration_status_classify_and_executor():
    q = "are you updating the notes?"
    assert classify_question_kind(q) == "integration_status"
    assert select_output_contract("integration_status") == "direct_integration"
    p = derive_mediation_profile(q, "integration_status", "direct_integration")
    assert p["mediation_move"] == "integration_status_reply"
    block = _trunk_block_for_question(q)
    assert "direct_integration" in block
    assert "integration_status_reply" in block
    assert "INTEGRATION COMMITTED" in block
    assert MODE_LOCK_HEADING in block


def test_structured_outcome_arrow_triggers_user_providing_precision():
    q = "redesign site → intake funnel → show value → reduce stress → live from the heart"
    assert classify_question_kind(q) == "user_providing_precision"


def test_what_should_we_do_instead_is_next_step_not_correction():
    assert classify_question_kind("what should we do instead of delaying launch?") == "next_step"


def test_missing_fields_kind():
    assert classify_question_kind("Which fields are still missing on this initiative?") == "missing_fields"
    assert select_output_contract("missing_fields") == "inventory_only"
    p = derive_mediation_profile("q", "missing_fields", "inventory_only")
    assert p["mediation_move"] == "compress_redundant_work"


def test_option_generation():
    assert classify_question_kind("Give me some ways to unblock this") == "option_generation"
    assert select_output_contract("option_generation") == "three_options_then_lean"


def test_user_providing_precision_desired_outcomes():
    q = "The desired outcomes would be a successful public launch and 500 signups in the first month."
    assert classify_question_kind(q) == "user_providing_precision"
    kind = classify_question_kind(q)
    assert select_output_contract(kind) == "confirm_and_integrate"
    p = derive_mediation_profile(q, kind, "confirm_and_integrate")
    assert p["mediation_move"] == "acknowledge_integrate"
    assert p["resolution_mode"] == "compress"
    packet = f"""{PRIMARY_CONTEXT_MARKER}
- Type: idea
- Title: Finalize Website Approach
- Initiative: —
- Status: —
- Brief / description: —
- Expanded description: —
"""
    preflight = {
        "ve_focus": {"entity_id": "idea-1", "entity_type": "idea"},
        "ve_focus_title": "Finalize Website Approach",
    }
    ct = derive_capture_target(q, packet=packet, council_preflight_dict=preflight)
    assert ct["field_target"] == "desired_outcome"
    assert ct["entity_target"] == "Finalize Website Approach"
    assert ct["capture_confidence"] == "high"
    block = _trunk_block_for_question(q, packet=packet, council_preflight_dict=preflight)
    assert "confirm_and_integrate" in block
    assert "Integration mode" in block
    assert "acknowledge_integrate" in block
    assert GLOBAL_EXTERNAL_VOICE_HEADING in block
    assert MODE_LOCK_HEADING in block
    assert "would you like" in block.lower()
    assert "CAPTURE TARGET" in block
    assert "capture_confidence=" in block and "high" in block
    assert "Intent / what this idea is trying to become" in block
    assert "Finalize Website Approach" in block
    assert "sequence_precision_layers" not in block


def test_derive_capture_target_medium_field_conflict():
    q = "Our goal is to ship by Friday."
    packet = f"{PRIMARY_CONTEXT_MARKER}\n- Title: Beta release\n"
    preflight = {
        "ve_focus": {"field_key": "desiredOutcome", "field_label": "Desired outcome"},
        "ve_focus_title": "Beta release",
    }
    ct = derive_capture_target(q, packet=packet, council_preflight_dict=preflight)
    assert ct["capture_confidence"] == "medium"
    assert ct["field_target"] == "goal"


def test_derive_capture_target_low_without_signals():
    ct = derive_capture_target("to clarify, we're aiming for quality.", packet=None, council_preflight_dict=None)
    assert ct["capture_confidence"] == "low"
    assert ct["entity_target"] is None


def test_user_providing_precision_not_when_asking_for_outcome():
    q = "What is the desired outcome for this project?"
    assert classify_question_kind(q) != "user_providing_precision"


def test_user_providing_precision_goal_is_declarative():
    assert classify_question_kind("Our goal is to ship the beta by March.") == "user_providing_precision"


def test_reflective_default():
    assert classify_question_kind("How are you thinking about trade-offs here?") == "reflective_inquiry"
    assert select_output_contract("reflective_inquiry") == "reflective_synthesis"
    p = derive_mediation_profile("q", "reflective_inquiry", "reflective_synthesis")
    assert p["mediation_move"] == "expose_decision_axis"


def test_aspiration_recall_rule_only_when_context_available():
    kind = "next_step"
    contract = "three_options_then_lean"
    profile = derive_mediation_profile("x", kind, contract)
    block_without = conversational_partner_trunk_instructions(
        question_kind=kind,
        output_contract=contract,
        mediation_profile=profile,
        aspiration_context_available=False,
        user_question="What should we do first?",
    )
    block_with = conversational_partner_trunk_instructions(
        question_kind=kind,
        output_contract=contract,
        mediation_profile=profile,
        aspiration_context_available=True,
        user_question="What should we do first?",
    )
    assert "Aspiration (internal vs external)" not in block_without
    assert "Aspiration (internal vs external)" in block_with
    assert "one sentence" in block_with.lower() or "woven" in block_with.lower()


def test_inventory_contract_stays_strict_without_aspiration_overlay():
    kind = "state_inventory"
    contract = "inventory_only"
    profile = derive_mediation_profile("q", kind, contract)
    block = conversational_partner_trunk_instructions(
        question_kind=kind,
        output_contract=contract,
        mediation_profile=profile,
        aspiration_context_available=True,
        user_question="what do we still need",
    )
    assert "MUST NOT" in block
    assert "aspiration-recall" not in block


def test_conversation_continuity_classified():
    assert classify_question_kind("continue the previous thread about the website") == "conversation_continuity"
    assert classify_question_kind("where were we?") == "conversation_continuity"
    assert classify_question_kind("what else do we need to discuss about it?") == "conversation_continuity"
    assert select_output_contract("conversation_continuity") == "continuity_forward"
    p = derive_mediation_profile("x", "conversation_continuity", "continuity_forward")
    assert p["mediation_move"] == "continue_from_subject"


def test_merge_conversation_subject_retains_contribution_on_continuity():
    prev = {
        "entity_id": "idea-1",
        "entity_type": "idea",
        "entity_display_name": "Website funnel",
        "active_field": "desired_outcome",
        "last_user_contribution": "Dual channel for medical vs tourist clients.",
        "confidence": "high",
    }
    merged = merge_conversation_subject(
        previous=parse_conversation_subject(prev),
        question="continue the previous thread",
        question_kind="conversation_continuity",
        output_contract="continuity_forward",
        capture_target=None,
        council_preflight_dict=None,
        packet=None,
    )
    assert merged is not None
    assert merged.get("last_user_contribution") == prev["last_user_contribution"]
    assert merged.get("active_field") == "desired_outcome"


def test_continuity_trunk_has_continue_executor_and_subject_block():
    prev = {
        "entity_id": "idea-1",
        "entity_type": "idea",
        "entity_display_name": "Website funnel",
        "active_field": "desired_outcome",
        "last_user_contribution": "Dual channel for medical vs tourist clients.",
        "confidence": "high",
    }
    block = _trunk_block_for_question(
        "where were we?",
        conversation_subject_previous=prev,
    )
    assert "continuity_forward" in block
    assert "continue_from_subject" in block
    assert "CONVERSATION SUBJECT" in block
    assert "Dual channel" in block
    assert "Continuity mode" in block
    assert "RETRIEVAL SCOPE" in block
    assert "retrieval_mode='subject'" in block


def test_what_else_is_there_is_system_inventory_not_reflective():
    assert classify_question_kind("what else is there?") == "state_inventory"
    s = resolve_query_scope(
        question="what else is there?",
        question_kind="state_inventory",
        conversation_subject=None,
        council_preflight_dict=None,
        packet=None,
    )
    assert s["retrieval_mode"] == "full_inventory"
    assert s["scope_type"] == "system_wide"


def test_what_were_we_working_on_is_continuity():
    assert classify_question_kind("what were we working on?") == "conversation_continuity"


def test_system_inventory_trunk_has_retrieval_and_hard_inventory_line():
    block = _trunk_block_for_question("what needs attention right now?")
    assert "RETRIEVAL SCOPE" in block
    assert "full_inventory" in block
    assert "inventory_only" in block or "state_inventory" in block
    assert "RETRIEVAL (inventory — hard)" in block or "system-state listing" in block


def test_named_pipeline_scope_is_scoped_not_full_inventory():
    q = "in Living From The Heart, what still needs work?"
    assert classify_question_kind(q) == "state_inventory"
    s = resolve_query_scope(
        question=q,
        question_kind="state_inventory",
        conversation_subject=None,
        council_preflight_dict=None,
        packet=None,
    )
    assert s["retrieval_mode"] == "scoped"
    assert s["scope_type"] == "explicit"
    assert "living from the heart" in (s["active_entity"].get("scope_phrase") or "").lower()


def test_can_you_record_as_desired_outcome_is_user_providing_precision():
    q = "can you record this as the desired outcome?"
    assert classify_question_kind(q) == "user_providing_precision"


def test_confirm_and_integrate_trunk_strict_capture_tool_shape():
    """Instructions enforce short capture-only reply; model tests would check ≤2 sentences separately."""
    q = "can you record this as the desired outcome?"
    assert classify_question_kind(q) == "user_providing_precision"
    kind = classify_question_kind(q)
    contract = select_output_contract(kind)
    profile = derive_mediation_profile(q, kind, contract)
    assert profile["mediation_move"] == "acknowledge_integrate"
    packet = f"""{PRIMARY_CONTEXT_MARKER}
- Type: idea
- Title: Mailing list signup
- Initiative: —
- Status: —
- Brief / description: —
- Expanded description: —
"""
    preflight = {
        "ve_focus": {"entity_id": "idea-2", "entity_type": "idea"},
        "ve_focus_title": "Mailing list signup",
    }
    block = _trunk_block_for_question(q, packet=packet, council_preflight_dict=preflight)
    assert "capture mode" in block
    assert "not thinking mode" in block
    assert "40 words" in block or "~40 words" in block
    assert "2 sentences" in block
    assert "restate" in block.lower() and "full input" in block.lower()
    assert "add" in block.lower() and "record" in block.lower()
    assert "intent / what this idea is trying to become" in block.lower()
    assert MODE_LOCK_HEADING in block
    assert "acknowledge_integrate" in block and "excludes" in block.lower()


def test_mode_lock_covers_enumerate_and_expose_paths():
    q_opt = "give me options"
    b_opt = _trunk_block_for_question(q_opt)
    assert MODE_LOCK_HEADING in b_opt
    assert "enumerate" in b_opt.lower()
    assert "consider" in b_opt.lower()

    b_exp = conversational_partner_trunk_instructions(
        question_kind="reflective_inquiry",
        output_contract="reflective_synthesis",
        mediation_profile=derive_mediation_profile("x", "reflective_inquiry", "reflective_synthesis"),
        user_question="How should we think about the trade-off?",
    )
    assert MODE_LOCK_HEADING in b_exp
    assert "expose_decision_axis" in b_exp
    assert "would you like" in b_exp.lower()


def test_mode_lock_on_continuity_and_inventory():
    b_cont = _trunk_block_for_question("where were we?")
    assert MODE_LOCK_HEADING in b_cont
    assert "continue_from_subject" in b_cont

    b_inv = _trunk_block_for_question("what do we still need to do to the finalize website idea?")
    assert MODE_LOCK_HEADING in b_inv
    assert "inventory excludes" in b_inv.lower() or "Inventory excludes" in b_inv
