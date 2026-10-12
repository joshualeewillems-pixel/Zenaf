"""Soil kernel: ensure node, append item, promotion record, CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.soil import (
    append_soil_item,
    ensure_node,
    read_manifest,
    resolve_soil_root,
    write_promotion_record,
)
from local_ai.soil.discover import find_soil_md_by_id


def test_resolve_soil_root_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZENAF_SOIL_ROOT", str(tmp_path))
    assert resolve_soil_root() == tmp_path.resolve()


def test_ensure_node_creates_tree(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZENAF_SOIL_ROOT", str(tmp_path))
    nd = ensure_node(tmp_path, "initiative", "abc-123", title="Test")
    assert (nd / "node.json").is_file()
    assert (nd / "canonical").is_dir()
    assert (nd / "soil" / "tensions").is_dir()
    assert (nd / "soil" / "promoted").is_dir()
    m = read_manifest(nd)
    assert m["node_id"] == "initiative:abc-123"
    assert m["node_type"] == "initiative"


def test_append_soil_item(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZENAF_SOIL_ROOT", str(tmp_path))
    path, sid = append_soil_item(
        "task",
        "t1",
        soil_type="tension",
        body="Scope keeps shifting.\n",
        capture_source="user_action",
        root=tmp_path,
        title="My task",
    )
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert sid in text
    assert "capture_source: \"user_action\"" in text or 'capture_source: "user_action"' in text
    assert "Scope keeps shifting." in text


def test_named_system_capture_requires_allowlisted_name(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZENAF_SOIL_ROOT", str(tmp_path))
    try:
        append_soil_item(
            "task",
            "t1",
            soil_type="hypothesis",
            body="x",
            capture_source="named_system_capture",
            capture_name="not_on_allowlist",
            root=tmp_path,
        )
    except ValueError as e:
        assert "allowlist" in str(e).lower() or "capture_name" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")


def test_named_system_capture_allowlisted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZENAF_SOIL_ROOT", str(tmp_path))
    path, sid = append_soil_item(
        "task",
        "t1",
        soil_type="hypothesis",
        body="from export",
        capture_source="named_system_capture",
        capture_name="dev_soil_export",
        root=tmp_path,
    )
    assert sid in path.read_text(encoding="utf-8")


def test_soil_markdown_basename_fallback_for_empty_slug(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZENAF_SOIL_ROOT", str(tmp_path))
    path, sid = append_soil_item(
        "task",
        "t1",
        soil_type="tension",
        body="x",
        capture_source="user_action",
        root=tmp_path,
        soil_id="!!!",
    )
    assert path.suffix == ".md"
    assert path.name.startswith("soil_")
    assert sid == "!!!"


def test_find_soil_md_by_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZENAF_SOIL_ROOT", str(tmp_path))
    path, sid = append_soil_item(
        "initiative",
        "i1",
        soil_type="tension",
        body="x",
        capture_source="user_action",
        root=tmp_path,
        soil_id="soil_test_fixed_id",
    )
    rel = path.relative_to(tmp_path).as_posix()
    p2, rel2, nid = find_soil_md_by_id(tmp_path, "soil_test_fixed_id")
    assert p2 == path.resolve()
    assert rel2 == rel
    assert nid == "initiative:i1"


def test_write_promotion_record(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZENAF_SOIL_ROOT", str(tmp_path))
    soil_path, sid = append_soil_item(
        "project",
        "p9",
        soil_type="excerpt",
        body="note",
        capture_source="manual_import",
        root=tmp_path,
    )
    rel = soil_path.relative_to(tmp_path).as_posix()
    nd = ensure_node(tmp_path, "project", "p9")
    m = read_manifest(nd)
    promo = write_promotion_record(
        tmp_path,
        "project",
        "p9",
        from_soil_id=sid,
        from_path_rel=rel,
        from_node_id=m["node_id"],
        to_canonical_ref={"kind": "unspecified", "note": "test"},
        reason="manual test",
        accepted_by="pytest",
        supporting_soil_ids=[sid],
    )
    data = json.loads(promo.read_text(encoding="utf-8"))
    assert data["from_soil_id"] == sid
    assert data["from_path"] == rel
    assert data["accepted_by"] == "pytest"


def test_cli_append_and_promote(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZENAF_SOIL_ROOT", str(tmp_path))
    note = tmp_path / "note.md"
    note.write_text("Scope approval unclear.\n", encoding="utf-8")
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "local_ai.soil.cli",
            "append",
            "--root",
            str(tmp_path),
            "--entity-type",
            "task",
            "--entity-id",
            "123",
            "--soil-type",
            "tension",
            "--capture-source",
            "user_action",
            "--title",
            "Scope approval ambiguity",
            "--body-file",
            str(note),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    lines = [x for x in r.stdout.strip().splitlines() if x.strip()]
    soil_id = lines[0]

    r2 = subprocess.run(
        [
            sys.executable,
            "-m",
            "local_ai.soil.cli",
            "promote",
            "--root",
            str(tmp_path),
            "--entity-type",
            "task",
            "--entity-id",
            "123",
            "--from-soil-id",
            soil_id,
            "--to-node-id",
            "project:abc",
            "--reason",
            "Repeated across 3 related tasks",
            "--accepted-by",
            "pytest_cli",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r2.returncode == 0, r2.stderr
    rel = r2.stdout.strip().splitlines()[-1]
    promo_path = tmp_path.joinpath(*rel.split("/"))
    assert promo_path.suffix == ".json"
    data = json.loads(promo_path.read_text(encoding="utf-8"))
    assert data["from_soil_id"] == soil_id
    assert data["to_node_id"] == "project:abc"
    assert data["reason"] == "Repeated across 3 related tasks"
