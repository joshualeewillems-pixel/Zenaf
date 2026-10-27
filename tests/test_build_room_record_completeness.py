"""Stage 2 tests: record-completeness checks (design §4).

Pure-check tests run the checker over a hand-built record and over
deliberately broken variants (a gap, a missing generation, a
mismatched transcript, a wrong derivation) — each broken record must
fail exactly the check it breaks. Live-run tests prove the runner
wires the checks into real meetings, including budget-blocked and
provider-down generations, which are accounted for, not dropped.
Generation is mocked — no live API calls, no real key values.
"""

from __future__ import annotations

import copy
import time

from local_ai.build_room.meeting import (
    Budget,
    EvidencePacket,
    replay_r2_transcript,
    run_multi_model_meeting,
)
from local_ai.build_room.participants import SEAT_SPECS, Seat
from local_ai.build_room.record_completeness import check_record_completeness

NAMES = [name for name, _, _ in SEAT_SPECS]
CHECKS = (
    "invited_generations_accounted",
    "claim_ids_sequential",
    "transcript_generation_parity",
    "unresolved_objection_derivation",
)


# ---------------------------------------------------------------- pure checks

def _clean_record():
    """A whole record: 2 openings + 2 responses (1 failed) + 1 revision.

    GPT opens C1–C2, Claude opens C3, GPT responds C4 (objecting to
    C3), Claude's response fails, GPT revises C5 without responding
    to anything — so the C3 objection stays unresolved.
    """
    return {
        "invited_generations": [
            {"phase": "opening", "participant": "GPT"},
            {"phase": "opening", "participant": "Claude"},
            {"phase": "response", "participant": "GPT"},
            {"phase": "response", "participant": "Claude"},
            {"phase": "revision", "participant": "GPT"},
        ],
        "generation_outcomes": [
            {"phase": "opening", "participant": "GPT", "status": "completed", "reason": None},
            {"phase": "opening", "participant": "Claude", "status": "completed", "reason": None},
            {"phase": "response", "participant": "GPT", "status": "completed", "reason": None},
            {"phase": "response", "participant": "Claude", "status": "failed",
             "reason": "RuntimeError: provider exploded"},
            {"phase": "revision", "participant": "GPT", "status": "completed", "reason": None},
        ],
        "transcript_entries": [
            {"kind": "convene", "participant": "Reynard (convener)"},
            {"kind": "contribution", "participant": "GPT"},
            {"kind": "contribution", "participant": "Claude"},
            {"kind": "contribution", "participant": "GPT"},
            {"kind": "failure", "participant": "Claude"},
            {"kind": "contribution", "participant": "GPT"},
            # Convener-level failure note: not a generation record,
            # must be ignored by the parity check, not flagged.
            {"kind": "failure", "participant": "Reynard (convener)"},
        ],
        "claims": [
            {"id": "C1", "participant": "GPT", "phase": "opening"},
            {"id": "C2", "participant": "GPT", "phase": "opening"},
            {"id": "C3", "participant": "Claude", "phase": "opening"},
            {"id": "C4", "participant": "GPT", "phase": "response"},
            {"id": "C5", "participant": "GPT", "phase": "revision"},
        ],
        "verified_challenges": [
            {"target_claim_id": "C3", "source_claim_id": "C4",
             "challenger": "GPT", "move": "objection"},
        ],
        "revision_claims": [
            {"id": "C5", "participant": "GPT", "relationship_target": None,
             "relates_to": []},
        ],
        "unresolved_objections": [
            {"claim_id": "C3", "originator": "Claude", "cited_by": "GPT",
             "moves": ["objection"], "source_claim_id": "C4",
             "state": "unresolved", "responded_by": None},
        ],
    }


def _check(record):
    return check_record_completeness(**record)


def _only_fails(result, name):
    assert result["passed"] is False
    for check in CHECKS:
        if check == name:
            assert result["checks"][check]["passed"] is False
            assert result["checks"][check]["failures"]
        else:
            assert result["checks"][check]["passed"] is True, check


def test_clean_record_passes_all_checks():
    result = _check(_clean_record())
    assert result["passed"] is True
    for check in CHECKS:
        assert result["checks"][check]["passed"] is True
        assert result["checks"][check]["failures"] == []


