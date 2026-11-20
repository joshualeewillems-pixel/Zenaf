"""Aria's grounded expression — the binding (Increment 1).

One pure derivation: given a user and a Work (a Vision-Execution
entity), produce Aria's expression specification for that Work's
portrait — data only, no rendering, no writes, no model calls.

SCOPE, AS RE-SCOPED BY THE FOUNDER CLARIFICATION (Aria's Compass
Orientation, 2026-11-19 16:13 PT — it governs over the Gate B
brief's body wherever the two differ): this derivation covers the
ACTIVITY dimension plus the recorded-relations set, and nothing
else. What exists, a Work's faculty mix (its strand weights, as a
fact about the WORK), recorded relations, recorded tensions,
recorded changes of direction. Identity and purpose are NOT
derivable from project metadata: they live in grounded
conversation, attributed interpretations, and the visitor's own
verdicts, none of which this module touches. The spec's coverage
block declares the dimensions it does not touch, so no consumer
can present this output as a portrait of a person.

The derivation is READ-ONLY and DETERMINISTIC: identical records
produce a byte-identical spec (``AriaExpressionSpec.to_json``), and
no store's bytes change across a call. It reads only through the
existing stores' own APIs and their ownership enforcement — every
read below is scoped by the requesting ``user_id`` in the store's
own SQL or row checks, so another user's records can never leak
into a spec; they read as absent.

CONSERVATIVE READINGS — the open questions for Gate C. Where an
existing read path was ambiguous, this module chose the reading
that contributes NOTHING rather than one that might over-claim,
and pinned the choice in tests/test_aria_expression.py:

OQ1 — entity → narrative thread mapping. No store field links a
  Vision-Execution entity to a narrative thread. The derivation
  adopts the steward's own PRECISE subject convention
  (``narrative/derivation.subject_key_for_thread``): a thread
  belongs to the entity iff the DOMINANT ``entity_ref`` across its
  annotated evidence rows equals ``"<entity_type>:<entity_id>"``
  (most frequent; ties break lexicographically first — derivation's
  deterministic rule, re-implemented here in five lines rather
  than imported, so this module never imports the S1 pipeline).
  Threads whose evidence carries no annotation are invisible to
  the derivation; any-mention matching was rejected as
  over-claiming. All precisely-matched threads contribute; their
  ids are recorded in coverage.
OQ2 — "presented" impression claims. Presentation is recorded
  ONLY as Weaver-round markers in conversation message context
  (``conversation/round.py`` derives round state from them per
  conversation; no claim-side presented flag and no global ledger
  exists). The derivation scans markers under the round's own
  history bound (§12.4 there): the most recent 100 messages of
  each conversation returned by ``list_conversations`` (itself
  capped at 100). A claim presented outside that window reads as
  unpresented and contributes nothing — undercount, never
  fabrication.
OQ3 — thread changes. Only CONFIRMED changes enter
  ``interactions``. Proposed changes are unconfirmed proposals and
  contribute nothing anywhere in this increment; dismissed changes
  likewise. A confirmed ``contradicted`` change is an interaction
  of kind ``tension`` — never ``resolution``: recorded tension
  renders as tension.
OQ4 — strand activity (growth). A strand counts as active iff it
  holds at least one strand source OR a resolved strand thread
  whose conversation holds at least one message. A resolved-but-
  empty thread (the panel was opened, never spoken in) is NOT
  activity. The growth mask is the active strands minus any strand
  carrying an explicit topic boundary — boundaries exclude
  absolutely, even when the bounded strand is the Work's dominant
  strand.
OQ5 — complexity quantization. Substance per family = strand
  sources held + PRESENTED strand-tagged pending impression
  claims citing the family. Tiers are bounded and quantized
  (three): substance 0 → tier 0, 1–2 → tier 1, ≥3 → tier 2. The
  quantization is artistic interpretation (per the grounded-
  expression map); the inputs are records. Unpresented claims
  contribute nothing — a claim sitting in the queue deepens
  nothing until her presentation machinery surfaces it.
OQ6 — capacities. Weighed ⇒ ``capacity_f = blend_f ×
  (1 + weight_f)`` (blend = the conductor archetype's strand
  weights, read verbatim through ``get_archetype``), rounded to
  6dp: monotone non-decreasing in the Work's weight for each
  family, bounded in [blend_f, 2·blend_f]. Unweighed ⇒ every
  family exactly ``BASE_CAPACITY`` (1.0), uniform — her blend's
  differentiation is NOT substituted for the Work's missing
  weights (brief test 1: no family differs from another).

OPACITY IS OUT OF SCOPE. Its ruled input (per-Work, per-seat
discussion counts) is not a record the system keeps, so the spec
carries ``coverage["opacity_input"] = "fixture_only"`` and no
opacity value appears anywhere in the spec — no consumer can
mistake a study fixture for data.

RECOGNITION IS NOT A DEPENDENCY. Proposed readings, fittings, and
correspondences are base-schema record types (Steward S0 /
Phase 7); the derivation reads them generically from the narrative
store when they exist and works fully when none do
(``coverage["recognition_absent"]`` says which happened).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from local_ai.agent_intake.signals import claim_strands
from local_ai.conversation.round import (
    CTX_ROUND_CLAIM_ID,
    CTX_ROUND_KIND,
    CTX_ROUND_STATE,
    ROUND_KIND,
)
from local_ai.council.archetypes import KEY_TO_PLAIN, get_archetype
from local_ai.entity_strands import get_entity_strands
from local_ai.strand_interviews.keys import (
    DESIGN_STRAND_KEYS,
    DESIGN_TO_TAXONOMY,
)
from local_ai.strands import STRANDS

#: The seven families, in canonical strand order, keyed by the
#: plain-spoken names the weight/blend vocabularies use.
FAMILIES: tuple[str, ...] = tuple(KEY_TO_PLAIN[s.key] for s in STRANDS)

#: The capacity of every family for an unweighed Work (OQ6): one
#: uniform base value — the honest null, mirroring the store's
#: "unknown is honest, never zero" for the weights themselves.
BASE_CAPACITY = 1.0

#: Presentation scan bounds (OQ2): the round machinery's own
#: history bound (§12.4 of its brief: 100 messages covers a round
#: segment with headroom) and list_conversations' own cap.
_PRESENTATION_HISTORY_LIMIT = 100
_PRESENTATION_CONVERSATION_LIMIT = 100

#: Complexity tiers (OQ5): substance thresholds for tiers 1 and 2.
_TIER_1_MIN = 1
_TIER_2_MIN = 3


def _plain_for_design(design_key: str) -> str:
    """Design strand key (heart) → plain family name (Heart)."""
    return KEY_TO_PLAIN[DESIGN_TO_TAXONOMY[design_key]]


def _tier(substance: int) -> int:
    if substance >= _TIER_2_MIN:
        return 2
    if substance >= _TIER_1_MIN:
        return 1
    return 0


def _dominant_entity_ref(refs: Any) -> str | None:
    """Most frequent entity ref; ties break lexicographically first.

    The steward derivation's deterministic subject rule
    (``narrative/derivation._dominant_entity_ref``), re-implemented
    rather than imported so this module never pulls in the S1
    pipeline. Rows without annotations read None and do not
    participate — honest unknown, never inferred.
    """
    counts: Counter = Counter(r for r in refs if r)
    if not counts:
        return None
    top = max(counts.values())
    return sorted(r for r, n in counts.items() if n == top)[0]


@dataclass(frozen=True)
class AriaExpressionSpec:
    """Aria's expression specification for one Work — data only.

    Frozen and JSON-able. ``to_json`` is canonical (sorted keys,
    tight separators), so identical records yield byte-identical
    output. Every family-keyed mapping carries all seven families;
    absence is expressed by values (tier 0, empty mask, empty
    lists), never by missing keys.
    """

    user_id: str
    entity_type: str
    entity_id: str
    blend: dict[str, float]
    capacities: dict[str, float]
    complexity: dict[str, int]
    growth_mask: tuple[str, ...]
    interactions: tuple[dict[str, Any], ...]
    provisional: tuple[dict[str, Any], ...]
    coverage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "blend": dict(self.blend),
            "capacities": dict(self.capacities),
            "complexity": dict(self.complexity),
            "growth_mask": list(self.growth_mask),
            "interactions": [dict(e) for e in self.interactions],
            "provisional": [dict(e) for e in self.provisional],
            "coverage": dict(self.coverage),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def _presented_claim_ids(conversation_store: Any, user_id: str) -> set[str]:
    """Claim ids the Weaver round has presented, per the markers.

    The markers are the only record of presentation (OQ2): an
    assistant ("voice") message whose context carries
    round_kind="weaver" and round_state="item" names the claim it
    presented. Scanned under the round's own history bound.
    """
    presented: set[str] = set()
    conversations = conversation_store.list_conversations(
        user_id, limit=_PRESENTATION_CONVERSATION_LIMIT
    )
    for convo in conversations:
        conversation_id = convo.get("conversation_id")
        if not conversation_id:
            continue
        history = conversation_store.history(
            user_id, conversation_id, limit=_PRESENTATION_HISTORY_LIMIT
        )
        for msg in history:
            if msg.get("role") != "voice":
                continue
            ctx = msg.get("context") or {}
            if ctx.get(CTX_ROUND_KIND) != ROUND_KIND:
                continue
            if ctx.get(CTX_ROUND_STATE) != "item":
                continue
            claim_id = ctx.get(CTX_ROUND_CLAIM_ID)
            if claim_id:
                presented.add(str(claim_id))
    return presented


def _matched_threads(
    narrative_store: Any, user_id: str, target_ref: str
) -> list[Any]:
    """The Work's narrative threads, by the PRECISE subject rule (OQ1)."""
    matched: list[Any] = []
    for thread in narrative_store.threads_for(user_id, limit=None):
        rows = narrative_store.evidence_for(user_id, thread.id)
        if _dominant_entity_ref(row.entity_ref for row in rows) == target_ref:
            matched.append(thread)
    return matched


