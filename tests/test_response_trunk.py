"""Response contract trunk (Technical Header) for Zenaf."""

from local_ai.response_trunk import build_response_control_block, build_response_contract


def test_response_contract_has_three_fields():
    c = build_response_contract(
        scoped_digression=False,
        question_kind="priority_resolution",
        output_contract="three_options_then_lean",
        mediation_profile={
            "ambiguity_type": "competing_priorities",
            "resolution_mode": "decide",
            "mediation_move": "resolve_priority",
        },
        aspiration_context_available=False,
    )
    assert set(c.keys()) == {"syntax_rules", "grounding_fences", "mode_directives"}
    assert "ID MANDATE" in c["syntax_rules"]
    assert "FATAL ERROR" in c["syntax_rules"] or "triple" in c["syntax_rules"].lower()
    assert "MAILING LIST" in c["grounding_fences"].upper() or "mailing list" in c["grounding_fences"].lower()
    assert "PRIORITY AMNESIA" in c["mode_directives"]
    assert "resolve_priority" in c["mode_directives"]
    assert "FIELD_1: [DRAFT_VALUE]" in c["mode_directives"]
    assert "FIELD_2: [ID]" in c["mode_directives"]


def test_scoped_adds_strict_and_scoped_grounding():
    c = build_response_contract(
        scoped_digression=True,
        question_kind="reflective_inquiry",
        output_contract="reflective_synthesis",
        mediation_profile={
            "ambiguity_type": "unknown",
            "resolution_mode": "sharpen",
            "mediation_move": "expose_decision_axis",
        },
        aspiration_context_available=False,
    )
    assert "STRICT FIELD MODE" in c["mode_directives"]
    assert "Scoped thread" in c["grounding_fences"] or "scoped" in c["grounding_fences"].lower()


def test_required_fields_override_renders_custom_rows():
    c = build_response_contract(
        scoped_digression=False,
        question_kind="next_step",
        output_contract="three_options_then_lean",
        mediation_profile={
            "ambiguity_type": "unclear_priority",
            "resolution_mode": "decide",
            "mediation_move": "recommend_first_collapse",
        },
        aspiration_context_available=False,
        required_fields=["FIELD_A: [ID]", "FIELD_B: [DRAFT_VALUE]"],
    )
    assert "FIELD_A: [ID]" in c["mode_directives"]
    assert "FIELD_B: [DRAFT_VALUE]" in c["mode_directives"]


def test_build_response_control_block_technical_header():
    s = build_response_control_block(
        scoped_digression=False,
        question_kind="next_step",
        output_contract="three_options_then_lean",
        mediation_profile={
            "ambiguity_type": "unclear_priority",
            "resolution_mode": "decide",
            "mediation_move": "recommend_first_collapse",
        },
        aspiration_context_available=True,
    )
    assert "TECHNICAL HEADER" in s
    assert "mode_directives" in s
    assert "syntax_rules" in s
    assert "grounding_fences" in s
