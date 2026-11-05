"""Decline levels (rev2 C2, as corrected).

Three distinct instructions, behaviorally distinct — never collapsed:

- "NOT NOW" — defer this question / this moment. The topic stays open.
  Weaver may ask a genuinely NEW question about it later, but must NOT
  repeat the declined question itself.
- "NOT THAT QUESTION" — that specific question is closed. The topic
  stays open for new questions. The closed question is never re-asked
  in any phrasing.
- "NEVER ASK ME ABOUT THIS" — an EXPLICIT TOPIC BOUNDARY. The topic is
  closed until the user reopens it. This is the ONLY level that
  prohibits future questions on the topic, and it requires the user's
  explicit boundary-setting words — never inferred from an ordinary
  decline.

Ordinary declines ("not now", "not that question") require no
permanent record beyond thread history; they must never be recorded as
topic prohibitions. Only this module's recognizer may create a topic
boundary from a user message, and it fires ONLY on explicit
boundary-setting words.

The verdict's example is normative: "Not feeling that question right
now" about a favorite song, followed six months later by a natural
return to music, must NOT prohibit a genuinely new question about
music. That sentence matches NO pattern here.
"""

from __future__ import annotations

import re

# Explicit boundary-setting phrases. Each pattern captures the topic
# after the boundary words. The phrasing must contain an explicit
# never/don't + ask/bring-up/mention + about/up — a bare "no", "not
# now", "skip this", or "not feeling that question" matches nothing.
_BOUNDARY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bnever\s+ask\s+(?:me\s+)?about\s+(?P<topic>.+)", re.IGNORECASE),
    re.compile(
        r"\b(?:don't|do\s+not|dont)\s+(?:ever\s+)?ask\s+(?:me\s+)?about\s+(?P<topic>.+)",
        re.IGNORECASE,
    ),
    re.compile(r"\bnever\s+bring\s+up\s+(?P<topic>.+)", re.IGNORECASE),
    re.compile(r"\b(?:don't|do\s+not|dont)\s+bring\s+up\s+(?P<topic>.+)", re.IGNORECASE),
    re.compile(r"\bnever\s+mention\s+(?P<topic>.+)", re.IGNORECASE),
    re.compile(r"\b(?:don't|do\s+not|dont)\s+mention\s+(?P<topic>.+)", re.IGNORECASE),
)

#: Trailing words that carry no topic meaning on their own.
_TRAILING_FILLER = ("again", "anymore", "ever")

#: Captured "topics" that refer to the question itself, not a topic.
#: "Never ask me that" bounds the question, not a subject — it is a
#: "not that question" decline, not a topic boundary.
_NON_TOPICS = frozenset({"that", "this", "it", "me", "that again", "this again"})

_MAX_TOPIC_CHARS = 120


def normalize_topic(topic: str | None) -> str:
    """Lowercase, strip punctuation/whitespace, collapse inner space.

    The normalized form is the dedupe key; the display form keeps the
    user's original casing.
    """
    raw = (topic or "").strip().lower()
    raw = raw.strip(" .!?,;:\"'()[]")
    raw = re.sub(r"\s+", " ", raw)
    return raw


def recognize_explicit_boundary(message: str | None) -> str | None:
    """Return the topic of an explicit topic boundary, or None.

    Fires ONLY on explicit boundary-setting words. Ordinary declines
    return None and must never be recorded as topic prohibitions.
    Returns the display form of the topic (user's words, trailing
    filler stripped, capped); None when no boundary is set.
    """
    text = (message or "").strip()
    if not text:
        return None
    for pattern in _BOUNDARY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        topic = match.group("topic").strip().strip(" .!?,;:\"'()[]")
        # Only the first clause is the topic: stop at a sentence
        # boundary or a coordinating conjunction that starts a new
        # thought ("but", "and" after a comma is kept only if short).
        topic = re.split(r"[.!?;\n]", topic, maxsplit=1)[0].strip()
        words = topic.split()
        while words and words[-1].lower().strip(" .!?,") in _TRAILING_FILLER:
            words.pop()
        topic = " ".join(words).strip(" .!?,;:\"'()[]")
        if not topic:
            return None
        if normalize_topic(topic) in _NON_TOPICS:
            return None
        if len(topic) > _MAX_TOPIC_CHARS:
            topic = topic[:_MAX_TOPIC_CHARS].rstrip()
        return topic
    return None
