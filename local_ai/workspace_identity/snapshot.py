"""
Bounded filesystem scan → local workspace identity snapshot (mirror only).
Extraction must not call this module; use build_workspace_packet_from_snapshot on a loaded JSON only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
from collections import Counter, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from local_ai.workspace_identity.buffers import (
    BUFFER_GRAPH,
    MAX_SURFACE_LITERALS_IN_PACKET,
    build_all_buffers,
    identity_scan_looks_low_quality,
    keep_packet_surface_literal,
    keep_path_sketch_literal,
    migrate_v1_snapshot_to_v2_shape,
)
from local_ai.workspace_identity.mirror_prose_title import mirror_basename_looks_like_prose_title
from local_ai.workspace_identity.translation_template import (
    apply_workspace_translation_template,
    read_translation_template,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- Caps (deterministic) ---
SCHEMA_VERSION = 2
MAX_DEPTH_DEFAULT = 4
MAX_NODES_DEFAULT = 5000
MAX_DOMAIN_HINTS_SNAPSHOT = 40
MAX_SURFACES = 30
MAX_PACKET_HINTS = 36
MAX_PATH_RECORDS = 800

IDENTITY_LOW_QUALITY_USER_MESSAGE = (
    "Workspace identity appears low-quality (mostly generic filenames). Consider changing scan roots."
)

# Prune at directory entry: no descent, no hints, no node budget (same as legacy IGNORE_DIR_NAMES).
PRUNE_DIR_NAMES_LOWER: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        "target",
        ".idea",
        ".vscode",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
        "htmlcov",
        # OS / package / download noise
        "downloads",
        "download",
        "__macosx",
        "$recycle.bin",
        "system volume information",
        "appdata",
        "application data",
        "local settings",
        "temporary internet files",
        "inetcache",
        "cookies",
        "history",
        "recent",
        "sent",
        "trash",
        ".trash",
        # Browser / app caches (segment names only)
        "gpucache",
        "code cache",
        "shadercache",
        "grshadercache",
        "dawncache",
        "videodecodestats",
        "blob_storage",
        "blob storage",
        "mediacache",
        "jump lists",
        "jumplist",
        "thumbnails",
        "thumbnail",
        "thumbcache",
        "safe browsing",
        "session storage",
        "local storage",
        "indexeddb",
        "service worker",
        "webrtccache",
        "file system",
        "offlineworker",
        "package cache",
        "npm-cache",
        "pnpm-store",
        ".gradle",
    }
)

# Directory basenames to prune — duplicate downloads / thumbnails / generic artifact folders only.
_JUNK_PRUNE_DIR_STEMS_LOWER: frozenset[str] = frozenset(
    {
        "profile",
        "unnamed",
        "resource",
        "thumbnails",
        "thumbnail",
    }
)

# Pruned directory name prefixes (browser/thumbnail trees).
_JUNK_DIR_PREFIXES_LOWER: tuple[str, ...] = (
    "hqdefault",
    "maxresdefault",
    "sddefault",
    "unnamed",
    "img_cache",
    "imagecache",
)

# File stem prefixes treated as media/thumbnail noise (also used for code files).
_THUMB_FILE_PREFIXES_LOWER: tuple[str, ...] = (
    "hqdefault",
    "maxresdefault",
    "sddefault",
)

# Code-like extensions: never drop hints solely for generic stems like "resource".
_CODE_LIKE_SUFFIXES_LOWER: frozenset[str] = frozenset(
    {
        ".py",
        ".pyi",
        ".pyw",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".rs",
        ".go",
        ".java",
        ".kt",
        ".kts",
        ".swift",
        ".cs",
        ".cpp",
        ".cc",
        ".cxx",
        ".c",
        ".h",
        ".hh",
        ".hpp",
        ".rb",
        ".php",
        ".vue",
        ".svelte",
        ".scala",
        ".clj",
        ".ex",
        ".exs",
        ".fs",
        ".fsx",
        ".ml",
        ".mli",
        ".hs",
        ".lhs",
        ".r",
        ".sql",
        ".graphql",
        ".gql",
    }
)

# Skip file entry entirely (no hints, surfaces, path records, node budget).
_ARTIFACT_FILE_SUFFIXES_LOWER: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
        ".ico",
        ".heic",
        ".heif",
        ".avif",
        ".svg",
        ".mp4",
        ".webm",
        ".m4v",
        ".mov",
        ".avi",
        ".mkv",
        ".mp3",
        ".wav",
        ".ogg",
        ".m4a",
        ".flac",
        ".opus",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".pak",
        ".sqlite",
        ".db",
        ".ldb",
        ".log",
        ".crdownload",
        ".part",
        ".download",
        ".tmp",
        ".temp",
        ".cache",
        ".bak",
        ".old",
        ".swp",
        ".swo",
        ".dmg",
        ".iso",
        ".bin",
        ".exe",
        ".dll",
        ".msi",
        ".deb",
        ".rpm",
        ".apk",
        ".ipa",
        ".zip",
        ".rar",
        ".7z",
        ".tar",
        ".gz",
        ".tgz",
        ".xz",
        ".zst",
        ".html",
        ".htm",
        ".mhtml",
        ".xhtml",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".map",
    }
)

# YouTube / CDN / minified bundle garbage in browser caches (often extensionless or odd names).
_CACHE_VFL_HASH_RE = re.compile(r"vfl[a-z0-9]{5,}", re.IGNORECASE)


def _looks_like_saved_page_companion_dir(name: str) -> bool:
    """Chrome/Edge 'Save page as' folders: '<title>_files' or variants with ' - Copy'."""
    n = name.strip()
    low = n.casefold()
    if "_files - copy" in low:
        return True
    if not low.endswith("_files"):
        return False
    stem = low[: -len("_files")].strip()
    if not stem:
        return False
    if any(ch in n for ch in " &,") or ";" in n:
        return True
    if len(n) > 40:
        return True
    if stem.count("_") >= 4:
        return True
    return False


def _looks_like_browser_cache_asset(name: str) -> bool:
    """True for cached web bundles, skeleton CSS stems, font CDNs, minified param blobs."""
    low = name.casefold().strip()
    if not low:
        return False
    if low.startswith("rs=") and len(low) >= 12:
        return True
    if "async_usersync" in low or "saved_resource" in low:
        return True
    if low == "api-surface":
        return True
    if "font-awesome" in low:
        return True
    if low.startswith(("www-main-", "www-player-", "www-onepick-")):
        return True
    if "www-" in low and ("skeleton" in low or "-webp-" in low or "webp-" in low):
        return True
    if _CACHE_VFL_HASH_RE.search(low):
        return True
    if low.count(",") >= 4 and len(low) <= 500:
        return True
    if low.count(",") >= 3 and len(low) <= 120 and re.fullmatch(r"[a-z0-9_=,\-]+", low):
        return True
    return False


_COPY_SUFFIX_RE = re.compile(r"(?: \(\d+\)|\(\d+\))$", re.IGNORECASE)

GENERIC_HINT_TOKENS = frozenset(
    {
        "video",
        "videos",
        "template",
        "templates",
        "dashboard",
        "dashboards",
        "slide",
        "slides",
        "deck",
        "doc",
        "docs",
        "document",
        "file",
        "files",
        "meeting",
        "meetings",
        "notes",
        "note",
        "report",
        "reports",
        "update",
        "updates",
        "link",
        "links",
        "email",
        "list",
        "sheet",
        "assets",
        "asset",
        "readme",
        "license",
        "changelog",
        "index",
        "main",
        "test",
        "tests",
        "src",
        "lib",
        "pkg",
        "tmp",
        "temp",
        "data",
        "public",
        "static",
        "images",
        "img",
        "css",
        "js",
        "profile",
        "profiles",
        "unnamed",
        "resource",
        "resources",
        "thumbnail",
        "thumbnails",
    }
)

STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "from",
        "with",
        "this",
        "that",
        "your",
        "our",
        "are",
        "was",
        "not",
        "has",
        "have",
        "been",
        "into",
        "over",
        "new",
        "old",
        "all",
        "any",
        "can",
        "use",
        "using",
        "used",
        "get",
        "set",
        "add",
        "via",
    }
)


def _dir_should_prune(name: str) -> bool:
    seg = name.casefold()
    if seg in PRUNE_DIR_NAMES_LOWER or seg in _JUNK_PRUNE_DIR_STEMS_LOWER:
        return True
    return any(seg.startswith(p) for p in _JUNK_DIR_PREFIXES_LOWER)


def _is_artifact_file(name: str) -> bool:
    suf = Path(name).suffix.casefold()
    return suf in _ARTIFACT_FILE_SUFFIXES_LOWER


# Office / ebook blobs: titles are prose, not workspace identity (buffer 0 stays structural).
_PROSE_DOCUMENT_SUFFIXES_LOWER: frozenset[str] = frozenset(
    {
        ".doc",
        ".docx",
        ".pdf",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".rtf",
        ".odt",
        ".odp",
        ".ods",
        ".epub",
    }
)

# Plain text is usually notes/exports; allow typical repo utility names only.
_TXT_MIRROR_ALLOWED_LOWER: frozenset[str] = frozenset(
    {
        "readme.txt",
        "license.txt",
        "changelog.txt",
        "authors.txt",
        "contributing.txt",
        "copying.txt",
        "install.txt",
        "manifest.txt",
        "requirements.txt",
        "todo.txt",
        "security.txt",
        "robots.txt",
    }
)


def _txt_basename_allowed_in_mirror(name: str) -> bool:
    low = Path(name).name.casefold()
    if low in _TXT_MIRROR_ALLOWED_LOWER:
        return True
    if low.startswith("requirements") and low.endswith(".txt"):
        return True
    return False


def _is_prose_document_mirror_excluded(name: str) -> bool:
    """Exclude from hint_counts, path_records, and surfaces (still consumes walk budget)."""
    suf = Path(name).suffix.casefold()
    if suf == ".txt":
        return not _txt_basename_allowed_in_mirror(name)
    return suf in _PROSE_DOCUMENT_SUFFIXES_LOWER


def _basename_core_display(name: str, *, is_dir: bool) -> str:
    raw = name if is_dir else Path(name).stem
    raw = _COPY_SUFFIX_RE.sub("", raw).strip()
    return raw.casefold()


def _stem_matches_thumbnail_junk(name: str) -> bool:
    core = _basename_core_display(name, is_dir=False)
    if not core:
        return False
    return any(core.startswith(p) for p in _THUMB_FILE_PREFIXES_LOWER)


def _should_suppress_hints_for_file(name: str) -> bool:
    """Skip mirror hints for noisy non-code names (HTML already excluded as artifact)."""
    if _is_prose_document_mirror_excluded(name):
        return True
    if _looks_like_browser_cache_asset(name):
        return True
    suf = Path(name).suffix.casefold()
    if suf not in _CODE_LIKE_SUFFIXES_LOWER and not _is_artifact_file(name):
        if mirror_basename_looks_like_prose_title(Path(name).stem):
            return True
    if suf in _CODE_LIKE_SUFFIXES_LOWER:
        return _stem_matches_thumbnail_junk(name)
    core = _basename_core_display(name, is_dir=False)
    if not core or len(core) < 2:
        return True
    if _stem_matches_thumbnail_junk(name):
        return True
    if core in _JUNK_PRUNE_DIR_STEMS_LOWER:
        return True
    if core.startswith("unnamed"):
        return True
    return False


def default_workspace_identity_dir(repo_root: Path | None = None) -> Path:
    return (repo_root or REPO_ROOT) / ".zenaf" / "workspace-identity" / "v1"


def snapshot_path(base: Path | None = None) -> Path:
    return (base or default_workspace_identity_dir()) / "snapshot.json"


def meta_path(base: Path | None = None) -> Path:
    return (base or default_workspace_identity_dir()) / "meta.json"


def compute_branch_key(*, cwd: Path | None = None) -> str:
    """Prefer git branch@shortSha; else ZENAF_WORKSPACE_LABEL or local-unknown."""
    root = cwd or REPO_ROOT
    try:
        br = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=8,
            encoding="utf-8",
            errors="replace",
        )
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=8,
            encoding="utf-8",
            errors="replace",
        )
        if br.returncode == 0 and sha.returncode == 0:
            b = (br.stdout or "").strip()
            s = (sha.stdout or "").strip()
            if b and s:
                return f"{b}@{s}"
    except Exception as e:
        logger.debug("[workspace-identity] git branch key failed: %s", e)
    label = (os.environ.get("ZENAF_WORKSPACE_LABEL") or "").strip()
    if label:
        return f"label:{label}"
    return "local-unknown"


def _root_id(root: Path) -> str:
    raw = str(root.resolve())
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _is_generic_label(s: str) -> bool:
    t = s.strip().lower()
    if len(t) < 3:
        return True
    if t in GENERIC_HINT_TOKENS:
        return True
    if len(t.split()) == 1 and t in GENERIC_HINT_TOKENS:
        return True
    return False


def _tokenize_name(name: str) -> list[str]:
    parts = re.split(r"[\s\-_]+", name)
    out: list[str] = []
    for p in parts:
        x = p.strip().lower()
        if len(x) < 3 or x in STOPWORDS or x in GENERIC_HINT_TOKENS:
            continue
        out.append(x)
    return out


def _add_hints_from_basename(name: str, counts: Counter[str]) -> None:
    if not name or name.startswith("."):
        return
    stem = Path(name).stem
    if stem != name and "." in name:
        candidates = [name, stem]
    else:
        candidates = [name]
    for piece in candidates:
        p = piece.strip()
        if len(p) >= 3 and not _is_generic_label(p):
            counts[p] += 1
        for tok in _tokenize_name(stem if len(stem) >= 3 else name):
            counts[tok] += 1


def build_workspace_identity_snapshot(
    roots: list[str],
    *,
    repo_root: Path | None = None,
    scan_kind: str = "deep_initial",
    max_depth: int = MAX_DEPTH_DEFAULT,
    max_nodes: int = MAX_NODES_DEFAULT,
) -> dict[str, Any]:
    """
    Walk only ``roots`` (bounded). Folder/file basenames only; no file body reads.
    Returns snapshot dict (does not write files).
    """
    rr = (repo_root or REPO_ROOT).resolve()
    norm_roots: list[Path] = []
    for r in roots:
        p = Path(r).expanduser().resolve()
        if not p.exists():
            logger.warning("[workspace-identity] skipping missing root: %s", r)
            continue
        norm_roots.append(p)
    if not norm_roots:
        norm_roots = [rr]

    norm_roots = sorted({p.resolve() for p in norm_roots}, key=lambda x: str(x).lower())
    branch_key = compute_branch_key(cwd=rr)
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    hint_counts: Counter[str] = Counter()
    surfaces: list[dict[str, Any]] = []
    path_records: list[dict[str, str]] = []
    fingerprints: list[dict[str, Any]] = []
    nodes_left = max_nodes
    max_depth_hit = 0
    node_cap_reached = False
    truncated = False
    junk_segments = 0

    def _record_path(rel_to: str, name: str, kind: str) -> None:
        if len(path_records) >= MAX_PATH_RECORDS:
            return
        path_records.append({"pathRelative": rel_to, "label": name, "kind": kind})

    for root in norm_roots:
        if nodes_left <= 0:
            node_cap_reached = True
            break
        rid = _root_id(root)
        entry_count = 0
        max_mtime = 0
        try:
            root_resolved = root.resolve()
        except OSError:
            continue

        q: deque[tuple[Path, int]] = deque([(root_resolved, 0)])
        while q and nodes_left > 0:
            path, depth = q.popleft()
            max_depth_hit = max(max_depth_hit, depth)
            try:
                if path.is_symlink() and path.is_dir():
                    continue
                it = os.scandir(path)
            except OSError:
                continue
            with it:
                entries = sorted(it, key=lambda e: e.name.lower())
            for ent in entries:
                if nodes_left <= 0:
                    node_cap_reached = True
                    break
                name = ent.name
                if name.startswith("."):
                    continue
                is_dir_ent = ent.is_dir(follow_symlinks=False)
                if is_dir_ent and (
                    _dir_should_prune(name)
                    or _looks_like_browser_cache_asset(name)
                    or _looks_like_saved_page_companion_dir(name)
                ):
                    junk_segments += 1
                    continue
                if not is_dir_ent and (_is_artifact_file(name) or _looks_like_browser_cache_asset(name)):
                    junk_segments += 1
                    continue
                nodes_left -= 1
                entry_count += 1
                try:
                    st = ent.stat(follow_symlinks=False)
                    if hasattr(st, "st_mtime"):
                        max_mtime = max(max_mtime, int(st.st_mtime))
                except OSError:
                    pass

                if is_dir_ent:
                    if not mirror_basename_looks_like_prose_title(name):
                        _add_hints_from_basename(name, hint_counts)
                    try:
                        pr = Path(ent.path)
                        rel_to = str(pr.relative_to(root_resolved)).replace("\\", "/")
                    except ValueError:
                        rel_to = name
                    _record_path(rel_to, name, "folder")
                    if len(surfaces) < MAX_SURFACES:
                        surfaces.append({"label": name, "pathRelative": rel_to, "kind": "folder"})
                    if depth < max_depth:
                        q.append((Path(ent.path), depth + 1))
                elif ent.is_file(follow_symlinks=False):
                    if not _should_suppress_hints_for_file(name):
                        _add_hints_from_basename(name, hint_counts)
                        try:
                            pr = Path(ent.path)
                            rel_to = str(pr.relative_to(root_resolved)).replace("\\", "/")
                        except ValueError:
                            rel_to = name
                        _record_path(rel_to, name, "file")
                        if len(surfaces) < MAX_SURFACES:
                            surfaces.append({"label": name, "pathRelative": rel_to, "kind": "file"})

        fingerprints.append({"rootId": rid, "entryCount": entry_count, "maxMtime": max_mtime})

    truncated = bool(node_cap_reached)

    buffers = build_all_buffers(path_records=path_records, hint_counts=hint_counts)
    phrases = list(buffers.get("surface_shallow", {}).get("phrases") or [])
    domain_hints = phrases[:MAX_DOMAIN_HINTS_SNAPSHOT]

    total_walked = sum(int(f.get("entryCount") or 0) for f in fingerprints)
    low_identity_quality = identity_scan_looks_low_quality(
        phrases=phrases,
        hint_key_count=len(hint_counts),
        nodes_walked=total_walked,
        junk_path_segments=junk_segments,
    )
    identity_warning = IDENTITY_LOW_QUALITY_USER_MESSAGE if low_identity_quality else None

    snapshot: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": now,
        "branchKey": branch_key,
        "sourceRoots": [str(p) for p in norm_roots],
        "domainHints": domain_hints,
        "rawIndex": {
            "surfaces": surfaces[:MAX_SURFACES],
            "fingerprints": fingerprints,
        },
        "buffers": buffers,
        "bufferGraph": BUFFER_GRAPH,
        "scanHealth": {
            "nodeCapReached": node_cap_reached,
            "maxDepthHit": max_depth_hit,
            "truncated": bool(truncated),
            "ignored": sorted(PRUNE_DIR_NAMES_LOWER),
            "pathRecords": len(path_records),
            "junkPathSegments": junk_segments,
            "nodesWalked": total_walked,
            "identityQualityWarning": identity_warning,
        },
        "provenance": {"scan_kind": scan_kind if scan_kind in ("deep_initial", "light_refresh") else "light_refresh"},
    }
    return snapshot


def _canonical_json_bytes(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(snapshot)).hexdigest()


def write_workspace_identity_snapshot(
    snapshot: dict[str, Any],
    *,
    base_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Write snapshot.json + meta.json under base_dir; create parents."""
    base = base_dir or default_workspace_identity_dir()
    base.mkdir(parents=True, exist_ok=True)
    sp = snapshot_path(base)
    mp = meta_path(base)
    sp.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    meta = {
        "branchKey": snapshot.get("branchKey"),
        "generatedAt": snapshot.get("generatedAt"),
        "snapshotHash": snapshot_hash(snapshot),
    }
    mp.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    buf = snapshot.get("buffers") or {}
    rs = (buf.get("reasoning") or {}) if isinstance(buf, dict) else {}
    logger.info(
        "[workspace-identity] wrote roots=%s hints=%s reasoning_themes=%s branchKey=%s",
        len(snapshot.get("sourceRoots") or []),
        len(snapshot.get("domainHints") or []),
        len(rs.get("themes") or []) if isinstance(rs, dict) else 0,
        snapshot.get("branchKey"),
    )
    return sp, mp


