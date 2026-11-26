"""The [[declare]] declaration tail — Rivers and Holds made in chat.

Board interaction pass (founder direction, 2026-11-25): declaring,
withdrawing, moving, and removing Rivers and Holds is conversational
work with Valen (the chat is the work; the board is the metaphor).
Valen actuates a declaration by ending his reply with a machine-
readable tail, in the established tail-grammar pattern (sketch /
chalk / noting precedents):

    [[declare]]
    declare-window | project=<project-id> | start=2026-12-06 | end=2026-12-09
    withdraw-window | project=<project-id>
    place-hold | project=<project-id> | at=2026-12-07
    move-hold | hold=<hold-id> | at=2026-12-08
    remove-hold | hold=<hold-id>

- The delimiter is a line whose entire stripped content is
  ``[[declare]]``. It opens a tail only when an instruction-shaped
  line follows before any prose line (the tail-position rule).
- Dates are ISO (``YYYY-MM-DD`` or a full ISO datetime) — the dates
  the visitor settled in the conversation, resolved by Valen.
- Caps are part of the grammar: at most 8 acts per tail, the whole
  tail at most 4000 chars.

Failure taxonomy (the chalk assertions, restated):

- Tail-level failure — duplicate delimiter, a prose line or an
  unknown verb inside the tail, the caps exceeded: the WHOLE tail
  drops; the spoken body is returned intact; zero acts result.
- Act-level failure — one line's fields are malformed (missing or
  unexpected key, an unparseable date): THAT act drops with a
  diagnostic; sibling acts still stand.
- Strip-always: on every outcome the returned body contains no
  delimiter line and no tail lines from a recognized tail. With no
  marker events at all, the text is returned byte-identical.

Parsing is only half the contract: the service seam honors the acts
against the turn's staged project and the visitor's own records
(``local_ai/vision_execution/declarations.apply_declaration_act``) —
an act naming anything else writes nothing.

This module is pure: no I/O, no store imports. Persistence and the
seat/context gating live at the service seam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

DELIMITER = "[[declare]]"

VERBS = ("declare-window", "withdraw-window", "place-hold", "move-hold", "remove-hold")

MAX_ACTS = 8
MAX_TAIL_CHARS = 4000

_INSTRUCTION_SHAPED_RE = re.compile(r"^[A-Za-z][A-Za-z_-]*\s*\|")
_VERB_LINE_RE = re.compile(
    r"^(declare-window|withdraw-window|place-hold|move-hold|remove-hold)\s*\|"
    r"|^(withdraw-window|remove-hold)\s*$"
)

#: The keyed fields each verb carries — exactly these, no others.
_VERB_FIELDS: dict[str, tuple[set[str], set[str]]] = {
    "declare-window": ({"project", "start", "end"}, {"project", "start", "end"}),
    "withdraw-window": ({"project"}, {"project"}),
    "place-hold": ({"project", "at"}, {"project", "at"}),
    "move-hold": ({"hold", "at"}, {"hold", "at"}),
    "remove-hold": ({"hold"}, {"hold"}),
}


@dataclass
class DeclarationParseResult:
    body: str
    acts: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    # absent | ok | no_change | grammar_failure | hygiene_strip
    status: str = "absent"


class _GrammarFailure(Exception):
    """Internal: a tail-level failure; the whole tail drops."""


class _ActFailure(Exception):
    """Internal: an act-level failure; that act drops whole."""


def _is_instruction_shaped(line: str) -> bool:
    return bool(_INSTRUCTION_SHAPED_RE.match(line.strip()))


def _valid_date(value: str, field_name: str) -> str:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise _ActFailure("%s: not an ISO date %r" % (field_name, value))
    return value


def _parse_act_line(line: str) -> dict:
    fields = [f for f in (p.strip() for p in line.split("|")) if f != ""]
    verb = fields[0]
    allowed, required = _VERB_FIELDS[verb]
    out: dict[str, str] = {"verb": verb}
    for raw in fields[1:]:
        if "=" not in raw:
            raise _ActFailure("%s: field %r is not key=value" % (verb, raw))
        key, _, value = raw.partition("=")
        key = key.strip()
        value = value.strip()
        if key not in allowed:
            raise _ActFailure("%s: unexpected field %r" % (verb, key))
        if key in out:
            raise _ActFailure("%s: duplicate field %r" % (verb, key))
        if value == "":
            raise _ActFailure("%s: empty value for %r" % (verb, key))
        out[key] = value
    for key in required:
        if key not in out:
            raise _ActFailure("%s: missing required field %r" % (verb, key))
    for key in ("start", "end", "at"):
        if key in out:
            out[key] = _valid_date(out[key], key)
    if verb == "declare-window":
        if not datetime.fromisoformat(out["end"]) > datetime.fromisoformat(out["start"]):
            raise _ActFailure("declare-window: end is not after start")
    return out


def _parse_tail(lines: list[str]) -> tuple[list, list]:
    """Parse the tail's instruction lines into acts.

    Raises _GrammarFailure for tail-level problems; act-level
    problems poison only their own line. Returns (acts, diagnostics).
    """
    acts: list = []
    diagnostics: list = []
    started = 0
    for line in lines:
        stripped = line.strip()
        if not _VERB_LINE_RE.match(stripped):
            if _is_instruction_shaped(stripped):
                raise _GrammarFailure("unknown verb in tail line %r" % stripped[:40])
            # A bare verb with no fields at all (e.g. "declare-window"
            # alone) is an act-level failure, not prose.
            if stripped in VERBS:
                diagnostics.append("act_failure: %s: no fields" % stripped)
                started += 1
                continue
            raise _GrammarFailure("prose line inside the tail %r" % stripped[:40])
        started += 1
        if started > MAX_ACTS:
            raise _GrammarFailure("too many acts (> %d)" % MAX_ACTS)
        # withdraw-window / remove-hold may stand bare (verb only);
        # they then fail at act level for their missing field.
        fields = [f for f in (p.strip() for p in stripped.split("|")) if f != ""]
        verb = fields[0]
        try:
            acts.append(_parse_act_line(stripped))
        except _ActFailure as exc:
            diagnostics.append("act_failure: %s" % exc)
    return acts, diagnostics


def parse_declaration_tail(text: str) -> DeclarationParseResult:
    """Split a generation into (clean body, declaration acts).

    The strip is total: on every outcome the returned body contains
    no delimiter line and no tail lines from a recognized tail.
    Grammar failures return the pre-delimiter body with zero acts.
    With no marker events at all, the text is returned byte-identical.
    """
    lines = text.split("\n")
    diagnostics: list = []
    body_lines: list[str] = []
    status = "absent"
    i = 0
    n = len(lines)
    last_nonblank = max((j for j, l in enumerate(lines) if l.strip() != ""), default=-1)

    def body_text() -> str:
        return "\n".join(body_lines).rstrip("\n")

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if i == last_nonblank and stripped != DELIMITER:
            # A generation truncated mid-delimiter ends on a proper
            # prefix of the delimiter. Grammar failure: the partial
            # marker is bookkeeping, never body text.
            if 3 <= len(stripped) < len(DELIMITER) and DELIMITER.startswith(stripped):
                diagnostics.append("grammar_failure: partial delimiter (truncated generation)")
                return DeclarationParseResult(body_text(), [], diagnostics, "grammar_failure")
            idx = line.rfind("[[")
            if idx > 0:
                frag = line[idx:]
                if 3 <= len(frag) < len(DELIMITER) and DELIMITER.startswith(frag):
                    head = line[:idx].rstrip()
                    if head:
                        body_lines.append(head)
                    diagnostics.append(
                        "grammar_failure: partial glued delimiter (truncated generation)")
                    return DeclarationParseResult(body_text(), [], diagnostics, "grammar_failure")

        if stripped == DELIMITER:
            region = [l for l in lines[i + 1:] if l.strip() != ""]
            if not region:
                diagnostics.append("explicit_no_change: delimiter with zero instruction lines")
                status = "no_change" if status == "absent" else status
                i = n
                continue
            if _is_instruction_shaped(region[0]) or region[0].strip() in VERBS:
                tail_text = "\n".join(lines[i:]).rstrip()
                try:
                    if any(l.strip() == DELIMITER for l in region):
                        raise _GrammarFailure("duplicate delimiter")
                    if len(tail_text) > MAX_TAIL_CHARS:
                        raise _GrammarFailure("tail over %d chars" % MAX_TAIL_CHARS)
                    acts, tail_diags = _parse_tail(region)
                except _GrammarFailure as exc:
                    diagnostics.append("grammar_failure: %s" % exc)
                    return DeclarationParseResult(body_text(), [], diagnostics, "grammar_failure")
                diagnostics.extend(tail_diags)
                return DeclarationParseResult(body_text(), acts, diagnostics, "ok")
            diagnostics.append("marker_stripped: delimiter followed by prose")
            if status == "absent":
                status = "hygiene_strip"
            i += 1
            continue

        if DELIMITER in line:
            following = [l for l in lines[i + 1:] if l.strip() != ""]
            if following and (_is_instruction_shaped(following[0]) or following[0].strip() in VERBS):
                head = line[: line.index(DELIMITER)].rstrip()
                if head:
                    body_lines.append(head)
                diagnostics.append("glued_stripped: fused marker and bookkeeping territory removed")
                if status == "absent":
                    status = "hygiene_strip"
                i += 1
                while i < n and (lines[i].strip() == "" or _is_instruction_shaped(lines[i])):
                    if lines[i].strip() == DELIMITER:
                        break
                    i += 1
                continue
            body_lines.append(line)
            i += 1
            continue

        body_lines.append(line)
        i += 1

    if status == "absent":
        return DeclarationParseResult(text, [], diagnostics, status)
    return DeclarationParseResult(body_text(), [], diagnostics, status)
