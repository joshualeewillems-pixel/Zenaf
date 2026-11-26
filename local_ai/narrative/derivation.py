"""Narrative Steward S1 — slow-path thread derivation.

Derivation turns evidence the system already holds (fellowship
events, review claims, journal entries) into thread *proposals*:
proposed thread births, proposed reading updates, proposed changes.
It follows the Fellowship P1 derivation pattern exactly, because
that pattern is the audit's specified slow-path shape (audit
Part II §3, Part III S1):

  1. Deterministic pre-filter — pure arithmetic, no model. Evidence
     items are clustered by shared entity refs, shared distinctive
     tokens, or strand-vector similarity; a cluster is eligible only
     when it also touches a seat's jurisdiction (focus terms or
     strand alignment) or an existing live thread. A cluster on
     nobody's ground produces zero model calls and zero proposals.
  2. Interpretation — at most ONE generation per candidate cluster
     (birth) or per candidate thread (extension), through the
     codebase's usual injectable ``generate_fn`` seam. The generator
     proposes structured state in the claim register (plain system
     text, never a seat's voice) or declines (``NONE``) — precision
     over coverage. A decline leaves no row.

Derivation also maintains one index the S0 store does not: the
entity each attached evidence row is about
(``thread_evidence.entity_ref``, nullable). The store never
invents it — rows from other writers read NULL — but derivation
records what it already knew when it attached evidence, so a
later batch can recognize a thread by entity, not only by ref
identity. That is what makes thread extension work across
batches: without it, a new event about a known task would be a
stranger to the thread its predecessors built.

What S1 deliberately does NOT do (audit Parts III/IV, ratified
Parts VII–XI):

  - Nothing is accepted, surfaced, or used for training. Births land
    as ``nascent`` threads with origin ``steward_proposal``; readings
    and changes land ``proposed``. The user verdicts on them through
    the review layer, which is not S1's to build (audit Part V Q2
    remains an open product decision — proposals live in the S0
    store, inspectable, until that surface exists).
  - No lens fittings are proposed. Fitting proposals follow the
    offer→verdict path and one-live-fitting rule of the S0 store,
    but S1's generations do not name lenses: a reading's progression
    stays ``unknown`` unless a lens is later fitted by a user verdict
    or a later phase. Lens-independent development is the base
    (audit Part XI boundary 2) — changes, milestones, and evidence
    are representable with no lens anywhere.
  - No containment-link traversal and no containment inference.
    This module never reads the containment-link rows (an AST
    test pins that). Part XI names cycle-safety as a requirement for any
    future traversal; S1 avoids the question entirely — links are
    inert storage until a phase that needs them also brings the
    cycle discipline.
  - No foreground calls. Nothing here runs on a reply path; the
    pipeline schedules derivation on daemon threads (the P1
    precedent). CORRECTION (Phase 1): the pipeline IS installed at
    app assembly — ``api/main.py`` installs it at boot. What bounds
    production behavior is the consent gate, not non-installation:
    derivation runs only for visitors holding the default-off
    ``steward_derivation`` flag, and fails closed otherwise.
  - No new user-facing interventions and no HTTP routes. The only
    writes are to the S0 narrative store (threads, readings,
    changes, dismissal memory).

Control invariants (mirroring fellowship/derivation.py): derivation
writes ONLY to the narrative store; it imports nothing from the
review/intake filing paths, nothing from the signals store, and
nothing from any conversation path (reply/service/encounter/
meeting) — an AST test pins the separation. Every failure inside
derivation — per-cluster or whole-batch — is logged and swallowed:
a failed proposal can never break the operation that produced the
evidence. The S0 store's own invariants still bind every write:
a reading with no evidence-tier refs cannot be stored, a change
with no NEW evidence cannot be recorded, and a dramatization ref
can never become derivation evidence (tier gate, by type).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable

from local_ai.council.archetypes import PLAIN_TO_KEY, get_archetype, stock_archetype_ids
from local_ai.council.jurisdictions import get_jurisdiction
from local_ai.fellowship.events import FellowshipEvent

from .models import NarrativeThread
from .refs import RefTier, SourceRef
from .store import ErasureBarrierRefusal, NarrativeStore

logger = logging.getLogger(__name__)

GenerateFn = Callable[..., str]

#: Statuses a thread must be in to receive an extension proposal.
#: Resolved / retired / archived threads do not receive automatic
#: proposals — reopening one is a user act or an S3 change detector's
#: job, never a side effect of new evidence arriving.
EXTENDABLE_STATUSES: tuple[str, ...] = ("nascent", "active", "dormant")

#: Change kinds a generation may propose for an extension. Retirement
#: and resolution are excluded on purpose: ending a story (or
#: declaring it settled) is a user declaration or an S3 detector's
#: evidence-backed proposal, never a slow-path generation's guess.
GENERATION_CHANGE_KINDS: tuple[str, ...] = (
    "extended",
    "contradicted",
    "milestone",
    "reopened",
)

# ---------------------------------------------------------------------------
# Evidence items — the derivation input, normalized from owning stores
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceItem:
    """One piece of evidence, normalized for clustering.

    ``ref`` is the tier-checked pointer the S0 store will attach
    (kind must be evidence-tier — the store refuses anything else).
    ``text`` is the verbatim words (or, for wordless records, the
    factual summary) the generation prompt may quote from; it is
    prompt context, never itself stored as evidence. ``entity_ref``
    is the "<type>:<id>" identity shared across records about the
    same thing in the world. ``strand_weights`` is the owning
    record's strand vector when one exists, else None (honest
    unknown — the signal simply doesn't contribute).

    ``anchor_ref`` (Slice A, Packet C1 revised — §4.6-R) is a
    different kind of field from ``entity_ref`` and must never be
    read as one: it is the "<type>:<id>" of the *conversation
    anchor* the source event carried (the conversation's working
    subject — contextual aboutness), populated only from a
    high-confidence carried subject. It is derivation-internal and
    in-memory only — never persisted in narrative.db, never an
    annotation, never a subject key. Its sole consumption is the
    clustering rule in ``_linked``, where it groups records whose
    conversations share an anchor; it asserts nothing about what
    the records concern.
    """

    ref: SourceRef
    text: str = ""
    entity_ref: str | None = None
    strand_weights: dict[str, float] | None = None
    anchor_ref: str | None = None
    #: Steward D2 (§9.3): the item's provenance time, stamped by the
    #: entry point's eligibility evaluation when an erasure boundary
    #: stands (canonical UTC ISO, strictly after the boundary). It
    #: is the admitted set the funnel calls manifest from. None on
    #: every pre-D2 path — the funnels consult it only when a
    #: tombstone stands. In-memory only; never persisted.
    source_time: str | None = None

    def evidence_key(self) -> str:
        return f"{self.ref.kind}:{self.ref.ref_id}"


def anchor_channel_enabled() -> bool:
    """Rollback switch for the Slice A anchor channel (§5).

    An explicit ``ZENAF_STEWARD_ANCHOR_CHANNEL`` value wins
    ("1"/"true"/"yes"/"on" = on; anything else = off); otherwise
    the channel is ON. Off is the §4.9 comparison's Arm B position:
    carried subjects are present in event payloads but populate no
    ``anchor_ref`` and form no anchor links, so items and clusters
    return to exactly their pre-Slice-A behavior. Read per call so
    tests can flip it with ``monkeypatch.setenv``.
    """
    raw = os.environ.get("ZENAF_STEWARD_ANCHOR_CHANNEL")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return True


def _payload_anchor_ref(event: FellowshipEvent) -> str | None:
    """The event's carried conversation anchor, gated (§4.6-R rule 1).

    Reads ``event.payload["subject"]`` — the anchor the Talk path
    carried under consent — and returns ``"<type>:<id>"`` only when
    the anchor channel is on, the subject names an entity, its
    ``confidence`` is ``"high"`` (anchoring strength from the user's
    own session behavior — never identity evidence, §4.7), and its
    type is ``project`` or ``task`` (the only types Slice A anchors;
    any other type in a payload is inert here, not consumed).
    Medium/low subjects stay visible in the record but populate no
    anchor. Anything malformed reads as no anchor.
    """
    if not anchor_channel_enabled():
        return None
    payload = event.payload or {}
    subject = payload.get("subject")
    if not isinstance(subject, dict):
        return None
    if subject.get("confidence") != "high":
        return None
    entity_type = str(subject.get("entity_type") or "").strip()
    entity_id = str(subject.get("entity_id") or "").strip()
    if entity_type not in ("project", "task") or not entity_id:
        return None
    return f"{entity_type}:{entity_id}"


def _entity_strand_weights(event: FellowshipEvent) -> dict[str, float] | None:
    """The event entity's strand weightings, if it has any.

    Honest unknown: entities never weighed return None and the strand
    signal simply doesn't contribute (entity_strands' own rule).
    Reads all sources (user_stated, inferred, mined) — no source
    filter, per the founder's Q2 ruling. Same shape as the
    fellowship derivation's precedent
    (local_ai/fellowship/derivation.py::_entity_strand_weights).
    """
    entity_type = (event.entity_type or "").strip().lower()
    if entity_type not in ("person", "project", "task", "asset", "job"):
        return None
    if not event.entity_id or not event.user_id:
        return None
    try:
        from local_ai.entity_strands import get_entity_strands

        weighting = get_entity_strands(event.user_id, entity_type, event.entity_id)
        return weighting.strand_weights
    except Exception:
        logger.exception("narrative: strand lookup failed for %s", event.id)
        return None


def event_to_item(event: FellowshipEvent) -> EvidenceItem:
    """FellowshipEvent → EvidenceItem (audit Part III S1 input)."""
    if (event.evidence_text or "").strip():
        ref = SourceRef(kind="event", ref_id=event.id, evidence_kind="quote")
        text = event.evidence_text
    else:
        ref = SourceRef(kind="event", ref_id=event.id, evidence_kind="entity_ref")
        text = event.summary or ""
    entity_ref = None
    if (event.entity_type or "").strip() and (event.entity_id or "").strip():
        entity_ref = f"{event.entity_type}:{event.entity_id}"
    return EvidenceItem(
        ref=ref,
        text=text,
        entity_ref=entity_ref,
        strand_weights=_entity_strand_weights(event),
        anchor_ref=_payload_anchor_ref(event),
    )


def claim_to_item(claim: Any) -> EvidenceItem:
    """A ReviewClaim-like (id, evidence, title) → EvidenceItem.

    Duck-typed on purpose: the claim store's row shape is owned
    elsewhere; derivation needs only the verbatim quote (or the
    title when a claim carries no quote) and the claim id.

    NOTE (strand weights): dead converter — zero callers at 1589a04.
    If a caller ever appears, apply the event_to_item treatment
    here (entity lookup when the claim row carries an entity)
    instead of leaving strand_weights None.
    """
    evidence = (getattr(claim, "evidence", "") or "").strip()
    if evidence:
        ref = SourceRef(
            kind="claim", ref_id=str(claim.id), evidence_kind="quote"
        )
        text = evidence
    else:
        ref = SourceRef(
            kind="claim", ref_id=str(claim.id), evidence_kind="entity_ref"
        )
        text = (getattr(claim, "title", "") or "").strip()
    return EvidenceItem(ref=ref, text=text)


def entry_to_item(entry_id: str, text: str) -> EvidenceItem:
    """A pipeline journal entry (id, full text) → EvidenceItem.

    NOTE (strand weights): dead converter — zero callers at 1589a04.
    If a caller ever appears, entries carry no entity, so there is
    no stored weighting to read; leave strand_weights None unless
    a stored source exists. No text scoring (founder ruling Q1).
    """
    return EvidenceItem(
        ref=SourceRef(
            kind="journal_entry", ref_id=str(entry_id), evidence_kind="quote"
        ),
        text=text or "",
    )


# ---------------------------------------------------------------------------
# Deterministic pre-filter (mirrors fellowship/derivation.py's shape)
# ---------------------------------------------------------------------------

_STOPWORDS: frozenset[str] = frozenset(
    """
    about above after again against all and any are as at be because been
    before being below between both but by can could did do does doing down
    during each few for from further had has have having he her here hers
    herself him himself his how i if in into is it its itself just like me
    more most my no nor not now of off on once only or other our ours out
    over own s same she should so some such t than that the their theirs
    them themselves then there these they this those through to too under
    until up very was we were what when where which while who whom why will
    with would you your yours yourself one ones thing things way ways get
    gets got make made makes also much many would could may might must
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z][a-z0-9']+")
_MIN_TOKEN_LEN = 4
#: A term appearing in at least this many seats' focus corpora
#: discriminates nothing and is dropped (fellowship's _DF_DROP rule).
_DF_DROP = 4
#: Two items cohere on tokens only when they share at least this many
#: distinctive tokens — one shared word is not a story.
_TOKEN_COHESION_MIN = 2
#: Item–item strand similarity bar for a cohesion link (stricter than
#: the 0.30 seat-alignment bar: two records about the same ground
#: should resemble each other, not merely lean the same way).
_STRAND_COHESION_MIN = 0.50
#: Seat-alignment bar for jurisdiction candidacy (P1's rule).
_STRAND_ALIGNMENT_MIN = 0.30


def _stem(token: str) -> str:
    """Naive suffix stem so 'fits'/'fitting' meet the corpus's 'fit'."""
    t = token.rstrip("'")
    for suffix in ("ingly", "edly", "ing", "ed", "es", "s"):
        if t.endswith(suffix) and len(t) - len(suffix) >= 3:
            return t[: -len(suffix)]
    return t


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for raw in _TOKEN_RE.findall((text or "").lower()):
        if len(raw) < _MIN_TOKEN_LEN or raw in _STOPWORDS:
            continue
        out.add(_stem(raw))
    return out


def _normalize_strand_keys(weights: dict[str, float] | None) -> dict[str, float]:
    """Map a strand vector's keys to canonical lowercase strand keys.

    Vectors arrive under two vocabularies: thread/item weights use
    lowercase strand keys (``word``/``people``/...) while archetype
    weights use plain-spoken names (``Voice``/``Heart``/...).
    PLAIN_TO_KEY (``local_ai/council/archetypes.py``) is the single
    source of truth for the mapping. Keys already in key form pass
    through unchanged; unknown keys pass through lowercased. Without
    this mapping the key sets are disjoint and every cross-vocabulary
    cosine is 0.0.
    """
    by_lower = {k.lower(): v for k, v in PLAIN_TO_KEY.items()}
    return {
        by_lower.get(str(k).strip().lower(), str(k).strip().lower()): v
        for k, v in (weights or {}).items()
    }


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity over canonical strand keys.

    Strand vectors arrive from different stores under different key
    vocabularies (archetype weights use display names); both sides
    are mapped through PLAIN_TO_KEY first, so the comparison must
    not depend on that accident.
    """
    norm_a = {k: float(v) for k, v in _normalize_strand_keys(a).items()}
    norm_b = {k: float(v) for k, v in _normalize_strand_keys(b).items()}
    dot = sum(norm_a.get(k, 0.0) * v for k, v in norm_b.items())
    mag_a = math.sqrt(sum(v * v for v in norm_a.values()))
    mag_b = math.sqrt(sum(v * v for v in norm_b.values()))
    if mag_a <= 0 or mag_b <= 0:
        return 0.0
    return dot / (mag_a * mag_b)


@dataclass(frozen=True)
class _FocusCorpus:
    focus_terms: frozenset[str]


_FOCUS_CORPORA: dict[str, _FocusCorpus] | None = None
_FOCUS_CORPORA_LOCK = threading.Lock()


def _focus_corpora() -> dict[str, _FocusCorpus]:
    """Per-seat focus-term sets, built once from the P0 registry.

    Focus terms only — periphery alone never opens the gate, the
    same discipline as P1's "attention comes from jurisdiction
    first." Terms in >= _DF_DROP seats' corpora are dropped.
    """
    global _FOCUS_CORPORA
    if _FOCUS_CORPORA is not None:
        return _FOCUS_CORPORA
    with _FOCUS_CORPORA_LOCK:
        if _FOCUS_CORPORA is not None:
            return _FOCUS_CORPORA
        raw: dict[str, set[str]] = {}
        doc_freq: dict[str, int] = {}
        for seat in stock_archetype_ids():
            record = get_jurisdiction(seat)
            if record is None:
                continue
            terms = _tokens(record.focus)
            raw[seat] = terms
            for term in terms:
                doc_freq[term] = doc_freq.get(term, 0) + 1
        _FOCUS_CORPORA = {
            seat: _FocusCorpus(
                frozenset(t for t in terms if doc_freq.get(t, 0) < _DF_DROP)
            )
            for seat, terms in raw.items()
        }
        return _FOCUS_CORPORA


def _seat_strand_vectors() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for seat in stock_archetype_ids():
        arch = get_archetype(seat)
        if arch is not None and arch.strand_weights:
            out[seat] = dict(arch.strand_weights)
    return out


@dataclass
class Cluster:
    """A cohesive group of evidence items — one candidate story.

    ``cohesion`` names the links that formed the cluster, so a
    proposal stays inspectable back to the pre-filter's reasons.
    """

    items: list[EvidenceItem]
    cohesion: list[str] = field(default_factory=list)

    def evidence_keys(self) -> list[str]:
        return sorted(item.evidence_key() for item in self.items)

    def tokens(self) -> set[str]:
        out: set[str] = set()
        for item in self.items:
            out |= _tokens(item.text)
        return out

    def entity_refs(self) -> set[str]:
        return {i.entity_ref for i in self.items if i.entity_ref}


def _linked(a: EvidenceItem, b: EvidenceItem) -> str | None:
    """One cohesion reason between two items, or None.

    Links are deliberately narrow: a shared entity (the same thing
    in the world), a shared conversation anchor (Slice A — the
    items' conversations were anchored to the same entity; a
    grouping hint, NOT same-thing attribution, §4.6-R), at least
    two shared distinctive tokens (the same ground in words), or
    genuinely similar strand vectors. Any one link is enough to
    join; no link means no cluster, however many items the batch
    holds.
    """
    if a.entity_ref and a.entity_ref == b.entity_ref:
        return f"shared entity {a.entity_ref}"
    if (
        anchor_channel_enabled()
        and a.anchor_ref
        and a.anchor_ref == b.anchor_ref
    ):
        return f"shared conversation anchor {a.anchor_ref}"
    shared = _tokens(a.text) & _tokens(b.text)
    if len(shared) >= _TOKEN_COHESION_MIN:
        return f"shared tokens {sorted(shared)[:4]}"
    if a.strand_weights and b.strand_weights:
        sim = _cosine(a.strand_weights, b.strand_weights)
        if sim >= _STRAND_COHESION_MIN:
            return f"strand similarity {sim:.2f}"
    return None


def cluster_items(items: list[EvidenceItem]) -> list[Cluster]:
    """Union-find clustering over the pre-filter's link rules.

    Singletons are returned as one-item clusters — they can never
    birth a thread (birth needs >= 2 items, audit Part II §5), but
    they can extend a live thread they overlap. Clustering is
    deterministic: items keep batch order inside each cluster, and
    clusters sort by their first item's batch position.
    """
    parent = list(range(len(items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    links: dict[int, list[str]] = {}
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            reason = _linked(items[i], items[j])
            if reason is not None:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
                links.setdefault(find(i), []).append(reason)
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    clusters = [
        Cluster(
            items=[items[i] for i in idxs],
            cohesion=sorted(set(links.get(root, []))),
        )
        for root, idxs in sorted(groups.items(), key=lambda kv: kv[1][0])
    ]
    return clusters


# ---------------------------------------------------------------------------
# Dismissal signatures — content-addressed, so new evidence re-opens
# ---------------------------------------------------------------------------


def birth_signature_from_keys(keys: Iterable[str]) -> str:
    """The birth signature over evidence keys ("<kind>:<id>").

    The keys-based core of :func:`birth_signature`: callers that
    hold a proposal's evidence as store rows (the review surface,
    recording a rejection) rebuild the identical signature from
    the rows' (ref_kind, ref_id) pairs.
    """
    return "birth:" + "|".join(sorted(keys))


def birth_signature(items: Iterable[EvidenceItem]) -> str:
    return birth_signature_from_keys(item.evidence_key() for item in items)


def extension_signature_from_keys(
    thread_id: str, keys: Iterable[str]
) -> str:
    """The extension signature over evidence keys — the
    keys-based core of :func:`extension_signature`, for callers
    holding store rows rather than EvidenceItems."""
    return f"extension:{thread_id}:" + "|".join(sorted(keys))


def extension_signature(thread_id: str, items: Iterable[EvidenceItem]) -> str:
    return extension_signature_from_keys(
        thread_id, (item.evidence_key() for item in items)
    )


def fitting_signature_from_keys(
    thread_id: str, lens_id: str, keys: Iterable[str]
) -> str:
    """The fitting signature: one lens placement on one thread,
    over the evidence keys the proposal cites.

    The placement is (thread, lens) — the fitting model carries
    no fitted-to axis beyond the thread, so thread + lens IS the
    placement identity the record supports. The grounds are the
    cited evidence keys ("<kind>:<id>", the same content
    addressing as births/extensions), so reordered citations and
    rebuilt evidence rows (new row ids, same refs) produce the
    identical signature, while a different lens, a different
    thread, or genuinely different cited evidence reopens.
    """
    return f"fitting:{thread_id}:{lens_id}:" + "|".join(sorted(keys))


def correspondence_signature_from_fields(
    thread_ids: Iterable[str],
    proposed_relationship: str,
    mapping: dict | None,
    keys: Iterable[str],
) -> str:
    """The correspondence signature: one relation between the
    same threads, over the evidence keys the proposal cites.

    The commitment is the record's own relation identity — the
    ``proposed_relationship`` statement plus the ``mapping`` of
    which elements parallel which. Direction, where the relation
    is directional, is borne by those fields (the stored thread
    pair is sorted and carries no direction), so the reverse
    relation or a different relation over the same pair produces
    a different signature, while the thread pair alone never
    keys anything. The relation fields enter as a digest of
    their canonical form (whitespace-collapsed relationship;
    mapping serialized with sorted keys), so citation-order,
    mapping-key-order, and evidence-row churn cannot make the
    same commitment look new; the grounds are the cited evidence
    keys, content-addressed exactly as births/extensions.
    """
    relation = {
        "relationship": " ".join((proposed_relationship or "").split()),
        "mapping": mapping or {},
    }
    digest = hashlib.sha256(
        json.dumps(
            relation,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:16]
    threads = "+".join(sorted(thread_ids))
    return f"correspondence:{threads}:{digest}:" + "|".join(sorted(keys))


# ---------------------------------------------------------------------------
# Offer identities + decline consultation (increment B, proposal §§4–7)
# ---------------------------------------------------------------------------
# An offer is a steward proposal put to the visitor for verdict: a
# proposed birth or a proposed extension. A decline attaches at a
# scope — one proposal (invitation), everything about X (subject),
# or a kind of invitation (class) — and is stored as a dismissal
# row whose signature is the scoped key, not a content signature.
# The two dismissal regimes are independent: thread-candidate
# dismissal stays per-signature/content-addressed (new evidence may
# propose a NEW candidate), while offer decline is semantic/scoped
# (new evidence never reopens it, rewording never resurrects it).
# Only an explicit visitor lift, respecting scope, clears a decline.

#: Offer scope → dismissal kind (proposal §7).
OFFER_KIND_BY_SCOPE: dict[str, str] = {
    "invitation": "offer_invitation",
    "subject": "offer_subject",
    "class": "offer_class",
}

#: Closed class vocabulary (proposal §4.3): proposal kinds plus
#: generation change kinds, plus the reading slot so the vocabulary
#: is exhaustive over what derivation proposes. Classes are
#: boundaries on OFFERS (presentation), never permission to
#: process data (proposal §6.4).
CLASS_LABELS: tuple[str, ...] = (
    "birth",
    "extension:reading",
    "extension:extended",
    "extension:contradicted",
    "extension:milestone",
    "extension:reopened",
)


def invitation_key(
    thread_ref: str, kind: str, slot: str, evidence_keys: Iterable[str]
) -> str:
    """One proposal's invitation identity (proposal §4.1).

    ``thread_ref`` is the thread id for extensions, the literal
    "birth" for births. The identity is derived from provenance
    (which evidence, which thread, which slot), never from prose —
    so rewording alone never evades it, and genuinely new evidence
    (or a different slot) is a new invitation.
    """
    return f"inv:{thread_ref}:{kind}:{slot}:" + "|".join(sorted(evidence_keys))


def _dominant_entity_ref(refs: Iterable[str | None]) -> str | None:
    """Most frequent entity ref; ties break lexicographically first.

    Deterministic: the same evidence always yields the same subject
    key, so a decline recorded for it keeps matching.
    """
    counts: Counter[str] = Counter(r for r in refs if r)
    if not counts:
        return None
    top = max(counts.values())
    return sorted(r for r, n in counts.items() if n == top)[0]


def subject_key_for_thread(
    store: NarrativeStore,
    user_id: str,
    thread: NarrativeThread,
    *,
    evidence_rows: Any = None,
) -> tuple[str | None, str]:
    """An offer's subject key for a thread + its precision tag
    (proposal §4.2, revised order: precision first).

    PRECISE: the thread's dominant entity_ref across annotated
    evidence (rows without annotations read NULL and don't
    participate — honest unknown, never inferred). COARSE: else
    the thread's scope label when set and non-empty (a broad
    classification, never the primary identity). UNKNOWN: else —
    no entity, no scope. Title fallback is deliberately NOT used:
    titles are unstable working text.

    ``evidence_rows`` (increment D): when the caller already holds
    the thread's evidence rows (e.g. from a single-acquisition
    snapshot), pass them to avoid a second store read; the
    computation is identical either way.
    """
    if evidence_rows is None:
        evidence_rows = store.evidence_for(user_id, thread.id)
    entity = _dominant_entity_ref(row.entity_ref for row in evidence_rows)
    if entity is not None:
        return entity, "precise"
    if thread.scope and thread.scope.strip():
        return thread.scope, "coarse"
    return None, "unknown"


def subject_key_for_cluster(
    cluster: Cluster,
) -> tuple[str | None, str]:
    """An offer's subject key for a birth cluster + precision tag.

    Clusters carry no scope label (scope is a thread field), so a
    birth subject is either PRECISE (dominant entity_ref across
    the cluster's items) or UNKNOWN.
    """
    entity = _dominant_entity_ref(i.entity_ref for i in cluster.items)
    if entity is not None:
        return entity, "precise"
    return None, "unknown"


def class_key(label: str) -> str:
    """A class scope's stored key for a class label."""
    return f"class:{label}"


def record_offer_decline(
    store: NarrativeStore, user_id: str, *, scope: str, key: str
) -> Any:
    """Record a visitor's refusal of an offer at a scope.

    A user act (called by E/H surfaces, never by derivation).
    ``key`` is the §4 key: a full invitation key for scope
    "invitation"; a raw subject key (or a full "subj:" key) for
    "subject"; a raw class label (or a full "class:" key) for
    "class". Recording the same decline twice returns the existing
    row (the generic path dedupes). Recording never deletes or
    alters the thread, reading, or change that was declined.
    """
    if scope not in OFFER_KIND_BY_SCOPE:
        raise ValueError(f"unknown offer scope: {scope!r}")
    if not str(key or "").strip():
        raise ValueError("an offer decline needs a non-empty key")
    if scope == "invitation":
        if not str(key).startswith("inv:"):
            raise ValueError("an invitation key starts with 'inv:'")
        signature = str(key)
    elif scope == "subject":
        signature = (
            str(key) if str(key).startswith("subj:") else f"subj:{key}"
        )
    else:
        label = str(key)
        if label.startswith("class:"):
            label = label[len("class:"):]
        if label not in CLASS_LABELS:
            raise ValueError(f"unknown offer class: {label!r}")
        signature = f"class:{label}"
    return store.record_dismissal(
        user_id, kind=OFFER_KIND_BY_SCOPE[scope], signature=signature
    )


def consult_offer_declines(
    *,
    dismissed_pairs: Any,
    has_subject_dismissal: bool,
    invitation_key: str | None = None,
    subject_key: str | None = None,
    subject_precision: str | None = None,
    class_label: str | None = None,
) -> str | None:
    """Pure offer-decline consultation over an already-fetched set.

    Increment D: the read model consults over a single-acquisition
    snapshot's dismissal rows (no store calls mid-response, so
    consultation coheres with content and totals). ``dismissed_pairs``
    is the set of (kind, signature) dismissal rows standing for the
    user; ``has_subject_dismissal`` is whether any offer_subject
    row stands. The matching logic is identical to
    :func:`is_offer_declined` — that function is now a thin wrapper
    over this one, so the two can never drift apart.
    """
    dismissed = set(dismissed_pairs)
    if invitation_key and ("offer_invitation", invitation_key) in dismissed:
        return "invitation"
    subject_ambiguous_candidate = False
    if subject_key is not None:
        sig = (
            subject_key
            if subject_key.startswith("subj:")
            else f"subj:{subject_key}"
        )
        if ("offer_subject", sig) in dismissed:
            return "subject"
        prec = (
            subject_precision
            if subject_precision in ("precise", "coarse", "unknown")
            else "unknown"
        )
        if prec != "precise":
            subject_ambiguous_candidate = True
    elif subject_precision is not None:
        # No key, but a precision was computed: never assume a
        # precise clearance without a key to match on.
        subject_ambiguous_candidate = True
    if class_label:
        sig = (
            class_label
            if class_label.startswith("class:")
            else f"class:{class_label}"
        )
        if ("offer_class", sig) in dismissed:
            return "class"
    if subject_ambiguous_candidate and has_subject_dismissal:
        return "ambiguous"
    return None


def is_offer_declined(
    store: NarrativeStore,
    user_id: str,
    *,
    invitation_key: str | None = None,
    subject_key: str | None = None,
    subject_precision: str | None = None,
    class_label: str | None = None,
) -> str | None:
    """Consult offer declines: matched scope, "ambiguous", or None.

    This is the H seam (proposal §6.5): H calls it before voicing
    any UNSOLICITED offer, never for visitor-initiated discussion
    (which is not an offer and is never consulted). Consultation
    is a pure query: it creates no rows and blocks nothing by
    itself — callers decide what a match or an ambiguous result
    does. Exact equality first: a key literally equal to a declined
    key matches, whatever its precision. Ambiguity (proposal
    §4.5): a coarse or unknown subject key is AMBIGUOUS exactly
    when at least one subject decline stands — never a silent
    clearance, never a false match. A precise mismatch proceeds.
    A call with no subject key AND no precision skips the subject
    check (the caller did not compute a subject — distinct from
    unknown). Matches beat ambiguity: a definite block names the
    reason; ambiguity only withholds when nothing matched. This
    function never raises for consultation inputs (derivation
    must never break on a bad label): an unrecognized precision
    is treated as unknown, and an unknown class label simply does
    not match.
    """
    rows = store.dismissals_for(user_id)
    return consult_offer_declines(
        dismissed_pairs={(r.kind, r.signature) for r in rows},
        has_subject_dismissal=any(
            r.kind == "offer_subject" for r in rows
        ),
        invitation_key=invitation_key,
        subject_key=subject_key,
        subject_precision=subject_precision,
        class_label=class_label,
    )


def clear_offer_decline(
    store: NarrativeStore, user_id: str, *, scope: str, key: str
) -> bool:
    """Clear exactly one offer decline (a visitor lift).

    Clearing is a user act and is never performed by derivation.
    Deletes exactly the matching row; True if a row was deleted.
    Scoped exactly: clearing one scope never clears another, and
    never clears the thread-candidate regime's rows.
    """
    if scope not in OFFER_KIND_BY_SCOPE:
        raise ValueError(f"unknown offer scope: {scope!r}")
    if not str(key or "").strip():
        raise ValueError("clearing a decline needs a non-empty key")
    if scope == "invitation":
        signature = str(key)
    elif scope == "subject":
        signature = (
            str(key) if str(key).startswith("subj:") else f"subj:{key}"
        )
    else:
        signature = (
            str(key)
            if str(key).startswith("class:")
            else f"class:{key}"
        )
    return store.clear_dismissal(
        user_id, kind=OFFER_KIND_BY_SCOPE[scope], signature=signature
    )


# ---------------------------------------------------------------------------
# Thread overlap — by ref identity and entity, never by walking links
# ---------------------------------------------------------------------------


def _thread_evidence_keys(
    store: NarrativeStore, user_id: str, thread: NarrativeThread
) -> set[str]:
    return {
        f"{row.ref_kind}:{row.ref_id}"
        for row in store.evidence_for(user_id, thread.id)
    }


def _thread_entity_refs(
    store: NarrativeStore, user_id: str, thread: NarrativeThread
) -> set[str]:
    """The "<type>:<id>" identities the thread's evidence is about.

    Only rows derivation annotated carry one; rows from other
    writers read NULL and simply don't participate in entity
    matching — honest unknown, never inferred.
    """
    return {
        row.entity_ref
        for row in store.evidence_for(user_id, thread.id)
        if row.entity_ref
    }


def _live_threads(store: NarrativeStore, user_id: str) -> list[NarrativeThread]:
    """Threads that may receive extension proposals.

    Archived / retired / resolved threads are excluded on purpose:
    new evidence about a settled story is a reopening question for
    the user or an S3 detector, not an automatic proposal.
    """
    out: list[NarrativeThread] = []
    for status in EXTENDABLE_STATUSES:
        out.extend(store.threads_for(user_id, status=status))
    return out


def _overlapping_threads(
    store: NarrativeStore,
    user_id: str,
    cluster: Cluster,
    live: list[NarrativeThread] | None = None,
) -> list[NarrativeThread]:
    """Live threads sharing a ref identity or an entity identity.

    Two ways a cluster belongs to a thread: it contains evidence
    already attached to the thread (same record), or it concerns
    the same thing in the world (same "<type>:<id>", recorded on
    the thread's evidence rows by derivation at attach time). This
    is the ONLY thread-matching S1 performs, and it reads
    thread_evidence rows directly. It never touches the
    containment-link rows: containment is inert storage until a
    phase brings the cycle discipline (audit Part XI).
    """
    if live is None:
        live = _live_threads(store, user_id)
    cluster_keys = set(cluster.evidence_keys())
    cluster_entities = cluster.entity_refs()
    out: list[NarrativeThread] = []
    for thread in live:
        thread_keys = _thread_evidence_keys(store, user_id, thread)
        if cluster_keys & thread_keys:
            out.append(thread)
            continue
        if cluster_entities & _thread_entity_refs(store, user_id, thread):
            out.append(thread)
    return out


def _has_jurisdiction_candidacy(cluster: Cluster) -> bool:
    """Does this cluster touch any seat's jurisdiction?

    Focus-term hit on the cluster's tokens, or strand alignment
    >= P1's bar for an item carrying a strand vector. Periphery
    alone never qualifies — attention comes from jurisdiction first.
    """
    tokens = cluster.tokens()
    corpora = _focus_corpora()
    if any(tokens & corpus.focus_terms for corpus in corpora.values()):
        return True
    vectors = _seat_strand_vectors()
    for item in cluster.items:
        if not item.strand_weights:
            continue
        if any(
            _cosine(item.strand_weights, vec) >= _STRAND_ALIGNMENT_MIN
            for vec in vectors.values()
        ):
            return True
    return False


def _cluster_strand_weights(items: list[EvidenceItem]) -> dict[str, float]:
    """Mean of member items' strand vectors, mapped to strand keys.

    Only items that carry weights contribute; a cluster with no weighed
    item yields {} (unchanged behavior — the thread is born weightless,
    never with an invented vector). The mean is renormalized to sum
    1.0 when any weight is present; strands with zero weight are
    omitted (a key present means the thread has weight on that
    strand). The mapping is PLAIN_TO_KEY (item vectors are
    plain-name-keyed, thread weights are strand-key-keyed by the
    store's contract).
    """
    present = [i.strand_weights for i in items if i.strand_weights]
    if not present:
        return {}
    mean = {
        name: sum(w.get(name, 0.0) for w in present) / len(present)
        for name in PLAIN_TO_KEY
    }
    total = sum(mean.values())
    if total <= 0:
        return {}
    keyed = {PLAIN_TO_KEY[name]: v / total for name, v in mean.items()}
    return {key: value for key, value in keyed.items() if value > 0}


def _recompute_thread_weights(
    thread: NarrativeThread,
    new_items: list[EvidenceItem],
    prior_attached_count: int,
) -> dict[str, float]:
    """Recomputed thread weights after an extension (founder ruling Q3).

    The mean over all attached evidence, maintained incrementally:
    the thread's current weights are the mean of the strand vectors
    of all previously attached weighed items, so they re-enter the
    mean weighted by the number of evidence rows attached before
    this extension. Each new weighed item enters once. Exact when
    every previously attached item carried weights; otherwise the
    old aggregate is weighted by the attached-row count, which
    imputes the aggregate to unweighed old rows — a bounded
    approximation, never a synthetic vector. A thread with no
    weighed evidence on either side stays {}.
    """
    old = thread.strand_weights or {}
    new_weighed = [i.strand_weights for i in new_items if i.strand_weights]
    if not old and not new_weighed:
        return {}
    acc: dict[str, float] = {}
    total_weight = 0.0
    if old:
        old_weight = float(prior_attached_count) if prior_attached_count > 0 else 1.0
        total_weight += old_weight
        for key, value in old.items():
            acc[key] = acc.get(key, 0.0) + old_weight * value
    for weights in new_weighed:
        total_weight += 1.0
        for name, value in weights.items():
            key = PLAIN_TO_KEY.get(name)
            if key is None:
                continue  # unmappable plain name: the store would refuse it
            acc[key] = acc.get(key, 0.0) + value
    if total_weight <= 0:
        return {}
    mean = {key: value / total_weight for key, value in acc.items()}
    total = sum(mean.values())
    if total <= 0:
        return {}
    # Strands with zero weight are omitted, matching the birth
    # aggregate (a key present means the thread has weight there).
    return {
        key: value / total for key, value in mean.items() if value > 0
    }


def _refresh_thread_weights_after_extension(
    store: NarrativeStore,
    user_id: str,
    thread: NarrativeThread,
    new_items: list[EvidenceItem],
) -> None:
    """Recompute + write a thread's weights after an extension lands.

    The prior attached-row count is the current row count minus this
    extension's new items — each new item added exactly one row,
    because derive_batch filters the extension to not-yet-attached
    evidence and attach is idempotent. Best-effort: the weights are
    a derived summary, and a failure here must never fail the
    extension itself (the evidence already landed; the next
    extension recomputes again). No-op when nothing is weighed.
    """
    try:
        fresh = store.get_thread(user_id, thread.id) or thread
        attached = store.evidence_for(user_id, thread.id)
        prior_attached = max(len(attached) - len(new_items), 0)
        weights = _recompute_thread_weights(fresh, new_items, prior_attached)
        if weights == (fresh.strand_weights or {}):
            return
        store.set_thread_strand_weights(user_id, thread.id, weights)
    except Exception:
        logger.exception(
            "narrative: thread weight refresh failed for %s", thread.id
        )


# ---------------------------------------------------------------------------
# Generation — one call per candidate, structured state or decline
# ---------------------------------------------------------------------------

_BIRTH_PROMPT = """\
You are the Narrative Steward's slow-path analyst. You do NOT speak
to the user and you are not any council voice. You read evidence and
propose, in plain system language, whether these records belong to
one unfolding story.

Evidence (verbatim words / records):
{evidence}

If these records do NOT belong to one unfolding story, reply with
exactly:
NONE

Otherwise reply with exactly one JSON object and nothing else:
{{"title": "short working title", "tensions": ["..."],
  "open_questions": ["..."], "milestones": ["..."],
  "scales": ["personal"], "primary_scale": "personal"}}

Rules: every tension, question, and milestone must trace to the
evidence above — invent no facts, people, or events. Scales are free
labels for the resolution(s) at which this story is intelligible
(for example personal, institutional); they are not a fixed ladder,
and primary_scale, when given, must be one of scales. Keep every
string short.
"""

_EXTENSION_PROMPT = """\
You are the Narrative Steward's slow-path analyst. You do NOT speak
to the user and you are not any council voice. A thread already
exists with the standing reading below, and new evidence has
arrived. Propose, in plain system language, an updated reading —
and, only if the new evidence genuinely moves the story, the kind
of move it is.

Standing reading:
{standing}

New evidence (verbatim words / records):
{evidence}

If the new evidence does NOT genuinely bear on this thread, reply
with exactly:
NONE

Otherwise reply with exactly one JSON object and nothing else:
{{"tensions": ["..."], "open_questions": ["..."],
  "milestones": ["..."], "scales": ["personal"],
  "primary_scale": "personal",
  "change_kind": "extended"}}

Rules: every tension, question, and milestone must trace to the
evidence — invent no facts, people, or events. Scales are free
labels, as above; primary_scale, when given, must be one of
scales. change_kind must be one of extended, contradicted,
milestone, reopened — or null when the new evidence informs the
reading without moving the story in one of those ways. Never
propose resolved or retired: ending a story is the user's call.
"""


def _render_evidence(items: list[EvidenceItem]) -> str:
    lines = []
    for i, item in enumerate(items, 1):
        text = (item.text or "").strip() or "(record with no words)"
        lines.append(f"{i}. [{item.evidence_key()}] {text[:600]}")
    return "\n".join(lines)


def _render_standing(thread: NarrativeThread, store: NarrativeStore) -> str:
    """The thread's standing reading as generation context, or a
    note that the thread has none yet (a nascent thread's first
    reading is still an update, not a birth)."""
    if not thread.standing_reading_id:
        return "(no standing reading yet)"
    readings = store.readings_for(thread.user_id, thread.id, status="accepted")
    for reading in readings:
        if reading.id == thread.standing_reading_id:
            payload = reading.reading or {}
            return json.dumps(payload, ensure_ascii=False)[:1200]
    return "(no standing reading yet)"


def _parse_proposal(raw: str | None) -> dict | None:
    """Parse a generation into proposal state, or None = decline.

    Strict on shape, forgiving on nothing that matters: unparseable
    output, a non-object, or wrong-typed core fields decline the
    whole proposal — no row. An invalid change_kind degrades to
    null (reading proposed, no change) rather than failing the
    reading, because the change is the optional half of the pair.
    """
    text = (raw or "").strip()
    if not text or text.upper() == "NONE" or text.upper().startswith("NONE\n"):
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("tensions", "open_questions", "milestones", "scales"):
        value = data.get(key) or []
        if not isinstance(value, list) or not all(
            isinstance(v, str) for v in value
        ):
            return None
        out[key] = list(value)
    title = data.get("title")
    out["title"] = title if isinstance(title, str) else ""
    primary = data.get("primary_scale")
    out["primary_scale"] = primary if isinstance(primary, str) else None
    # Pre-validate the scale rule the store enforces, BEFORE any
    # write: a primary scale outside scales would strand a birth
    # thread (created) with a refused reading. Decline instead.
    if out["primary_scale"] is not None and out["primary_scale"] not in out["scales"]:
        return None
    change_kind = data.get("change_kind")
    out["change_kind"] = (
        change_kind if change_kind in GENERATION_CHANGE_KINDS else None
    )
    return out


def _annotate_entities(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
    items: list[EvidenceItem],
) -> None:
    """Record what attached evidence is about (store's index).

    Only items carrying an entity_ref annotate; the rest keep
    NULL (honest unknown). Failures here never fail the proposal
    itself — annotation is an index, not the record.
    """
    mapping = {
        (item.ref.kind, item.ref.ref_id): item.entity_ref
        for item in items
        if item.entity_ref
    }
    if not mapping:
        return
    try:
        store.annotate_evidence_entities(user_id, thread_id, mapping)
    except Exception:
        logger.exception("narrative: entity annotation failed")


def _resolve_generate_fn(generate_fn: GenerateFn | None) -> GenerateFn | None:
    if generate_fn is not None:
        return generate_fn
    try:
        from local_ai.agent_intake.llm_keys import generate as _gen

        return _gen
    except Exception as e:
        # Records-first (increment A) makes no-backend routine, not
        # exceptional: records land and prose is deferred. Log the
        # reason once per resolution at warning, without a traceback.
        logger.warning(
            "narrative: no generation backend available (%s); "
            "records-first will defer prose",
            e,
        )
        return None


# ---------------------------------------------------------------------------
# Derivation entry points
# ---------------------------------------------------------------------------


@dataclass
class DerivationResult:
    """What one derivation run did — counts, ids, and skips.

    ``calls`` counts generations actually spent. ``skipped`` records
    every cluster/thread the pre-filter or the durability rules
    passed over, with the reason, so a run that proposes nothing
    still explains itself instead of looking broken.
    """

    births: list[str] = field(default_factory=list)
    readings: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    declines: int = 0
    calls: int = 0
    skipped: list[str] = field(default_factory=list)
    #: Thread ids whose records landed while prose is still owed
    #: (records-first, increment A §6). Deferred is not success and
    #: not decline: the ledger holds the evidence, the deferred row
    #: holds the obligation, and the worker settles it later.
    deferred: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "births": list(self.births),
            "readings": list(self.readings),
            "changes": list(self.changes),
            "declines": self.declines,
            "calls": self.calls,
            "skipped": list(self.skipped),
            "deferred": list(self.deferred),
        }


