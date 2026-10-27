"""R2 legibility correction tests (Scopes A–C, amended design).

Unit tests per scope plus the two fixture replays: the derived replay
over meeting 8cce24eb4226 (Claude recovery with historical-ID
preservation) and the regression replay over 2d82b762ae9e (no
regression, no spurious "challenges"). No live API calls, no real
key values anywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

from local_ai.build_room.meeting import (
    ClaimRegistry,
    EvidencePacket,
    _analyze_contribution,
    _claim_status,
    _explicit_targets,
    _map_relationship,
    _parse_claim_spans,
    _revision_links,
    replay_derived_r2_transcript,
    replay_r2_transcript,
)


def _openings() -> ClaimRegistry:
    """Registry with GPT=C1, Claude=C2, Gemini=C3, Grok=C4, Muse=C5."""
    reg = ClaimRegistry()
    reg.register("GPT", "opening", "1. Observed: Alpha.")
    reg.register("Claude", "opening", "1. Inferred: Beta.")
    reg.register("Gemini", "opening", "1. Proposed: Gamma.")
    reg.register("Grok", "opening", "1. Speculative: Delta.")
    reg.register("Muse", "opening", "1. Observed: Epsilon.")
    return reg


# --- Scope A: bold-number boundaries -------------------------------------

def test_a_bold_number_forms_each_yield_one_claim():
    spans = _parse_claim_spans(
        "**1.** Plain bold number.\n"
        "**2. Inferred:** Bare status in bold number.\n"
        "**3. (Contested)** Parenthetical status in bold number.\n"
        "**4. [Proposed]** Bracket status in bold number.\n"
        "5. Plain number, unchanged.")
    assert len(spans) == 5
    assert spans[0].text == "Plain bold number."
    assert spans[0].status == "unknown"
    assert spans[1].status == "Inferred"
    assert spans[2].status == "Contested"
    assert spans[3].status == "Proposed"
    assert spans[4].status == "unknown"


def test_a_boundary_status_separation_no_split_or_duplicate():
    # A status marker is metadata, not a second boundary: each of
    # these yields exactly ONE claim carrying the status.
    spans = _parse_claim_spans("**1. (Inferred)** The room fails when roles are assumed.")
    assert len(spans) == 1
    assert spans[0].status == "Inferred"
    spans = _parse_claim_spans("**1. Inferred:** The room fails when roles are assumed.")
    assert len(spans) == 1
    assert spans[0].status == "Inferred"


def test_a_rejection_midline_and_midsentence_never_split():
    spans = _parse_claim_spans(
        "1. First claim. As noted in 1. above, see step 1. "
        "The **1.** item rule is mid-sentence, not a boundary.")
    assert len(spans) == 1


def test_a_midsentence_parenthetical_is_prose_not_status():
    spans = _parse_claim_spans(
        "1. A claim that mentions (Inferred) only mid-sentence.")
    assert len(spans) == 1
    assert spans[0].status == "unknown"


def test_a_multiline_numbered_examples_join_indented_but_split_flush():
    # Indented numbered examples inside supporting paragraphs join
    # the current claim; they do not become independent claims.
    spans = _parse_claim_spans(
        "1. Main claim with supporting detail.\n"
        "   1. Nested example one.\n"
        "   2. Nested example two.\n"
        "2. Next claim.")
    assert len(spans) == 2
    assert "Nested example one" in spans[0].text
    assert "Nested example two" in spans[0].text
    assert spans[1].text == "Next claim."
    # Documented residual ambiguity: a flush-left numbered line
    # inside a claim is structurally indistinguishable from a new
    # claim and still splits.
    spans = _parse_claim_spans(
        "1. Main claim.\n"
        "1. Example at flush left.")
    assert len(spans) == 2


# --- Scope A: status precedence, parenthetical weakest explicit ---------

def test_a3_precedence_bare_bold_paren_inherited():
    assert _claim_status("Observed: (Inferred) text.") == "Observed"
    assert _claim_status("**Observed:** (Inferred) text.") == "Observed"
    assert _claim_status("[Observed] (Inferred) text.") == "Observed"
    assert _claim_status("(Inferred) text.") == "Inferred"
    spans = _parse_claim_spans(
        "## Proposed\n"
        "1. (Inferred) text under a Proposed heading.")
    assert spans[0].status == "Inferred"


def test_a3_extended_parenthetical_status_and_targeting_kept_separate():
    # "(Contested — Objection to C21)" parses the status word
    # Contested; the remainder is targeting info for C5, not status.
    assert _claim_status("(Contested — Objection to C21) text.") == "Contested"
    targets = _explicit_targets(
        "(Contested — Objection to C21) In response to C21, this fails.")
    assert targets == {"objection": ["C21"]}


def test_a_plain_numbered_parenthetical_status():
    # The 27-claim case from the rerun: plain numbers with
    # parenthetical statuses now populate instead of "unknown".
    spans = _parse_claim_spans(
        "1. (Observed) The room convenes five participants.\n"
        "2. (Proposed) Add an opening instruction.")
    assert [s.status for s in spans] == ["Observed", "Proposed"]


# --- Scope C: defended/revised same-author only ---------------------------

def test_c_unstated_target_means_unstated_relationship():
    # A bare stance word without an identifiable target is recorded
    # nowhere as a relationship (legibility C).
    assert _map_relationship("defended", None, "GPT", _openings()) == (
        "unstated", "unstated", None, None)
    assert _map_relationship("revised", None, "GPT", _openings()) == (
        "unstated", "unstated", None, None)
    assert _map_relationship(None, "C1", "GPT", _openings()) == (
        "unstated", None, None, None)


def test_c_same_author_defended_and_cross_author_mapping():
    reg = _openings()
    mapped, target, _, _ = _map_relationship("defended", "C1", "GPT", reg)
    assert (mapped, target) == ("defended", "C1")
    mapped, target, _, _ = _map_relationship("withdrawn", "C5", "Grok", reg)
    assert (mapped, target) == ("supports_withdrawal_of", "C5")
    mapped, target, _, _ = _map_relationship("defended", "C5", "GPT", reg)
    assert (mapped, target) == ("endorses", "C5")


def test_c_explicit_challenge_preserved_not_erased():
    # A revision span with an explicitly targeted objection to
    # another author's claim, and no revised/defended/withdrawn
    # word, links as "challenges" — neither an authorial revision
    # nor an unknown relationship.
    reg = _openings()
    analysis = _analyze_contribution(
        "1. Objection to C2: beta is unproven.",
        author="Gemini", registry=reg, frozen_ids=reg.ids())
    links = _revision_links(analysis, "Gemini", reg)
    assert links[0]["relationship"] == "challenges"
    assert links[0]["relationship_target"] == "C2"
    assert links[0]["supersedes"] is None
    assert links[0]["withdraws"] is None
    assert analysis["relationship"] == "challenges"
    assert analysis["relationship_target"] == "C2"


def test_c_cross_author_unclear_stays_unstated():
    reg = _openings()
    analysis = _analyze_contribution(
        "1. Some general remark with no target and no stance word.",
        author="Gemini", registry=reg, frozen_ids=reg.ids())
    links = _revision_links(analysis, "Gemini", reg)
    assert links[0]["relationship"] == "unstated"
    assert links[0]["relationship_target"] == "unstated"


def _derived_fixture():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures"
         / "r2_correction_rerun_derived.json").read_text())
    return replay_derived_r2_transcript(
        fixture["contributions"], fixture["historical_claims"],
        meeting_id="derived-test",
        historical_meeting_id=fixture["meeting_id"],
        work_item=fixture["work_item"], question=fixture["question"],
        historical_objections=fixture["original_unresolved_objections"]), fixture


def test_derived_replay_recovers_claude_preserving_history():
    art, fixture = _derived_fixture()
    reg = art["claim_registry"]
    by_id = {c["id"]: c for c in reg}
    historical = fixture["historical_claims"]
    # 50 historical + 12 recovered = 62.
    assert len(reg) == 62
    assert len(art["recovered_claims"]) == 12
    # Claude: 5 opening (D1–D5) + 7 response (D6–D12), derived ids
    # only, never colliding with historical C-ids.
    recovered = art["recovered_claims"]
    assert all(c["id"].startswith("D") for c in recovered)
    assert [c["id"] for c in recovered] == [f"D{i}" for i in range(1, 13)]
    assert [(c["participant"], c["phase"]) for c in recovered] == (
        [("Claude", "opening")] * 5 + [("Claude", "response")] * 7)
    assert [c["status"] for c in recovered[:5]] == [
        "Inferred", "Proposed", "Speculative", "Contested", "Inferred"]
    # Historical ids unchanged, in original relative order, same
    # text/participant/phase.
    assert [c["id"] for c in reg if not c["id"].startswith("D")] == [
        c["id"] for c in historical]
    for old in historical:
        new = by_id[old["id"]]
        assert new["text"] == old["text"]
        assert new["participant"] == old["participant"]
        assert new["phase"] == old["phase"]
    # No historical claim left unmatched; no manufactured interaction.
    assert art["unmatched_historical_ids"] == []
    assert art["manufactured_interaction_flags"] == []
    # Mapping + prominent disclosure.
    assert len(art["historical_derived_mapping"]) == 12
    assert "NOT available" in art["retrospective_recovery_disclosure"]
    assert "during the original meeting" in art["retrospective_recovery_disclosure"]


def test_derived_replay_status_diff_is_parenthetical_only():
    art, fixture = _derived_fixture()
    by_id = {c["id"]: c for c in art["claim_registry"]}
    changed = art["replay_diff"]["status_changed"]
    # Exactly the 27 parenthetical statuses the rerun packet
    # identified — and every change is unknown → named, never a
    # named → different-named flip.
    assert len(changed) == 27
    for entry in changed:
        old = next(c for c in fixture["historical_claims"]
                   if c["id"] == entry["id"])
        assert entry["old_status"] == "unknown"
        assert entry["new_status"] != "unknown"
        assert old["text"].startswith(f"({entry['new_status']}")
        assert by_id[entry["id"]]["status"] == entry["new_status"]


def test_derived_replay_scope_c_relabeling_and_chain_survival():
    art, fixture = _derived_fixture()
    by_id = {c["id"]: c for c in art["claim_registry"]}
    orig = {c["id"]: c for c in fixture["historical_claims"]}
    # Bare stance words without targets become unstated (Scope C):
    # GPT C41/C42/C43 defended/defended/revised → unstated.
    assert orig["C41"]["relationship"] == "defended"
    assert by_id["C41"]["relationship"] == "unstated"
    assert by_id["C41"]["relationship_target"] == "unstated"
    assert by_id["C41"]["relates_to"] == ["C17"]
    assert orig["C43"]["relationship"] == "revised"
    assert by_id["C43"]["relationship"] == "unstated"
    # Muse C49 gains the preserved "challenges" link to Grok's C30.
    assert by_id["C49"]["relationship"] == "challenges"
    assert by_id["C49"]["relationship_target"] == "C30"
    assert by_id["C49"]["supersedes"] is None
    # The C21 → C31 → C47 chain survives relabeling, still
    # responded_to, never resolved.
    chains = [ch for ch in art["delta_report"]["revision_chains"]
              if ch["original_claim_id"] == "C21"]
    assert len(chains) == 1
    assert chains[0]["challenge_claim_id"] == "C31"
    assert chains[0]["revision_claim_id"] == "C47"
    assert chains[0]["state"] == "responded_to"
    # GPT revision interaction: defended/unstated → unstated/unstated.
    gpt_rev = [i for i in art["interactions"]
               if i["participant"] == "GPT" and i["phase"] == "revision"][0]
    assert gpt_rev["relationship"] == "unstated"
    assert gpt_rev["relationship_target"] == "unstated"
    # Claude's interactions are classified now, citations preserved.
    claude = [i for i in art["interactions"] if i["participant"] == "Claude"]
    assert [i["classification"] for i in claude] == ["classified", "classified"]
    assert claude[1]["cited_claim_ids"] == ["C8", "C10", "C16", "C17", "C21"]


def test_derived_replay_objections_originals_plus_recovered_source():
    art, fixture = _derived_fixture()
    entries = {(e["claim_id"], e["cited_by"], e["state"])
               for e in art["unresolved_objections"]}
    original = {(e["claim_id"], e["cited_by"], e["state"])
                for e in fixture["original_unresolved_objections"]}
    assert original <= entries
    # Exactly one addition: Claude's recovered response span
    # explicitly objects to Grok's C16. The objection text existed
    # in the live transcript; only its registry representation is
    # new — it is a recovered SOURCE, not a manufactured target
    # interaction, and C16's assessment now records source D8.
    assert entries - original == {("C16", "Claude", "unresolved")}
    c16 = next(c for c in art["claim_registry"] if c["id"] == "C16")
    assert c16["epistemic_assessment"] == "challenged"
    assert c16["assessment_sources"] == ["D8"]


# --- Replay: regression 2d82b762ae9e --------------------------------------

def test_regression_replay_r2_acceptance_unchanged():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures"
         / "r2_acceptance_contributions.json").read_text())
    art = replay_r2_transcript(
        fixture["contributions"], meeting_id=fixture["meeting_id"],
        work_item=fixture["work_item"], question=fixture["question"])
    reg = art["claim_registry"]
    assert len(reg) == 115
    assert len(art["unresolved_objections"]) == 8
    assert all(c["status"] for c in reg)
    # No "challenges" relationship leaks into the old record: the
    # fixture's revision spans all carry relationship words.
    assert all(c.get("relationship") != "challenges" for c in reg)
    assert all(i.get("relationship") != "challenges"
               for i in art["interactions"])
    # Grok/GPT revision endorsements unchanged.
    grok_rev = [i for i in art["interactions"]
                if i["participant"] == "Grok" and i["phase"] == "revision"][0]
    assert grok_rev["relationship"] == "supports_withdrawal_of"
    assert grok_rev["relationship_target"] == "C59"
    gpt_rev = [i for i in art["interactions"]
               if i["participant"] == "GPT" and i["phase"] == "revision"][0]
    assert gpt_rev["relationship"] == "endorses"
    assert gpt_rev["relationship_target"] == "C58"


def test_derived_objection_counts_preserve_both():
    art, fixture = _derived_fixture()
    assert art["objection_counts"] == {
        "historical": 3,
        "recovered_sourced": 1,
        "derived": 4,
    }
    disclosure = art["retrospective_recovery_disclosure"]
    assert "3 historical" in disclosure
    assert "4 in this derived artifact" in disclosure
    assert "1 sourced from recovered claims" in disclosure


def test_derived_objection_counts_without_historical_input():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures"
         / "r2_correction_rerun_derived.json").read_text())
    art = replay_derived_r2_transcript(
        fixture["contributions"], fixture["historical_claims"],
        meeting_id="derived-test",
        historical_meeting_id=fixture["meeting_id"],
        work_item=fixture["work_item"], question=fixture["question"])
    # Fallback derivation (no historical list supplied): objections not
    # sourced from recovered claims count as historical.
    assert art["objection_counts"] == {
        "historical": 3,
        "recovered_sourced": 1,
        "derived": 4,
    }
