"""Stage 1A — the Bonsai Bench shaping-tail parser (standalone).

Parses the delimited bookkeeping tail of a Severine (skeptic) Talk
generation into Level-1 sketch instructions, per the Shape A narrow
technical design (Rev 2, sections 3-5):

- The delimiter is a line whose entire stripped content is ``[[sketch]]``.
- A delimiter opens a tail only when an instruction-shaped line follows
  it before any prose line (the tail-position rule, design section 3.1).
- The vocabulary is closed: nine verbs (branch, reading, support, cross,
  gap, revise, remove, keep, accept). An unknown verb is a grammar
  failure.
- Caps are part of the grammar: at most 6 instruction lines per tail,
  labels at most 80 chars, total tail at most 600 chars (measured from
  the start of the delimiter line to the end of the generation,
  trailing whitespace excluded).
- Fail-closed: any grammar-level failure drops the WHOLE tail and the
  spoken body is returned intact (design A4). A citation-level failure
  drops only that element (design A5). There is no retry path (A6).

This module is pure: it imports nothing from the conversation service,
the conversation store, or any other Zenaf module, and it performs no
I/O. Citation *validation* at Stage 1A is syntactic, plus existence /
role checks against caller-supplied identifier sets when the caller
provides them; unresolved references otherwise pass through for the
Stage 1B seam to validate (scope section 1A.1).

Instruction dicts use the tail's own field names:
  branch/reading: {verb, label, ground, src[, on][, cross]}
  support:        {verb, handle, ground, src}
  cross:          {verb, a, b}
  gap:            {verb, label, basis}
  revise:         {verb, handle[, label][, ground]}
  remove/keep/accept: {verb, handle}
References are carried as their raw strings ('turn', 'msg:<id>',
'rec:<id>', and for basis= also 'reply').
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DELIMITER = "[[sketch]]"

VERBS = (
    "branch",
    "reading",
    "support",
    "cross",
    "gap",
    "revise",
    "remove",
    "keep",
    "accept",
)

GROUND_KINDS = ("reported", "documented", "assumed")
SUPPORT_GROUND_KINDS = ("reported", "documented")

MAX_INSTRUCTIONS = 6
MAX_LABEL_CHARS = 80
MAX_TAIL_CHARS = 600

_HANDLE_RE = re.compile(r"^e[1-9][0-9]*$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
# Loose "instruction-shaped" test used by the tail-position rule and the
# glued-marker rule: a word token followed by a field separator. Prose
# that begins "<word> |" is therefore treated as bookkeeping territory;
# that is a deliberate, documented interpretation (see results note).
_INSTRUCTION_SHAPED_RE = re.compile(r"^[A-Za-z][A-Za-z_-]*\s*\|")


@dataclass
class ParseResult:
    body: str
    instructions: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    # absent | ok | no_change | grammar_failure | hygiene_strip
    status: str = "absent"


class _GrammarFailure(Exception):
    """Internal: a grammar-level failure; the whole tail drops."""


def _is_instruction_shaped(line: str) -> bool:
    return bool(_INSTRUCTION_SHAPED_RE.match(line.strip()))


def _parse_ref(value: str, *, allow_reply: bool) -> str:
    """Validate a src=/basis= reference's syntax; return it unchanged."""
    if value == "turn" or (allow_reply and value == "reply"):
        return value
    for prefix in ("msg:", "rec:"):
        if value.startswith(prefix) and _ID_RE.match(value[len(prefix):]):
            return value
    raise _GrammarFailure("malformed reference %r" % value)


def _parse_keyed_fields(fields, allowed, required, verb):
    """Parse key=value fields; enforce the allowed/required key sets."""
    out = {}
    for raw in fields:
        if "=" not in raw:
            raise _GrammarFailure("%s: field %r is not key=value" % (verb, raw))
        key, _, value = raw.partition("=")
        key = key.strip()
        value = value.strip()
        if key not in allowed:
            raise _GrammarFailure("%s: unexpected field %r" % (verb, key))
        if key in out:
            raise _GrammarFailure("%s: duplicate field %r" % (verb, key))
        if value == "":
            raise _GrammarFailure("%s: empty value for %r" % (verb, key))
        out[key] = value
    for key in required:
        if key not in out:
            raise _GrammarFailure("%s: missing required field %r" % (verb, key))
    return out