def _deferred_texts(items: list[EvidenceItem]) -> list[dict]:
    """Verbatim prompt inputs for a deferred row (parallel to refs).

    The worker cannot re-derive prompt text from evidence rows:
    text is prompt context, never stored as evidence. The deferred
    row therefore carries the texts so rendering never depends on
    the activity log surviving. Deleted with the row on completion
    or thread deletion.
    """
    return [{"key": item.evidence_key(), "text": item.text or ""} for item in items]


def _admitted_from_items(
    items: list[EvidenceItem],
) -> list[tuple[str, str, str]] | None:
    """The D2 admitted set for a funnel call, from stamped items.

    Returns None when NO item carries a provenance stamp — the
    pre-D2 path, where the funnels never consult the set. When any
    item is stamped (an eligibility evaluation ran), the set holds
    exactly the stamped items: an unstamped item in a stamped run
    is simply absent, so a write naming it is refused at the
    funnel and aborted at the trigger (§9.2 layering).
    """
    stamped = [
        (item.ref.kind, item.ref.ref_id, item.source_time)
        for item in items
        if item.source_time
    ]
    if not stamped:
        return None
    return stamped  # type: ignore[return-value]


def _birth_records_first(
    user_id: str,
    cluster: Cluster,
    store: NarrativeStore,
    result: DerivationResult,
) -> None:
    """Records-first birth (increment A §6): thread + founding
    evidence + deferred-prose row in ONE commit, prose owed.

    The thread is born with a working title ("Untitled thread"):
    with no generation to propose one, retitling on prose
    completion is later work. The run reports deferred, never
    success and never decline: the ledger holds the evidence, the
    deferred row holds the obligation.
    """
    try:
        thread = store.create_thread_with_deferred_prose(
            user_id,
            origin="steward_proposal",
            title="Untitled thread",
            evidence_refs=[item.ref for item in cluster.items],
            deferred_kind="birth",
            evidence_signature=birth_signature(cluster.items),
            evidence_texts=_deferred_texts(cluster.items),
            strand_weights=_cluster_strand_weights(cluster.items),
            admitted_sources=_admitted_from_items(cluster.items),
        )
    except Exception:
        logger.exception("narrative: records-first birth failed")
        result.declines += 1
        return
    _annotate_entities(store, user_id, thread.id, cluster.items)
    result.births.append(thread.id)
    result.deferred.append(thread.id)


