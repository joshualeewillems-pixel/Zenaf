"""Bounded Reliability Mandate v1 acceptance tests (A1-A11).

Local replay of the two stored stage-1 meetings (corrective probe +
live validation) through the fixed parser/derivation, plus unit tests
for every parser, derivation, and audit rule. Zero model spend: the
fixtures are reduced copies of the stored response files (transcript
contributions with phases, claim registries, interactions, tool
logs), committed under tests/fixtures/mandate_*_replay.json.

Acceptance map:
- A1: live C70 withdrawal list -> C30-C44 withdrawn (replay).
- A2: live C68 retraction extracted, not "unstated" (replay).
- A3: probe C54 downgrade -> effective Inferred, authored Observed
  retained (replay + unit).
- A4: C54 never parses as "defended" (unit + replay).
- A5: probe C61 stays active (replay).
- A6: probe C33/C39-style challenges do not flip standing (unit +
  replay: C6-C9 challenged yet active).
- A7: probe C56 leaves C6-C9 content active while its citations are
  withdrawn/unverified (unit + replay).
- A8: probe C8/C10/C12 narrated reads surface UNVERIFIED (replay).
- A9: live C5 meeting.py claim CONTRADICTED only under a complete-log
  attestation, else UNVERIFIED (unit + replay).
- A10: no new failures (full-suite comparison, reported separately);
  build-room subset green; no mutation of untouched record fields
  (replay identity assertions).
- A11: no third issue (backlog one-liners live in MANDATE_EVIDENCE.md).
"""

import json
from pathlib import Path