def _check_label(label, verb):
    if label == "":
        raise _GrammarFailure("%s: empty label" % verb)
    if len(label) > MAX_LABEL_CHARS:
        raise _GrammarFailure(
            "%s: label over %d chars" % (verb, MAX_LABEL_CHARS))
    return label


def _check_ground(value, verb, allowed=GROUND_KINDS):
    if value not in allowed:
        raise _GrammarFailure("%s: bad ground= %r" % (verb, value))
    return value


def _check_handle(value, verb):
    if not _HANDLE_RE.match(value):
        raise _GrammarFailure("%s: bad handle %r" % (verb, value))
    return value


def _parse_instruction(line: str) -> dict:
    """Strict-parse one instruction line; raise _GrammarFailure."""
    fields = [f.strip() for f in line.split("|")]
    verb = fields[0]
    if verb not in VERBS:
        raise _GrammarFailure("unknown verb %r" % verb)
    rest = fields[1:]

    if verb in ("branch", "reading"):
        if not (3 <= len(rest) <= (5 if verb == "reading" else 3)):
            raise _GrammarFailure("%s: wrong field count" % verb)
        label = _check_label(rest[0], verb)
        allowed = {"ground", "src"} | ({"on", "cross"} if verb == "reading" else set())
        keyed = _parse_keyed_fields(rest[1:], allowed, {"ground", "src"}, verb)
        ins = {
            "verb": verb,
            "label": label,
            "ground": _check_ground(keyed["ground"], verb),
            "src": _parse_ref(keyed["src"], allow_reply=False),
        }
        if "on" in keyed:
            ins["on"] = _check_handle(keyed["on"], verb)
        if "cross" in keyed:
            ins["cross"] = _check_handle(keyed["cross"], verb)
        return ins

    if verb == "support":
        if len(rest) != 3:
            raise _GrammarFailure("support: wrong field count")
        handle = _check_handle(rest[0], verb)
        keyed = _parse_keyed_fields(rest[1:], {"ground", "src"}, {"ground", "src"}, verb)
        return {
            "verb": verb,
            "handle": handle,
            "ground": _check_ground(keyed["ground"], verb, SUPPORT_GROUND_KINDS),
            "src": _parse_ref(keyed["src"], allow_reply=False),
        }

    if verb == "cross":
        if len(rest) != 2:
            raise _GrammarFailure("cross: wrong field count")
        return {
            "verb": verb,
            "a": _check_handle(rest[0], verb),
            "b": _check_handle(rest[1], verb),
        }

    if verb == "gap":
        if len(rest) != 2:
            raise _GrammarFailure("gap: wrong field count")
        label = _check_label(rest[0], verb)
        if any(f.startswith("src=") for f in rest[1:]):
            raise _GrammarFailure("gap: carries src= (gaps cite a basis, not a source)")
        keyed = _parse_keyed_fields(rest[1:], {"basis"}, {"basis"}, verb)
        return {
            "verb": verb,
            "label": label,
            "basis": _parse_ref(keyed["basis"], allow_reply=True),
        }

    if verb == "revise":
        if not (2 <= len(rest) <= 3):
            raise _GrammarFailure("revise: wrong field count")
        handle = _check_handle(rest[0], verb)
        if len(rest) == 1:
            raise _GrammarFailure("revise: no change field (label= or ground= required)")
        keyed = _parse_keyed_fields(rest[1:], {"label", "ground"}, set(), verb)
        if not keyed:
            raise _GrammarFailure("revise: no change field (label= or ground= required)")
        ins = {"verb": verb, "handle": handle}
        if "label" in keyed:
            ins["label"] = _check_label(keyed["label"], verb)
        if "ground" in keyed:
            ins["ground"] = _check_ground(keyed["ground"], verb)
        return ins

    # remove / keep / accept
    if len(rest) != 1:
        raise _GrammarFailure("%s: wrong field count" % verb)
    return {"verb": verb, "handle": _check_handle(rest[0], verb)}


