"""Role briefs for the Moneyball role-only comparison (experimental drafts).

These briefs are EXPERIMENTAL, PROVISIONAL, and reversible. They are
not seat identities, not Fellowship archetypes, and not training
labels: they direct attention and task emphasis ONLY, for six
experiment meetings. After the program, the default is removal, not
retention, unless a FUTURE authorization adopts routing.

A brief says what to DO, never what to BE. Identity wording ("you are
the auditor") is forbidden: the model identity and the assigned
responsibility stay separate (Model / Assignment / Status:
provisional / Evidence / Confidence, recorded outside the room).

GPT receives NO brief: there is no falsifiable specialty hypothesis
for GPT yet (UNPROVEN — 5 proposals in 7 meetings, zero objections,
90% unknown labels; synthesis 0/4 confounded by the instrument).
GPT is an unbriefed PARTICIPANT in Condition B, not a control
expected to produce equivalent outputs — it reads the shared registry
in later phases, and briefed models may have changed that registry,
so GPT may differ with zero change to its own instructions. That
difference is information, never invalidation of a packet pair.

No fallback for Grok during this experiment: Grok's reliability is
part of what is measured; substituting another model would conceal
a limitation. If Grok is absent, unparseable, or at capacity, the
challenge slot stays empty and that emptiness is recorded.
"""

from __future__ import annotations

# Brief text version, recorded per meeting. Briefs do not change
# mid-program; a new version means a new program authorization.
ROLE_BRIEF_VERSION = "role-briefs-v1"

# Participant name -> brief text. Names are SEAT_SPECS names
# (local_ai/build_room/participants.py). GPT is deliberately absent.
ROLE_BRIEFS: dict[str, str] = {
    "Muse": (
        "Verify every claim you make against the packet: cite the "
        "source that says what you say it says. Flag claims in the "
        "registry whose cited source does not support them. State "
        "completeness limits explicitly where the packet cannot settle "
        "a question. Object on provenance grounds when prior-session "
        "or invalidated material is carried forward."
    ),
    "Gemini": (
        "Enumerate failure modes and edge cases for each proposal in "
        "the packet and in the registry: what breaks, under what "
        "conditions, with what consequence. Stress-test the strongest "
        "proposals hardest. Name each failure mode concretely enough "
        "that it can be checked against the packet or the code."
    ),
    "Claude": (
        "Turn positions into implementable form: concrete "
        "specifications, sequencing, and gates. For each "
        "recommendation, state what would have to be true for it to "
        "ship, and what blocks it. Prefer a shippable specification "
        "over a further consideration."
    ),
    "Grok": (
        "Challenge premises and consensus: for each load-bearing "
        "claim, ask what it assumes, what would falsify it, and "
        "whether agreement in the room reflects evidence or "
        "repetition. Object with grounds, not with posture — an "
        "objection must name the premise or the evidence gap."
    ),
}

BRIEFED_SEATS: tuple[str, ...] = ("Muse", "Gemini", "Claude", "Grok")
UNBRIEFED_SEATS: tuple[str, ...] = ("GPT",)


def role_prompt_extras(
    briefs: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the prompt_extras dict for Condition B.

    Maps a participant name to a section appended ONLY to that
    participant's prompt, following the tools-section precedent
    ("\\n\\n" + section). GPT is never in the returned dict.
    """
    source = ROLE_BRIEFS if briefs is None else briefs
    return {name: "\n\n" + text for name, text in source.items()}
