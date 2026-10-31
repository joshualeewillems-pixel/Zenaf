"""Declaration blocks at generation time (Increment A, accepted schema
contract §1.2/§2/§7, Joshua 2026-10-30).

Pure stdlib; no imports from meeting.py, so this module cannot mutate
the record it reads. It answers one question per response/revision
contribution: what did this model explicitly declare about its own
claims' targets — as emitted, not as inferred from its prose?

Design rules (contract + plan Rev 2, verdict 2026-10-30):

- Declared != inferred. Only an explicit model-emitted declaration
  block counts as declared. The engine's existing prose-parsed links
  keep running as fallback for claims WITHOUT a native declaration
  outcome, with their pre-existing adapter provenance; they are never
  relabeled declared for a claim that carries a native outcome.
- Block format (versioned, separate from prose). Response/revision
  prompts ask models to END their contribution with::

      Declarations (declaration-block-v1):
      1: extends C12, challenges C18, integrates C24
      2: none

  One entry per claim, keyed by the claim's ordinal position in the
  contribution (1st numbered claim -> entry 1). One entry may carry
  several {target, kind} pairs, so one claim may extend C12, challenge
  C18, and integrate C24 in the same block. Kind vocabulary is the
  contract §1.2 vocabulary; ``other`` may carry a free-text note in
  parentheses (``other C5 (note: ...)``). ``none`` is an explicit
  no-target declaration for that claim.
- Both representations preserved, always: the original emitted block
  verbatim (``declaration_raw`` on every claim of the contribution)
  AND the parsed declarations (layer ``declared``). Parsed output
  never overwrites raw input.
- Three outcomes, never conflated (per claim):
    valid entries -> ``populated`` (or ``declared-none`` for an
      explicit ``none`` entry, author-set, zero records). A claim
      whose entries carry ONLY out-of-vocabulary kinds is
      ``unknown`` + malformed-reason with those declarations kept:
      the E4 they earn is the error, and ``populated`` would
      wrongly add an E6 (zero valid declarations);
    no block at all -> ``unknown`` + reason "no declaration emitted";
    structurally malformed block -> ``unknown`` + reason "malformed
      declaration block" + raw block preserved + a parse-failure
      record + a validation error (E4 if a kind is present but
      invalid, else E6 — see the validator rule in
      ``transjective_record``). The distinction survives in reason +
      raw + failure record + error, NOT in a fifth target-state:
      the contract has exactly four states.
- The parser NEVER manufactures declarations and NEVER "fixes" a
  malformed block. Structural failures are fail-closed and atomic:
  if any entry line is unparseable, duplicated, out of range, or
  self-contradictory (``none`` + targets for one ordinal, or two
  different kinds for one target), the WHOLE block is malformed —
  ordinal alignment cannot be trusted once the model mis-numbers,
  so no entry from such a block is kept. The single exception is
  kind vocabulary: a structurally well-formed entry naming a kind
  outside the vocabulary is preserved verbatim as a declaration, so
  the validator fires E4 on it genuinely, instead of the parser
  silently dropping authored content. Identical (claim, target,
  kind) triples deduplicate silently: repetition is not ambiguity.
- A header-only block (valid header, zero entry lines) is an
  explicitly empty block, NOT malformed: every claim in the
  contribution is ``declared-none`` (author-set, zero records).
- A claim with no entry line in an otherwise valid block is
  ``unknown`` + reason "no declaration entry for this claim" — the
  block is fine, the author simply did not declare for that claim.
  That reason, the raw block, and the absence of a failure record
  distinguish it from both absent and malformed.
- Only the exact versioned header counts as a block. An unversioned
  "Declarations:" section is prose, not a declaration block: the
  version is the contract, and an unversioned block is not a block
  under this version.
- The block must be the contribution's final section. Extraction
  takes the LAST versioned-header line as the block start; prose
  before it is the claim text. Block lines never become claim spans
  and never count as citations: the runner strips the block before
  span analysis, while the transcript keeps the full verbatim text.
"""

from __future__ import annotations

import re