def read_snapshot_file(base_dir: Path | None = None) -> dict[str, Any] | None:
    sp = snapshot_path(base_dir)
    if not sp.is_file():
        return None
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("[workspace-identity] failed to read snapshot: %s", e)
        return None
    if not isinstance(data, dict):
        return None
    ver = data.get("schemaVersion")
    if ver not in (1, 2):
        return None
    return data


def read_meta_file(base_dir: Path | None = None) -> dict[str, Any] | None:
    mp = meta_path(base_dir)
    if not mp.is_file():
        return None
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_snapshot_and_meta(base_dir: Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    return read_snapshot_file(base_dir), read_meta_file(base_dir)


def normalize_snapshot_for_extract(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Ensure v2 + buffers for packet / extract helpers."""
    if not snapshot or not isinstance(snapshot, dict):
        return None
    if snapshot.get("schemaVersion") == 2 and isinstance(snapshot.get("buffers"), dict):
        return snapshot
    return migrate_v1_snapshot_to_v2_shape(snapshot)


def build_workspace_packet_from_snapshot(
    snapshot: dict[str, Any] | None,
    *,
    translation_base_dir: Path | None = None,
) -> dict[str, Any] | None:
    """
    Extraction packet: literal anchors + reasoning capsule + backward-compatible domainHints.

    Literal pool order: reasoning ``namedPrograms`` / ``tags`` (buffer 4, functional lineage),
    then ``surface_shallow.pathSketches``, then a **capped** set of basename phrases that pass
    ``keep_packet_surface_literal`` — so the packet reflects the pipeline, not raw filenames only.

    After that, merges optional ``translation-template.json`` from ``translation_base_dir``.
    """
    snap = normalize_snapshot_for_extract(snapshot)
    if not snap:
        return None
    buffers = snap.get("buffers") or {}
    shallow = buffers.get("surface_shallow") or {}
    phrases = list(shallow.get("phrases") or snap.get("domainHints") or [])
    reasoning = buffers.get("reasoning") or {}

    phrase_counts: Counter[str] = Counter()
    for h in phrases:
        s = str(h).strip()
        if s:
            phrase_counts[s] = max(phrase_counts[s], 3)

    # Tiered literals: deeper buffers first (functional/reasoning), then path co-occurrence
    # sketches, then a capped set of surface basename phrases — not "all filenames first".
    seen: set[str] = set()
    entries: list[tuple[int, int, int, str]] = []

    def _try_add_literal(tier: int, raw: str) -> bool:
        t = str(raw).strip()
        if len(t) < 3 or _is_generic_label(t):
            return False
        low = t.lower()
        if low in seen:
            return False
        seen.add(low)
        wc = len(t.split())
        entries.append((tier, -wc, -len(t), t))
        return True

    if isinstance(reasoning, dict):
        for key in ("namedPrograms", "tags"):
            for x in reasoning.get(key) or []:
                if len(seen) >= MAX_PACKET_HINTS:
                    break
                _try_add_literal(0, x)

    for sk in shallow.get("pathSketches") or []:
        if len(seen) >= MAX_PACKET_HINTS:
            break
        norm = str(sk).replace("\\", "/").strip()
        if not keep_path_sketch_literal(norm):
            continue
        _try_add_literal(1, norm)

    surface_added = 0
    for h in phrases:
        if len(seen) >= MAX_PACKET_HINTS:
            break
        if surface_added >= MAX_SURFACE_LITERALS_IN_PACKET:
            break
        s = str(h).strip()
        if not keep_packet_surface_literal(s, phrase_counts):
            continue
        if _try_add_literal(2, s):
            surface_added += 1

    entries.sort(key=lambda e: (e[0], e[1], e[2], e[3].lower()))
    literal_pool = [e[3] for e in entries[:MAX_PACKET_HINTS]]

    themes = [str(t).strip() for t in (reasoning.get("themes") or []) if str(t).strip()][:12]
    tags = [str(t).strip() for t in (reasoning.get("tags") or []) if str(t).strip()][:16]
    named_programs = [str(t).strip() for t in (reasoning.get("namedPrograms") or []) if str(t).strip()][:10]

    reasoning_capsule = {
        "themes": themes,
        "namedPrograms": named_programs,
        "tags": tags,
    }
    tpl = read_translation_template(translation_base_dir)
    literal_pool, reasoning_capsule = apply_workspace_translation_template(
        literal_pool,
        reasoning_capsule,
        tpl,
        max_hints=MAX_PACKET_HINTS,
    )
    if not literal_pool:
        return None

    return {
        "schemaVersion": 2,
        "domainHints": literal_pool,
        "literalAnchors": literal_pool,
        "reasoningCapsule": reasoning_capsule,
    }


def snapshot_age_seconds(snapshot: dict[str, Any] | None) -> float | None:
    if not snapshot:
        return None
    ga = snapshot.get("generatedAt")
    if not isinstance(ga, str):
        return None
    try:
        raw = ga.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - dt).total_seconds())
    except ValueError:
        return None


TTL_STALE_SECONDS = int(timedelta(days=7).total_seconds())


def snapshot_usable_for_extract(
    snapshot: dict[str, Any] | None,
    *,
    current_branch_key: str | None = None,
) -> tuple[bool, str]:
    """
    Branch mismatch → not usable (no silent stale mirror).
    Returns (usable, reason_code).
    """
    if not snapshot:
        return False, "missing"
    if snapshot.get("schemaVersion") not in (1, 2):
        return False, "invalid_schema"
    cur = current_branch_key or compute_branch_key()
    snap_br = snapshot.get("branchKey")
    if snap_br != cur:
        return False, "branch_mismatch"
    return True, "ok"
