"""
Deterministic resolution buffers derived from scan aggregates (no second filesystem pass).

Layer contracts and default exposure policy: see ``buffer_contracts`` (strict roles,
pipeline order, decision surface = functional + reasoning only). Per-layer resolution
boundaries and examples: ``BUFFER_BEHAVIORAL_CONTRACTS`` / ``validate_buffer_output_shape``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from local_ai.workspace_identity.buffer_contracts import BUFFER_PIPELINE_KEYS, validate_buffer_stack_present
from local_ai.workspace_identity.mirror_prose_title import mirror_basename_looks_like_prose_title

# --- Caps ---
MAX_PHRASES_SHALLOW = 40
MAX_PATH_SKETCHES = 25
MAX_CLUSTERS = 15
MAX_MEMBERS_PER_CLUSTER = 8
MAX_BUCKET_LABELS = 12
MAX_FUNCTIONAL_TAGS = 20
MAX_REASONING_THEMES = 14
MAX_NAMED_PROGRAMS = 10

# Extraction packet: max raw basename strings taken from surface_shallow after deeper buffers.
# Reasoning (functional) + path sketches fill the pool first so literals reflect the pipeline.
MAX_SURFACE_LITERALS_IN_PACKET = 12

# Pull extra candidates before shallow filter so we can still fill MAX_PHRASES_SHALLOW.
_SURFACE_SHALLOW_RANK_POOL = 400

# --- surface_shallow only: strip low-signal tokens (deterministic, no ML) ---
_SURFACE_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "to",
        "too",
        "up",
        "with",
        "without",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "not",
        "no",
        "yes",
        "all",
        "any",
        "each",
        "every",
        "some",
        "such",
        "this",
        "that",
        "these",
        "those",
        "i",
        "me",
        "my",
        "we",
        "us",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "it",
        "its",
        "they",
        "them",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "when",
        "where",
        "why",
        "how",
        "can",
        "could",
        "may",
        "might",
        "must",
        "shall",
        "should",
        "will",
        "would",
        "get",
        "got",
        "set",
        "use",
        "using",
        "used",
        "via",
        "new",
        "old",
        "just",
        "also",
        "only",
        "like",
        "one",
        "two",
        "first",
        "last",
        "next",
        "here",
        "there",
    }
)

_SURFACE_GENERIC: frozenset[str] = frozenset(
    {
        "page",
        "pages",
        "copy",
        "copies",
        "watch",
        "watches",
        "desktop",
        "mobile",
        "web",
        "site",
        "sites",
        "thing",
        "things",
        "stuff",
        "item",
        "items",
        "system",
        "systems",
        "file",
        "files",
        "folder",
        "folders",
        "directory",
        "directories",
        "path",
        "paths",
        "name",
        "names",
        "type",
        "types",
        "kind",
        "kinds",
        "data",
        "info",
        "content",
        "contents",
        "body",
        "text",
        "code",
        "source",
        "target",
        "output",
        "input",
        "default",
        "defaults",
        "general",
        "misc",
        "other",
        "others",
        "temp",
        "tmp",
        "backup",
        "archive",
        "old",
        "draft",
        "final",
        "home",
        "shared",
        "public",
        "private",
        "internal",
        "external",
        "local",
        "remote",
        "utils",
        "utilities",
        "helpers",
        "common",
        "core",
        "base",
        "main",
        "index",
        "sample",
        "example",
        "demo",
        "test",
        "tests",
        "spec",
        "mock",
        "stub",
        "assets",
        "asset",
        "images",
        "image",
        "img",
        "media",
        "static",
        "resources",
        "resource",
        "profile",
        "profiles",
        "unnamed",
        "config",
        "settings",
        "options",
        "preferences",
        "docs",
        "doc",
        "readme",
        "license",
        "changelog",
        "notes",
        "note",
        "report",
        "reports",
        "update",
        "updates",
        "link",
        "links",
        "list",
        "lists",
        "sheet",
        "table",
        "row",
        "column",
        "user",
        "users",
        "admin",
        "guest",
        "account",
        "accounts",
        "session",
        "sessions",
        "login",
        "logout",
        "dashboard",
        "dashboards",
        "panel",
        "widget",
        "menu",
        "toolbar",
        "window",
        "dialog",
        "popup",
        "modal",
        "view",
        "views",
        "screen",
        "screens",
        "app",
        "apps",
        "application",
        "applications",
        "service",
        "services",
        "server",
        "servers",
        "client",
        "clients",
        "api",
        "http",
        "rest",
        "graphql",
        "json",
        "xml",
        "yaml",
        "toml",
        "csv",
        "sql",
        "db",
        "database",
        "repo",
        "repos",
        "repository",
        "git",
        "branch",
        "build",
        "dist",
        "pkg",
        "package",
        "packages",
        "lib",
        "libs",
        "library",
        "libraries",
        "module",
        "modules",
        "component",
        "components",
        "hook",
        "hooks",
        "util",
        "misc",
        "video",
        "videos",
        "audio",
        "image",
        "template",
        "templates",
        "slide",
        "slides",
        "deck",
        "document",
        "meeting",
        "meetings",
        "email",
        "mail",
        "css",
        "js",
        "javascript",
        "typescript",
        "python",
        "java",
        "rust",
        "go",
        "php",
        "ruby",
        "swift",
        "kotlin",
    }
)

_WEB_CACHE_MIRROR_JUNK_RE = re.compile(
    r"(www-main-|www-player-|www-onepick-|font-awesome|-skeleton|vfl[a-z0-9]{5,}|^rs=|async_usersync|saved_resource)",
    re.IGNORECASE,
)


def _segment_looks_like_saved_page_files_folder(seg: str) -> bool:
    """Match snapshot._looks_like_saved_page_companion_dir (no cross-import: snapshot imports buffers)."""
    n = seg.strip()
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


def _path_rel_noise_for_clustering(rel: str) -> bool:
    low = rel.replace("\\", "/").casefold()
    if "rs=" in low:
        return True
    for seg in low.split("/"):
        if _segment_looks_like_saved_page_files_folder(seg):
            return True
        if mirror_basename_looks_like_prose_title(seg):
            return True
    return False


def _label_noise_for_clustering(label: str) -> bool:
    raw = label.strip()
    if mirror_basename_looks_like_prose_title(raw):
        return True
    low = raw.casefold()
    if low.startswith("rs=") and len(low) >= 12:
        return True
    if "async_usersync" in low or "saved_resource" in low:
        return True
    if low == "api-surface":
        return True
    return False


def _cluster_parent_sketch_is_noise(parent: str) -> bool:
    p = parent.strip()
    if not p or p == ".":
        return False
    return _path_rel_noise_for_clustering(p)


_PROSE_MIRROR_DOC_SUFFIX_RE = re.compile(
    r"\.(docx?|pdf|pptx?|xlsx?|rtf|odt|odp|ods|epub|txt)\b",
    re.IGNORECASE,
)


def _phrase_looks_like_web_cache_junk(low: str) -> bool:
    if mirror_basename_looks_like_prose_title(low):
        return True
    if _WEB_CACHE_MIRROR_JUNK_RE.search(low):
        return True
    if low.count(",") >= 3:
        return True
    if low == "api-surface":
        return True
    if "_files" in low and (" co-occurring" in low or "co-occurring items" in low):
        return True
    if low.startswith("copy of ") or low.startswith("copy_of_"):
        return True
    if " — " in low or " – " in low:
        return True
    if "[" in low and "]" in low and len(low) > 22:
        return True
    if _PROSE_MIRROR_DOC_SUFFIX_RE.search(low):
        if low in {
            "readme.txt",
            "license.txt",
            "changelog.txt",
            "requirements.txt",
            "robots.txt",
            "security.txt",
            "todo.txt",
            "manifest.txt",
            "authors.txt",
            "contributing.txt",
            "copying.txt",
            "install.txt",
        } or (low.startswith("requirements") and low.endswith(".txt")):
            return False
        return True
    return False


# Short tokens that are still useful as literals when they appear as path segments.
_SURFACE_TECH_SHORT_OK: frozenset[str] = frozenset(
    {
        "ai",
        "ml",
        "llm",
        "nlp",
        "gpu",
        "cpu",
        "iot",
        "ux",
        "ui",
        "cli",
        "sdk",
        "rpc",
        "jwt",
        "sso",
        "oauth",
        "phi",
        "ehr",
        "hl7",
        "fhir",
        "hipaa",
    }
)

_SURFACE_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "tion",
    "ment",
    "ness",
    "ity",
    "ing",
    "able",
    "ible",
    "ology",
    "ence",
    "ance",
    "eous",
    "ious",
    "iasis",
    "emia",
    "scopy",
    "pathy",
)

# Single-token keep: frequency floor when using domain-ish heuristic (not proper-noun style).
_SURFACE_SINGLE_FREQ_FLOOR = 4
_SURFACE_DOMAINISH_MIN_LEN = 8


def _surface_segment_count(s: str) -> int:
    parts = [p for p in re.split(r"[\s\-_]+", s.strip()) if len(p) >= 2]
    return len(parts)


def _surface_is_camel_or_pascal(s: str) -> bool:
    if not s or not s[0].isalpha():
        return False
    if re.fullmatch(r"[A-Z][a-z]+(?:[A-Z][a-z]+)+", s):
        return True
    if re.fullmatch(r"[a-z]+(?:[A-Z][a-z]+)+", s):
        return True
    return False


def _surface_is_title_word(s: str) -> bool:
    return len(s) >= 4 and s[0].isupper() and s[1:].islower() and s[1:].isalpha()


def _surface_is_acronym(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{2,6}", s))


def _surface_count_for_key(counts: Counter[str], phrase: str) -> int:
    n = counts.get(phrase, 0)
    if n:
        return n
    low = phrase.lower()
    return sum(v for k, v in counts.items() if k.lower() == low)


def _surface_substantive_parts(s: str) -> list[str]:
    return [p for p in re.split(r"[\s\-_]+", s.strip()) if len(p) >= 2]


def _surface_part_ok(part: str) -> bool:
    low = part.lower()
    if low in _SURFACE_TECH_SHORT_OK and len(low) >= 2:
        return True
    if len(low) < 3:
        return False
    if low in _SURFACE_STOPWORDS or low in _SURFACE_GENERIC:
        return False
    return True


def _surface_multi_segment_keeps(phrase: str) -> bool:
    parts = _surface_substantive_parts(phrase)
    if len(parts) < 2:
        return False
    ok = [p for p in parts if _surface_part_ok(p)]
    if len(ok) >= 2:
        return True
    if (
        len(ok) == 1
        and ("_" in phrase or "-" in phrase)
        and len(phrase.strip()) >= 6
        and any(p.lower() in _SURFACE_TECH_SHORT_OK and len(p) >= 2 for p in parts)
    ):
        return True
    return False


def _surface_domainish_token(low: str) -> bool:
    if len(low) < _SURFACE_DOMAINISH_MIN_LEN:
        return False
    if any(ch.isdigit() for ch in low):
        return True
    return any(low.endswith(suf) for suf in _SURFACE_DOMAIN_SUFFIXES)


def keep_surface_shallow_phrase(phrase: str, counts: Counter[str]) -> bool:
    """
    Deterministic filter for surface_shallow.phrases only.
    Suppresses stopwords / generic nouns and low-signal single tokens.
    """
    s = phrase.strip()
    if len(s) < 3:
        return False
    low = s.lower()
    if low in _SURFACE_STOPWORDS or low in _SURFACE_GENERIC:
        return False
    if _phrase_looks_like_web_cache_junk(low):
        return False

    if _surface_multi_segment_keeps(s):
        return True

    if _surface_is_camel_or_pascal(s) or _surface_is_acronym(s):
        return True

    if _surface_is_title_word(s):
        return True

    if low in _SURFACE_TECH_SHORT_OK:
        return True

    n = _surface_count_for_key(counts, s)
    if n >= _SURFACE_SINGLE_FREQ_FLOOR and _surface_domainish_token(low):
        return True

    return False


def _surface_has_irregular_token_casing(phrase: str) -> bool:
    """
    True for typo / paste artifacts like ``hElaing``, ``FOcus``, ``DIspenza`` (internal case breaks).
    Normal Title Case or single leading cap per word is allowed.
    """
    for raw in re.split(r"[\s\-_/]+", phrase):
        word = raw.strip(".,()[]\"'")
        if len(word) < 4:
            continue
        if re.search(r"[a-z][A-Z]", word):
            return True
        if re.search(r"[A-Z]{2,}[a-z]", word):
            return True
    return False


def keep_packet_surface_literal(phrase: str, counts: Counter[str]) -> bool:
    """
    Stricter than surface_shallow alone: basename phrases promoted into the workspace packet
    must pass this so garbled-casing filenames do not dominate over deeper buffer outputs.
    """
    if not keep_surface_shallow_phrase(phrase, counts):
        return False
    if _surface_has_irregular_token_casing(phrase):
        return False
    return True


def identity_scan_looks_low_quality(
    *,
    phrases: list[str],
    hint_key_count: int,
    nodes_walked: int,
    junk_path_segments: int,
) -> bool:
    """
    Heuristic: many filesystem nodes / raw hint keys but few phrases passing the mirror filter,
    or heavy junk suppression — suggests wrong scan roots or mostly generic artifacts.
    """
    n = len(phrases)
    if n == 0:
        return True
    if n <= 3 and hint_key_count >= 32:
        return True
    if n <= 5 and nodes_walked >= 380:
        return True
    if junk_path_segments >= 70 and n <= 10:
        return True
    if n <= 2 and nodes_walked >= 120:
        return True
    return False


BUFFER_GRAPH: dict[str, Any] = {
    "version": 1,
    "layers": [{"index": idx, "key": key} for idx, key in BUFFER_PIPELINE_KEYS],
    "edges": [
        {"from": "surface_shallow", "to": "associative_cluster", "pass": 0, "layer": 0},
        {"from": "associative_cluster", "to": "structural_translation", "pass": 1, "layer": 1},
        {"from": "structural_translation", "to": "functional", "pass": 2, "layer": 2},
        {"from": "functional", "to": "reasoning", "pass": 3, "layer": 3},
    ],
}

# (bucket_name, pattern) — matched against posix path lower
_STRUCTURAL_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("engine", re.compile(r"(^|/)local_ai(/|$)|(^|/)api(/|$)|(^|/)tools(/|$)")),
    ("ui", re.compile(r"(^|/)frontend(/|$)|components|\.tsx?$|\.jsx?$")),
    ("docs", re.compile(r"(^|/)docs(/|$)|\.md$|readme|changelog", re.I)),
    ("tests", re.compile(r"(^|/)tests?(/|$)|__tests__|\.test\.|\.spec\.")),
    ("config", re.compile(r"(^|/)\.github(/|$)|(^|/)config(/|$)|\.ya?ml$|\.toml$")),
    ("integrations", re.compile(r"intake|oauth|webhook|stripe|email|imap|gmail")),
]

_ACTIVITY_TOKENS: list[tuple[str, str]] = [
    (r"onboard", "onboarding"),
    (r"intake", "intake"),
    (r"deploy", "deployment"),
    (r"rfp|proposal", "proposals"),
    (r"extract|ingest", "extraction"),
    (r"identity|workspace", "workspace-identity"),
    (r"harvest|ledger", "harvest"),
    (r"signal|radar", "signals"),
    (r"evaluat|assess", "evaluation"),
    (r"automat|workflow", "automation"),
]

_ROLE_TOKENS: list[tuple[str, str]] = [
    (r"patient|clinic|provider", "clinical"),
    (r"meeting|transcript|segment", "meetings"),
    (r"api|route|endpoint", "api-surface"),
    (r"auth|session|login", "auth"),
]


def _parent_sketch(path_relative: str) -> str:
    p = path_relative.replace("\\", "/").strip("/")
    if "/" not in p:
        return "."
    return "/".join(p.split("/")[:-1]) or "."


# Top-level (first path segment) buckets that are almost always course / notes trees, not repo identity.
_PATH_SKETCH_JUNK_ROOT_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)^ai\s+how\s+to\b"),
    re.compile(r"(?i)^a\s+powerful\s+day\b"),
    re.compile(r"(?i)^a\s+mastermind\b"),
    re.compile(r"(?i)^how\s+to\b"),
    re.compile(r"(?i)^book$"),
    re.compile(r"(?i)^stories$"),
)

# Explorer / course scaffolding folder names (any segment).
_PATH_SKETCH_OS_PLACEHOLDER_RE = re.compile(r"(?i)^new\s+folder(\s*\(\d+\))?\s*$")
_PATH_SKETCH_WEEK_UNIT_RE = re.compile(r"(?i)^week\s*\d+\s*$")

# Wellness / course folder stems that rarely encode repo identity (path sketches only; not global mirror).
_PATH_SKETCH_COACHING_PHRASE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bpassion\s+test\b"),
    re.compile(r"(?i)\bsignature\s+talk\b"),
    re.compile(r"(?i)\bpeace\s+walk\b"),
    re.compile(r"(?i)\bteach\s+back\b"),
    re.compile(r"(?i)\bbook\s+writing\b"),
    re.compile(r"(?i)\bjoe\s+dispenza\b"),
    re.compile(r"(?i)\bdispenza\b"),
    re.compile(r"(?i)manifestation[a-z]{1,4}$"),
)
_PATH_SKETCH_ENROL_RE = re.compile(r"(?i)^enrolments?$")


def _path_sketch_segment_is_noise(segment: str) -> bool:
    s = segment.strip()
    if not s:
        return True
    if ";" in s:
        return True
    if _PATH_SKETCH_OS_PLACEHOLDER_RE.match(s):
        return True
    if _PATH_SKETCH_WEEK_UNIT_RE.match(s):
        return True
    if _PATH_SKETCH_ENROL_RE.match(s):
        return True
    if re.search(r"(?i)^for\s+[A-Z][a-z]{2,}\b", s):
        return True
    if re.search(r"[A-Za-z]\d+[A-Za-z]{2,}", s):
        return True
    if any(rx.search(s) for rx in _PATH_SKETCH_COACHING_PHRASE_RES):
        return True
    if mirror_basename_looks_like_prose_title(s):
        return True
    if _surface_has_irregular_token_casing(s):
        return True
    return False


def keep_path_sketch_literal(sketch: str) -> bool:
    """
    Path sketches (parent/child co-occurrence) promoted into the packet must pass this.
    Drops course-style buckets, prose titles, paste typos, and ``FOR Name`` ops folders.
    """
    raw = sketch.replace("\\", "/").strip().strip("/")
    if not raw:
        return False
    parts = [p for p in raw.split("/") if p.strip()]
    if not parts:
        return False
    first = parts[0]
    if any(rx.search(first) for rx in _PATH_SKETCH_JUNK_ROOT_RES):
        return False
    return not any(_path_sketch_segment_is_noise(p) for p in parts)


def _path_sketches_from_records(records: list[dict[str, str]], cap: int) -> list[str]:
    sketches: set[str] = set()
    for r in records:
        rel = r.get("pathRelative") or ""
        if not rel:
            continue
        parts = rel.replace("\\", "/").strip("/").split("/")
        if not parts:
            continue
        if len(parts) >= 2:
            sk = "/".join(parts[:2])
        else:
            sk = parts[0]
        if keep_path_sketch_literal(sk):
            sketches.add(sk)
    out = sorted(sketches, key=lambda s: (-len(s.split("/")), s.lower()))
    return out[:cap]


def _sort_phrases_from_counter(counts: Counter[str], cap: int) -> list[str]:
    items = list(counts.items())
    items.sort(
        key=lambda kv: (
            -kv[1],
            -_surface_segment_count(kv[0]),
            -len(kv[0].split()),
            -len(kv[0]),
            kv[0].lower(),
        )
    )
    seen: set[str] = set()
    out: list[str] = []
    for k, _ in items:
        low = k.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(k)
        if len(out) >= cap:
            break
    return out


def build_associative_clusters(records: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Buffer 1: co-occurrence under parent sketches; no semantic typing."""
    by_parent: dict[str, list[str]] = defaultdict(list)
    for r in records:
        rel = (r.get("pathRelative") or "").replace("\\", "/")
        name = r.get("label") or ""
        if not rel or not name:
            continue
        if _path_rel_noise_for_clustering(rel) or _label_noise_for_clustering(name):
            continue
        parent = _parent_sketch(rel)
        by_parent[parent].append(name)
    scored: list[tuple[str, list[str], int]] = []
    for parent, members in by_parent.items():
        uniq = sorted({m for m in members if m}, key=lambda x: x.lower())[:MAX_MEMBERS_PER_CLUSTER]
        if len(uniq) < 2 and parent == ".":
            continue
        weight = len(members)
        scored.append((parent, uniq, weight))
    scored.sort(key=lambda t: (-t[2], t[0].lower()))
    clusters: list[dict[str, Any]] = []
    for i, (parent, members, weight) in enumerate(scored[:MAX_CLUSTERS]):
        if len(members) < 2:
            continue
        clusters.append(
            {
                "id": f"c-{i}",
                "parentSketch": parent[:120],
                "members": members[:MAX_MEMBERS_PER_CLUSTER],
                "weight": weight,
            }
        )
    return clusters