__all__ = [
    "DECLARATION_BLOCK_VERSION",
    "extract_declaration_block",
    "parse_declaration_block",
]

DECLARATION_BLOCK_VERSION = "declaration-block-v1"

# Exact versioned header line (trailing whitespace tolerated).
_HEADER_RE = re.compile(
    r"^Declarations \(declaration-block-v1\):\s*$"
)

# One entry line: ordinal, colon, body. Body is "none" or a
# comma-separated list of kind-target items.
_ENTRY_RE = re.compile(r"^(\d+):\s*(.+?)\s*$")

# One kind-target item: kind, claim id, optional (note: ...) for other.
# The kind group deliberately accepts any word: vocabulary membership
# is checked by the caller, so an out-of-vocabulary kind survives as
# a declaration (validator E4) instead of being dropped by the parser.
_ITEM_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9_-]*)\s+C(\d+)"
    r"(?:\s*\(note:\s*(.*)\))?\s*$"
)

KIND_VOCABULARY = (
    "extends",
    "corrects",
    "challenges",
    "integrates",
    "endorses",
    "repeats",
    "defends",
    "requests-evidence",
    "other",
)

REASON_ABSENT = "no declaration emitted"
REASON_MALFORMED = "malformed declaration block"
REASON_NO_ENTRY = "no declaration entry for this claim"


def extract_declaration_block(text: str) -> tuple[str, str | None]:
    """Split a contribution into (prose, declaration block or None).

    The block starts at the LAST line matching the exact versioned
    header and runs to the end of the text (trailing blank lines
    stripped from the block, not from the prose). No header line ->
    (full text, None). The prose is returned unchanged apart from
    the removed block; the block is returned verbatim (header +
    entry lines, single newlines, no trailing blank line).
    """
    lines = (text or "").split("\n")
    header_idx: int | None = None
    for i, line in enumerate(lines):
        if _HEADER_RE.match(line.strip()):
            header_idx = i
    if header_idx is None:
        return text or "", None
    prose = "\n".join(lines[:header_idx]).rstrip("\n")
    block_lines = lines[header_idx:]
    while block_lines and block_lines[-1].strip() == "":
        block_lines.pop()
    return prose, "\n".join(block_lines)


