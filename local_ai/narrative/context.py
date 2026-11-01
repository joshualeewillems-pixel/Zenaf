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
  count. Readings (interpretations) are never rendered into a seat's
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

import re
from dataclasses import dataclass, field

from .branches import get_branch
from .consent import coordination_allowed
from .coordination import prepare_context
from .store import NarrativeStore

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
        available_facts.append(
            {
                "thread_id": thread.id,
                "title": (thread.title or "")[:_MAX_TITLE_CHARS],
                "status": thread.status,
                "scope": (thread.scope or "")[:_MAX_SCOPE_CHARS],
                "evidence_count": len(evidence_by_thread[thread.id]),
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
    """

    state: dict[str, NarrativeStore | None] = {"store": store}

    def provider(user_id: str, message: str, history=None) -> str | None:
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
            return prepared.block
        except Exception:
            return None

    return provider
