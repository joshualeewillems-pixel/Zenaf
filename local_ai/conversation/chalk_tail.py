"""OPS-7 — the [[chalk]] drawing-tail parser (Jynx's carriage).

Parses the delimited bookkeeping tail of a Jynx (maverick) Talk
generation into drawings, per the chalk design record
(zenaf-jynx-chalk-mechanism-investigation-2026-11-17 §§3–5 and the
OPS-7 entry in the technical necessities ledger), adapted to the
drawing vocabulary the shipped Scroll renders (PR #416,
frontend/src/jynx-scroll/scrollLogic.ts): a drawing is an ordered
list of marks in its own coordinate space — a STAMP placement from
Jynx's stencil kit (the closed vocabulary below, placed by centre,
width, angle, flip, and ink tier, exactly as the approved scroll
study's generator places them) or a freehand STROKE (an SVG path in
the minimal sumi hand). The words of the reply carry the content;
the drawing carries the act (Rev 3 §2.4's honesty rule).

Grammar (one instruction per line, ``|``-separated, in the
sketch_tail house idiom):

    [[chalk]]
    drawing | space=600x800 | title=Optional words
    stamp | ring | cx=300 | cy=300 | w=400 | tier=0.60
    stroke | d=M100 600 Q300 560 500 620 | width=3 | tier=0.32

- The delimiter is a line whose entire stripped content is
  ``[[chalk]]``. It opens a tail only when an instruction-shaped
  line follows before any prose line (the tail-position rule).
- A ``drawing`` line opens a drawing; following ``stamp``/``stroke``
  lines are its marks, in arrival order. ``space=`` defaults to
  600x800; ``title=`` is optional, must be the last field, and is
  data only — no surface renders it on the parchment.
- Caps are part of the grammar: at most 4 drawings per tail (the
  bounded-alternatives bound, ledger OPS-7), at most 32 marks per
  drawing, the whole tail at most 8000 chars (measured from the
  delimiter line to the end of the generation, trailing whitespace
  excluded), a stroke path at most 600 chars, a title at most 80.
- Ink tiers are the study's closed three: 0.95 (dark), 0.60 (mid),
  0.32 (light). A stamp's tier defaults to 0.95, the generator's
  own default; a stroke must state its width and tier.

Failure taxonomy (the sketch assertions, restated for drawings):

- Tail-level (grammar) failure — duplicate or partial delimiter, a
  non-instruction line inside the tail, an unknown verb, a mark
  line before any ``drawing`` line, the tail or drawing-count cap
  exceeded: the WHOLE tail drops; the spoken body is returned
  intact; zero drawings result.
- Drawing-level failure — one drawing's line or marks are invalid
  (unknown stamp, bad tier, out-of-range number, malformed path,
  mark cap exceeded, a drawing with no marks): THAT drawing drops
  whole — never half-parsed into a partial drawing — and sibling
  drawings in the same tail still stand.
- Strip-always: on every outcome the returned body contains no
  delimiter line and no tail lines from a recognized tail. With no
  marker events at all, the text is returned byte-identical.

This module is pure: it imports nothing from the conversation
service or any store, and performs no I/O. Persistence and the
rollout flag live at the service seam.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

DELIMITER = "[[chalk]]"

#: The stencil kit's closed vocabulary (scrollLogic.ts StampName;
#: ~/workspace/rendering-test-assets/jynx-stencil-kit).
STAMPS = (
    "arc",
    "caret",
    "crescent",
    "fork",
    "frame",
    "leaf",
    "ring",
    "slash",
    "triangle",
    "wave",
)

#: The study's three ink tiers (build_scroll2.py: DARK/MID/LIGHT).
TIERS = (0.95, 0.60, 0.32)

VERBS = ("drawing", "stamp", "stroke")

MAX_DRAWINGS = 4
MAX_MARKS_PER_DRAWING = 32
MAX_TAIL_CHARS = 8000
MAX_PATH_CHARS = 600
MAX_TITLE_CHARS = 80

DEFAULT_SPACE = (600, 800)
MIN_SPACE_DIM = 50
MAX_SPACE_DIM = 2400
MAX_STAMP_W = 2400.0
MAX_STROKE_WIDTH = 40.0

_INSTRUCTION_SHAPED_RE = re.compile(r"^[A-Za-z][A-Za-z_-]*\s*\|")
_VERB_LINE_RE = re.compile(r"^(drawing|stamp|stroke)\s*\|")
_SPACE_RE = re.compile(r"^(\d{1,4})x(\d{1,4})$")
# An SVG path in the minimal hand: path commands, numbers, and the
# separators between them. No letters beyond the command set and
# the exponent marker, no markup characters — a path that carries
# anything else is not a path this surface will render.
_PATH_CHARS_RE = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz0-9eE+\-.,\s]+$")


@dataclass
class ChalkParseResult:
    body: str
    drawings: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    # absent | ok | no_change | grammar_failure | hygiene_strip
    status: str = "absent"


class _GrammarFailure(Exception):
    """Internal: a tail-level failure; the whole tail drops."""


class _DrawingFailure(Exception):
    """Internal: a drawing-level failure; that drawing drops whole."""


def _is_instruction_shaped(line: str) -> bool:
    return bool(_INSTRUCTION_SHAPED_RE.match(line.strip()))


def _num(value: str, field_name: str) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise _DrawingFailure("%s: not a number %r" % (field_name, value))
    if not math.isfinite(n):
        raise _DrawingFailure("%s: not finite %r" % (field_name, value))
    return n


def _clean_number(n: float):
    """Emit ints where the value is integral (payload hygiene)."""
    return int(n) if float(n).is_integer() else n


def _tier(value: str) -> float:
    n = _num(value, "tier")
    for t in TIERS:
        if abs(n - t) < 0.005:
            return t
    raise _DrawingFailure("tier: not one of 0.95/0.60/0.32: %r" % value)


def _parse_keyed_fields(fields, allowed, required, verb):
    """Parse key=value fields; enforce the allowed/required key sets.

    Structural problems are drawing-level: they are contained in one
    line of one drawing.
    """
    out = {}
    for raw in fields:
        if "=" not in raw:
            raise _DrawingFailure("%s: field %r is not key=value" % (verb, raw))
        key, _, value = raw.partition("=")
        key = key.strip()
        value = value.strip()
        if key not in allowed:
            raise _DrawingFailure("%s: unexpected field %r" % (verb, key))
        if key in out:
            raise _DrawingFailure("%s: duplicate field %r" % (verb, key))
        if value == "":
            raise _DrawingFailure("%s: empty value for %r" % (verb, key))
        out[key] = value
    for key in required:
        if key not in out:
            raise _DrawingFailure("%s: missing required field %r" % (verb, key))
    return out


def _parse_drawing_line(fields) -> dict:
    """A `drawing` line: keyed fields only; title must come last."""
    title = None
    rest = []
    for i, raw in enumerate(fields):
        if raw.startswith("title="):
            if i != len(fields) - 1:
                raise _DrawingFailure("drawing: title= must be the last field")
            title = raw[len("title="):].strip()
        else:
            rest.append(raw)
    keyed = _parse_keyed_fields(rest, {"space"}, set(), "drawing")
    space = DEFAULT_SPACE
    if "space" in keyed:
        m = _SPACE_RE.match(keyed["space"])
        if not m:
            raise _DrawingFailure("drawing: bad space %r" % keyed["space"])
        w, h = int(m.group(1)), int(m.group(2))
        if not (MIN_SPACE_DIM <= w <= MAX_SPACE_DIM and MIN_SPACE_DIM <= h <= MAX_SPACE_DIM):
            raise _DrawingFailure("drawing: space out of range %r" % keyed["space"])
        space = (w, h)
    if title is not None:
        if title == "":
            raise _DrawingFailure("drawing: empty title")
        if len(title) > MAX_TITLE_CHARS:
            raise _DrawingFailure("drawing: title over %d chars" % MAX_TITLE_CHARS)
        if "[[" in title:
            raise _DrawingFailure("drawing: title carries a marker sequence")
    return {"title": title, "space": {"w": space[0], "h": space[1]}, "marks": []}


def _parse_stamp_line(fields, space) -> dict:
    if len(fields) < 1:
        raise _DrawingFailure("stamp: missing stamp name")
    name = fields[0]
    if name not in STAMPS:
        raise _DrawingFailure("stamp: unknown stamp %r" % name)
    keyed = _parse_keyed_fields(
        fields[1:], {"cx", "cy", "w", "angle", "flip", "tier"},
        {"cx", "cy", "w"}, "stamp",
    )
    cx = _num(keyed["cx"], "cx")
    cy = _num(keyed["cy"], "cy")
    w = _num(keyed["w"], "w")
    if not (0 <= cx <= space["w"] and 0 <= cy <= space["h"]):
        raise _DrawingFailure("stamp: centre outside the drawing space")
    if not (0 < w <= MAX_STAMP_W):
        raise _DrawingFailure("stamp: width out of range %r" % keyed["w"])
    mark = {
        "type": "stamp",
        "stamp": name,
        "cx": _clean_number(cx),
        "cy": _clean_number(cy),
        "w": _clean_number(w),
    }
    if "angle" in keyed:
        angle = _num(keyed["angle"], "angle")
        if not (-360 <= angle <= 360):
            raise _DrawingFailure("stamp: angle out of range %r" % keyed["angle"])
        mark["angle"] = _clean_number(angle)
    if "flip" in keyed:
        if keyed["flip"] in ("1", "true"):
            mark["flip"] = True
        elif keyed["flip"] in ("0", "false"):
            mark["flip"] = False
        else:
            raise _DrawingFailure("stamp: bad flip %r" % keyed["flip"])
    mark["tier"] = _tier(keyed["tier"]) if "tier" in keyed else TIERS[0]
    return mark


def _parse_stroke_line(fields) -> dict:
    keyed = _parse_keyed_fields(fields, {"d", "width", "tier"}, {"d", "width", "tier"}, "stroke")
    d = keyed["d"]
    if len(d) > MAX_PATH_CHARS:
        raise _DrawingFailure("stroke: path over %d chars" % MAX_PATH_CHARS)
    if not _PATH_CHARS_RE.match(d):
        raise _DrawingFailure("stroke: path carries characters outside the path vocabulary")
    if not d.lstrip()[:1] in ("M", "m"):
        raise _DrawingFailure("stroke: path does not open with a move command")
    if not any(ch.isdigit() for ch in d):
        raise _DrawingFailure("stroke: path carries no coordinates")
    width = _num(keyed["width"], "width")
    if not (0 < width <= MAX_STROKE_WIDTH):
        raise _DrawingFailure("stroke: width out of range %r" % keyed["width"])
    return {
        "type": "stroke",
        "d": " ".join(d.split()),
        "width": _clean_number(width),
        "tier": _tier(keyed["tier"]),
    }


def _parse_tail(lines):
    """Parse the tail's instruction lines into drawings.

    Raises _GrammarFailure for tail-level problems; drawing-level
    problems poison only their own drawing. Returns (drawings,
    diagnostics).
    """
    drawings = []
    diagnostics = []
    current = None  # the drawing under construction
    poisoned = False  # current drawing failed at drawing level
    started = 0  # drawings begun (the cap binds beginnings, not survivors)

    def finish_current():
        nonlocal current, poisoned
        if current is None:
            return
        if poisoned:
            diagnostics.append("drawing_drop: a drawing was dropped whole")
        elif not current["marks"]:
            diagnostics.append("drawing_drop: a drawing with no marks was dropped")
        else:
            drawings.append(current)
        current = None
        poisoned = False

    for line in lines:
        stripped = line.strip()
        if not _VERB_LINE_RE.match(stripped):
            if _is_instruction_shaped(stripped):
                raise _GrammarFailure("unknown verb in tail line %r" % stripped[:40])
            raise _GrammarFailure("prose line inside the tail %r" % stripped[:40])
        # Empty fields (a trailing "|", a doubled "|") carry no
        # meaning in this grammar and are dropped before parsing.
        fields = [f for f in (p.strip() for p in stripped.split("|")) if f != ""]
        verb = fields[0]
        rest = fields[1:]
        if verb == "drawing":
            finish_current()
            started += 1
            if started > MAX_DRAWINGS:
                raise _GrammarFailure("too many drawings (> %d)" % MAX_DRAWINGS)
            current = None
            poisoned = False
            try:
                current = _parse_drawing_line(rest)
            except _DrawingFailure as exc:
                diagnostics.append("drawing_failure: %s" % exc)
                current = {"title": None, "space": {"w": DEFAULT_SPACE[0], "h": DEFAULT_SPACE[1]}, "marks": []}
                poisoned = True
            continue
        # stamp / stroke
        if current is None:
            raise _GrammarFailure("%s line before any drawing line" % verb)
        if poisoned:
            continue  # consumed as part of the dropped drawing
        try:
            if verb == "stamp":
                mark = _parse_stamp_line(rest, current["space"])
            else:
                mark = _parse_stroke_line(rest)
        except _DrawingFailure as exc:
            diagnostics.append("drawing_failure: %s" % exc)
            poisoned = True
            continue
        current["marks"].append(mark)
        if len(current["marks"]) > MAX_MARKS_PER_DRAWING:
            diagnostics.append(
                "drawing_failure: more than %d marks in one drawing" % MAX_MARKS_PER_DRAWING)
            poisoned = True
    finish_current()
    return drawings, diagnostics


def parse_chalk_tail(text: str) -> ChalkParseResult:
    """Split a generation into (clean body, drawings).

    The strip is total: on every outcome the returned body contains
    no delimiter line and no tail lines from a recognized tail.
    Grammar failures return the pre-delimiter body with zero
    drawings. With no marker events at all, the text is returned
    byte-identical.
    """
    lines = text.split("\n")
    diagnostics = []
    body_lines = []
    status = "absent"
    i = 0
    n = len(lines)
    last_nonblank = max((j for j, l in enumerate(lines) if l.strip() != ""), default=-1)

    def body_text():
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
                return ChalkParseResult(body_text(), [], diagnostics, "grammar_failure")
            idx = line.rfind("[[")
            if idx > 0:
                frag = line[idx:]
                if 3 <= len(frag) < len(DELIMITER) and DELIMITER.startswith(frag):
                    head = line[:idx].rstrip()
                    if head:
                        body_lines.append(head)
                    diagnostics.append(
                        "grammar_failure: partial glued delimiter (truncated generation)")
                    return ChalkParseResult(body_text(), [], diagnostics, "grammar_failure")

        if stripped == DELIMITER:
            # Standalone delimiter: examine the non-blank lines after it.
            region = [l for l in lines[i + 1:] if l.strip() != ""]
            if not region:
                # Explicit no-change: delimiter (and trailing blanks) drop.
                diagnostics.append("explicit_no_change: delimiter with zero instruction lines")
                status = "no_change" if status == "absent" else status
                i = n
                continue
            if _is_instruction_shaped(region[0]):
                # A tail opens; it consumes the rest of the generation.
                tail_text = "\n".join(lines[i:]).rstrip()
                try:
                    if any(l.strip() == DELIMITER for l in region):
                        raise _GrammarFailure("duplicate delimiter")
                    if len(tail_text) > MAX_TAIL_CHARS:
                        raise _GrammarFailure("tail over %d chars" % MAX_TAIL_CHARS)
                    drawings, tail_diags = _parse_tail(region)
                except _GrammarFailure as exc:
                    diagnostics.append("grammar_failure: %s" % exc)
                    return ChalkParseResult(body_text(), [], diagnostics, "grammar_failure")
                diagnostics.extend(tail_diags)
                return ChalkParseResult(body_text(), drawings, diagnostics, "ok")
            # Delimiter followed by prose: strip the marker line
            # only; the prose is body. Keep scanning for a later tail.
            diagnostics.append("marker_stripped: delimiter followed by prose")
            if status == "absent":
                status = "hygiene_strip"
            i += 1
            continue

        if DELIMITER in line:
            # Glued marker candidate: it is bookkeeping territory only
            # when an instruction-shaped line follows before any prose.
            following = [l for l in lines[i + 1:] if l.strip() != ""]
            if following and _is_instruction_shaped(following[0]):
                head = line[: line.index(DELIMITER)].rstrip()
                if head:
                    body_lines.append(head)
                diagnostics.append("glued_stripped: fused marker and bookkeeping territory removed")
                if status == "absent":
                    status = "hygiene_strip"
                i += 1
                # Drop the consecutive instruction-shaped territory.
                while i < n and (lines[i].strip() == "" or _is_instruction_shaped(lines[i])):
                    if lines[i].strip() == DELIMITER:
                        break
                    i += 1
                continue
            # Marker-like text inside ordinary prose: preserved as speech.
            body_lines.append(line)
            i += 1
            continue

        body_lines.append(line)
        i += 1

    if status == "absent":
        # No marker events: byte-identical return.
        return ChalkParseResult(text, [], diagnostics, status)
    return ChalkParseResult(body_text(), [], diagnostics, status)
