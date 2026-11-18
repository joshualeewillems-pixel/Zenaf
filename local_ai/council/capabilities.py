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

Re-audited 2026-11-17 against the WI-4 verified capability
inventory (founder verdict 2026-11-17, §2): the registry holds 35
capabilities (the earlier count of 36 mistook the dynamic
constructor in _render_lines for an entry). Text is aligned to
demonstrated capability, real ownership, enforced permissions, and
verification standing: five status fields corrected
(fellowship_attention verified → unverified; signal_decay
limited-experimental → planned, described as inactive;
never_observed available → limited-experimental, narrowed to its
demonstrated enforcement coverage; review_insights_ui planned →
available; export_all planned → limited-experimental and its
display name corrected to Identity & Presence Takeout, id
unchanged), with evidence/note/detail corrections on seventeen
further entries. Prerequisite tuples are unchanged: they gate
prompt rendering, not routes. The WI-4 security findings stand in
this audit record — D-1 (ingest and review routes enforce no
session-auth or consent prerequisite), D-6 (the per-scope toggle
backend enforces no authentication and grant/revoke write to the
global scope ledger), D-14 (the takeout route requires no
signed-in session), D-4 (raw uploaded export files are retained
verbatim; redaction covers stored events and signals only).
Entries 8, 20, 27, and 34 describe that enforcement as it exists
at this revision; correcting the enforcement itself is the
security-correction proposal's scope, not this alignment's.