def _extension_records_first(
    user_id: str,
    thread: NarrativeThread,
    new_items: list[EvidenceItem],
    store: NarrativeStore,
    result: DerivationResult,
) -> None:
    """Records-first extension (increment A §6): attach the new
    evidence + deferred-prose row in ONE commit, prose owed.

    No change is recorded here: a change kind comes from a
    proposal, and with no generation there is no proposal. (The
    worker likewise renders readings only — invariant 2 forbids
    recording a change on already-attached evidence.)
    """
    try:
        store.attach_evidence_with_deferred_prose(
            user_id,
            thread.id,
            [item.ref for item in new_items],
            deferred_kind="extension",
            evidence_signature=extension_signature(thread.id, new_items),
            evidence_texts=_deferred_texts(new_items),
            admitted_sources=_admitted_from_items(new_items),
        )
    except Exception:
        logger.exception("narrative: records-first extension failed")
        result.declines += 1
        return
    _annotate_entities(store, user_id, thread.id, new_items)
    _refresh_thread_weights_after_extension(store, user_id, thread, new_items)
    result.deferred.append(thread.id)


def _propose_birth(
    user_id: str,
    cluster: Cluster,
    store: NarrativeStore,
    generate_fn: GenerateFn,
    result: DerivationResult,
) -> None:
    """One generation → one nascent steward_proposal thread + reading.

    The thread is a proposal in the store's own terms: status
    nascent, origin steward_proposal, user-editable working title.
    Nothing about it is accepted, surfaced, or trained on by S1.
    A generation FAILURE (raise) is not a decline: records-first
    lands the thread + evidence + deferred row instead. A NONE
    judgment or unparseable output IS a decline and lands nothing
    (re-derivation can retry it later, since nothing landed).
    """
    prompt = _BIRTH_PROMPT.format(evidence=_render_evidence(cluster.items))
    try:
        raw = generate_fn(
            prompt,
            provider_id="meta",
            user_id=user_id or None,
            operation="narrative-derivation",
            timeout=60,
        )
    except Exception:
        logger.exception(
            "narrative: birth generation failed; records-first"
        )
        _birth_records_first(user_id, cluster, store, result)
        return
    result.calls += 1
    proposal = _parse_proposal(raw)
    if proposal is None:
        result.declines += 1
        return
    try:
        thread = store.create_thread(
            user_id,
            origin="steward_proposal",
            title=proposal["title"],
            evidence_refs=[item.ref for item in cluster.items],
            strand_weights=_cluster_strand_weights(cluster.items),
            admitted_sources=_admitted_from_items(cluster.items),
        )
        # Annotate what the founding evidence is about, so later
        # batches can recognize this thread by entity, not only by
        # ref identity (the thread-extension path).
        _annotate_entities(store, user_id, thread.id, cluster.items)
        reading = store.propose_reading(
            user_id,
            thread.id,
            author="steward",
            reading={
                "tensions": proposal["tensions"],
                "open_questions": proposal["open_questions"],
                "milestones": proposal["milestones"],
                "cast_notes": {},
            },
            evidence_refs=[item.ref for item in cluster.items],
            scales=proposal["scales"],
            primary_scale=proposal["primary_scale"],
            admitted_sources=_admitted_from_items(cluster.items),
        )
    except ValueError:
        # Store validation refused the proposal (e.g. a primary scale
        # outside scales): the store's invariants outrank the
        # generation, and a refused proposal leaves no row.
        logger.exception("narrative: birth proposal refused by store")
        result.declines += 1
        return
    result.births.append(thread.id)
    result.readings.append(reading.id)


