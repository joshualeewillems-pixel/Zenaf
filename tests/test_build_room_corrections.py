"""Increment E: correction input path (tooling + validator interaction).

Proven with synthetic fixtures only (no model calls, no spend).
Validator interaction is tested by running validate_contract_record
over tooling outputs and hand-built records and asserting on E11
(and E7) codes specifically: other codes (e.g. E12 for fixture
claims without exposure) describe the fixtures, not the
corrections, and are filtered out following the Increment C
convention.
"""

import copy

import pytest

from local_ai.build_room.corrections import (
    PROVENANCE_CONVENER,
    PROVENANCE_USER,
    apply_convener_correction,
    apply_correction,
    apply_user_correction,
    correction_chain,
    resolve_head,
)
from local_ai.build_room.transjective_record import (
    build_transjective_record,
    validate_contract_record,
)


def claim(cid, text="t"):
    return {"id": cid, "participant": "GPT", "phase": "opening", "text": text}


def base_record():
    return {"claims": [claim("C1", "first"), claim("C2", "second")]}


def codes(report, wanted):
    return [e for e in report["errors"] if e["code"] in wanted]


def e11(report):
    return codes(report, {"E11"})


def hand_corr(cid, sup, **extra):
    d = {
        "id": cid,
        "original_value": "v0",
        "corrected_value": "v1",
        "author_or_process": "convener-tooling",
        "reason": "fix",
        "superseded_record": sup,
    }
    d.update(extra)
    return d


# --- Acceptance 1: missing element -> E11 (tooling refuses; validator E11s) ---


def test_tooling_refuses_missing_elements():
    for field in ("original_value", "corrected_value", "author_or_process", "reason"):
        kwargs = {
            "target_id": "C1",
            "original_value": "v0",
            "corrected_value": "v1",
            "author_or_process": "convener-tooling",
            "reason": "fix",
        }
        kwargs[field] = None
        with pytest.raises(ValueError, match="missing elements"):
            apply_correction(base_record(), **kwargs)
    with pytest.raises(ValueError, match="target_id"):
        apply_correction(
            base_record(),
            target_id="",
            original_value="v0",
            corrected_value="v1",
            author_or_process="convener-tooling",
            reason="fix",
        )


def test_validator_e11_missing_elements():
    for field in (
        "original_value",
        "corrected_value",
        "author_or_process",
        "reason",
        "superseded_record",
    ):
        corr = hand_corr("K1", "C1")
        corr[field] = None
        report = validate_contract_record(
            {**base_record(), "corrections": [corr]}
        )
        assert e11(report), f"expected E11 for missing {field}"


# --- Acceptance 2: non-head without reconciliation -> E11 ---


def test_non_head_without_reconciliation_e11():
    rec = {
        **base_record(),
        "corrections": [
            hand_corr("K1", "C1"),
            hand_corr("K2", "C1"),  # cites origin while head K1 exists
        ],
    }
    assert e11(validate_contract_record(rec))
    rec2 = {
        **base_record(),
        "corrections": [
            hand_corr("K1", "C1"),
            hand_corr(
                "K2",
                "C1",
                reconciles={"heads": ["K1"], "resolver": "R", "reason": "r"},
            ),
            hand_corr("K3", "K1"),  # cites non-head correction, no reconciles
        ],
    }
    assert e11(validate_contract_record(rec2))


def test_stale_snapshot_compete_then_reconcile():
    snapshot = base_record()
    r1 = apply_convener_correction(
        snapshot,
        target_id="C1",
        original_value="v0",
        corrected_value="v1",
        reason="fix",
        correction_id="K1",
    )
    # A second builder working from the pre-K1 snapshot cites the
    # origin again: the validator must reject it without reconciliation.
    stale = apply_user_correction(
        snapshot,
        target_id="C1",
        original_value="v0",
        corrected_value="v2",
        reason="other fix",
        correction_id="K2",
    )
    merged = {
        **base_record(),
        "corrections": r1["corrections"] + stale["corrections"],
    }
    assert e11(validate_contract_record(merged))
    # With a reconciliation citing the current head, it validates.
    r2 = apply_user_correction(
        r1,
        target_id="C1",
        original_value="v0",
        corrected_value="v2",
        reason="other fix",
        correction_id="K2",
        reconciles={"heads": ["K1"], "resolver": "convener", "reason": "merge"},
    )
    assert not e11(validate_contract_record(r2))
    assert resolve_head(r2, "C1") == "K2"


# --- Acceptance 3: valid reconciliation becomes head ---


