"""Increment A tests: declaration blocks at generation time.

No live generations, no provider calls, no real keys anywhere. Fake
participants return canned text; the runner hook is exercised through
run_multi_model_meeting with injected fake seats (the established
test pattern), plus direct unit tests of the declarations module and
of the adapter/validator wiring.
"""

from __future__ import annotations

import pytest

from local_ai.build_room.declarations import (
    DECLARATION_BLOCK_VERSION,
    extract_declaration_block,
    parse_declaration_block,
)
from local_ai.build_room.meeting import (
    Budget,
    Claim,
    ClaimRegistry,
    EvidencePacket,
    _parse_claim_spans,
    run_multi_model_meeting,
)
from local_ai.build_room.participants import SEAT_SPECS, Seat
from local_ai.build_room.transjective_record import build_transjective_record


BLOCK = (
    "Declarations (declaration-block-v1):\n"
    "1: extends C12, challenges C18, integrates C24\n"
    "2: none"
)


def _claim(cid, who, phase, text, **kw):
    d = {"id": cid, "participant": who, "phase": phase, "text": text}
    d.update(kw)
    return d


def _native(claim, *, raw=None, declarations=None, state="populated",
            set_by="system", reason=None, failure=None):
    claim["declaration_raw"] = raw
    claim["declarations"] = declarations
    claim["target_state"] = state
    claim["target_state_set_by"] = set_by
    claim["uncertainty_reason"] = reason
    claim["declaration_parse_failure"] = failure
    return claim


def _errors_by_code(section):
    out: dict[str, set] = {}
    for e in section["validation"]["errors"]:
        out.setdefault(e["code"], set()).add(e.get("claim_id"))
    return out


# ---------------------------------------------------------------------------
# Extraction: block vs prose
# ---------------------------------------------------------------------------

def test_extract_splits_block_from_prose():
    text = ("1. Inferred: first claim.\n2. Proposed: second claim.\n\n"
            + BLOCK)
    prose, block = extract_declaration_block(text)
    assert block == BLOCK
    assert prose == "1. Inferred: first claim.\n2. Proposed: second claim."
    # Block lines never become claim spans.
    assert len(_parse_claim_spans(prose)) == 2


def test_extract_absent_returns_none():
    text = "1. Inferred: prose only, mentions C12 in passing."
    prose, block = extract_declaration_block(text)
    assert block is None and prose == text


def test_extract_unversioned_header_is_prose():
    text = ("1. Inferred: claim.\n\nDeclarations:\n1: extends C1")
    prose, block = extract_declaration_block(text)
    assert block is None


def test_extract_last_header_wins():
    text = ("Declarations (declaration-block-v1):\n1: extends C1\n\n"
            "Some prose.\n\n" + BLOCK)
    prose, block = extract_declaration_block(text)
    assert block == BLOCK
    assert "Some prose." in prose


# ---------------------------------------------------------------------------
# Acceptance 1: per-target parsing, incl. the multi-kind case
# ---------------------------------------------------------------------------

def test_multi_kind_parse():
    outs = parse_declaration_block(BLOCK, 2)
    decls = outs[0]["declarations"]
    assert outs[0]["target_state"] == "populated"
    assert [(d["kind"], d["target_claim"]) for d in decls] == [
        ("extends", "C12"), ("challenges", "C18"), ("integrates", "C24")]
    assert all(d["layer"] == "declared" for d in decls)
    assert outs[1]["target_state"] == "declared-none"
    assert outs[1]["target_state_set_by"] == "author"
    assert outs[1]["declarations"] == []


def test_other_with_note_and_dedup():
    block = ("Declarations (declaration-block-v1):\n"
             "1: other C5 (note: restates with new evidence), "
             "other C5 (note: restates with new evidence), endorses C6")
    outs = parse_declaration_block(block, 1)
    decls = outs[0]["declarations"]
    assert len(decls) == 2  # identical repetition deduplicates
    assert decls[0]["kind"] == "other"
    assert decls[0]["note"] == "restates with new evidence"
    assert decls[1]["kind"] == "endorses"


