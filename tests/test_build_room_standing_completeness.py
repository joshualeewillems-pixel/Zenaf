"""Registry standing stage-2 tests: invariants + reporting headlines.

Pure-check tests run the standing-invariants check over a valid
table and deliberately broken variants — each broken table must fail
the standing check. Live-run tests prove the runner wires the check
and the standing report into real meetings. Generation is mocked —
no live API calls, no real key values.
"""

from __future__ import annotations

import copy
import time

from local_ai.build_room.claim_standing import (
    compute_claim_standing,
    format_standing_headline,
    render_standing_table,
)
from local_ai.build_room.meeting import EvidencePacket, run_multi_model_meeting
from local_ai.build_room.participants import SEAT_SPECS, Seat
from local_ai.build_room.record_completeness import check_record_completeness

NAMES = [name for name, _, _ in SEAT_SPECS]


def C(cid, participant, phase, status="unknown", **kw):
    d = {
        "id": cid,
        "participant": participant,
        "phase": phase,
        "text": "",
        "status": status,
        "relationship": None,
        "relationship_target": None,
        "supersedes": None,
        "withdraws": None,
        "epistemic_assessment": "unresolved",
        "assessment_sources": [],
    }
    d.update(kw)
    return d


def _record(table=None, claims=None):
    """Minimal valid original-four record plus a standing table."""
    if claims is None:
        claims = [
            C("C1", "GPT", "opening", "Observed"),
            C("C2", "Claude", "opening", "Inferred"),
            C("C3", "GPT", "revision", text="Revised.", supersedes="C1"),
        ]
    if table is None:
        table = compute_claim_standing(claims, [])
    return {
        "invited_generations": [
            {"phase": "opening", "participant": "GPT"},
            {"phase": "opening", "participant": "Claude"},
            {"phase": "revision", "participant": "GPT"},
        ],
        "generation_outcomes": [
            {"phase": "opening", "participant": "GPT", "status": "completed", "reason": None},
            {"phase": "opening", "participant": "Claude", "status": "completed", "reason": None},
            {"phase": "revision", "participant": "GPT", "status": "completed", "reason": None},
        ],
        "transcript_entries": [
            {"kind": "contribution", "participant": "GPT"},
            {"kind": "contribution", "participant": "Claude"},
            {"kind": "contribution", "participant": "GPT"},
        ],
        "claims": [
            {"id": c["id"], "participant": c["participant"], "phase": c["phase"]}
            for c in claims
        ],
        "verified_challenges": [],
        "revision_claims": [
            {"id": "C3", "participant": "GPT",
             "relationship_target": "C1", "relates_to": []}
        ],
        "unresolved_objections": [],
        "claims_full": claims,
        "interactions": [],
        "standing_table": table,
    }


def _standing_failures(result):
    check = result["checks"]["standing_invariants"]
    assert check["passed"] is False
    return check["failures"]


# ---------------------------------------------------------------- headlines

def test_headline_renders_three_dimensions():
    entry = {
        "claim_id": "C6",
        "authored_status": "Observed",
        "standing": "active",
        "assessment": "challenged",
        "provenance": "unverified",
        "retraction_signals": [{"by": "C56", "kind": "signal"}],
    }
    assert format_standing_headline(entry) == (
        "C6 [authored: Observed | standing: active | assessment: challenged "
        "| retraction signal: present | provenance: unverified]"
    )
    assert format_standing_headline({**entry, "retraction_signals": []}).endswith(
        "retraction signal: none | provenance: unverified]")
    assert format_standing_headline(
        {**entry, "retraction_signals": [{"by": "C4", "kind": "ambiguous"}]}
    ).endswith("retraction signal: present (ambiguous) | provenance: unverified]")


def test_table_render_is_deterministic_and_ordered():
    table = compute_claim_standing(
        [C("C1", "GPT", "opening", "Observed"),
         C("C2", "Claude", "opening", "Inferred")], [])
    rendered = render_standing_table(table)
    lines = rendered.split("\n")
    assert lines[0].startswith("Claim standing (derived")
    assert lines[1].startswith("C1 [")
    assert lines[2].startswith("C2 [")
    assert render_standing_table(table) == rendered


