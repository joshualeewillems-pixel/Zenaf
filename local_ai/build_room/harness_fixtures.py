"""Shared synthesis-harness fixtures (PR #227, unchanged).

Single source of truth for the bounded fixture states used by BOTH
the test-only harness (``tests/test_build_room_synthesis_harness.py``)
and the staging harness route (``api/routes/build_room_routes.py``,
``/build-room/harness/synthesis-call``). The route MUST construct
exactly these states — same claims, same packet, same unresolved
objections/chains, same telemetry — never a re-invented copy; a
route test asserts identity against these builders.

Fixture D (disagreements): C1/C2 carry the opposing positions,
C3 objects to C1 (unresolved objection), C4 is GPT's authorial
response (revision chain). Fixture E (legitimate empties): a small
state whose honest synthesis has no recommendations or limitations.

Telemetry inputs are fixed constants (phase ``"synthesis"``,
``max_generations`` 16, ``completed`` 15 mirroring a full meeting's
synthesis slot, ``allocated`` 1, ``reserved`` {}), so the assembled
prompt is reproducible. No credentials, no keys, no model calls here.
"""

from __future__ import annotations

from local_ai.build_room.meeting import ClaimRegistry, EvidencePacket

# Fixed, disclosed telemetry inputs. completed=15 mirrors a full
# meeting's synthesis slot (15 generations completed before synthesis).
TELEMETRY = {
    "phase": "synthesis",
    "max_generations": 16,
    "completed": 15,
    "allocated": 1,
    "reserved": {},
}

QUESTION = (
    "What would make the Build-Council Room fail to function as a "
    "genuine deliberative council?"
)


def fixture_d_state():
    """Fixture D: opposing claims + unresolved objection + response chain."""
    reg = ClaimRegistry()
    reg.register("GPT", "opening",
                 "1. Observed: Assigned roles improve accountability.")
    reg.register("Muse", "opening",
                 "1. Observed: Open roles permit more substantive deliberation.")
    reg.register("Gemini", "response",
                 "1. Inferred: In response to C1, assigned roles risk "
                 "entrenching the convener's framing.")
    reg.register("GPT", "revision",
                 "1. Inferred: Assigned roles improve accountability when "
                 "the role description is itself revisable by the council.")
    packet = EvidencePacket(
        work_item="Harness fixture D",
        question=QUESTION,
        constraints=("The room deliberates and recommends only.",
                     "Roles and jurisdictions are NOT assigned."),
    )
    unresolved = [{"claim_id": "C1", "cited_by": "Gemini",
                   "source_claim_id": "C3", "moves": ["objection"],
                   "state": "unresolved", "responded_by": None}]
    chains = [{"original_claim_id": "C1", "challenge_claim_id": "C3",
               "challenge_move": "objection", "challenger": "Gemini",
               "revision_claim_id": "C4", "revision_relationship": "unstated",
               "author": "GPT"}]
    return packet, reg, unresolved, chains


def fixture_e_state():
    """Fixture E: small state, honestly no recommendations/limitations."""
    reg = ClaimRegistry()
    reg.register("GPT", "opening",
                 "1. Observed: The council recommends only; Joshua decides.")
    reg.register("Muse", "opening",
                 "1. Inferred: Open roles permit more substantive deliberation.")
    packet = EvidencePacket(work_item="Harness fixture E", question=QUESTION)
    return packet, reg, [], []