def derive_aria_expression(
    user_id: str,
    entity_type: str,
    entity_id: str,
    *,
    conversation_store: Any = None,
    narrative_store: Any = None,
    agent_store: Any = None,
) -> AriaExpressionSpec:
    """Derive Aria's expression spec for one Work from live records.

    Read-only and deterministic. Stores may be injected (tests);
    any store not given is constructed at its production default
    and closed again before returning — the derivation never holds
    a store open and never writes through one. An unknown
    ``entity_type`` raises ValueError, exactly as
    ``entity_strands.get_entity_strands`` raises it: a bad entity
    kind is a caller error, not a record state.
    """
    constructed: list[Any] = []
    if conversation_store is None:
        from local_ai.conversation.store import ConversationStore

        conversation_store = ConversationStore()
        constructed.append(conversation_store)
    if narrative_store is None:
        from local_ai.narrative.store import NarrativeStore

        narrative_store = NarrativeStore()
        constructed.append(narrative_store)
    if agent_store is None:
        from local_ai.agent_intake.store import AgentStore

        agent_store = AgentStore(user_id=user_id)
        constructed.append(agent_store)
    try:
        return _derive(
            user_id,
            entity_type,
            entity_id,
            conversation_store=conversation_store,
            narrative_store=narrative_store,
            agent_store=agent_store,
        )
    finally:
        for store in constructed:
            close = getattr(store, "close", None)
            if callable(close):
                close()


