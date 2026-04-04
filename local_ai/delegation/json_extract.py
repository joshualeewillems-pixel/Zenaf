"""Extract a single JSON object from model text (fences, junk). Shared by delegation paths."""

from __future__ import annotations

import re
from typing import Any


def extract_json_object(raw: str) -> str | None:
    """Strip markdown/code fences; return first balanced ``{...}`` slice or ``None``."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json|JSON)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
        s = s.strip()
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    quote = None
    for i in range(start, len(s)):
        c = s[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
            elif c in ("'", '"'):
                in_string = True
                quote = c
        else:
            if c == quote:
                in_string = False
    return None