def _propose_extension(
    user_id: str,
    thread: NarrativeThread,
    new_items: list[EvidenceItem],
    store: NarrativeStore,
    generate_fn: GenerateFn,
    result: DerivationResult,
) -> None:
    """One generation → an optional change + a proposed reading.

    Order matters and is load-bearing: the change is recorded FIRST,
    while the new evidence is still new to the thread (invariant 2);
    the reading proposal follows and re-resolves the same evidence
    (attach is idempotent). Reversing the order would make every
    change impossible, because the reading's attach would consume
    the evidence's newness. A change the store refuses (evidence
    already attached, unknown kind) is skipped while the reading is
    still proposed — the reading is the durable half of the pair.
    A generation FAILURE (raise) is not a decline: records-first
    attaches the evidence + deferred row instead (no change — see
    _extension_records_first). A NONE judgment or unparseable
    output IS a decline and lands nothing.
    """
    prompt = _EXTENSION_PROMPT.format(
        standing=_render_standing(thread, store),
        evidence=_render_evidence(new_items),
    )
    try:
        raw = generate_fn(
            prompt,
            provider_id="meta",
            user_id=user_id or None,
            operation="narrative-derivation",
            timeout=60,
        )
    except Exception:
        logger.exception(
            "narrative: extension generation failed; records-first"
        )
        _extension_records_first(user_id, thread, new_items, store, result)
        return
    result.calls += 1
    proposal = _parse_proposal(raw)
    if proposal is None:
        result.declines += 1
        return
    # Increment B §6.4: post-generation class check. The change kind
    # is known only after generation, so a change-kind class decline
    # (e.g. extension:reopened) cannot be consulted pre-generation.
    # On match, DISCARD the whole proposal: no reading, no change
    # stored. The generation is already spent (calls incremented
    # above) — correctness over cost, and change-kind class declines
    # are expected to be rare. This is an OFFER boundary (enforced
    # before surfacing/storing), NOT a processing ban: a ban on
    # analyzing material in a way must be enforced BEFORE generation,
    # which B does not implement — B claims nothing about it.
    if proposal["change_kind"] and is_offer_declined(
        store, user_id, class_label=f"extension:{proposal['change_kind']}"
    ) == "class":
        logger.info(
            "narrative: extension change_kind %r declined by class; "
            "discarding proposal for thread %s",
            proposal["change_kind"],
            thread.id,
        )
        result.skipped.append("offer declined (class)")
        return
    refs = [item.ref for item in new_items]
    change_kind = proposal["change_kind"]
    change_recorded = False
    if change_kind:
        try:
            change = store.record_change(
                user_id, thread.id, kind=change_kind, evidence_refs=refs,
                admitted_sources=_admitted_from_items(new_items),
            )
            result.changes.append(change.id)
            change_recorded = True
        except ValueError:
            logger.exception(
                "narrative: extension change refused by store "
                "(thread %s)",
                thread.id,
            )
    try:
        reading = store.propose_reading(
            user_id,
            thread.id,
            author="steward",
            reading={
                "tensions": proposal["tensions"],
                "open_questions": proposal["open_questions"],
                "milestones": proposal["milestones"],
                "cast_notes": {},
            },
            evidence_refs=refs,
            scales=proposal["scales"],
            primary_scale=proposal["primary_scale"],
            admitted_sources=_admitted_from_items(new_items),
        )
    except ValueError:
        logger.exception("narrative: extension reading refused by store")
        result.declines += 1
        if change_recorded:
            # The change already attached the evidence, so the
            # weights still refresh even though the reading declined.
            _refresh_thread_weights_after_extension(
                store, user_id, thread, new_items
            )
        return
    # The reading's attach is the final attach on this path (the
    # change's attach, when one was recorded, covered the same
    # rows) — annotate once, idempotently.
    _annotate_entities(store, user_id, thread.id, new_items)
    _refresh_thread_weights_after_extension(store, user_id, thread, new_items)
    result.readings.append(reading.id)