# ---------------------------------------------------------------------------
# Acceptance 5: explicitly empty block -> declared-none
# ---------------------------------------------------------------------------

def test_header_only_block_is_declared_none():
    outs = parse_declaration_block("Declarations (declaration-block-v1):", 2)
    assert all(o["target_state"] == "declared-none" for o in outs)
    assert all(o["target_state_set_by"] == "author" for o in outs)
    assert all(o["declarations"] == [] for o in outs)
    assert all(o["declaration_parse_failure"] is None for o in outs)


# ---------------------------------------------------------------------------
# Acceptance 4: absent vs malformed distinguishable
# ---------------------------------------------------------------------------

def test_absent_unknown_with_reason():
    out = parse_declaration_block(None, 1)[0]
    assert out["target_state"] == "unknown"
    assert out["uncertainty_reason"] == "no declaration emitted"
    assert out["declarations"] is None
    assert out["declaration_parse_failure"] is None


def test_no_entry_unknown_distinct_reason():
    outs = parse_declaration_block(
        "Declarations (declaration-block-v1):\n1: extends C3", 2)
    assert outs[1]["target_state"] == "unknown"
    assert outs[1]["uncertainty_reason"] == "no declaration entry for this claim"
    assert outs[1]["declaration_parse_failure"] is None


def test_malformed_variants_all_fail_closed():
    variants = [
        # unparseable line
        "Declarations (declaration-block-v1):\n1: blah blah",
        # duplicate ordinal
        "Declarations (declaration-block-v1):\n1: extends C3\n1: none",
        # out-of-range ordinal
        "Declarations (declaration-block-v1):\n5: extends C3",
        # none + targets in one entry
        "Declarations (declaration-block-v1):\n1: none, extends C3",
        # two kinds for one target
        "Declarations (declaration-block-v1):\n1: extends C3, challenges C3",
    ]
    for block in variants:
        outs = parse_declaration_block(block, 2)
        for out in outs:
            assert out["target_state"] == "unknown"
            assert out["uncertainty_reason"] == "malformed declaration block"
            assert out["declarations"] is None
            assert out["declaration_parse_failure"] is not None
            assert out["declaration_parse_failure"]["failures"]


# ---------------------------------------------------------------------------
# Acceptance 6: malformed -> E4 (bad kind) else E6 (garbage)
# ---------------------------------------------------------------------------

def test_invalid_kind_only_is_unknown_with_declaration_kept():
    outs = parse_declaration_block(
        "Declarations (declaration-block-v1):\n1: destroys C12", 1)
    out = outs[0]
    assert out["target_state"] == "unknown"
    assert out["uncertainty_reason"] == "malformed declaration block"
    assert out["declarations"] == [
        {"target_claim": "C12", "kind": "destroys",
         "layer": "declared", "note": None}]
    assert out["declaration_parse_failure"] is None


def test_invalid_kind_fires_e4_not_e6_via_validator():
    claims = [
        _claim("C1", "GPT", "opening", "Opening."),
        _native(_claim("C2", "Claude", "response", "Reply."),
                declarations=[{"target_claim": "C1", "kind": "destroys",
                               "layer": "declared", "note": None}],
                state="unknown", reason="malformed declaration block"),
    ]
    section = build_transjective_record(claims)
    errs = _errors_by_code(section)
    assert "C2" in errs.get("E4", set())
    assert "C2" not in errs.get("E6", set())


def test_structural_malformation_fires_e6_not_e4_via_validator():
    claims = [
        _claim("C1", "GPT", "opening", "Opening."),
        _native(_claim("C2", "Claude", "response", "Reply."),
                declarations=None, state="unknown",
                reason="malformed declaration block",
                failure={"reason": "malformed declaration block",
                         "failures": ["unparseable entry line"]}),
    ]
    section = build_transjective_record(claims)
    errs = _errors_by_code(section)
    assert "C2" in errs.get("E6", set())
    assert "C2" not in errs.get("E4", set())


