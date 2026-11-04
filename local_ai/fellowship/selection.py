"""Capability C S2 — exchange-level selection contract (deterministic).

The verdict's core correction, stated as code: selection judges
CONTRIBUTIONS from COMPLETED EXCHANGES, it does not rank
keyword-derived observations. Candidacy (which seats might have
something relevant) and selection (whether any contribution is
genuinely useful, distinct, and timely enough to justify interrupting
the conversation) are separate functions, and selection may return
zero even when several candidates exist.

What this module IS: the contract for one bounded exchange-level
selection decision, plus a fail-closed validator for the judge's
structured output. The judge itself (S3) is NOT here — no model calls,
no provider, no prompt, no cost or latency decisions. Nothing in this
module imports the per-candidate observation pipeline
(derivation/observations/attention): the verdict forbids reusing that
pipeline as a mandatory prerequisite, and this contract must be
testable without it.

Input — a completed exchange (verdict §2), evaluated AFTER the
responding seat has spoken:
  user_message    verbatim user turn
  responding_seat archetype_id of the seat that replied
  assistant_reply verbatim assistant reply
  context         limited relevant context: prior turns as
                  {"role", "speaker" (archetype_id or None), "text"}
  candidate_seats jurisdiction info the judge was given (optional;
                  when present, selections are restricted to it)

Output — 0, 1, or 2 invitations, each with a seat and a short,
evidence-grounded reason. The judge generates NO seat dialogue; it
selects invitations and supplies reasons.

Validation FAILS CLOSED: any violation — malformed output, duplicate
seats, unknown seat, the responding seat selecting itself, a
selection outside the candidate set, an empty or over-long reason, or
an evidence quote that does not appear verbatim in the cited part of
the exchange — rejects the ENTIRE output (zero invitations), never a
partial or truncated guess. A legitimate zero (empty selections) is
valid and ordinary.

Deliberate boundaries of what deterministic validation CANNOT check:
  - Whether a reason is semantically TRUE or wise. The contract checks
    structure + verbatim evidence grounding; the judge prompt (S3)
    owns framing the reason as a reading, and the join surface (S5)
    owns rendering it labeled as such (verdict Q5: interpretation is
    never presented as fact).
  - Whether a contribution is "distinct" in meaning. Two selections
    with different keywords but the same intervention are a judge
    error the contract cannot detect; the verdict's rejection of
    keyword-overlap suppression as the final diversity criterion (Q6)
    is honored by NOT pretending overlap checks settle diversity.
    Distinctness is the judge's judgment, bounded by the cap of 2.
  - Extra keys in the judge output are ignored (forward-compatible),
    not violations: malformed means structurally unusable, not merely
    unfamiliar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from local_ai.council.archetypes import get_archetype

#: Maximum invitations per exchange (verdict Q6). Over-cap output
#: fails closed entirely — it is never truncated to two.
SELECTION_MAX = 2

#: A selection reason is short by contract. Longer reasons are a
#: judge-prompt violation, rejected here rather than silently kept.
REASON_MAX_CHARS = 500

#: Parts of the exchange an evidence quote may cite. "context" quotes
#: must appear verbatim in ONE context entry's text, not assembled
#: across entries.
EVIDENCE_PARTS = ("user_message", "assistant_reply", "context")


@dataclass(frozen=True)
class CandidateSeat:
    """Jurisdiction info given to the judge for one candidate seat.

    The jurisdiction text is judge INPUT, not validator-checked: the
    validator checks seat membership in the candidate set, never the
    content of the jurisdiction summary.
    """

    seat: str
    jurisdiction: str = ""


@dataclass(frozen=True)
class CompletedExchange:
    """The unit of evaluation: one completed exchange, verbatim."""

    user_message: str
    responding_seat: str
    assistant_reply: str
    context: tuple[dict[str, Any], ...] = ()
    candidate_seats: tuple[CandidateSeat, ...] = ()


@dataclass(frozen=True)
class ValidatedInvitation:
    """One validated selection: seat + reason + its evidence anchor."""

    seat: str
    reason: str
    evidence_part: str
    evidence_quote: str


@dataclass(frozen=True)
class SelectionResult:
    """Outcome of validating one judge output.

    valid=False ALWAYS carries invitations=() (fail closed) and at
    least one violation. valid=True carries 0, 1, or 2 invitations;
    zero is legitimate and ordinary.
    """

    valid: bool
    invitations: tuple[ValidatedInvitation, ...] = ()
    violations: tuple[str, ...] = ()


def _quote_in_exchange(
    exchange: CompletedExchange, part: str, quote: str
) -> bool:
    """Verbatim substring check: the quote must occur in the cited part."""
    if part == "user_message":
        return quote in (exchange.user_message or "")
    if part == "assistant_reply":
        return quote in (exchange.assistant_reply or "")
    for entry in exchange.context:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text", "")
        if isinstance(text, str) and quote in text:
            return True
    return False


def validate_selection(
    exchange: CompletedExchange, raw_output: Any
) -> SelectionResult:
    """Validate one judge output against one completed exchange.

    Pure and deterministic: no model calls, no store reads, no pipeline
    dependency. Any violation fails the whole output closed.
    """
    violations: list[str] = []

    # -- exchange sanity (a degenerate exchange cannot ground anything)
    if not isinstance(exchange, CompletedExchange):
        return SelectionResult(
            valid=False, violations=("exchange must be a CompletedExchange",)
        )
    responding = (exchange.responding_seat or "").strip().lower()
    if get_archetype(responding) is None:
        violations.append(f"responding seat is unknown: {exchange.responding_seat!r}")
    if not isinstance(exchange.user_message, str) or not exchange.user_message.strip():
        violations.append("exchange user_message must be non-empty")
    if not isinstance(exchange.assistant_reply, str) or not exchange.assistant_reply.strip():
        violations.append("exchange assistant_reply must be non-empty")
    if violations:
        return SelectionResult(valid=False, violations=tuple(violations))

    candidate_ids = {
        (c.seat or "").strip().lower() for c in exchange.candidate_seats
    }

    # -- output shape
    if not isinstance(raw_output, dict):
        return SelectionResult(
            valid=False, violations=("selection output must be an object",)
        )
    selections = raw_output.get("selections")
    if not isinstance(selections, list):
        return SelectionResult(
            valid=False, violations=("selection output must carry a 'selections' list",)
        )
    if len(selections) > SELECTION_MAX:
        violations.append(
            f"at most {SELECTION_MAX} selections, got {len(selections)}"
        )

    invitations: list[ValidatedInvitation] = []
    seen: set[str] = set()
    for index, selection in enumerate(selections):
        where = f"selection {index}"
        if not isinstance(selection, dict):
            violations.append(f"{where} must be an object")
            continue
        ok = True
        seat = str(selection.get("seat") or "").strip().lower()
        if not seat or get_archetype(seat) is None:
            violations.append(f"{where} has an unknown seat: {selection.get('seat')!r}")
            ok = False
        elif seat == responding:
            violations.append(f"{where} selects the responding seat itself: {seat!r}")
            ok = False
        elif seat in seen:
            violations.append(f"{where} duplicates seat: {seat!r}")
            ok = False
        elif candidate_ids and seat not in candidate_ids:
            violations.append(f"{where} seat was not a candidate: {seat!r}")
            ok = False
        else:
            seen.add(seat)
        reason = selection.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            violations.append(f"{where} reason must be a non-empty string")
            ok = False
        elif len(reason) > REASON_MAX_CHARS:
            violations.append(
                f"{where} reason exceeds {REASON_MAX_CHARS} characters"
            )
            ok = False
        evidence = selection.get("evidence")
        part = evidence.get("part") if isinstance(evidence, dict) else None
        quote = evidence.get("quote") if isinstance(evidence, dict) else None
        if not isinstance(evidence, dict):
            violations.append(f"{where} evidence must be an object")
            ok = False
        elif part not in EVIDENCE_PARTS:
            violations.append(f"{where} evidence part is unknown: {part!r}")
            ok = False
        elif not isinstance(quote, str) or not quote.strip():
            violations.append(f"{where} evidence quote must be a non-empty string")
            ok = False
        elif not _quote_in_exchange(exchange, part, quote.strip()):
            violations.append(
                f"{where} evidence quote not found verbatim in {part!r}"
            )
            ok = False
        if ok:
            invitations.append(
                ValidatedInvitation(
                    seat=seat,
                    reason=reason.strip(),
                    evidence_part=part,
                    evidence_quote=quote.strip(),
                )
            )

    if violations:
        # Fail closed: a violated output yields NO invitations, even
        # if some selections were individually fine.
        return SelectionResult(valid=False, violations=tuple(violations))
    return SelectionResult(valid=True, invitations=tuple(invitations))
