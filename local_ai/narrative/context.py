"""Prepared steward context for branches (Phase 2, base plan S2).

``narrative_context_for`` is the fast-path read Phase 1 named but did
not build: a store read plus a bounded render. It adds no generation,
no per-request model analysis, and no new foreground work:

- Consent and relevance are re-validated at preparation time through
  Phase 1's ``prepare_context`` — the same dual default-off flags,
  the same deterministic relevance rules, the same fail-closed
  discipline. A preparation that fails any gate returns no content
  at all, not even a thread title.
- Rendering is facts only: thread title, status, scope, and evidence
  count — plus, since Gate B recognition, standing-frame facts: an
  ACCEPTED fitting's lens name and the count of ACCEPTED
  correspondences citing the thread. Proposed frames are never
  rendered. Readings (interpretations) are never rendered into a seat's
  prompt, and evidence text is never copied — the layer cites by
  ref, and the block carries ref counts, not ref contents. One
  thread rendered for two branches shows identical fact lines; only
  the registry-derived framing line names the receiving branch, so
  no cross-seat lexicon leaks into another seat's context.
- Only standing threads condition a seat: status ``active`` or
  ``dormant``. Nascent threads are proposals awaiting a user verdict
  (Phase 1 review); retired and archived threads are finished
  business. Serving an unaccepted proposal as context would let a
  seat speak from state the user never validated.
- The aspiration bridge joins the same block ONLY when the user's
  existing aspiration gates all allow it: the aspiration feature
  flag, the ``aspiration_use_in_guidance`` permission, and the
  profile's own ``use_in_guidance`` toggle. Aspiration lines are
  user-stated profile text only — core aim, edge, obstacles,
  near/long-term aspirations, and the Phase 2 Heart fields (loves,
  sources of meaning, commitments). No inference runs here: no
  derived signal, no calibration, no directive. ``allow_inference``
  is not consulted because context is not a proposal.
- Decline needs no function: a seat that does not use available
  context writes nothing. This module creates no decline rows, no
  flags, and no disagreement records; the only rows a preparation
  writes are Phase 1's relevance-assessment records.

Attended refs: the caller supplies what the branch is currently
attending to. For the chat wiring that is the current user message:
``attended_refs_for_text`` matches the message's tokens against
entity refs already in the store — a deterministic lookup, not
analysis. A ref attends when every matchable token of its id part
appears in the message; refs with no matchable token (e.g. a
two-letter id) never attend via text, only via the explicit
``attended_entity_refs`` parameter.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .branches import get_branch
from .consent import coordination_allowed
from .coordination import prepare_context
from .currency import derive_currency
from .lenses import get_lens
from .store import NarrativeStore

logger = logging.getLogger(__name__)

#: The Weaver's branch id (archetype ``conductor``).
WEAVER_BRANCH_ID = "seat:conductor"

#: Thread statuses that may condition a seat. Nascent threads are
#: unaccepted proposals; resolved threads are finished stories;
#: retired/archived threads are closed. Only active and dormant
#: threads are ongoing stories a seat may encounter.
CONTEXT_THREAD_STATUSES: tuple[str, ...] = ("active", "dormant")

#: Bounds for one prepared block. The chat path's extra_instructions
#: cap is 8000 chars; the steward block stays far inside it so the
#: seat's own frame can never be silently truncated by context.
MAX_CONTEXT_THREADS = 5
MAX_CONTEXT_CHARS = 2000
_MAX_TITLE_CHARS = 120
_MAX_SCOPE_CHARS = 80
_MAX_ASPIRATION_LINE_CHARS = 200

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def attended_refs_for_text(known_refs, text: str) -> frozenset[str]:
    """Entity refs the given text attends to, by deterministic lookup.

    ``known_refs`` are "<type>:<id>" identities already in the
    store. A ref attends when every matchable token (length >= 3)
    of its id part appears among the text's tokens. No model, no
    inference, no new knowledge — only refs the store already holds
    can attend, and only through tokens the user actually wrote.
    """
    message_tokens = _tokens(text)
    if not message_tokens:
        return frozenset()
    attended: set[str] = set()
    for ref in known_refs:
        ref = str(ref or "").strip()
        if not ref:
            continue
        id_part = ref.split(":", 1)[-1] if ":" in ref else ref
        id_tokens = {t for t in _tokens(id_part) if len(t) >= 3}
        if not id_tokens:
            continue
        if id_tokens <= message_tokens:
            attended.add(ref)
    return frozenset(attended)


@dataclass(frozen=True)
class PreparedContext:
    """The outcome of one prepared-context read.

    ``block`` is None whenever context is unavailable — no partial
    payload, no leaked title. ``threads`` carries the rendered
    facts (thread id, title, status, scope, evidence count) for
    exactly the threads in the block. ``assessment_ids`` names the
    Phase 1 relevance rows this preparation recorded, so any
    discrepancy flag can reference them.
    """

    available: bool
    reason: str
    block: str | None = None
    threads: tuple[dict, ...] = ()
    aspiration_included: bool = False
    assessment_ids: tuple[str, ...] = field(default_factory=tuple)


def _default_aspiration_reader(user_id: str):
    """The aspiration profile via its home store (lazy import: this
    module must not pull vision-execution storage in at import
    time, mirroring consent.py's leaf discipline)."""
    from local_ai.vision_execution.storage import get_aspiration_profile

    return get_aspiration_profile(user_id)


def _default_aspiration_permission_check(user_id: str) -> bool:
    """The aspiration layer's own permission gate (lazy import)."""
    from local_ai.vision_execution.storage import user_permission_enabled

    return bool(user_permission_enabled(user_id, "aspiration_use_in_guidance"))


def _aspiration_lines(
    user_id: str,
    *,
    aspiration_reader=None,
    aspiration_permission_check=None,
) -> tuple[list[str], bool]:
    """User-stated aspiration lines for the block, or ([], False).

    All three inherited gates must pass: the aspiration feature
    flag, the ``aspiration_use_in_guidance`` permission, and the
    profile's own ``use_in_guidance`` toggle. Any gate failing, any
    read error, or an empty profile yields no lines — aspiration is
    absent, never inferred, when the user has not allowed it in
    guidance. Lines are clipped profile text, never composed prose.
    """
    try:
        from local_ai.aspiration_layer import aspiration_guidance_injection_enabled

        if not aspiration_guidance_injection_enabled():
            return [], False
        permission_check = (
            aspiration_permission_check or _default_aspiration_permission_check
        )
        if not permission_check(user_id):
            return [], False
        reader = aspiration_reader or _default_aspiration_reader
        prof = reader(user_id) or {}
        if not isinstance(prof, dict) or not prof.get("use_in_guidance"):
            return [], False
    except Exception:
        return [], False
    lines: list[str] = []
    for label, key in (
        ("Core aim", "core_aim"),
        ("Active edge", "current_edge"),
        ("Obstacle now", "current_obstacles"),
        ("Near-term aspirations", "near_term_aspirations"),
        ("Long-term aspirations", "long_term_aspirations"),
        ("Loves", "heart_loves"),
        ("Sources of meaning", "heart_meaning"),
        ("Commitments", "heart_commitments"),
    ):
        value = str(prof.get(key) or "").strip()
        if value:
            lines.append(f"- {label}: {value[:_MAX_ASPIRATION_LINE_CHARS]}")
    return lines, bool(lines)


def _render_block(
    branch_display_name: str,
    thread_facts: list[dict],
    hidden_count: int,
    aspiration_lines: list[str],
) -> str:
    """Bounded facts-only render. Identical fact lines for every
    branch; only the framing line names the receiving branch."""
    lines = [
        "Steward context — ongoing threads relevant to this "
        "conversation. Facts only; interpret them in your own voice, "
        "or set them aside if they don't fit.",
        f"Prepared for {branch_display_name}.",
    ]
    for fact in thread_facts:
        line = f"- {fact['title']} [{fact['status']}]"
        if fact["scope"]:
            line += f" (scope: {fact['scope']})"
        line += f" — {fact['evidence_count']} evidence ref(s)"
        if fact.get("fitting_name"):
            # Standing frame (Gate B recognition): an ACCEPTED
            # fitting is a fact about the record, rendered like the
            # other facts. Proposed frames are never rendered — an
            # unaccepted proposal is not seat context.
            line += f" — fitting: {fact['fitting_name']} (accepted)"
        if fact.get("correspondence_count"):
            line += (
                f" — {fact['correspondence_count']} accepted "
                "correspondence(s)"
            )
        lines.append(line)
    if hidden_count > 0:
        lines.append(f"+{hidden_count} more relevant thread(s) not shown.")
    if aspiration_lines:
        lines.append(
            "Your stated aspirations (shown only where you have "
            "allowed them in guidance):"
        )
        lines.extend(aspiration_lines)
    block = "\n".join(lines)
    if len(block) > MAX_CONTEXT_CHARS:
        block = block[:MAX_CONTEXT_CHARS].rstrip() + "\n[…truncated]"
    return block


def narrative_context_for(
    store: NarrativeStore,
    user_id: str,
    branch_id: str,
    *,
    attended_text: str = "",
    attended_entity_refs: tuple[str, ...] | list[str] = (),
    attended_thread_ids: tuple[str, ...] | list[str] = (),
    connection=None,
    aspiration_reader=None,
    aspiration_permission_check=None,
    max_threads: int = MAX_CONTEXT_THREADS,
) -> PreparedContext:
    """Prepare bounded steward context for one branch, or refuse it.

    Raises ``ValueError`` for an unknown branch id (a registry
    configuration error). Every other failure returns
    ``available=False`` with a reason code and ``block=None``.

    The consent pre-check is an early exit only: every thread
    preparation below re-validates both flags and relevance fresh
    through ``prepare_context``, so revoked consent or stale
    relevance closes availability even if the pre-check passed.
    """
    contract = get_branch(branch_id)
    if contract is None:
        raise ValueError(f"unknown branch: {branch_id!r}")
    if "coordination" not in contract.capabilities:
        return PreparedContext(
            available=False, reason="branch_not_coordination_contracted"
        )
    if not coordination_allowed(user_id, connection=connection):
        # No coordination work at all when consent is closed: no
        # assessment rows, no relevance computation, no content.
        return PreparedContext(available=False, reason="consent_closed")

    standing = [
        t
        for t in store.threads_for(user_id, limit=None)
        if t.status in CONTEXT_THREAD_STATUSES
    ]
    if not standing:
        return PreparedContext(available=False, reason="no_standing_threads")

    # One evidence read per thread: the refs are the candidate
    # entity refs and the lookup pool for attended-text matching.
    evidence_by_thread: dict[str, list] = {}
    known_refs: set[str] = set()
    for thread in standing:
        rows = store.evidence_for(user_id, thread.id)
        evidence_by_thread[thread.id] = rows
        for row in rows:
            if row.entity_ref:
                known_refs.add(row.entity_ref)
    attended = set(str(r) for r in attended_entity_refs)
    attended |= attended_refs_for_text(known_refs, attended_text)

    # Standing frames, read once per preparation: accepted
    # fittings (by thread) and accepted correspondences (counted
    # per cited thread). Only ACCEPTED frames are facts; proposed
    # or rejected frames never reach a seat's context.
    accepted_correspondences = store.correspondences_for(
        user_id, status="user_accepted"
    )
    correspondence_counts: dict[str, int] = {}
    for corr in accepted_correspondences:
        for cited_thread in corr.thread_ids or []:
            correspondence_counts[cited_thread] = (
                correspondence_counts.get(cited_thread, 0) + 1
            )

    available_facts: list[dict] = []
    assessment_ids: list[str] = []
    for thread in standing:
        thread_refs = [
            row.entity_ref for row in evidence_by_thread[thread.id] if row.entity_ref
        ]
        candidate_text = " ".join(
            part for part in (thread.title, thread.scope) if part
        )
        outcome = prepare_context(
            store,
            user_id,
            branch_id,
            thread_id=thread.id,
            candidate_text=candidate_text,
            candidate_entity_refs=thread_refs,
            candidate_strand_weights=thread.strand_weights,
            attended_entity_refs=sorted(attended),
            attended_thread_ids=attended_thread_ids,
            connection=connection,
        )
        if outcome.assessment is not None:
            assessment_ids.append(outcome.assessment.id)
        if not outcome.available or outcome.context is None:
            continue
        fitting_name = None
        accepted_fittings = store.fittings_for(
            user_id, thread.id, status="accepted"
        )
        if accepted_fittings:
            lens = get_lens(accepted_fittings[0].lens_id)
            fitting_name = (
                lens.name if lens is not None else accepted_fittings[0].lens_id
            )
        available_facts.append(
            {
                "thread_id": thread.id,
                "title": (thread.title or "")[:_MAX_TITLE_CHARS],
                "status": thread.status,
                "scope": (thread.scope or "")[:_MAX_SCOPE_CHARS],
                "evidence_count": len(evidence_by_thread[thread.id]),
                "fitting_name": fitting_name,
                "correspondence_count": correspondence_counts.get(
                    thread.id, 0
                ),
            }
        )
    if not available_facts:
        return PreparedContext(
            available=False,
            reason="no_relevant_threads",
            assessment_ids=tuple(assessment_ids),
        )

    shown = available_facts[:max_threads]
    hidden = len(available_facts) - len(shown)
    aspiration_lines, aspiration_included = _aspiration_lines(
        user_id,
        aspiration_reader=aspiration_reader,
        aspiration_permission_check=aspiration_permission_check,
    )
    block = _render_block(
        contract.display_name, shown, hidden, aspiration_lines
    )
    return PreparedContext(
        available=True,
        reason="available",
        block=block,
        threads=tuple(shown),
        aspiration_included=aspiration_included,
        assessment_ids=tuple(assessment_ids),
    )


def weaver_context_provider(
    store: NarrativeStore | None = None,
    *,
    connection=None,
    aspiration_reader=None,
    aspiration_permission_check=None,
    with_selection: bool = False,
) -> object:
    """A chat-path provider returning the Weaver's prepared block.

    The returned callable takes ``(user_id, message, history)`` and
    returns the context block string, or None when nothing is
    available. It never raises: any failure degrades to no context,
    so a steward outage can never break a turn. The store is built
    lazily on first use when not supplied (the production path);
    tests pass an explicit store. History is accepted for call-site
    symmetry but deliberately unused — relevance is to this turn's
    message, so stale turns cannot pull stale threads into view.

    With ``with_selection=True`` the callable instead returns the
    full :class:`PreparedContext`, so a caller that records
    provenance (the conversation service's generation manifest,
    plan Q4.1) can name the threads the block was prepared from.
    The block text is identical either way; the default preserves
    the string contract every existing caller relies on.
    """

    state: dict[str, NarrativeStore | None] = {"store": store}

    def provider(user_id: str, message: str, history=None):
        try:
            if state["store"] is None:
                state["store"] = NarrativeStore()
            prepared = narrative_context_for(
                state["store"],
                user_id,
                WEAVER_BRANCH_ID,
                attended_text=message or "",
                connection=connection,
                aspiration_reader=aspiration_reader,
                aspiration_permission_check=aspiration_permission_check,
            )
            return prepared if with_selection else prepared.block
        except Exception:
            return None

    return provider


# ---------------------------------------------------------------------------
# Pencil-standing observations (founder ruling, 2026-11-21 — scoping
# Addendum 23). The facts-only layer above is unchanged: readings are
# still never rendered as FACTS, and the Weaver's path serves standing,
# user-validated material only. This section is a separate, narrower
# channel with its own standing:
#
# - A pencil observation is a PROPOSED reading's pattern language
#   (tensions, open questions) on a standing (active/dormant) thread,
#   served to the Jynx branch as material for its imagination. It is
#   marked uncertain in the block itself, carries no reading id and no
#   evidence ref — nothing in it is citable — and asserts nothing as
#   established about the visitor.
# - Every gate from the facts layer applies unchanged: the branch must
#   be coordination-contracted, BOTH consent flags must be open, and
#   relevance is re-validated per thread through ``prepare_context``
#   at preparation time. One additional gate is this channel's own:
#   the ``ZENAF_STEWARD_PENCIL`` master switch, default OFF.
# - Nascent threads never contribute: a thread the user has not
#   accepted as born stays invisible here exactly as above. Only the
#   reading's standing changes (proposed may travel, as pencil), not
#   the thread's.
# ---------------------------------------------------------------------------

#: The Jynx's branch id (archetype ``maverick``).
PENCIL_BRANCH_ID = "seat:maverick"

#: The champion's branch id (archetype ``champion``) — V3 (Valen
#: vertical slice, governing I3 bounded to champion): pencil carriage
#: for the encountering seat. The champion's carriage is separately
#: flagged (``ZENAF_PENCIL_CHAMPION``, see
#: :func:`pencil_champion_enabled`) and independently toggled from
#: every other slice switch; the toggle gates RENDERING only — never
#: capture (V1), never any relevance determination.
CHAMPION_BRANCH_ID = "seat:champion"

#: The archetype id whose encounter arcs V3 prepares.
CHAMPION_ARCHETYPE_ID = "champion"

#: Bounds for one pencil block, mirroring the facts layer's discipline.
MAX_PENCIL_THREADS = 5
MAX_PENCIL_CHARS = 2000
_MAX_PENCIL_ITEM_CHARS = 160
_MAX_PENCIL_TENSIONS = 3
_MAX_PENCIL_QUESTIONS = 2

_PENCIL_HEADER = (
    "Steward observations — pencil standing. These are the system's "
    "uncertain readings of patterns across this person's history, "
    "offered as material for your imagination. They are not facts "
    "and not evidence: do not cite them, do not present them as "
    "established, and do not announce where they came from. Let them "
    "inform what you notice, or set them aside."
)


def pencil_context_enabled() -> bool:
    """Master switch for pencil-standing serving (default OFF).

    Same switch idiom as ``recognition_enabled``: unset means off, so
    every path behaves exactly as today until the switch is
    deliberately set.
    """
    raw = os.environ.get("ZENAF_STEWARD_PENCIL")
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def pencil_champion_enabled() -> bool:
    """Carriage toggle for the encountering seat (champion) — V3.

    ``ZENAF_PENCIL_CHAMPION``, read per call, default OFF, in the
    same idiom as :func:`pencil_context_enabled`. Independent of the
    pencil master switch (both must be on for champion carriage to
    render) and of every other slice toggle: this flag's state
    influences no other code path — in particular not the obligation
    block's rendering and not any relevance determination. It gates
    rendering only: V1 capture writes whether or not it is set.
    """
    raw = os.environ.get("ZENAF_PENCIL_CHAMPION")
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


#: Resolves one fellowship event id to its verbatim evidence text
#: (the visitor's own words), or None when unresolvable. Injectable
#: so tests never touch the activity log.
EventTextResolver = Callable[[str], "str | None"]


def _resolve_event_evidence_text(event_id: str) -> str | None:
    """Default :data:`EventTextResolver`: the activity log scan, in
    the shape of ``noting.resolve_turn_event_id`` — a fellowship
    event's log detail carries its verbatim ``evidence`` text.
    Fail-closed: any failure or non-match returns None and the
    objection slot simply stays empty."""
    if not event_id:
        return None
    try:
        from local_ai import activity as _activity

        events = _activity.get_recent_activity(limit=100_000)
    except Exception:
        logger.exception("pencil: activity log scan failed")
        return None
    for event in events:
        if getattr(event, "id", "") != event_id:
            continue
        if getattr(event, "source", "") != "fellowship":
            return None
        try:
            detail = json.loads(getattr(event, "detail", "") or "{}")
        except (json.JSONDecodeError, TypeError):
            return None
        text = detail.get("evidence")
        return text if isinstance(text, str) and text.strip() else None
    return None


def _render_pencil_block(
    branch_display_name: str,
    items: list[dict],
    hidden_count: int,
) -> str:
    """Bounded pencil render. Pattern language only — tensions and
    open questions from proposed readings. No ids, no refs, no
    evidence text, no milestones (what has happened is fact-class;
    what is tense and unresolved is the observation).

    V3 adds the governing §9 rendering contract's two field classes,
    inside the same caps and the same header: ONE verbatim objection
    quote (the visitor's own words, attributed to the visitor — the
    single sanctioned exception to "no evidence text", because a
    quoted objection remains the visitor's expression where a
    paraphrase would become the system's interpretation) and the
    seat's own recognition in its own words, quoted to itself. Both
    ride the same per-item character discipline; neither has an
    action surface. Positions are never carried as labelled stances:
    they travel only transformed, as the tensions / open questions
    above."""
    lines = [_PENCIL_HEADER, f"Prepared for {branch_display_name}."]
    for item in items:
        parts = []
        if item["tensions"]:
            parts.append("tension: " + " / ".join(item["tensions"]))
        if item["open_questions"]:
            parts.append("open: " + " / ".join(item["open_questions"]))
        if item.get("recognition"):
            parts.append(f'own recognition, in its own words: "{item["recognition"]}"')
        if item.get("objection_quote"):
            parts.append(f'visitor objection, verbatim: "{item["objection_quote"]}"')
        lines.append(f"- {item['title']} — " + " · ".join(parts))
    if hidden_count > 0:
        lines.append(f"+{hidden_count} more observation(s) not shown.")
    block = "\n".join(lines)
    if len(block) > MAX_PENCIL_CHARS:
        block = block[:MAX_PENCIL_CHARS].rstrip() + "\n[…truncated]"
    return block


def _pencil_item_for_thread(
    store: NarrativeStore,
    user_id: str,
    thread,
    *,
    evidence_text_resolver: EventTextResolver | None = None,
) -> dict | None:
    """One thread's pencil item, or None when it carries nothing.

    The whitelist, exactly: tensions (≤3) and open questions (≤2)
    from the latest CURRENT proposed reading — plus V3's two §9
    field classes:

    - **the seat's own recognition in its own words**: the
      ``recognition`` statement of the latest current proposed
      reading AUTHORED BY A SEAT (V1's seat-authored readings; the
      store admits only seat ids and ``steward``/``user`` as reading
      authors, so a non-steward, non-user author is a seat). The
      lineage retains the full sequence; only the latest current
      recognition travels.
    - **one verbatim objection quote**: sourced from the CURRENT
      recognition reading's evidence ONLY — a held objection note
      (V1) on this thread whose cited evidence ref is among that
      reading's own evidence rows, resolved to the visitor's
      verbatim words. An objection evidenced anywhere else on the
      thread does NOT qualify: widening the slot's sourcing to
      thread evidence generally is an open founder decision and is
      deliberately not implemented here.

    Nothing else in a reading's payload travels — due items,
    decisions, next steps, milestones and every other key stay
    retained-only, per §9."""
    proposed = store.readings_for(user_id, thread.id, status="proposed")
    if not proposed:
        return None
    # Phase 1A (organic currency): a reading retired by a
    # successor through change lineage keeps stored status
    # "proposed" but is history, not current material — it must
    # never be served as the thread's living observation. The
    # latest CURRENT proposed reading carries the pencil.
    currency = derive_currency(
        thread, proposed, store.changes_for(user_id, thread.id)
    )
    current = [r for r in proposed if currency[r.id].placement == "current"]
    if not current:
        return None
    reading = (current[-1].reading or {})
    tensions = [
        str(t).strip()[:_MAX_PENCIL_ITEM_CHARS]
        for t in (reading.get("tensions") or [])
        if str(t).strip()
    ][:_MAX_PENCIL_TENSIONS]
    questions = [
        str(q).strip()[:_MAX_PENCIL_ITEM_CHARS]
        for q in (reading.get("open_questions") or [])
        if str(q).strip()
    ][:_MAX_PENCIL_QUESTIONS]

    recognition = None
    recognition_reading = None
    for candidate in reversed(current):
        if candidate.author in ("steward", "user", ""):
            continue
        statement = str((candidate.reading or {}).get("recognition") or "").strip()
        if statement:
            recognition = statement[:_MAX_PENCIL_ITEM_CHARS]
            recognition_reading = candidate
            break

    objection_quote = None
    if recognition_reading is not None:
        rows_by_id = {
            row.id: row for row in store.evidence_for(user_id, thread.id)
        }
        reading_refs = {
            (rows_by_id[row_id].ref_kind, rows_by_id[row_id].ref_id)
            for row_id in (recognition_reading.evidence_refs or [])
            if row_id in rows_by_id
        }
        if reading_refs:
            resolver = evidence_text_resolver or _resolve_event_evidence_text
            objections = [
                note
                for note in store.held_notes_for(user_id, thread.id)
                if note.get("kind") == "objection"
                and (
                    note.get("evidence_ref_kind"),
                    note.get("evidence_ref_id"),
                )
                in reading_refs
            ]
            if objections:
                note = objections[-1]
                if note.get("evidence_ref_kind") == "event":
                    text = resolver(str(note.get("evidence_ref_id") or ""))
                    if text and str(text).strip():
                        objection_quote = str(text).strip()[
                            :_MAX_PENCIL_ITEM_CHARS
                        ]

    if not tensions and not questions and not recognition and not objection_quote:
        return None
    return {
        "thread_id": thread.id,
        # The selected reading's id rides the prepared
        # context's thread facts (never the rendered block:
        # pencil material carries no citable ids) so the
        # generation manifest can record WHICH reading the
        # turn's material came from (plan Q4.1 source ids).
        "reading_id": current[-1].id,
        "title": (thread.title or "")[:_MAX_TITLE_CHARS],
        "tensions": tensions,
        "open_questions": questions,
        "recognition": recognition,
        "objection_quote": objection_quote,
    }


def _collect_pencil_items(
    store: NarrativeStore,
    user_id: str,
    branch_id: str,
    threads: list,
    *,
    attended_text: str = "",
    attended_entity_refs: tuple[str, ...] | list[str] = (),
    attended_thread_ids: tuple[str, ...] | list[str] = (),
    connection=None,
    evidence_text_resolver: EventTextResolver | None = None,
) -> tuple[list[dict], list[str]]:
    """Per-thread preparation for the pencil channel: every thread
    re-validated fresh through ``prepare_context`` (dual consent
    flags re-read per thread, relevance recomputed, assessment
    recorded), fail-closed per thread — a thread that fails any
    gate contributes nothing, not even its title."""
    evidence_by_thread: dict[str, list] = {}
    known_refs: set[str] = set()
    for thread in threads:
        rows = store.evidence_for(user_id, thread.id)
        evidence_by_thread[thread.id] = rows
        for row in rows:
            if row.entity_ref:
                known_refs.add(row.entity_ref)
    attended = set(str(r) for r in attended_entity_refs)
    attended |= attended_refs_for_text(known_refs, attended_text)

    items: list[dict] = []
    assessment_ids: list[str] = []
    for thread in threads:
        thread_refs = [
            row.entity_ref for row in evidence_by_thread[thread.id] if row.entity_ref
        ]
        candidate_text = " ".join(
            part for part in (thread.title, thread.scope) if part
        )
        outcome = prepare_context(
            store,
            user_id,
            branch_id,
            thread_id=thread.id,
            candidate_text=candidate_text,
            candidate_entity_refs=thread_refs,
            candidate_strand_weights=thread.strand_weights,
            attended_entity_refs=sorted(attended),
            attended_thread_ids=attended_thread_ids,
            connection=connection,
        )
        if outcome.assessment is not None:
            assessment_ids.append(outcome.assessment.id)
        if not outcome.available:
            continue
        item = _pencil_item_for_thread(
            store, user_id, thread, evidence_text_resolver=evidence_text_resolver
        )
        if item is not None:
            items.append(item)
    return items, assessment_ids


def pencil_context_for(
    store: NarrativeStore,
    user_id: str,
    branch_id: str = PENCIL_BRANCH_ID,
    *,
    attended_text: str = "",
    attended_entity_refs: tuple[str, ...] | list[str] = (),
    attended_thread_ids: tuple[str, ...] | list[str] = (),
    connection=None,
    max_threads: int = MAX_PENCIL_THREADS,
) -> PreparedContext:
    """Prepare pencil-standing steward observations for one branch.

    Mirrors ``narrative_context_for``'s gate order and fail-closed
    discipline, with the master switch first: when the switch is off
    this returns before any store read or assessment write, so the
    channel's existence costs nothing and changes nothing. Raises
    ``ValueError`` for an unknown branch id, as the facts layer does.
    """
    if not pencil_context_enabled():
        return PreparedContext(available=False, reason="pencil_flag_off")
    contract = get_branch(branch_id)
    if contract is None:
        raise ValueError(f"unknown branch: {branch_id!r}")
    if "coordination" not in contract.capabilities:
        return PreparedContext(
            available=False, reason="branch_not_coordination_contracted"
        )
    if not coordination_allowed(user_id, connection=connection):
        return PreparedContext(available=False, reason="consent_closed")

    standing = [
        t
        for t in store.threads_for(user_id, limit=None)
        if t.status in CONTEXT_THREAD_STATUSES
    ]
    if not standing:
        return PreparedContext(available=False, reason="no_standing_threads")

    items, assessment_ids = _collect_pencil_items(
        store,
        user_id,
        branch_id,
        standing,
        attended_text=attended_text,
        attended_entity_refs=attended_entity_refs,
        attended_thread_ids=attended_thread_ids,
        connection=connection,
    )
    if not items:
        return PreparedContext(
            available=False,
            reason="no_pencil_material",
            assessment_ids=tuple(assessment_ids),
        )

    shown = items[:max_threads]
    hidden = len(items) - len(shown)
    block = _render_pencil_block(contract.display_name, shown, hidden)
    return PreparedContext(
        available=True,
        reason="available",
        block=block,
        threads=tuple(
            {
                "thread_id": item["thread_id"],
                "reading_id": item["reading_id"],
                "title": item["title"],
            }
            for item in shown
        ),
        assessment_ids=tuple(assessment_ids),
    )


def _encounter_pencil_items(
    store: NarrativeStore,
    user_id: str,
    conversation_id: str,
    *,
    attended_text: str = "",
    connection=None,
    evidence_text_resolver: EventTextResolver | None = None,
) -> tuple[list[dict], list[str]]:
    """The encounter-scope preparation path (V3 build element ii).

    The active encounter arc — V1's encounter scope for this
    conversation with the champion — made preparable DURING its own
    encounter. Encounter-born material sits in V1's holding state on
    a thread that is not a standing (active/dormant) thread, so the
    standing selection above can never see it; this path bridges
    exactly that, and nothing more: the one open encounter thread
    for (user, conversation, champion), prepared through the same
    ``prepare_context`` discipline as every standing thread — both
    steward consent flags re-read fresh, relevance recomputed and
    recorded, fail-closed. Relevance for the arc is established by
    attendance: the conversation attends its own arc by standing in
    it, so the encounter's thread id is supplied as attended (the
    same input the facts layer takes from its callers), alongside
    any entity refs the current message attends. A closed encounter
    is not prepared: carriage is an in-encounter act."""
    scope = store.open_encounter_for(
        user_id, conversation_id, CHAMPION_ARCHETYPE_ID
    )
    if scope is None:
        return [], []
    thread = store.get_thread(user_id, scope["thread_id"])
    if thread is None:
        return [], []
    items, assessment_ids = _collect_pencil_items(
        store,
        user_id,
        CHAMPION_BRANCH_ID,
        [thread],
        attended_text=attended_text,
        attended_thread_ids=(thread.id,),
        connection=connection,
        evidence_text_resolver=evidence_text_resolver,
    )
    return items, assessment_ids


def champion_pencil_context_for(
    store: NarrativeStore,
    user_id: str,
    *,
    conversation_id: str,
    attended_text: str = "",
    attended_entity_refs: tuple[str, ...] | list[str] = (),
    attended_thread_ids: tuple[str, ...] | list[str] = (),
    connection=None,
    evidence_text_resolver: EventTextResolver | None = None,
    max_threads: int = MAX_PENCIL_THREADS,
) -> PreparedContext:
    """Prepare pencil-standing carriage for the champion (V3).

    Gate order mirrors :func:`pencil_context_for`, with the
    carriage toggle second: master switch off ⇒ nothing; carriage
    toggle off ⇒ nothing (and no store read or assessment write
    happens on either early return — the toggle gates rendering
    only, and a dark carriage costs nothing). What renders is the
    active encounter arc (encounter-scope preparation, above)
    alongside the standing-thread selection that exists today, under
    the one existing header and caps, the encounter's own arc first.
    """
    if not pencil_context_enabled():
        return PreparedContext(available=False, reason="pencil_flag_off")
    if not pencil_champion_enabled():
        return PreparedContext(
            available=False, reason="pencil_champion_flag_off"
        )
    contract = get_branch(CHAMPION_BRANCH_ID)
    if contract is None:
        raise ValueError(f"unknown branch: {CHAMPION_BRANCH_ID!r}")
    if "coordination" not in contract.capabilities:
        return PreparedContext(
            available=False, reason="branch_not_coordination_contracted"
        )
    if not coordination_allowed(user_id, connection=connection):
        return PreparedContext(available=False, reason="consent_closed")

    encounter_items, encounter_assessments = _encounter_pencil_items(
        store,
        user_id,
        conversation_id,
        attended_text=attended_text,
        connection=connection,
        evidence_text_resolver=evidence_text_resolver,
    )

    standing = [
        t
        for t in store.threads_for(user_id, limit=None)
        if t.status in CONTEXT_THREAD_STATUSES
    ]
    standing_items: list[dict] = []
    standing_assessments: list[str] = []
    if standing:
        standing_items, standing_assessments = _collect_pencil_items(
            store,
            user_id,
            CHAMPION_BRANCH_ID,
            standing,
            attended_text=attended_text,
            attended_entity_refs=attended_entity_refs,
            attended_thread_ids=attended_thread_ids,
            connection=connection,
            evidence_text_resolver=evidence_text_resolver,
        )

    assessment_ids = encounter_assessments + standing_assessments
    seen: set[str] = set()
    items: list[dict] = []
    for item in encounter_items + standing_items:
        if item["thread_id"] in seen:
            continue
        seen.add(item["thread_id"])
        items.append(item)
    if not items:
        return PreparedContext(
            available=False,
            reason="no_pencil_material",
            assessment_ids=tuple(assessment_ids),
        )

    shown = items[:max_threads]
    hidden = len(items) - len(shown)
    block = _render_pencil_block(contract.display_name, shown, hidden)
    return PreparedContext(
        available=True,
        reason="available",
        block=block,
        threads=tuple(
            {
                "thread_id": item["thread_id"],
                "reading_id": item["reading_id"],
                "title": item["title"],
            }
            for item in shown
        ),
        assessment_ids=tuple(assessment_ids),
    )


def champion_context_provider(
    store: NarrativeStore | None = None,
    *,
    connection=None,
    with_selection: bool = False,
    evidence_text_resolver: EventTextResolver | None = None,
) -> object:
    """A chat-path provider returning the champion's pencil block (V3).

    Same contract as :func:`jynx_context_provider`, plus the
    conversation the turn belongs to: the service hands it as the
    ``conversation_id`` keyword, because encounter carriage is keyed
    to the encounter's own conversation — without it the provider
    fails closed and returns None. Takes ``(user_id, message,
    history)``, returns the block string or None, never raises. With
    either switch off (the default) it returns None before touching
    the store.
    """

    state: dict[str, NarrativeStore | None] = {"store": store}

    def provider(user_id: str, message: str, history=None, *, conversation_id=None):
        try:
            if not pencil_context_enabled() or not pencil_champion_enabled():
                return None
            if not conversation_id:
                return None
            if state["store"] is None:
                state["store"] = NarrativeStore()
            prepared = champion_pencil_context_for(
                state["store"],
                user_id,
                conversation_id=conversation_id,
                attended_text=message or "",
                connection=connection,
                evidence_text_resolver=evidence_text_resolver,
            )
            return prepared if with_selection else prepared.block
        except Exception:
            return None

    return provider


def jynx_context_provider(
    store: NarrativeStore | None = None,
    *,
    connection=None,
    with_selection: bool = False,
) -> object:
    """A chat-path provider returning the Jynx's pencil block.

    Same contract as ``weaver_context_provider``: takes
    ``(user_id, message, history)``, returns the block string or
    None, never raises. With the master switch off (the default) it
    returns None before touching the store. ``with_selection=True``
    returns the full :class:`PreparedContext` instead of the block
    string, exactly as on the Weaver's provider — the selected
    thread/reading ids ride its ``threads`` facts for the
    generation manifest, never the rendered block.
    """

    state: dict[str, NarrativeStore | None] = {"store": store}

    def provider(user_id: str, message: str, history=None):
        try:
            if not pencil_context_enabled():
                return None
            if state["store"] is None:
                state["store"] = NarrativeStore()
            prepared = pencil_context_for(
                state["store"],
                user_id,
                PENCIL_BRANCH_ID,
                attended_text=message or "",
                connection=connection,
            )
            return prepared if with_selection else prepared.block
        except Exception:
            return None

    return provider
