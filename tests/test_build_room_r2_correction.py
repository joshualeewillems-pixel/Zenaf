"""R2 correction tests (amended spec C1-C10, §4, §6).

Unit tests per correction plus the fixture regression over the
stored R2 acceptance transcript (meeting 2d82b762ae9e). No live API
calls, no real key values anywhere. The fixture regression re-runs
the corrected parser/artifact builder over stored contributions and
asserts the spec's §3 acceptance checks structurally — replay ids
differ from the original run (Claude's 15 response claims now
register), so assertions are structural, never old-id equality.
"""

from __future__ import annotations

import json
from pathlib import Path

from local_ai.build_room.artifact import build_draft_artifact_r2
from local_ai.build_room.meeting import (
    _CLAIM_NUMBERING_INSTRUCTION,
    _CONTRIBUTION_DISCIPLINE,
    _analyze_contribution,
    _claim_status,
    _explicit_targets,
    _map_relationship,
    _parse_claim_spans,
    _revision_links,
    _telemetry_block,
    build_delta_report,
    compute_epistemic_assessments,
    compute_unresolved_objections,
    estimate_tokens,
    replay_r2_transcript,
    ClaimRegistry,
    EvidencePacket,
)


def _packet() -> EvidencePacket:
    return EvidencePacket(
        work_item="Test work item",
        question="What would make the Build-Council Room fail?",
    )


def _register_openings() -> ClaimRegistry:
    """Registry with GPT=C1, Claude=C2, Gemini=C3, Grok=C4, Muse=C5."""
    reg = ClaimRegistry()
    reg.register("GPT", "opening", "1. Observed: Alpha.")
    reg.register("Claude", "opening", "1. Inferred: Beta.")
    reg.register("Gemini", "opening", "1. Proposed: Gamma.")
    reg.register("Grok", "opening", "1. Speculative: Delta.")
    reg.register("Muse", "opening", "1. Observed: Epsilon.")
    return reg


# --- C1: authoritative registration -------------------------------------

def test_c1_model_written_numbers_disregarded_system_ids_assigned():
    reg = ClaimRegistry()
    spans = _parse_claim_spans(
        "C60. The five participants act independently.\n"
        "C61. No hierarchy constrains them.")
    assert [s.used_model_number for s in spans] == [True, True]
    assert [s.model_number for s in spans] == ["60", "61"]
    claims = reg.register_spans("Claude", "response", spans)
    assert [c.id for c in claims] == ["C1", "C2"]
    assert all("C60" not in c.text and "C61" not in c.text for c in claims)
    assert reg.last_disregarded_model_numbers == ["C60", "C61"]


def test_c1_numbering_instruction_system_assigned_plain_digits():
    assert "assigned by the system" in _CLAIM_NUMBERING_INSTRUCTION
    assert "plain digits" in _CLAIM_NUMBERING_INSTRUCTION
    assert "do not invent" in _CLAIM_NUMBERING_INSTRUCTION.lower()


def test_c1_zero_claims_note_reason():
    reg = ClaimRegistry()
    assert reg.register("Gemini", "opening", "No numbered claims here.") == []


# --- C2: status parsing + explicit unknown ------------------------------

def test_c2_status_formats():
    assert _claim_status("Observed: the room deliberates.") == "Observed"
    assert _claim_status("**Observed:** the room deliberates.") == "Observed"
    assert _claim_status("**Observed**: the room deliberates.") == "Observed"
    assert _claim_status("[Observed] the room deliberates.") == "Observed"
    assert _claim_status("**[Inferred]** the room may fail.") == "Inferred"
    assert _claim_status("The room may fail.") == "unknown"
    assert _claim_status("The room may fail.", inherited="Observed") == "Observed"


def test_c2_section_header_inheritance_and_span_end():
    spans = _parse_claim_spans(
        "## Observed\n"
        "1. First claim, no own prefix.\n"
        "2. Inferred: second claim overrides.\n"
        "## Proposed\n"
        "3. Third claim inherits the new heading.")
    assert [s.status for s in spans] == ["Observed", "Inferred", "Proposed"]
    assert spans[0].text == "First claim, no own prefix."


def test_c2_status_never_blank():
    reg = ClaimRegistry()
    claims = reg.register("Muse", "opening",
                          "1. A claim with no status marker at all.")
    assert claims[0].status == "unknown"


# --- C3: claim-local relationships --------------------------------------

def test_c3_per_span_relationships_no_propagation():
    reg = _register_openings()
    text = (
        "1. [Observed] Revised — I revise my C3 in response to C1: gamma qualified.\n"
        "2. [Proposed] Extension of C2: beta generalizes.")
    analysis = _analyze_contribution(text, author="Gemini", registry=reg,
                                     frozen_ids=reg.ids())
    assert analysis["per_span"][0]["citations_valid"] == ["C3", "C1"]
    assert analysis["per_span"][1]["citations_valid"] == ["C2"]
    links = _revision_links(analysis, "Gemini", reg)
    assert links[0]["relates_to"] == ["C3", "C1"]
    assert links[1]["relates_to"] == ["C2"]
    assert links[0]["relates_to"] != links[1]["relates_to"]


