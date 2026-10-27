"""Tool-access snapshot + manifest + runtime verification (stage-1 increment A).

Builds the read-only source snapshot the council's future `read_file`
tool will read from, and provides the fail-closed runtime check that
increment B's tool loop will call before the first tool invocation in
a meeting.

Design references (all under ~/workspace/your_files/):
- tool-access stage-1 plan, Increment A (governing spec).
- tool-access stage-1 correction §3 (fail-closed: deployment vs runtime
  distinction; manifest + bake-in are prerequisites, not options) and
  §7 (allowlist construction; per-file SHA-256 digests).
- tool-access design §3.4 (revision identity) and §5.2 (snapshot
  construction).

Deliberately dependency-free (stdlib only) and independent of the
meeting runner: no tool code exists yet, so nothing imports this
module at runtime today. Increment B wires `snapshot_status()` into
the runner as the fail-closed hook.

Key properties, each enforced here rather than promised in prose:

- ALLOWLIST construction: the build copies ONLY listed paths (the
  manifest's path list) into the snapshot directory. What is not
  listed is not copied. The denylist is a backstop at build/scan
  time, not the construction method.
- Revision identity vs content integrity are DISTINCT: the manifest
  commit SHA names the revision the snapshot claims to represent;
  the per-file SHA-256 digests prove the bytes are the ones the
  trusted build recorded. A correct SHA does not rescue copied
  modified files, which is why the build digests the COPIED bytes
  (not the source bytes) and why digest verification runs before
  any file is returned as evidence.
- Symlinks: a symlink resolving OUTSIDE the source tree FAILS the
  build (never dereferenced). A symlink resolving INSIDE the tree
  is materialized as a regular file with the target's content, so
  the snapshot contains regular files only — there is no symlink
  left to escape at read time.
- Secrets by construction: the snapshot source is `local_ai/` only,
  and denylisted names (env files, key material, logs, operational
  outputs, and non-code secret/credential files) are excluded from
  the allowlist. Code that handles keys (e.g. `credentials.py`
  modules) is NOT key material and stays in — see the denylist
  comment at the top of this module. The CI scan re-sweeps the
  built snapshot and fails the build on any violation.
- Fail closed: `snapshot_status()` returns enabled=False with a
  reason whenever the manifest is absent, malformed, commit-
  mismatched, digest-mismatched, or the bake-in is absent. There
  is no execution path for unverified revision: no tool results
  exist without a verified snapshot. `revision: "unavailable"`
  does not exist as a value that accompanies tool results.
- Bake-in: `ZENAF_CODE_VERSION` is the deployed commit, set at
  image build time (Docker ARG -> ENV; the Fly deploy workflow
  passes the checkout SHA). It is the independent cross-check
  against the manifest commit. An empty or absent bake-in disables
  tools, it never falls back to trusting the manifest alone.

Snapshot layout (inside the image, next to the app tree):

    <repo root>/tool_snapshot/
        manifest.json
        <allowlisted files, same relative layout as local_ai/>

Manifest schema (version 1):

    {
      "version": 1,
      "commit": "<full commit SHA>",
      "built_at": "<UTC ISO-8601 timestamp>",
      "source": "local_ai",
      "allowlist": ["<posix rel path>", ...],   # sorted
      "files": {"<posix rel path>": "<sha256 hex>", ...},
      "provenance": {"builder": "tool_snapshot", "build_context": ...},
    }

CLI (used by the Dockerfile build step and by CI):

    python -m local_ai.build_room.tool_snapshot build \
        --source ./local_ai --dest ./tool_snapshot --commit <sha>
    python -m local_ai.build_room.tool_snapshot scan \
        --snapshot-dir ./tool_snapshot
    python -m local_ai.build_room.tool_snapshot check \
        --snapshot-dir ./tool_snapshot [--expected-commit <sha>]
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_FILENAME = "manifest.json"
MANIFEST_VERSION = 1

# Patterns excluded from the snapshot by construction, matched
# case-insensitively against both the basename and the full relative
# posix path. Two tiers, because the naive rule is wrong in an
# instructive way:
# - ALWAYS patterns (.env files, key material, logs, usage outputs)
#   are excluded whatever they are called.
# - VALUE patterns (*secret*, *credential*) apply ONLY to files
#   that are not source code or docs. Code that HANDLES keys is not
#   key material: llm/credentials.py and
#   execution_policy/openai_credentials.py resolve key NAMES from
#   env/settings and carry no values, and excluding them would blind
#   the council to exactly the security-sensitive code it most needs
#   to verify. Values live in env vars and Fly secrets, never in the
#   repo checkout, so a *credentials.py* file in the tree is code by
#   construction. A *credentials.json* or *secrets.yaml* data file,
#   by contrast, could carry values and stays excluded.
# Kept narrow on purpose elsewhere too: broad patterns such as
# "*artifact*" or "*.json" would wrongly exclude legitimate source
# (artifact.py, brand-profile JSON). Runtime operational outputs
# (usage logs, meeting transcripts/artifacts) live in store_dir and
# data/, never in the local_ai/ source tree, so they cannot enter
# the snapshot through the allowlist walk in the first place.
ALWAYS_DENYLIST_PATTERNS = (
    ".env*",
    "*.pem",
    "*.key",
    "*.log",
    "usage.jsonl",
    "usage.json",
)
VALUE_DENYLIST_PATTERNS = (
    "*secret*",
    "*credential*",
)
# Suffixes whose files are code or prose documentation, never value
# stores, for the VALUE patterns above.
SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".md",
        ".rst",
        ".sql",
        ".html",
        ".htm",
        ".css",
    }
)

# Directory names never descended into, and file suffixes never copied.
SKIP_DIR_NAMES = ("__pycache__", ".git")
SKIP_SUFFIXES = (".pyc", ".pyo")
SKIP_NAMES = (".DS_Store",)


class SnapshotBuildError(Exception):
    """The snapshot cannot be built truthfully. Fail the build."""


class ManifestError(Exception):
    """The manifest is absent, malformed, or unusable."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_denylisted(rel_posix: str) -> bool:
    """True if a snapshot-relative path must never be copied.

    ALWAYS patterns match any file. VALUE patterns (*secret*,
    *credential*) match only non-code files: a `credentials.py`
    module is key-handling code, not key material, and stays in.
    """
    lowered = rel_posix.lower()
    basename = lowered.rsplit("/", 1)[-1]
    if basename in SKIP_NAMES or basename.endswith(SKIP_SUFFIXES):
        return True
    for pattern in ALWAYS_DENYLIST_PATTERNS:
        if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(lowered, pattern):
            return True
    suffix = basename.rsplit(".", 1)[-1] if "." in basename else ""
    if f".{suffix}" not in SOURCE_SUFFIXES:
        for pattern in VALUE_DENYLIST_PATTERNS:
            if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(lowered, pattern):
                return True
    return False