def test_missing_generation_outcome_fails_check_a_only():
    record = _clean_record()
    record["generation_outcomes"] = [
        o for o in record["generation_outcomes"]
        if not (o["phase"] == "revision" and o["participant"] == "GPT")]
    # Keep transcript parity consistent with the outcomes (drop the
    # revision contribution entry too) so only check (a) fires: the
    # break is the missing outcome, not a transcript mismatch.
    record["transcript_entries"] = record["transcript_entries"][:-2] + \
        record["transcript_entries"][-1:]
    _only_fails(_check(record), "invited_generations_accounted")


def test_failure_without_reason_fails_check_a_only():
    record = _clean_record()
    for o in record["generation_outcomes"]:
        if o["status"] == "failed":
            o["reason"] = None
    _only_fails(_check(record), "invited_generations_accounted")


def test_outcome_without_invitation_fails_check_a_only():
    record = _clean_record()
    record["generation_outcomes"].append(
        {"phase": "response", "participant": "Muse",
         "status": "completed", "reason": None})
    _only_fails(_check(record), "invited_generations_accounted")


def test_duplicate_outcome_fails_check_a_only():
    record = _clean_record()
    record["generation_outcomes"].append(
        {"phase": "opening", "participant": "GPT",
         "status": "completed", "reason": None})
    # Keep transcript parity consistent with the outcomes (mirror
    # the duplicate contribution) so only check (a) fires.
    record["transcript_entries"].append(
        {"kind": "contribution", "participant": "GPT"})
    _only_fails(_check(record), "invited_generations_accounted")


def test_claim_id_gap_fails_check_b_only():
    record = _clean_record()
    record["claims"][2]["id"] = "C4"
    record["claims"][3]["id"] = "C5"
    record["claims"][4]["id"] = "C6"
    # Renumber the derivation consistently (target C3 -> C4, source
    # C4 -> C5) so only check (b) fires: the break is the ID gap.
    record["verified_challenges"][0]["target_claim_id"] = "C4"
    record["verified_challenges"][0]["source_claim_id"] = "C5"
    record["unresolved_objections"][0]["claim_id"] = "C4"
    record["unresolved_objections"][0]["source_claim_id"] = "C5"
    _only_fails(_check(record), "claim_ids_sequential")


def test_claim_id_duplicate_fails_check_b_only():
    record = _clean_record()
    record["claims"][1]["id"] = "C1"
    _only_fails(_check(record), "claim_ids_sequential")


def test_noncontiguous_group_fails_check_b_only():
    # Global order still C1..C5, but GPT's opening claims are no
    # longer a contiguous run: C1 (GPT opening), C2 (Claude
    # opening), C3 (GPT opening). Only the per-group check catches it.
    record = _clean_record()
    record["claims"][1] = {"id": "C2", "participant": "Claude", "phase": "opening"}
    record["claims"][2] = {"id": "C3", "participant": "GPT", "phase": "opening"}
    # C3 is now GPT's claim, so the derivation's originator follows
    # it (GPT), keeping check (d) consistent.
    record["unresolved_objections"][0]["originator"] = "GPT"
    _only_fails(_check(record), "claim_ids_sequential")


def test_transcript_contribution_mismatch_fails_check_c_only():
    record = _clean_record()
    record["transcript_entries"] = [
        e for e in record["transcript_entries"]
        if not (e["kind"] == "contribution" and e["participant"] == "Claude")]
    _only_fails(_check(record), "transcript_generation_parity")


def test_transcript_failure_mismatch_fails_check_c_only():
    record = _clean_record()
    record["transcript_entries"] = [
        e for e in record["transcript_entries"]
        if not (e["kind"] == "failure" and e["participant"] == "Claude")]
    _only_fails(_check(record), "transcript_generation_parity")


def test_orphan_contribution_fails_check_c_only():
    record = _clean_record()
    record["transcript_entries"].append(
        {"kind": "contribution", "participant": "Muse"})
    _only_fails(_check(record), "transcript_generation_parity")


def test_missing_objection_entry_fails_check_d_only():
    record = _clean_record()
    record["unresolved_objections"] = []
    _only_fails(_check(record), "unresolved_objection_derivation")