def test_unknown_without_failure_field_fires_no_e6():
    # The E6 parse-failure rule needs the failure record: an absent
    # declaration (unknown + reason, no failure) warns W1 only.
    claims = [
        _claim("C1", "GPT", "opening", "Opening."),
        _native(_claim("C2", "Claude", "response", "Reply."),
                declarations=None, state="unknown",
                reason="no declaration emitted"),
    ]
    section = build_transjective_record(claims)
    errs = _errors_by_code(section)
    assert "E6" not in errs
    assert "W1" in section["validation"]["warning_counts"]


# ---------------------------------------------------------------------------
# Acceptance 3: prose-only claims produce NO declared records
# ---------------------------------------------------------------------------

def test_native_unknown_excludes_prose_derivation():
    # The response claim's prose mentions C1, but its native outcome
    # is absent: the adapter must NOT upgrade the prose mention into
    # a declaration for it (declared != inferred).
    claims = [
        _claim("C1", "GPT", "opening", "Opening."),
        _native(_claim("C2", "Claude", "response",
                       "In response to C1, the point stands."),
                declarations=None, state="unknown",
                reason="no declaration emitted"),
    ]
    section = build_transjective_record(claims)
    assert [d for d in section["declarations"]
            if d["source_claim"] == "C2"] == []
    assert section["target_states"]["C2"]["state"] == "unknown"


def test_old_claims_keep_prose_derivation():
    # Regression guard: claims WITHOUT native outcomes keep the
    # pre-A adapter behavior (prose links derive declarations and
    # make the state populated; a link-less response claim is
    # missing -> E5).
    claims = [
        _claim("C1", "GPT", "opening", "Opening."),
        _claim("C2", "Claude", "response", "Extends C1.",
               relationship="extends", relates_to=["C1"]),
        _claim("C3", "Gemini", "response", "Unlinked reply."),
    ]
    section = build_transjective_record(claims)
    assert any(d["source_claim"] == "C2" and d["target_claim"] == "C1"
               for d in section["declarations"])
    assert section["target_states"]["C2"]["state"] == "populated"
    assert section["target_states"]["C3"]["state"] == "missing"
    assert "E5" in section["validation"]["error_counts"]


def test_native_populated_flows_to_validator():
    claims = [
        _claim("C1", "GPT", "opening", "Opening."),
        _native(_claim("C2", "Claude", "response", "Reply."),
                declarations=[{"target_claim": "C1", "kind": "extends",
                               "layer": "declared", "note": None}]),
    ]
    section = build_transjective_record(claims)
    assert section["target_states"]["C2"]["state"] == "populated"
    assert "E5" not in section["validation"]["error_counts"]
    assert "E6" not in section["validation"]["error_counts"]


def test_native_declared_none_validated():
    claims = [
        _claim("C1", "GPT", "opening", "Opening."),
        _native(_claim("C2", "Claude", "response", "Reply."),
                declarations=[], state="declared-none", set_by="author"),
    ]
    section = build_transjective_record(claims)
    assert section["target_states"]["C2"]["state"] == "declared-none"
    assert "E6" not in section["validation"]["error_counts"]


# ---------------------------------------------------------------------------
# Claim integration + shape safety
# ---------------------------------------------------------------------------

def test_claim_to_dict_omits_native_keys_when_none():
    c = Claim(id="C1", participant="GPT", phase="opening", text="Hello.")
    keys = sorted(c.to_dict().keys())
    assert "exposure_ref" not in keys
    assert "declaration_raw" not in keys
    assert "declarations" not in keys
    assert "target_state" not in keys
    assert keys == ["assessment_sources", "disposition", "disposition_by",
                    "epistemic_assessment", "id", "participant", "phase",
                    "reclassified_status", "relates_to", "relationship",
                    "relationship_target", "relationship_targets", "status",
                    "supersedes", "text", "withdraws"]


def test_claim_to_dict_includes_native_keys_when_set():
    c = Claim(id="C1", participant="GPT", phase="response", text="Hi.",
              declaration_raw=BLOCK,
              declarations=[{"target_claim": "C12", "kind": "extends",
                             "layer": "declared", "note": None}],
              target_state="populated", target_state_set_by="system")
    d = c.to_dict()
    assert d["declaration_raw"] == BLOCK
    assert d["target_state"] == "populated"
    assert d["declarations"][0]["kind"] == "extends"