def _derive(
    user_id: str,
    entity_type: str,
    entity_id: str,
    *,
    conversation_store: Any,
    narrative_store: Any,
    agent_store: Any,
) -> AriaExpressionSpec:
    # -- her fingerprint: the conductor's blend, verbatim ----------
    archetype = get_archetype("conductor")
    blend_raw = (archetype.strand_weights if archetype else None) or {}
    blend = {f: float(blend_raw.get(f, 0.0)) for f in FAMILIES}

    # -- capacities: the Work's faculty mix, or the honest null ----
    weighting = get_entity_strands(user_id, entity_type, entity_id)
    weights = weighting.strand_weights
    if weights is None:
        capacities = {f: BASE_CAPACITY for f in FAMILIES}
    else:
        capacities = {
            f: round(blend[f] * (1.0 + float(weights.get(f, 0.0))), 6)
            for f in FAMILIES
        }

    # -- her strand keeping: substance, activity, boundaries -------
    substance: Counter = Counter()
    boundaries_in_force: list[dict[str, Any]] = []
    active: set[str] = set()
    bounded: set[str] = set()
    for design_key in DESIGN_STRAND_KEYS:
        plain = _plain_for_design(design_key)
        sources = conversation_store.list_strand_sources(user_id, design_key)
        substance[plain] += len(sources)
        boundaries = conversation_store.list_topic_boundaries(
            user_id, design_key
        )
        if boundaries:
            bounded.add(plain)
            for row in boundaries:
                boundaries_in_force.append(
                    {"strand": plain, "topic": str(row.get("topic") or "")}
                )
        thread_row = conversation_store.get_strand_thread(user_id, design_key)
        messages = 0
        if thread_row:
            messages = conversation_store.count_messages(
                user_id, str(thread_row["conversation_id"])
            )
        if sources or messages > 0:
            active.add(plain)

    # -- presented impression claims: complexity + provisional -----
    presented_ids = _presented_claim_ids(conversation_store, user_id)
    provisional: list[dict[str, Any]] = []
    presented_found = 0
    for claim in agent_store.pending_impressions(user_id):
        claim_id = str(claim.get("id") or "")
        if not claim_id or claim_id not in presented_ids:
            continue  # unpresented claims contribute nothing (OQ5)
        presented_found += 1
        cited: list[str] = []
        for tax_key in claim_strands(claim_id, "meeting_impression"):
            plain = KEY_TO_PLAIN.get(tax_key)
            if plain is None:
                continue
            substance[plain] += 1
            cited.append(plain)
        provisional.append(
            {
                "kind": "impression_claim",
                "source_id": claim_id,
                "standing": "presented_unruled",
                "strands": [f for f in FAMILIES if f in cited],
            }
        )

    complexity = {f: _tier(substance[f]) for f in FAMILIES}
    growth_mask = tuple(
        f for f in FAMILIES if f in active and f not in bounded
    )

    # -- the Work's threads: recorded relations + proposals --------
    target_ref = f"{entity_type}:{entity_id}"
    matched = _matched_threads(narrative_store, user_id, target_ref)
    matched_ids = [t.id for t in matched]

    interactions: list[dict[str, Any]] = []
    thread_proposals = 0
    for thread in matched:
        for link in narrative_store.links_for(user_id, thread.id):
            if link.parent_thread_id == thread.id:
                direction, other = "contains", link.child_thread_id
            else:
                direction, other = "part_of", link.parent_thread_id
            interactions.append(
                {
                    "kind": "link",
                    "source_id": link.id,
                    "standing": "recorded",
                    "relation": link.relation,
                    "direction": direction,
                    "thread_id": thread.id,
                    "other_thread_id": other,
                }
            )
        for change in narrative_store.changes_for(user_id, thread.id):
            if change.status != "confirmed":
                continue  # OQ3: unconfirmed proposals contribute nothing
            if change.kind == "contradicted":
                interactions.append(
                    {
                        "kind": "tension",
                        "source_id": change.id,
                        "standing": "confirmed",
                        "change_kind": change.kind,
                        "thread_id": thread.id,
                    }
                )
            else:
                interactions.append(
                    {
                        "kind": "change",
                        "source_id": change.id,
                        "standing": "confirmed",
                        "change_kind": change.kind,
                        "thread_id": thread.id,
                    }
                )
        for reading in narrative_store.readings_for(
            user_id, thread.id, status="proposed"
        ):
            thread_proposals += 1
            provisional.append(
                {
                    "kind": "reading",
                    "source_id": reading.id,
                    "standing": reading.status,
                    "author": reading.author,
                    "thread_id": thread.id,
                }
            )
        for fitting in narrative_store.fittings_for(user_id, thread.id):
            if fitting.status not in ("proposed", "offered"):
                continue
            thread_proposals += 1
            provisional.append(
                {
                    "kind": "fitting",
                    "source_id": fitting.id,
                    "standing": fitting.status,
                    "lens_id": fitting.lens_id,
                    "thread_id": thread.id,
                }
            )

    matched_id_set = set(matched_ids)
    for corr in narrative_store.correspondences_for(user_id):
        if not (set(corr.thread_ids or []) & matched_id_set):
            continue
        if corr.status == "user_accepted":
            interactions.append(
                {
                    "kind": "correspondence",
                    "source_id": corr.id,
                    "standing": "user_accepted",
                    "thread_ids": sorted(corr.thread_ids or []),
                }
            )
        elif corr.status == "proposed":
            thread_proposals += 1
            provisional.append(
                {
                    "kind": "correspondence",
                    "source_id": corr.id,
                    "standing": corr.status,
                    "thread_ids": sorted(corr.thread_ids or []),
                }
            )

    interactions.sort(key=lambda e: (e["kind"], e["source_id"]))
    provisional.sort(key=lambda e: (e["kind"], e["source_id"]))
    boundaries_in_force.sort(
        key=lambda b: (FAMILIES.index(b["strand"]), b["topic"])
    )

    provisional_sources: list[str] = []
    if presented_found:
        provisional_sources.append("presented_impression_claims")
    if thread_proposals:
        provisional_sources.append("thread_proposals")

    coverage: dict[str, Any] = {
        # The Revision's required declaration: this spec touches
        # the activity dimension and recorded relations only.
        "dimensions_touched": ["activity", "recorded_relations"],
        "dimensions_not_touched": ["identity", "purpose"],
        "unweighed": weights is None,
        "weights_source": weighting.source,
        "narrative_thread_match": (
            "precise_dominant_entity" if matched else "none"
        ),
        "narrative_thread_ids": matched_ids,
        "boundaries_in_force": boundaries_in_force,
        "opacity_input": "fixture_only",
        "provisional_sources": provisional_sources,
        "recognition_absent": thread_proposals == 0,
        "presented_claims_found": presented_found,
        "presentation_scan": "round_markers_recent_history",
    }

    return AriaExpressionSpec(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        blend=blend,
        capacities=capacities,
        complexity=complexity,
        growth_mask=growth_mask,
        interactions=tuple(interactions),
        provisional=tuple(provisional),
        coverage=coverage,
    )
