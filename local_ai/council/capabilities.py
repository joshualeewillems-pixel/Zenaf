"""Capability registry — the one shared source of truth for what Zenaf
offers, per the approved first-meeting demonstration spec §6.

Every capability is recorded ONCE, capability-first: one definition,
referenced by seats (a primary seat plus also-relevant seats where
applicable). Prompts never duplicate hardcoded feature promises —
frames render slices of this registry, so a status changes in exactly
one place.

Three fields, never collapsed (demonstration spec §6 + the settled
registry refinements):

- ``implementation`` — available / limited-experimental / planned.
  "Available" here means CODE availability (backend mounted + a
  user-facing surface in code). It does NOT mean the visitor-facing
  workflow was tested end to end — that is the verification field.
- ``verification`` — verified / unverified. Nothing is promoted to
  verified without supporting evidence, recorded in ``evidence``.
- ``prerequisite_note`` — what this visitor needs before they can
  use it. Contextual availability is resolved at conversation time
  from the visitor's actual state (see ``currently_usable``), never
  from model inference. The registry describes capabilities; it never
  grants access and never overrides permissions or consent.

Planned capabilities stay visible but explicitly unavailable: the
slice renders them as "planned, not available yet", and the character
may discuss intended direction aspirationally ("we're aiming to…")
only while knowing it speaks aspirationally — never drifting into
implying current availability.

Steward-contract note (design only, no steward code here): entries
carry stable ``id`` values and are capability-first, so the later
steward framework can reference capabilities by id for
tending-signals. This module builds no steward, driver,
tending-signal, or negotiated-initiative machinery.

Re-audited 2026-10-25 against main at 34d96f58 (post-#210/#211),
correcting the 96e416f audit in one place: per-scope toggle UI was
recorded as "not verified" from a backend-only grep, but the
Settings → Identity grant/revoke UI plus backend /scopes endpoints
exist and are reachable (present since 96e416f). It is recorded here
as implementation-available with verification unverified — the
workflow itself has no playtest evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from local_ai.council import steward_records as _steward_records

#: Canonical seat order (archetype ids, matching
#: local_ai/council/jurisdictions.py and archetypes.stock_archetype_ids()).
SEAT_IDS = (
    "conductor",
    "mentor",
    "champion",
    "guardian",
    "ambassador",
    "skeptic",
    "maverick",
)

IMPLEMENTATION_STATUSES = ("available", "limited-experimental", "planned")
VERIFICATION_STATUSES = ("verified", "unverified")

#: Prerequisite keys that gate even STARTING a capability. Anything
#: else (notably per-claim review approval, which gates the training
#: ACTION at review time) lives in the human-readable
#: ``prerequisite_note`` and never blocks the conversation about it.
PREREQUISITE_KEYS = ("signed_in", "consent_acknowledged")

#: The ONE shared intention line (demonstration spec §3/§6). It lives
#: in first-meeting frames only — never in continuation frames.
INTENTION_LINE = (
    "when a natural opportunity arises, offer something characteristic "
    "of what you do here; prefer a real action or interaction over an "
    "abstract description; never force an example, manufacture a need, "
    "or imply that an action occurred when it didn't"
)

#: Standing honesty guard, first-meeting frames only. It restates the
#: illustration/action distinction (demonstration spec §5) as a frame
#: constraint; it is not an instruction to offer anything.
HONESTY_GUARD = (
    "Never present a planned capability as available, a hypothetical "
    "as an action, or a gated capability as immediately usable."
)


@dataclass(frozen=True)
class Capability:
    """One capability, defined once. Seats reference it; nobody
    redefines it."""

    #: Stable id — the steward framework's future reference key.
    id: str
    #: Short human name, rendered in slices.
    name: str
    #: Frame-visible clarifier, rendered in parentheses after the
    #: name when present (e.g. the never-observed policy distinction).
    detail: str = ""
    #: Primary seat (archetype id), or None for unassigned.
    #: Suggestions stay unassigned until a jurisdiction claims them.
    primary_seat: str | None = None
    #: Additional seats whose slice includes this capability.
    also_relevant: tuple[str, ...] = ()
    #: One of IMPLEMENTATION_STATUSES. "Available" = code availability
    #: (backend mounted + user-facing surface in code), NOT verified
    #: end-to-end operation.
    implementation: str = "planned"
    #: One of VERIFICATION_STATUSES. "Verified" requires evidence.
    verification: str = "unverified"
    #: Grounding: endpoints/files for code availability, and/or the
    #: playtest or run that verified the workflow. Empty only where
    #: the audit found nothing at all (planned items still cite the
    #: negative finding).
    evidence: str = ""
    #: Gating prerequisite keys (subset of PREREQUISITE_KEYS).
    prerequisites: tuple[str, ...] = ()
    #: Human-readable prerequisite/eligibility note. Always present:
    #: it is the third field, and it is what a gated rendering quotes.
    prerequisite_note: str = ""


@dataclass(frozen=True)
class VisitorState:
    """The visitor facts contextual availability may be resolved
    from. ``consent_acknowledged=None`` means unknown — and unknown
    fails CLOSED: a consent-gated capability is rendered gated, never
    implied usable."""

    signed_in: bool = True
    consent_acknowledged: bool | None = None


# ---------------------------------------------------------------------------
# The registry — one definition per capability.
# ---------------------------------------------------------------------------

CAPABILITIES: tuple[Capability, ...] = (
    # -- Conductor / Weaver — council and tree --
    Capability(
        id="first_meetings",
        name="First meetings",
        primary_seat="conductor",
        implementation="available",
        verification="verified",
        evidence=(
            "conversation_routes /meeting/start|turn|pause|complete; "
            "MeetingView.tsx; staging baseline playtest 2026-10-24 "
            "(Weaver K1 completed via the Complete button; playtest #5)."
        ),
        prerequisites=("signed_in",),
        prerequisite_note=(
            "Signed-in account. Only the Conductor's first meeting is "
            "scripted so far; other seats have no meeting to begin yet."
        ),
    ),
    Capability(
        id="seat_chat",
        name="One-on-one seat chat",
        primary_seat="conductor",
        implementation="available",
        verification="unverified",
        evidence=(
            "conversation_routes /conversation/turn; CouncilChat.tsx. "
            "No playtest evidence recorded."
        ),
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account.",
    ),
    Capability(
        id="fellowship_attention",
        name="Fellowship attention (!)",
        primary_seat="conductor",
        implementation="available",
        verification="verified",
        evidence=(
            "fellowship/attention.py + derivation.candidate_seats; "
            "seen live in playtest #5; clears on meeting."
        ),
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account.",
    ),
    Capability(
        id="tree_view",
        name="Tree view and branch panels",
        detail="the tree mapping conversations and artifacts",
        primary_seat="conductor",
        implementation="available",
        verification="unverified",
        evidence=(
            "living-tree/LivingTree.tsx; tree/NodeSheet.tsx; inline "
            "narrative panels. No playtest evidence recorded."
        ),
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account.",
    ),
    Capability(
        id="convened_council",
        name="Convened multi-seat council",
        primary_seat="conductor",
        implementation="planned",
        verification="unverified",
        evidence="No convened endpoint found.",
        prerequisite_note="Unbuilt — explain, never offer.",
    ),
    Capability(
        id="marketplace_info",
        name="Marketplace info via the tree",
        primary_seat="conductor",
        implementation="planned",
        verification="unverified",
        evidence="No marketplace router; marketplace is phase 2.",
        prerequisite_note="Phase 2 — explain, never offer.",
    ),
    Capability(
        id="artifact_provenance",
        name="Artifact provenance",
        detail="recorded origin of an artifact — not rental or listing disclosure",
        primary_seat="conductor",
        implementation="available",
        verification="unverified",
        evidence=(
            "provenance_router (register/mint/publish/lineage/ledger) "
            "mounted. Workflow not playtest-verified."
        ),
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account.",
    ),
    # -- Mentor / Gardener — training and growth --
    Capability(
        id="import_uploads",
        name="Conversation-export import",
        primary_seat="mentor",
        also_relevant=("maverick",),
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "ingest_router + agent-intake UI; proven on the staging "
            "TEST account only; own-account run still awaiting call. "
            "Same flow serves the Mentor and Maverick slices."
        ),
        prerequisites=("signed_in", "consent_acknowledged"),
        prerequisite_note=(
            "Consent acknowledged; nothing trains without per-claim "
            "review approval."
        ),
    ),
    Capability(
        id="training_distillation",
        name="Training and distillation",
        primary_seat="mentor",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "Meta provider + per-strand depth/blend APIs; dedicated "
            "training UI not verified."
        ),
        prerequisites=("signed_in", "consent_acknowledged"),
        prerequisite_note=(
            "Consent acknowledged; review approval per claim — "
            "nothing trains without it."
        ),
    ),
    Capability(
        id="snapshots_eras",
        name="Snapshots and eras",
        primary_seat="mentor",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "Immutable snapshots + era addressing in personality/"
            "temporal.py; dedicated snapshot/era UI not verified."
        ),
        prerequisites=("signed_in",),
        prerequisite_note=(
            "Signed-in account; dedicated snapshot/era UI not verified."
        ),
    ),
    Capability(
        id="signal_decay",
        name="Signal decay",
        primary_seat="mentor",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "temporal.signal_relevance and find_parallels exist; "
            "180-day decay wiring into council-time weighting not "
            "verified."
        ),
        prerequisite_note=(
            "Decay wiring into council-time weighting not verified."
        ),
    ),
    Capability(
        id="growth_records",
        name="Growth records",
        primary_seat="mentor",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "followthrough /entities/.../growth GET/PATCH; UI not "
            "verified."
        ),
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account; UI not verified.",
    ),
    Capability(
        id="specializations",
        name="Specializations (twigs)",
        primary_seat="mentor",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "council_twigs_router (list/detect/approve/delete) "
            "mounted; twig UI not verified."
        ),
        prerequisites=("signed_in",),
        prerequisite_note=(
            "Signed-in account; review approval for new "
            "specializations; twig UI not verified."
        ),
    ),
    # -- Champion / Firebrand — projects, tasks, commitments --
    Capability(
        id="projects_tasks",
        name="Projects and tasks",
        primary_seat="champion",
        implementation="available",
        verification="unverified",
        evidence=(
            "vision_execution_router mounted; vision-execution/ "
            "frontend incl. timeline. End-to-end UI completeness not "
            "playtest-verified."
        ),
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account.",
    ),
    Capability(
        id="commitments",
        name="Commitments",
        primary_seat="champion",
        implementation="available",
        verification="unverified",
        evidence="followthrough /commitments GET/POST/PATCH mounted.",
        prerequisites=("signed_in",),
        prerequisite_note=(
            "Signed-in account; the visitor chooses — naming one "
            "does not create it."
        ),
    ),
    Capability(
        id="followthrough_nudges",
        name="Follow-through nudges",
        primary_seat="champion",
        implementation="available",
        verification="unverified",
        evidence="followthrough /nudges GET, ack/snooze mounted.",
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account.",
    ),
    # -- Guardian / Bear — consent, redaction, never observed --
    # Four different mechanisms, rowed separately. Never-observed is
    # a policy guarantee, NOT a configurable setting or toggle.
    Capability(
        id="redaction",
        name="Redaction at capture",
        primary_seat="guardian",
        implementation="available",
        verification="unverified",
        evidence=(
            "presence_ingest.redact used by the intake pipeline "
            "('only redacted text is stored or sorted')."
        ),
        prerequisite_note="Automatic; applies to intake.",
    ),
    Capability(
        id="consent_enforcement",
        name="Consent-scope enforcement",
        primary_seat="guardian",
        implementation="available",
        verification="unverified",
        evidence="identity.scopes.require_scope; default-deny.",
        prerequisite_note="Backend enforcement; default-deny.",
    ),
    Capability(
        id="consent_onboarding",
        name="Consent onboarding gate",
        primary_seat="guardian",
        implementation="available",
        verification="unverified",
        evidence=(
            "auth/ConsentOnboardingGate.tsx; settings consent "
            "acknowledgement."
        ),
        prerequisite_note="New visitors complete onboarding consent first.",
    ),
    Capability(
        id="scope_toggles",
        name="Per-scope toggles",
        primary_seat="guardian",
        implementation="available",
        verification="unverified",
        evidence=(
            "Re-audit 2026-10-25 (correcting the 96e416f audit, which "
            "grepped settings_routes only): backend GET/POST /scopes "
            "plus Settings → Identity grant/revoke UI, reachable via "
            "SettingsView, present since 96e416f. Workflow not "
            "playtest-verified."
        ),
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account; Settings → Identity.",
    ),
    Capability(
        id="never_observed",
        name="Never observed",
        detail="a data-handling policy guarantee, not a configurable setting or toggle",
        primary_seat="guardian",
        implementation="available",
        verification="unverified",
        evidence=(
            "Context envelope excludes internal states by design."
        ),
        prerequisite_note=(
            "A data-handling guarantee, not a user-facing control."
        ),
    ),
    # -- Ambassador / Crane — voice travel, rentals, zones, disclosures --
    Capability(
        id="voice_chat",
        name="Voice chat",
        primary_seat="ambassador",
        implementation="available",
        verification="unverified",
        evidence=(
            "voice_router /voice/chat; VoiceConsole.tsx (re-skinned "
            "onto CouncilChat); CouncilChat fallback. No playtest "
            "evidence recorded."
        ),
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account.",
    ),
    Capability(
        id="echo_rentals",
        name="Echo rentals",
        primary_seat="ambassador",
        implementation="planned",
        verification="unverified",
        evidence="No rental/marketplace router.",
        prerequisite_note="Phase 2 — explain, never offer.",
    ),
    Capability(
        id="zones",
        name="Zones (rental slicing)",
        primary_seat="ambassador",
        implementation="planned",
        verification="unverified",
        evidence="No zones implementation found.",
        prerequisite_note="Phase 2 — explain, never offer.",
    ),
    Capability(
        id="listing_disclosures",
        name="Listing disclosures",
        primary_seat="ambassador",
        implementation="planned",
        verification="unverified",
        evidence="No listings exist, so no listing disclosures exist.",
        prerequisite_note="Phase 2 — explain, never offer.",
    ),
    Capability(
        id="represented_in_councils",
        name="Being represented in other people's councils",
        primary_seat="ambassador",
        implementation="planned",
        verification="unverified",
        evidence="No representation mechanism found.",
        prerequisite_note="Phase 2 — explain, never offer.",
    ),
    # -- Skeptic / Raven — checking, review queue, evidence, blend --
    Capability(
        id="review_intake",
        name="Review queue — intake candidates",
        primary_seat="skeptic",
        implementation="available",
        verification="unverified",
        evidence=(
            "ingest /sessions/{id}/review; agent-intake/ReviewView. "
            "Staging TEST-account run 2026-10-23 produced 18 pending "
            "candidates; the approve path was not exercised, so the "
            "workflow is not promoted to verified."
        ),
        prerequisites=("signed_in", "consent_acknowledged"),
        prerequisite_note="Consent + review approval flow.",
    ),
    Capability(
        id="review_insights_ui",
        name="Review queue — personality claims",
        primary_seat="skeptic",
        implementation="planned",
        verification="unverified",
        evidence="No dedicated insights-review UI found.",
        prerequisite_note=(
            "Intake review covers import candidates only — do not "
            "imply broader review UI exists."
        ),
    ),
    Capability(
        id="anchored_evidence",
        name="Anchored evidence",
        primary_seat="skeptic",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "Narrative store evidence references (S0); "
            "presence-review/ frontend dir exists; end-to-end "
            "evidence display not verified."
        ),
        prerequisites=("signed_in",),
        prerequisite_note=(
            "Signed-in account; end-to-end evidence display not "
            "verified."
        ),
    ),
    Capability(
        id="contest_read",
        name="Contesting a read",
        primary_seat="skeptic",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "Review gate allows correction per doctrine; intake "
            "approve/reject exists; personality-claim contest UI not "
            "verified."
        ),
        prerequisite_note=(
            "Visitor correction always allowed in conversation; "
            "personality-claim contest UI not verified."
        ),
    ),
    Capability(
        id="recurrence",
        name="Recurrence patterns",
        primary_seat="skeptic",
        implementation="limited-experimental",
        verification="unverified",
        evidence="temporal.find_parallels backend exists; UI not verified.",
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account; UI not verified.",
    ),
    Capability(
        id="blend_view",
        name="Blend view",
        primary_seat="skeptic",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "council_mode (base/mirror/blend) + per-strand blend "
            "weights API in personality_routes; dedicated blend-view "
            "UI not verified."
        ),
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account; dedicated blend-view UI not verified.",
    ),
    # -- Maverick / Fox — import, bring-your-own key, export, reshape --
    Capability(
        id="byo_key",
        name="Bring-your-own key",
        primary_seat="maverick",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "openrouter_oauth_router (/llm/openrouter/oauth/"
            "initiate|exchange) mounted under /settings; direct "
            "key-entry UI not verified."
        ),
        prerequisites=("signed_in",),
        prerequisite_note=(
            "Signed-in account; Settings access; OAuth flow. Direct "
            "key-entry UI not verified."
        ),
    ),
    Capability(
        id="export_all",
        name="Export everything",
        primary_seat="maverick",
        implementation="planned",
        verification="unverified",
        evidence=(
            "No export-all endpoint found; studio/vision_execution "
            "export functions are narrower (their own outputs)."
        ),
        prerequisite_note=(
            "No export-all endpoint — do not claim full export exists."
        ),
    ),
    Capability(
        id="rename_reshape",
        name="Rename and reshape seats",
        primary_seat="maverick",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "Twigs approve/delete exist; user-renamed seats supported "
            "in prompt lines; seat rename/reshape UI not verified."
        ),
        prerequisites=("signed_in",),
        prerequisite_note=(
            "Signed-in account; review approval where applicable; "
            "seat rename/reshape UI not verified."
        ),
    ),
    # -- Unassigned: suggestions belong to no seat's slice until a
    # jurisdiction claims them. Never defaulted to the Weaver. --
    Capability(
        id="suggestions",
        name="Suggestions",
        detail="three kinds, drafts only — never filed, never pushed",
        primary_seat=None,
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "GET /conversation/suggestions; three kinds, drafts; UI "
            "surface not verified."
        ),
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account; drafts only.",
    ),
)

_BY_ID = {c.id: c for c in CAPABILITIES}


def get_capability(capability_id: str) -> Capability | None:
    return _BY_ID.get((capability_id or "").strip().lower())


def normalize_seat(seat: str | None) -> str:
    return (seat or "").strip().lower()


def seat_slice(seat: str | None) -> tuple[Capability, ...]:
    """The capabilities one seat's frame may mention: its primary
    entries plus entries where it is also-relevant, in registry
    order. Unassigned capabilities (suggestions) appear in NO
    slice. Unknown seats get an empty slice."""
    seat = normalize_seat(seat)
    if seat not in SEAT_IDS:
        return ()
    return tuple(
        c for c in CAPABILITIES
        if c.primary_seat == seat or seat in c.also_relevant
    )


def currently_usable(cap: Capability, state: VisitorState) -> bool:
    """Contextual availability, resolved from actual visitor state —
    never from model inference. Planned is never usable. A required
    prerequisite the state does not affirmatively satisfy (including
    unknown consent) gates the capability: it is rendered gated, and
    the character explains the prerequisite instead of offering it.
    The registry grants nothing; route-level permission and consent
    enforcement still apply at action time."""
    if cap.implementation == "planned":
        return False
    if "signed_in" in cap.prerequisites and not state.signed_in:
        return False
    if (
        "consent_acknowledged" in cap.prerequisites
        and state.consent_acknowledged is not True
    ):
        return False
    return True


def resolve_visitor_state(user_id: str | None) -> VisitorState:
    """Resolve a visitor's state for contextual availability. Read
    ONLY: a direct SELECT on the permissions row. The settings
    helper (get_user_permissions_settings) must NOT be used here —
    it INSERTs a row for unknown users, a write that does not belong
    on the prompt path. Any failure resolves to unknown consent,
    which fails closed (consent-gated capabilities render gated)."""
    if not user_id:
        return VisitorState(signed_in=False, consent_acknowledged=None)
    try:
        from local_ai.vision_execution.storage import get_connection

        conn = get_connection()
        row = conn.execute(
            "SELECT consent_given FROM user_permissions_settings "
            "WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return VisitorState(signed_in=True, consent_acknowledged=None)
        return VisitorState(
            signed_in=True, consent_acknowledged=bool(row["consent_given"])
        )
    except Exception:
        return VisitorState(signed_in=True, consent_acknowledged=None)


def _status_text(cap: Capability, state: VisitorState) -> str:
    """One short status rendering. Planned is always explicitly
    unavailable; gated is never implied usable; unverified workflows
    are never described as verified."""
    if cap.implementation == "planned":
        return "planned, not available yet"
    if not currently_usable(cap, state):
        note = cap.prerequisite_note or "prerequisite not met"
        return f"not available to you yet — {note}"
    if cap.implementation == "limited-experimental":
        return "available in limited form (workflow not yet verified)"
    if cap.verification == "verified":
        return "available"
    return "available (workflow not yet verified)"


def _render_lines(seat: str | None, state: VisitorState) -> list[str]:
    """Render one seat's capability lines for a prompt frame.

    Weaver consolidation (mandate P2–P3): when the steward read path is
    active, the conductor slice is built from the steward record source
    instead of the registry table; the rendering logic (status text,
    prerequisite gating) is unchanged shared code, and the values are
    identical (module == Phase 1 JSON, checked mechanically). The
    registry table stays as the rollback source. Other seats never
    consult the steward module.
    """
    lines: list[str] = []
    if (normalize_seat(seat) == "conductor"
            and _steward_records.weaver_steward_active()):
        caps: tuple[Capability, ...] = tuple(
            Capability(
                id=c["id"],
                name=c["name"],
                detail=c.get("detail") or "",
                primary_seat="conductor",
                implementation=c["implementation"],
                verification=c["verification"],
                evidence=c.get("evidence") or "",
                prerequisites=tuple(c.get("prerequisites") or ()),
                prerequisite_note=c.get("prerequisite_note") or "",
            )
            for c in _steward_records.CAPABILITIES
        )
    else:
        caps = seat_slice(seat)
    for cap in caps:
        head = f"- {cap.name}"
        if cap.detail:
            head += f" ({cap.detail})"
        lines.append(f"{head} — {_status_text(cap, state)}")
    return lines


def first_meeting_block(seat: str | None, state: VisitorState) -> str:
    """The first-meeting frame's capability context: the seat's own
    slice as knowledge, plus the ONE shared intention line and the
    standing honesty guard. Empty for unknown seats (no slice, no
    intention line). This is the only place the intention line is
    defined for frames; continuations never receive it."""
    lines = _render_lines(seat, state)
    if not lines:
        return ""
    header = (
        "What you can introduce, explain, or offer from your scope "
        "(knowledge, not a list to work through):"
    )
    return "\n".join([header, *lines, INTENTION_LINE, HONESTY_GUARD])


def continuation_block(seat: str | None, state: VisitorState) -> str:
    """The continuation frame's capability context: the slice as
    BACKGROUND KNOWLEDGE ONLY. No intention line, no per-turn
    instruction to offer a feature, no onboarding agenda — a seat
    that repeats an offer every turn is performing a tutorial, not
    retaining knowledge."""
    lines = _render_lines(seat, state)
    if not lines:
        return ""
    header = (
        "Background knowledge — things in your scope (knowledge only, "
        "never an agenda or a list to work through):"
    )
    return "\n".join([header, *lines])
