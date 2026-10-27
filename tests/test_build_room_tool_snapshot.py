"""Tool-access stage-1 increment A tests: snapshot + manifest + bake-in.

Pure-function tests over temp directories plus CLI tests through
main(). No live API calls, no real key values, no staging access.
Deployed-tree layout (what the Fly image actually carries) cannot be
confirmed from the repo alone and is NOT asserted here — it is a
staging-confirmation item in the PR report.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from local_ai.build_room import tool_snapshot
from local_ai.build_room.tool_snapshot import (
    ManifestError,
    SnapshotBuildError,
    build_snapshot,
    collect_allowlist,
    deployed_code_version,
    is_denylisted,
    load_manifest,
    scan_snapshot,
    snapshot_status,
    verify_snapshot,
)

COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40


@pytest.fixture()
def source_dir(tmp_path: Path) -> Path:
    src = tmp_path / "local_ai"
    (src / "build_room").mkdir(parents=True)
    (src / "build_room" / "meeting.py").write_text("x = 1\n", encoding="utf-8")
    (src / "build_room" / "notes.md").write_text("# notes\n", encoding="utf-8")
    (src / "llm").mkdir()
    (src / "llm" / "provider.py").write_text("y = 2\n", encoding="utf-8")
    (src / "data.json").write_text('{"k": 1}\n', encoding="utf-8")
    return src


def _build(source_dir: Path, tmp_path: Path, commit: str = COMMIT) -> Path:
    dest = tmp_path / "tool_snapshot"
    build_snapshot(source_dir, dest, commit)
    return dest


def test_build_happy_path_manifest_and_digests(source_dir, tmp_path):
    dest = _build(source_dir, tmp_path)
    manifest = load_manifest(dest)
    assert manifest["version"] == 1
    assert manifest["commit"] == COMMIT
    assert manifest["source"] == "local_ai"
    assert manifest["built_at"]
    assert manifest["allowlist"] == sorted(manifest["allowlist"])
    assert manifest["allowlist"] == [
        "build_room/meeting.py",
        "build_room/notes.md",
        "data.json",
        "llm/provider.py",
    ]
    for rel, digest in manifest["files"].items():
        copied = dest / rel
        assert copied.is_file()
        assert copied.read_bytes() == (source_dir / rel).read_bytes()
        assert digest == hashlib.sha256(copied.read_bytes()).hexdigest()
    # Digests are of the COPIED bytes: tamper source after build and
    # the manifest must still match the snapshot, not the source.
    (source_dir / "data.json").write_text('{"k": 999}\n', encoding="utf-8")
    assert verify_snapshot(dest, COMMIT).ok


def test_build_excludes_denylisted_and_cache(source_dir, tmp_path):
    (source_dir / ".env").write_text("KEY=1\n", encoding="utf-8")
    (source_dir / ".env.local").write_text("KEY=1\n", encoding="utf-8")
    (source_dir / "my_secret_notes.txt").write_text("s\n", encoding="utf-8")
    (source_dir / "id_credential.pem").write_text("p\n", encoding="utf-8")
    (source_dir / "key.key").write_text("k\n", encoding="utf-8")
    (source_dir / "debug.log").write_text("l\n", encoding="utf-8")
    (source_dir / "usage.jsonl").write_text("{}\n", encoding="utf-8")
    cache = source_dir / "build_room" / "__pycache__"
    cache.mkdir()
    (cache / "meeting.pyc").write_bytes(b"\x00")
    # Key-handling code stays in (see test_is_denylisted_cases).
    (source_dir / "llm" / "credentials.py").write_text(
        "import os\nKEY = os.environ.get('X')\n", encoding="utf-8")
    dest = _build(source_dir, tmp_path)
    manifest = load_manifest(dest)
    assert manifest["allowlist"] == [
        "build_room/meeting.py",
        "build_room/notes.md",
        "data.json",
        "llm/credentials.py",
        "llm/provider.py",
    ]
    assert not (dest / ".env").exists()
    assert scan_snapshot(dest) == []


def test_is_denylisted_cases():
    assert is_denylisted(".env")
    assert is_denylisted("a/.env.local")
    assert is_denylisted("SECRET_keys.txt")
    assert is_denylisted("a/b/credentials.json")
    assert is_denylisted("secrets.yaml")
    assert is_denylisted("x.pem")
    assert is_denylisted("x.key")
    assert is_denylisted("x.log")
    assert is_denylisted("usage.jsonl")
    assert not is_denylisted("build_room/artifact.py")
    assert not is_denylisted("data.json")
    assert not is_denylisted("brand-profile.json")
    # Key-handling CODE is not key material: a credentials.py module
    # resolves key names from env/settings and carries no values.
    # Excluding it would blind verification to security-sensitive code.
    assert not is_denylisted("llm/credentials.py")
    assert not is_denylisted("execution_policy/openai_credentials.py")
    assert not is_denylisted("secret_store.py")


def test_escaping_symlink_fails_build(source_dir, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    os.symlink(outside, source_dir / "escape.py")
    with pytest.raises(SnapshotBuildError, match="escapes source tree"):
        build_snapshot(source_dir, tmp_path / "tool_snapshot", COMMIT)
    # A failed build never ships a half snapshot.
    assert not (tmp_path / "tool_snapshot").exists()


def test_internal_symlink_materialized(source_dir, tmp_path):
    target = source_dir / "llm" / "provider.py"
    os.symlink(target, source_dir / "llm" / "alias.py")
    dest = _build(source_dir, tmp_path)
    copied = dest / "llm" / "alias.py"
    assert copied.is_file() and not copied.is_symlink()
    assert copied.read_bytes() == target.read_bytes()
    manifest = load_manifest(dest)
    assert manifest["files"]["llm/alias.py"] == hashlib.sha256(
        target.read_bytes()
    ).hexdigest()


def test_build_requires_commit_and_empty_dest(source_dir, tmp_path):
    with pytest.raises(SnapshotBuildError, match="without a commit"):
        build_snapshot(source_dir, tmp_path / "tool_snapshot", "")
    dest = tmp_path / "tool_snapshot"
    dest.mkdir()
    (dest / "stale.txt").write_text("stale\n", encoding="utf-8")
    with pytest.raises(SnapshotBuildError, match="not empty"):
        build_snapshot(source_dir, dest, COMMIT)


def test_verify_ok_and_bake_in_absent(source_dir, tmp_path):
    dest = _build(source_dir, tmp_path)
    result = verify_snapshot(dest, COMMIT)
    assert result.ok and result.reason is None
    assert result.details["files"] == 4
    assert not verify_snapshot(dest, None).ok
    assert verify_snapshot(dest, None).reason == "bake-in-absent"
    assert verify_snapshot(dest, "").reason == "bake-in-absent"


def test_verify_commit_mismatch(source_dir, tmp_path):
    dest = _build(source_dir, tmp_path)
    result = verify_snapshot(dest, OTHER_COMMIT)
    assert not result.ok and result.reason == "commit-mismatch"
    assert result.details["manifest_commit"] == COMMIT


def test_verify_digest_mismatch_missing_unexpected(source_dir, tmp_path):
    dest = _build(source_dir, tmp_path)
    (dest / "data.json").write_text('{"k": 2}\n', encoding="utf-8")
    assert verify_snapshot(dest, COMMIT).reason == "digest-mismatch"
    (dest / "data.json").write_text('{"k": 1}\n', encoding="utf-8")
    assert verify_snapshot(dest, COMMIT).ok
    (dest / "llm" / "provider.py").unlink()
    assert verify_snapshot(dest, COMMIT).reason == "file-missing"
    (dest / "llm" / "provider.py").write_text("y = 2\n", encoding="utf-8")
    (dest / "extra.txt").write_text("x\n", encoding="utf-8")
    assert verify_snapshot(dest, COMMIT).reason == "unexpected-file"


def test_verify_missing_and_malformed_manifest(tmp_path):
    dest = tmp_path / "tool_snapshot"
    dest.mkdir()
    # Missing manifest inside an existing dir:
    result = verify_snapshot(dest, COMMIT)
    assert not result.ok and result.reason == "manifest-unusable"
    # Missing snapshot dir entirely:
    result = verify_snapshot(tmp_path / "nope", COMMIT)
    assert not result.ok and result.reason == "snapshot-missing"
    (dest / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(dest)
    assert verify_snapshot(dest, COMMIT).reason == "manifest-unusable"


def test_scan_flags_denylisted_and_unlisted(source_dir, tmp_path):
    dest = _build(source_dir, tmp_path)
    (dest / ".env").write_text("K=1\n", encoding="utf-8")
    (dest / "rogue.txt").write_text("r\n", encoding="utf-8")
    violations = scan_snapshot(dest)
    assert any("denylisted" in v for v in violations)
    assert any("unlisted" in v for v in violations)


def test_snapshot_status_hook(source_dir, tmp_path, monkeypatch):
    dest = _build(source_dir, tmp_path)
    monkeypatch.setenv("ZENAF_CODE_VERSION", COMMIT)
    enabled, reason, _ = snapshot_status(dest)
    assert enabled and reason is None
    monkeypatch.delenv("ZENAF_CODE_VERSION")
    enabled, reason, _ = snapshot_status(dest)
    assert not enabled and reason == "bake-in-absent"


def test_deployed_code_version_env(monkeypatch):
    monkeypatch.setenv("ZENAF_CODE_VERSION", "  abc123  ")
    assert deployed_code_version() == "abc123"
    monkeypatch.setenv("ZENAF_CODE_VERSION", "   ")
    assert deployed_code_version() is None
    monkeypatch.delenv("ZENAF_CODE_VERSION", raising=False)
    assert deployed_code_version() is None


def test_cli_build_check_scan(source_dir, tmp_path, capsys):
    dest = tmp_path / "tool_snapshot"
    assert tool_snapshot.main([
        "build", "--source", str(source_dir), "--dest", str(dest),
        "--commit", COMMIT,
    ]) == 0
    assert tool_snapshot.main([
        "check", "--snapshot-dir", str(dest), "--expected-commit", COMMIT,
    ]) == 0
    assert tool_snapshot.main(["scan", "--snapshot-dir", str(dest)]) == 0
    assert tool_snapshot.main([
        "check", "--snapshot-dir", str(dest), "--expected-commit", OTHER_COMMIT,
    ]) == 1


def test_cli_build_rejects_empty_commit(source_dir, tmp_path):
    assert tool_snapshot.main([
        "build", "--source", str(source_dir),
        "--dest", str(tmp_path / "tool_snapshot"), "--commit", "",
    ]) == 1


def _init_git_repo(path: Path) -> str:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "f.py").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-qm", "init"], check=True)
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()


def test_cli_verify_git_matches_and_mismatches(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    head = _init_git_repo(repo)
    dest = tmp_path / "tool_snapshot"
    assert tool_snapshot.main([
        "build", "--source", str(repo), "--dest", str(dest),
        "--commit", head, "--verify-git",
    ]) == 0
    dest2 = tmp_path / "tool_snapshot2"
    assert tool_snapshot.main([
        "build", "--source", str(repo), "--dest", str(dest2),
        "--commit", "0" * 40, "--verify-git",
    ]) == 1


def test_module_entry_point_runs(tmp_path):
    """The exact `python -m` invocation the Dockerfile uses."""
    src = tmp_path / "local_ai"
    src.mkdir()
    (src / "a.py").write_text("a\n", encoding="utf-8")
    dest = tmp_path / "tool_snapshot"
    proc = subprocess.run(
        [sys.executable, "-m", "local_ai.build_room.tool_snapshot",
         "build", "--source", str(src), "--dest", str(dest),
         "--commit", COMMIT],
        capture_output=True, text=True, cwd=str(Path.cwd()),
    )
    assert proc.returncode == 0, proc.stderr
    assert (dest / "manifest.json").is_file()