# --- C4: authorship — disposition vs assessment -------------------------

def test_c4_cross_author_revision_never_changes_disposition():
    reg = _register_openings()
    # Grok "revises" Muse's C5: cross-author language, not a disposition.
    mapped, target, supersedes, withdraws = _map_relationship(
        "revised", "C5", "Grok", reg)
    assert mapped == "proposes_revision_of"
    assert target == "C5"
    assert supersedes is None and withdraws is None
    # GPT "defends" Muse's C5: endorsement, not self-defense.
    mapped, target, _, _ = _map_relationship("defended", "C5", "GPT", reg)
    assert mapped == "endorses"
    # Muse revises its own C5: genuine disposition change.
    mapped, target, supersedes, _ = _map_relationship(
        "revised", "C5", "Muse", reg)
    assert mapped == "revised"
    assert supersedes == "C5"


def test_c4_assessment_independent_and_sourced():
    reg = _register_openings()
    challenges = [{"source_claim_id": "C9", "challenger": "Gemini",
                   "target_claim_id": "C5", "move": "evidence_request"}]
    compute_epistemic_assessments(challenges, [], reg)
    muse_claim = reg.by_id("C5")
    assert muse_claim.epistemic_assessment == "challenged"
    assert muse_claim.assessment_sources == ["C9"]
    # "contradicted" is never set mechanically.
    assert all(c.epistemic_assessment != "contradicted" for c in reg.claims)


# --- C5: explicit targeting, responded_to vs resolved -------------------

def test_c5_proximity_trap_only_explicit_target_counts():
    scope = "C14 correctly identifies a risk. I object to C29, which is unproven."
    targets = _explicit_targets(scope)
    assert targets == {"objection": ["C29"]}
    assert "C14" not in targets.get("objection", [])


def test_c5_same_span_proximity_alone_is_candidacy_only():
    scope = "C29 is unproven, and I object to this whole approach."
    assert _explicit_targets(scope) == {}


def test_c5_responded_to_never_resolved():
    reg = _register_openings()
    reg.register("Gemini", "response",
                 "1. Evidence request regarding C5: show the mechanism.")
    gemini_challenge = reg.claims[-1]
    analysis = _analyze_contribution(
        "1. Revised — I revise my C5 in response to "
        f"{gemini_challenge.id}: epsilon, narrowed.",
        author="Muse", registry=reg, frozen_ids=reg.ids())
    links = _revision_links(analysis, "Muse", reg)
    registered = reg.register_spans("Muse", "revision", analysis["spans"], links)
    revision_claims = [c for c in reg.claims if c.phase == "revision"]
    assert registered[0].relationship_target == "C5"
    entries = compute_unresolved_objections(
        [{"source_claim_id": gemini_challenge.id, "challenger": "Gemini",
          "target_claim_id": "C5", "move": "evidence_request"}],
        reg, revision_claims)
    assert len(entries) == 1
    assert entries[0]["state"] == "responded_to"
    assert entries[0]["responded_by"] == revision_claims[0].id
    assert all(e["state"] != "resolved" for e in entries)


def test_c5_unclassified_prose_never_promoted():
    reg = _register_openings()
    analysis = _analyze_contribution(
        "In response to C1, I object: alpha is overstated. "
        "In response to C4, I object: delta is unproven.",
        author="Claude", registry=reg, frozen_ids=reg.ids())
    assert analysis["classification"] == "unclassified"
    # Citations preserved for legibility, but no verified targets.
    assert analysis["cited_claim_ids"] == ["C1", "C4"]
    assert analysis["per_span"] == []


# --- C6: addressability --------------------------------------------------

def test_c6_addressable_needs_other_author_citation_and_targeted_move():
    reg = _register_openings()
    # GPT's response cites others with an explicit agreement target.
    analysis = _analyze_contribution(
        "1. Agreement with C2: beta's mechanism is sound.",
        author="GPT", registry=reg, frozen_ids=reg.ids())
    assert analysis["other_citations"] == ["C2"]
    assert analysis["per_span"][0]["explicit_targets"] == {"agreement": ["C2"]}
    # Self-citation alone is never addressable.
    self_analysis = _analyze_contribution(
        "1. Agreement with C1: my alpha stands.",
        author="GPT", registry=reg, frozen_ids=reg.ids())
    assert self_analysis["self_citations"] == ["C1"]
    assert self_analysis["other_citations"] == []