def _resolve_within_tree(path: Path, tree: Path) -> Path:
    """Resolve symlinks; fail if the result escapes the tree.

    Returns the resolved path (which may equal the input for a
    regular file). Raises SnapshotBuildError on escape.
    """
    resolved = path.resolve()
    try:
        resolved.relative_to(tree)
    except ValueError:
        raise SnapshotBuildError(
            f"symlink escapes source tree: {path} -> {resolved}"
        ) from None
    return resolved


def collect_allowlist(source_dir: Path) -> list[str]:
    """Walk the source tree and return the sorted allowlist.

    Regular files only, denylisted names excluded, __pycache__ and
    .git never descended into. Symlinks resolving outside the tree
    raise SnapshotBuildError; symlinks resolving inside are included
    (their content is materialized at copy time).
    """
    source = source_dir.resolve()
    if not source.is_dir():
        raise SnapshotBuildError(f"source directory missing: {source_dir}")
    allowlist: list[str] = []
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIR_NAMES)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = full.relative_to(source).as_posix()
            if is_denylisted(rel):
                continue
            if full.is_symlink():
                # Fail on escape; inside links are included and
                # materialized as regular files by build_snapshot.
                _resolve_within_tree(full, source)
            elif not full.is_file():
                continue
            allowlist.append(rel)
    return sorted(allowlist)


