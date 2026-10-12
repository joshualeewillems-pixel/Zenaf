"""Locate soil Markdown files by soil_id (for CLI promote)."""

from __future__ import annotations

import re
from pathlib import Path


_SOIL_ID_RE = re.compile(
    r"^soil_id:\s*(?:(?P<q>\"(?P<qv>[^\"]*)\"|'(?P<qs>[^']*)')|(?P<bare>[^\s#]+))",
    re.MULTILINE,
)
_NODE_ID_RE = re.compile(
    r"^node_id:\s*(?:(?P<q>\"(?P<qv>[^\"]*)\"|'(?P<qs>[^']*)')|(?P<bare>[^\s#]+))",
    re.MULTILINE,
)


def parse_soil_frontmatter_ids(text: str) -> tuple[str | None, str | None]:
    """Return (soil_id, node_id) from first YAML frontmatter block, if present."""
    if not text.startswith("---"):
        return None, None
    end = text.find("\n---", 3)
    if end == -1:
        return None, None
    block = text[3:end]
    sid = _extract_id(_SOIL_ID_RE, block)
    nid = _extract_id(_NODE_ID_RE, block)
    return sid, nid


def _extract_id(rx: re.Pattern[str], block: str) -> str | None:
    m = rx.search(block)
    if not m:
        return None
    if m.group("qv") is not None:
        return m.group("qv")
    if m.group("qs") is not None:
        return m.group("qs")
    return (m.group("bare") or "").strip() or None


def find_soil_md_by_id(root: Path, soil_id: str) -> tuple[Path, str, str]:
    """
    Search nodes/**/soil/**/*.md (excluding soil/promoted/) for matching soil_id.

    Returns (absolute_path, relative_posix_path_from_root, node_id_from_frontmatter).
    Raises FileNotFoundError if not found or ambiguous.
    """
    want = (soil_id or "").strip()
    if not want:
        raise ValueError("soil_id is empty")

    nodes = root / "nodes"
    if not nodes.is_dir():
        raise FileNotFoundError(f"no nodes/ under soil root: {root}")

    matches: list[tuple[Path, str, str]] = []
    for md in nodes.rglob("*.md"):
        parts = md.parts
        try:
            si = parts.index("soil")
        except ValueError:
            continue
        if si + 1 >= len(parts) or parts[si + 1] == "promoted":
            continue

        text = md.read_text(encoding="utf-8")
        sid, nid = parse_soil_frontmatter_ids(text)
        if sid == want:
            if not nid:
                raise ValueError(f"soil file {md} matches soil_id but has no node_id in frontmatter")
            rel_posix = md.resolve().relative_to(root.resolve()).as_posix()
            matches.append((md.resolve(), rel_posix, nid))

    if not matches:
        raise FileNotFoundError(f"no soil item with soil_id={want!r} under {root}")
    if len(matches) > 1:
        paths = ", ".join(m[0].as_posix() for m in matches[:5])
        raise ValueError(
            f"ambiguous soil_id {want!r}: {len(matches)} files ({paths}…)"
        )
    return matches[0]
