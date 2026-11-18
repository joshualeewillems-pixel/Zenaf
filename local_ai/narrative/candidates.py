"""Steward D1: candidate-mention capture (packet Rev 1 §§5/8/10).

Recognition is not identification. This module notices that a
name-shaped form recurs in the visitor's own words and records
that recurrence — a candidate mention — in the narrative store.
It never decides who anyone is: no model call, no NER library,
no coreference, no variant folding, no registry lookup (capture
must not consult the ownerless VE persons list, packet §2.2).
Deterministic rules only (founder ruling Q9), precision over
recall as a stated value: a missed mention costs nothing (the
name can recur); a false candidate spends the visitor's trust.

FIRST SCOPE IS CAPTURE-ONLY (packet §11/§15.6): this module
writes candidates, sightings, and capture membership links. It
builds no ask, no delivery, no correction surface, and no
promotion — those are ruled-but-dormant design. Candidates feed
nothing: no seat context, no generation prompt, no strand
weighting, no thread subject key (packet §11 non-goals).

When capture runs (all conditions, fail-closed):

- the rollback switch is on (``ZENAF_CANDIDATE_CAPTURE``, the
  Slice A switch idiom; off ⇒ derivation behaves exactly as it
  did before D1 and retained candidates stay readable/erasable);
- the event is a ``conversation_turn`` whose entity is the
  conversation (Q7: user-authored conversation turns only), with
  non-empty ``evidence_text`` — the turn event's user
  contribution, the same evidence text derivation consumes. Seat
  text is never in a turn event's evidence (the conversation
  service emits the user's message only), so seat echoes and the
  future ask's own words cannot mint sightings (test T10);
- the batch's consent gate was open (the drivers check it before
  calling; capture has no consent-independent state — packet
  §8.1's deliberate contrast with Slice A's snapshot);
- the Q3 disclosure is the standing consent text FOR THIS USER:
  ``consent.candidate_capture_disclosed`` requires the derivation
  flag AND a consent recorded under the disclosure's consent
  version. A consent given under the pre-disclosure wording is
  not read as covering name retention — no grandfathering
  (packet §§8.1/15.5);
- D2's barrier discipline holds (packet §8.2 point 2): the
  drivers pass the event's admitted manifest entry when an
  erasure boundary stands; an ineligible event never reaches
  this module, and a barrier hold stops the whole pass upstream.

THE RULE FAMILY, enumerated exactly (packet §5.2: the Gate B
enumeration, fixture-pinned in both directions by
tests/test_steward_d1_candidates.py):

R1 Tokenize into word tokens: maximal runs of Unicode letters
   allowing internal apostrophes/hyphens between letter groups
   ("Ana's", "Mary-Jane", "O'Brien" are single tokens). Track
   sentence boundaries (``. ! ? …`` and newlines): a token is
   sentence-initial when it is the first token of the text or
   the gap since the previous token contains a boundary.
R2 A token is NAME-CAPITALIZED when its first letter is
   uppercase, it is not all-uppercase (acronyms and shouting are
   not names), and it is not the pronoun "I".
R3 A span is a maximal run of name-capitalized tokens joined by
   space-only gaps, where a lowercase particle (PARTICLES) may
   appear between two name-capitalized tokens and is included
   ("Ludwig van Beethoven"). Commas and boundaries break spans.
R4 Sentence-initial discount: capitalization explained by
   position alone is not evidence. A span beginning at a
   sentence-initial token first sheds leading SENTENCE_STARTERS
   tokens (never part of a name at a sentence start in this
   grammar); what remains is judged on its own shape — two or
   more name-capitalized tokens are a span, a lone token falls
   to R5's frames. A non-starter sentence-initial span of two
   or more tokens is kept whole: the non-initial capitals are
   the evidence ("Ana Ruiz called." captures "Ana Ruiz"; "Ana
   called." captures nothing).
R5 Single tokens qualify ONLY through a frame, exhaustively:
   (a) possessive — the token ends in 's or ’s; the captured
       form is the token without the suffix ("Ana's" → "Ana");
   (b) relational — the token immediately follows the word
       "my"/"My" ("my Ana", "My Ana is here");
   (c) self-evidencing compound — the token itself contains
       two or more capitalized parts ("Mary-Jane", "O'Brien").
   A trailing possessive is likewise stripped from a multi-
   token span's final token ("Ana Ruiz's" → "Ana Ruiz").
R6 Exclusions, applied to the captured normalized form before
   accumulation: the seven seats' role names and personal names
   and the visitor's own names (deployment constants below —
   constants, not inferences); single-token forms that are
   calendar words (weekdays, months, their abbreviations —
   "May" the person is a documented loss); multi-token spans
   whose first or final token is a generic geographic noun
   (GEOGRAPHIC_NOUNS: "Fort Worth", "Main Street").
R7 One mention per event per form: repeated occurrences inside
   one turn are emphasis, not recurrence (packet §5.1). The
   first occurrence's surface form wins.
R8 Normalization is casefold + whitespace collapse ONLY
   (packet §3.1). The surface form stored is the captured name
   form as written (frame punctuation stripped per R5 — the
   possessive suffix is the frame's punctuation, not part of
   the name, and the accumulation key must be built from the
   name itself).

Known losses, accepted by design (precision over recall):
nicknames, pronouns, lowercase mentions, most single-name
references, sentence-initial single names without a frame,
calendar-word names, inverted "Ruiz, Ana" forms.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable

from . import consent

logger = logging.getLogger(__name__)


def candidate_capture_enabled() -> bool:
    """Rollback switch for D1 capture (packet §13, Slice A idiom).

    An explicit ``ZENAF_CANDIDATE_CAPTURE`` value wins ("1"/"true"/
    "yes"/"on" = on; anything else = off); otherwise capture is ON.
    Off ⇒ no new sightings or candidates; derivation behavior
    returns to exactly its pre-D1 shape. Read per call so tests
    can flip it with ``monkeypatch.setenv``.
    """
    raw = os.environ.get("ZENAF_CANDIDATE_CAPTURE")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return True


# -- deployment constants (packet §5.2: constants, not inferences) ----------

#: The seven seats' role names (the council archetypes'
#: display names and ids are the same words).
SEAT_ROLE_NAMES: frozenset[str] = frozenset(
    {
        "mentor",
        "champion",
        "guardian",
        "maverick",
        "ambassador",
        "conductor",
        "skeptic",
    }
)

#: The seven seats' personal names, as settled in the adopted
#: character record. They are NOT enumerable from code at this
#: base (no constant in the backend names them), so they are
#: stated here as the deployment constants the packet specifies.
SEAT_PERSONAL_NAMES: frozenset[str] = frozenset(
    {"rumi", "valen", "maeve", "lucian", "aria", "severine", "jynx"}
)

#: The visitor's own names / forms of address. No machine-
#: readable source for the visitor's name exists in the backend
#: at this base (the owner record carries an id, not a name), so
#: the deployment constant ships empty: the exclusion mechanism
#: is live, and a deployment that knows its visitor's names
#: populates it here. Stated plainly rather than faked from data
#: the system does not hold.
USER_OWN_NAMES: frozenset[str] = frozenset()

#: Forms that never accumulate, matched against the captured
#: normalized form (R6).
EXCLUDED_FORMS: frozenset[str] = (
    SEAT_ROLE_NAMES | SEAT_PERSONAL_NAMES | USER_OWN_NAMES
)

#: Lowercase particles allowed inside a span (R3).
PARTICLES: frozenset[str] = frozenset(
    {
        "al", "bin", "da", "das", "de", "del", "den", "der", "di",
        "dos", "du", "ibn", "la", "le", "ten", "ter", "van", "von",
    }
)

#: Sentence-starter words shed from a sentence-initial span (R4).
SENTENCE_STARTERS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "this", "that", "it", "he", "she", "they",
        "we", "but", "and", "so", "then", "now", "here", "there",
        "when", "while", "after", "before", "in", "on", "at", "for",
        "with", "as", "if", "yes", "no", "well", "oh",
        "yesterday", "today", "tomorrow", "tonight", "meanwhile",
        "however", "also", "still", "later", "soon", "finally",
        "actually", "once", "again",
    }
)

#: Calendar vocabulary (R6): weekdays, months, abbreviations.
CALENDAR_WORDS: frozenset[str] = frozenset(
    {
        "monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday", "mon", "tue", "tues", "wed", "thu",
        "thur", "thurs", "fri", "sat", "sun",
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november",
        "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug",
        "sep", "sept", "oct", "nov", "dec",
    }
)

#: Generic geographic nouns (R6): a multi-token span ending in
#: one of these is a place phrase in this grammar, not a name.
GEOGRAPHIC_NOUNS: frozenset[str] = frozenset(
    {
        "street", "avenue", "boulevard", "road", "city", "county",
        "state", "park", "river", "lake", "mount", "fort", "beach",
        "bridge", "island", "valley", "bay",
    }
)

_TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*")
_BOUNDARY_RE = re.compile(r"[.!?…\n]")
_POSSESSIVE_RE = re.compile(r"^(.+?)['’]s$")


def normalize_form(surface: str) -> str:
    """The accumulation key (packet §3.1): casefold + whitespace
    collapse only. No stemming, no honorific stripping, no
    initial expansion — each of those is an interpretation."""
    return " ".join(str(surface).split()).casefold()


class _Token:
    __slots__ = ("text", "sentence_initial", "joinable")

    def __init__(self, text: str, sentence_initial: bool, joinable: bool) -> None:
        self.text = text
        self.sentence_initial = sentence_initial
        #: The gap before this token is spaces/tabs only — a span
        #: may extend across it (R3). A comma, quote, boundary, or
        #: any other mark breaks a span.
        self.joinable = joinable


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    prev_end = 0
    for match in _TOKEN_RE.finditer(text):
        gap = text[prev_end:match.start()]
        initial = not tokens or bool(_BOUNDARY_RE.search(gap))
        joinable = bool(tokens) and gap.strip(" \t") == ""
        tokens.append(_Token(match.group(0), initial, joinable))
        prev_end = match.end()
    return tokens


def _is_name_capitalized(token: str) -> bool:
    if not token or not token[0].isupper():
        return False
    if token == "I":
        return False
    letters = [c for c in token if c.isalpha()]
    if len(letters) >= 2 and all(c.isupper() for c in letters):
        return False  # all-caps: acronym or emphasis, not a name
    return True


def _capitalized_parts(token: str) -> int:
    parts = re.split(r"['’\-]", token)
    return sum(1 for p in parts if p and p[0].isupper())


def _strip_possessive(token: str) -> str | None:
    """The token without a trailing possessive suffix, or None
    when the token is not possessive-shaped (R5a)."""
    match = _POSSESSIVE_RE.match(token)
    if match is None:
        return None
    return match.group(1)


def extract_candidate_forms(text: str) -> list[tuple[str, str]]:
    """Propose (surface_form, normalized_form) pairs from one
    user-authored turn text, per the rule family in this module's
    header (R1–R8). Deterministic; no model, no registry, no
    state. Deduped by normalized form (R7), first surface wins,
    in order of first appearance."""
    tokens = _tokenize(text or "")
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _offer(surface: str) -> None:
        surface = " ".join(surface.split())
        if not surface:
            return
        normalized = normalize_form(surface)
        if normalized in EXCLUDED_FORMS or normalized in seen:
            return
        seen.add(normalized)
        found.append((surface, normalized))

    def _offer_single(token: str, *, prev_word: str | None) -> None:
        """R5: a lone name-capitalized token qualifies only
        through a frame (possessive / 'my' / compound)."""
        base = _strip_possessive(token)
        if base is not None and _is_name_capitalized(base):
            if normalize_form(base) not in CALENDAR_WORDS:
                _offer(base)
            return
        if prev_word is not None and prev_word.casefold() == "my":
            if normalize_form(token) not in CALENDAR_WORDS:
                _offer(token)
            return
        if _capitalized_parts(token) >= 2:
            _offer(token)

    def _offer_span(span: list[_Token]) -> None:
        """A multi-token span (R3/R4): join as written, strip a
        trailing possessive from the final token (R5), apply the
        geographic exclusion (R6)."""
        texts = [t.text for t in span]
        base = _strip_possessive(texts[-1])
        if base is not None:
            texts[-1] = base
        # Geographic nouns bind from either edge in English place
        # phrases: "Fort Worth", "Lake Tahoe" (prefix) and "Main
        # Street", "Salt Lake City" (suffix).
        if (
            normalize_form(texts[0]) in GEOGRAPHIC_NOUNS
            or normalize_form(texts[-1]) in GEOGRAPHIC_NOUNS
        ):
            return
        _offer(" ".join(texts))

    i = 0
    n = len(tokens)
    while i < n:
        token = tokens[i]
        if not _is_name_capitalized(token.text):
            i += 1
            continue
        # Build the maximal span starting here (R3): extension
        # requires a space-only gap — a boundary, comma, or any
        # other mark ends the span.
        span = [token]
        j = i
        while j + 1 < n:
            nxt = tokens[j + 1]
            if not nxt.joinable:
                break
            if _is_name_capitalized(nxt.text):
                span.append(nxt)
                j += 1
                continue
            if (
                nxt.text.casefold() in PARTICLES
                and j + 2 < n
                and tokens[j + 2].joinable
                and _is_name_capitalized(tokens[j + 2].text)
            ):
                span.append(nxt)
                span.append(tokens[j + 2])
                j += 2
                continue
            break
        name_tokens = [t for t in span if _is_name_capitalized(t.text)]
        if len(name_tokens) >= 2 and span[0].text.casefold() == "my":
            # "My" is a determiner, never part of the name it
            # introduces ("My Ana is here" — the name is Ana).
            span = span[1:]
            name_tokens = name_tokens[1:]
            if len(name_tokens) == 1:
                _offer_single(name_tokens[0].text, prev_word="my")
                i = j + 1
                continue
        if token.sentence_initial:
            # R4: shed leading sentence starters; judge the rest
            # on its own shape.
            rest = list(span)
            while (
                len(rest) > 1
                and rest[0].text.casefold() in SENTENCE_STARTERS
            ):
                rest.pop(0)
            rest_names = [t for t in rest if _is_name_capitalized(t.text)]
            if len(rest_names) >= 2:
                _offer_span(rest)
            elif len(rest_names) == 1:
                prev = tokens[i - 1].text if i > 0 else None
                _offer_single(rest_names[0].text, prev_word=prev)
            # A span reduced to nothing name-shaped: no evidence.
        elif len(name_tokens) >= 2:
            _offer_span(span)
        else:
            prev = tokens[i - 1].text if i > 0 else None
            _offer_single(token.text, prev_word=prev)
        i = j + 1
    return found


def capture_event_mentions(
    store: Any,
    event: Any,
    *,
    admitted_sources: Any = None,
    disclosed_reader: Callable[[str], bool] | None = None,
) -> dict[str, int] | None:
    """Capture one event's mentions into the store (packet §5.2).

    Called by both batch drivers (the live pipeline's per-event
    path and the sweep's batch loop) AFTER the batch's consent
    gate and the D2 eligibility evaluation: ``admitted_sources``
    is the event's manifest entry when an erasure boundary
    stands, None when none does. Capture never consults
    derivation's admission outcome — a fully declined batch
    yields the same sightings as a fully admitted one (T14).

    Returns the store's capture report, or None when the event
    is not capture-eligible (switch off, wrong kind, no user
    words, disclosure not standing for this user). Store refusals
    (the erasure barrier) propagate to the driver's own guarded
    handling, exactly as other funnel refusals do.
    """
    if not candidate_capture_enabled():
        return None
    if getattr(event, "kind", "") != "conversation_turn":
        return None
    if (getattr(event, "entity_type", "") or "") != "conversation":
        return None
    text = getattr(event, "evidence_text", "") or ""
    if not text.strip():
        return None
    user_id = getattr(event, "user_id", "") or ""
    event_id = getattr(event, "id", "") or ""
    if not user_id or not event_id:
        return None
    reader = disclosed_reader or consent.candidate_capture_disclosed
    try:
        if not reader(user_id):
            return None
    except Exception:
        logger.exception(
            "narrative: candidate disclosure read failed for user "
            "%r; failing closed",
            user_id,
        )
        return None
    forms = extract_candidate_forms(text)
    if not forms:
        return None
    sightings = [
        {
            "ref_kind": "event",
            "ref_id": event_id,
            "normalized_form": normalized,
            "surface_form": surface,
            "conversation_id": getattr(event, "entity_id", "") or "",
            "seen_at": getattr(event, "created_at", "") or "",
        }
        for surface, normalized in forms
    ]
    return store.capture_sightings(
        user_id, sightings, admitted_sources=admitted_sources
    )


__all__ = [
    "CALENDAR_WORDS",
    "EXCLUDED_FORMS",
    "GEOGRAPHIC_NOUNS",
    "PARTICLES",
    "SENTENCE_STARTERS",
    "candidate_capture_enabled",
    "capture_event_mentions",
    "extract_candidate_forms",
    "normalize_form",
]
