"""Key-line tiers for story artifacts and quote cards (S4, F3 fix).

The governing law (audit Parts XII–XIII, ratified 2026-10-24):

- Personal artifacts DISTILL, never invent. A key line presented as the
  user's words must be a verbatim span of their material, with source.
- No synthesis in disguise. A Zenaf-written line is never a quotation.
- Adoption is not authorship of wording. Choosing among options is
  user decision-making, but the wording keeps the tier it was born with
  unless the user themselves rewrote it.

Tier vocabulary (the ONLY values a key_line_tier may take):

- ``certified`` — verbatim span of the source journal entry, mechanically
  verified (see :func:`is_verbatim_span`), stored with its source.
  The ONLY tier that may be rendered or minted as a quotation.
- ``user_authored`` — the user wrote or edited the final text. It IS
  their words, but it is NOT a verbatim entry span: it is evidence of
  what they endorse now, not of what they said in the entry. Never
  presented as a quotation *from the entry*.
- ``adopted`` — chosen by the user from Zenaf's compositions. The choice
  is recorded as user decision-making; the wording stays synthesized.
  Attributed as "chosen by the user from Zenaf's options", never quoted.
- ``dramatization`` — Zenaf invention, or a legacy line that could not
  be verified against its source. Creative material only, never quoted,
  never carrying the user's name as a quotation.

There is deliberately NO ``evidence`` tier here: story artifacts are
never evidence for mining or claims (see the citation-guard test).
A missing key line has tier ``None`` — absence is a valid outcome,
never an error to be papered over with an invented line.

Verbatim check (documented normalization — light whitespace only):

- Collapse every whitespace run to a single space and strip the ends
  (the same normalization the pipeline already uses for text hashes).
- No case folding, no punctuation changes, no fuzzy matching.
  A near-quote is not a quote. Callers must NEVER truncate a verified
  span either: a mid-sentence cut can distort meaning, and the stored
  line must be the span that was verified, not a mutation of it.
"""

from __future__ import annotations

TIER_CERTIFIED = "certified"
TIER_USER_AUTHORED = "user_authored"
TIER_ADOPTED = "adopted"
TIER_DRAMATIZATION = "dramatization"

#: Every tier a key_line_tier may take. No "evidence" value exists here
#: on purpose: story artifacts are never evidence (citation guard).
ALL_TIERS = frozenset(
    {
        TIER_CERTIFIED,
        TIER_USER_AUTHORED,
        TIER_ADOPTED,
        TIER_DRAMATIZATION,
    }
)

#: The only tier that may be rendered or minted as a quotation.
QUOTE_TIERS = frozenset({TIER_CERTIFIED})


def normalize_text(text: str) -> str:
    """Collapse whitespace runs to single spaces and strip.

    Light normalization ONLY. Case, punctuation, and wording are
    untouched: a candidate that differs in any of those is not verbatim.
    """
    return " ".join((text or "").split())


def is_verbatim_span(candidate: str, entry_text: str) -> bool:
    """True iff the candidate appears word-for-word in the entry text.

    Both sides go through :func:`normalize_text` first, so a candidate
    that differs only in whitespace still counts — anything else (a
    rewording, a tidied-up sentence, a paraphrase) does not.
    """
    cand = normalize_text(candidate)
    if not cand:
        return False
    return cand in normalize_text(entry_text)


def verified_span(candidate: str, entry_text: str) -> str | None:
    """Return the candidate's normalized form iff it is verbatim.

    Returns ``None`` for anything else — including near-quotes. The
    normalized form is what gets stored: it matches the entry modulo
    whitespace, which is the only difference the check permits.
    """
    if not is_verbatim_span(candidate, entry_text):
        return None
    return normalize_text(candidate)