def test_register_spans_attaches_outcomes():
    reg = ClaimRegistry()
    spans = _parse_claim_spans("1. Inferred: first.\n2. Proposed: second.")
    outcomes = parse_declaration_block(BLOCK, 2)
    for outcome in outcomes:
        outcome["declaration_raw"] = BLOCK
    made = reg.register_spans("GPT", "response", spans,
                              declaration_outcomes=outcomes)
    assert len(made) == 2
    assert made[0].target_state == "populated"
    assert made[0].declaration_raw == BLOCK
    assert made[0].declarations[0]["kind"] == "extends"
    assert made[1].target_state == "declared-none"
    assert made[1].declarations == []
    # Short outcome lists leave tail claims without native outcomes.
    reg2 = ClaimRegistry()
    made2 = reg2.register_spans("GPT", "response", spans,
                                declaration_outcomes=outcomes[:1])
    assert made2[1].target_state is None
    assert "target_state" not in made2[1].to_dict()


# ---------------------------------------------------------------------------
# Runner hook end-to-end with fake participants (no live calls)
# ---------------------------------------------------------------------------

class _FakeParticipant:
    def __init__(self, name, *, opening="", response="", revision=""):
        self.name = name
        self.provider_id = dict((n, p) for n, p, _ in SEAT_SPECS)[name]
        self.model = "fake-model"
        self.key_source = "settings"
        self._texts = {"revision": revision, "response": response,
                       "opening": opening}
        self.prompts: list[str] = []

    def generate(self, prompt, *, timeout=120):
        self.prompts.append(prompt)
        if "state the relationship explicitly" in prompt:
            return self._texts["revision"]
        if "Claim registry" in prompt:
            return self._texts["response"]
        return self._texts["opening"]


def _packet():
    return EvidencePacket(
        work_item="Test work item",
        question="What would make the Build-Council Room fail?",
        excerpts=("excerpt one",),
        constraints=("room deliberates, never decides",),
        source_refs=("local_ai/build_room/meeting.py",),
    )


def _seats(fakes):
    seats = []
    for name, provider_id, model in SEAT_SPECS:
        fake = fakes.get(name)
        if fake is None:
            seats.append(Seat(name, provider_id, model, None,
                              absence_note=f"absent: no {provider_id} key"))
        else:
            seats.append(Seat(name, provider_id, model, fake))
    return seats


def _run(tmp_path, **kwargs):
    fakes = {
        "GPT": _FakeParticipant(
            "GPT",
            opening="1. Inferred: Authority confusion is a failure mode.\n"
                    "2. Proposed: Keep authorization with Joshua.",
            response="1. Inferred: The registry point stands.\n"
                     "2. Proposed: A second registry point.\n\n"
                     "Declarations (declaration-block-v1):\n"
                     "1: extends C3, integrates C4\n"
                     "2: none",
            revision="Relationship: defended.\nIn response to C7, I defend my claim:\n"
                     "1. Inferred: Authority confusion remains the top risk.\n\n"
                     "Declarations (declaration-block-v1):\n"
                     "1: defends C1",
        ),
        "Claude": _FakeParticipant(
            "Claude",
            opening="1. Inferred: Parallel monologues are a failure mode.",
            response="1. Objection to C1: authorization alone does not "
                     "prevent misrepresentation.\n\n"
                     "Declarations (declaration-block-v1):\n"
                     "1: challenges C1",
        ),
        "Muse": _FakeParticipant(
            "Muse",
            opening="1. Observed: A fourth opening claim.",
            # Prose-only response: mentions C1, emits no block.
            response="1. Inferred: The registry point stands, "
                     "in response to C1.",
        ),
    }
    return run_multi_model_meeting(_packet(), store_dir=tmp_path,
                                   seats=_seats(fakes), **kwargs), fakes


