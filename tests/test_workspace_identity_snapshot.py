"""Workspace identity snapshot: bounded scan, packet, branch usability."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collections import Counter

from local_ai.workspace_identity.buffer_contracts import (
    BUFFER_BEHAVIORAL_CONTRACTS,
    BUFFER_PIPELINE_KEYS,
    decision_surface_excludes_literal_buffer_layers,
    decision_surface_from_buffers,
    validate_buffer_output_shape,
    validate_buffer_stack_present,
)
from local_ai.workspace_identity.buffers import (
    build_all_buffers,
    build_associative_clusters,
    keep_packet_surface_literal,
    keep_path_sketch_literal,
    keep_surface_shallow_phrase,
)
from local_ai.workspace_identity.snapshot import (
    IDENTITY_LOW_QUALITY_USER_MESSAGE,
    SCHEMA_VERSION,
    build_workspace_identity_snapshot,
    build_workspace_packet_from_snapshot,
    default_workspace_identity_dir,
    read_snapshot_file,
    snapshot_usable_for_extract,
    write_workspace_identity_snapshot,
)


def test_google_rs_query_cache_files_suppressed(tmp_path: Path) -> None:
    (tmp_path / "rs=AA2YrTtGj0ppAB9TeeShbTNSI3bE_iNr4Q").write_bytes(b"x")
    (tmp_path / "async_usersync(1)").write_bytes(b"x")
    good = tmp_path / "RealClinicModule"
    good.mkdir()
    (good / "notes.md").write_text("x", encoding="utf-8")

    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=5, max_nodes=800)
    joined = " ".join(snap.get("domainHints") or []).lower()
    assert "aa2y" not in joined
    assert "usersync" not in joined
    assert "realclinic" in joined or "module" in joined


def test_saved_page_companion_files_folder_not_scanned(tmp_path: Path) -> None:
    junk = tmp_path / "Cyclic breathing_ Why experts say just 5 minutes a day can reduce stress_files"
    junk.mkdir()
    (junk / "script.js").write_text("//x", encoding="utf-8")
    good = tmp_path / "HealingHavenModule"
    good.mkdir()
    (good / "notes.md").write_text("x", encoding="utf-8")

    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=5, max_nodes=800)
    joined = " ".join(snap.get("domainHints") or []).lower()
    assert "cyclic" not in joined
    assert "breathing" not in joined
    assert "healing" in joined or "haven" in joined or "module" in joined


def test_short_underscore_files_folder_still_walked(tmp_path: Path) -> None:
    d = tmp_path / "user_files"
    d.mkdir()
    (d / "data.txt").write_text("x", encoding="utf-8")
    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=4, max_nodes=400)
    surfaces = (snap.get("rawIndex") or {}).get("surfaces") or []
    rels = " ".join(str(s.get("pathRelative") or "") for s in surfaces).lower()
    assert "user_files" in rels


def test_associative_clusters_skip_saved_page_and_rs_paths() -> None:
    records = [
        {"pathRelative": "services/auth/a.py", "label": "a.py"},
        {"pathRelative": "services/auth/b.py", "label": "b.py"},
        {"pathRelative": "downloads/Article Title_files/x.js", "label": "x.js"},
        {"pathRelative": "cache/rs=AA2YrTtGj0ppAB9TeeShbTNSI3bE_iNr4Q", "label": "rs=AA2YrTtGj0ppAB9TeeShbTNSI3bE_iNr4Q"},
        {
            "pathRelative": "desk/AI Guide — Demo [Accelerator]/z.py",
            "label": "z.py",
        },
    ]
    clusters = build_associative_clusters(records)
    parents = [c.get("parentSketch") or "" for c in clusters]
    assert "services/auth" in parents
    assert not any("Article Title_files" in p for p in parents)
    assert not any("rs=" in p for p in parents)
    assert not any("Accelerator" in (p or "") for p in parents)


def test_office_documents_excluded_from_domain_hints(tmp_path: Path) -> None:
    (tmp_path / "What makes the Healing Haven the Healing Haven.docx").write_bytes(b"x")
    (tmp_path / "CA Condensed Trainer Notes with cover_8-7-2024.pdf").write_bytes(b"%PDF")
    (tmp_path / "AI Communications Clone — Practical Demo Guide [AI Accelerator].txt").write_text(
        "x", encoding="utf-8"
    )
    good = tmp_path / "HealingHavenModule"
    good.mkdir()
    (good / "README.md").write_text("x", encoding="utf-8")

    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=5, max_nodes=800)
    joined = " ".join(snap.get("domainHints") or []).lower()
    assert "what makes" not in joined
    assert "condensed" not in joined
    assert ".docx" not in joined
    assert ".pdf" not in joined
    assert "practical demo" not in joined
    assert "accelerator" not in joined
    assert "healing" in joined or "haven" in joined or "module" in joined


def test_readme_txt_allowed_in_mirror_surfaces(tmp_path: Path) -> None:
    (tmp_path / "README.txt").write_text("x", encoding="utf-8")
    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=3, max_nodes=200)
    surfaces = (snap.get("rawIndex") or {}).get("surfaces") or []
    assert any(str(s.get("label") or "").lower() == "readme.txt" for s in surfaces)


def test_copy_of_prefix_folder_skips_hints(tmp_path: Path) -> None:
    d = tmp_path / "Copy of Test Press Release Oct 2025"
    d.mkdir()
    (d / "x.txt").write_text("x", encoding="utf-8")
    good = tmp_path / "CodeModule"
    good.mkdir()
    (good / "app.py").write_text("x", encoding="utf-8")
    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=5, max_nodes=400)
    joined = " ".join(snap.get("domainHints") or []).lower()
    assert "caylor" not in joined
    assert "press release" not in joined
    assert "codemodule" in joined or "module" in joined


def test_sentence_like_folder_names_skip_hint_counts(tmp_path: Path) -> None:
    long_dir = tmp_path / "How to achieve action mindset with daily practice"
    long_dir.mkdir()
    (long_dir / "note.txt").write_text("x", encoding="utf-8")
    good = tmp_path / "AcmeClinical"
    good.mkdir()
    (good / "app.py").write_text("x", encoding="utf-8")

    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=5, max_nodes=800)
    joined = " ".join(snap.get("domainHints") or []).lower()
    assert "achieve" not in joined
    assert "mindset" not in joined
    assert "acme" in joined or "clinical" in joined


def test_browser_cache_style_names_suppressed_in_hints(tmp_path: Path) -> None:
    (tmp_path / "www-main-desktop-watch-page-skeleton-webp-vflS1WbUQ.css").write_text("x", encoding="utf-8")
    (tmp_path / "font-awesome.min.css").write_text("x", encoding="utf-8")
    (tmp_path / "m=m,m_i,i20jfd,lKrWxc").write_text("x", encoding="utf-8")
    good = tmp_path / "AcmePatientPortal"
    good.mkdir()
    (good / "spec.md").write_text("x", encoding="utf-8")

    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=5, max_nodes=800)
    joined = " ".join(snap.get("domainHints") or []).lower()
    assert "www-main" not in joined
    assert "font-awesome" not in joined
    assert "vfls1wbuq" not in joined
    assert "m=m" not in joined
    assert "acme" in joined or "patient" in joined or "portal" in joined


def test_junk_artifacts_suppressed_in_hints(tmp_path: Path) -> None:
    (tmp_path / "hqdefault.jpg").write_bytes(b"x")
    (tmp_path / "unnamed (1).txt").write_text("x", encoding="utf-8")
    (tmp_path / "profile (2).pdf").write_bytes(b"%PDF")
    good = tmp_path / "HealingHavenModule"
    good.mkdir()
    (good / "notes.md").write_text("x", encoding="utf-8")

    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=5, max_nodes=800)
    joined = " ".join(snap.get("domainHints") or []).lower()
    assert "hqdefault" not in joined
    assert "unnamed" not in joined
    assert "profile" not in joined
    assert "healing" in joined or "haven" in joined or "module" in joined


def test_profile_folder_not_descended(tmp_path: Path) -> None:
    inner = tmp_path / "profile" / "SecretStuff"
    inner.mkdir(parents=True)
    (inner / "x.txt").write_text("x", encoding="utf-8")
    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=5, max_nodes=200)
    joined = " ".join(snap.get("domainHints") or []).lower()
    assert "secret" not in joined


def test_identity_quality_warning_when_only_artifacts(tmp_path: Path) -> None:
    for i in range(160):
        (tmp_path / f"img{i}.png").write_bytes(b"x")
    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=3, max_nodes=600)
    w = (snap.get("scanHealth") or {}).get("identityQualityWarning")
    assert w == IDENTITY_LOW_QUALITY_USER_MESSAGE


def test_scan_collects_basename_hints(tmp_path: Path) -> None:
    clinic = tmp_path / "Healing-Haven-Clinic"
    clinic.mkdir()
    onboarding = clinic / "Onboarding-Flow"
    onboarding.mkdir()
    (onboarding / "readme.txt").write_text("x", encoding="utf-8")

    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=6, max_nodes=2000)
    assert snap["schemaVersion"] == 2
    assert "buffers" in snap and "reasoning" in snap["buffers"]
    hints = snap["domainHints"]
    joined = " ".join(hints).lower()
    assert "healing" in joined or "clinic" in joined or "onboarding" in joined


def test_write_read_roundtrip(tmp_path: Path) -> None:
    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, scan_kind="deep_initial")
    snap["branchKey"] = "test-branch@abc1234"
    base = default_workspace_identity_dir(tmp_path)
    write_workspace_identity_snapshot(snap, base_dir=base)
    loaded = read_snapshot_file(base)
    assert loaded is not None
    assert loaded["branchKey"] == "test-branch@abc1234"
    meta_p = base / "meta.json"
    assert meta_p.is_file()
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    assert meta.get("snapshotHash")


def test_packet_subset_deterministic(tmp_path: Path) -> None:
    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path)
    phrases = ["Zebra Alpha", "Beta Program", "zebra beta"]
    snap["domainHints"] = phrases
    snap["buffers"]["surface_shallow"]["phrases"] = phrases
    p1 = build_workspace_packet_from_snapshot(snap)
    p2 = build_workspace_packet_from_snapshot(snap)
    assert p1 == p2
    assert p1 and "domainHints" in p1
    assert p1.get("schemaVersion") == 2
    assert p1.get("reasoningCapsule") is not None


def test_branch_mismatch_not_usable(tmp_path: Path) -> None:
    snap = {"schemaVersion": 1, "branchKey": "old@deadbeef", "domainHints": ["x"]}
    ok, reason = snapshot_usable_for_extract(snap, current_branch_key="new@cafebabe")
    assert ok is False
    assert reason == "branch_mismatch"


def test_branch_match_usable() -> None:
    snap = {"schemaVersion": 1, "branchKey": "main@abc", "domainHints": ["HelloWorld"]}
    ok, reason = snapshot_usable_for_extract(snap, current_branch_key="main@abc")
    assert ok is True
    assert reason == "ok"


def test_buffer_stack_validates_and_decision_surface_is_functional_plus_reasoning() -> None:
    from collections import Counter

    buf = build_all_buffers(path_records=[], hint_counts=Counter())
    assert validate_buffer_stack_present(buf) == []
    ds = decision_surface_from_buffers(buf)
    assert set(ds.keys()) == {"functional", "reasoning"}
    assert "surface_shallow" not in ds
    assert decision_surface_excludes_literal_buffer_layers(ds) == []


def test_behavioral_contracts_align_with_pipeline_keys() -> None:
    pipeline = {key for _, key in BUFFER_PIPELINE_KEYS}
    assert set(BUFFER_BEHAVIORAL_CONTRACTS.keys()) == pipeline
    for key, spec in BUFFER_BEHAVIORAL_CONTRACTS.items():
        assert 1 <= len(spec.allowed_output_examples) <= 5
        assert 1 <= len(spec.disallowed_output_examples) <= 5


def test_decision_surface_must_not_carry_buffer_zero_shape() -> None:
    polluted = {
        "functional": {"activityTags": ["onboarding"], "phrases": ["leak"]},
        "reasoning": {"themes": ["ok theme with enough words"], "namedPrograms": [], "tags": []},
    }
    issues = decision_surface_excludes_literal_buffer_layers(polluted)
    assert any("phrases" in issue for issue in issues)
    assert any("functional" in issue for issue in issues)


def test_validate_buffer_output_shape_flags_surface_interpretation() -> None:
    issues = validate_buffer_output_shape(
        "surface_shallow",
        {"phrases": ["Northwind Portal", "this is an onboarding flow"], "pathSketches": []},
    )
    assert any("interpretation_clause" in issue for issue in issues)


def test_validate_buffer_output_shape_flags_reasoning_raw_literal_theme() -> None:
    issues = validate_buffer_output_shape(
        "reasoning",
        {
            "themes": ["meditation"],
            "namedPrograms": [],
            "tags": [],
        },
    )
    assert any("raw literal" in issue.lower() for issue in issues)


def test_keep_packet_surface_literal_rejects_garbled_casing() -> None:
    c = Counter({"x": 1})
    assert keep_packet_surface_literal("Spirit Science", c)
    # Two-word *…healing* is filtered as course-style prose (mirror_prose_title), not casing.
    assert keep_packet_surface_literal("Sound Healing", c) is False
    assert keep_packet_surface_literal("Trauma relief", c) is True
    assert keep_packet_surface_literal("SOUND hElaing", c) is False
    assert keep_packet_surface_literal("FOcus group", c) is False
    assert keep_packet_surface_literal("Joe DIspenza", c) is False


def test_keep_path_sketch_literal_drops_course_trees_and_prose_children() -> None:
    assert keep_path_sketch_literal("clinical/intake-forms")
    assert keep_path_sketch_literal("courses/spirit")
    assert keep_path_sketch_literal("local_ai/workspace_identity")
    assert keep_path_sketch_literal("AI how to use/Elevan labs") is False
    assert keep_path_sketch_literal("A powerful day/How to achieve action mindset") is False
    assert keep_path_sketch_literal("A mastermind/AAA Landing page") is False
    assert keep_path_sketch_literal("docs/How to r4ecover reboot") is False
    assert keep_path_sketch_literal("training/Awareness faci;litator school") is False
    assert keep_path_sketch_literal("AI how to use/FOR JOSH") is False
    assert keep_path_sketch_literal("Book/Joe dispenza") is False
    assert keep_path_sketch_literal("Book/Peace walk") is False
    assert keep_path_sketch_literal("Stories/Signature talk") is False
    assert keep_path_sketch_literal("Jack Canfield/Passion Test") is False
    assert keep_path_sketch_literal("Jean Huston/New folder") is False
    assert keep_path_sketch_literal("Jean Huston/New folder (2)") is False
    assert keep_path_sketch_literal("Jean Huston/Week 1") is False
    assert keep_path_sketch_literal("Heart math/Teach Back") is False
    assert keep_path_sketch_literal("Sage Levine/Enrolment") is False
    assert keep_path_sketch_literal("Manifestationj/New folder") is False


def test_path_sketches_from_scan_drop_junk_roots(tmp_path: Path) -> None:
    (tmp_path / "clinical" / "notes").mkdir(parents=True)
    (tmp_path / "clinical" / "notes" / "a.md").write_text("x", encoding="utf-8")
    junk = tmp_path / "AI how to use" / "Elevan labs"
    junk.mkdir(parents=True)
    (junk / "x.md").write_text("x", encoding="utf-8")

    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path, max_depth=6, max_nodes=200)
    sketches = (snap.get("buffers") or {}).get("surface_shallow", {}).get("pathSketches") or []
    joined = "\n".join(sketches).lower()
    assert "clinical" in joined
    assert "ai how" not in joined


def test_packet_prefers_reasoning_literals_over_surface(tmp_path: Path) -> None:
    snap = build_workspace_identity_snapshot([str(tmp_path)], repo_root=tmp_path)
    snap["buffers"]["reasoning"] = {
        "themes": ["theme a"],
        "namedPrograms": ["workspace-identity", "onboarding"],
        "tags": ["extraction", "signals"],
    }
    snap["buffers"]["surface_shallow"]["phrases"] = [
        "Zebra Filename Alpha",
        "Beta Filename Gamma",
        "Zeta Filename Delta",
    ]
    snap["buffers"]["surface_shallow"]["pathSketches"] = ["courses/spirit"]
    p = build_workspace_packet_from_snapshot(snap)
    assert p is not None
    hints = p["domainHints"]
    assert hints[0] in ("workspace-identity", "onboarding", "extraction", "signals")
    assert "courses/spirit" in hints
    assert hints.index("courses/spirit") < hints.index("Zebra Filename Alpha")


def test_surface_shallow_filter_drops_noise() -> None:
    c = Counter({"copy": 20, "page": 15})
    assert keep_surface_shallow_phrase("copy", c) is False
    assert keep_surface_shallow_phrase("page", c) is False
    assert keep_surface_shallow_phrase("desktop", c) is False
    assert keep_surface_shallow_phrase("you", c) is False
    assert keep_surface_shallow_phrase("Onboarding-Flow", Counter())
    assert keep_surface_shallow_phrase("VisionExecution", Counter())
    assert keep_surface_shallow_phrase("local_ai", Counter())
    assert keep_surface_shallow_phrase("www-main-desktop-home-page-skeleton", Counter()) is False
    assert keep_surface_shallow_phrase("meetings", Counter()) is False
    assert keep_surface_shallow_phrase("Meeting notes.docx", Counter()) is False
    assert keep_surface_shallow_phrase("Story export Oct 2025.txt", Counter()) is False


def test_v1_snapshot_migrates_to_v2_packet() -> None:
    v1 = {
        "schemaVersion": 1,
        "branchKey": "x@y",
        "domainHints": ["Healing Haven", "onboarding-flow"],
        "surfaces": [{"label": "docs", "pathRelative": "docs", "kind": "folder"}],
        "fingerprints": [],
    }
    p = build_workspace_packet_from_snapshot(v1)
    assert p is not None
    assert p.get("schemaVersion") == 2
    assert any("healing" in (x or "").lower() for x in (p.get("literalAnchors") or []))
    assert isinstance(p.get("reasoningCapsule"), dict)
    assert SCHEMA_VERSION == 2