# ---------------------------------------------------------------- pure checks

def test_clean_record_passes_all_five_checks():
    result = check_record_completeness(**_record())
    assert result["passed"] is True
    assert set(result["checks"]) == {
        "invited_generations_accounted",
        "claim_ids_sequential",
        "transcript_generation_parity",
        "unresolved_objection_derivation",
        "standing_invariants",
    }
    assert result["checks"]["standing_invariants"]["failures"] == []


def test_check_without_standing_inputs_keeps_original_four():
    record = _record()
    for key in ("claims_full", "interactions", "standing_table"):
        del record[key]
    result = check_record_completeness(**record)
    assert result["passed"] is True
    assert "standing_invariants" not in result["checks"]
    assert len(result["checks"]) == 4


def test_entry_for_unknown_claim_fails():
    record = _record()
    table = copy.deepcopy(record["standing_table"])
    table["entries"][0]["claim_id"] = "C99"
    record["standing_table"] = table
    failures = _standing_failures(check_record_completeness(**record))
    assert any("unknown claim: C99" in f for f in failures)


def test_duplicate_and_missing_entries_fail():
    record = _record()
    table = copy.deepcopy(record["standing_table"])
    table["entries"].append(copy.deepcopy(table["entries"][0]))
    record["standing_table"] = table
    failures = _standing_failures(check_record_completeness(**record))
    assert any("duplicate standing entries" in f for f in failures)

    record = _record()
    table = copy.deepcopy(record["standing_table"])
    table["entries"] = table["entries"][:-1]
    record["standing_table"] = table
    failures = _standing_failures(check_record_completeness(**record))
    assert any("without standing entry" in f for f in failures)


def test_cross_author_and_unlinked_moves_fail():
    claims = [
        C("C1", "GPT", "opening", "Observed"),
        C("C2", "Claude", "revision", text="Revised."),
    ]
    table = compute_claim_standing(claims, [])
    # Hand-craft a cross-author chain move onto C1.
    table["entries"][0]["standing_chain"] = [
        {"move": "supersession", "by": "C2", "target": "C1"}
    ]
    table["entries"][0]["standing"] = "superseded"
    record = _record(table=table, claims=claims)
    failures = _standing_failures(check_record_completeness(**record))
    assert any("cross-author" in f for f in failures)

    # A chain move whose mover's link does not name the target.
    claims = [
        C("C1", "GPT", "opening", "Observed"),
        C("C2", "GPT", "revision", text="Revised.", supersedes="C1"),
    ]
    table = compute_claim_standing(claims, [])
    table["entries"][0]["standing_chain"] = [
        {"move": "withdrawal", "by": "C2", "target": "C1"}
    ]
    table["entries"][0]["standing"] = "withdrawn"
    record = _record(table=table, claims=claims)
    failures = _standing_failures(check_record_completeness(**record))
    assert any("without matching source link" in f for f in failures)

    # A chain move whose source claim does not exist.
    table = compute_claim_standing(claims, [])
    table["entries"][0]["standing_chain"] = [
        {"move": "withdrawal", "by": "C99", "target": "C1"}
    ]
    table["entries"][0]["standing"] = "withdrawn"
    record = _record(table=table, claims=claims)
    failures = _standing_failures(check_record_completeness(**record))
    assert any("without source claim" in f for f in failures)


def test_forward_reference_and_unordered_chain_fail():
    claims = [
        C("C1", "GPT", "opening", "Observed"),
        C("C2", "GPT", "revision", text="Revised.", supersedes="C1"),
        C("C3", "GPT", "revision", text="Withdrawn.", withdraws="C1"),
    ]
    table = compute_claim_standing(claims, [])
    # Mover earlier than its target: put C1's own move on C3's entry.
    table["entries"][2]["standing_chain"] = [
        {"move": "supersession", "by": "C1", "target": "C3"}
    ]
    record = _record(table=table, claims=claims)
    failures = _standing_failures(check_record_completeness(**record))
    assert any("not to an earlier claim" in f for f in failures)

    # Valid chain reversed: moves out of transcript order.
    table = compute_claim_standing(claims, [])
    chain = table["entries"][0]["standing_chain"]
    assert len(chain) == 2
    table["entries"][0]["standing_chain"] = list(reversed(chain))
    record = _record(table=table, claims=claims)
    failures = _standing_failures(check_record_completeness(**record))
    assert any("not deterministically ordered" in f for f in failures)


