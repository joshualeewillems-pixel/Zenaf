"""Attention service — Fellowship Runtime P2.

The per-seat attention read model (mapping §C): one merged view of

  (a) the existing keystone progression markers (unchanged semantics —
      ``intro | meet | recognition``), and
  (b) P1's pending observations — a seat has something relevant to
      discuss, clarify, challenge, or offer.

Doctrine §3: "!" is persistent awareness WITHOUT constant interruption.
This module therefore produces markers only. It never injects a seat
message, a suggestion, or any content into a turn, and it never
generates anything: serving attention is a pure read over two stores
(the keystone state and the observations store). Characters are
generally listening; they produce nothing until asked.

Two-speed law: relevance scoring runs in the slow path, never on a
turn path. P2 does NOT invent a second scorer — P1's deterministic
pre-filter (``derivation.candidate_seats``: jurisdiction focus/periphery
keywords from the P0 registry, weighted, plus strand alignment) IS the
cheap weighted relevance score, and it already runs inside P1's async
derivation pipeline. ``score_relevance`` exposes that scorer under the
attention layer's name so it is testable and reusable; the read model
itself never re-scores at serve time — markers derive from stored
observations, so serving attention cannot change a turn's cost.

Marker rules (all deliberate, all tested):

- One marker per seat. ``attention`` is lit when EITHER source is lit.
- ``reason`` preserves the existing contract: a keystone reason wins
  when both sources are lit (the Living Tree's Begin door keys off
  ``reason == "intro"`` and must never be masked by an observation).
  The observation's own reason is always visible separately as
  ``observation_reason``.
- Observation markers cover observations with status ``pending`` or
  ``surfaced`` ("active"). ``discussed``/``dismissed`` clear the marker
  automatically — the read model derives from status, so there is no
  second marker store to drift out of sync with the observations store.
- The marker's reason for a seat comes from its MOST RECENT active
  observation (by ``(created_at, id)``, the store's order); the marker
  lists every active observation id for that seat.
- Observation reasons are a DISPLAY classification, derived
  deterministically from the observation's interpretation text
  (``reason_for_observation``). They do not assert the seat's intent;
  the observation text is the content and the reason is a hint for the
  dot's title. Assigning reasons by model judgment would be a P1
  schema change (a reason field on observations), not a P2 read-model
  concern.
- No auto-transition: serving attention does NOT move observations
  from ``pending`` to ``surfaced``. "Surfaced" means the user has seen
  observation *content* — P4's thread notes are the honest "shown"
  moment; a tree-view fetch rendering a dot is not. P2 reads both
  statuses as active and leaves the transition to the surface that
  actually shows content.

No LLM, no network, no writes: this module's only I/O is SQLite reads
(observations) plus the keystone read it already performed. The turn
path never imports this module (pinned by test).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from local_ai.council import keystones as KD
from local_ai.fellowship.derivation import CandidateMatch, candidate_seats
from local_ai.fellowship.events import FellowshipEvent
from local_ai.fellowship.observations import Observation, ObservationStore

#: Reason vocabulary for observation-derived markers (mapping §C).
OBSERVATION_REASONS: tuple[str, ...] = ("discuss", "clarify", "challenge", "offer")

#: Observation statuses that keep a marker lit. Terminal statuses clear it.
ACTIVE_OBSERVATION_STATUSES: tuple[str, ...] = ("pending", "surfaced")

#: Cap on observations read per status when serving attention. The
#: store's list is oldest-first; the cap exists so one pathological
#: user cannot make serving attention unbounded. Markers stay correct
#: past the cap (attention is a boolean); only the id list truncates.
_ATTENTION_LIST_LIMIT = 10000

#: Word-boundary patterns for the display classification. A question
#: mark is the strongest stance signal and wins outright; contrast
#: reframes a whole reading, so challenge beats offer.
_CHALLENGE_RE = re.compile(
    r"\b(but|however|yet|despite|instead|contradict\w*|tension|"
    r"what if|on the other hand)\b"
)
_OFFER_RE = re.compile(
    r"\b(consider|could|try|might|perhaps|suggest\w*|offer\w*|"
    r"invite\w*|opportunity|seed\w*)\b"
)


def reason_for_observation(observation: Observation) -> str:
    """Display reason for one observation's marker.

    Deterministic and cheap: a question is a clarification request;
    contrast language is a challenge; proposal language is an offer;
    anything else is a discussion. This classifies the *text*, not the
    seat's intent — see the module docstring.
    """
    text = (observation.interpretation or "").lower()
    if "?" in text:
        return "clarify"
    if _CHALLENGE_RE.search(text):
        return "challenge"
    if _OFFER_RE.search(text):
        return "offer"
    return "discuss"


@dataclass(frozen=True)
class SeatRelevance:
    """One seat's cheap relevance score for one event.

    This is P1's pre-filter result under the attention layer's name:
    keyword hits against the seat's jurisdiction corpus plus strand
    alignment. No model is consulted; for events without an entity
    reference the computation is pure (no I/O at all).
    """

    seat: str
    score: int
    focus_terms: list[str] = field(default_factory=list)
    periphery_terms: list[str] = field(default_factory=list)
    strand_alignment: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "seat": self.seat,
            "score": self.score,
            "focus_terms": list(self.focus_terms),
            "periphery_terms": list(self.periphery_terms),
            "strand_alignment": self.strand_alignment,
        }


def score_relevance(event: FellowshipEvent) -> list[SeatRelevance]:
    """Deterministic per-seat relevance for one event, highest first.

    Thin wrapper over ``derivation.candidate_seats`` — deliberately not
    a second scorer. Callers are slow-path only (derivation, sweeps);
    the attention read model never calls this at serve time.
    """
    matches: list[CandidateMatch] = candidate_seats(event)
    return [
        SeatRelevance(
            seat=m.seat,
            score=m.score,
            focus_terms=list(m.focus_terms),
            periphery_terms=list(m.periphery_terms),
            strand_alignment=m.strand_alignment,
        )
        for m in matches
    ]


@dataclass(frozen=True)
class SeatAttention:
    """One seat's merged attention marker."""

    seat: str
    attention: bool
    reason: str | None
    keystone_reason: str | None
    observation_reason: str | None
    observation_ids: tuple[str, ...] = ()
    observation_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "attention": self.attention,
            "reason": self.reason,
            "keystone_reason": self.keystone_reason,
            "observation_reason": self.observation_reason,
            "observation_ids": list(self.observation_ids),
            "observation_count": self.observation_count,
        }