def test_runner_hook_end_to_end(tmp_path):
    result, fakes = _run(tmp_path)
    registry = result.artifact["claim_registry"]
    by_id = {c["id"]: c for c in registry}
    # Openings: GPT C1,C2; Claude C3; Muse C4. Responses: GPT C5,C6;
    # Claude C7; Muse C8. Revision: GPT C9.
    assert [c["phase"] for c in registry].count("opening") == 4
    assert [c["phase"] for c in registry].count("response") == 4
    assert [c["phase"] for c in registry].count("revision") == 1

    # Acceptance 2: raw block preserved byte-identically.
    gpt_block = ("Declarations (declaration-block-v1):\n"
                 "1: extends C3, integrates C4\n2: none")
    assert by_id["C5"]["declaration_raw"] == gpt_block
    assert by_id["C6"]["declaration_raw"] == gpt_block
    # Acceptance 1: per-target parsing through the runner.
    assert by_id["C5"]["target_state"] == "populated"
    assert [(d["kind"], d["target_claim"])
            for d in by_id["C5"]["declarations"]] == [
                ("extends", "C3"), ("integrates", "C4")]
    assert by_id["C6"]["target_state"] == "declared-none"
    assert by_id["C6"]["target_state_set_by"] == "author"
    assert by_id["C6"]["declarations"] == []
    assert by_id["C7"]["target_state"] == "populated"
    assert by_id["C7"]["declarations"][0]["kind"] == "challenges"
    assert by_id["C9"]["target_state"] == "populated"
    assert by_id["C9"]["declarations"][0]["kind"] == "defends"
    # Acceptance 3: prose-only response produces no declared records.
    assert by_id["C8"]["target_state"] == "unknown"
    assert by_id["C8"]["uncertainty_reason"] == "no declaration emitted"
    assert by_id["C8"].get("declarations") is None
    assert "declaration_raw" not in by_id["C8"]
    # Openings carry no native outcomes (no declaration prompt there).
    assert "target_state" not in by_id["C1"]

    # Block lines never became claim spans: GPT response registered
    # exactly its two prose claims, not the block lines.
    assert "registry point stands" in by_id["C5"]["text"]
    assert "second registry point" in by_id["C6"]["text"]
    assert "Declarations" not in by_id["C5"]["text"]
    assert "Declarations" not in by_id["C6"]["text"]

    # Prompt versioning: declaration instruction in response/revision
    # prompts only, version recorded in the capture.
    assert result.artifact["comparison_capture"][
        "declaration_prompt_version"] == DECLARATION_BLOCK_VERSION
    for fake in fakes.values():
        opening_prompts = [p for p in fake.prompts
                           if "Claim registry" not in p
                           and "state the relationship explicitly" not in p]
        assert all("Declarations (declaration-block-v1):" not in p
                   for p in opening_prompts)
    response_prompts = [p for p in fakes["GPT"].prompts
                        if "Claim registry" in p]
    assert response_prompts and all(
        "Declarations (declaration-block-v1):" in p
        for p in response_prompts)

    # Transjective section: native declarations flow through, and no
    # E5/E6/E4/E3/E12 for the natively declared claims.
    section = result.artifact["transjective_record"]
    decls = {(d["source_claim"], d["target_claim"]): d["kind"]
             for d in section["declarations"]}
    assert decls[("C5", "C3")] == "extends"
    assert decls[("C5", "C4")] == "integrates"
    assert decls[("C7", "C1")] == "challenges"
    assert decls[("C9", "C1")] == "defends"
    assert not [d for d in section["declarations"]
                if d["source_claim"] == "C8"]
    errs = _errors_by_code(section)
    for code in ("E5", "E6", "E4", "E3", "E12"):
        assert code not in errs, f"{code}: {errs.get(code)}"
    assert "W1" in section["validation"]["warning_counts"]
    # Registry standing section untouched and present.
    assert "claim_standing" in result.artifact


def test_prompt_version_override_recorded(tmp_path):
    result, _ = _run(tmp_path,
                     declaration_prompt_version="declaration-block-v9")
    assert result.artifact["comparison_capture"][
        "declaration_prompt_version"] == "declaration-block-v9"
