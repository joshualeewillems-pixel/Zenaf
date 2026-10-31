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

import json
import logging
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from local_ai.council.archetypes import get_archetype, stock_archetype_ids
from local_ai.council.jurisdictions import get_jurisdiction
from local_ai.fellowship.events import MEETING_COMPLETED, FellowshipEvent

from .models import NarrativeThread
from .refs import RefTier, SourceRef
from .store import NarrativeStore

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
    """

    ref: SourceRef
    text: str = ""
    entity_ref: str | None = None
    strand_weights: dict[str, float] | None = None

    def evidence_key(self) -> str:
        return f"{self.ref.kind}:{self.ref.ref_id}"


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
    return EvidenceItem(ref=ref, text=text, entity_ref=entity_ref)


def claim_to_item(claim: Any) -> EvidenceItem:
    """A ReviewClaim-like (id, evidence, title) → EvidenceItem.

    Duck-typed on purpose: the claim store's row shape is owned
    elsewhere; derivation needs only the verbatim quote (or the
    title when a claim carries no quote) and the claim id.
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
    """A pipeline journal entry (id, full text) → EvidenceItem."""
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


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity with case-insensitive strand keys.

    Strand vectors arrive from different stores under different key
    casings (archetype weights use display names); the comparison
    must not depend on that accident.
    """
    norm_a = {str(k).lower(): float(v) for k, v in a.items()}
    norm_b = {str(k).lower(): float(v) for k, v in b.items()}
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
    in the world), at least two shared distinctive tokens (the same
    ground in words), or genuinely similar strand vectors. Any one
    link is enough to join; no link means no cluster, however many
    items the batch holds.
    """
    if a.entity_ref and a.entity_ref == b.entity_ref:
        return f"shared entity {a.entity_ref}"
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


def birth_signature(items: Iterable[EvidenceItem]) -> str:
    keys = sorted(item.evidence_key() for item in items)
    return "birth:" + "|".join(keys)


def extension_signature(thread_id: str, items: Iterable[EvidenceItem]) -> str:
    keys = sorted(item.evidence_key() for item in items)
    return f"extension:{thread_id}:" + "|".join(keys)


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
        )
    except Exception:
        logger.exception("narrative: records-first extension failed")
        result.declines += 1
        return
    _annotate_entities(store, user_id, thread.id, new_items)
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
    if change_kind:
        try:
            change = store.record_change(
                user_id, thread.id, kind=change_kind, evidence_refs=refs
            )
            result.changes.append(change.id)
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
        )
    except ValueError:
        logger.exception("narrative: extension reading refused by store")
        result.declines += 1
        return
    # The reading's attach is the final attach on this path (the
    # change's attach, when one was recorded, covered the same
    # rows) — annotate once, idempotently.
    _annotate_entities(store, user_id, thread.id, new_items)
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
) -> DerivationResult:
    """Audit Part II §3 entry point: one event → thread proposals.

    A single event can only EXTEND a live thread it overlaps; it
    can never birth one (birth needs >= 2 items, Part II §5). An
    event on nobody's ground, or overlapping nothing, spends zero
    generations and proposes nothing — the single-event call is
    where the pre-filter's thrift is most visible.
    """
    item = event_to_item(event)
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
    skipped_no_backend: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "rendered": list(self.rendered),
            "already_covered": list(self.already_covered),
            "settled_without_prose": list(self.settled_without_prose),
            "failed": list(self.failed),
            "suppressed": [dict(s) for s in self.suppressed],
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
) -> None:
    """Render one claimed deferred row. Never raises for a settled
    outcome; generation/store-transient failures leave the row in
    rendering for lease-expiry retry (recorded in failed)."""
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
        )
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
            _render_deferred_row(store, user_id, claimed, gen, result)
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
    ) -> None:
        self._store = store
        self._generate_fn = generate_fn
        self._scheduler = scheduler or self._thread_scheduler
        self._consent_reader = consent_reader

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

    def _run_batch(self, user_id: str, items: list[EvidenceItem]) -> None:
        try:
            if not self._gate_open(user_id):
                logger.info(
                    "narrative: steward consent closed for user %r; "
                    "batch skipped",
                    user_id,
                )
                return
            derive_batch(user_id, items, self.store, generate_fn=self._generate_fn)
        except Exception:
            logger.exception("narrative: derivation run failed")

    def _run_event(self, event: FellowshipEvent) -> None:
        try:
            # Increment A rollout: the install path derives
            # meeting completions only; other kinds arrive via the
            # sweep only after the initial path passes tests.
            if event.kind != MEETING_COMPLETED:
                return
            if not self._gate_open(event.user_id):
                logger.info(
                    "narrative: steward consent closed for user %r; "
                    "event %s skipped",
                    event.user_id,
                    event.id,
                )
                return
            analyze_for_threads(event, self.store, generate_fn=self._generate_fn)
        except Exception:
            logger.exception("narrative: derivation run failed")


_PIPELINE: StewardPipeline | None = None
_PIPELINE_LOCK = threading.Lock()


def install_default_pipeline(
    store: NarrativeStore | None = None,
    generate_fn: GenerateFn | None = None,
    scheduler: Callable[[Callable[[], None]], None] | None = None,
    consent_reader: Callable[[str], bool] | None = None,
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
        )
        return _PIPELINE


def get_pipeline() -> StewardPipeline | None:
    """The installed pipeline, or None when derivation is not wired."""
    return _PIPELINE
