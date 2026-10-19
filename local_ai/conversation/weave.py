"""Shared [[u]]...[[/u]] weave-marker sanitizer.

Council voices weave the user's own words into replies wrapped in
``[[u]]...[[/u]]`` markers (rendered amber in the client). When weaving
densely the model occasionally emits malformed closings (``[/u]]``,
``[/[/u]]``). This normalizes known variants to the canonical close and
drops orphan opens so broken markup never reaches any client — demo,
authenticated chat, or API consumers.
"""

import re

WEAVE_OPEN = "[[u]]"
WEAVE_CLOSE = "[[/u]]"

_WEAVE_CLOSE_RE = re.compile(r"\[/\[/u\]\]|\[/u\]\]|\[\[/u\]\]")


def sanitize_weave(text: str) -> str:
    """Normalize model-generated [[u]]...[[/u]] markers.

    Known malformed closings become the canonical ``[[/u]]``; an open
    marker with no recognizable close is dropped while its words are kept.
    Plain text passes through untouched.
    """
    parts = text.split(WEAVE_OPEN)
    out = [parts[0]]
    for seg in parts[1:]:
        m = _WEAVE_CLOSE_RE.search(seg)
        if m:
            out.append(WEAVE_OPEN + seg[: m.start()] + WEAVE_CLOSE + seg[m.end() :])
        else:
            out.append(seg)  # orphan open marker dropped, words kept
    return "".join(out)