def derive_batch(
    user_id: str,
    items: list[EvidenceItem],
    store: NarrativeStore,
    generate_fn: GenerateFn | None = None,
) -> DerivationResult:
    """Derive thread proposals from one batch of evidence. Never raises.

    Flow: cluster (deterministic) → per cluster, check dismissal
    memory and existing-thread coverage → birth path for eligible
    multi-item clusters, extension path for clusters overlapping a
    live thread. A batch re-analyzed with no new evidence produces
    zero new rows: births are covered by the threads they already
    created, and extensions find their evidence already attached.
    """
    result = DerivationResult()
    if not items:
        return result
    gen = _resolve_generate_fn(generate_fn)
    clusters = cluster_items(items)
    live = _live_threads(store, user_id)
    for cluster in clusters:
        # Tier gate, applied before any generation is spent: the
        # store would refuse a non-evidence ref anyway (invariant),
        # but refusing here costs zero calls instead of one. A
        # dramatization ref can never become derivation evidence by
        # any path — not by prompt, not by caller carelessness.
        inadmissible = [
            item for item in cluster.items
            if item.ref.tier is not RefTier.EVIDENCE
        ]
        if inadmissible:
            result.skipped.append(
                "cluster contains non-evidence-tier refs: "
                + ",".join(sorted({i.ref.kind for i in inadmissible}))
            )
            continue
        cluster_keys = set(cluster.evidence_keys())
        # --- extension path first: a cluster overlapping a live
        # thread is an update to that story, not a second story.
        overlapping = _overlapping_threads(store, user_id, cluster, live)
        handled_as_extension = False
        for thread in overlapping:
            thread_keys = _thread_evidence_keys(store, user_id, thread)
            new_items = [
                item for item in cluster.items
                if item.evidence_key() not in thread_keys
            ]
            if not new_items:
                result.skipped.append(
                    f"thread {thread.id}: cluster already in thread"
                )
                handled_as_extension = True
                continue
            # Increment B §6.2: offer declines first (the stronger,
            # semantic refusal), then the per-signature check —
            # both before records-first and before any generation.
            # Slot is "reading" pre-generation: the change kind (if
            # any) is not known until generation (§6.4 checks it
            # after parsing). A skipped extension attaches nothing.
            offer_inv = invitation_key(
                thread.id,
                "extension",
                "reading",
                [item.evidence_key() for item in new_items],
            )
            offer_subj, offer_prec = subject_key_for_thread(
                store, user_id, thread
            )
            offer = is_offer_declined(
                store,
                user_id,
                invitation_key=offer_inv,
                subject_key=offer_subj,
                subject_precision=offer_prec,
                class_label="extension:reading",
            )
            if offer == "ambiguous":
                result.skipped.append(
                    f"thread {thread.id}: offer ambiguous (subject)"
                )
                handled_as_extension = True
                continue
            if offer is not None:
                result.skipped.append(
                    f"thread {thread.id}: offer declined ({offer})"
                )
                handled_as_extension = True
                continue
            sig = extension_signature(thread.id, new_items)
            if store.is_dismissed(user_id, kind="extension", signature=sig):
                result.skipped.append(
                    f"thread {thread.id}: extension dismissed"
                )
                handled_as_extension = True
                continue
            # No separate "already proposed" check is needed: a
            # proposed reading always attaches its evidence (store
            # invariant), so re-analysis finds that evidence already
            # in the thread and takes the already-attached skip
            # above. Idempotency comes from the attach, not from a
            # second bookkeeping rule.
            if gen is None:
                # Records-first (§6): no backend is not a skip —
                # the evidence lands and the prose is owed.
                _extension_records_first(
                    user_id, thread, new_items, store, result
                )
                handled_as_extension = True
                continue
            try:
                _propose_extension(
                    user_id, thread, new_items, store, gen, result
                )
            except Exception:
                logger.exception(
                    "narrative: extension failed for thread %s", thread.id
                )
            handled_as_extension = True
        if handled_as_extension:
            # An overlapping cluster belongs to its thread(s); it is
            # never ALSO a birth candidate. A cluster overlapping
            # nothing falls through to the birth path below.
            continue
        # --- birth path: needs >= 2 items and jurisdiction candidacy.
        if len(cluster.items) < 2:
            result.skipped.append("singleton with no live-thread overlap")
            continue
        if not _has_jurisdiction_candidacy(cluster):
            result.skipped.append("cluster on nobody's ground")
            continue
        # Increment B §6.1: offer declines first, then the
        # per-signature check — both before records-first and
        # before any generation is spent.
        offer_inv = invitation_key(
            "birth", "birth", "birth", cluster.evidence_keys()
        )
        offer_subj, offer_prec = subject_key_for_cluster(cluster)
        offer = is_offer_declined(
            store,
            user_id,
            invitation_key=offer_inv,
            subject_key=offer_subj,
            subject_precision=offer_prec,
            class_label="birth",
        )
        if offer == "ambiguous":
            result.skipped.append("offer ambiguous (subject)")
            continue
        if offer is not None:
            result.skipped.append(f"offer declined ({offer})")
            continue
        sig = birth_signature(cluster.items)
        if store.is_dismissed(user_id, kind="thread_birth", signature=sig):
            result.skipped.append("birth dismissed")
            continue
        if _covered_by_thread(store, user_id, cluster_keys):
            result.skipped.append("cluster already covered by a thread")
            continue
        if gen is None:
            # Records-first (§6): no backend is not a skip — the
            # thread + evidence land and the prose is owed.
            _birth_records_first(user_id, cluster, store, result)
            continue
        try:
            _propose_birth(user_id, cluster, store, gen, result)
        except Exception:
            logger.exception("narrative: birth failed for a cluster")
    return result