def test_extra_objection_entry_fails_check_d_only():
    record = _clean_record()
    record["unresolved_objections"].append(
        {"claim_id": "C1", "originator": "GPT", "cited_by": "Claude",
         "moves": ["objection"], "source_claim_id": "C3",
         "state": "unresolved", "responded_by": None})
    _only_fails(_check(record), "unresolved_objection_derivation")


def test_wrong_objection_state_fails_check_d_only():
    record = _clean_record()
    record["unresolved_objections"][0]["state"] = "responded_to"
    record["unresolved_objections"][0]["responded_by"] = "C5"
    _only_fails(_check(record), "unresolved_objection_derivation")


def test_responded_to_derivation_passes():
    # Standalone record: Claude's response C3 objects to GPT's C1,
    # and GPT's revision C4 targets C1 — so the entry is
    # responded_to by C4. (A revision only responds when it is by
    # the TARGET claim's author, mirroring the runner's rule.)
    record = {
        "invited_generations": [
            {"phase": "opening", "participant": "GPT"},
            {"phase": "opening", "participant": "Claude"},
            {"phase": "response", "participant": "Claude"},
            {"phase": "revision", "participant": "GPT"},
        ],
        "generation_outcomes": [
            {"phase": "opening", "participant": "GPT", "status": "completed", "reason": None},
            {"phase": "opening", "participant": "Claude", "status": "completed", "reason": None},
            {"phase": "response", "participant": "Claude", "status": "completed", "reason": None},
            {"phase": "revision", "participant": "GPT", "status": "completed", "reason": None},
        ],
        "transcript_entries": [
            {"kind": "contribution", "participant": "GPT"},
            {"kind": "contribution", "participant": "Claude"},
            {"kind": "contribution", "participant": "Claude"},
            {"kind": "contribution", "participant": "GPT"},
        ],
        "claims": [
            {"id": "C1", "participant": "GPT", "phase": "opening"},
            {"id": "C2", "participant": "Claude", "phase": "opening"},
            {"id": "C3", "participant": "Claude", "phase": "response"},
            {"id": "C4", "participant": "GPT", "phase": "revision"},
        ],
        "verified_challenges": [
            {"target_claim_id": "C1", "source_claim_id": "C3",
             "challenger": "Claude", "move": "objection"},
        ],
        "revision_claims": [
            {"id": "C4", "participant": "GPT", "relationship_target": "C1",
             "relates_to": []},
        ],
        "unresolved_objections": [
            {"claim_id": "C1", "originator": "GPT", "cited_by": "Claude",
             "moves": ["objection"], "source_claim_id": "C3",
             "state": "responded_to", "responded_by": "C4"},
        ],
    }
    result = _check(record)
    assert result["passed"] is True


def test_duplicate_challenge_deduped():
    record = _clean_record()
    record["verified_challenges"].append(
        copy.deepcopy(record["verified_challenges"][0]))
    result = _check(record)
    assert result["passed"] is True


def test_challenge_to_missing_target_skipped():
    record = _clean_record()
    record["verified_challenges"].append(
        {"target_claim_id": "C99", "source_claim_id": "C4",
         "challenger": "GPT", "move": "objection"})
    result = _check(record)
    assert result["passed"] is True


# ---------------------------------------------------------------- live runs

class FakeParticipant:
    """Duck-typed seat participant: generate(prompt, timeout=...)."""

    def __init__(self, name, *, opening="", response="", revision="",
                 delay=0.0, boom=False):
        self.name = name
        self.provider_id = dict((n, p) for n, p, _ in SEAT_SPECS)[name]
        self.model = "fake-model"
        self.key_source = "settings"
        self._texts = {
            "revision": revision,
            "response": response,
            "opening": opening,
        }
        self.delay = delay
        self.boom = boom

    def generate(self, prompt, *, timeout=120):
        if self.delay:
            time.sleep(self.delay)
        if self.boom:
            raise RuntimeError("provider exploded")
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


def _seats(fakes: dict[str, FakeParticipant | None]) -> list[Seat]:
    seats = []
    for name, provider_id, model in SEAT_SPECS:
        fake = fakes.get(name, FakeParticipant(name, opening="1. Inferred: nothing yet."))
        if fake is None:
            seats.append(Seat(name, provider_id, model, None,
                              absence_note=f"absent: no {provider_id} api key present"))
        else:
            seats.append(Seat(name, provider_id, model, fake))
    return seats


