"""Increment B tests: exposure capture at generation time.

No live generations, no provider calls, no real keys anywhere. Fake
participants return canned text; the runner hook is exercised through
run_multi_model_meeting with injected fake seats (the established
test pattern), plus direct unit tests of the exposure module.
"""

from __future__ import annotations

import hashlib

import pytest

from local_ai.build_room.exposure import (
    REGISTRY_HEADER,
    capture_exposure,
    extract_presented_claims,
    truncation_record,
    unknown_exposure,
)
from local_ai.build_room.meeting import (
    Budget,
    Claim,
    ClaimRegistry,
    EvidencePacket,
    run_multi_model_meeting,
)
from local_ai.build_room.participants import SEAT_SPECS, Seat
from local_ai.build_room.transjective_record import (
    build_transjective_record,
    validate_contract_record,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _block(*claims):
    """A registry render: header + one line per (id, participant, status, text)."""
    lines = [REGISTRY_HEADER]
    for cid, who, status, text in claims:
        lines.append(f"{cid} [{who}, {status}]: {text}")
    return "\n".join(lines)


def _payload(block, *, mention=""):
    """A realistic prompt: packet prose (with bare mentions) + registry + instruction."""
    return (
        "Work item:\nTest work item\n\nQuestion:\nIs this sound?\n\n"
        f"Note: earlier discussion mentioned {mention} in passing.\n\n"
        f"{block}\n\n"
        "Respond as a single deliberation contribution.\n"
    )


def _claim(cid, who, phase, text, **kw):
    d = {"id": cid, "participant": who, "phase": phase, "text": text}
    d.update(kw)
    return d


# ---------------------------------------------------------------------------
# Extraction: presented vs mentioned
# ---------------------------------------------------------------------------

def test_extract_basic_order_spans_section():
    block = _block(
        ("C1", "GPT", "Observed", "First claim."),
        ("C2", "Claude", "Inferred", "Second claim."),
    )
    payload = _payload(block)
    offset = payload.index(block)
    out = extract_presented_claims(block, base_offset=offset,
                                   base_line=payload[:offset].count("\n"))
    assert [p["claim_id"] for p in out] == ["C1", "C2"]
    assert out[0]["participant"] == "GPT" and out[0]["status"] == "Observed"
    assert all(p["section"] == "claim_registry" for p in out)
    for p in out:
        line = payload[p["start_offset"]:p["end_offset"]]
        assert line.startswith(p["claim_id"] + " [")
    assert out[0]["line"] < out[1]["line"]


def test_mentioned_ids_are_not_visible():
    block = _block(
        ("C1", "GPT", "Observed", "First claim mentions C2 in its text."),
        ("C2", "Claude", "Inferred", "Second claim."),
    )
    # Prose mentions C99 (never presented) and C1 (presented elsewhere).
    payload = _payload(block, mention="C99 and C1")
    out = extract_presented_claims(block)
    assert [p["claim_id"] for p in out] == ["C1", "C2"]
    assert "C99" not in [p["claim_id"] for p in out]


def test_extract_rejects_malformed_blocks():
    with pytest.raises(ValueError):
        extract_presented_claims("No header here\nC1 [GPT, Observed]: x.")
    with pytest.raises(ValueError):
        extract_presented_claims(_block(("C1", "GPT", "Observed", "x.")) + "\n\nNot a registry line.")
    with pytest.raises(ValueError):
        extract_presented_claims(_block(
            ("C1", "GPT", "Observed", "x."),
            ("C1", "Claude", "Inferred", "duplicate."),
        ))


def test_capture_requires_block_in_payload():
    block = _block(("C1", "GPT", "Observed", "x."))
    with pytest.raises(ValueError):
        capture_exposure("Unrelated prompt with no registry.",
                         block, window_id="w1")


def test_empty_block_visible_empty():
    payload = _payload("", mention="C7")
    rec = capture_exposure(payload, "", window_id="w1")
    assert rec["visible_ids"] == [] and rec["visible_spans"] == []
    assert rec["evidence"] == "present"


# ---------------------------------------------------------------------------
# Payload fidelity + truncation
# ---------------------------------------------------------------------------

def test_payload_hash_is_exact_and_binding():
    block = _block(("C1", "GPT", "Observed", "x."))
    payload = _payload(block)
    rec = capture_exposure(payload, block, window_id="declared-window:fake:100")
    assert rec["payload_hash"] == hashlib.sha256(payload.encode()).hexdigest()
    assert rec["payload_ref"] == f"payload_evidence:{rec['payload_hash']}"
    assert rec["window_id"] == "declared-window:fake:100"
    tampered = payload + " "
    rec2 = capture_exposure(tampered, block, window_id="w")
    assert rec2["payload_hash"] != rec["payload_hash"]


def test_truncated_payload_excludes_dropped():
    full = _block(
        ("C1", "GPT", "Observed", "one."),
        ("C2", "Claude", "Inferred", "two."),
        ("C3", "Gemini", "Proposed", "three."),
        ("C4", "Grok", "Speculative", "four."),
    )
    truncated = _block(
        ("C1", "GPT", "Observed", "one."),
        ("C2", "Claude", "Inferred", "two."),
        ("C4", "Grok", "Speculative", "four."),
    )
    payload = _payload(truncated)
    rec = capture_exposure(
        payload, truncated, window_id="w",
        transformations=[truncation_record(["C3"], policy="window-cap")],
    )
    assert rec["visible_ids"] == ["C1", "C2", "C4"]
    assert rec["transformations"][0]["dropped_claim_ids"] == ["C3"]
    assert rec["transformations"][0]["policy"] == "window-cap"


def test_transformation_claiming_visible_drop_raises():
    block = _block(("C1", "GPT", "Observed", "x."),
                   ("C2", "Claude", "Inferred", "y."))
    with pytest.raises(ValueError):
        capture_exposure(_payload(block), block, window_id="w",
                         transformations=[truncation_record(["C2"], policy="p")])


def test_truncation_record_shape():
    tr = truncation_record(["C3", "C1"], policy="window-cap")
    assert tr == {"kind": "truncated", "dropped_claim_ids": ["C3", "C1"],
                  "policy": "window-cap", "order": "registry order"}


# ---------------------------------------------------------------------------
# Failure honesty
# ---------------------------------------------------------------------------

def test_unknown_absent_and_temp():
    rec = unknown_exposure("no payload captured", capture_method="test")
    assert rec["evidence"] == "absent" and rec["visible_ids"] is None
    assert rec["payload_ref"] is None and rec["reason"] == "no payload captured"
    with pytest.raises(ValueError):
        unknown_exposure("x", temporarily=True)  # pending_ref required


def test_unknown_temp_interim_warns_final_errors_via_adapter():
    claims = [
        _claim("C1", "GPT", "opening", "Opening."),
        _claim("C2", "Claude", "response", "Reply.",
               exposure_ref=unknown_exposure("evidence delayed", temporarily=True,
                                             pending_ref="pending:test-1")),
    ]
    section = build_transjective_record(claims, validation_phase="interim")
    assert "W2" in section["validation"]["warning_counts"]
    e12_claims = {e.get("claim_id") for e in section["validation"]["errors"]
                  if e["code"] == "E12"}
    assert e12_claims == {"C1"}  # C1 is old-style (absent); C2 temp warns only
    section = build_transjective_record(claims, validation_phase="final")
    e12_claims = {e.get("claim_id") for e in section["validation"]["errors"]
                  if e["code"] == "E12"}
    assert e12_claims == {"C1", "C2"}  # temp evidence escalates to E12 at close


def test_unknown_absent_errors_e12_via_adapter():
    claims = [_claim("C1", "GPT", "opening", "Opening.",
                     exposure_ref=unknown_exposure("capture impossible"))]
    section = build_transjective_record(claims)
    assert "E12" in section["validation"]["error_counts"]


def test_malformed_native_evidence_fails_closed():
    claims = [_claim("C1", "GPT", "opening", "Opening.",
                     exposure_ref={"payload_hash": "abc", "payload_ref": "x",
                                   "evidence": "bogus", "visible_ids": []})]
    section = build_transjective_record(claims)
    assert "E12" in section["validation"]["error_counts"]


# ---------------------------------------------------------------------------
# Claim integration + validator wiring (existing validator, not forked)
# ---------------------------------------------------------------------------

def test_claim_to_dict_omits_exposure_when_none():
    c = Claim(id="C1", participant="GPT", phase="opening", text="Hello.")
    keys = sorted(c.to_dict().keys())
    assert "exposure_ref" not in keys
    assert keys == ["assessment_sources", "disposition", "disposition_by",
                    "epistemic_assessment", "id", "participant", "phase",
                    "reclassified_status", "relates_to", "relationship",
                    "relationship_target", "relationship_targets", "status",
                    "supersedes", "text", "withdraws"]


def test_claim_to_dict_includes_exposure_when_set():
    ref = {"payload_hash": "abc", "evidence": "present", "visible_ids": []}
    c = Claim(id="C1", participant="GPT", phase="opening", text="Hi.",
              exposure_ref=ref)
    assert c.to_dict()["exposure_ref"] == ref


def test_register_spans_attaches_exposure():
    reg = ClaimRegistry()
    ref = {"payload_hash": "abc", "evidence": "present", "visible_ids": []}
    from local_ai.build_room.meeting import _parse_claim_spans
    spans = _parse_claim_spans("1. Inferred: first.\n2. Proposed: second.")
    made = reg.register_spans("GPT", "opening", spans, exposure_ref=ref)
    assert len(made) == 2
    assert all(c.exposure_ref == ref for c in made)
    assert all("exposure_ref" in c.to_dict() for c in made)


def test_register_passes_exposure_through():
    reg = ClaimRegistry()
    ref = {"payload_hash": "abc", "evidence": "present", "visible_ids": []}
    made = reg.register("GPT", "opening", "1. Inferred: only.",
                        exposure_ref=ref)
    assert made[0].exposure_ref == ref


def test_native_exposure_feeds_validator_e3():
    block = _block(("C1", "GPT", "Observed", "Opening."))
    payload = _payload(block)
    ref = capture_exposure(payload, block, window_id="w")
    # C2 declares on visible C1: no E3, no E12 for C2.
    claims = [
        _claim("C1", "GPT", "opening", "Opening.", exposure_ref=ref),
        _claim("C2", "Claude", "response", "Extends C1.",
               relationship="extends", relates_to=["C1"], exposure_ref=ref),
    ]
    section = build_transjective_record(claims)
    assert "E3" not in section["validation"]["error_counts"]
    assert "E12" not in section["validation"]["error_counts"]
    # C4 declares on C3, which exists but is NOT in C4's visible set: E3.
    claims = [
        _claim("C1", "GPT", "opening", "one.", exposure_ref=ref),
        _claim("C3", "Gemini", "opening", "three.",
               exposure_ref=capture_exposure(
                   _payload(_block(("C1", "GPT", "Observed", "one."),
                                   ("C3", "Gemini", "Proposed", "three."))),
                   _block(("C1", "GPT", "Observed", "one."),
                          ("C3", "Gemini", "Proposed", "three.")),
                   window_id="w")),
        _claim("C4", "Gemini", "response", "About C3.",
               relationship="extends", relates_to=["C3"], exposure_ref=ref),
    ]
    section = build_transjective_record(claims)
    assert "E3" in section["validation"]["error_counts"]
    # Declaration to a nonexistent target is E1 (dangling), not E3.
    claims = [
        _claim("C1", "GPT", "opening", "Opening.", exposure_ref=ref),
        _claim("C2", "Claude", "response", "Extends C9.",
               relationship="extends", relates_to=["C9"], exposure_ref=ref),
    ]
    section = build_transjective_record(claims)
    assert "E1" in section["validation"]["error_counts"]
    assert "E3" not in section["validation"]["error_counts"]


def test_e3_gate_is_present_evidence_only():
    # Pre-existing validator property (PR #281), documented here so the
    # module's "present" vocabulary choice is auditable: a hand-built
    # record with a non-"present" evidence label skips E3 even with a
    # visible list. Native captures emit "present" and never hit this.
    claims = [
        _claim("C1", "GPT", "opening", "one.",
               exposure_ref={"payload_hash": "h", "payload_ref": "p",
                             "evidence": "available", "visible_ids": ["C1"]}),
        _claim("C3", "Gemini", "opening", "three.",
               exposure_ref={"payload_hash": "h", "payload_ref": "p",
                             "evidence": "available",
                             "visible_ids": ["C1", "C3"]}),
        _claim("C4", "Gemini", "response", "About C3.",
               relationship="extends", relates_to=["C3"],
               exposure_ref={"payload_hash": "h", "payload_ref": "p",
                             "evidence": "available", "visible_ids": ["C1"]}),
    ]
    section = build_transjective_record(claims)
    assert "E3" not in section["validation"]["error_counts"]


def test_truncated_target_e3_through_validator():
    truncated = _block(("C1", "GPT", "Observed", "one."),
                       ("C2", "Claude", "Inferred", "two."))
    ref = capture_exposure(
        _payload(truncated), truncated, window_id="w",
        transformations=[truncation_record(["C3"], policy="window-cap")])
    claims = [
        _claim("C1", "GPT", "opening", "one.", exposure_ref=ref),
        _claim("C2", "Claude", "opening", "two.", exposure_ref=ref),
        _claim("C5", "Gemini", "response", "About C3.",
               relationship="extends", relates_to=["C3"], exposure_ref=ref),
    ]
    # C3 is not a claim in this record at all -> E1 (unknown target);
    # the visibility case needs C3 present-but-not-visible, covered next.
    section = build_transjective_record(claims)
    assert "E1" in section["validation"]["error_counts"]
    claims = [
        _claim("C1", "GPT", "opening", "one.", exposure_ref=ref),
        _claim("C2", "Claude", "opening", "two.", exposure_ref=ref),
        _claim("C3", "Gemini", "opening", "three.",
               exposure_ref=capture_exposure(
                   _payload(_block(("C1", "GPT", "Observed", "one."),
                                   ("C2", "Claude", "Inferred", "two."),
                                   ("C3", "Gemini", "Proposed", "three."))),
                   _block(("C1", "GPT", "Observed", "one."),
                          ("C2", "Claude", "Inferred", "two."),
                          ("C3", "Gemini", "Proposed", "three.")),
                   window_id="w")),
        _claim("C5", "Gemini", "response", "About C3.",
               relationship="extends", relates_to=["C3"], exposure_ref=ref),
    ]
    section = build_transjective_record(claims)
    assert "E3" in section["validation"]["error_counts"]


def test_build_section_payload_evidence_key():
    claims = [_claim("C1", "GPT", "opening", "Opening.")]
    section = build_transjective_record(claims)
    assert "payload_evidence" not in section
    assert "exposure" in section
    assert section["exposure"]["C1"]["evidence"] == "absent"
    section = build_transjective_record(
        claims, payload_evidence={"deadbeef": "payload text"})
    assert section["payload_evidence"] == {"deadbeef": "payload text"}


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


def test_runner_hook_attaches_exposure_end_to_end(tmp_path):
    fakes = {
        "GPT": _FakeParticipant(
            "GPT",
            opening="1. Inferred: Authority confusion is a failure mode.\n"
                    "2. Proposed: Keep authorization with Joshua.",
            response="1. Inferred: The registry point stands.",
            revision="Relationship: defended.\nIn response to C1, I defend my claim:\n"
                     "1. Inferred: Authority confusion remains the top risk.",
        ),
        "Claude": _FakeParticipant(
            "Claude",
            opening="1. Inferred: Parallel monologues are a failure mode.",
            response="1. Objection to C1: authorization alone does not "
                     "prevent misrepresentation.",
        ),
    }
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path,
                                     seats=_seats(fakes))
    registry = result.artifact["claim_registry"]
    assert registry, "expected registered claims"
    by_phase = {}
    for c in registry:
        by_phase.setdefault(c["phase"], []).append(c["id"])
    opening_ids = by_phase.get("opening", [])
    response_ids = by_phase.get("response", [])
    revision_ids = by_phase.get("revision", [])
    assert opening_ids and response_ids and revision_ids

    def prompt_for(fake, marker):
        hits = [p for p in fake.prompts if marker in p]
        assert hits, f"no {marker} prompt recorded"
        return hits[0]

    for c in registry:
        ref = c.get("exposure_ref")
        assert ref is not None, f"{c['id']} missing exposure_ref"
        assert ref["evidence"] == "present"
        assert ref["payload_ref"] == f"payload_evidence:{ref['payload_hash']}"
        if c["phase"] == "opening":
            assert ref["visible_ids"] == []
        elif c["phase"] == "response":
            assert ref["visible_ids"] == opening_ids
            # Payload fidelity: hash matches the exact prompt the fake saw.
            prompt = prompt_for(fakes[c["participant"]], "Claim registry")
            assert ref["payload_hash"] == hashlib.sha256(
                prompt.encode()).hexdigest()
        elif c["phase"] == "revision":
            assert ref["visible_ids"] == opening_ids + response_ids

    section = result.artifact["transjective_record"]
    # Payload copies retrievable in the artifact, keyed by hash.
    assert section["payload_evidence"]
    for c in registry:
        h = c["exposure_ref"]["payload_hash"]
        assert h in section["payload_evidence"]
        assert section["exposure"][c["id"]]["evidence"] == "present"
        assert section["exposure"][c["id"]]["visible_ids"] == \
            c["exposure_ref"]["visible_ids"]
    # No E12 for any natively exposed claim.
    e12_claims = {e.get("claim_id") for e in
                  section["validation"]["errors"] if e["code"] == "E12"}
    assert not e12_claims
    # Registry standing section untouched and present.
    assert "claim_standing" in result.artifact
