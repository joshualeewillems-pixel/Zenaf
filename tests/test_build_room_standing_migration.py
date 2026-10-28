"""Registry standing stage-4 tests: derivation-only migration.

Stage 4 appends the ``claim_standing`` section to stored artifacts
that predate it, from the registry they already carry. Nothing else
changes: claim records and every other field are untouched, the
input is never mutated, failures leave the artifact exactly as it
was, and unmigrated artifacts report "standing not computed" —
never an assumed standing. No live API calls, no live store.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest import mock

from local_ai.build_room.claim_standing import compute_claim_standing
from local_ai.build_room.migration import (
    STANDING_NOT_COMPUTED,
    migrate_artifact_standing,
    migrate_store_dir,
)

FIXTURE = Path(__file__).parent / "fixtures" / "probe_artifact_registry.json"


def _small_artifact():
    return {
        "status": "DRAFT_EXPERIMENTAL",
        "meeting_id": "test123",
        "claim_registry": [
            {"id": "C1", "participant": "GPT", "phase": "opening",
             "status": "Observed", "text": "Authority confusion is a risk.",
             "supersedes": None, "withdraws": None,
             "epistemic_assessment": "unresolved", "assessment_sources": []},
            {"id": "C2", "participant": "GPT", "phase": "revision",
             "status": "Inferred", "text": "I withdraw C1.",
             "supersedes": None, "withdraws": "C1",
             "epistemic_assessment": "unresolved", "assessment_sources": []},
        ],
        "interactions": [],
    }


def test_migration_appends_only_the_section():
    artifact = _small_artifact()
    before = copy.deepcopy(artifact)
    migrated, report = migrate_artifact_standing(artifact)
    assert report["migrated"] is True
    assert report["standing"] == "computed"
    assert report["claims"] == 2
    # The input is never mutated.
    assert artifact == before
    # The section equals a fresh derivation from the stored record.
    assert migrated["claim_standing"] == compute_claim_standing(
        artifact["claim_registry"], artifact["interactions"])
    # Everything else is identical — including byte-identical claim
    # records (the plan's byte-comparison, at the record level).
    for key in artifact:
        if key == "claim_standing":
            continue
        assert migrated[key] == artifact[key]
    assert json.dumps(migrated["claim_registry"], sort_keys=True) == json.dumps(
        artifact["claim_registry"], sort_keys=True)
    c1 = next(e for e in migrated["claim_standing"]["entries"]
              if e["claim_id"] == "C1")
    assert c1["standing"] == "withdrawn"
    assert c1["standing_chain"] == [
        {"move": "withdrawal", "by": "C2", "target": "C1"}]


def test_already_present_is_left_untouched():
    artifact = _small_artifact()
    artifact["claim_standing"] = {"version": 1, "entries": []}
    before = copy.deepcopy(artifact)
    migrated, report = migrate_artifact_standing(artifact)
    assert report["migrated"] is False
    assert report["standing"] == "computed"
    assert report["reason"] == "claim_standing already present"
    assert migrated == before


def test_unusable_registries_report_not_computed():
    cases = [
        ({"meeting_id": "x"}, "no claim registry"),
        ({"claim_registry": []}, "no claim registry"),
        ({"claim_registry": [{"participant": "GPT"}]}, "without an id"),
        ({"claim_registry": ["C1"]}, "not an object"),
        ({"claim_registry": [
            {"id": "C1", "participant": "GPT", "phase": "opening"},
            {"id": "C1", "participant": "GPT", "phase": "opening"},
        ]}, "duplicate claim id"),
        ({"claim_registry": [
            {"id": "C1", "participant": "GPT", "phase": "opening"}],
          "interactions": {"not": "a list"}}, "not a list"),
    ]
    for artifact, reason_fragment in cases:
        before = copy.deepcopy(artifact)
        migrated, report = migrate_artifact_standing(artifact)
        assert report["migrated"] is False, artifact
        assert report["standing"] == STANDING_NOT_COMPUTED
        assert reason_fragment in report["reason"], report
        assert migrated == before
        assert "claim_standing" not in migrated


def test_derivation_failure_leaves_artifact_exactly_as_it_was():
    artifact = _small_artifact()
    before = copy.deepcopy(artifact)
    with mock.patch(
        "local_ai.build_room.migration.compute_claim_standing",
        side_effect=RuntimeError("boom"),
    ):
        migrated, report = migrate_artifact_standing(artifact)
    assert report["migrated"] is False
    assert report["standing"] == STANDING_NOT_COMPUTED
    assert "derivation failed" in report["reason"]
    assert migrated == before


def test_probe_artifact_migrates_to_the_v2_worked_example():
    """The plan's verification: the corrective-probe artifact's
    migrated table matches design v2's worked example for C6.

    The fixture is the probe artifact's claim registry + interactions
    reduced to exactly the fields the derivation reads; it was
    verified to reproduce the full artifact's table identically.
    """
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    artifact = {
        "status": "DRAFT_EXPERIMENTAL",
        "meeting_id": fixture["meeting_id"],
        "claim_registry": fixture["claim_registry"],
        "interactions": fixture["interactions"],
    }
    before_registry = json.dumps(artifact["claim_registry"], sort_keys=True)
    migrated, report = migrate_artifact_standing(artifact)
    assert report["migrated"] is True
    assert report["claims"] == 71
    table = migrated["claim_standing"]
    assert len(table["entries"]) == 71
    by_id = {e["claim_id"]: e for e in table["entries"]}
    c6 = by_id["C6"]
    assert c6["authored_status"] == "Observed"
    assert c6["standing"] == "active"
    assert c6["assessment"] == "challenged"
    assert c6["provenance"] == "unverified"
    assert [s["by"] for s in c6["retraction_signals"]] == ["C54", "C56", "C61"]
    # Claim records byte-identical after migration.
    assert json.dumps(migrated["claim_registry"], sort_keys=True) == before_registry
    # And the honest stage-1 conclusion survives: no valid withdrawal
    # was ever emitted, so nothing reads withdrawn.
    assert not any(e["standing"] == "withdrawn" for e in table["entries"])


def _write(path: Path, payload) -> None:
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")


def test_store_dir_pass_writes_only_migrated_files(tmp_path):
    store = tmp_path / "build_room"
    store.mkdir()
    migratable = _small_artifact()
    already = _small_artifact()
    already["claim_standing"] = {"version": 1, "entries": []}
    _write(store / "meeting_aaa.draft_artifact.json", migratable)
    _write(store / "meeting_bbb.draft_artifact.json", already)
    _write(store / "meeting_ccc.draft_artifact.json", "{not json")
    _write(store / "meeting_ddd.draft_artifact.json", {"meeting_id": "no-registry"})
    _write(store / "unrelated.json", migratable)
    already_bytes = (store / "meeting_bbb.draft_artifact.json").read_bytes()
    corrupt_bytes = (store / "meeting_ccc.draft_artifact.json").read_bytes()
    noreg_bytes = (store / "meeting_ddd.draft_artifact.json").read_bytes()
    unrelated_bytes = (store / "unrelated.json").read_bytes()

    report = migrate_store_dir(store)
    assert report["migrated"] == 1
    assert report["already_present"] == 1
    assert report["unmigrated"] == 1
    assert report["failed"] == 1
    assert len(report["files"]) == 4  # the unrelated file is not an artifact

    migrated_on_disk = json.loads(
        (store / "meeting_aaa.draft_artifact.json").read_text(encoding="utf-8"))
    assert "claim_standing" in migrated_on_disk
    assert migrated_on_disk["claim_registry"] == migratable["claim_registry"]
    # Everything else byte-identical.
    assert (store / "meeting_bbb.draft_artifact.json").read_bytes() == already_bytes
    assert (store / "meeting_ccc.draft_artifact.json").read_bytes() == corrupt_bytes
    assert (store / "meeting_ddd.draft_artifact.json").read_bytes() == noreg_bytes
    assert (store / "unrelated.json").read_bytes() == unrelated_bytes

    # Second run is a no-op: the migrated file now reports already
    # present, and its bytes do not change again.
    second_bytes = (store / "meeting_aaa.draft_artifact.json").read_bytes()
    report2 = migrate_store_dir(store)
    assert report2["migrated"] == 0
    assert report2["already_present"] == 2
    assert (store / "meeting_aaa.draft_artifact.json").read_bytes() == second_bytes


def test_store_dir_pass_dry_run_changes_nothing(tmp_path):
    store = tmp_path / "build_room"
    store.mkdir()
    _write(store / "meeting_aaa.draft_artifact.json", _small_artifact())
    before = (store / "meeting_aaa.draft_artifact.json").read_bytes()
    report = migrate_store_dir(store, dry_run=True)
    assert report["migrated"] == 1
    assert report["dry_run"] is True
    assert (store / "meeting_aaa.draft_artifact.json").read_bytes() == before


def test_store_dir_pass_missing_directory_reports_without_raising():
    report = migrate_store_dir("/nonexistent/store/dir")
    assert report["migrated"] == 0
    assert report["files"] == []
    assert "error" in report