# --- C7: per-field evaluation status -------------------------------------

def test_c7_synthesis_fields_absent_and_marker_present():
    # Synthesis removal stage 1: the builder takes no synthesis
    # params and emits no synthesis fields (absent, not failed).
    packet = _packet()
    artifact = build_draft_artifact_r2(
        "m", packet, _FakeTranscript(), [], ClaimRegistry())
    assert artifact["synthesis_removed"] is True
    for key in ("synthesis", "synthesis_failure", "positions",
                "positions_evaluation", "disagreements",
                "disagreements_evaluation", "recommendations",
                "recommendations_evaluation", "limitations",
                "limitations_evaluation", "rejected_entries",
                "synthesis_coverage", "synthesis_coverage_accepted",
                "synthesis_generation", "synthesis_generation_cost",
                "synthesis_gate"):
        assert key not in artifact
    assert artifact["unresolved_objections_evaluation"] == "mechanical"
    assert artifact["record_complete"] is False
    assert artifact["deliberation_complete"] is False
    assert artifact["ok"] is False


class _FakeTranscript:
    entries = []


# --- C8: parallel-safe telemetry ------------------------------------------

def test_c8_telemetry_distinguishes_completed_allocated_reserved():
    block = _telemetry_block(phase="response", max_generations=16,
                             completed=5, allocated=5,
                             reserved={"Revision slots": "up to 5",
                                       "Synthesis slots": "1"})
    assert "Generations completed: 5" in block
    assert "allocated this phase: 5" in block
    assert "Revision slots reserved: up to 5" in block
    assert "Synthesis slots reserved: 1" in block
    assert "not yet completed generations" in block
    assert "generation 5 of 16" not in block.lower()
    assert "generation 6 of 16" not in block.lower()


# --- C9: bounded state, mandatory vs optional ------------------------------


# --- C10: soft target, not a hard cap ---------------------------------------

def test_c10_soft_target_present_no_hard_cap_language():
    assert "3–6" in _CONTRIBUTION_DISCIPLINE
    lowered = _CONTRIBUTION_DISCIPLINE.lower()
    assert "no hard cap" in lowered
    assert "no rejection" in lowered
    assert "you may exceed" in lowered
    assert "genuinely distinct" in lowered


# --- §4: delta report -------------------------------------------------------

def test_delta_report_chains_and_unclassified_candidates():
    reg = _register_openings()
    reg.register("Gemini", "response",
                 "1. Evidence request regarding C5: show the mechanism.")
    challenge = reg.claims[-1]
    analysis = _analyze_contribution(
        "1. Revised — I revise my C5 in response to "
        f"{challenge.id}: epsilon, narrowed.",
        author="Muse", registry=reg, frozen_ids=reg.ids())
    links = _revision_links(analysis, "Muse", reg)
    reg.register_spans("Muse", "revision", analysis["spans"], links)
    report = build_delta_report(
        reg, [{"source_claim_id": challenge.id, "challenger": "Gemini",
               "target_claim_id": "C5", "move": "evidence_request"}],
        unclassified_interactions=[
            {"participant": "Grok", "phase": "revision",
             "cited_claim_ids": ["C5"], "stated_moves": [],
             "relationship": "supports_withdrawal_of",
             "relationship_target": "C5"}])
    assert len(report["revision_chains"]) == 1
    chain = report["revision_chains"][0]
    assert chain["original_claim_id"] == "C5"
    assert chain["state"] == "responded_to"
    assert "novelty" not in report and "improvement" not in report
    assert len(report["unclassified_candidates"]) == 1
    cand = report["unclassified_candidates"][0]
    assert cand["classification"] == "unclassified"
    assert cand["contribution_relationship"] == "supports_withdrawal_of"
    assert "requires review" in cand["note"]


# --- §6: fixture regression over meeting 2d82b762ae9e -----------------------

def _fixture_artifact():
    path = Path(__file__).parent / "fixtures" / "r2_acceptance_contributions.json"
    fixture = json.loads(path.read_text())
    return replay_r2_transcript(
        fixture["contributions"], meeting_id=fixture["meeting_id"],
        work_item=fixture["work_item"], question=fixture["question"])