def test_valid_reconciliation_becomes_head():
    r1 = apply_convener_correction(
        base_record(),
        target_id="C1",
        original_value="v0",
        corrected_value="v1",
        reason="fix",
        correction_id="K1",
    )
    assert resolve_head(r1, "C1") == "K1"
    r2 = apply_user_correction(
        r1,
        target_id="C1",
        original_value="v0",
        corrected_value="v2",
        reason="merge",
        correction_id="K2",
        reconciles={"heads": ["K1"], "resolver": "convener", "reason": "merge"},
    )
    assert resolve_head(r2, "C1") == "K2"
    assert not e11(validate_contract_record(r2))
    # A later reconciliation citing the OLD head is stale: the
    # validator rejects it, and the tooling refuses to build it.
    stale = {
        **base_record(),
        "corrections": r2["corrections"]
        + [
            hand_corr(
                "K3",
                "C1",
                reconciles={"heads": ["K1"], "resolver": "R", "reason": "r"},
            )
        ],
    }
    assert e11(validate_contract_record(stale))
    with pytest.raises(ValueError, match="reconciliation"):
        apply_convener_correction(
            r2,
            target_id="C1",
            original_value="v0",
            corrected_value="v3",
            reason="late",
            correction_id="K3",
            reconciles={"heads": ["K1"], "resolver": "R", "reason": "r"},
        )


def test_reconciliation_correction_is_citable():
    # Regression: a correction citing a reconciliation correction
    # by id used to crash the validator (KeyError) because the
    # reconciliation branch never recorded the chain map. Citing
    # the head validates; citing a non-head still E11s.
    rec = {
        **base_record(),
        "corrections": [
            hand_corr("K1", "C1"),
            hand_corr(
                "K2",
                "C1",
                reconciles={"heads": ["K1"], "resolver": "R", "reason": "m"},
            ),
            hand_corr("K3", "K2"),
        ],
    }
    assert not e11(validate_contract_record(rec))
    rec_stale = {
        **base_record(),
        "corrections": [
            hand_corr("K1", "C1"),
            hand_corr(
                "K2",
                "C1",
                reconciles={"heads": ["K1"], "resolver": "R", "reason": "m"},
            ),
            hand_corr("K3", "K1"),
        ],
    }
    assert e11(validate_contract_record(rec_stale))


def test_reconciles_on_fresh_chain_refused():
    with pytest.raises(ValueError, match="nothing to reconcile"):
        apply_convener_correction(
            base_record(),
            target_id="C1",
            original_value="v0",
            corrected_value="v1",
            reason="fix",
            reconciles={"heads": ["C1"], "resolver": "R", "reason": "r"},
        )


# --- Acceptance 4: originals never overwritten ---


def test_originals_never_overwritten():
    record = base_record()
    snapshot = copy.deepcopy(record)
    r1 = apply_convener_correction(
        record,
        target_id="C1",
        original_value="first",
        corrected_value="first-fixed",
        reason="typo",
        correction_id="K1",
    )
    r2 = apply_user_correction(
        r1,
        target_id="C1",
        original_value="first",
        corrected_value="first-fixed-again",
        reason="clarity",
        correction_id="K2",
        reconciles={"heads": ["K1"], "resolver": "convener", "reason": "merge"},
    )
    # Input untouched: same claims, no corrections key added.
    assert record == snapshot
    assert "corrections" not in record
    # New records carry the chain; the original claim is intact.
    assert r2["claims"][0]["text"] == "first"
    assert [c["id"] for c in r2["corrections"]] == ["K1", "K2"]
    assert r2["corrections"][0]["original_value"] == "first"
    assert r2["corrections"][0]["superseded_record"] == "C1"
    assert r2["corrections"][1]["superseded_record"] == "C1"  # origin-citing
    assert r1["corrections"] is not r2["corrections"]


# --- Acceptance 5: distinct provenance, never blended ---


def test_distinct_provenance():
    r1 = apply_convener_correction(
        base_record(),
        target_id="C1",
        original_value="v0",
        corrected_value="v1",
        reason="fix",
        correction_id="K1",
    )
    r2 = apply_user_correction(
        r1,
        target_id="C2",
        original_value="w0",
        corrected_value="w1",
        reason="user fix",
        correction_id="K2",
    )
    prov = [c["author_or_process"] for c in r2["corrections"]]
    assert prov == [PROVENANCE_CONVENER, PROVENANCE_USER]
    assert prov[0] != prov[1]
    assert not e11(validate_contract_record(r2))
    # Blended or unknown provenance is refused, not defaulted.
    for bad in ("convener-tooling/user", "admin", "", "system"):
        with pytest.raises(ValueError, match="author_or_process"):
            apply_correction(
                base_record(),
                target_id="C1",
                original_value="v0",
                corrected_value="v1",
                author_or_process=bad,
                reason="fix",
            )
    # Named entry points pin provenance: no provenance argument exists.
    with pytest.raises(TypeError):
        apply_convener_correction(
            base_record(),
            target_id="C1",
            original_value="v0",
            corrected_value="v1",
            reason="fix",
            author_or_process="user",
        )