def _covered_by_thread(
    store: NarrativeStore,
    user_id: str,
    cluster_keys: set[str],
) -> bool:
    """Is this cluster's whole evidence set already inside one thread?

    Coverage is per-thread, not across threads: evidence split
    across two threads is still a new story candidate, not a
    duplicate. Coverage checks threads in EVERY status, not just
    live ones: evidence already inside a resolved or archived
    thread must not be re-proposed as a brand-new story — a
    settled story is not quietly revived by re-proposal (the
    retirement durability rule, audit Part II §5). Only a
    user-driven dismissal or genuinely new evidence changes what
    may be proposed, and dismissal is checked before coverage.
    """
    for thread in store.threads_for(user_id):
        if cluster_keys <= _thread_evidence_keys(store, user_id, thread):
            return True
    return False


def analyze_for_threads(
    event: FellowshipEvent,
    store: NarrativeStore,
    generate_fn: GenerateFn | None = None,
    *,
    source_time: str | None = None,
) -> DerivationResult:
    """Audit Part II §3 entry point: one event → thread proposals.

    A single event can only EXTEND a live thread it overlaps; it
    can never birth one (birth needs >= 2 items, Part II §5). An
    event on nobody's ground, or overlapping nothing, spends zero
    generations and proposes nothing — the single-event call is
    where the pre-filter's thrift is most visible.

    ``source_time`` is the D2 eligibility stamp (§9.3) the live
    pipeline's evaluation produced for this event; it rides the
    item into the funnel calls' manifests.
    """
    item = event_to_item(event)
    if source_time:
        item = replace(item, source_time=source_time)
    return derive_batch(event.user_id, [item], store, generate_fn=generate_fn)


#: Lease for a deferred-prose render claim: comfortably longer than
#: the 60s generation timeout, so a slow render is never mistaken
#: for a dead one (increment A §6.2).
STEWARD_DEFERRED_LEASE_SECONDS = 300


@dataclass
class DeferredWorkResult:
    """What one deferred-prose worker pass did.

    ``rendered`` holds new reading ids; ``already_covered`` holds
    deferred row ids settled because a reading already covered the
    evidence (no duplicate rendered); ``settled_without_prose``
    holds row ids settled because the render yielded no usable
    prose (a NONE judgment or unparseable output — _parse_proposal
    cannot distinguish them, so both settle rather than retrying
    forever; the thread + evidence persist and a later extension
    may still propose a reading); ``failed`` holds row ids whose
    render attempt failed this pass: a caught generation raise
    releases the row to pending for retry on the next pass, while
    a transient store error leaves it rendering for lease-expiry
    retry; ``suppressed`` (increment B §6.3) holds one dict per
    deferred row settled as suppressed_by_decline (row id +
    matched refusal scope + key) — a distinct terminal outcome,
    never a completed render and never a deletion.
    """

    rendered: list[str] = field(default_factory=list)
    already_covered: list[str] = field(default_factory=list)
    settled_without_prose: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    suppressed: list[dict] = field(default_factory=list)
    #: Steward D2 (§§8.3/9.3): rows skipped because the completion's
    #: eligibility re-evaluation found their provenance at or
    #: before the erasure boundary. The row is released back to
    #: pending — never settled, never rendered — and the erasure
    #: operation's provenance audit owns its eventual removal.
    erasure_skipped: list[str] = field(default_factory=list)
    skipped_no_backend: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "rendered": list(self.rendered),
            "already_covered": list(self.already_covered),
            "settled_without_prose": list(self.settled_without_prose),
            "failed": list(self.failed),
            "suppressed": [dict(s) for s in self.suppressed],
            "erasure_skipped": list(self.erasure_skipped),
            "skipped_no_backend": self.skipped_no_backend,
        }


