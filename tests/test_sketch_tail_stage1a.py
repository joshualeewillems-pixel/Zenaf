"""Stage 1A fixtures for the Bonsai Bench shaping-tail parser.

Covers the 1A-assigned fixtures from the Stage 1 scope (section 1A.2)
that execute at the parser-module level: F1, F3, F13, F14, F15, and the
F17 purity half (the module imports no store/service code and operates
on text alone). F17's application half and F18 (summary selection) are
client-derivation fixtures, discharged by the JS harness; F18 is
recorded here as an explicit skip so the fixture map has no gaps.

All inputs are recorded/hand-authored generation outputs. No live
model call occurs anywhere in this file.
"""

import ast
import pathlib

import pytest

from local_ai.conversation.sketch_tail import parse_sketch_tail

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "local_ai" / "conversation" / "sketch_tail.py"
)

BODY = "What you said and what you concluded are two different things."


def gen(tail_lines, body=BODY):
    return body + "\n\n[[sketch]]\n" + "\n".join(tail_lines)


# ---------------------------------------------------------------- F1

F1_TAILS = [
    [
        "branch | the claim that the delay is fine | ground=assumed | src=turn",
        "reading | the delay is the decision | ground=assumed | src=turn",
        "gap | what would change my mind | basis=reply",
    ],
    [
        "support | e1 | ground=reported | src=turn",
        "cross | e1 | e2",
        "keep | e2",
    ],
    [
        "revise | e1 | label=the claim that waiting is safer",
        "remove | e3",
        "accept | e2",
    ],
]


def test_f1_golden_tails_split_exact_and_cover_all_nine_verbs():
    seen_verbs = []
    for tail in F1_TAILS:
        result = parse_sketch_tail(gen(tail))
        assert result.status == "ok"
        assert result.body == BODY
        assert [i["verb"] for i in result.instructions] == [
            line.split("|")[0].strip() for line in tail
        ]
        seen_verbs.extend(i["verb"] for i in result.instructions)
    assert set(seen_verbs) == {
        "branch", "reading", "support", "cross", "gap",
        "revise", "remove", "keep", "accept",
    }


def test_f1_golden_field_values():
    result = parse_sketch_tail(gen(F1_TAILS[0]))
    branch, reading, gap = result.instructions
    assert branch == {
        "verb": "branch",
        "label": "the claim that the delay is fine",
        "ground": "assumed",
        "src": "turn",
    }
    assert reading["label"] == "the delay is the decision"
    assert gap == {
        "verb": "gap",
        "label": "what would change my mind",
        "basis": "reply",
    }
    result = parse_sketch_tail(gen(F1_TAILS[2]))
    revise = result.instructions[0]
    assert revise == {
        "verb": "revise",
        "handle": "e1",
        "label": "the claim that waiting is safer",
    }


def test_f1_delimiter_with_zero_instruction_lines_is_explicit_no_change():
    result = parse_sketch_tail(BODY + "\n\n[[sketch]]\n")
    assert result.status == "no_change"
    assert result.body == BODY
    assert result.instructions == []


def test_absent_tail_returns_text_byte_identical():
    text = "An ordinary reply.\nWith a second line."
    result = parse_sketch_tail(text)
    assert result.status == "absent"
    assert result.body == text
    assert result.instructions == []


# ---------------------------------------------------------------- F3

F3_VARIANTS = {
    "unknown verb": ["frobnicate | x | ground=assumed | src=turn"],
    "wrong field count": ["branch | only a label"],
    "81-char label": [
        "branch | " + "x" * 81 + " | ground=assumed | src=turn"
    ],
    "bad ground=": ["branch | a point | ground=certain | src=turn"],
    "gap carrying src=": ["gap | something missing | src=turn"],
    "fieldless revise": ["revise | e1"],
}


@pytest.mark.parametrize("variant", sorted(F3_VARIANTS))
def test_f3_malformed_grammar_variants(variant):
    result = parse_sketch_tail(gen(F3_VARIANTS[variant]))
    assert result.status == "grammar_failure"
    assert result.body == BODY  # byte-identical pre-delimiter body
    assert result.instructions == []


def test_f3_seven_instruction_lines_exceeds_cap():
    tail = [
        "branch | point %d | ground=assumed | src=turn" % k for k in range(7)
    ]
    result = parse_sketch_tail(gen(tail))
    assert result.status == "grammar_failure"
    assert result.body == BODY
    assert result.instructions == []


def test_f3_tail_over_600_chars_exceeds_cap():
    tail = [
        "branch | " + ("point %d " % k) + "y" * 62 + " | ground=assumed | src=turn"
        for k in range(6)
    ]
    text = gen(tail)
    tail_text = text[text.index("[[sketch]]"):]
    assert len(tail_text) > 600  # the cap's documented measure
    result = parse_sketch_tail(text)
    assert result.status == "grammar_failure"
    assert result.body == BODY
    assert result.instructions == []


def test_f3_non_instruction_line_inside_tail_drops_whole_tail():
    tail = [
        "branch | a point | ground=assumed | src=turn",
        "and then a line of prose wandered in",
    ]
    result = parse_sketch_tail(gen(tail))
    assert result.status == "grammar_failure"
    assert result.body == BODY
    assert result.instructions == []


# --------------------------------------------------------------- F13

def test_f13_truncated_mid_instruction():
    text = BODY + "\n\n[[sketch]]\nbranch | half a lab"
    result = parse_sketch_tail(text)
    assert result.status == "grammar_failure"
    assert result.body == BODY
    assert result.instructions == []