def test_fixture_regression_r2_acceptance():
    art = _fixture_artifact()
    reg = art["claim_registry"]
    by_id = {c["id"]: c for c in reg}
    # 115 claims (vs 100 originally): Claude's 15 response claims now
    # register under system ids; openings C1-C59 are unchanged.
    assert len(reg) == 115
    assert [c["participant"] for c in reg if c["phase"] == "opening"] == (
        ["GPT"] * 8 + ["Claude"] * 15 + ["Gemini"] * 10
        + ["Grok"] * 8 + ["Muse"] * 18)
    assert [c["id"] for c in reg if c["phase"] == "opening"] == [
        f"C{i}" for i in range(1, 60)]
    # No silent empty statuses: every claim has an explicit status.
    assert all(c["status"] for c in reg)
    assert all(c["status"] != "" for c in reg)
    # Opening statuses populated for every participant.
    for participant in ("GPT", "Claude", "Gemini", "Grok", "Muse"):
        assert all(c["status"] != "unknown"
                   for c in reg
                   if c["phase"] == "opening" and c["participant"] == participant)
    # Claude's response claims registered without invented ids:
    # model-written C60.-C74. became system ids C73-C87.
    claude_resp = [c for c in reg
                   if c["phase"] == "response" and c["participant"] == "Claude"]
    assert len(claude_resp) == 15
    assert [c["id"] for c in claude_resp] == [f"C{i}" for i in range(73, 88)]
    # Gemini revision claims: distinct relationships, no propagated
    # supersession (originally all six shared supersedes C77 + one
    # 22-item relates_to list).
    gemini_revs = [c for c in reg
                   if c["phase"] == "revision" and c["participant"] == "Gemini"]
    assert len(gemini_revs) == 6
    assert all(c["supersedes"] is None for c in gemini_revs)
    relates = [tuple(c["relates_to"]) for c in gemini_revs]
    assert len(set(relates)) == len(relates)
    # Grok revision: supports withdrawal of C59, disposition unchanged.
    grok_rev = [i for i in art["interactions"]
                if i["participant"] == "Grok" and i["phase"] == "revision"][0]
    assert grok_rev["relationship"] == "supports_withdrawal_of"
    assert grok_rev["relationship_target"] == "C59"
    # GPT revision: endorses C58, not self-defense.
    gpt_rev = [i for i in art["interactions"]
               if i["participant"] == "GPT" and i["phase"] == "revision"][0]
    assert gpt_rev["relationship"] == "endorses"
    assert gpt_rev["relationship_target"] == "C58"
    # C59: disposition revised by Muse's revision claim alone;
    # assessment challenged via Gemini's evidence request.
    c59 = by_id["C59"]
    muse_rev = [c for c in reg
                if c["phase"] == "revision" and c["participant"] == "Muse"]
    assert len(muse_rev) == 1
    assert c59["disposition"] == "revised"
    assert c59["disposition_by"] == muse_rev[0]["id"]
    assert c59["epistemic_assessment"] == "challenged"
    assert c59["assessment_sources"], "assessment without source"
    # Gemini evidence request -> Muse authorial revision chain,
    # responded_to, never resolved.
    chains = art["delta_report"]["revision_chains"]
    c59_chains = [ch for ch in chains if ch["original_claim_id"] == "C59"]
    assert len(c59_chains) == 1
    assert c59_chains[0]["challenger"] == "Gemini"
    assert c59_chains[0]["challenge_move"] == "evidence_request"
    assert c59_chains[0]["revision_claim_id"] == muse_rev[0]["id"]
    assert c59_chains[0]["state"] == "responded_to"
    assert all(e["state"] != "resolved"
               for e in art["unresolved_objections"])
    c59_entries = [e for e in art["unresolved_objections"]
                   if e["claim_id"] == "C59"]
    assert len(c59_entries) == 1
    assert c59_entries[0]["state"] == "responded_to"
    # No manufactured objections: every entry is verified and
    # claim-specific (source claim id present); Claude's prose
    # citations contribute none.
    assert len(art["unresolved_objections"]) == 8  # was 29 manufactured
    assert all(e.get("source_claim_id") for e in art["unresolved_objections"])
    assert all(e["cited_by"] != "Claude" for e in art["unresolved_objections"])
    # GPT response: mechanically addressable, substantively unassessed.
    gpt_resp = [i for i in art["interactions"]
                if i["participant"] == "GPT" and i["phase"] == "response"][0]
    assert gpt_resp["cited_other_author"] is True
    assert gpt_resp["move_targeted"] is True
    assert gpt_resp["addressable"] is True
    assert gpt_resp["substantive_engagement"] == "unassessed"
    # Unclassified revision relationships survive as candidates
    # requiring review, never disappearing from the artifact.
    candidates = art["delta_report"]["unclassified_candidates"]
    cand_by_participant = {c["participant"]: c for c in candidates}
    assert cand_by_participant["Grok"]["contribution_relationship"] == \
        "supports_withdrawal_of"
    assert cand_by_participant["GPT"]["contribution_relationship"] == "endorses"
    # No synthesis fields in the replayed artifact: synthesis is
    # absent by design, not failed.
    assert art["synthesis_removed"] is True
    assert "synthesis" not in art
    assert "synthesis_failure" not in art
    assert "positions" not in art
    assert "disagreements" not in art
    assert art["unresolved_objections_evaluation"] == "mechanical"