def _render_deferred_texts(evidence_texts: list[dict]) -> str:
    """Deferred prompt evidence, in _render_evidence's shape."""
    lines = []
    for i, entry in enumerate(evidence_texts, 1):
        key = str(entry.get("key", ""))
        text = (str(entry.get("text", "")) or "").strip() or "(record with no words)"
        lines.append(f"{i}. [{key}] {text[:600]}")
    return "\n".join(lines)


def _already_covered(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
    refs: list[SourceRef],
) -> bool:
    """Does a reading on this thread already cover these refs?

    Resolves refs to thread-evidence row ids and checks every
    reading's evidence set. Missing evidence rows mean not covered
    (the completion path re-resolves and would re-attach them).
    """
    try:
        attached = {
            (row.ref_kind, row.ref_id): row.id
            for row in store.evidence_for(user_id, thread_id)
        }
        wanted: set[str] = set()
        for ref in refs:
            row_id = attached.get((ref.kind, ref.ref_id))
            if row_id is None:
                return False
            wanted.add(row_id)
        for reading in store.readings_for(user_id, thread_id):
            if wanted <= set(reading.evidence_refs or []):
                return True
    except Exception:
        logger.exception("narrative: coverage pre-check failed")
        return False
    return False


def _render_deferred_row(
    store: NarrativeStore,
    user_id: str,
    row: dict,
    gen: GenerateFn,
    result: DeferredWorkResult,
    erasure_resolver: Any = None,
) -> None:
    """Render one claimed deferred row. Never raises for a settled
    outcome; generation/store-transient failures leave the row in
    rendering for lease-expiry retry (recorded in failed).

    ``erasure_resolver`` (Steward D2) is the pass's provenance
    resolver when an erasure boundary stands: the completion's own
    eligibility re-evaluation runs before any generation is spent,
    and an ineligible row is released back to pending — it is
    never settled and never rendered (§§8.3/9.3).
    """
    thread = store.get_thread(user_id, row["thread_id"])
    if thread is None:
        # Orphaned row (thread gone by another path): settle it.
        logger.warning(
            "narrative: deferred row %s has no thread; settling",
            row["id"],
        )
        store.mark_deferred_prose_done(user_id, row["id"])
        result.settled_without_prose.append(row["id"])
        return
    try:
        evidence_texts = json.loads(row["evidence_texts_json"] or "[]")
        evidence_refs = json.loads(row["evidence_refs_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        logger.exception(
            "narrative: deferred row %s has unusable payload; settling",
            row["id"],
        )
        store.mark_deferred_prose_done(user_id, row["id"])
        result.settled_without_prose.append(row["id"])
        return
    refs = []
    for key in evidence_refs:
        kind, _, ref_id = str(key).partition(":")
        refs.append(SourceRef(kind=kind, ref_id=ref_id))
    completion_admitted: list[tuple[str, str, str]] | None = None
    if erasure_resolver is not None:
        # D2 completion discipline (§§8.3/9.3): re-evaluate the
        # row's provenance NOW — resolve every cited ref through
        # its family's rule; the row's own created_at is only a
        # sanity bound inside that resolution. Ineligible → the
        # completion refuses regardless of anything else: release
        # the claim, spend no generation, settle nothing.
        row_time = erasure_resolver.origin_time_for_ref(
            "deferred_prose", row["id"]
        )
        admitted_refs = (
            erasure_resolver.admitted_for_refs(refs)
            if row_time is not None
            else None
        )
        if row_time is None or admitted_refs is None:
            logger.info(
                "narrative: deferred row %s fails erasure "
                "eligibility re-evaluation; released to pending "
                "without rendering",
                row["id"],
            )
            store.release_deferred_prose(user_id, row["id"])
            result.erasure_skipped.append(row["id"])
            return
        completion_admitted = admitted_refs + [
            ("deferred_prose", row["id"], row_time)
        ]
    if _already_covered(store, user_id, thread.id, refs):
        # Completion guard, checked BEFORE rendering (§6.2): a
        # reading already covers this evidence, so the row is done
        # WITHOUT spending a generation. The completion method
        # re-checks inside its transaction as backstop.
        logger.info(
            "narrative: deferred row %s already covered; settling "
            "without render",
            row["id"],
        )
        store.mark_deferred_prose_done(user_id, row["id"])
        result.already_covered.append(row["id"])
        return
    if row["kind"] in ("birth", "extension"):
        # Increment B §6.3: consult dismissals BEFORE any
        # generation — the gap this increment closes. Per-signature
        # first (the row's evidence_signature IS the birth /
        # extension signature), then offer declines. A match settles
        # the row as suppressed_by_decline WITHOUT a reading; an
        # ambiguous subject leaves the row pending (lease released)
        # for re-check next pass — ambiguity can resolve if the
        # thread's subject becomes computable, and until then the
        # owed row pins its thread from pruning.
        per_sig_kind = (
            "thread_birth" if row["kind"] == "birth" else "extension"
        )
        if store.is_dismissed(
            user_id, kind=per_sig_kind, signature=row["evidence_signature"]
        ):
            store.mark_deferred_prose_suppressed(
                user_id,
                row["id"],
                scope=per_sig_kind,
                key=row["evidence_signature"],
            )
            result.suppressed.append(
                {
                    "row_id": row["id"],
                    "scope": per_sig_kind,
                    "key": row["evidence_signature"],
                }
            )
            logger.info(
                "narrative: deferred row %s suppressed by %s "
                "dismissal; not rendered",
                row["id"],
                per_sig_kind,
            )
            return
        if row["kind"] == "birth":
            sig_keys = (
                row["evidence_signature"][len("birth:"):]
                if row["evidence_signature"].startswith("birth:")
                else ""
            )
            offer_inv = invitation_key(
                "birth",
                "birth",
                "birth",
                sig_keys.split("|") if sig_keys else [],
            )
            offer_class = "birth"
        else:
            prefix = f"extension:{thread.id}:"
            sig_keys = (
                row["evidence_signature"][len(prefix):]
                if row["evidence_signature"].startswith(prefix)
                else ""
            )
            offer_inv = invitation_key(
                thread.id,
                "extension",
                "reading",
                sig_keys.split("|") if sig_keys else [],
            )
            offer_class = "extension:reading"
        offer_subj, offer_prec = subject_key_for_thread(
            store, user_id, thread
        )
        offer = is_offer_declined(
            store,
            user_id,
            invitation_key=offer_inv,
            subject_key=offer_subj,
            subject_precision=offer_prec,
            class_label=offer_class,
        )
        if offer == "ambiguous":
            logger.info(
                "narrative: deferred row %s ambiguous (subject); "
                "released to pending for re-check",
                row["id"],
            )
            store.release_deferred_prose(user_id, row["id"])
            return
        if offer is not None:
            if offer == "invitation":
                matched_key = offer_inv
            elif offer == "subject":
                matched_key = f"subj:{offer_subj}"
            else:
                matched_key = f"class:{offer_class}"
            store.mark_deferred_prose_suppressed(
                user_id, row["id"], scope=offer, key=matched_key
            )
            result.suppressed.append(
                {"row_id": row["id"], "scope": offer, "key": matched_key}
            )
            logger.info(
                "narrative: deferred row %s suppressed by offer "
                "decline (%s); not rendered",
                row["id"],
                offer,
            )
            return
    if row["kind"] == "birth":
        prompt = _BIRTH_PROMPT.format(
            evidence=_render_deferred_texts(evidence_texts)
        )
    elif row["kind"] == "extension":
        prompt = _EXTENSION_PROMPT.format(
            standing=_render_standing(thread, store),
            evidence=_render_deferred_texts(evidence_texts),
        )
    else:
        logger.warning(
            "narrative: deferred row %s has unknown kind %r; settling",
            row["id"],
            row["kind"],
        )
        store.mark_deferred_prose_done(user_id, row["id"])
        result.settled_without_prose.append(row["id"])
        return
    try:
        raw = gen(
            prompt,
            provider_id="meta",
            user_id=user_id or None,
            operation="narrative-derivation",
            timeout=60,
        )
    except Exception:
        # Caught failure, not a crash: the attempt is over, so
        # release the row to pending for retry on the next pass
        # instead of holding the lease. Only a process crash
        # mid-render (no release possible) waits out the lease.
        logger.exception(
            "narrative: deferred render failed for row %s; "
            "released to pending for retry",
            row["id"],
        )
        store.release_deferred_prose(user_id, row["id"])
        result.failed.append(row["id"])
        return
    proposal = _parse_proposal(raw)
    if proposal is None:
        # NONE judgment or unparseable output: settle, do not spin.
        # The thread + evidence persist; a later extension may
        # still propose a reading for them.
        logger.info(
            "narrative: deferred row %s yielded no usable prose; settling",
            row["id"],
        )
        store.mark_deferred_prose_done(user_id, row["id"])
        result.settled_without_prose.append(row["id"])
        return
    if row["kind"] == "extension" and proposal.get("change_kind"):
        # A change cannot be recorded retroactively: invariant 2
        # requires new evidence, and this evidence was attached
        # records-first. The reading is the durable half; the
        # change-kind is dropped and logged, not forced.
        logger.info(
            "narrative: deferred extension %s proposed change_kind %r; "
            "dropped (evidence already attached)",
            row["id"],
            proposal["change_kind"],
        )
    try:
        reading = store.propose_reading_and_complete_deferred(
            user_id,
            thread.id,
            row["id"],
            author="steward",
            reading={
                "tensions": proposal["tensions"],
                "open_questions": proposal["open_questions"],
                "milestones": proposal["milestones"],
                "cast_notes": {},
            },
            evidence_refs=refs,
            scales=proposal["scales"],
            primary_scale=proposal["primary_scale"],
            admitted_sources=completion_admitted,
        )
    except ErasureBarrierRefusal:
        # The barrier moved between the re-evaluation and the
        # completion (backstop fired): the row is NOT settled —
        # release it to pending for a later pass's re-evaluation.
        logger.warning(
            "narrative: deferred row %s refused at completion by "
            "the erasure barrier; released to pending",
            row["id"],
        )
        store.release_deferred_prose(user_id, row["id"])
        result.erasure_skipped.append(row["id"])
        return
    except ValueError:
        # Deterministic validation failure (not transient): settle
        # rather than retrying the same failure after every lease.
        logger.exception(
            "narrative: deferred row %s refused by store; settling",
            row["id"],
        )
        store.mark_deferred_prose_done(user_id, row["id"])
        result.settled_without_prose.append(row["id"])
        return
    if reading is None:
        # Already covered: a reading covers this evidence, so the
        # row is done without a duplicate render.
        result.already_covered.append(row["id"])
        return
    result.rendered.append(reading.id)


def work_deferred_prose(
    store: NarrativeStore,
    user_id: str,
    *,
    generate_fn: GenerateFn | None = None,
    lease_seconds: int = STEWARD_DEFERRED_LEASE_SECONDS,
    limit: int = 50,
    erasure_resolver: Any = None,
) -> DeferredWorkResult:
    """Render owed prose for a user's pending deferred rows.

    Lease-claimed, exactly-once by construction: a row is claimed
    pending → rendering, rendered + marked done in ONE transaction
    with its reading, and a row whose evidence is already covered
    by a reading is marked done without duplicating. No backend
    means no row churn: pending rows simply wait, and no attempt
    is counted for backend absence. Never raises for a single
    row's failure; a caught render failure releases the row to
    pending for the next pass, and only a process crash mid-render
    holds the lease until expiry.
    """
    result = DeferredWorkResult()
    gen = _resolve_generate_fn(generate_fn)
    if gen is None:
        result.skipped_no_backend = True
        return result
    try:
        store.release_stale_deferred_prose(lease_seconds)
    except Exception:
        logger.exception("narrative: stale-deferred release failed")
    try:
        rows = store.deferred_prose_for(user_id, status="pending")[:limit]
    except Exception:
        logger.exception("narrative: deferred listing failed")
        return result
    for row in rows:
        try:
            claimed = store.claim_deferred_prose(user_id, row["id"])
        except Exception:
            logger.exception(
                "narrative: deferred claim failed for row %s", row["id"]
            )
            continue
        if claimed is None:
            continue
        try:
            _render_deferred_row(
                store, user_id, claimed, gen, result,
                erasure_resolver=erasure_resolver,
            )
        except Exception:
            logger.exception(
                "narrative: deferred render failed for row %s; "
                "lease expiry will retry",
                row["id"],
            )
            result.failed.append(row["id"])
    return result


def dismiss_proposal(
    store: NarrativeStore,
    user_id: str,
    *,
    kind: str,
    signature: str,
):
    """Record a user dismissal for the future review surface.

    Thin wrapper over the store's dismissal memory: the review
    surface (not S1) calls this when the user dismisses a birth or
    extension proposal, and derivation consults the rows before
    proposing. A dismissal never deletes the proposal's rows.
    """
    return store.record_dismissal(user_id, kind=kind, signature=signature)


# ---------------------------------------------------------------------------
# Background pipeline (installed at app assembly — NOT by this phase)
# ---------------------------------------------------------------------------


class StewardPipeline:
    """Schedules steward derivation off the caller's path.

    Mirrors fellowship's DerivationPipeline: the default scheduler
    spawns a daemon thread; tests and tools may inject a synchronous
    scheduler (``lambda fn: fn()``) for determinism. Scheduling
    itself never raises.

    Consent gating (increment A §1.8): when ``consent_reader`` is
    set, every run checks it first — a closed gate means no
    derivation, on the install path and the sweep path alike. A
    pipeline built WITHOUT a reader derives ungated: that is the
    direct-drive mode for tests and tools only. The production
    install (``install_default_pipeline``) always gates, using
    the production reader by default — pass an explicit reader
    there only to override it in tests.
    """

    def __init__(
        self,
        store: NarrativeStore | None = None,
        generate_fn: GenerateFn | None = None,
        scheduler: Callable[[Callable[[], None]], None] | None = None,
        consent_reader: Callable[[str], bool] | None = None,
        operation_reader: Callable[[str], Any] | None = None,
        meeting_provider: Callable[[str], Any] | None = None,
    ) -> None:
        self._store = store
        self._generate_fn = generate_fn
        self._scheduler = scheduler or self._thread_scheduler
        self._consent_reader = consent_reader
        # Steward D2 (§9.4): the barrier-integrity check's operation
        # -record reader — injectable like the consent reader; the
        # production default reads the identity store.
        self._operation_reader = operation_reader
        # Steward D2 (§9.3): meeting rows for provenance resolution
        # of meeting_completed culminations — the same seam the
        # sweep takes (the narrative package does not import the
        # conversation package). Without it, meeting origins are
        # unresolvable on this path and fail closed.
        self._meeting_provider = meeting_provider

    @staticmethod
    def _thread_scheduler(fn: Callable[[], None]) -> None:
        threading.Thread(target=fn, name="narrative-derivation", daemon=True).start()

    @property
    def store(self) -> NarrativeStore:
        if self._store is None:
            self._store = NarrativeStore()
        return self._store

    def _gate_open(self, user_id: str) -> bool:
        """True when this pipeline may derive for this user."""
        if self._consent_reader is None:
            return True
        try:
            return bool(self._consent_reader(user_id))
        except Exception:
            logger.exception(
                "narrative: consent read failed for user %r; failing closed",
                user_id,
            )
            return False

    def schedule_batch(
        self, user_id: str, items: list[EvidenceItem]
    ) -> None:
        try:
            self._scheduler(
                lambda: self._run_batch(user_id, list(items))
            )
        except Exception:
            logger.exception("narrative: could not schedule derivation")

    def schedule_event(self, event: FellowshipEvent) -> None:
        try:
            self._scheduler(lambda: self._run_event(event))
        except Exception:
            logger.exception("narrative: could not schedule derivation")

    def _barrier_resolver(self, user_id: str):
        """The D2 barrier check for one run (§9.4 Rev 4).

        Returns (verdict, resolver-or-None). A "hold" verdict means
        this run derives nothing; a "proceed" verdict carries the
        pass's provenance resolver; "clear" means no erasure stands
        and the run behaves exactly as it did before D2.
        """
        from .eligibility import check_barrier_integrity, resolver_from_verdict

        verdict = check_barrier_integrity(
            user_id,
            narrative_store=self.store,
            operation_reader=self._operation_reader,
        )
        if verdict.state == "hold":
            logger.info(
                "narrative: erasure barrier holds derivation for "
                "user %r: %s",
                user_id,
                verdict.reason,
            )
            return verdict, None
        resolver = resolver_from_verdict(
            user_id,
            verdict,
            narrative_store=self.store,
            meeting_rows=(
                self._meeting_provider(user_id)
                if self._meeting_provider is not None
                else None
            ),
        )
        return verdict, resolver

    def _run_batch(self, user_id: str, items: list[EvidenceItem]) -> None:
        try:
            verdict, resolver = self._barrier_resolver(user_id)
            if verdict.state == "hold":
                return
            if not self._gate_open(user_id):
                logger.info(
                    "narrative: steward consent closed for user %r; "
                    "batch skipped",
                    user_id,
                )
                return
            if resolver is not None:
                # Eligibility (§9.3): stamp the admissible items,
                # drop the rest — an ineligible item never reaches
                # clustering.
                admitted_items: list[EvidenceItem] = []
                for item in items:
                    entry = resolver.admitted_entry(
                        item.ref.kind, item.ref.ref_id
                    )
                    if entry is None:
                        logger.info(
                            "narrative: item %s fails erasure "
                            "eligibility; skipped",
                            item.evidence_key(),
                        )
                        continue
                    admitted_items.append(
                        replace(item, source_time=entry[2])
                    )
                items = admitted_items
            derive_batch(user_id, items, self.store, generate_fn=self._generate_fn)
        except Exception:
            logger.exception("narrative: derivation run failed")

    def _run_event(self, event: FellowshipEvent) -> None:
        try:
            # Steward D2 (§9.4): the barrier-integrity check runs at
            # the head of the entry point, before the consent gate
            # and before any detector or derivation write.
            verdict, resolver = self._barrier_resolver(event.user_id)
            if verdict.state == "hold":
                return
            # Phase 3: the live path derives ALL event kinds, not
            # just meeting completions (increment A rollout lifted
            # once the Phase 3 fixture criteria pass). The consent
            # gate still comes first — detectors are derivation
            # work and never run for a closed gate. Detectors run
            # before analysis: a change proposal attaches the
            # event's evidence before derivation sees it, so
            # re-analysis finds it already attached and proposes
            # nothing twice.
            if not self._gate_open(event.user_id):
                logger.info(
                    "narrative: steward consent closed for user %r; "
                    "event %s skipped",
                    event.user_id,
                    event.id,
                )
                return
            source_time: str | None = None
            admitted: list[tuple[str, str, str]] | None = None
            if resolver is not None:
                entry = resolver.admitted_for_event(event)
                if entry is None:
                    logger.info(
                        "narrative: event %s fails erasure "
                        "eligibility; consumed-skipped",
                        event.id,
                    )
                    return
                source_time = entry[2]
                admitted = [entry]
            # Steward D1 (packet §5.2 as revised): candidate-
            # mention capture runs once per eligible user-authored
            # event, INDEPENDENTLY of thread admission — it does
            # not consult what the detectors or derivation below
            # decide, and its failure never fails derivation (the
            # detectors' own discipline). It sits after the consent
            # gate and the eligibility evaluation: a gate-closed or
            # erasure-ineligible event is never captured, and a
            # barrier hold has already returned above.
            try:
                from local_ai.narrative.candidates import (
                    capture_event_mentions,
                )

                capture_event_mentions(
                    self.store, event, admitted_sources=admitted
                )
            except Exception:
                logger.exception(
                    "narrative: candidate capture failed for event %s",
                    event.id,
                )
            from local_ai.narrative.changes import (
                detect_changes_for_event,
            )

            try:
                detect_changes_for_event(
                    self.store, event.user_id, event,
                    admitted_sources=admitted,
                )
            except Exception:
                logger.exception(
                    "narrative: change detection failed for event %s",
                    event.id,
                )
            analyze_for_threads(
                event, self.store, generate_fn=self._generate_fn,
                source_time=source_time,
            )
        except Exception:
            logger.exception("narrative: derivation run failed")


_PIPELINE: StewardPipeline | None = None
_PIPELINE_LOCK = threading.Lock()


def install_default_pipeline(
    store: NarrativeStore | None = None,
    generate_fn: GenerateFn | None = None,
    scheduler: Callable[[Callable[[], None]], None] | None = None,
    consent_reader: Callable[[str], bool] | None = None,
    operation_reader: Callable[[str], Any] | None = None,
    meeting_provider: Callable[[str], Any] | None = None,
) -> StewardPipeline:
    """Install the process-wide steward pipeline (app assembly).

    Idempotent-ish: re-installing replaces the pipeline (tests use
    this to install a synchronous one; production installs once).
    Unlike a directly constructed StewardPipeline, the installed
    pipeline ALWAYS gates: with no explicit reader it uses the
    production consent reader (increment A §1.8). Pass an explicit
    reader only to override it in tests.
    """
    global _PIPELINE
    if consent_reader is None:
        from local_ai.narrative.consent import steward_consent_allowed

        consent_reader = steward_consent_allowed
    with _PIPELINE_LOCK:
        _PIPELINE = StewardPipeline(
            store=store,
            generate_fn=generate_fn,
            scheduler=scheduler,
            consent_reader=consent_reader,
            operation_reader=operation_reader,
            meeting_provider=meeting_provider,
        )
        return _PIPELINE


def get_pipeline() -> StewardPipeline | None:
    """The installed pipeline, or None when derivation is not wired."""
    return _PIPELINE