def build_snapshot(
    source_dir: Path,
    dest_dir: Path,
    commit: str,
    builder: str = "tool_snapshot",
    build_context: str | None = None,
    timestamp: str | None = None,
) -> dict:
    """Build the snapshot directory and its manifest.

    Copies exactly the allowlist from source_dir into dest_dir,
    digests the COPIED bytes, writes manifest.json, then scans the
    result. Any failure raises SnapshotBuildError and removes the
    partial destination, so a failed build never ships a half
    snapshot. dest_dir must not exist or must be empty.
    """
    commit = (commit or "").strip()
    if not commit:
        raise SnapshotBuildError(
            "cannot build a snapshot without a commit SHA: "
            "pass --commit (the Dockerfile passes ZENAF_CODE_VERSION; "
            "without it no snapshot ships and tools stay disabled)"
        )
    source = Path(source_dir)
    dest = Path(dest_dir)
    if dest.exists() and any(dest.iterdir()):
        raise SnapshotBuildError(f"destination not empty: {dest}")
    allowlist = collect_allowlist(source)
    source_resolved = source.resolve()
    try:
        dest.mkdir(parents=True, exist_ok=True)
        digests: dict[str, str] = {}
        for rel in allowlist:
            src = source_resolved / rel
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            # Materialize symlinks: copy the resolved content, never
            # the link itself, so the snapshot holds regular files only.
            shutil.copyfile(_resolve_within_tree(src, source_resolved), target)
            digests[rel] = sha256_file(target)
        manifest = {
            "version": MANIFEST_VERSION,
            "commit": commit,
            "built_at": timestamp
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "local_ai",
            "allowlist": allowlist,
            "files": digests,
            "provenance": {
                "builder": builder,
                "build_context": build_context or str(source_resolved),
            },
        }
        (dest / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        violations = scan_snapshot(dest)
        if violations:
            raise SnapshotBuildError(
                "snapshot failed its own CI scan: " + "; ".join(violations)
            )
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return manifest


def load_manifest(snapshot_dir: Path) -> dict:
    """Load and structurally validate manifest.json."""
    manifest_path = Path(snapshot_dir) / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ManifestError(f"manifest missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManifestError(f"manifest malformed: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestError("manifest is not a JSON object")
    for key in ("version", "commit", "allowlist", "files"):
        if key not in manifest:
            raise ManifestError(f"manifest missing required key: {key}")
    if manifest["version"] != MANIFEST_VERSION:
        raise ManifestError(
            f"unsupported manifest version: {manifest['version']!r}"
        )
    if not isinstance(manifest["allowlist"], list) or not isinstance(
        manifest["files"], dict
    ):
        raise ManifestError("manifest allowlist/files have wrong types")
    if sorted(manifest["allowlist"]) != sorted(manifest["files"].keys()):
        raise ManifestError("manifest allowlist and files disagree")
    return manifest


def scan_snapshot(snapshot_dir: Path) -> list[str]:
    """CI scan over a built snapshot directory.

    Returns violation strings (empty means clean). Checks: manifest
    present, no denylisted names, and no files present that the
    manifest does not list (except manifest.json itself).
    """
    violations: list[str] = []
    root = Path(snapshot_dir)
    if not root.is_dir():
        return [f"snapshot directory missing: {snapshot_dir}"]
    try:
        manifest = load_manifest(root)
    except ManifestError as exc:
        return [str(exc)]
    allowed = set(manifest["allowlist"]) | {MANIFEST_FILENAME}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(dirnames)
        for name in sorted(filenames):
            rel = (Path(dirpath) / name).relative_to(root).as_posix()
            if is_denylisted(rel):
                violations.append(f"denylisted file in snapshot: {rel}")
            elif rel not in allowed:
                violations.append(f"unlisted file in snapshot: {rel}")
    return violations


@dataclass
class VerifyResult:
    ok: bool
    reason: str | None = None
    details: dict = field(default_factory=dict)


def verify_snapshot(
    snapshot_dir: Path, deployed_version: str | None
) -> VerifyResult:
    """Verify a snapshot before any file is returned as evidence.

    Order is deliberate: presence, parseability, bake-in cross-check,
    then content integrity (every allowlisted file present with a
    matching digest), then no unexpected files. The first failure
    wins; the reason names it. A failure here disables tools for the
    whole meeting (increment B), it is never a per-call retry.
    """
    root = Path(snapshot_dir)
    if not root.is_dir():
        return VerifyResult(False, "snapshot-missing", {"snapshot_dir": str(root)})
    try:
        manifest = load_manifest(root)
    except ManifestError as exc:
        return VerifyResult(False, "manifest-unusable", {"error": str(exc)})
    deployed = (deployed_version or "").strip()
    if not deployed:
        return VerifyResult(
            False,
            "bake-in-absent",
            {"detail": "ZENAF_CODE_VERSION is unset; cannot cross-check manifest"},
        )
    if manifest["commit"] != deployed:
        return VerifyResult(
            False,
            "commit-mismatch",
            {"manifest_commit": manifest["commit"], "deployed": deployed},
        )
    for rel in manifest["allowlist"]:
        target = root / rel
        if not target.is_file():
            return VerifyResult(False, "file-missing", {"path": rel})
        if sha256_file(target) != manifest["files"][rel]:
            return VerifyResult(False, "digest-mismatch", {"path": rel})
    allowed = set(manifest["allowlist"]) | {MANIFEST_FILENAME}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            rel = (Path(dirpath) / name).relative_to(root).as_posix()
            if rel not in allowed:
                return VerifyResult(False, "unexpected-file", {"path": rel})
    return VerifyResult(
        True,
        None,
        {"commit": manifest["commit"], "files": len(manifest["allowlist"])},
    )


def deployed_code_version() -> str | None:
    """The baked-in deployed commit, or None when absent.

    Reads ZENAF_CODE_VERSION, set at image build time from the build
    argument the deploy workflow passes. An empty value counts as
    absent: an empty bake-in must never read as a version.
    """
    value = (os.environ.get("ZENAF_CODE_VERSION") or "").strip()
    return value or None


def default_snapshot_dir() -> Path:
    """<repo root>/tool_snapshot — /app/tool_snapshot in the image."""
    return Path(__file__).resolve().parent.parent.parent / "tool_snapshot"


def snapshot_status(
    snapshot_dir: Path | None = None,
    deployed_version: str | None = None,
) -> tuple[bool, str | None, dict]:
    """Fail-closed hook for increment B's tool loop.

    Returns (enabled, reason, details). enabled is True ONLY when
    the snapshot verifies against the baked-in deployed commit.
    Callers pass deployed_version explicitly in tests; at runtime it
    defaults to the ZENAF_CODE_VERSION environment value.
    """
    if deployed_version is None:
        deployed_version = deployed_code_version()
    result = verify_snapshot(
        Path(snapshot_dir) if snapshot_dir is not None else default_snapshot_dir(),
        deployed_version,
    )
    return result.ok, result.reason, result.details


def _git_head(source_dir: Path) -> str:
    """HEAD commit of the repo containing source_dir (CI verification)."""
    proc = subprocess.run(
        ["git", "-C", str(source_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SnapshotBuildError(f"git rev-parse failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tool_snapshot",
        description="Build, scan, and verify the tool-access source snapshot.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Build a snapshot directory + manifest.")
    build.add_argument("--source", required=True)
    build.add_argument("--dest", required=True)
    build.add_argument("--commit", required=True, help="Intended checkout SHA.")
    build.add_argument("--builder", default="tool_snapshot")
    build.add_argument("--build-context", default=None)
    build.add_argument(
        "--verify-git",
        action="store_true",
        help="Require git HEAD of the source repo to equal --commit.",
    )

    scan = sub.add_parser("scan", help="CI scan a built snapshot directory.")
    scan.add_argument("--snapshot-dir", required=True)

    check = sub.add_parser("check", help="Verify a snapshot (fail-closed).")
    check.add_argument("--snapshot-dir", required=True)
    check.add_argument(
        "--expected-commit",
        default=None,
        help="Defaults to ZENAF_CODE_VERSION.",
    )

    version = sub.add_parser("version", help="Print the baked-in deployed commit.")
    version.add_argument("--snapshot-dir", default=None)

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            if args.verify_git:
                head = _git_head(Path(args.source))
                if head != args.commit.strip():
                    print(
                        f"error: source checkout {head} != intended commit "
                        f"{args.commit.strip()}",
                        file=sys.stderr,
                    )
                    return 1
            manifest = build_snapshot(
                Path(args.source),
                Path(args.dest),
                args.commit,
                builder=args.builder,
                build_context=args.build_context,
            )
            print(
                f"snapshot built: {len(manifest['allowlist'])} files, "
                f"commit {manifest['commit']}"
            )
            return 0
        if args.command == "scan":
            violations = scan_snapshot(Path(args.snapshot_dir))
            if violations:
                print("scan FAILED:", file=sys.stderr)
                for violation in violations:
                    print(f"  - {violation}", file=sys.stderr)
                return 1
            print("scan clean")
            return 0
        if args.command == "check":
            expected = args.expected_commit
            if expected is None:
                expected = deployed_code_version()
            result = verify_snapshot(Path(args.snapshot_dir), expected)
            if result.ok:
                print(
                    f"snapshot OK: commit {result.details.get('commit')}, "
                    f"{result.details.get('files')} files"
                )
                return 0
            print(f"snapshot DISABLED: {result.reason} {result.details}", file=sys.stderr)
            return 1
        if args.command == "version":
            value = deployed_code_version()
            print(value if value else "absent")
            return 0
    except (SnapshotBuildError, ManifestError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