Post-merge update 2026-11-17: the security correction has since
merged (PR #388, main 8beae48) and was verified live on staging,
so the five affected entries — import_uploads (8), redaction
(18), scope_toggles (20), review_intake (27), and export_all
(34) — now describe the corrected enforcement: ingest and
review routes behind a session-auth + installation-owner
dependency resolved before any presence-store access (D-1);
license and scopes routes owner-gated, scope writes recorded
under the owner's identity, and historical global grants
preserved only in the owner's fold and reported distinctly as
unverified provenance (D-6); the takeout route owner-gated at
route and service layer with bundle contents unchanged (D-14);
and imports parsed in place from the request's temporary file
with no persistent raw copy retained (D-4). The findings above
stand as the record of the state this alignment first described.
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
#: RESOLVED (Conductor agency refinement, 2026-10-28): the apparent
#: contradiction with the block header ("knowledge, not a list to
#: work through") is resolved by accepting the line as a deliberate
#: offer instruction, not by scoping it out of first-meeting frames.
#: The line itself already says when (a natural opportunity), how
#: (a real action over an abstract description), and never (forced,
#: manufactured, or implied as occurred) — permission, not an agenda
#: and not a list to work through. The Weaver frames' own "you may
#: show one real thing" wording now reads the same way, so the block
#: and the frames agree; scoping the line out would have removed the
#: permission the agency direction needs.
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
    "as an action, a gated capability as immediately usable, or a "
    "limited, unverified workflow as something you can do or offer."
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
    #: Action-honesty note (Firebrand FC4 companion, 2026-11-07):
    #: one sentence appended to the capability's own status line
    #: when set and the capability is currently usable — so the
    #: note rides ONLY where the workflow is actually available,
    #: never on a planned or gated line. The field is optional and
    #: defaults to ""; the rendering rule is part of _render_lines.
    prompt_note: str = ""


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
            "Signed-in account. All seven first meetings are written "
            "and released (all seats released 2026-10-29)."
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
        verification="unverified",
        evidence=(
            "fellowship/attention.py read model + derivation."
            "candidate_seats; markers seen live in playtest #5. "
            "Keystone-sourced markers clear when the keystone "
            "completes. Observation-sourced markers clear only on "
            "discussed/dismissed status, and no production code "
            "path transitions an observation when a meeting happens "
            "(ObservationStore.set_status has no production caller) "
            "— observation markers have no production clearing "
            "path today."
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
        evidence=(
            "No marketplace router, endpoint, or data source; "
            "marketplace is phase 2. (A 'Marketplace'-labelled "
            "placeholder in the character panel shows only a "
            "training-depth 'Viability' bar — it presents no "
            "marketplace information.)"
        ),
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
            "provenance_router (register/mint/publish/derive/"
            "lineage/ledger) mounted, and a complete user surface "
            "exists in code (provenance/ProvenanceView.tsx, wired "
            "in App.tsx). User-operated; no seat executes "
            "provenance actions in conversation. Workflow not "
            "playtest-verified."
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
            "ingest_router mounted (upload/distill/candidates/"
            "review); UIs are chat/StrandPanel.tsx and "
            "presence-review/SignalReviewView.tsx (the agent-intake "
            "UI does not call these endpoints). Proven on the "
            "staging TEST account only; own-account run still "
            "awaiting call. Route enforcement (security "
            "correction D-1, merged PR #388, verified live on "
            "staging 2026-11-17): every ingest route carries a "
            "router-level session-auth + installation-owner "
            "dependency — 401 unauthenticated, 403 non-owner, "
            "resolved before any access to the singleton "
            "presence store. An active identity license for "
            "upload and the train:self scope for distill remain "
            "as the operation-specific second layer; the routes "
            "do not check consent_acknowledged, and the recorded "
            "prerequisites gate prompt rendering only."
        ),
        prerequisites=("signed_in", "consent_acknowledged"),
        prerequisite_note=(
            "Import requires a signed-in installation-owner "
            "session and an active identity license; distilling "
            "requires the train:self scope. Distilled material "
            "becomes pending candidates — nothing trains without "
            "per-claim review approval."
        ),
    ),
    Capability(
        id="training_distillation",
        name="Training and distillation",
        primary_seat="mentor",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "Distillation runs on the local Ollama instance by "
            "default (presence_ingest/distill.py), producing "
            "pending candidates only; per-strand depth/blend APIs "
            "exist. Publishing a profile version is the sole "
            "mirror-changing act and is an explicit user act. No "
            "frontend surface calls the candidate/publish "
            "endpoints — API-only in code."
        ),
        prerequisites=("signed_in", "consent_acknowledged"),
        prerequisite_note=(
            "Consent acknowledged. Distillation alone changes "
            "nothing: candidates stay pending until an explicit "
            "publish (signed-in, train:self scope). Import-derived "
            "candidates pass per-claim review; a candidate can "
            "also be proposed directly and published without "
            "ingest review."
        ),
    ),
    Capability(
        id="snapshots_eras",
        name="Snapshots and eras",
        primary_seat="mentor",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "Immutable snapshots (storage in personality/store.py; "
            "snapshot/era logic in personality/temporal.py) with "
            "era addressing at the API; no UI exists in code. "
            "Snapshot triggers fire only on an explicit "
            "check-triggers call — no scheduler is built."
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
        implementation="planned",
        verification="unverified",
        evidence=(
            "Inactive. temporal.signal_relevance and "
            "rank_signals_by_relevance exist as library functions "
            "with zero production callers; the 180-day decay is "
            "not wired into council-time weighting or any other "
            "product path — nothing decays in the running system. "
            "(find_parallels is a separate helper; its one "
            "production use counts parallels for the YOU profile "
            "and applies no decay.)"
        ),
        prerequisite_note=(
            "Inactive — not wired into the running system. "
            "Explain as intended direction only, never as "
            "operating behaviour."
        ),
    ),
    Capability(
        id="growth_records",
        name="Growth records",
        primary_seat="mentor",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "followthrough /entities/{task|project}/.../growth "
            "GET/PATCH (forward-only seed → sprout → sapling → "
            "bloom → fruit, or clear; per-entity ownership "
            "enforced). Growth state on task and project entities "
            "— not a personal growth record. No frontend caller "
            "exists."
        ),
        prerequisites=("signed_in",),
        prerequisite_note="Signed-in account; API-only — no UI.",
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
        evidence=(
            "followthrough /commitments GET/POST/PATCH mounted "
            "(API-only; no dedicated frontend). Creation is a "
            "direct user act through this API only — meeting "
            "filing is not implemented (the meeting-side filing "
            "hook is a no-op until FC5), so no conversation can "
            "create a commitment."
        ),
        prerequisites=("signed_in",),
        prerequisite_note=(
            "Signed-in account; the visitor chooses — naming one "
            "does not create it, and a conversation cannot file "
            "one."
        ),
        # FC4 companion (2026-11-07): the note rides the commitments
        # line when — and only when — the workflow is usable, so a
        # signed-out or gated rendering never carries it.
        prompt_note="Naming one does not create it.",
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
            "presence_ingest.redact (regex tokenisation) is "
            "applied at capture to stored intake text ('only "
            "redacted text is stored or sorted'). The module "
            "describes itself as a backstop, not a guarantee. "
            "Since the security correction (finding D-4, merged "
            "PR #388), imports are parsed in place from the "
            "request's temporary upload — no raw copy of the "
            "export is written or retained (the uploads location "
            "holds no files after an import), so redaction at "
            "capture covers everything an import persists; "
            "session deletion and Scope S erasure still remove "
            "legacy retained trees from pre-correction imports."
        ),
        prerequisite_note=(
            "Automatic at intake for stored text; a backstop, "
            "not a guarantee. No raw upload copy is retained — "
            "imports are parsed from the request's temporary "
            "file."
        ),
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
            "Re-audit 2026-10-25 (correcting the 96e416f audit): "
            "backend GET/POST /identity/scopes plus Settings → "
            "Identity grant/revoke UI, reachable via SettingsView, "
            "present since 96e416f. Enforcement correction "
            "(WI-4 finding D-6) is merged (security correction, "
            "PR #388, verified live on staging 2026-11-17): the "
            "license and scopes routes require a signed-in "
            "session resolved to the installation owner — 401 "
            "unauthenticated, 403 non-owner, before any store "
            "access — and grants/revokes are written under the "
            "owner's user_id, never the global empty identity. "
            "Historical global (user_id='') events are preserved "
            "only in the owner's fold, are reported distinctly "
            "as unverified-provenance legacy grants "
            "(legacy_scope_inventory), and confer nothing on any "
            "other account; the staging ledger holds 4 such "
            "grant events (2026-10-14; net fold delete:execute, "
            "export, rent:zone:*, train:self) and no per-user "
            "events. Workflow not playtest-verified."
        ),
        prerequisites=("signed_in",),
        prerequisite_note=(
            "Settings → Identity. Enforced: a signed-in session "
            "resolved to the installation owner is required "
            "(401 unauthenticated, 403 non-owner); grants and "
            "revokes are recorded under the owner's identity. "
            "Pre-correction global grants apply only to the "
            "owner's fold and are shown distinctly as unverified "
            "provenance."
        ),
    ),
    Capability(
        id="never_observed",
        name="Never observed",
        detail=(
            "a data-handling policy, not a configurable setting "
            "or toggle; structurally enforced only for "
            "training-signal decision context — not a general "
            "conversation guarantee"
        ),
        primary_seat="guardian",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "The training-signal decision context (personality/"
            "context.py) excludes internal states by construction "
            "— only six situational dimensions are admitted and "
            "any internal-state key is dropped in normalisation; "
            "the distillation prompt repeats the exclusion. No "
            "equivalent envelope or enforcement exists in "
            "conversation-context assembly: as a general "
            "data-handling guarantee this is a policy assertion, "
            "narrowed here to its demonstrated enforcement "
            "coverage (WI-4 D-7)."
        ),
        prerequisite_note=(
            "A data-handling policy, not a user-facing control. "
            "Demonstrated coverage: training-signal decision "
            "context only."
        ),
    ),
    # -- Ambassador / Crane — voice travel, rentals, zones, disclosures --
    Capability(
        id="voice_chat",
        name="Voice chat",
        detail=(
            "a text exchange in the seat's voice — no audio: "
            "there is no speech input or output"
        ),
        primary_seat="ambassador",
        implementation="available",
        verification="unverified",
        evidence=(
            "voice_router /voice/chat; VoiceConsole.tsx "
            "(re-skinned onto CouncilChat); CouncilChat fallback. "
            "Text in / text out end to end — no speech "
            "recognition or synthesis exists in the path. No "
            "playtest evidence recorded."
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
            "ingest /sessions/{id}/review; the ingest-review UI "
            "is presence-review/SignalReviewView.tsx "
            "(agent-intake/ReviewView does not call the ingest "
            "endpoints — it serves the personality-claims queue, "
            "entry review_insights_ui). Staging TEST-account run "
            "2026-10-23 produced 18 pending candidates; the "
            "approve path was not exercised in that run, so the "
            "workflow is not promoted to verified. Route "
            "enforcement (security correction D-1, merged "
            "PR #388): the review routes sit behind the ingest "
            "router's session-auth + installation-owner "
            "dependency — owner resolution precedes any access "
            "to the presence store (401 unauthenticated, 403 "
            "non-owner); the identity license and train:self "
            "gates remain as the operation-specific layer (see "
            "entry import_uploads)."
        ),
        prerequisites=("signed_in", "consent_acknowledged"),
        prerequisite_note=(
            "Review of import-derived candidates; verdicts are "
            "the user's explicit acts. Consent gates what is "
            "said about this queue in conversation; route-level "
            "enforcement is the installation-owner session, "
            "with license + train:self as the operation-specific "
            "layer."
        ),
    ),
    Capability(
        id="review_insights_ui",
        name="Review queue — personality claims",
        primary_seat="skeptic",
        implementation="available",
        verification="unverified",
        evidence=(
            "A dedicated personality-claims review UI exists in "
            "code: agent-intake/ReviewView.tsx + ClaimCard.tsx "
            "(claim cards with verbatim evidence; Confirm/"
            "Qualify/Reject/Unresolve/Explain actions), backed "
            "by the claims list and verdict endpoints in "
            "agent_routes (accept/correct/explain/reject/"
            "unresolve, compare-and-swap on pending). Workflow "
            "not playtest-verified."
        ),
        prerequisite_note=(
            "Signed-in account. Personality-claim review exists "
            "and is distinct from the intake-candidate queue "
            "(entry review_intake); verdicts are explicit user "
            "acts."
        ),
    ),
    Capability(
        id="anchored_evidence",
        name="Anchored evidence",
        primary_seat="skeptic",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "Anchored evidence is displayed in code in "
            "agent-intake/ClaimCard.tsx (verbatim evidence + "
            "turn reference) and living-tree/YouEchoPanel.tsx "
            "(anchor text). Narrative store evidence references "
            "(S0) exist and ride narrative proposals, but have "
            "no frontend display surface (no frontend calls GET "
            "/steward/review). The presence-review/ directory "
            "is the ingest-signal UI (entry review_intake), not "
            "an evidence display."
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
            "Personality claims have a full contest path in "
            "code: POST correct/explain on the claims API "
            "(compare-and-swap on pending; correction note "
            "required), with UI in agent-intake/ClaimCard.tsx "
            "('Qualify') and chat/WeaverRoundClaimCard.tsx. "
            "Narrative steward proposals have NO correction "
            "verdict — accept/reject/unresolve only — and their "
            "review route has no frontend caller. Intake "
            "candidates accept context corrections before a "
            "decision."
        ),
        prerequisite_note=(
            "Visitor correction is always allowed in "
            "conversation. Personality claims can be contested "
            "in the claims UI; narrative proposals cannot be "
            "corrected, only accepted, rejected, or left "
            "unresolved."
        ),
    ),
    Capability(
        id="recurrence",
        name="Recurrence patterns",
        primary_seat="skeptic",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "temporal.find_parallels backend exists and its "
            "corroboration counts are user-visible via the YOU "
            "profile (living-tree/YouEchoPanel.tsx); recurrence "
            "also surfaces as a claim type in the claims review "
            "UI (agent-intake/ClaimCard.tsx). No dedicated "
            "recurrence-patterns view exists."
        ),
        prerequisites=("signed_in",),
        prerequisite_note=(
            "Signed-in account; no dedicated recurrence view — "
            "patterns surface in the YOU profile and as "
            "reviewable claims."
        ),
    ),
    Capability(
        id="blend_view",
        name="Blend view",
        primary_seat="skeptic",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "council_mode (base/mirror/blend) + per-strand blend "
            "weights API in personality_routes. A mode-selector "
            "component exists in code (council/"
            "CouncilPersonalityModeSelector.tsx) but is mounted "
            "nowhere; strand-blend bars display in archetype "
            "panels. No dedicated blend-view UI is in use."
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
            "openrouter_oauth_router (initiate|exchange) plus "
            "direct credential entry (PUT /settings/llm/"
            "credentials/{provider}) mounted under /settings; "
            "direct key-entry UI exists in code (settings/"
            "sections/ModelConnectionsSection.tsx) for six "
            "providers, as does the full OAuth UI. OAuth is not "
            "live-tested (recorded in the OAuth module itself)."
        ),
        prerequisites=("signed_in",),
        prerequisite_note=(
            "Signed-in account; Settings → Model Connections: "
            "direct key entry or OpenRouter OAuth (OAuth not "
            "live-tested)."
        ),
    ),
    Capability(
        id="export_all",
        name="Identity & Presence Takeout",
        detail=(
            "identity takeout — identity and presence data only; "
            "not conversations, projects, or artifacts"
        ),
        primary_seat="maverick",
        implementation="limited-experimental",
        verification="unverified",
        evidence=(
            "POST /identity/takeout is mounted and executes "
            "(identity_routes → identity/service.build_takeout), "
            "returning a downloadable JSON bundle: license, "
            "scope ledger, approved training signals, import "
            "sessions, and counts. It does NOT include "
            "conversations, meetings, projects/vision-execution "
            "records, claims, provenance artifacts, or settings. "
            "The route requires a signed-in session resolved to "
            "the installation owner, enforced at the route and "
            "again in the service layer before any bundle is "
            "composed (security correction D-14, merged "
            "PR #388, verified live on staging 2026-11-17: "
            "unauthenticated requests receive 401). No consent "
            "scope is required — the export right is "
            "ownership-gated — and bundle contents are "
            "unchanged. No frontend surface exists."
        ),
        prerequisite_note=(
            "Backend route only; no UI. Requires the "
            "installation owner's signed-in session. Covers "
            "identity and presence data only — never describe it "
            "as exporting everything."
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
        line = f"{head} — {_status_text(cap, state)}"
        # FC4 companion: the prompt_note rides ONLY a usable line —
        # never a planned, gated, or limited-experimental one. The
        # "available" wording in _status_text is what a signed-in
        # visitor sees; the note corrects the reading that naming
        # creates the thing.
        if cap.prompt_note and currently_usable(cap, state):
            line += f". {cap.prompt_note}"
        lines.append(line)
    return lines


#: Lead-in for the first-meeting block (Level 1, founder review
#: item 1, 2026-11-10): a short structural lead-in, not doctrine.
#: It heads the seat-specific capability bullets inside the frame
#: after the scope line moved to the canonical tier. The canonical
#: scope doctrine stays in the tier; the lead-in carries no doctrine
#: of its own.
_CAPABILITY_LEADIN = "From your scope:"


def first_meeting_block(seat: str | None, state: VisitorState) -> str:
    """The first-meeting frame's capability context: the adopted
    lead-in plus the seat's own capability bullets only. The shared
    lines that used to ride this block — the scope line, the ONE
    shared intention line, and the standing honesty guard — now ride
    the canonical tier (``local_ai/conversation/canonical_tier.py``),
    carried once as an uncapped section immediately before the frame
    on the meeting path. Empty for unknown seats (no slice, no
    lead-in). Continuations never receive this block."""
    lines = _render_lines(seat, state)
    if not lines:
        return ""
    return "\n".join([_CAPABILITY_LEADIN, *lines])


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