def test_user_correction_is_not_e7():
    # The E7 user ban restricts disposition EVENT authorizers, not
    # correction authorship: a user correction validates with no E7.
    r1 = apply_user_correction(
        base_record(),
        target_id="C1",
        original_value="v0",
        corrected_value="v1",
        reason="user fix",
        correction_id="K1",
    )
    report = validate_contract_record(r1, meeting_kind="build_council")
    assert not codes(report, {"E7"})


# --- Tooling outputs validate clean on E11; heads and chains ---


def test_tooling_outputs_validate_clean_on_e11():
    r1 = apply_convener_correction(
        base_record(),
        target_id="C1",
        original_value="v0",
        corrected_value="v1",
        reason="fix",
        correction_id="K1",
    )
    r2 = apply_user_correction(
        r1,
        target_id="C1",
        original_value="v0",
        corrected_value="v2",
        reason="merge",
        correction_id="K2",
        reconciles={"heads": ["K1"], "resolver": "convener", "reason": "merge"},
    )
    assert not e11(validate_contract_record(r2))


def test_head_resolution_and_chain_audit():
    record = base_record()
    assert resolve_head(record, "C1") == "C1"
    r1 = apply_convener_correction(
        record,
        target_id="C1",
        original_value="v0",
        corrected_value="v1",
        reason="fix",
        correction_id="K1",
    )
    assert resolve_head(r1, "C1") == "K1"
    # Resolving via a correction id follows its chain to the head.
    assert resolve_head(r1, "K1") == "K1"
    r2 = apply_user_correction(
        r1,
        target_id="C1",
        original_value="v0",
        corrected_value="v2",
        reason="merge",
        correction_id="K2",
        reconciles={"heads": ["K1"], "resolver": "convener", "reason": "merge"},
    )
    assert resolve_head(r2, "K1") == "K2"
    assert [c["id"] for c in correction_chain(r2, "C1")] == ["K1", "K2"]
    with pytest.raises(ValueError, match="unknown correction target"):
        resolve_head(r2, "C99")
    with pytest.raises(ValueError, match="unknown correction target"):
        apply_convener_correction(
            r2,
            target_id="C99",
            original_value="v0",
            corrected_value="v1",
            reason="fix",
        )


def test_chain_audit_excludes_invalid_corrections():
    rec = {
        **base_record(),
        "corrections": [
            hand_corr("K1", "C1"),
            hand_corr("Kbad", "C1", reason=None),
        ],
    }
    assert [c["id"] for c in correction_chain(rec, "C1")] == ["K1"]


def test_correction_id_rules():
    r1 = apply_convener_correction(
        base_record(),
        target_id="C1",
        original_value="v0",
        corrected_value="v1",
        reason="fix",
    )
    r2 = apply_user_correction(
        r1,
        target_id="C1",
        original_value="v0",
        corrected_value="v2",
        reason="fix2",
        reconciles={"heads": ["correction:1"], "resolver": "R", "reason": "r"},
    )
    ids = [c["id"] for c in r2["corrections"]]
    assert ids == ["correction:1", "correction:2"]
    with pytest.raises(ValueError, match="duplicate correction id"):
        apply_convener_correction(
            r2,
            target_id="C1",
            original_value="v0",
            corrected_value="v3",
            reason="fix3",
            correction_id="correction:1",
        )


# --- Corrections never move standing; section wiring is additive ---


def test_corrections_do_not_move_standing():
    plain = validate_contract_record(base_record())
    corrected = validate_contract_record(
        apply_convener_correction(
            base_record(),
            target_id="C1",
            original_value="v0",
            corrected_value="v1",
            reason="fix",
            correction_id="K1",
        )
    )
    assert (
        corrected["derived_contract_standing"]
        == plain["derived_contract_standing"]
    )


def test_build_section_corrections_key():
    claims = [claim("C1", "first"), claim("C2", "second")]
    section = build_transjective_record(claims)
    assert "corrections" not in section  # old callers see no new key
    section_empty = build_transjective_record(claims, corrections=[])
    assert section_empty["corrections"] == []
    r1 = apply_convener_correction(
        {"claims": claims},
        target_id="C1",
        original_value="v0",
        corrected_value="v1",
        reason="fix",
        correction_id="K1",
    )
    section_corr = build_transjective_record(
        claims, corrections=r1["corrections"]
    )
    assert section_corr["corrections"] == r1["corrections"]
    assert not e11(
        validate_contract_record(
            {"claims": claims, "corrections": r1["corrections"]}
        )
    )