def _active_observations(
    store: ObservationStore, user_id: str
) -> dict[str, list[Observation]]:
    """Active observations grouped by seat, oldest first per seat."""
    by_seat: dict[str, list[Observation]] = {}
    for status in ACTIVE_OBSERVATION_STATUSES:
        for obs in store.list_for_user(
            user_id, status=status, limit=_ATTENTION_LIST_LIMIT
        ):
            by_seat.setdefault(obs.seat, []).append(obs)
    for obs_list in by_seat.values():
        obs_list.sort(key=lambda o: (o.created_at, o.id))
    return by_seat


def attention_for_user(
    user_id: str,
    *,
    observation_store: ObservationStore | None = None,
    keystone_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merged per-seat attention for one user. Pure read, no writes.

    ``keystone_state`` is injectable for tests; by default it is read
    from ``vision_execution.keystone_seeding`` (imported lazily, the
    same way the route does, so this package never imports the VE
    layer at module load). ``seeded`` keeps the keystone meaning
    (whether the user has a "Meet your council" initiative); an
    unseeded user can still carry observation markers — observations
    come from conversations, not from keystone seeding.
    """
    if keystone_state is None:
        from local_ai.vision_execution import keystone_seeding

        keystone_state = keystone_seeding.keystone_attention(user_id)
    store = observation_store or ObservationStore()
    by_seat = _active_observations(store, user_id)

    keystone_markers = keystone_state.get("markers") or {}
    markers: dict[str, dict[str, Any]] = {}
    for seat in KD.SEATS:
        ref = seat["seat_ref"]
        keystone = keystone_markers.get(ref) or {}
        keystone_lit = bool(keystone.get("attention"))
        keystone_reason = keystone.get("reason")
        obs_list = by_seat.get(ref, [])
        obs_reason = (
            reason_for_observation(obs_list[-1]) if obs_list else None
        )
        markers[ref] = SeatAttention(
            seat=ref,
            attention=bool(keystone_lit or obs_list),
            reason=keystone_reason if keystone_lit else obs_reason,
            keystone_reason=keystone_reason,
            observation_reason=obs_reason,
            observation_ids=tuple(o.id for o in obs_list),
            observation_count=len(obs_list),
        ).to_dict()
    # Defensive: an observation for a seat outside the canonical seven
    # must never be silently dropped from the read model.
    for seat, obs_list in by_seat.items():
        if seat in markers:
            continue
        markers[seat] = SeatAttention(
            seat=seat,
            attention=True,
            reason=reason_for_observation(obs_list[-1]),
            keystone_reason=None,
            observation_reason=reason_for_observation(obs_list[-1]),
            observation_ids=tuple(o.id for o in obs_list),
            observation_count=len(obs_list),
        ).to_dict()
    return {"seeded": bool(keystone_state.get("seeded")), "markers": markers}