def test_recomputation_mismatch_fails_alone():
    record = _record()
    table = copy.deepcopy(record["standing_table"])
    # Standing value changed, chain untouched: only recomputation fails.
    table["entries"][1]["standing"] = "withdrawn"
    record["standing_table"] = table
    failures = _standing_failures(check_record_completeness(**record))
    assert failures == [
        "standing table differs from recomputation (first differing: C2)"
    ]


# ---------------------------------------------------------------- live runs

class FakeParticipant:
    """Duck-typed seat participant: generate(prompt, timeout=...)."""

    def __init__(self, name, *, opening="", response="", revision=""):
        self.name = name
        self.provider_id = dict((n, p) for n, p, _ in SEAT_SPECS)[name]
        self.model = "fake-model"
        self.key_source = "settings"
        self._texts = {
            "revision": revision,
            "response": response,
            "opening": opening,
        }

    def generate(self, prompt, *, timeout=120):
        if "state the relationship explicitly" in prompt:
            return self._texts["revision"]
        if "Claim registry" in prompt:
            return self._texts["response"]
        return self._texts["opening"]


def _packet() -> EvidencePacket:
    return EvidencePacket(
        work_item="Test work item",
        question="What would make the Build-Council Room fail to function as a genuine deliberative council?",
        excerpts=("excerpt one",),
        constraints=("room deliberates, never decides",),
        source_refs=("local_ai/build_room/meeting.py",),
    )


def _seats(fakes) -> list[Seat]:
    seats = []
    for name, provider_id, model in SEAT_SPECS:
        fake = fakes.get(name, FakeParticipant(name, opening="1. Inferred: nothing yet."))
        if fake is None:
            seats.append(Seat(name, provider_id, model, None,
                              absence_note=f"absent: no {provider_id} api key present"))
        else:
            seats.append(Seat(name, provider_id, model, fake))
    return seats


def test_live_meeting_artifact_carries_standing_check_and_report(tmp_path):
    fakes = {
        "GPT": FakeParticipant(
            "GPT",
            opening="1. Observed: Authority confusion is a failure mode.\n2. Proposed: Keep authorization with Joshua.",
            response="In response to C3, I agree: the registry point stands.",
            revision="Relationship: revised.\nIn response to C1, I revise my claim:\n"
                     "1. Inferred: Authority confusion remains the top risk.",
        ),
        "Claude": FakeParticipant(
            "Claude",
            opening="1. Inferred: Parallel monologues are a failure mode.",
            response="1. Objection to C1: authorization alone does not "
                     "prevent misrepresentation.",
        ),
        "Gemini": FakeParticipant("Gemini", opening="1. Proposed: Add addressable claims."),
        "Grok": FakeParticipant("Grok", opening="1. Speculative: The room may perform deliberation."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Cost grows with participants."),
    }
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path,
                                     seats=_seats(fakes))
    assert result.ok is True
    artifact = result.artifact
    assert artifact["record_complete"] is True
    rc = artifact["record_completeness"]
    assert rc["passed"] is True
    assert rc["checks"]["standing_invariants"]["passed"] is True
    assert rc["checks"]["standing_invariants"]["failures"] == []
    # The artifact's standing section and its rendering agree, and
    # the same-author revision superseded GPT's opening claim C1.
    table = artifact["claim_standing"]
    assert len(table["entries"]) == len(artifact["claim_registry"])
    c1 = next(e for e in table["entries"] if e["claim_id"] == "C1")
    assert c1["standing"] == "superseded"
    assert c1["standing_chain"][0]["move"] == "supersession"
    report = artifact["standing_report"]
    assert "C1 [authored: Observed | standing: superseded |" in report
    assert "assessment:" in report and "provenance:" in report
    # The rendered report persists with the artifact file.
    import json
    persisted = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert persisted["record_completeness"]["checks"]["standing_invariants"]["passed"] is True
    assert persisted["standing_report"] == report