def parse_declaration_block(
    block: str | None, n_claims: int
) -> list[dict]:
    """Parse a declaration block into one outcome per claim ordinal.

    ``n_claims`` is the number of registered claims in the
    contribution; outcomes are aligned 1..n in span order. Each
    outcome carries ``target_state``, ``target_state_set_by``,
    ``uncertainty_reason``, ``declarations`` (list of
    {target_claim, kind, layer, note} or None), and
    ``declaration_parse_failure`` (dict or None). ``block`` None
    means absent: every claim is unknown + REASON_ABSENT.

    Structural malformation is atomic (see module docstring): any
    structural failure makes every claim unknown + REASON_MALFORMED
    with the failure record and no kept declarations. Invalid kinds
    are NOT structural failures: they are preserved as declarations
    so the validator fires E4.
    """
    if n_claims <= 0:
        return []
    if block is None:
        return [
            {
                "target_state": "unknown",
                "target_state_set_by": "system",
                "uncertainty_reason": REASON_ABSENT,
                "declarations": None,
                "declaration_parse_failure": None,
            }
            for _ in range(n_claims)
        ]

    raw = block
    lines = block.split("\n")
    entry_lines = [ln for ln in lines[1:] if ln.strip() != ""]
    if not entry_lines:
        # Explicitly empty block: author-set declared-none for all.
        return [
            {
                "target_state": "declared-none",
                "target_state_set_by": "author",
                "uncertainty_reason": None,
                "declarations": [],
                "declaration_parse_failure": None,
            }
            for _ in range(n_claims)
        ]

    failures: list[str] = []
    # ordinal -> {"none": bool, "declarations": [...], "kinds_by_target": {...}}
    per_ordinal: dict[int, dict] = {}

    def fail(detail: str) -> None:
        failures.append(detail)

    seen_ordinals: set[int] = set()
    for line in entry_lines:
        stripped = line.strip()
        m = _ENTRY_RE.match(stripped)
        if m is None:
            fail(f"unparseable entry line: {stripped[:80]!r}")
            continue
        ordinal = int(m.group(1))
        body = m.group(2).strip()
        if ordinal in seen_ordinals:
            fail(f"duplicate entry for claim ordinal {ordinal}")
            continue
        seen_ordinals.add(ordinal)
        if ordinal < 1 or ordinal > n_claims:
            fail(f"entry ordinal out of range: {ordinal} "
                 f"(contribution has {n_claims} claims)")
            continue
        slot = per_ordinal.setdefault(
            ordinal, {"none": False, "declarations": [],
                      "kinds_by_target": {}})
        if body.lower() == "none":
            if slot["declarations"]:
                fail(f"claim ordinal {ordinal} declares both none and targets")
            slot["none"] = True
            continue
        if slot["none"]:
            fail(f"claim ordinal {ordinal} declares both none and targets")
            continue
        for raw_item in body.split(","):
            item = raw_item.strip()
            if not item:
                fail(f"empty item in entry for claim ordinal {ordinal}")
                continue
            im = _ITEM_RE.match(item)
            if im is None:
                fail(f"unparseable item for claim ordinal {ordinal}: "
                     f"{item[:80]!r}")
                continue
            kind, target = im.group(1), f"C{im.group(2)}"
            note = im.group(3) if im.group(3) is not None else None
            prev = slot["kinds_by_target"].get(target)
            if prev is not None and prev != kind:
                fail(f"claim ordinal {ordinal} gives two kinds for {target}: "
                     f"{prev!r} and {kind!r}")
                continue
            if prev == kind:
                continue  # identical repetition deduplicates silently
            slot["kinds_by_target"][target] = kind
            slot["declarations"].append(
                {
                    "target_claim": target,
                    "kind": kind,
                    "layer": "declared",
                    "note": note,
                }
            )

    if failures:
        failure_record = {
            "reason": REASON_MALFORMED,
            "failures": failures,
        }
        return [
            {
                "target_state": "unknown",
                "target_state_set_by": "system",
                "uncertainty_reason": REASON_MALFORMED,
                "declarations": None,
                "declaration_parse_failure": dict(failure_record),
            }
            for _ in range(n_claims)
        ]

    outcomes: list[dict] = []
    for ordinal in range(1, n_claims + 1):
        slot = per_ordinal.get(ordinal)
        if slot is None:
            outcomes.append(
                {
                    "target_state": "unknown",
                    "target_state_set_by": "system",
                    "uncertainty_reason": REASON_NO_ENTRY,
                    "declarations": None,
                    "declaration_parse_failure": None,
                }
            )
        elif slot["none"]:
            outcomes.append(
                {
                    "target_state": "declared-none",
                    "target_state_set_by": "author",
                    "uncertainty_reason": None,
                    "declarations": [],
                    "declaration_parse_failure": None,
                }
            )
        else:
            decls = list(slot["declarations"])
            # A claim whose ONLY declarations carry out-of-vocabulary
            # kinds is unknown + malformed-reason, NOT populated:
            # populated with zero valid declarations would fire E6
            # alongside the E4 the invalid kinds already earn, and
            # the plan's mapping is E4 *else* E6. The invalid-kind
            # declarations are kept (E4 fires on them); no failure
            # record is attached, so the parse-failure E6 rule does
            # not fire either. Mixed valid + invalid stays populated
            # (E4 only: >= 1 valid declaration satisfies E6).
            valid = [d for d in decls if d["kind"] in KIND_VOCABULARY]
            if valid:
                outcomes.append(
                    {
                        "target_state": "populated",
                        "target_state_set_by": "system",
                        "uncertainty_reason": None,
                        "declarations": decls,
                        "declaration_parse_failure": None,
                    }
                )
            else:
                outcomes.append(
                    {
                        "target_state": "unknown",
                        "target_state_set_by": "system",
                        "uncertainty_reason": REASON_MALFORMED,
                        "declarations": decls,
                        "declaration_parse_failure": None,
                    }
                )
    return outcomes