def _full_fakes():
    return {
        "GPT": FakeParticipant(
            "GPT",
            opening="1. Inferred: Authority confusion is a failure mode.\n2. Proposed: Keep authorization with Joshua.",
            response="In response to C3, I agree: the registry point stands.",
            revision="Relationship: defended.\nIn response to C1, I defend my claim:\n"
                     "1. Inferred: Authority confusion remains the top risk.",
        ),
        "Claude": FakeParticipant(
            "Claude",
            opening="1. Inferred: Parallel monologues are a failure mode.",
            response="1. Objection to C1: authorization alone does not "
                     "prevent a synthesis from misrepresenting choices.",
        ),
        "Gemini": FakeParticipant("Gemini", opening="1. Proposed: Add addressable claims."),
        "Grok": FakeParticipant("Grok", opening="1. Speculative: The room may perform deliberation."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Cost grows with participants."),
    }


def test_live_meeting_artifact_carries_passing_completeness(tmp_path):
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path,
                                     seats=_seats(_full_fakes()))
    assert result.ok is True
    rc = result.artifact["record_completeness"]
    assert rc["passed"] is True
    for check in CHECKS:
        assert rc["checks"][check]["passed"] is True, check
        assert rc["checks"][check]["failures"] == []
    assert result.artifact["record_complete"] is True
    # The completeness report persists with the artifact file.
    import json
    persisted = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert persisted["record_completeness"]["passed"] is True


def test_blocked_generations_still_accounted(tmp_path):
    # Response prompts exceed the 100-char response cap, so every
    # response generation is budget-blocked (recorded, not raised).
    # Blocked generations are accounted outcomes: the checks pass
    # even though deliberation is incomplete and ok is False.
    fakes = {
        name: FakeParticipant(name, opening="1. Inferred: Some claim with substance.")
        for name in NAMES
    }
    budget = Budget(max_contributions=15, max_prompt_chars=20000,
                    max_response_prompt_chars=100)
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path,
                                     seats=_seats(fakes), budget=budget)
    assert result.ok is False
    assert result.artifact["deliberation_complete"] is False
    assert result.artifact["record_completeness"]["passed"] is True
    assert result.artifact["record_complete"] is True


def test_generation_budget_cap_still_accounted(tmp_path):
    # Only 2 generations attempted; the rest are budget-blocked in
    # _generate_jobs. All are accounted: checks pass, ok is False
    # on deliberation, not on the record.
    fakes = {name: FakeParticipant(name, opening="1. Inferred: Claim.")
             for name in NAMES}
    budget = Budget(max_contributions=2, max_prompt_chars=20000,
                    max_response_prompt_chars=40000)
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path,
                                     seats=_seats(fakes), budget=budget)
    assert result.ok is False
    assert result.artifact["record_completeness"]["passed"] is True
    assert result.artifact["record_complete"] is True


def test_provider_failure_still_accounted(tmp_path):
    fakes = {
        "GPT": FakeParticipant("GPT", opening="1. Inferred: Alpha."),
        "Claude": FakeParticipant("Claude", opening="1. Inferred: Beta."),
        "Gemini": FakeParticipant("Gemini", opening="", boom=True),
        "Grok": FakeParticipant("Grok", opening="1. Inferred: Delta."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Epsilon."),
    }
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=_seats(fakes))
    assert result.ok is False
    assert result.artifact["record_completeness"]["passed"] is True
    assert result.artifact["record_complete"] is True


def test_all_absent_meeting_record_checks_pass_vacuously(tmp_path):
    seats = _seats({name: None for name in NAMES})
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=seats)
    assert result.ok is False
    assert result.artifact["record_completeness"]["passed"] is True
    assert result.artifact["record_complete"] is True
    assert result.artifact["deliberation_complete"] is False


def test_replay_artifact_marks_completeness_not_checked():
    artifact = replay_r2_transcript([
        {"participant": "GPT", "phase": "opening",
         "text": "1. Inferred: Authority confusion is a failure mode."},
        {"participant": "Claude", "phase": "opening",
         "text": "1. Inferred: Parallel monologues are a failure mode."},
    ])
    rc = artifact["record_completeness"]
    assert rc["status"] == "not_checked"
    assert "passed" not in rc