def build_structural_buckets(records: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Buffer 2: map paths/labels to structural system types (engine, ui, media, …)."""
    buckets: dict[str, list[str]] = defaultdict(list)
    seen_label: dict[str, set[str]] = defaultdict(set)
    for r in records:
        rel = ((r.get("pathRelative") or "") + "/" + (r.get("label") or "")).lower().replace("\\", "/")
        label = r.get("label") or ""
        if not label:
            continue
        bucket = "general"
        for bname, pat in _STRUCTURAL_RULES:
            if pat.search(rel):
                bucket = bname
                break
        low = label.lower()
        if low not in seen_label[bucket]:
            seen_label[bucket].add(low)
            buckets[bucket].append(label)
    order = ["engine", "ui", "tests", "docs", "integrations", "config", "general"]
    out: list[dict[str, Any]] = []
    for b in order:
        labels = sorted(buckets.get(b, []), key=lambda x: (-len(x), x.lower()))[:MAX_BUCKET_LABELS]
        if labels:
            out.append({"bucket": b, "labels": labels})
    return out


def build_functional_tags(records: list[dict[str, str]], phrases: list[str]) -> dict[str, list[str]]:
    """Buffer 3: operational purpose tags; may unify disparate surface strings."""
    text = " ".join(
        [(r.get("label") or "") + " " + (r.get("pathRelative") or "") for r in records]
        + phrases
    ).lower()
    activities: list[str] = []
    roles: list[str] = []
    for pat, tag in _ACTIVITY_TOKENS:
        if re.search(pat, text) and tag not in activities:
            activities.append(tag)
    for pat, tag in _ROLE_TOKENS:
        if re.search(pat, text) and tag not in roles:
            roles.append(tag)
    return {
        "activityTags": activities[:MAX_FUNCTIONAL_TAGS],
        "roleHints": roles[:MAX_FUNCTIONAL_TAGS],
    }


def build_reasoning_buffer(
    *,
    clusters: list[dict[str, Any]],
    structural: list[dict[str, Any]],
    functional: dict[str, list[str]],
) -> dict[str, list[str]]:
    """
    Buffer 4: synthesize judgment lines from buffers 1–3 only.
    Does not ingest surface_shallow phrases (no upward literal leakage).
    """
    themes: list[str] = []
    for c in clusters[:8]:
        m = c.get("members") or []
        if len(m) >= 2:
            parent = str(c.get("parentSketch") or "")
            if _cluster_parent_sketch_is_noise(parent):
                continue
            n = len(m)
            if parent and parent != ".":
                piece = f"{parent}: {n} co-occurring items"
            else:
                piece = f"Co-occurring group: {n} items"
            if len(piece) >= 8:
                themes.append(piece[:160])
    for b in structural[:5]:
        labels = b.get("labels") or []
        bucket = str(b.get("bucket") or "general")
        if len(labels) >= 2:
            themes.append(f"{bucket}: {len(labels)} structural labels"[:160])
    named: list[str] = []
    for tag in list(functional.get("activityTags") or []) + list(functional.get("roleHints") or []):
        t = str(tag).strip()
        if len(t) >= 3 and t not in named:
            named.append(t)
    named = sorted(set(named), key=lambda x: (-len(x), x.lower()))[:MAX_NAMED_PROGRAMS]
    tags = list(functional.get("activityTags") or []) + list(functional.get("roleHints") or [])
    tags = sorted(set(tags), key=lambda x: x.lower())[:MAX_FUNCTIONAL_TAGS]
    themes = sorted(set(themes), key=lambda x: (-len(x), x.lower()))[:MAX_REASONING_THEMES]
    return {
        "themes": themes,
        "namedPrograms": named,
        "tags": tags,
    }


def build_all_buffers(
    *,
    path_records: list[dict[str, str]],
    hint_counts: Counter[str],
) -> dict[str, Any]:
    ranked = _sort_phrases_from_counter(hint_counts, _SURFACE_SHALLOW_RANK_POOL)
    phrases_for_downstream = ranked[:MAX_PHRASES_SHALLOW]
    phrases_shallow = [p for p in ranked if keep_surface_shallow_phrase(p, hint_counts)][:MAX_PHRASES_SHALLOW]
    path_sketches = _path_sketches_from_records(path_records, MAX_PATH_SKETCHES)
    # Buffer 0: literals only (phrases + sketches); interpretation happens in deeper layers.
    surface_shallow: dict[str, Any] = {
        "phrases": phrases_shallow,
        "pathSketches": path_sketches,
    }
    clusters = build_associative_clusters(path_records)
    associative_cluster = {"clusters": clusters}
    structural = build_structural_buckets(path_records)
    structural_translation = {"buckets": structural}
    functional_raw = build_functional_tags(path_records, phrases_for_downstream)
    functional = {
        "activityTags": functional_raw["activityTags"],
        "roleHints": functional_raw["roleHints"],
    }
    reasoning = build_reasoning_buffer(
        clusters=clusters,
        structural=structural,
        functional=functional_raw,
    )
    out = {
        "surface_shallow": surface_shallow,
        "associative_cluster": associative_cluster,
        "structural_translation": structural_translation,
        "functional": functional,
        "reasoning": reasoning,
    }
    stack_issues = validate_buffer_stack_present(out)
    if stack_issues:
        raise RuntimeError("buffer pipeline incomplete: " + "; ".join(stack_issues))
    return out


def migrate_v1_snapshot_to_v2_shape(snap: dict[str, Any]) -> dict[str, Any]:
    """In-memory v1 → v2 for packet / extract paths (no FS)."""
    if snap.get("schemaVersion") == 2:
        return snap
    hints = list(snap.get("domainHints") or [])
    if not isinstance(hints, list):
        hints = []
    surfaces = list(snap.get("surfaces") or [])
    fps = list(snap.get("fingerprints") or [])
    records: list[dict[str, str]] = []
    for s in surfaces:
        if not isinstance(s, dict):
            continue
        records.append(
            {
                "pathRelative": str(s.get("pathRelative") or ""),
                "label": str(s.get("label") or ""),
                "kind": str(s.get("kind") or "folder"),
            }
        )
    counts: Counter[str] = Counter()
    for h in hints:
        counts[str(h).strip()] = counts.get(str(h).strip(), 0) + 2
    buffers = build_all_buffers(path_records=records, hint_counts=counts)
    out = {**snap, "schemaVersion": 2}
    out["rawIndex"] = {"surfaces": surfaces, "fingerprints": fps}
    out["buffers"] = buffers
    out["bufferGraph"] = BUFFER_GRAPH
    out["domainHints"] = buffers["surface_shallow"]["phrases"][:40]
    return out
