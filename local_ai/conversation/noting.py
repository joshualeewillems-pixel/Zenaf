"""V1 — the noting trailer: flag, instruction, and pure parser.

The capture feed of the narrative architecture's governing direction
(§6): a seat flags what is notable via a bookkeeping trailer riding
its Talk reply — a recognition it has formed, or a visitor objection
it has noticed — parsed post-generation at the ConversationService
seam and stripped before the reply is persisted or seen. The pattern
is the established one (the meeting path's thread trailers; the
Bonsai sketch tail in ``sketch_tail.py``): a pure parser, strip-always
at the seam while the feed is live, citations validated by the
service against the conversation's own messages, non-compliance
degrading to *no note* — never to a visitor-visible artifact and
never to a failed turn.

Seat-general Fellowship infrastructure: nothing here knows any
particular seat. Enablement is per-seat configuration — the
``ZENAF_NOTING_CAPTURE_SEATS`` env var lists the archetype ids the
feed is live for (comma-separated; unset/empty = off everywhere).
Valen (champion) is the slice's first consumer, not the owner: he
appears nowhere in this module.

This module is pure: it imports only the standard library, performs
no I/O beyond reading the flag env var per call, and never raises on
text input.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

#: The capture switch (V1 of the slice's three independent switches;
#: carriage is V3's toggle, gating is V4's — neither lives here).
#: Comma-separated archetype ids; default empty = capture off for
#: every seat. Read per call so tests and operations can flip it
#: without a restart, in the house flag idiom (cf.
#: ``pencil_context_enabled``, local_ai/narrative/context.py).
CAPTURE_SEATS_ENV = "ZENAF_NOTING_CAPTURE_SEATS"

#: Grammar caps — part of the grammar, like the sketch tail's.
#: At most this many notes are taken from one reply (further
#: well-formed notes are stripped but dropped).
MAX_NOTES = 4
#: A recognition statement's character cap.
MAX_STATEMENT_CHARS = 500

_NOTE_MARKER = "[[note:"
_NOTE_RE = re.compile(r"\[\[note:(recognition|objection)\|([^\[\]\n]*)\]\]")
_MSG_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def capture_enabled(arch_id: str | None) -> bool:
    """Is the noting capture feed live for this seat right now?

    Default OFF everywhere: the env var must name the archetype id
    explicitly. With capture off, the service adds no instruction to
    the prompt, runs no parser, and writes nothing — Talk behavior is
    byte-identical to the feed's absence.
    """
    raw = os.environ.get(CAPTURE_SEATS_ENV)
    if raw is None:
        return False
    seats = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return (arch_id or "").strip().lower() in seats


#: The noting instruction — a service-layer prompt addition (the
#: PROPOSAL_INSTRUCTION pattern), present only when capture is
#: enabled for the replying seat, seat-general in wording, kept
#: small and bookkeeping-shaped.
NOTING_INSTRUCTION = (
    "Bookkeeping notes (never speech): when you form a recognition "
    "about the visitor or yourself, or the visitor objects to "
    "something, you may append note lines at the very end of your "
    "reply, each on its own line: [[note:recognition|<the "
    "recognition, in your own words>]] or [[note:objection|<the id "
    "of the visitor's message>]]. Never mention the notes; your "
    "reply must be complete without them. Most turns need no note."
)


@dataclass
class Note:
    """One parsed noting-trailer note.

    ``recognition``: ``statement`` carries the seat's recognition in
    its own words. ``objection``: ``message_id`` cites the visitor
    message the seat flags as an objection — the message itself is
    captured verbatim by reference downstream, never copied here.
    """

    kind: str  # "recognition" | "objection"
    statement: str = ""
    message_id: str = ""


@dataclass
class NotingParseResult:
    """The seam's outcome: the visible reply (all trailer content
    stripped) and the notes that survived the grammar."""

    body: str
    notes: list[Note] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    status: str = "absent"  # "absent" | "ok" | "empty"


def _validate_span(span: str) -> Note | None:
    """Validate one complete ``[[note:...]]`` span; None = no note."""
    match = _NOTE_RE.fullmatch(span)
    if match is None:
        return None
    kind, payload = match.group(1), match.group(2)
    if kind == "recognition":
        statement = payload.strip()
        if not statement or len(statement) > MAX_STATEMENT_CHARS:
            return None
        return Note(kind="recognition", statement=statement)
    message_id = payload.strip()
    if _MSG_ID_RE.fullmatch(message_id) is None:
        return None
    return Note(kind="objection", message_id=message_id)


def parse_noting_trailer(text: str) -> NotingParseResult:
    """Split a generation into (visible reply, notes).

    The strip is total: every ``[[note:`` span — well-formed,
    malformed, glued to prose, or truncated — is removed from the
    returned body, so trailer text can never leak into the visible
    reply. A span yields a note only when it is fully well-formed;
    anything else degrades to no note. Foreign trailers (the sketch
    tail, meeting markers) are not this parser's business and pass
    through untouched. With no marker at all, the text is returned
    byte-identical.
    """
    if not text or _NOTE_MARKER not in text:
        return NotingParseResult(body=text or "", status="absent")
    diagnostics: list[str] = []
    notes: list[Note] = []
    kept_lines: list[str] = []
    found_marker = False
    for line in text.split("\n"):
        removed_on_line = False
        while _NOTE_MARKER in line:
            found_marker = True
            start = line.index(_NOTE_MARKER)
            end = line.find("]]", start)
            if end == -1:
                # Truncated / unterminated bookkeeping: strip from
                # the marker to the end of the line, yield no note.
                diagnostics.append("drop: unterminated note span")
                line = line[:start]
                removed_on_line = True
                break
            span = line[start:end + 2]
            note = _validate_span(span)
            if note is None:
                diagnostics.append("drop: malformed note span")
            elif len(notes) < MAX_NOTES:
                notes.append(note)
            else:
                diagnostics.append("drop: note over per-reply cap")
            line = line[:start] + line[end + 2:]
            removed_on_line = True
        if removed_on_line:
            line = line.rstrip()
            if not line.strip():
                # The line was trailer only; it leaves no trace.
                continue
        kept_lines.append(line)
    body = "\n".join(kept_lines).rstrip("\n") if found_marker else text
    status = "ok" if notes else "empty"
    return NotingParseResult(
        body=body, notes=notes, diagnostics=diagnostics, status=status
    )


__all__ = [
    "CAPTURE_SEATS_ENV",
    "MAX_NOTES",
    "MAX_STATEMENT_CHARS",
    "NOTING_INSTRUCTION",
    "Note",
    "NotingParseResult",
    "capture_enabled",
    "parse_noting_trailer",
]