def test_f13_truncated_mid_delimiter():
    text = BODY + "\n\n[[sket"
    result = parse_sketch_tail(text)
    assert result.status == "grammar_failure"
    assert result.body == BODY
    assert result.instructions == []


# --------------------------------------------------------------- F14

def test_f14_two_complete_tail_blocks():
    text = gen(["branch | a point | ground=assumed | src=turn"])
    text += "\n[[sketch]]\nremove | e1"
    result = parse_sketch_tail(text)
    assert result.status == "grammar_failure"
    assert result.body == BODY
    assert result.instructions == []


def test_f14_delimiter_repeated_inside_one_tail():
    tail = [
        "branch | a point | ground=assumed | src=turn",
        "[[sketch]]",
        "remove | e1",
    ]
    result = parse_sketch_tail(gen(tail))
    assert result.status == "grammar_failure"
    assert result.body == BODY
    assert result.instructions == []


# --------------------------------------------------------------- F15

def test_f15a_marker_followed_by_prose_is_stripped_prose_preserved():
    text = "First line of speech.\n[[sketch]]\nStill speaking, nothing to file."
    result = parse_sketch_tail(text)
    assert result.status == "hygiene_strip"
    assert result.body == "First line of speech.\nStill speaking, nothing to file."
    assert result.instructions == []


def test_f15b_glued_marker_never_opens_a_tail():
    text = (
        "And so I wonder[[sketch]]\n"
        "branch | a point | ground=assumed | src=turn\n"
        "remove | e1\n"
        "But the conversation itself goes on."
    )
    result = parse_sketch_tail(text)
    assert result.status == "hygiene_strip"
    assert result.body == "And so I wonder\nBut the conversation itself goes on."
    assert result.instructions == []


def test_f15c_genuine_tail_after_hygiene_sensitive_content_parses():
    text = (
        "Speaking first.\n"
        "[[sketch]]\n"
        "Prose after a stray marker.\n"
        "[[sketch]]\n"
        "branch | a real point | ground=reported | src=turn"
    )
    result = parse_sketch_tail(text)
    assert result.status == "ok"
    assert result.body == "Speaking first.\nProse after a stray marker."
    assert [i["verb"] for i in result.instructions] == ["branch"]


def test_f15_marker_like_text_inside_prose_line_is_preserved():
    text = "You typed [[sketch]] yourself last week, I noticed."
    result = parse_sketch_tail(text)
    assert result.status == "absent"
    assert result.body == text
    assert result.instructions == []


# --------------------------------------------------------------- F17
# (purity half; the application half runs in the JS harness)

def test_f17_parser_module_is_pure_no_store_or_service_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 or node.module == "__future__" or True
            if node.module:
                imported.add(node.module.split(".")[0])
    # Stdlib only; nothing from the conversation service, the store,
    # or any other Zenaf module.
    assert imported <= {"__future__", "re", "dataclasses"}
    assert "local_ai" not in imported


def test_f17_keep_and_accept_verbs_parse_at_parser_level():
    result = parse_sketch_tail(gen(["keep | e2", "accept | e2"]))
    assert result.status == "ok"
    assert result.instructions == [
        {"verb": "keep", "handle": "e2"},
        {"verb": "accept", "handle": "e2"},
    ]


# --------------------------------------------------------------- F18

@pytest.mark.skip(
    reason="F18 is a client-derivation fixture (summary selection, design "
    "section 6.2); discharged by the JS application harness, not the parser."
)
def test_f18_summary_selection_discharged_in_js_harness():
    pass


# ------------------------------------------- supplementary semantics
# Element-level (A5) semantics determinable at Stage 1A (design 5.2).
# The F-numbered citation fixtures (F5/F19) execute at the 1B seam;
# these unit tests pin the parser-stage behaviour only.

def test_semantic_documented_without_rec_source_drops_only_that_element():
    tail = [
        "branch | a documented claim | ground=documented | src=turn",
        "branch | an ordinary point | ground=assumed | src=turn",
    ]
    result = parse_sketch_tail(gen(tail))
    assert result.status == "ok"
    assert [i["label"] for i in result.instructions] == ["an ordinary point"]
    assert any(d.startswith("semantic_drop") for d in result.diagnostics)


def test_semantic_reported_from_rec_source_drops():
    tail = ["branch | a claim | ground=reported | src=rec:r1"]
    result = parse_sketch_tail(gen(tail))
    assert result.instructions == []


def test_semantic_known_identifier_sets_enforced_when_supplied():
    known = {"msg_roles": {"m1": "user", "m2": "voice"}, "rec_ids": {"r1"}}
    ok = parse_sketch_tail(
        gen(["branch | from you | ground=reported | src=msg:m1"]), known=known)
    assert len(ok.instructions) == 1
    voice = parse_sketch_tail(
        gen(["branch | from her | ground=reported | src=msg:m2"]), known=known)
    assert voice.instructions == []
    unknown = parse_sketch_tail(
        gen(["branch | from where | ground=assumed | src=msg:zz"]), known=known)
    assert unknown.instructions == []
    gap_bad_basis = parse_sketch_tail(
        gen(["gap | an absence | basis=msg:zz"]), known=known)
    assert gap_bad_basis.instructions == []
    gap_ok_basis = parse_sketch_tail(
        gen(["gap | an absence | basis=msg:m1"]), known=known)
    assert len(gap_ok_basis.instructions) == 1