def _semantic_filter(instructions, known):
    """Element-level (A5) drops determinable at Stage 1A.

    Always applied (form-level semantics from design section 5.2):
    - ground=documented requires a rec: source.
    - ground=reported requires a user-role source (src=turn qualifies;
      a rec: source never does).
    Applied only when the caller supplies the knowledge:
    - known['msg_roles']: {message_id: 'user'|'voice'} — msg: ids must
      be present; ground=reported requires role 'user'.
    - known['rec_ids']: set of record ids — rec: ids must be present
      (applies to src= and basis= alike).
    Returns (kept_instructions, diagnostics).
    """
    kept = []
    diagnostics = []
    msg_roles = known.get("msg_roles") if known else None
    rec_ids = known.get("rec_ids") if known else None

    def ref_known(ref):
        if ref.startswith("msg:"):
            return msg_roles is None or ref[4:] in msg_roles
        if ref.startswith("rec:"):
            return rec_ids is None or ref[4:] in rec_ids
        return True  # turn / reply

    def ref_is_user(ref):
        if ref == "turn":
            return True
        if ref.startswith("msg:") and msg_roles is not None:
            return msg_roles.get(ref[4:]) == "user"
        return None  # unknown

    for ins in instructions:
        drop = None
        ground = ins.get("ground")
        src = ins.get("src")
        if ground == "documented" and src is not None and not src.startswith("rec:"):
            drop = "ground=documented without a rec: source"
        elif ground == "reported" and src is not None:
            is_user = ref_is_user(src)
            if src.startswith("rec:") or is_user is False:
                drop = "ground=reported whose source is not a user-role message"
        if drop is None and src is not None and not ref_known(src):
            drop = "src= reference not in the caller-supplied identifier set"
        if drop is None and ins["verb"] == "gap" and not ref_known(ins["basis"]):
            drop = "gap basis= reference not in the caller-supplied identifier set"
        if drop is not None:
            diagnostics.append("semantic_drop: %s (%s)" % (drop, ins["verb"]))
        else:
            kept.append(ins)
    return kept, diagnostics


def parse_sketch_tail(text: str, known=None) -> ParseResult:
    """Split a generation into (clean body, sketch instructions).

    The strip is total: on every outcome the returned body contains no
    delimiter line and no tail lines from a recognized tail. Grammar
    failures return the pre-delimiter body byte-identical (modulo the
    trailing-newline trim at the delimiter boundary) with zero
    instructions. With no marker events at all, the text is returned
    byte-identical (design A3).
    """
    lines = text.split("\n")
    diagnostics = []
    body_lines = []
    instructions = []
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
            # F13: a generation truncated mid-delimiter ends on a proper
            # prefix of the delimiter. Grammar failure: the partial
            # marker is bookkeeping, never body text.
            if 3 <= len(stripped) < len(DELIMITER) and DELIMITER.startswith(stripped):
                diagnostics.append("grammar_failure: partial delimiter (truncated generation)")
                return ParseResult(body_text(), [], diagnostics, "grammar_failure")
            idx = line.rfind("[[")
            if idx > 0:
                frag = line[idx:]
                if 3 <= len(frag) < len(DELIMITER) and DELIMITER.startswith(frag):
                    head = line[:idx].rstrip()
                    if head:
                        body_lines.append(head)
                    diagnostics.append(
                        "grammar_failure: partial glued delimiter (truncated generation)")
                    return ParseResult(body_text(), [], diagnostics, "grammar_failure")

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
                    if len(region) > MAX_INSTRUCTIONS:
                        raise _GrammarFailure(
                            "too many instruction lines (%d > %d)"
                            % (len(region), MAX_INSTRUCTIONS))
                    if len(tail_text) > MAX_TAIL_CHARS:
                        raise _GrammarFailure(
                            "tail over %d chars" % MAX_TAIL_CHARS)
                    parsed = [_parse_instruction(l) for l in region]
                except _GrammarFailure as exc:
                    diagnostics.append("grammar_failure: %s" % exc)
                    status = "grammar_failure"
                    return ParseResult(body_text(), [], diagnostics, status)
                kept, sem_diags = _semantic_filter(parsed, known)
                diagnostics.extend(sem_diags)
                instructions = kept
                status = "ok"
                return ParseResult(body_text(), instructions, diagnostics, status)
            # Delimiter followed by prose (F15a): strip the marker line
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
        # No marker events: byte-identical return (design A3).
        return ParseResult(text, [], diagnostics, status)
    return ParseResult(body_text(), instructions, diagnostics, status)