from local_ai.build_room.claim_standing import (
    compute_claim_standing,
    format_standing_headline,
)
from local_ai.build_room.evidence_audit import audit_prose_evidence_claims
from local_ai.build_room.meeting import (
    Claim,
    ClaimRegistry,
    _analyze_contribution,
    _apply_dispositions,
    _revision_links,
    replay_r2_transcript,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _registry_with(priors):
    """ClaimRegistry preloaded with (id, participant) opening claims."""
    registry = ClaimRegistry()
    for cid, participant in priors:
        registry.claims.append(
            Claim(id=cid, participant=participant, phase="opening", text="prior")
        )
    return registry


def _revision(text, author, priors):
    """Parse one revision contribution; return (registered, links)."""
    registry = _registry_with(priors)
    frozen = {cid for cid, _ in priors}
    analysis = _analyze_contribution(
        text, author=author, registry=registry, frozen_ids=frozen
    )
    links = _revision_links(analysis, author, registry)
    registered = registry.register_spans(author, "revision", analysis["spans"], links)
    _apply_dispositions(registry, registered, links)
    return registered, links, registry


def _claim_dict(cid, participant, phase="opening", **over):
    d = {
        "id": cid,
        "participant": participant,
        "phase": phase,
        "text": "text",
        "status": "unknown",
        "relationship": None,
        "relationship_target": None,
        "relationship_targets": [],
        "supersedes": None,
        "withdraws": None,
        "reclassified_status": None,
    }
    d.update(over)
    return d


def _standing(claims):
    table = compute_claim_standing(claims)
    return {e["claim_id"]: e for e in table["entries"]}


def _load(name):
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------- parser


def test_parser_retract_anaphoric_range():
    priors = [(f"C{n}", "Claude") for n in range(27, 45)]
    text = (
        "1. C27–C44 (my prior contribution) falsely claimed to have "
        "performed reads; they are retracted."
    )
    registered, _, _ = _revision(text, "Claude", priors)
    assert len(registered) == 1
    claim = registered[0]
    assert claim.relationship == "withdrawn"
    assert claim.relationship_targets == [f"C{n}" for n in range(27, 45)]


def test_parser_colon_list_with_range():
    priors = [(f"C{n}", "Claude") for n in range(27, 45)]
    text = "1. **Withdrawn:** C27, C28, C29, C30–C44."
    registered, _, _ = _revision(text, "Claude", priors)
    assert registered[0].relationship == "withdrawn"
    assert registered[0].relationship_targets == (
        ["C27", "C28", "C29"] + [f"C{n}" for n in range(30, 45)]
    )


def test_parser_citation_withdrawal_is_not_a_content_move():
    priors = [(f"C{n}", "Claude") for n in range(6, 10)]
    text = "1. (Withdrawn) The line-number citations in C6–C9 are fabricated."
    registered, _, _ = _revision(text, "Claude", priors)
    claim = registered[0]
    assert claim.relationship == "withdraws_citations"
    assert claim.relationship_targets == ["C6", "C7", "C8", "C9"]
    assert claim.supersedes is None and claim.withdraws is None


def test_parser_defended_values_list():
    priors = [(f"C{n}", "Claude") for n in range(6, 14)]
    text = "1. (Defended) The numeric values reported in C6–C13 are consistent."
    registered, _, _ = _revision(text, "Claude", priors)
    assert registered[0].relationship == "defended"
    assert registered[0].relationship_targets == [f"C{n}" for n in range(6, 14)]


def test_parser_span_own_stance_beats_preamble_defense():
    """A4: a framing-retraction span is never recorded as a defense."""
    priors = [(f"C{n}", "Claude") for n in range(6, 14)]
    text = (
        "**Relationship:** Defended with clarification and evidence "
        "reconciliation.\n"
        "**Defending C6–C13 against C31, C33, C37, C39, C44, C45**\n"
        "1. (Revised) C6–C13 were presented as Observed, but I lack "
        "tool authority. I retract the framing. Those claims are "
        "Inferred, not Observed."
    )
    registered, _, _ = _revision(text, "Claude", priors)
    claim = registered[0]
    assert claim.relationship == "reclassifies"
    assert claim.relationship_targets == [f"C{n}" for n in range(6, 14)]
    assert claim.reclassified_status == "Inferred"


def test_parser_negated_stance_yields_nothing():
    """The rescue loop's negation guard: a negated stance word yields
    no move. (Boundary: the pre-mandate tight patterns match a verb
    directly adjacent to a target with no negation check, so "I do
    not withdraw C6" still parses as withdrawn — that old behavior is
    unchanged by this mandate; see MANDATE_EVIDENCE.md backlog.)"""
    priors = [(f"C{n}", "Claude") for n in range(6, 10)]
    for text in (
        "1. I do not withdraw the claims in C6–C9.",
        "1. C6–C9 are not withdrawn by me.",
    ):
        registered, _, _ = _revision(text, "Claude", priors)
        assert registered[0].relationship == "unstated"
        assert registered[0].relationship_targets == []
    # Positive control: the same sentence without negation moves.
    registered, _, _ = _revision(
        "1. I withdraw the claims in C6–C9.", "Claude", priors
    )
    assert registered[0].relationship == "withdrawn"
    assert registered[0].relationship_targets == ["C6", "C7", "C8", "C9"]


def test_parser_range_cap_fails_closed():
    priors = [(f"C{n}", "Claude") for n in range(1, 6)]
    text = "1. **Withdrawn:** C1–C500."
    registered, _, _ = _revision(text, "Claude", priors)
    assert registered[0].relationship == "unstated"
    assert registered[0].relationship_targets == []


def test_parser_bare_status_correction_stays_supersession():
    """Without a framing-retraction cue, a status correction is an
    ordinary revision, not a reclassification (detector boundary)."""
    priors = [("C6", "Claude")]
    text = "1. (Revised) C6: it is Inferred, not Observed."
    registered, _, _ = _revision(text, "Claude", priors)
    assert registered[0].relationship == "revised"
    assert registered[0].reclassified_status is None


def test_parser_citation_scope_revision_moves_nothing():
    priors = [(f"C{n}", "Claude") for n in range(6, 10)]
    text = "1. (Revised) The citations in C6–C9 are corrected to the packet."
    registered, _, _ = _revision(text, "Claude", priors)
    assert registered[0].relationship == "unstated"
    assert registered[0].relationship_targets == []


def test_parser_list_grammar_terminates_and_cross_author_proposes():
    priors = [("C4", "GPT"), ("C34", "Gemini"), ("C43", "Gemini")]
    text = (
        "1. (Inferred — revised: C4 in response to objection C34 "
        "(and C43). I revise and supersede C4."
    )
    registered, _, _ = _revision(text, "Gemini", priors)
    assert registered[0].relationship == "proposes_revision_of"
    assert registered[0].relationship_targets == ["C4"]


def test_parser_preamble_supplies_target_for_same_stance():
    """Span stance without a target takes the preamble's target for
    the SAME stance only (regression guard for the r2 suite's
    revised/defended/withdrawn revision test)."""
    priors = [("C3", "Gemini")]
    text = (
        "Relationship: withdrawn.\n"
        "In response to C3, I withdraw it:\n"
        "1. Withdrawn: Gamma is retracted."
    )
    registered, _, _ = _revision(text, "Gemini", priors)
    assert registered[0].relationship == "withdrawn"
    assert registered[0].relationship_target == "C3"
    assert registered[0].withdraws == "C3"


def test_parser_preamble_different_stance_never_overrides_span():
    """A different preamble stance never supplies a target for the
    span's own word (C54 shape: header 'Defended' vs span
    '(Revised)' — here with no span target at all)."""
    priors = [("C3", "Gemini")]
    text = (
        "Relationship: withdrawn.\n"
        "In response to C3, I withdraw it:\n"
        "1. (Revised) Gamma is updated."
    )
    registered, _, _ = _revision(text, "Gemini", priors)
    assert registered[0].relationship == "unstated"

# ------------------------------------------------------------- derivation


def test_derivation_multi_target_withdrawal():
    claims = [
        _claim_dict(f"C{n}", "Claude") for n in range(1, 4)
    ] + [
        _claim_dict(
            "C9", "Claude", phase="revision",
            relationship="withdrawn", relationship_target="C1",
            relationship_targets=["C1", "C2"],
        )
    ]
    entries = _standing(claims)
    assert entries["C1"]["standing"] == "withdrawn"
    assert entries["C2"]["standing"] == "withdrawn"
    assert entries["C3"]["standing"] == "active"


def test_derivation_mixed_authorship_list_moves_only_own():
    claims = [
        _claim_dict("C1", "Claude"),
        _claim_dict("C2", "GPT"),
        _claim_dict(
            "C9", "Claude", phase="revision",
            relationship="withdrawn", relationship_target="C1",
            relationship_targets=["C1", "C2"],
        ),
    ]
    entries = _standing(claims)
    assert entries["C1"]["standing"] == "withdrawn"
    assert entries["C2"]["standing"] == "active"
    assert entries["C9"]["rejected_moves"] == []


def test_derivation_reclassification_effective_status_retains_authored():
    claims = [
        _claim_dict("C6", "Claude", status="Observed"),
        _claim_dict(
            "C9", "Claude", phase="revision",
            relationship="reclassifies", relationship_target="C6",
            relationship_targets=["C6"], reclassified_status="Inferred",
        ),
    ]
    entries = _standing(claims)
    entry = entries["C6"]
    assert entry["standing"] == "active"
    assert entry["authored_status"] == "Observed"
    assert entry["effective_status"] == "Inferred"
    assert "effective: Inferred" in format_standing_headline(entry)


def test_derivation_reclassification_last_wins_with_chain():
    claims = [
        _claim_dict("C6", "Claude", status="Observed"),
        _claim_dict(
            "C9", "Claude", phase="revision",
            relationship="reclassifies", relationship_target="C6",
            relationship_targets=["C6"], reclassified_status="Inferred",
        ),
        _claim_dict(
            "C10", "Claude", phase="revision",
            relationship="reclassifies", relationship_target="C6",
            relationship_targets=["C6"], reclassified_status="Observed",
        ),
    ]
    entries = _standing(claims)
    assert entries["C6"]["effective_status"] == "Observed"
    assert len(entries["C6"]["reclassification_chain"]) == 2


def test_derivation_rejected_list_targets_with_siblings_applied():
    claims = [
        _claim_dict("C1", "Claude"),
        _claim_dict(
            "C9", "Claude", phase="revision",
            relationship="withdrawn", relationship_target="C1",
            relationship_targets=["C1", "C9", "C99"],
        ),
        _claim_dict("C10", "Claude", phase="revision"),
    ]
    # C9 self-target + unknown C99 are rejected; C1 still withdraws.
    # (C10 after C9 makes a forward reference impossible here; the
    # forward case is covered by the unknown/self rejections plus
    # the ordering unit in the standing suite.)
    entries = _standing(claims)
    assert entries["C1"]["standing"] == "withdrawn"
    reasons = {r["reason"] for r in entries["C9"]["rejected_moves"]}
    assert reasons == {"self_target", "unknown_target"}


def test_derivation_headline_omits_effective_when_equal():
    claims = [_claim_dict("C6", "Claude", status="Observed")]
    entry = _standing(claims)["C6"]
    assert "effective:" not in format_standing_headline(entry)


def test_derivation_citation_withdrawal_never_moves_content():
    claims = [
        _claim_dict(f"C{n}", "Claude") for n in range(6, 10)
    ] + [
        _claim_dict(
            "C9", "Claude", phase="revision",
            relationship="withdraws_citations", relationship_target="C6",
            relationship_targets=["C6", "C7", "C8", "C9"],
        )
    ]
    entries = _standing(claims)
    for n in range(6, 10):
        assert entries[f"C{n}"]["standing"] == "active"
    assert entries["C9"]["rejected_moves"] == []


def test_derivation_challenged_assessment_does_not_flip_standing():
    """A6: a challenged assessment is not a standing move."""
    claims = [_claim_dict("C6", "Claude", epistemic_assessment="challenged")]
    assert _standing(claims)["C6"]["standing"] == "active"


# ------------------------------------------------------------ audit (unit)


def _audit_claim(cid, participant, text):
    return {"id": cid, "participant": participant, "text": text}


def test_audit_narrated_read_unverified():
    findings = audit_prose_evidence_claims(
        [_audit_claim("C8", "Claude", "1. *[Read completed: local_ai/build_room/measurement.py]*")],
        [],
    )
    assert [(f["claim_id"], f["inspection_verdict"]) for f in findings] == [("C8", "unverified")]


def test_audit_attempt_with_logged_refusal_verified():
    calls = [{"participant": "GPT", "requested_path": "local_ai/build_room/meeting.py",
              "resolved_path": "local_ai/build_room/meeting.py", "outcome": "refused"}]
    findings = audit_prose_evidence_claims(
        [_audit_claim("C1", "GPT", "I attempted to read the file at the unauthorized path `local_ai/build_room/meeting.py`")],
        calls,
    )
    assert [(f["claim_id"], f["inspection_verdict"]) for f in findings] == [("C1", "verified")]


def test_audit_request_made_contradicted_only_when_log_complete():
    claim = _audit_claim(
        "C5", "GPT",
        "The request for `local_ai/build_room/meeting.py` was made, but this path is not in the nominated set.")
    other_calls = [{"participant": "GPT", "requested_path": "local_ai/build_room/tool_access.py",
                    "resolved_path": "local_ai/build_room/tool_access.py", "outcome": "returned"}]
    assert audit_prose_evidence_claims(
        [claim], other_calls, log_complete_participants={"GPT"}
    )[0]["inspection_verdict"] == "contradicted"
    assert audit_prose_evidence_claims(
        [claim], other_calls
    )[0]["inspection_verdict"] == "unverified"


def test_audit_request_made_with_logged_attempt_verified():
    calls = [{"participant": "GPT", "requested_path": "local_ai/build_room/meeting.py",
              "resolved_path": "local_ai/build_room/meeting.py", "outcome": "returned"}]
    findings = audit_prose_evidence_claims(
        [_audit_claim("C5", "GPT", "The request for `local_ai/build_room/meeting.py` was made.")],
        calls, log_complete_participants={"GPT"},
    )
    assert findings[0]["inspection_verdict"] == "verified"


def test_audit_honest_negatives_not_flagged():
    texts = [
        "No file reads have been performed because no tool capability is available.",
        "I performed no read_file calls in this exchange.",
        "I have performed no file reads myself.",
        "I read the packet, not the source files.",
    ]
    claims = [_audit_claim(f"C{n}", "Claude", t) for n, t in enumerate(texts, 1)]
    assert audit_prose_evidence_claims(claims, []) == []


def test_audit_meta_discussion_not_flagged():
    texts = [
        "The absence of performed reads in C6–C13 is noted.",
        "GPT's performed reads are the only logged ones.",
        "C33 reports execution outputs (`*[Read completed...]*`) without a path.",
        "C54 retracts the read statements in C6–C13.",
    ]
    claims = [_audit_claim(f"C{n}", "Gemini", t) for n, t in enumerate(texts, 1)]
    assert audit_prose_evidence_claims(claims, []) == []

# ------------------------------------------------------------- replay


def _replay(fixture_name):
    """Replay a stored meeting's contributions; return (artifact, stored)."""
    fixture = _load(fixture_name)
    artifact = replay_r2_transcript(
        fixture["contributions"], meeting_id="mandate-replay"
    )
    return artifact, fixture


def _replayed_claims(artifact):
    return {c["id"]: c for c in artifact["claim_registry"]}


def _replayed_standing(artifact):
    return {e["claim_id"]: e for e in artifact["claim_standing"]["entries"]}


def _diff(stored, replayed):
    """(claim, field) diffs between stored and replayed claim dicts."""
    keys = (
        "relationship", "relationship_target", "relationship_targets",
        "supersedes", "withdraws", "disposition", "disposition_by",
        "status", "epistemic_assessment", "reclassified_status",
    )
    out = {}
    for cid, s in stored.items():
        r = replayed[cid]
        diffs = {}
        for k in keys:
            sv, rv = s.get(k), r.get(k)
            if k == "relationship_targets":
                sv, rv = sv or [], rv or []
            if sv != rv:
                diffs[k] = (sv, rv)
        if diffs:
            out[cid] = diffs
    return out


def test_replay_probe_identity():
    artifact, fixture = _replay("mandate_probe_replay.json")
    stored = {c["id"]: c for c in fixture["claim_registry"]}
    replayed = _replayed_claims(artifact)
    assert len(replayed) == len(stored) == 71
    assert set(replayed) == set(stored)
    # No mutation of untouched record fields: every replayed claim
    # text is verbatim identical to the stored text.
    for cid in stored:
        assert replayed[cid]["text"] == stored[cid]["text"]


def test_replay_probe_relationships():
    """A2/A4 shape (probe): reclassification, defense, citation
    withdrawal, contested preservation, cross-author proposal."""
    artifact, _ = _replay("mandate_probe_replay.json")
    claims = _replayed_claims(artifact)
    assert claims["C54"]["relationship"] == "reclassifies"
    assert claims["C54"]["relationship_targets"] == [f"C{n}" for n in range(6, 14)]
    assert claims["C54"]["reclassified_status"] == "Inferred"
    assert claims["C55"]["relationship"] == "defended"
    assert claims["C55"]["relationship_targets"] == [f"C{n}" for n in range(6, 14)]
    assert claims["C56"]["relationship"] == "withdraws_citations"
    assert claims["C56"]["relationship_targets"] == ["C6", "C7", "C8", "C9"]
    assert claims["C61"]["relationship"] == "unstated"
    assert claims["C62"]["relationship"] == "proposes_revision_of"
    assert claims["C62"]["relationship_targets"] == ["C4"]


def test_replay_probe_standing():
    """A3/A5/A6/A7: effective Inferred with authored retained, C61
    active, challenged claims still active, citation withdrawal
    leaves content active."""
    artifact, fixture = _replay("mandate_probe_replay.json")
    standing = _replayed_standing(artifact)
    # Before (stored registry): C6 active with no effective downgrade.
    before = _standing(fixture["claim_registry"])
    assert before["C6"]["standing"] == "active"
    assert before["C6"]["effective_status"] == "Observed"
    for n in range(6, 14):
        entry = standing[f"C{n}"]
        assert entry["standing"] == "active"
        assert entry["effective_status"] == "Inferred"
    assert standing["C6"]["authored_status"] == "Observed"
    assert standing["C61"]["standing"] == "active"
    claims = _replayed_claims(artifact)
    for n in range(6, 10):
        assert claims[f"C{n}"]["epistemic_assessment"] == "challenged"
        assert standing[f"C{n}"]["standing"] == "active"


def test_replay_probe_audit():
    """A8: narrated reads unverified; honest attempts verified."""
    artifact, fixture = _replay("mandate_probe_replay.json")
    findings = audit_prose_evidence_claims(
        artifact["claim_registry"], fixture["tool_calls"],
        log_complete_participants={"GPT"},
    )
    got = {(f["claim_id"], f["inspection_verdict"]) for f in findings}
    assert got == {
        ("C1", "verified"), ("C48", "verified"),
        ("C8", "unverified"), ("C10", "unverified"), ("C12", "unverified"),
    }


def test_replay_live_identity():
    artifact, fixture = _replay("mandate_live_replay.json")
    stored = {c["id"]: c for c in fixture["claim_registry"]}
    replayed = _replayed_claims(artifact)
    assert len(replayed) == len(stored) == 75
    assert set(replayed) == set(stored)
    for cid in stored:
        assert replayed[cid]["text"] == stored[cid]["text"]


def test_replay_live_relationships_and_standing():
    """A1/A2: C70's list and C68's retraction both extract as
    18-target withdrawals; C30-C44 derive withdrawn."""
    artifact, fixture = _replay("mandate_live_replay.json")
    claims = _replayed_claims(artifact)
    targets = [f"C{n}" for n in range(27, 45)]
    for mover in ("C68", "C70"):
        assert claims[mover]["relationship"] == "withdrawn"
        assert claims[mover]["relationship_targets"] == targets
    standing = _replayed_standing(artifact)
    before = _standing(fixture["claim_registry"])
    for n in range(30, 38):
        assert before[f"C{n}"]["standing"] == "active"
    for n in range(27, 45):
        assert standing[f"C{n}"]["standing"] == "withdrawn"


def test_replay_live_audit_a9():
    """A9: the meeting.py request claim is CONTRADICTED only under
    the complete-log attestation (GPT is runner-mediated; the runner
    drains every attempt including refusals into the log, and the
    live log holds 12 GPT attempts, none for meeting.py). Without
    the attestation the same claim is UNVERIFIED, never verified."""
    artifact, fixture = _replay("mandate_live_replay.json")
    claims = artifact["claim_registry"]
    complete = audit_prose_evidence_claims(
        claims, fixture["tool_calls"], log_complete_participants={"GPT"}
    )
    got = {(f["claim_id"], f["inspection_verdict"]) for f in complete}
    assert got == {
        ("C5", "contradicted"), ("C26", "contradicted"), ("C65", "contradicted"),
    }
    c5 = [c for c in claims if c["id"] == "C5"]
    incomplete = audit_prose_evidence_claims(c5, fixture["tool_calls"])
    assert [(f["claim_id"], f["inspection_verdict"]) for f in incomplete] == [
        ("C5", "unverified")
    ]


def test_replay_divergence_set_is_exactly_the_intended_set():
    """Regression guard: the replay changes NOTHING beyond the
    intended parses (reclassification, defense, citation withdrawal,
    range withdrawals, list-form storage, and the dispositions those
    moves set). Any other divergence fails this test."""
    probe_artifact, probe_fixture = _replay("mandate_probe_replay.json")
    probe_stored = {c["id"]: c for c in probe_fixture["claim_registry"]}
    probe_diff = _diff(probe_stored, _replayed_claims(probe_artifact))
    c6_13 = [f"C{n}" for n in range(6, 14)]
    expected_probe = {
        "C54": {
            "relationship": ("defended", "reclassifies"),
            "relationship_targets": ([], c6_13),
            "reclassified_status": (None, "Inferred"),
        },
        "C55": {
            "relationship": ("unstated", "defended"),
            "relationship_target": ("unstated", "C6"),
            "relationship_targets": ([], c6_13),
        },
        "C56": {
            "relationship": ("unstated", "withdraws_citations"),
            "relationship_target": ("unstated", "C6"),
            "relationship_targets": ([], ["C6", "C7", "C8", "C9"]),
        },
        "C62": {
            "relationship": ("unstated", "proposes_revision_of"),
            "relationship_target": ("unstated", "C4"),
            "relationship_targets": ([], ["C4"]),
        },
        "C69": {
            "relationship_targets": ([], ["C27"]),
            "supersedes": ("C27", None),
        },
        "C6": {"disposition_by": ("C54", "C55")},
    }
    for n in range(7, 14):
        expected_probe[f"C{n}"] = {
            "disposition": (None, "maintained"),
            "disposition_by": (None, "C55"),
        }
    assert probe_diff == expected_probe

    live_artifact, live_fixture = _replay("mandate_live_replay.json")
    live_stored = {c["id"]: c for c in live_fixture["claim_registry"]}
    live_diff = _diff(live_stored, _replayed_claims(live_artifact))
    targets_27_44 = [f"C{n}" for n in range(27, 45)]
    expected_live = {
        "C68": {
            "relationship": ("unstated", "withdrawn"),
            "relationship_target": ("unstated", "C27"),
            "relationship_targets": ([], targets_27_44),
        },
        "C70": {
            "relationship": ("unstated", "withdrawn"),
            "relationship_target": ("unstated", "C27"),
            "relationship_targets": ([], targets_27_44),
        },
        "C71": {"relationship_targets": ([], ["C1"])},
        "C72": {"relationship_targets": ([], ["C4"])},
        "C73": {"relationship_targets": ([], ["C5"])},
    }
    for n in range(27, 45):
        expected_live[f"C{n}"] = {
            "disposition": (None, "withdrawn"),
            "disposition_by": (None, "C68"),
        }
    assert live_diff == expected_live
