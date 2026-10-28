"""Build-room meeting runner, R1: single-model meeting.

One work item in, persisted verbatim transcript out, plus a draft
artifact (see artifact.py). The transcript is append-only: convene,
contribution, pass, failure, and absence entries are all recorded
verbatim with attribution. Nothing is paraphrase-laundered.

Budget enforcement (spec §5): one contribution max for R1, a per-call
timeout, and a prompt-size cap. Breach means a recorded failure entry
and no generation — never a silent overrun.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from local_ai.build_room.artifact import build_draft_artifact
from local_ai.build_room.measurement import (
    compute_generation_cost,
    measure_generation,
)
from local_ai.build_room.participants import (
    OpenAIParticipant,
    resolve_openai_participant,
)
from local_ai.llm.execution_principal import ExecutionPrincipal


@dataclass(frozen=True)
class EvidencePacket:
    """Shared, immutable meeting evidence (spec §4 convene).

    Frozen on purpose: later evidence is appended as new transcript
    entries, never by mutating this packet.
    """

    work_item: str
    question: str
    excerpts: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    context: tuple[str, ...] = ()

    def render_prompt(self) -> str:
        parts = [f"Work item:\n{self.work_item}", f"Question:\n{self.question}"]
        if self.excerpts:
            parts.append("Excerpts:\n" + "\n---\n".join(self.excerpts))
        if self.constraints:
            parts.append("Constraints:\n" + "\n".join(f"- {c}" for c in self.constraints))
        if self.source_refs:
            parts.append("Source references:\n" + "\n".join(f"- {r}" for r in self.source_refs))
        if self.context:
            parts.append("Architectural context:\n" + "\n---\n".join(self.context))
        parts.append(
            "Respond as a single deliberation contribution, keeping these "
            "distinct:\n"
            "- Observed: only statements directly supported by the supplied "
            "evidence above.\n"
            "- Inferred: conclusions reached by reasoning from identified "
            "evidence above.\n"
            "- Proposed: a suggested intervention.\n"
            "- Speculative: an exploratory possibility.\n"
            "- Contested: an unresolved objection, not merely uncertainty.\n"
            "If no observations are warranted, omit the Observed category "
            "rather than filling it."
        )
        return "\n\n".join(parts)


# Cap-replacement gates (folded design 2026-10-28, implemented
# 2026-10-28). R2 admission operates on counted tokens, declared
# windows, a conservative cost estimate, and an authorized meeting
# budget — never on character counts. The legacy char-cap fields
# below stay on Budget for the untouched R1 path only.
#
# Declared context windows, with sources. Gemini declared
# 2026-10-28 from Google Cloud docs (model page + developer guide
# agree; max output 65,536). Other windows per the cap report.
CAP_MODEL_WINDOWS: dict[str, int] = {
    "gpt-4o-mini": 128_000,
    "claude-haiku-4-5": 200_000,
    "gemini-3.8-flash": 1_048_576,
    "grok-4-1-fast-reasoning": 2_000_000,
    "muse-spark-1.3": 1_000_000,
}
CAP_MODEL_WINDOW_SOURCES: dict[str, str] = {
    "gpt-4o-mini": "OpenAI model docs (128K context)",
    "claude-haiku-4-5": "Anthropic model docs (200K context)",
    "gemini-3.8-flash": "Google Cloud docs, model page + developer guide (2026-10-28)",
    "grok-4-1-fast-reasoning": "xAI model docs (2M context)",
    "muse-spark-1.3": "Meta model docs (1M context)",
}
# Pricing per 1M tokens, standard (non-batch, non-cached) rates:
# (input, output). Source + date recorded; expiry enforced (see
# evaluate_admission): past expiry, admission fails closed until
# the table is refreshed. 2027-01-01 is when Gemini's standard
# pricing ($1.50/$7.50) replaces its introductory pricing.
CAP_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "claude-haiku-4-5": (1.00, 5.00),
    "gemini-3.8-flash": (0.75, 3.75),
    "grok-4-1-fast-reasoning": (0.20, 0.50),
    "muse-spark-1.3": (1.25, 4.25),
}
CAP_PRICING_SOURCE = "cap report 2026-10-28 (public per-1M pricing pages)"
CAP_PRICING_DATE = "2026-10-28"
CAP_PRICING_DEFAULT_EXPIRY = "2027-01-01"
# Output reservation R, PROVISIONAL (B2's figure). R is a COST
# RESERVATION plus a budget hard stop, NOT a provider-enforced
# limit: no provider client enforces 4,000 (Anthropic/xAI hardcode
# 4096, the rest set nothing client-side; only OpenAI surfaces
# usage; no client surfaces a finish/stop reason). Never claim
# otherwise; see the implementation evidence file.
CAP_OUTPUT_RESERVATION_TOKENS = 4000
# Fleet-wide safety ceiling (smallest confirmed window): a REPORTED
# secondary check only. The declared window governs admission; the
# ceiling is checked and reported, never refusing on its own.
# (Fork, flagged for Joshua: GPT's correction left binding vs
# reported unsettled; reported is adopted because a binding ceiling
# would reintroduce an arbitrary cap and make the Gemini
# declaration pointless. Joshua may overrule to binding.)
CAP_FLEET_CEILING_TOKENS = 128_000
# Non-native tokenizer margin, PROVISIONAL starting assumption, not
# a verified upper bound. o200k_base is exact for gpt-4o-mini only;
# every other seat counts under it with this margin, and the
# fallback estimate is never represented as an exact provider count.
CAP_NON_NATIVE_TOKEN_MARGIN_NUM = 1  # margin = ceil(counted / 5) = ceil(20%)
CAP_NATIVE_TOKENIZER_MODEL = "gpt-4o-mini"
CAP_DEFAULT_MAX_COST_USD = 0.50


@dataclass(frozen=True)
class Budget:
    max_contributions: int = 1
    timeout_seconds: int = 120
    # Legacy char caps: R1-only (run_single_model_meeting) and
    # deprecated for R2. R2 admission NEVER consults them; the
    # gates below are the only R2 admission authority.
    max_prompt_chars: int = 20000
    max_response_prompt_chars: int = 40000
    # Cap-replacement gates (R2 only). max_cost_usd None means
    # explicitly NO authorized budget -> every generation refused
    # before any provider call. The $0.50 default IS the
    # authorization; a plain Budget() never triggers the
    # missing-budget refusal.
    max_cost_usd: float | None = CAP_DEFAULT_MAX_COST_USD
    output_reservation_tokens: int = CAP_OUTPUT_RESERVATION_TOKENS
    pricing_expiry: str = CAP_PRICING_DEFAULT_EXPIRY


@dataclass
class GateDecision:
    """One generation's admission verdict under the cap gates.

    ``code`` is "" when admitted, else one structured gate code:
    capacity | reservation | budget | configuration | tokenizer.
    The generic outer label in recorded refusals stays
    "budget_exceeded" (existing accounting); the code is what
    distinguishes a capacity restriction from a missing
    configuration from a monetary limit.
    """

    admitted: bool
    code: str
    reason: str
    prompt_chars: int
    prompt_tokens: int | None  # counted, before margin; None when counting failed
    margin_tokens: int
    counted_tokens: int  # prompt_tokens + margin (0 when counting failed)
    reservation_tokens: int
    window: int | None
    estimated_cost_usd: float | None
    fleet_ceiling_exceeded: bool


def _today_iso() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def evaluate_admission(
    *,
    model: str,
    prompt: str,
    budget: Budget,
    remaining_budget: float,
) -> GateDecision:
    """Evaluate gates §1–§4 for one generation, pre-generation.

    Pure (no I/O beyond the local tokenizer): safe to unit-test
    with mocks/fixtures, no provider call. Order: budget presence
    -> declared window/pricing -> pricing expiry -> counter ->
    capacity -> estimate vs remaining budget. The fleet ceiling is
    computed and REPORTED, never refusing on its own.
    """
    prompt_chars = len(prompt)
    reservation = budget.output_reservation_tokens
    base = dict(
        prompt_chars=prompt_chars,
        prompt_tokens=None,
        margin_tokens=0,
        counted_tokens=0,
        reservation_tokens=reservation,
        window=None,
        estimated_cost_usd=None,
        fleet_ceiling_exceeded=False,
    )
    # 1. Budget presence: explicit None = no authorized budget.
    if budget.max_cost_usd is None:
        return GateDecision(
            False, "budget",
            "no authorized budget: max_cost_usd is None (explicit opt-out); "
            "no generation attempted",
            **base,
        )
    # 2. Declared window + pricing for this model.
    window = CAP_MODEL_WINDOWS.get(model)
    pricing = CAP_PRICING.get(model)
    if window is None or pricing is None:
        return GateDecision(
            False, "configuration",
            f"no declared window/pricing for model {model!r}; "
            "no generation attempted",
            **base,
        )
    base["window"] = window
    # 3. Pricing expiry: stale/unverifiable pricing never silently
    # authorizes spending.
    if budget.pricing_expiry < _today_iso():
        return GateDecision(
            False, "configuration",
            f"pricing table expired {budget.pricing_expiry} "
            f"(source {CAP_PRICING_SOURCE}, dated {CAP_PRICING_DATE}); "
            "refresh required; no generation attempted",
            **base,
        )
    # 4. Counter: o200k_base exact for the GPT model; every other
    # seat counts under it with a provisional +20% margin (ceiling,
    # so the margin never under-counts).
    counted = count_tokens_exact(prompt)
    if counted is None:
        return GateDecision(
            False, "tokenizer",
            "no usable token counter (tiktoken unavailable); "
            "no generation attempted",
            **base,
        )
    if model == CAP_NATIVE_TOKENIZER_MODEL:
        margin = 0
    else:
        margin = -(-counted // 5)  # ceil(counted * 20%)
    total = counted + margin
    base.update(prompt_tokens=counted, margin_tokens=margin, counted_tokens=total)
    # 5. Capacity: counted (+ margin) + reservation <= window.
    if total + reservation > window:
        return GateDecision(
            False, "capacity",
            f"prompt {total} tokens + {reservation} reservation exceeds "
            f"window {window} for {model}; no generation attempted "
            "(never truncated)",
            **base,
        )
    # 6. Fleet ceiling: reported only, never refusing alone.
    base["fleet_ceiling_exceeded"] = (total + reservation > CAP_FLEET_CEILING_TOKENS)
    # 7. Estimate vs remaining budget (conservative: full
    # reservation charged at standard rates).
    in_price, out_price = pricing
    estimate = (total * in_price + reservation * out_price) / 1_000_000
    base["estimated_cost_usd"] = estimate
    if estimate > remaining_budget:
        if remaining_budget <= 0:
            reason = (
                f"meeting budget exhausted (remaining ${remaining_budget:.4f}); "
                "no generation attempted"
            )
        else:
            reason = (
                f"estimate ${estimate:.4f} exceeds remaining budget "
                f"${remaining_budget:.4f}; no generation attempted"
            )
        return GateDecision(False, "budget", reason, **base)
    return GateDecision(True, "", "admitted", **base)


class CapBudgetLedger:
    """Per-meeting dollar ledger for the cap gates (§4).

    ceiling: authorized max_cost_usd (None = no budget; available
    is then 0). settled: provider-reported usage reconciled to
    dollars. outstanding: active reservations. retained_unverified:
    calls that occurred without usage (estimated expenditure, never
    $0). retained_uncertain: call status uncertain (e.g. timeout
    after dispatch). available = ceiling - settled - outstanding -
    retained_unverified - retained_uncertain. A reservation that
    settles to reported usage frees (reserved - actual) when actual
    is smaller; an overrun (actual > reserved) is recorded and
    reduces available accordingly.
    """

    def __init__(self, ceiling: float | None):
        self.ceiling = ceiling
        self.settled_usd = 0.0
        self.reservations: dict[tuple[str, str], float] = {}
        self.retained_unverified_usd = 0.0
        self.retained_uncertain_usd = 0.0
        self.overruns: list[dict[str, Any]] = []

    @property
    def outstanding_usd(self) -> float:
        return sum(self.reservations.values())

    @property
    def available_usd(self) -> float:
        if self.ceiling is None:
            return 0.0
        return (
            self.ceiling
            - self.settled_usd
            - self.outstanding_usd
            - self.retained_unverified_usd
            - self.retained_uncertain_usd
        )

    @property
    def estimated_expenditure_usd(self) -> float:
        """Money spent or assumed spent, excluding outstanding."""
        return (
            self.settled_usd
            + self.retained_unverified_usd
            + self.retained_uncertain_usd
        )

    def reserve(self, key: tuple[str, str], amount: float) -> None:
        self.reservations[key] = amount

    def settle_reported(self, key: tuple[str, str], actual_usd: float) -> float:
        """Reconcile a reservation to reported usage. Returns the
        overrun (actual - reserved) when positive, else 0."""
        reserved = self.reservations.pop(key, 0.0)
        self.settled_usd += actual_usd
        overrun = actual_usd - reserved
        if overrun > 0:
            self.overruns.append(
                {"phase": key[0], "participant": key[1],
                 "reserved_usd": reserved, "actual_usd": actual_usd,
                 "overrun_usd": overrun}
            )
        return max(0.0, overrun)

    def settle_unverified(self, key: tuple[str, str]) -> float:
        """Call occurred, usage unavailable: retain the reservation
        as estimated expenditure, marked unverified. Returns the
        retained amount."""
        reserved = self.reservations.pop(key, 0.0)
        self.retained_unverified_usd += reserved
        return reserved

    def settle_uncertain(self, key: tuple[str, str]) -> float:
        """Call status uncertain: retain the reservation and report
        the uncertainty. Returns the retained amount."""
        reserved = self.reservations.pop(key, 0.0)
        self.retained_uncertain_usd += reserved
        return reserved

    def release(self, key: tuple[str, str]) -> float:
        """Confirmed no provider call: free the reservation."""
        return self.reservations.pop(key, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ceiling_usd": self.ceiling,
            "settled_verified_usd": round(self.settled_usd, 6),
            "outstanding_reserved_usd": round(self.outstanding_usd, 6),
            "retained_unverified_usd": round(self.retained_unverified_usd, 6),
            "retained_uncertain_usd": round(self.retained_uncertain_usd, 6),
            "available_usd": round(self.available_usd, 6),
            "estimated_expenditure_usd": round(self.estimated_expenditure_usd, 6),
            "overruns": list(self.overruns),
        }


@dataclass
class TranscriptEntry:
    kind: str  # convene | contribution | failure | absence | note | claims
    participant: str
    text: str
    ts: float = field(default_factory=time.time)


@dataclass
class Transcript:
    entries: list[TranscriptEntry] = field(default_factory=list)

    def append(self, kind: str, participant: str, text: str) -> TranscriptEntry:
        entry = TranscriptEntry(kind=kind, participant=participant, text=text)
        self.entries.append(entry)
        return entry

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [asdict(e) for e in self.entries]}


@dataclass
class MeetingResult:
    meeting_id: str
    transcript: Transcript
    artifact: dict[str, Any]
    ok: bool
    transcript_path: Path
    artifact_path: Path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _log_usage(store_dir: Path, **fields: Any) -> None:
    line = json.dumps({"ts": time.time(), **fields}, sort_keys=True)
    with (store_dir / "usage.jsonl").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_single_model_meeting(
    packet: EvidencePacket,
    *,
    store_dir: Path | str,
    budget: Budget | None = None,
    principal: ExecutionPrincipal | None = None,
    participant: OpenAIParticipant | None = None,
) -> MeetingResult:
    """Run one R1 meeting. Never raises for participant/generation failure:
    failures are recorded in the transcript and reflected in ``ok``."""
    budget = budget or Budget()
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    meeting_id = uuid.uuid4().hex[:12]
    transcript = Transcript()
    transcript.append("convene", "Reynard (convener)",
                      f"Work item: {packet.work_item}\nQuestion: {packet.question}")

    if participant is None:
        participant, absence_note = resolve_openai_participant(principal)
        if participant is None:
            transcript.append("absence", "GPT", absence_note)
            artifact = build_draft_artifact(meeting_id, packet, transcript, None)
            t_path = store / f"meeting_{meeting_id}.transcript.json"
            a_path = store / f"meeting_{meeting_id}.draft_artifact.json"
            _write_json(t_path, {"meeting_id": meeting_id, **transcript.to_dict()})
            _write_json(a_path, artifact)
            _log_usage(store, meeting_id=meeting_id, participant="GPT",
                       provider="openai", key_source="none",
                       operation="build_room_r1_meeting", outcome="absent")
            return MeetingResult(meeting_id, transcript, artifact, False, t_path, a_path)

    prompt = packet.render_prompt()
    contribution: str | None = None
    failure: str | None = None
    if budget.max_contributions < 1:
        failure = "budget_exceeded: max_contributions is 0; no generation attempted"
    elif len(prompt) > budget.max_prompt_chars:
        failure = (
            f"budget_exceeded: prompt of {len(prompt)} chars exceeds "
            f"max_prompt_chars={budget.max_prompt_chars}; no generation attempted"
        )
    else:
        try:
            contribution = participant.generate(prompt, timeout=budget.timeout_seconds)
        except Exception as exc:  # recorded, not raised
            failure = f"{type(exc).__name__}: {str(exc)[:200]}"

    if failure is not None:
        transcript.append("failure", "GPT", failure)
        outcome = "failed"
    else:
        transcript.append("contribution", "GPT", contribution or "")
        outcome = "generated"

    artifact = build_draft_artifact(meeting_id, packet, transcript, participant,
                                    contribution=contribution, failure=failure)
    t_path = store / f"meeting_{meeting_id}.transcript.json"
    a_path = store / f"meeting_{meeting_id}.draft_artifact.json"
    _write_json(t_path, {"meeting_id": meeting_id, **transcript.to_dict()})
    _write_json(a_path, artifact)
    _log_usage(store, meeting_id=meeting_id, participant="GPT",
               provider="openai", key_source=participant.key_source,
               operation="build_room_r1_meeting", outcome=outcome)
    return MeetingResult(meeting_id, transcript, artifact, failure is None, t_path, a_path)


# ---------------------------------------------------------------------------
# R2: multi-participant deliberation (approved design, 2026-10-26).
#
# Shape: convene -> independent openings (baseline) -> one response
# round -> optional revision. The transcript stays append-only and
# verbatim; failures are recorded, never raised. No synthesis phase
# (removed by design 2026-10-27, Joshua: drop synthesis entirely):
# the registry + transcript are the meeting output.
#
# Load-bearing distinctions (approved design §2 + review amendments):
# - The claim registry is MECHANICALLY derived from numbered claims
#   in contributions. No LLM extraction, ever.
# - Position grouping and disagreement identification are ATTRIBUTED,
#   model-authored annotations with direct claim references — never
#   objective facts, never inferred by the runner. The runner groups
#   nothing itself.
# - "Addressable" is a mechanical check (existing claim cited AND a
#   move word stated). It is NOT a genuineness score: whether the
#   reasoning is good is Joshua's judgment from the transcript.
# - The collapse rule is enforced by preservation, not by runner
#   judgment: positions and disagreements survive in the registry +
#   transcript, so invented agreement is visible.
# ---------------------------------------------------------------------------

from local_ai.build_room.artifact import build_draft_artifact_r2
from local_ai.build_room.citation_validation import validate_tool_citations
from local_ai.build_room.claim_standing import compute_claim_standing
from local_ai.build_room.measurement import summarize_tool_round_usage
from local_ai.build_room.record_completeness import check_record_completeness
from local_ai.build_room.tool_access import (
    ToolLoopContext,
    normalize_snapshot_path,
    run_tool_loop,
    tools_prompt_section,
)
from local_ai.build_room.tool_snapshot import (
    ManifestError,
    default_snapshot_dir,
    load_manifest,
    snapshot_status,
)
from local_ai.build_room.participants import (
    Seat,
    resolve_seat_participants,
)

# Default R2 budget: 5 openings + up to 5 responses + up to 5
# revisions = max 15 generations. No synthesis phase (removed by
# design 2026-10-27, Joshua: drop synthesis entirely).
R2_MAX_GENERATIONS = 15

_NUMBERED_CLAIM_RE = re.compile(r"^\s*(?:\*\*)?(\d+)[.)](?:\*\*)?\s+(.*\S)\s*$")
# C1: a model-written "C60." line is a claim boundary too, but the
# number is NEVER an identifier — the system assigns the next ID and
# the model-written number is recorded as disregarded.
_MODEL_NUMBER_RE = re.compile(r"^\s*C(\d+)[.)]\s+(.*\S)\s*$")
_CITATION_RE = re.compile(r"\b(C\d+)\b")
_STATUS_PREFIX_RE = re.compile(
    r"^(Observed|Inferred|Proposed|Speculative|Contested)\s*:\s*",
    re.IGNORECASE,
)
# C2: the status formats the R2 participants actually used.
_STATUS_BOLD_PREFIX_RE = re.compile(
    r"^\*\*\s*(Observed|Inferred|Proposed|Speculative|Contested)\s*:\s*\*\*",
    re.IGNORECASE,
)
# Same bold prefix with the colon outside the bold markers
# ("**Observed**:") — the status word is bolded either way.
_STATUS_BOLD_COLON_OUT_RE = re.compile(
    r"^\*\*\s*(Observed|Inferred|Proposed|Speculative|Contested)\s*\*\*\s*:\s*",
    re.IGNORECASE,
)
# Same bracket prefix wrapped in bold ("**[Inferred]**").
_STATUS_BOLD_BRACKET_RE = re.compile(
    r"^\*\*\s*\[\s*(Observed|Inferred|Proposed|Speculative|Contested)\s*\]\s*\*\*",
    re.IGNORECASE,
)
_STATUS_BRACKET_RE = re.compile(
    r"^\[\s*(Observed|Inferred|Proposed|Speculative|Contested)\s*\]",
    re.IGNORECASE,
)
# Legibility correction, Scope A: parenthetical status prefix
# ("(Observed)", "(Inferred)", …) — the weakest explicit format,
# checked after bare/bold/bracket and before section-header
# inheritance. The status word is the first token inside the
# parentheses; extended forms ("(Contested — Objection to C21)")
# parse the status word only — the remainder is targeting
# information for the C5 explicit-targeting rule, not status content.
# Only a span-start parenthetical counts; mid-sentence parentheses
# are prose and never set a status.
_STATUS_PAREN_RE = re.compile(
    r"^\(\s*(Observed|Inferred|Proposed|Speculative|Contested)\b",
    re.IGNORECASE,
)
# A whole-line section heading ("## Observed", "**Observed**",
# "Observed:"). Headings end the previous claim's span and set the
# inherited status for following claims without their own prefix.
_SECTION_HEADER_RE = re.compile(
    r"^(?:#{1,6}\s*|\*\*)?\s*(Observed|Inferred|Proposed|Speculative|Contested)"
    r"\s*(?::\s*)?(?:\*\*)?\s*$",
    re.IGNORECASE,
)
_RELATIONSHIP_RE = re.compile(
    r"\b(revised|defended|withdrawn|retract\w*)\b", re.IGNORECASE)
# Mandate reliability (2026-10-28): retract-family words are withdrawal
# language. A bare stance word is normalized by _normalize_stance_word;
# retract* always maps to "withdrawn".
# C5 explicit targeting: a move is VERIFIED as targeted only when the
# text syntactically associates it with its claim id. Same-span
# proximity without one of these patterns is a candidate, never a
# verified objection/correction/evidence request.
_TARGET_PATTERNS: tuple[tuple[str, str], ...] = (
    ("objection", r"\b(?:objection|object)\s+(?:to|regarding|against|on)\s+(C\d+)"),
    ("evidence_request",
     r"\b(?:evidence request|request for evidence|requesting evidence|request evidence)"
     r"\s+(?:regarding|for|on|about)\s+(C\d+)"),
    ("correction", r"\b(?:correction|correct)\s+(?:of|to)\s+(C\d+)"),
    ("agreement", r"\b(?:agreement|agree)\s+(?:with|to)\s+(C\d+)"),
    ("extension", r"\b(?:extension|extend)\s+(?:of|to)\s+(C\d+)"),
)
_TARGET_RES = tuple((name, re.compile(p, re.IGNORECASE)) for name, p in _TARGET_PATTERNS)
_IN_RESPONSE_TO_RE = re.compile(
    r"\bin response to\s+((?:C\d+\s*(?:,|and)?\s*)+)", re.IGNORECASE)
_MOVE_DECL_RE = re.compile(r"\bMove:\s*([A-Za-z,\s]+)", re.IGNORECASE)
# C4 relationship targeting, in precedence order: bracket annotation,
# "revised C18", "C59 is withdrawn", "defend C12", then fallbacks.
_REL_BRACKET_RE = re.compile(
    r"\b(C\d+)\s*\[\s*(revised|defended|withdrawn)\b", re.IGNORECASE)
_REL_VERB_TARGET_RE = re.compile(
    r"\b(revised|revise|revising|defended|defend|defending|withdrawn|withdraw|withdraws|withdrawing|retracted|retract|retracts|retracting)"
    r"\s+(?:my\s+)?(C\d+)",
    re.IGNORECASE)
_REL_IS_WITHDRAWN_RE = re.compile(r"\b(C\d+)\s+is\s+withdrawn\b", re.IGNORECASE)
# Mandate reliability: sentence-scoped stance rescue. The tight patterns
# above miss the forms models actually emit in the historical record:
# parenthetical markers ("(Withdrawn) ..."), colon lists ("Withdrawn:
# C27, C28, C29, C30–C44"), object phrasing ("citations in C6–C9"),
# and anaphoric range retractions ("C27–C44 ... they are retracted").
# These patterns run ONLY when the tight patterns yield no target, so
# previously working parses are unchanged. A negated stance ("do not
# withdraw C6") never yields targets; bare "no" is excluded from the
# negation set, as in claim_standing's signal detector (too broad).
_STANCE_WORD_RE = re.compile(
    r"\b(revised|revise|revising|defended|defend|defending|withdrawn|withdraw|withdraws|withdrawing|retracted|retract|retracts|retracting)\b",
    re.IGNORECASE)
_STANCE_NEGATION_RE = re.compile(
    r"\b(not|never|don't|doesn't|didn't|do not|does not|did not|cannot)\b",
    re.IGNORECASE)
_STANCE_NEGATION_WINDOW = 40
_MOVE_RANGE_CAP = 50
_LIST_ITEM_RE = re.compile(r"C(\d+)\s*(?:[-–—]\s*C(\d+))?")
_OBJECT_TARGETS_RE = re.compile(
    r"\b(citations|claims|statements|values|figures|numbers|read statements|sources|references)\b"
    r"(?:\s+\w+){0,3}?\s+(?:in|of)\s+"
    r"((?:C\d+\s*(?:[-–—]\s*C\d+)?)(?:\s*(?:,|and)\s*C\d+\s*(?:[-–—]\s*C\d+)?)*)",
    re.IGNORECASE)

# P3 nouns that name EVIDENCE, not claim content: a stance over
# these withdraws/revises the citations, never the claims they point
# to (A7: withdrawing "the citations in C6–C9" leaves C6–C9 active).
_CITATION_NOUNS = frozenset(
    {"citations", "sources", "references", "read statements"})
_ANAPHOR_RE = re.compile(
    r"\b(they|these|those)\s+(?:are|were)\s+(?:\w+\s+){0,2}?",
    re.IGNORECASE)
# Reclassification: a revised-family span that retracts its framing
# and reassigns an epistemic status ("are Inferred, not Observed").
# Markdown bold around the status words is tolerated.
_STATUS_PAIR_RE = re.compile(
    r"\b(?:are|were)\s+(?:\*\*)?(Observed|Inferred|Proposed|Speculative|Contested)(?:\*\*)?\b"
    r"[^.!?\n]{0,80}?\bnot\s+(?:\*\*)?(Observed|Inferred|Proposed|Speculative|Contested)(?:\*\*)?\b",
    re.IGNORECASE)
_FRAMING_CUE_RE = re.compile(
    r"\b(retract\w*|framing|presented as)\b", re.IGNORECASE)

# The five response moves (design §2B). Patterns match the move WORDS
# as stated by the participant; stating a word is not proof of
# substance — see "addressable" above.
_MOVE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("agreement", r"\b(agree|agrees|agreed|agreeing|agreement)\b"),
    ("correction", r"\b(correct|corrects|corrected|correcting|correction)\b"),
    ("objection", r"\b(object|objects|objected|objecting|objection)\b"),
    ("extension", r"\b(extend|extends|extended|extending|extension)\b"),
    ("evidence_request",
     r"\b(request for evidence|evidence request|requesting evidence|request evidence)\b"),
)
_MOVE_RES = tuple((name, re.compile(p, re.IGNORECASE)) for name, p in _MOVE_PATTERNS)
_OBJECTION_MOVES = ("objection", "evidence_request")

_CLAIM_NUMBERING_INSTRUCTION = (
    "Number each substantive claim in your contribution (\"1. ...\", "
    "\"2. ...\"), each with its epistemic status (Observed, Inferred, "
    "Proposed, Speculative, Contested). Numbering is a formatting "
    "instruction only; it says nothing about what to conclude. "
    "Claim IDs are assigned by the system; do not invent, renumber, or "
    "reuse C-numbers; cite existing IDs to reference, and number new "
    "claims with plain digits only."
)

# C10: contribution discipline — a soft target, not a hard cap.
_CONTRIBUTION_DISCIPLINE = (
    "Contribution discipline: target 3–6 substantive claims per "
    "contribution. You may exceed the target when additional claims "
    "introduce genuinely distinct reasoning; there is no hard cap and "
    "no rejection for exceeding it. Identify the most consequential "
    "issues; explain why those issues matter; avoid restating "
    "established architectural constraints unless challenging their "
    "interpretation; prefer developing an existing argument over "
    "generating another redundant claim."
)

_LANGUAGE_LINE = (
    "Language: seat-to-seat shorthand in another language is permitted "
    "only if it remains transliterable into English; anything bearing "
    "on Joshua's decisions must be understandable in English, and the "
    "synthesis and artifact conclusions for his review are in English."
)

_RESPONSE_INSTRUCTION = (
    "Respond to the claim registry below, not to the packet in general. "
    "Cite the claim IDs you engage (e.g. 'In response to C4...') and "
    "state your move on each cited claim's reasoning: agreement, "
    "correction, objection, extension, or request for evidence. "
    "Merely naming another participant does not count as a response. "
    "Do not collapse disagreements into consensus."
)

_FOLLOWUP_INSTRUCTION = (
    "One of your claims drew an objection or evidence request. Make ONE "
    "follow-up: state the relationship explicitly — revised (you change "
    "or qualify the claim), defended (you maintain it with additional "
    "reasoning), or withdrawn (you retract it) — and cite your own claim "
    "ID and the objection's claim ID. Number any new substantive claims "
    "as before. A defense links to the original claim without replacing "
    "it; a revision may supersede it. "
    # Registry standing stage 3 (design v2): the input contract for
    # standing moves — what the model is ASKED to emit. Acceptance
    # rules are unchanged (stage 1): only a structured same-author
    # link to one earlier claim moves standing.
    "Standing moves — how a revision changes a claim's standing: "
    "one numbered span per move, naming exactly one earlier claim ID "
    "of your own (a range such as C6–C9 is not a move and moves "
    "nothing; a stance word with no claim ID is not a move). You can "
    "only move your own claims — a link to another participant's "
    "claim stays a proposal and never changes that claim's standing. "
    "A defense is not a move: defending a claim never reactivates it "
    "and never changes its standing. To move four claims, write four "
    "spans."
)

@dataclass
class Claim:
    """One mechanically registered claim (design §2A, correction C1–C4).

    ``text`` is verbatim (preamble lines excluded — see
    :func:`_parse_claim_spans`). ``status`` is the epistemic label when
    the participant wrote one in a recognized format, inherited from a
    section heading, else ``"unknown"`` — never blank. ``relationship``
    / ``relates_to`` / ``supersedes`` / ``withdraws`` /
    ``relationship_target`` describe a follow-up's link to earlier
    claims; they are None / empty for openings and responses.
    ``disposition`` / ``disposition_by`` live on ORIGINAL claims and
    change only on their own author's revision (C4): ``revised`` /
    ``withdrawn`` / ``maintained`` plus the revision claim id that set
    it. ``epistemic_assessment`` is independent of disposition (C4):
    ``challenged`` when a verified objection/evidence request targets
    the claim, ``supported`` when a verified agreement does and nothing
    challenges it, else ``unresolved``; ``contradicted`` is never set
    mechanically — a participant asserting a contradiction does not
    establish one, and an independently verified contradiction is a
    review judgment. ``assessment_sources`` preserves the source claim
    ids behind every assessment, so no assessment is false authority.
    """

    id: str
    participant: str
    phase: str
    text: str
    status: str = "unknown"
    relationship: str | None = None
    relates_to: list[str] = field(default_factory=list)
    supersedes: str | None = None
    withdraws: str | None = None
    relationship_target: str | None = None
    # Mandate reliability: multi-target moves (range/list withdrawals)
    # carry every target here; relationship_target keeps the first for
    # backward compatibility. Consumers use this list when non-empty,
    # else the single fields — never both (no double application).
    # reclassified_status records a same-author epistemic
    # reclassification (e.g. Observed → Inferred) on a revision span;
    # it is a derived-field input, not a new standing dimension.
    relationship_targets: list[str] = field(default_factory=list)
    reclassified_status: str | None = None
    disposition: str | None = None
    disposition_by: str | None = None
    epistemic_assessment: str = "unresolved"
    assessment_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClaimSpan:
    """One parsed claim span.

    ``text`` is the claim's own lines joined (verbatim, preamble
    excluded). ``preamble`` holds the non-numbered lines that preceded
    this span's numbered line since the previous span or section
    header — e.g. "Relationship: defended." — kept separate so
    relationship/target analysis can use it without it becoming part
    of the claim text. ``used_model_number`` is True when the span
    started with a model-written ``C\d+.`` boundary (C1).
    """

    text: str
    status: str
    preamble: str = ""
    used_model_number: bool = False
    model_number: str | None = None


def _parse_claim_spans(text: str) -> list[ClaimSpan]:
    """Split a contribution into claim spans (C1, C2, C3, legibility A).

    A numbered line (``1.``, ``2.`` — including bold-wrapped forms
    ``**1.**``, ``**1. Inferred:**``, ``**1. (Inferred)**``) or a
    model-written ``C60.`` line starts a span; following non-blank
    lines extend it until the next numbered line or section heading.
    A section heading ends the previous span and sets the inherited
    status. Non-numbered lines before the first span (or after a
    heading, before the next span) become that span's preamble.
    A numbered line strictly MORE indented than the current span's
    start line is a nested example inside that span's supporting
    paragraphs, not a new claim boundary — it joins the current span.
    A numbered line at the same or lesser indent starts a new span.
    Flush-left numbered lines inside a claim remain ambiguous and
    still split (no mechanical rule separates them from new claims);
    that residual ambiguity is documented, not silently resolved.
    Nothing here judges content.
    """
    spans: list[ClaimSpan] = []
    current: list[str] | None = None
    current_model_number = False
    current_model_number_value: str | None = None
    current_indent: int | None = None
    preamble: list[str] = []
    span_preamble = ""
    inherited = ""

    def flush() -> None:
        nonlocal current, current_model_number, current_model_number_value
        nonlocal current_indent
        if current is not None:
            spans.append(ClaimSpan(
                text=" ".join(current),
                status=_claim_status(current[0], inherited),
                preamble=span_preamble,
                used_model_number=current_model_number,
                model_number=current_model_number_value,
            ))
            current = None
            current_model_number = False
            current_model_number_value = None
            current_indent = None

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        header = _SECTION_HEADER_RE.match(line)
        if header:
            flush()
            inherited = header.group(1).capitalize()
            preamble = []
            continue
        m = _NUMBERED_CLAIM_RE.match(line)
        model_m = None if m else _MODEL_NUMBER_RE.match(line)
        if (m or model_m) and current is not None \
                and current_indent is not None and indent > current_indent:
            # Nested numbered example inside the current claim's
            # supporting paragraphs: continuation, not a boundary.
            current.append(line)
        elif m or model_m:
            flush()
            span_preamble = " ".join(preamble)
            preamble = []
            current = [(m or model_m).group(2).strip()]
            current_model_number = model_m is not None
            current_model_number_value = model_m.group(1) if model_m else None
            current_indent = indent
        elif current is not None:
            current.append(line)
        else:
            preamble.append(line)
    flush()
    return spans


class ClaimRegistry:
    """Append-only, mechanically derived claim list (design §2A)."""

    def __init__(self) -> None:
        self.claims: list[Claim] = []
        # Model-written numbers seen in the most recent register call
        # (C1); the caller turns these into a transcript note.
        self.last_disregarded_model_numbers: list[str] = []

    def ids(self) -> set[str]:
        return {c.id for c in self.claims}

    def by_id(self, claim_id: str) -> Claim | None:
        for c in self.claims:
            if c.id == claim_id:
                return c
        return None

    def register(self, participant: str, phase: str, text: str,
                 relationship: str | None = None,
                 relates_to: list[str] | None = None,
                 supersedes: str | None = None,
                 withdraws: str | None = None) -> list[Claim]:
        """Parse numbered claims structurally and append them.

        Kept for openings/responses (no links). Revision claims use
        :meth:`register_spans` for per-span links (C3).
        """
        spans = _parse_claim_spans(text)
        links = [{
            "relationship": relationship,
            "relationship_target": None,
            "relates_to": list(relates_to or []),
            "supersedes": supersedes,
            "withdraws": withdraws,
        } for _ in spans]
        return self.register_spans(participant, phase, spans, links)

    def register_spans(self, participant: str, phase: str,
                       spans: list[ClaimSpan],
                       links: list[dict[str, Any]] | None = None) -> list[Claim]:
        """Append pre-parsed spans with per-span links (C3).

        ``links[i]`` (when given) carries that span's relationship,
        relationship_target, relates_to, supersedes, and withdraws,
        plus relationship_targets and reclassified_status for
        multi-target / reclassification links.
        System IDs are assigned sequentially; model-written numbers
        are never stored (C1).
        """
        self.last_disregarded_model_numbers = []
        registered: list[Claim] = []
        for i, span in enumerate(spans):
            link = (links or [{}] * len(spans))[i] if links else {}
            if span.used_model_number:
                # Recover the model-written number for the note.
                self.last_disregarded_model_numbers.append(
                    f"C{span.model_number}" if span.model_number else "C?")
            claim = Claim(
                id=f"C{len(self.claims) + 1}",
                participant=participant,
                phase=phase,
                text=span.text,
                status=span.status,
                relationship=link.get("relationship"),
                relates_to=list(link.get("relates_to") or []),
                supersedes=link.get("supersedes"),
                withdraws=link.get("withdraws"),
                relationship_target=link.get("relationship_target"),
                relationship_targets=list(link.get("relationship_targets") or []),
                reclassified_status=link.get("reclassified_status"),
            )
            self.claims.append(claim)
            registered.append(claim)
        return registered

    def render(self) -> str:
        lines = ["Claim registry (meeting-local IDs):"]
        for c in self.claims:
            lines.append(f"{c.id} [{c.participant}, {c.status}]: {c.text}")
        return "\n".join(lines)


def _claim_status(first_line: str, inherited: str = "") -> str:
    """Epistemic status for a claim's first line (C2, legibility A).

    Recognized formats, in order: bare prefix (``Observed:``), bold
    prefix (``**Observed:**``, colon inside or outside the bold
    markers), bracket prefix (``[Observed]``, optionally bold-wrapped
    as ``**[Observed]**``), parenthetical prefix (``(Observed)``,
    weakest explicit format — first token inside the parentheses
    only), then the section-heading inheritance. Anything else is
    explicitly ``"unknown"`` — never blank.
    """
    line = first_line.strip()
    for rx in (_STATUS_PREFIX_RE, _STATUS_BOLD_PREFIX_RE,
               _STATUS_BOLD_COLON_OUT_RE, _STATUS_BOLD_BRACKET_RE,
               _STATUS_BRACKET_RE, _STATUS_PAREN_RE):
        m = rx.match(line)
        if m:
            return m.group(1).capitalize()
    return inherited or "unknown"


def _find_citations(text: str) -> list[str]:
    """Claim IDs cited, in order of first appearance, deduplicated."""
    seen: list[str] = []
    for m in _CITATION_RE.finditer(text or ""):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def _stated_moves(text: str) -> list[str]:
    """Move words stated, in order of first occurrence in the text."""
    found: list[tuple[int, str]] = []
    for name, rx in _MOVE_RES:
        m = rx.search(text or "")
        if m:
            found.append((m.start(), name))
    return [name for _, name in sorted(found)]


def _explicit_targets(scope: str) -> dict[str, list[str]]:
    """Verified move→claim targets in a scope (C5).

    A move counts as explicitly targeted only when the text
    syntactically associates it with its claim id:
    - a direct pattern ("Objection to C29", "Evidence request
      regarding C59", "Correction of C18", "Agreement with C4");
    - a "Move:" declaration together with an "in response to" id list
      ("In response to C14, C26 — Move: agreement and extension");
    - a single move word together with an "in response to" id list
      ("In response to C14, agreement: ...").
    Same-span proximity without one of these is a candidate only and
    yields nothing here. Returns {move: [claim ids in order]}.
    """
    found: dict[str, list[str]] = {}

    def add(move: str, cid: str) -> None:
        found.setdefault(move, [])
        if cid not in found[move]:
            found[move].append(cid)

    for move, rx in _TARGET_RES:
        for m in rx.finditer(scope or ""):
            add(move, m.group(1))
    resp = _IN_RESPONSE_TO_RE.search(scope or "")
    if resp:
        ids = _find_citations(resp.group(1))
        decl = _MOVE_DECL_RE.search(scope or "")
        if decl:
            for move, _ in _MOVE_PATTERNS:
                if re.search(r"\b" + move.replace("_", r"\s+") + r"\b",
                             decl.group(1), re.IGNORECASE):
                    for cid in ids:
                        add(move, cid)
            # "request for evidence" spelled out in a Move: declaration.
            if re.search(r"request for evidence", decl.group(1), re.IGNORECASE):
                for cid in ids:
                    add("evidence_request", cid)
        else:
            moves_here = _stated_moves(scope or "")
            if len(set(moves_here)) == 1:
                for cid in ids:
                    add(moves_here[0], cid)
    return found


def _relationship_in_scope(scope: str) -> tuple[str | None, str | None]:
    """Relationship word + target claim in a scope (C4), by precedence.

    Returns (word, target_id) where word is revised/defended/withdrawn
    (normalized to the base form) and target_id is the claim the word
    applies to, or (word, None) when the word appears without an
    identifiable target, or (None, None) when no word appears. The
    fallbacks — "in response to" list first id, then "my claim" first
    citation — are documented heuristics: they identify what the text
    points at, not whether the link is valid (authorship decides that
    in :func:`_map_relationship`).
    """
    m = _REL_BRACKET_RE.search(scope or "")
    if m:
        return _normalize_stance_word(m.group(2)), m.group(1)
    m = _REL_VERB_TARGET_RE.search(scope or "")
    if m:
        return _normalize_stance_word(m.group(1)), m.group(2)
    m = _REL_IS_WITHDRAWN_RE.search(scope or "")
    if m:
        return "withdrawn", m.group(1)
    word_m = _RELATIONSHIP_RE.search(scope or "")
    if not word_m:
        return None, None
    word = _normalize_stance_word(word_m.group(1))
    resp = _IN_RESPONSE_TO_RE.search(scope or "")
    if resp:
        ids = _find_citations(resp.group(1))
        if ids:
            return word, ids[0]
    if re.search(r"\bmy claim\b", scope or "", re.IGNORECASE):
        ids = _find_citations(scope or "")
        if ids:
            return word, ids[0]
    return word, None


def _normalize_stance_word(word: str | None) -> str | None:
    """Normalize a stance verb to revised/defended/withdrawn.

    Retract-family verbs are withdrawal language (mandate reliability:
    "they are retracted" must not parse as no stance at all).
    """
    if word is None:
        return None
    w = word.lower()
    if w in ("revise", "revising", "revised"):
        return "revised"
    if w in ("defend", "defending", "defended"):
        return "defended"
    if w in ("withdraw", "withdraws", "withdrawing", "withdrawn") or w.startswith("retract"):
        return "withdrawn"
    return w


def _stance_negated(scope: str, pos: int) -> bool:
    """True when a negation word precedes a stance word in-window.

    Bare "no" is excluded (too broad: "No, I withdraw C6" negates
    nothing). A negated stance yields no targets anywhere below.
    """
    window = scope[max(0, pos - _STANCE_NEGATION_WINDOW):pos]
    return _STANCE_NEGATION_RE.search(window) is not None


def _parse_id_list(fragment: str) -> list[str]:
    """Claim ids in a list fragment: explicit ids plus range expansion.

    Ranges expand only when the span is within _MOVE_RANGE_CAP; an
    over-cap range contributes nothing (fail-closed: an absurd range
    must not withdraw anything). Order preserved, duplicates removed.
    """
    targets: list[str] = []

    def add(cid: str) -> None:
        if cid not in targets:
            targets.append(cid)

    pos = 0
    n = len(fragment)
    while pos < n:
        m = _LIST_ITEM_RE.match(fragment, pos)
        if not m:
            break
        a, b = int(m.group(1)), m.group(2)
        if b is None:
            add(f"C{a}")
        elif int(b) >= a and (int(b) - a) <= _MOVE_RANGE_CAP:
            for num in range(a, int(b) + 1):
                add(f"C{num}")
        pos = m.end()
        # Separator: comma or "and", then another item; else done.
        sep = re.match(r"\s*(?:,|\band\b)\s*", fragment[pos:])
        if not sep:
            break
        pos += sep.end()
    return targets


def _sentences(text: str) -> list[str]:
    """Split text into sentences on terminators and newlines.

    Over-splitting only risks missing a target (fail-closed), never
    inventing one.
    """
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text or "") if p.strip()]


def _sentence_containing(text: str, pos: int) -> str:
    """The sentence (per _sentences) containing character offset pos."""
    offset = 0
    for sentence in _sentences(text):
        start = text.find(sentence, offset)
        if start == -1:
            continue
        end = start + len(sentence)
        if start <= pos < end:
            return sentence
        offset = end
    return text


def _stance_move_in_scope(scope: str) -> tuple[str | None, list[str], str]:
    """Stance word + move targets + scope for one span's own text.

    Runs the tight patterns first (unchanged behavior for every form
    they already handle). When they yield no target, rescues the
    historical forms, in order, for the first non-negated stance
    occurrence that yields targets:
    - P2 immediate list: stance word + punctuation + id list/range
      ("Withdrawn: C27, C28, C29, C30–C44", "(Revised) C6–C13").
    - P3 object phrasing: stance word ... <noun> in/of <list>
      ("citations in C6–C9", "values reported in C6–C13").
    - P4 anaphoric range: sentence-initial list + "they are retracted"
      ("C27–C44 ... they are retracted").
    Returns (word, targets, scope): scope is "citations" when a P3
    noun names evidence (citations, sources, references, read
    statements) — the stance then applies to the citations, never to
    the claim content — and "claims" otherwise. Targets empty means
    no move was found (the caller falls back to the bare-word /
    preamble behavior).
    """
    word0, target0 = _relationship_in_scope(scope)
    if target0 is not None:
        return word0, [target0], "claims"
    for m in _STANCE_WORD_RE.finditer(scope or ""):
        if _stance_negated(scope or "", m.start()):
            continue
        word = _normalize_stance_word(m.group(1))
        # P2: list immediately following the stance word.
        rest = (scope or "")[m.end():]
        stripped = re.match(r"[\s:\)\-–—*_]*", rest)
        after = rest[stripped.end():] if stripped else rest
        targets = _parse_id_list(after)
        if targets:
            return word, targets, "claims"
        # P3/P4 operate on the occurrence's sentence.
        sentence = _sentence_containing(scope or "", m.start())
        obj = _OBJECT_TARGETS_RE.search(sentence)
        if obj:
            targets = _parse_id_list(obj.group(2))
            if targets:
                scope_name = ("citations"
                              if obj.group(1).lower() in _CITATION_NOUNS
                              else "claims")
                return word, targets, scope_name
        # P4: sentence-initial list + anaphoric stance of this family.
        head = re.match(
            r"\s*(?:[-*]\s*)?(?:\*\*)?"
            r"((?:C\d+\s*(?:[-–—]\s*C\d+)?)(?:\s*(?:,|and)\s*C\d+\s*(?:[-–—]\s*C\d+)?)*)",
            sentence)
        if head:
            tail = sentence[head.end():]
            fam = {"revised": r"revis\w*",
                   "defended": r"defend\w*",
                   "withdrawn": r"(?:withdraw\w*|retract\w*)"}[word or ""]
            if re.search(r"\b(they|these|those)\s+(?:are|were)\s+(?:\w+\s+){0,2}?" + fam + r"\b",
                         tail, re.IGNORECASE):
                targets = _parse_id_list(head.group(1))
                if targets:
                    return word, targets, "claims"
    return word0, [], "claims"


def _map_relationship(word: str | None, target: str | None, author: str,
                      registry: "ClaimRegistry") -> tuple[str, str | None, str | None, str | None]:
    """Map a stated relationship through the authorship rule (C4, legibility C).

    Returns (relationship, relationship_target, supersedes, withdraws).
    Self-targets keep revised/defended/withdrawn and set supersedes /
    withdraws. Cross-author targets map to proposes_revision_of /
    supports_withdrawal_of / endorses and never change the target's
    disposition. No target → ("unstated", "unstated", None, None): a
    bare stance word without an identifiable target is recorded
    nowhere as a relationship — the word itself stays in the
    transcript prose and in stated_moves, never as a claim-level
    label. No word → ("unstated", None, None, None).
    """
    if word is None:
        return "unstated", None, None, None
    if target is None:
        return "unstated", "unstated", None, None
    original = registry.by_id(target) if registry is not None else None
    if original is not None and original.participant == author:
        if word == "revised":
            return "revised", target, target, None
        if word == "withdrawn":
            return "withdrawn", target, None, target
        return "defended", target, None, None
    mapped = {"revised": "proposes_revision_of",
              "withdrawn": "supports_withdrawal_of",
              "defended": "endorses"}.get(word, word)
    return mapped, target, None, None


def _explicit_challenge_target(span_analysis: dict[str, Any], author: str,
                               registry: "ClaimRegistry") -> str | None:
    """First explicitly targeted objection to another author's claim (C).

    Used when a span carries no revised/defended/withdrawn word: an
    explicit objection/evidence-request move with a mechanically
    established other-author target is a ``challenges`` relationship,
    not an erased disagreement and not an authorial revision. Returns
    the target claim id, or None when no such target exists.
    """
    for move, targets in span_analysis["explicit_targets"].items():
        if move not in _OBJECTION_MOVES:
            continue
        for target_id in targets:
            if target_id not in span_analysis["citations_valid"]:
                continue
            original = registry.by_id(target_id) if registry is not None else None
            if original is not None and original.participant != author:
                return target_id
    return None


def _analyze_span(span: ClaimSpan, *, author: str, registry: "ClaimRegistry",
                  frozen_ids: set[str] | None) -> dict[str, Any]:
    """Per-span mechanical analysis (C3, C5, C6).

    Scope = preamble + text (preamble lines like "Relationship:
    defended." belong to the span for relationship purposes, but are
    not part of the claim text). Mandate reliability: the span's OWN
    text is consulted first — a contribution header ("Defending
    C6–C13") must not override the span's own stance ("(Revised)").
    Only when the span's own text carries no stance word does the
    preamble fall back apply. Exception: when the span's own stance
    word carries no target, the preamble may still supply the target
    for the SAME stance ("Relationship: withdrawn. In response to
    C3, I withdraw it:" above "Withdrawn: Gamma is retracted.") —
    a different preamble stance never overrides the span's own word.
    Citations are validated against ``frozen_ids``; authorship is
    looked up in the registry.
    """
    scope = f"{span.preamble} {span.text}".strip()
    cited = _find_citations(scope)
    valid = [c for c in cited if frozen_ids is None or c in frozen_ids]
    dead = [c for c in cited if frozen_ids is not None and c not in frozen_ids]
    self_cites: list[str] = []
    other_cites: list[str] = []
    for cid in valid:
        original = registry.by_id(cid) if registry is not None else None
        if original is not None and original.participant == author:
            self_cites.append(cid)
        else:
            other_cites.append(cid)
    targets = _explicit_targets(scope)
    word, move_targets, move_scope = _stance_move_in_scope(span.text)
    source: str | None = None
    citation_withdrawal = False
    if word is None:
        # No stance word in the span's own text: preamble declares it.
        word, target = _relationship_in_scope(scope)
        move_targets = [target] if target else []
        source = "single" if target else None
    elif not move_targets:
        # Span stance without a target: the preamble may supply the
        # target for the SAME stance only. A different preamble
        # stance never overrides the span's own word.
        p_word, p_target = _relationship_in_scope(scope)
        if p_word == word and p_target:
            move_targets = [p_target]
            source = "single"
    elif move_scope == "citations":
        # The stance is over evidence, not content. A citation
        # withdrawal is recorded as its own non-move link
        # ("withdraws_citations"); a citation-scope revision or
        # defense moves no claim at all, so the stance is
        # neutralized rather than misread as a content move.
        if word == "withdrawn":
            citation_withdrawal = True
            source = "citation"
        else:
            word = None
            move_targets = []
    else:
        source = "list"
    reclassification = _reclassification_in_span(span.text, word, move_targets)
    return {
        "span": span,
        "citations_valid": valid,
        "citations_dead": dead,
        "self_citations": self_cites,
        "other_citations": other_cites,
        "moves": _stated_moves(scope),
        "explicit_targets": targets,
        "relationship_word": word,
        "relationship_target_raw": move_targets[0] if move_targets else None,
        "relationship_targets": move_targets,
        "relationship_source": source,
        "citation_withdrawal": citation_withdrawal,
        "reclassification": reclassification,
    }


def _reclassification_in_span(text: str, word: str | None,
                              targets: list[str]) -> dict[str, Any] | None:
    """Detect a same-author epistemic reclassification in a span.

    Requires all three: a revised-family stance word, a status-pair
    reassignment ("are Inferred, not Observed"), and a framing-
    retraction cue ("I retract ...", "framing", "presented as").
    Without the cue, a bare status correction stays an ordinary
    revision (supersession) — the detector is deliberately narrow.
    Targets are the span's move targets; authorship and ordering are
    validated in derivation, not here. Returns None when absent.
    """
    if word != "revised" or not targets:
        return None
    m = _STATUS_PAIR_RE.search(text or "")
    if not m:
        return None
    if not _FRAMING_CUE_RE.search(text or ""):
        return None
    return {"targets": list(targets),
            "new_status": m.group(1).capitalize()}


def _analyze_contribution(text: str, *, author: str, registry: "ClaimRegistry",
                          frozen_ids: set[str] | None) -> dict[str, Any]:
    """Analyze a whole contribution via its spans (C3, C5, C6).

    Returns spans, per-span analyses, contribution aggregates, the
    contribution-level relationship (first explicit pattern in the
    full text, mapped through authorship), and classification:
    "classified" when spans exist, else "unclassified" — unclassified
    interactions are recorded but never promoted into objections.
    """
    spans = _parse_claim_spans(text)
    per_span = [_analyze_span(s, author=author, registry=registry,
                              frozen_ids=frozen_ids) for s in spans]
    cited: list[str] = []
    dead: list[str] = []
    self_cites: list[str] = []
    other_cites: list[str] = []
    moves = _stated_moves(text or "")
    for a in per_span:
        for cid in a["citations_valid"]:
            if cid not in cited:
                cited.append(cid)
        for cid in a["citations_dead"]:
            if cid not in dead:
                dead.append(cid)
        for cid in a["self_citations"]:
            if cid not in self_cites:
                self_cites.append(cid)
        for cid in a["other_citations"]:
            if cid not in other_cites:
                other_cites.append(cid)
    if not spans:
        # Unclassified: no parseable spans. Contribution-level
        # citations are preserved for legibility, labeled
        # unclassified — they are never promoted into claim-level
        # links, objections, or addressability targets (no spans
        # means no explicit targets, so move_targeted stays False).
        for cid in _find_citations(text or ""):
            if frozen_ids is not None and cid not in frozen_ids:
                if cid not in dead:
                    dead.append(cid)
            else:
                if cid not in cited:
                    cited.append(cid)
                original = registry.by_id(cid)
                if original is not None:
                    if original.participant == author:
                        if cid not in self_cites:
                            self_cites.append(cid)
                    else:
                        if cid not in other_cites:
                            other_cites.append(cid)
    word, target = _relationship_in_scope(text or "")
    mapped, mapped_target, _, _ = _map_relationship(word, target, author, registry)
    challenge_target = None
    if word is None:
        # No revised/defended/withdrawn word, but an explicitly
        # targeted objection to another author's claim is a
        # "challenges" relationship at contribution level too —
        # legitimate disagreement, not an authorial revision and not
        # an unknown relationship (legibility C).
        for span_analysis in per_span:
            challenge_target = _explicit_challenge_target(
                span_analysis, author, registry)
            if challenge_target is not None:
                break
        if challenge_target is not None:
            mapped, mapped_target = "challenges", challenge_target
    return {
        "spans": spans,
        "per_span": per_span,
        "cited_claim_ids": cited,
        "dead_citations": dead,
        "self_citations": self_cites,
        "other_citations": other_cites,
        "stated_moves": moves,
        "classification": "classified" if spans else "unclassified",
        "relationship": mapped if (word or challenge_target) else "unstated",
        "relationship_target": mapped_target if (word or challenge_target) else "unstated",
    }


def _verified_targets_from_spans(analysis: dict[str, Any],
                                 registered: list["Claim"],
                                 author: str,
                                 registry: "ClaimRegistry") -> tuple[list[dict], list[dict]]:
    """Verified challenges/supports from per-span explicit targets (C5).

    Only explicitly targeted moves at other-author claims count, and
    only when the target is a valid citation. Same-span proximity
    alone yields nothing here — those citations stay candidates.
    """
    challenges: list[dict] = []
    supports: list[dict] = []
    for span_analysis, claim in zip(analysis["per_span"], registered):
        for move, targets in span_analysis["explicit_targets"].items():
            for target_id in targets:
                if target_id not in analysis["cited_claim_ids"]:
                    continue
                original = registry.by_id(target_id)
                if original is None or original.participant == author:
                    continue
                if move in _OBJECTION_MOVES:
                    challenges.append({
                        "source_claim_id": claim.id,
                        "challenger": author,
                        "target_claim_id": target_id,
                        "move": move,
                    })
                elif move == "agreement":
                    supports.append({
                        "source_claim_id": claim.id,
                        "supporter": author,
                        "target_claim_id": target_id,
                        "move": move,
                    })
    return challenges, supports


def _move_targeted(analysis: dict[str, Any], author: str,
                   registry: "ClaimRegistry") -> bool:
    """True when any span explicitly targets another author's claim (C6)."""
    for span_analysis in analysis["per_span"]:
        for move, targets in span_analysis["explicit_targets"].items():
            for target_id in targets:
                if target_id not in analysis["cited_claim_ids"]:
                    continue
                original = registry.by_id(target_id)
                if original is not None and original.participant != author:
                    return True
    return False


def _revision_links(analysis: dict[str, Any], author: str,
                    registry: "ClaimRegistry") -> list[dict[str, Any]]:
    """Per-span relationship links for a revision contribution (C3, C4, C).

    A span with no revised/defended/withdrawn word but an explicitly
    targeted objection to another author's claim links as
    "challenges" — the disagreement is preserved, not erased and not
    mislabeled as an authorial revision. Mandate reliability: spans
    whose stance attaches to a list/range link every target
    (relationship_targets); derivation and disposition validate each
    target's authorship and ordering, so a mixed-authorship list can
    never move another author's claim. A reclassification span links
    as "reclassifies" (never as supersession: downgrading Observed to
    Inferred is not withdrawing or replacing the claim). A
    citation-scope withdrawal links as "withdraws_citations" (never
    as withdrawal: withdrawing citations leaves content active).
    """
    links: list[dict[str, Any]] = []
    for span_analysis in analysis["per_span"]:
        word = span_analysis["relationship_word"]
        targets = span_analysis.get("relationship_targets") or []
        if word is None:
            challenge_target = _explicit_challenge_target(
                span_analysis, author, registry)
            if challenge_target is not None:
                links.append({
                    "relationship": "challenges",
                    "relationship_target": challenge_target,
                    "relates_to": [c for c in span_analysis["citations_valid"]],
                    "supersedes": None,
                    "withdraws": None,
                })
                continue
        recl = span_analysis.get("reclassification")
        if recl is not None:
            links.append({
                "relationship": "reclassifies",
                "relationship_target": recl["targets"][0],
                "relationship_targets": list(recl["targets"]),
                "reclassified_status": recl["new_status"],
                "relates_to": [c for c in span_analysis["citations_valid"]],
                "supersedes": None,
                "withdraws": None,
            })
            continue
        if span_analysis.get("citation_withdrawal") and targets:
            # A citation-scope withdrawal (A7): recorded, but never a
            # content move — derivation and disposition both ignore
            # this relationship, so the cited claims stay active
            # while the withdrawal itself is visible in the record.
            links.append({
                "relationship": "withdraws_citations",
                "relationship_target": targets[0],
                "relationship_targets": list(targets),
                "relates_to": [c for c in span_analysis["citations_valid"]],
                "supersedes": None,
                "withdraws": None,
            })
            continue
        if span_analysis.get("relationship_source") == "list" and targets:
            # Label follows the first target's mapping (the single-
            # target convention); effects are per-target downstream.
            mapped, _, _, _ = _map_relationship(
                word, targets[0], author, registry)
            links.append({
                "relationship": mapped,
                "relationship_target": targets[0],
                "relationship_targets": list(targets),
                "relates_to": [c for c in span_analysis["citations_valid"]],
                "supersedes": None,
                "withdraws": None,
            })
            continue
        mapped, mapped_target, supersedes, withdraws = _map_relationship(
            word, span_analysis["relationship_target_raw"], author, registry)
        links.append({
            "relationship": mapped if word else "unstated",
            "relationship_target": mapped_target if word else "unstated",
            "relates_to": [c for c in span_analysis["citations_valid"]],
            "supersedes": supersedes,
            "withdraws": withdraws,
        })
    return links


def _apply_dispositions(registry: "ClaimRegistry",
                        registered: list["Claim"],
                        links: list[dict[str, Any]]) -> None:
    """Authorial disposition updates from a revision (C4).

    Only the author's own revision changes an original claim's
    disposition; first revision wins. Cross-author revision language
    never changes disposition (it maps to proposes_revision_of /
    supports_withdrawal_of / endorses in the links).
    """
    for claim, link in zip(registered, links):
        target_id = link["supersedes"] or link["withdraws"]
        if target_id is None:
            continue
        original = registry.by_id(target_id)
        if original is None or original.disposition is not None:
            continue
        if link["supersedes"]:
            original.disposition = "revised"
        elif link["withdraws"]:
            original.disposition = "withdrawn"
        original.disposition_by = claim.id
    for claim in registered:
        if claim.relationship == "defended":
            original = registry.by_id(claim.relationship_target or "")
            if (original is not None
                    and original.participant == claim.participant
                    and original.disposition is None):
                original.disposition = "maintained"
                original.disposition_by = claim.id
    # Mandate reliability: multi-target links (relationship_targets)
    # apply per target with the same first-wins rule. The label family
    # maps back to the move (proposes_revision_of → revised, and so
    # on); authorship is checked per target, so a mixed-authorship
    # list can never set another author's disposition. Reclassifies
    # links never touch disposition (a downgrade is not a move).
    _MOVE_FAMILY = {
        "revised": "revised", "proposes_revision_of": "revised",
        "withdrawn": "withdrawn", "supports_withdrawal_of": "withdrawn",
        "defended": "maintained", "endorses": "maintained",
    }
    for claim, link in zip(registered, links):
        targets = link.get("relationship_targets") or []
        if not targets or link.get("relationship") == "reclassifies":
            continue
        disposition = _MOVE_FAMILY.get(link.get("relationship"))
        if disposition is None:
            continue
        for target_id in targets:
            original = registry.by_id(target_id)
            if original is None or original.disposition is not None:
                continue
            if original.participant != claim.participant:
                continue
            original.disposition = disposition
            original.disposition_by = claim.id


def _telemetry_block(*, phase: str, max_generations: int, completed: int,
                     allocated: int, reserved: dict[str, str]) -> str:
    """Parallel-safe orchestrator telemetry (C8).

    Distinguishes completed, allocated (this phase's jobs), and
    reserved (planned, not yet completed) generations, because phases
    run in parallel and no participant-specific "generation N of 16"
    is meaningful. ``reserved`` maps slot labels to display values
    like "up to 5" or "1".
    """
    reserved_text = ". ".join(
        f"{label} reserved: {value}" for label, value in reserved.items())
    allocated_text = f"Slots allocated this phase: {allocated}."
    if reserved_text:
        allocated_text += f" {reserved_text}."
    return (
        f"Orchestrator state — Phase: {phase}. Maximum generations: "
        f"{max_generations}. Generations completed: {completed}. "
        f"{allocated_text} This block "
        "describes completed, allocated, and planned execution; planned "
        "slots are not yet completed generations. Do not infer remaining "
        "capacity from a number that ignores concurrent calls, and do "
        "not assert any other operational fact (remaining capacity, "
        "token counts, other participants' state)."
    )


def estimate_tokens(text: str) -> int:
    """Rough token estimate for state-packet diagnostics (C9).

    Labeled estimate only (chars / 4) — it is NOT a provider token
    measurement. True provider token measurement (tokenizers or API
    usage fields) is still open; no cap value in this change depends
    on it, and usage rows keep ``token_usage: "unavailable"`` for
    actuals rather than dressing an estimate up as a measurement.
    """
    return max(1, len(text or "") // 4)


def count_tokens_exact(text: str) -> int | None:
    """Exact token count via ``local_ai.llm.tokenizer`` (B1).

    Returns None when tiktoken is unavailable instead of falling
    back to the chars/4 estimate — a missing measurement is
    reported as missing, never disguised as an estimate, and
    never breaks a meeting: production paths must not fail
    because a measurement dependency is absent.
    """
    try:
        from local_ai.llm.tokenizer import count_tokens
    except ImportError:
        return None
    try:
        return count_tokens(text)
    except RuntimeError:
        # tiktoken missing at call time (tokenizer raises loudly
        # for direct measurement use; here it degrades to None).
        return None


def compute_unresolved_objections(
        verified_challenges: list[dict], registry: "ClaimRegistry",
        revision_claims: list["Claim"]) -> list[dict]:
    """Verified, claim-specific objections with response state (C5).

    Only explicitly targeted objection/evidence-request moves become
    entries — never contribution-level citations, never same-span
    proximity alone. An entry is ``responded_to`` when the target
    claim's author later revised that claim (relationship_target ==
    target, or a revision span citing the objection's source claim);
    ``resolved`` is never set mechanically.
    """
    entries: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ch in verified_challenges:
        key = (ch["target_claim_id"], ch["source_claim_id"])
        if key in seen:
            continue
        seen.add(key)
        target = registry.by_id(ch["target_claim_id"])
        if target is None:
            continue
        responded_by: str | None = None
        for rev in revision_claims:
            if rev.participant != target.participant:
                continue
            if rev.relationship_target == target.id or ch["source_claim_id"] in rev.relates_to:
                responded_by = rev.id
                break
        entries.append({
            "claim_id": ch["target_claim_id"],
            "originator": target.participant,
            "cited_by": ch["challenger"],
            "moves": [ch["move"]],
            "source_claim_id": ch["source_claim_id"],
            "state": "responded_to" if responded_by else "unresolved",
            "responded_by": responded_by,
        })
    return entries


def compute_epistemic_assessments(verified_challenges: list[dict],
                                  verified_supports: list[dict],
                                  registry: "ClaimRegistry") -> None:
    """Set per-claim epistemic assessment from verified targets (C4).

    Challenged wins over supported; anything else stays unresolved.
    ``contradicted`` is never set mechanically (review judgment: a
    participant asserting a contradiction does not establish one).
    Every assessment records its source claim ids in
    ``assessment_sources`` — no assessment without provenance.
    """
    challenged: dict[str, list[str]] = {}
    supported: dict[str, list[str]] = {}
    for ch in verified_challenges:
        challenged.setdefault(ch["target_claim_id"], []).append(ch["source_claim_id"])
    for sup in verified_supports:
        if sup["target_claim_id"] not in challenged:
            supported.setdefault(sup["target_claim_id"], []).append(sup["source_claim_id"])
    for claim in registry.claims:
        if claim.id in challenged:
            claim.epistemic_assessment = "challenged"
            claim.assessment_sources = challenged[claim.id]
        elif claim.id in supported:
            claim.epistemic_assessment = "supported"
            claim.assessment_sources = supported[claim.id]


def build_delta_report(registry: "ClaimRegistry",
                       verified_challenges: list[dict],
                       synthesis_elements: list[dict] | None = None,
                       unclassified_interactions: list[dict] | None = None) -> dict[str, Any]:
    """Candidate delta report (§4, mechanical parts only).

    Revision chains link original claim → verified challenge → the
    author's later revision (by registry order, citing the challenge
    or targeting the claim). Novelty and improvement are NOT computed
    here — the runner proposes candidates; the acceptance review
    judges value. A chain proves responsiveness, never improvement.
    Unclassified candidates: interactions the parser could not
    mechanically verify (no parseable claim spans) that still cite
    claims are listed here, labeled as requiring review — a
    relationship a human can plainly recognize in the transcript must
    never disappear from the artifact merely because the parser could
    not verify it. Legibility, not parser-satisfying output.
    """
    order = {c.id: i for i, c in enumerate(registry.claims)}
    chains: list[dict] = []
    for ch in verified_challenges:
        target = registry.by_id(ch["target_claim_id"])
        if target is None:
            continue
        for rev in registry.claims:
            if rev.phase != "revision" or rev.participant != target.participant:
                continue
            if order.get(rev.id, -1) <= order.get(ch["source_claim_id"], -1):
                continue
            if (ch["source_claim_id"] in rev.relates_to
                    or rev.relationship_target == target.id):
                chains.append({
                    "original_claim_id": target.id,
                    "challenge_claim_id": ch["source_claim_id"],
                    "challenge_move": ch["move"],
                    "challenger": ch["challenger"],
                    "revision_claim_id": rev.id,
                    "revision_relationship": rev.relationship,
                    "author": target.participant,
                    "state": "responded_to",
                })
                break
    later: list[dict] = []
    for el in synthesis_elements or []:
        phases = [registry.by_id(cid).phase for cid in el.get("claim_ids", [])
                  if registry.by_id(cid) is not None]
        if any(p in ("response", "revision") for p in phases):
            later.append(el)
    candidates: list[dict] = []
    for inter in unclassified_interactions or []:
        if not inter.get("cited_claim_ids"):
            continue
        candidates.append({
            "participant": inter["participant"],
            "phase": inter["phase"],
            "cited_claim_ids": inter["cited_claim_ids"],
            "stated_moves": inter.get("stated_moves", []),
            "contribution_relationship": inter.get("relationship", "unstated"),
            "contribution_relationship_target": inter.get("relationship_target"),
            "classification": "unclassified",
            "note": ("Relationship not mechanically verified; requires "
                     "review. Do not treat as an established chain."),
        })
    return {"revision_chains": chains,
            "synthesis_elements_from_later_phases": later,
            "unclassified_candidates": candidates}


def _render_transcript(transcript: Transcript) -> str:
    lines = []
    for e in transcript.entries:
        lines.append(f"{e.kind} [{e.participant}]: {e.text}")
    return "\n".join(lines)


def _run_phase_parallel(
    jobs: list[tuple[str, Any, str]],
    budget: Budget,
    *,
    tool_contexts: dict[str, Any] | None = None,
    tool_phase: str = "",
    tool_log_sink: list | None = None,
) -> list[tuple[str, str | None, str | None, float]]:
    """Run one phase's generations in parallel (design §4).

    ``jobs`` are (participant_name, participant, prompt) in stable
    order. Returns (name, text_or_None, error_or_None, completed_ts,
    usage_or_None) IN STABLE ORDER, never completion order. One
    participant's failure never affects another's result.
    ``usage`` is the provider-reported usage dict when the
    participant exposes ``generate_with_usage`` (the OpenAI seat
    only, via participants.py ``__getattr__``); it is None for the
    tool-loop path (usage arrives via the tool usage sink) and for
    seats with no usage channel (they settle unverified).

    Tool-access stage-1 increment B: when ``tool_contexts`` maps a
    participant name to a ToolLoopContext AND that participant has a
    structured channel (``generate_structured``), its generation
    runs the bounded tool loop instead of a single generate() call.
    The loop's log entries are appended to ``tool_log_sink`` (in
    thread-completion order; the caller re-sorts them into stable
    seat order before appending them to the transcript). A loop
    error is a recorded generation failure, never a raise.
    """
    if not jobs:
        return []

    def work(job: tuple[str, Any, str]) -> tuple[str, str | None, str | None, float, dict | None]:
        name, participant, _prompt = job
        try:
            if (
                tool_contexts is not None
                and name in tool_contexts
                and hasattr(participant, "generate_structured")
            ):
                text, error, entries = run_tool_loop(
                    participant, _prompt, tool_contexts[name],
                    phase=tool_phase, participant_name=name,
                    timeout_seconds=budget.timeout_seconds)
                if tool_log_sink is not None:
                    tool_log_sink.extend(entries)
                return name, text, error, time.time(), None
            if hasattr(participant, "generate_with_usage"):
                # Single call: the usage channel REPLACES generate(),
                # never a second generation. Only the OpenAI seat
                # exposes it; every other seat falls through to
                # generate() and settles unverified (hierarchy case 2).
                text, usage = participant.generate_with_usage(
                    _prompt, timeout=budget.timeout_seconds)
                return (name, text, None, time.time(),
                        usage if isinstance(usage, dict) else None)
            text = participant.generate(_prompt, timeout=budget.timeout_seconds)
            return name, text, None, time.time(), None
        except Exception as exc:  # recorded per participant, not raised
            return name, None, f"{type(exc).__name__}: {str(exc)[:200]}", time.time(), None

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        # futures stay in stable order; results are read back in that
        # same order, so registration is deterministic.
        futures = [pool.submit(work, job) for job in jobs]
        return [f.result() for f in futures]


def run_multi_model_meeting(
    packet: EvidencePacket,
    *,
    store_dir: Path | str,
    budget: Budget | None = None,
    principal: ExecutionPrincipal | None = None,
    seats: list[Seat] | None = None,
    tools_enabled: bool = False,
    nominated_paths: list[str] | None = None,
    snapshot_dir: Path | str | None = None,
    deployed_version: str | None = None,
) -> MeetingResult:
    """Run one R2 meeting. Never raises for participant/generation
    failure: failures are recorded in the transcript and reflected
    in ``ok``.

    ``seats`` overrides resolution (tests inject fake participants);
    otherwise all five seats resolve under the caller's principal in
    stable SEAT_SPECS order.

    Tool-access stage-1 increment B: ``tools_enabled`` turns on the
    per-meeting tool flag (default OFF, never default-on). When on,
    only seats with a structured channel (the GPT seat in stage 1)
    run the bounded read_file loop, and only over
    ``nominated_paths`` that are also in the snapshot manifest;
    every other seat deliberates packet-only, and the asymmetry is
    disclosed in the transcript and the artifact. The snapshot is
    verified once, before the first tool invocation; any failure
    disables tools for the whole meeting and the meeting proceeds
    packet-only. ``snapshot_dir`` / ``deployed_version`` default to
    the increment-A runtime values (image snapshot dir /
    ZENAF_CODE_VERSION); tests pass explicit values.
    """
    # R2 default: max_cost_usd defaults to $0.50 (the authorization);
    # legacy char-cap fields keep their defaults but R2 admission
    # never consults them — the gates are the only authority.
    budget = budget or Budget(
        max_contributions=R2_MAX_GENERATIONS,
        timeout_seconds=120,
    )
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    meeting_id = uuid.uuid4().hex[:12]
    transcript = Transcript()
    registry = ClaimRegistry()
    interactions: list[dict[str, Any]] = []
    # Verified, claim-specific response-phase targets (C5/C6): challenges
    # (objection/evidence-request) and supports (agreement) with explicit
    # syntax. Collected during _record_phase("response", ...).
    verified_challenges: list[dict] = []
    verified_supports: list[dict] = []
    generation_timestamps: dict[str, dict[str, float]] = {}
    # Synthesis-removal stage 2 (2026-10-27): record-completeness
    # inputs. _generate_jobs records every invitation (including
    # budget/cap-blocked generations, which never become jobs);
    # _record_phase and the revision loop record every attempted
    # generation's outcome. The four checks run over these lists
    # before the artifact is written.
    invited_generations: list[dict[str, str]] = []
    generation_outcomes: list[dict[str, Any]] = []
    attempts = 0
    # Cap gates (§4): the per-meeting dollar ledger. Reservations
    # are made in _generate_jobs (before dispatch, single-threaded,
    # hence batch-atomic); settlement happens in _record_phase and
    # the revision loop via _settle_generation.
    ledger = CapBudgetLedger(budget.max_cost_usd)
    generation_settlements: list[dict[str, Any]] = []

    if budget.max_cost_usd is None:
        budget_line = "no authorized budget (fail-closed: no generation)"
    else:
        budget_line = f"meeting budget ${budget.max_cost_usd:.2f}"
    transcript.append(
        "convene", "Reynard (convener)",
        f"Work item: {packet.work_item}\nQuestion: {packet.question}\n"
        f"Budget: max {budget.max_contributions} generations, "
        f"{budget.timeout_seconds}s per call, gates: counted tokens + "
        f"{budget.output_reservation_tokens} reservation <= declared window, "
        f"estimates at standard rates, {budget_line}, no silent truncation. "
        f"No synthesis phase (removed by design 2026-10-27).")

    if seats is None:
        seats = resolve_seat_participants(principal)
    # Stable participant order, fixed at convene (design §4).
    order = [s.name for s in seats]
    present = [s for s in seats if s.participant is not None]
    for seat in seats:
        if seat.participant is None:
            transcript.append("absence", seat.name, seat.absence_note)
            _log_usage(store, meeting_id=meeting_id, participant=seat.name,
                       provider=seat.provider_id, key_source="none",
                       operation="build_room_r2_meeting", outcome="absent",
                       phase="convene", cited_claim_ids=[],
                       token_usage="unavailable")

    # Tool-access stage-1 increment B: per-meeting flag, default OFF.
    # The snapshot is verified ONCE here, before the first tool
    # invocation; a failure disables tools for the whole meeting
    # (never per-call retries) and the meeting proceeds packet-only.
    # A tools-disabled note uses kind "note", never "failure": it is
    # not a failed generation and must not break the
    # record-completeness transcript/generation parity check (which
    # counts only contribution/failure kinds).
    tool_enabled_for_meeting = False
    tool_revision: str | None = None
    tool_capable_names: list[str] = []
    tool_disabled_reason: str | None = None
    tool_nominated: list[str] = []
    tool_contexts: dict[str, ToolLoopContext] = {}
    tool_log_sink: list[dict[str, Any]] = []
    tool_log_all: list[dict[str, Any]] = []
    # Increment C: per-generation tool usage records (drained per
    # phase like the tool log) and a (phase, participant) index so
    # a generation's usage row can carry its tool record.
    tool_usage_sink: list[dict[str, Any]] = []
    tool_usage_all: list[dict[str, Any]] = []
    tool_usage_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    if tools_enabled:
        tool_nominated = sorted({
            normalize_snapshot_path(p)
            for p in (nominated_paths or [])
            if p and p.strip()
        })
        tool_capable_names = [
            s.name for s in present
            if hasattr(s.participant, "generate_structured")
        ]
        snap_dir = Path(snapshot_dir) if snapshot_dir is not None else default_snapshot_dir()
        snap_ok, snap_reason, _snap_details = snapshot_status(snap_dir, deployed_version)
        if not snap_ok:
            tool_disabled_reason = snap_reason
            transcript.append(
                "note", "Reynard (convener)",
                f"Tool access disabled for this meeting: snapshot "
                f"verification failed ({snap_reason}). The meeting "
                f"proceeds packet-only; no file was read as evidence.")
        else:
            try:
                tool_manifest = load_manifest(snap_dir)
                tool_revision = tool_manifest["commit"]
            except ManifestError as exc:
                tool_disabled_reason = f"manifest-unusable: {exc}"
                transcript.append(
                    "note", "Reynard (convener)",
                    f"Tool access disabled for this meeting: {tool_disabled_reason}. "
                    f"The meeting proceeds packet-only; no file was read "
                    f"as evidence.")
            else:
                ctx = ToolLoopContext(
                    nominated_paths=frozenset(tool_nominated),
                    snapshot_dir=snap_dir,
                    manifest=tool_manifest,
                    revision=tool_revision,
                )
                tool_contexts = {name: ctx for name in tool_capable_names}
                ctx.usage_sink = tool_usage_sink
                tool_enabled_for_meeting = True
                packet_only_names = [
                    s.name for s in present if s.name not in tool_capable_names
                ]
                transcript.append(
                    "note", "Reynard (convener)",
                    f"Tool access enabled (stage-1 packet-named-path mode): "
                    f"tool-capable seats: {', '.join(tool_capable_names) or 'none'}; "
                    f"packet-only seats: {', '.join(packet_only_names) or 'none'}; "
                    f"nominated paths: {len(tool_nominated)}; "
                    f"snapshot revision: {tool_revision}. Other seats "
                    f"deliberate packet-only; outside the nominated set "
                    f"is not_inspected, never absence.")
    tool_prompt_extras: dict[str, str] = {}
    if tool_enabled_for_meeting and tool_revision is not None:
        section = tools_prompt_section(tool_nominated, tool_revision)
        tool_prompt_extras = {name: "\n\n" + section for name in tool_capable_names}

    def _drain_tool_log() -> None:
        """Append one phase's tool entries to the transcript.

        Entries are re-sorted into stable seat order (the sink
        collects them in thread-completion order) and appended with
        kind "tool_call", which the record-completeness check
        ignores (it counts only contribution/failure kinds). The
        full entry dicts accumulate in ``tool_log_all`` for the
        artifact's tool_access record.
        """
        if not tool_log_sink:
            return
        ordered = sorted(
            enumerate(tool_log_sink),
            key=lambda pair: (
                order.index(pair[1]["participant"])
                if pair[1]["participant"] in order else len(order),
                pair[0],
            ),
        )
        for _, entry in ordered:
            line = (
                f"{entry['outcome']}: read_file "
                f"{entry.get('requested_path') or '?'} -> "
                f"{entry.get('resolved_path') or '-'} "
                f"({entry.get('lines') or '-'}, {entry.get('chars', 0)} chars)"
            )
            if entry.get("reason"):
                line += f" reason: {entry['reason']}"
            transcript.append("tool_call", entry["participant"], line)
            tool_log_all.append(entry)
        del tool_log_sink[:]

    def _drain_tool_usage() -> None:
        """Move one phase's per-generation usage records to the index.

        Runs after _drain_tool_log and before _record_phase, so a
        generation's usage row can carry its tool record (keyed by
        phase + participant) instead of "unavailable".
        """
        if not tool_usage_sink:
            return
        for record in tool_usage_sink:
            tool_usage_all.append(record)
            tool_usage_by_key[(record["phase"], record["participant"])] = record
        del tool_usage_sink[:]

    def _tool_citation_annotations(phase: str, name: str, text: str) -> list[dict[str, Any]]:
        """Validate one contribution's tool citations at ingestion.

        The validation source is THIS generation's runner-recorded
        tool-call log (same participant, same phase) from
        tool_log_all, which _drain_tool_log has already populated
        for the phase. Claim text is never modified: the returned
        annotations only mark. See citation_validation.py.
        """
        entries = [
            e for e in tool_log_all
            if e.get("phase") == phase and e.get("participant") == name
        ]
        return validate_tool_citations(text or "", entries)

    def _budget_blocked() -> str | None:
        if attempts >= budget.max_contributions:
            return (f"budget_exceeded: generation cap of "
                    f"{budget.max_contributions} reached; no generation attempted")
        return None

    def _settle_generation(phase: str, name: str, error: str | None,
                           usage: dict | None) -> dict[str, Any]:
        """Settle one dispatched generation against the ledger (§4).

        Returns the settlement record for the usage log + artifact,
        and appends it to generation_settlements. Error (any
        exception after dispatch, including timeout): status
        uncertain -> reservation retained, since no signal
        positively confirms non-execution (release requires an
        explicit confirmed-no-call signal, which no current path
        produces). Success with a usable usage dict: reconcile to
        reported billable tokens; a finish_reason of "length" marks
        output-capped (no current provider client surfaces one —
        documented gap, never inferred from token counts or text
        length). Success without usage: retain the reservation,
        marked unverified (never $0).
        """
        key = (phase, name)
        reserved = ledger.reservations.get(key, 0.0)
        seat = next(s for s in seats if s.name == name)
        record: dict[str, Any] = {
            "phase": phase, "participant": name,
            "reserved_usd": round(reserved, 6),
        }
        if error is not None:
            retained = ledger.settle_uncertain(key)
            record.update(reservation_status="uncertain",
                          verified_cost_usd=None,
                          estimated_cost_usd=round(retained, 6),
                          output_capped=False)
        elif (isinstance(usage, dict)
                and isinstance(usage.get("prompt_tokens"), (int, float))
                and isinstance(usage.get("completion_tokens"), (int, float))):
            in_price, out_price = CAP_PRICING.get(seat.model, (0.0, 0.0))
            actual = (usage["prompt_tokens"] * in_price
                      + usage["completion_tokens"] * out_price) / 1_000_000
            overrun = ledger.settle_reported(key, actual)
            record.update(reservation_status="settled",
                          verified_cost_usd=round(actual, 6),
                          estimated_cost_usd=round(reserved, 6),
                          output_capped=(usage.get("finish_reason") == "length"),
                          overrun_usd=round(overrun, 6),
                          reported_prompt_tokens=usage["prompt_tokens"],
                          reported_completion_tokens=usage["completion_tokens"])
        else:
            retained = ledger.settle_unverified(key)
            record.update(reservation_status="unverified",
                          verified_cost_usd=None,
                          estimated_cost_usd=round(retained, 6),
                          output_capped=False)
        generation_settlements.append(record)
        return record

    def _record_phase(phase: str, results: list[tuple[str, str | None, str | None, float, dict | None]],
                      frozen_ids: set[str] | None = None,
                      register: bool = True) -> list[tuple[str, str]]:
        """Append a phase's results to the transcript in stable order.

        Returns [(participant_name, contribution_text)] for generated
        contributions. ``frozen_ids`` is the registry snapshot the
        phase's prompts were built from: citations are validated
        against it, and unknown IDs become dead-citation notes.
        Interactions now carry the C5/C6 evaluations: other-author
        citation, explicitly targeted moves, mechanical addressability
        (those two only), substantive engagement always "unassessed",
        and classification (classified vs unclassified). Verified
        response-phase challenges/supports are collected for the
        objections pass and the delta report.
        """
        generated: list[tuple[str, str]] = []
        generation_timestamps.setdefault(phase, {})
        for name, text, error, completed_ts, usage in results:
            generation_timestamps[phase][name] = completed_ts
            generation_outcomes.append({
                "phase": phase, "participant": name,
                "status": "failed" if error is not None else "completed",
                "reason": error,
            })
            seat = next(s for s in seats if s.name == name)
            if error is not None:
                settlement = _settle_generation(phase, name, error, None)
                transcript.append("failure", name, error)
                _log_usage(store, meeting_id=meeting_id, participant=name,
                           provider=seat.provider_id,
                           key_source=seat.participant.key_source,
                           operation="build_room_r2_meeting", outcome="failed",
                           phase=phase, cited_claim_ids=[],
                           token_usage="unavailable",
                           reservation_status=settlement["reservation_status"],
                           estimated_cost_usd=settlement["estimated_cost_usd"],
                           verified_cost_usd=None)
                continue
            transcript.append("contribution", name, text or "")
            generated.append((name, text or ""))
            analysis = _analyze_contribution(text or "", author=name,
                                             registry=registry,
                                             frozen_ids=frozen_ids)
            valid = analysis["cited_claim_ids"]
            dead = analysis["dead_citations"]
            moves = analysis["stated_moves"]
            # Increment C: ingestion-time tool-citation validation
            # (correction §5, mark never strip). The claim text
            # above is preserved verbatim; only this annotation
            # marks grounded vs unverified.
            tool_citations = _tool_citation_annotations(phase, name, text or "")
            grounded_tool = sum(
                1 for a in tool_citations if a["status"] == "grounded")
            unverified_tool = sum(
                1 for a in tool_citations if a["status"] == "unverified")
            if tool_citations:
                detail = "; ".join(
                    f"{a['citation']} {a['status']}"
                    + (f" ({a['reason']})" if a["reason"] else "")
                    for a in tool_citations)
                transcript.append(
                    "note", name,
                    f"Tool citations: {detail}. Claim text preserved "
                    "verbatim; unverified marks are visible, not removals.")
            if dead:
                transcript.append(
                    "note", name,
                    f"Dead citation: {', '.join(dead)} cited by {name} "
                    "does not exist; it counts for nothing.")
            registered: list[Claim] = []
            if register:
                registered = registry.register_spans(
                    name, phase, analysis["spans"])
                if registry.last_disregarded_model_numbers:
                    transcript.append(
                        "note", name,
                        "model-written number disregarded; system ID assigned "
                        f"(model numbers: {', '.join(registry.last_disregarded_model_numbers)}).")
                listing = "\n".join(
                    f"{c.id} [{c.participant}, {c.status}]: {c.text}"
                    for c in registered
                )
                transcript.append(
                    "claims", name,
                    "Registered claims:\n" + listing if registered
                    else "Registered claims: none.")
                if not registered:
                    transcript.append(
                        "note", name,
                        f"No numbered claims registered from {name}'s {phase}; "
                        "recorded with zero claims. Reason: no parseable "
                        "claim boundaries found.")
            # Verified targets (C5/C6): explicit syntax only, per span.
            if phase == "response":
                challenges, supports = _verified_targets_from_spans(
                    analysis, registered, name, registry)
                verified_challenges.extend(challenges)
                verified_supports.extend(supports)
            move_targeted = _move_targeted(analysis, name, registry)
            cited_other = bool(analysis["other_citations"])
            interactions.append({
                "participant": name, "phase": phase,
                "cited_claim_ids": valid, "dead_citations": dead,
                "self_citations": analysis["self_citations"],
                "other_author_citations": analysis["other_citations"],
                "stated_moves": moves,
                # Mechanical addressability only (C6): other-author
                # citation AND an explicitly targeted move at such a
                # claim. NOT a genuineness score: substance is
                # Joshua's judgment; substantive_engagement stays
                # "unassessed" unless a review sets it.
                "cited_other_author": cited_other,
                "move_targeted": move_targeted,
                "addressable": cited_other and move_targeted,
                "substantive_engagement": "unassessed",
                "classification": analysis["classification"],
                # Increment C: tool-citation validation (mark, never
                # strip) and grounded/unverified counts. No grounding
                # score exists: unverified citations are excluded
                # from grounded counts, never deleted.
                "tool_citations": tool_citations,
                "grounded_tool_citations": grounded_tool,
                "unverified_tool_citations": unverified_tool,
            })
            settlement = _settle_generation(phase, name, None, usage)
            _log_usage(store, meeting_id=meeting_id, participant=name,
                       provider=seat.provider_id,
                       key_source=seat.participant.key_source,
                       operation="build_room_r2_meeting", outcome="generated",
                       phase=phase, cited_claim_ids=valid,
                       token_usage=(usage if usage is not None
                                    else tool_usage_by_key.get(
                                        (phase, name), "unavailable")),
                       reservation_status=settlement["reservation_status"],
                       estimated_cost_usd=settlement["estimated_cost_usd"],
                       verified_cost_usd=settlement["verified_cost_usd"],
                       output_capped=settlement["output_capped"])
        return generated

    def _generate_jobs(phase: str, prompt: str,
                       members: list[Seat],
                       prompt_extras: dict[str, str] | None = None,
                       ) -> list[tuple[str, Any, str]]:
        """Build parallel jobs, enforcing the cap gates + generation budget.

        The single enforcement chokepoint: openings, responses, and
        revisions all pass through here. Per seat, in stable order:
        the invitation is recorded (Stage 2: blocked generations
        stay accounted), then the generation-count cap, then gates
        §1–§4 on the seat's FULL prompt (base + its extras).
        Admission is atomic at the batch level: after per-seat
        gates, the batch's TOTAL reservations must fit the
        available budget — if not, the WHOLE batch is refused
        (none reserved, none dispatched), so combined reservations
        can never exceed the budget. This loop runs
        single-threaded before _run_phase_parallel dispatches,
        which is what makes the reservation atomic.
        ``prompt_extras`` maps a participant name to a section
        appended ONLY to that participant's prompt (tool-access
        stage-1 increment B: the tools section goes to tool-capable
        seats only; packet-only seats never see it).
        """
        nonlocal attempts

        def _record_refusal(seat: Seat, reason: str,
                            decision: GateDecision | None,
                            code_override: str | None = None) -> None:
            transcript.append("failure", seat.name, reason)
            generation_outcomes.append({
                "phase": phase, "participant": seat.name,
                "status": "failed", "reason": reason,
            })
            _log_usage(store, meeting_id=meeting_id, participant=seat.name,
                       provider=seat.provider_id,
                       key_source=seat.participant.key_source,
                       operation="build_room_r2_meeting",
                       outcome="failed", phase=phase,
                       cited_claim_ids=[], token_usage="unavailable",
                       gate_code=(code_override or (decision.code if decision
                                                    else "generation_count")),
                       gate_prompt_tokens=(decision.prompt_tokens
                                           if decision else None),
                       gate_estimated_cost_usd=(decision.estimated_cost_usd
                                                if decision else None),
                       gate_remaining_budget_usd=round(ledger.available_usd, 6))

        jobs: list[tuple[str, Any, str]] = []
        candidates: list[tuple[Seat, str, GateDecision]] = []
        for seat in members:
            assert seat.participant is not None
            # Stage 2: every invitation is recorded, including
            # generations that never become jobs (blocked below) —
            # otherwise check (a) could not see them.
            invited_generations.append({"phase": phase, "participant": seat.name})
            # Generation-count cap: _budget_blocked counts attempts
            # from PRIOR phases; candidates admitted so far in THIS
            # batch have not incremented attempts yet (reservation
            # happens after the batch check), so they must count too
            # — otherwise a max_contributions=2 batch would admit
            # all five seats instead of the first two.
            blocked = _budget_blocked()
            if (blocked is None
                    and attempts + len(candidates) >= budget.max_contributions):
                blocked = (f"budget_exceeded: generation cap of "
                           f"{budget.max_contributions} reached; no generation attempted")
            if blocked is not None:
                _record_refusal(seat, blocked, None)
                continue
            extra = (prompt_extras or {}).get(seat.name, "")
            full_prompt = prompt + extra
            decision = evaluate_admission(
                model=seat.model, prompt=full_prompt, budget=budget,
                remaining_budget=ledger.available_usd)
            if not decision.admitted:
                if decision.prompt_tokens is None:
                    tokens_part = "tokens uncounted"
                else:
                    tokens_part = f"{decision.prompt_tokens} tokens"
                    if decision.margin_tokens:
                        tokens_part += f" + {decision.margin_tokens} margin"
                detail = (
                    f"(prompt {decision.prompt_chars} chars, {tokens_part}, "
                    f"reservation {decision.reservation_tokens}"
                )
                if decision.window is not None:
                    detail += f", window {decision.window}"
                if decision.estimated_cost_usd is not None:
                    detail += f", estimate ${decision.estimated_cost_usd:.4f}"
                detail += f", remaining ${ledger.available_usd:.4f}; no generation attempted)"
                reason = (
                    f"budget_exceeded: [gate={decision.code}] {phase} "
                    f"generation refused: {decision.reason} {detail}"
                )
                _record_refusal(seat, reason, decision)
                continue
            candidates.append((seat, full_prompt, decision))
        # Batch budget: the batch's TOTAL reservations must fit.
        batch_total = sum(d.estimated_cost_usd or 0.0 for _, _, d in candidates)
        if candidates and batch_total > ledger.available_usd:
            for seat, _full_prompt, decision in candidates:
                reason = (
                    f"budget_exceeded: [gate=budget] {phase} batch refused: "
                    f"batch estimate ${batch_total:.4f} exceeds remaining "
                    f"budget ${ledger.available_usd:.4f}; no generation attempted"
                )
                _record_refusal(seat, reason, decision, code_override="budget")
            return jobs
        for seat, full_prompt, decision in candidates:
            ledger.reserve((phase, seat.name), decision.estimated_cost_usd or 0.0)
            attempts += 1
            jobs.append((seat.name, seat.participant, full_prompt))
        return jobs

    # -- Phase 1: independent openings (baseline control). Each
    # participant receives ONLY the packet; no other contribution.
    opening_telemetry = _telemetry_block(
        phase="opening", max_generations=budget.max_contributions,
        completed=0, allocated=len(present),
        reserved={"Response slots": "up to 5", "Revision slots": "up to 5"})
    transcript.append("note", "Reynard (convener)", opening_telemetry)
    opening_prompt = (
        packet.render_prompt() + "\n\n" + _CLAIM_NUMBERING_INSTRUCTION
        + "\n\n" + _CONTRIBUTION_DISCIPLINE
        + "\n\n" + _LANGUAGE_LINE
        + "\n\n" + opening_telemetry
    )
    opening_jobs = _generate_jobs("opening", opening_prompt, present,
                                  prompt_extras=tool_prompt_extras)
    opening_results = _run_phase_parallel(
        opening_jobs, budget,
        tool_contexts=tool_contexts if tool_enabled_for_meeting else None,
        tool_phase="opening", tool_log_sink=tool_log_sink)
    _drain_tool_log()
    _drain_tool_usage()
    openings = _record_phase("opening", opening_results, frozen_ids=set())

    unresolved_objections: list[dict] = []
    # Stage 2: initialized here (not only in the deliberation branch)
    # so the record-completeness check below always has a value,
    # including the no-openings path where no revision claims exist.
    revision_claims: list = []
    # Synthesis-removal stage 1 (2026-10-27): no synthesis phase, so
    # no synthesis variables. Status fields for the synthesis-less
    # artifact (design §3B): record_complete is set when the run
    # reaches artifact writing (all phase results processed — every
    # result is recorded as a contribution or a failure by the phase
    # loops, and a raise before this point produces no result);
    # deliberation_complete is set in the deliberation branch below.
    record_complete: bool = False
    deliberation_complete: bool = False
    unclassified: list[dict] = []
    delta_report: dict[str, Any] = build_delta_report(
        registry, verified_challenges)

    if not openings:
        transcript.append(
            "failure", "Reynard (convener)",
            "no opening contributions; response and revision "
            "phases skipped")
        ok = False
    else:
        # -- Phase 2: one response round. All responders share the
        # same frozen opening registry (one cross-examination round,
        # not an open conversation).
        frozen_ids = registry.ids()
        response_telemetry = _telemetry_block(
            phase="response", max_generations=budget.max_contributions,
            completed=len(openings), allocated=len(present),
            reserved={"Revision slots": "up to 5"})
        transcript.append("note", "Reynard (convener)", response_telemetry)
        response_prompt = (
            packet.render_prompt() + "\n\n" + _CLAIM_NUMBERING_INSTRUCTION
            + "\n\n" + _CONTRIBUTION_DISCIPLINE
            + "\n\n" + registry.render()
            + "\n\n" + _RESPONSE_INSTRUCTION
            + "\n\n" + _LANGUAGE_LINE
            + "\n\n" + response_telemetry
        )
        for seat in seats:
            if seat.participant is None:
                transcript.append(
                    "note", seat.name,
                    f"{seat.name} did not respond: absent from openings.")
        response_jobs = _generate_jobs("response", response_prompt, present,
                                       prompt_extras=tool_prompt_extras)
        response_results = _run_phase_parallel(
            response_jobs, budget,
            tool_contexts=tool_contexts if tool_enabled_for_meeting else None,
            tool_phase="response", tool_log_sink=tool_log_sink)
        _drain_tool_log()
        _drain_tool_usage()
        responses = _record_phase("response", response_results, frozen_ids=frozen_ids)

        # -- Phase 3: optional revision. Invited = originators of
        # claims cited with an objection or evidence request.
        invited_names: list[str] = []
        for inter in interactions:
            if inter["phase"] != "response":
                continue
            if not any(m in _OBJECTION_MOVES for m in inter["stated_moves"]):
                continue
            for cid in inter["cited_claim_ids"]:
                claim = registry.by_id(cid)
                if claim is not None and claim.participant not in invited_names:
                    invited_names.append(claim.participant)
        invited = [s for s in seats
                   if s.name in invited_names and s.participant is not None]
        # Stable order, not invitation order.
        invited.sort(key=lambda s: order.index(s.name))
        if invited:
            revision_telemetry = _telemetry_block(
                phase="revision", max_generations=budget.max_contributions,
                completed=len(openings) + len(responses), allocated=len(invited),
                reserved={})
            transcript.append("note", "Reynard (convener)", revision_telemetry)
            revision_prompt = (
                packet.render_prompt() + "\n\n" + _CLAIM_NUMBERING_INSTRUCTION
                + "\n\n" + _CONTRIBUTION_DISCIPLINE
                + "\n\n" + registry.render()
                + "\n\n" + _FOLLOWUP_INSTRUCTION
                + "\n\n" + _LANGUAGE_LINE
                + "\n\n" + revision_telemetry
            )
            revision_frozen = registry.ids()
            revision_jobs = _generate_jobs(
                "revision", revision_prompt, invited,
                prompt_extras=tool_prompt_extras)
            revision_results = _run_phase_parallel(
                revision_jobs, budget,
                tool_contexts=tool_contexts if tool_enabled_for_meeting else None,
                tool_phase="revision", tool_log_sink=tool_log_sink)
            _drain_tool_log()
            _drain_tool_usage()
            # Follow-ups register with per-span relationship links (C3,
            # C4), not one contribution-wide link.
            rev_generated: list[tuple[str, str]] = []
            generation_timestamps.setdefault("revision", {})
            for name, text, error, completed_ts, usage in revision_results:
                generation_timestamps["revision"][name] = completed_ts
                generation_outcomes.append({
                    "phase": "revision", "participant": name,
                    "status": "failed" if error is not None else "completed",
                    "reason": error,
                })
                seat = next(s for s in seats if s.name == name)
                if error is not None:
                    settlement = _settle_generation("revision", name, error, None)
                    transcript.append("failure", name, error)
                    _log_usage(store, meeting_id=meeting_id, participant=name,
                               provider=seat.provider_id,
                               key_source=seat.participant.key_source,
                               operation="build_room_r2_meeting",
                               outcome="failed", phase="revision",
                               cited_claim_ids=[], token_usage="unavailable",
                               reservation_status=settlement["reservation_status"],
                               estimated_cost_usd=settlement["estimated_cost_usd"],
                               verified_cost_usd=None)
                    continue
                transcript.append("contribution", name, text or "")
                rev_generated.append((name, text or ""))
                analysis = _analyze_contribution(
                    text or "", author=name, registry=registry,
                    frozen_ids=revision_frozen)
                valid = analysis["cited_claim_ids"]
                dead = analysis["dead_citations"]
                moves = analysis["stated_moves"]
                # Increment C: same ingestion-time tool-citation
                # validation as _record_phase (mark, never strip).
                tool_citations = _tool_citation_annotations(
                    "revision", name, text or "")
                grounded_tool = sum(
                    1 for a in tool_citations if a["status"] == "grounded")
                unverified_tool = sum(
                    1 for a in tool_citations if a["status"] == "unverified")
                if tool_citations:
                    detail = "; ".join(
                        f"{a['citation']} {a['status']}"
                        + (f" ({a['reason']})" if a["reason"] else "")
                        for a in tool_citations)
                    transcript.append(
                        "note", name,
                        f"Tool citations: {detail}. Claim text preserved "
                        "verbatim; unverified marks are visible, not removals.")
                if dead:
                    transcript.append(
                        "note", name,
                        f"Dead citation: {', '.join(dead)} cited by {name} "
                        "does not exist; it counts for nothing.")
                if analysis["relationship"] == "unstated":
                    transcript.append(
                        "note", name,
                        f"No relationship stated in {name}'s follow-up; "
                        "recorded as unstated.")
                links = _revision_links(analysis, name, registry)
                registered = registry.register_spans(
                    name, "revision", analysis["spans"], links)
                # Authorial disposition (C4): only the author's own
                # revision changes the original claim, first wins.
                _apply_dispositions(registry, registered, links)
                if registry.last_disregarded_model_numbers:
                    transcript.append(
                        "note", name,
                        "model-written number disregarded; system ID assigned "
                        f"(model numbers: {', '.join(registry.last_disregarded_model_numbers)}).")
                listing = "\n".join(
                    f"{c.id} [{c.participant}, {c.status}]: {c.text}"
                    for c in registered
                )
                transcript.append(
                    "claims", name,
                    "Registered claims:\n" + listing if registered
                    else "Registered claims: none.")
                if not registered:
                    transcript.append(
                        "note", name,
                        f"No numbered claims registered from {name}'s revision; "
                        "recorded with zero claims. Reason: no parseable "
                        "claim boundaries found.")
                move_targeted = _move_targeted(analysis, name, registry)
                cited_other = bool(analysis["other_citations"])
                interactions.append({
                    "participant": name, "phase": "revision",
                    "cited_claim_ids": valid, "dead_citations": dead,
                    "self_citations": analysis["self_citations"],
                    "other_author_citations": analysis["other_citations"],
                    "stated_moves": moves,
                    "cited_other_author": cited_other,
                    "move_targeted": move_targeted,
                    "addressable": cited_other and move_targeted,
                    "substantive_engagement": "unassessed",
                    "classification": analysis["classification"],
                    "relationship": analysis["relationship"],
                    "relationship_target": analysis["relationship_target"],
                    "tool_citations": tool_citations,
                    "grounded_tool_citations": grounded_tool,
                    "unverified_tool_citations": unverified_tool,
                })
                settlement = _settle_generation("revision", name, None, usage)
                _log_usage(store, meeting_id=meeting_id, participant=name,
                           provider=seat.provider_id,
                           key_source=seat.participant.key_source,
                           operation="build_room_r2_meeting",
                           outcome="generated", phase="revision",
                           cited_claim_ids=valid,
                           token_usage=(usage if usage is not None
                                        else tool_usage_by_key.get(
                                            ("revision", name), "unavailable")),
                           reservation_status=settlement["reservation_status"],
                           estimated_cost_usd=settlement["estimated_cost_usd"],
                           verified_cost_usd=settlement["verified_cost_usd"],
                           output_capped=settlement["output_capped"])

        # Verified, claim-specific objections (C5) and epistemic
        # assessments (C4), computed AFTER the revision phase so
        # responded_to can be established mechanically. Unclassified
        # interactions are never promoted into objections — they
        # stay visible in the interactions record and as delta
        # candidates requiring review.
        revision_claims = [c for c in registry.claims if c.phase == "revision"]
        unresolved_objections = compute_unresolved_objections(
            verified_challenges, registry, revision_claims)
        compute_epistemic_assessments(
            verified_challenges, verified_supports, registry)
        unclassified = [i for i in interactions
                        if i.get("classification") == "unclassified"]
        delta_report = build_delta_report(
            registry, verified_challenges,
            unclassified_interactions=unclassified)

        # Synthesis-less status (design §3B): required phases are
        # opening + response; revision is invited, not required, so
        # a recorded revision failure does not block this.
        deliberation_complete = (len(openings) == len(present)
                                 and len(responses) == len(present))

        # No synthesis phase (removed by design 2026-10-27,
        # Joshua: drop synthesis entirely). The registry +
        # transcript are the meeting output; nothing is
        # compressed, so there is no synthesis to gate, parse,
        # or coverage-check. Deliberation ends at revision.
        # Final delta report (no synthesis elements: synthesis removed).
        delta_report = build_delta_report(
            registry, verified_challenges,
            unclassified_interactions=unclassified)

    # Synthesis-removal stage 2 (2026-10-27): the four
    # record-completeness checks run over the record just built
    # (design §4). A check failure never raises out of the runner:
    # it is reported on the artifact itself and flips
    # record_complete False, so ok cannot claim a whole record the
    # checks found broken. The artifact is still written either way.
    # Registry standing stage 2: the standing table is computed here
    # (once) from the finished registry, so the completeness check
    # and the artifact carry the identical table — the check's
    # recomputation invariant verifies exactly that.
    standing_table = compute_claim_standing(
        [c.to_dict() for c in registry.claims], interactions)
    try:
        record_completeness = check_record_completeness(
            invited_generations=invited_generations,
            generation_outcomes=generation_outcomes,
            transcript_entries=[
                {"kind": e.kind, "participant": e.participant}
                for e in transcript.entries
            ],
            claims=[
                {"id": c.id, "participant": c.participant, "phase": c.phase}
                for c in registry.claims
            ],
            verified_challenges=verified_challenges,
            revision_claims=[
                {"id": c.id, "participant": c.participant,
                 "relationship_target": c.relationship_target,
                 "relates_to": list(c.relates_to)}
                for c in revision_claims
            ],
            unresolved_objections=unresolved_objections,
            claims_full=[c.to_dict() for c in registry.claims],
            interactions=interactions,
            standing_table=standing_table,
        )
    except Exception as exc:  # check bug, not meeting failure: report it
        record_completeness = {
            "passed": False, "checks": {},
            "error": f"{type(exc).__name__}: {exc}",
        }

    # Reached artifact writing: every phase result was processed
    # (contribution or recorded failure); see the record_complete
    # note at initialization. Stage 2 makes record_complete
    # VERIFIED, not just asserted: reaching this point is necessary
    # but the four checks must also pass. ok is NOT synthesis
    # success — there is no synthesis — it is record +
    # deliberation completeness.
    record_complete = bool(record_completeness.get("passed"))
    ok = record_complete and deliberation_complete

    # Tool-access stage-1 increment B: the artifact discloses the
    # tool asymmetry (capable vs packet-only seats), the nominated
    # set, the snapshot revision, and the full tool-call log. A
    # flag-off meeting records enabled False with all seats
    # packet-only; a snapshot failure records its reason. The log
    # is what lets a reviewer distinguish "the model inspected X"
    # from "the model said it inspected X".
    # Increment C: citation-validation totals (grounded vs unverified
    # across all recorded interactions; no grounding score exists)
    # and the tool usage summary (generations AND tool-round calls
    # stated separately, never blended).
    citation_totals = {
        "grounded": sum(
            i.get("grounded_tool_citations", 0) for i in interactions),
        "unverified": sum(
            i.get("unverified_tool_citations", 0) for i in interactions),
    }
    if tools_enabled:
        tool_access_record = {
            "enabled": tool_enabled_for_meeting,
            "reason": tool_disabled_reason,
            "revision": tool_revision,
            "tool_capable_seats": tool_capable_names,
            "packet_only_seats": [
                s.name for s in present if s.name not in tool_capable_names
            ],
            "nominated_paths": tool_nominated,
            "tool_calls": tool_log_all,
            "usage": summarize_tool_round_usage(tool_usage_all),
            "citation_validation": citation_totals,
        }
    else:
        tool_access_record = {
            "enabled": False,
            "reason": None,
            "revision": None,
            "tool_capable_seats": [],
            "packet_only_seats": [s.name for s in present],
            "nominated_paths": [],
            "tool_calls": [],
            "usage": summarize_tool_round_usage([]),
            "citation_validation": {"grounded": 0, "unverified": 0},
        }

    artifact = build_draft_artifact_r2(
        meeting_id, packet, transcript, seats, registry,
        interactions=interactions,
        unresolved_objections=unresolved_objections,
        delta_report=delta_report,
        generation_timestamps=generation_timestamps,
        record_complete=record_complete,
        deliberation_complete=deliberation_complete,
        ok=ok,
        record_completeness=record_completeness,
        tool_access=tool_access_record,
        claim_standing=standing_table,
    )
    # Cap gates (§6): the meeting's budget record — estimated vs
    # verified expenditure, reservation states, and the pricing
    # table's provenance. Attached after construction because
    # build_draft_artifact_r2 takes a fixed kwarg set.
    artifact["cap_budget"] = {
        **ledger.to_dict(),
        "pricing_source": CAP_PRICING_SOURCE,
        "pricing_date": CAP_PRICING_DATE,
        "pricing_expiry": budget.pricing_expiry,
        "reservation_tokens": budget.output_reservation_tokens,
        "fleet_ceiling_tokens": CAP_FLEET_CEILING_TOKENS,
        "fleet_ceiling_binding": False,  # reported only; see fork note
        "settlements": generation_settlements,
        "output_capped_generations": [
            {"phase": s["phase"], "participant": s["participant"]}
            for s in generation_settlements if s.get("output_capped")
        ],
    }
    t_path = store / f"meeting_{meeting_id}.transcript.json"
    a_path = store / f"meeting_{meeting_id}.draft_artifact.json"
    _write_json(t_path, {"meeting_id": meeting_id, **transcript.to_dict()})
    _write_json(a_path, artifact)
    return MeetingResult(meeting_id, transcript, artifact, ok, t_path, a_path)


def replay_r2_transcript(contributions: list[dict[str, str]],
                         *, meeting_id: str = "replay",
                         work_item: str = "", question: str = "") -> dict[str, Any]:
    """Re-run corrected parsing over stored contributions (§6 fixture).

    No live generation. ``contributions`` are dicts with
    ``participant``, ``phase`` (opening/response/revision), and
    ``text``, in phase order (openings, then responses, then
    revisions). Frozen citation sets follow the runner: openings
    freeze on nothing, responses on the opening registry, revisions
    on openings + responses. Returns the synthesis-less artifact
    dict built by :func:`build_draft_artifact_r2` (synthesis fields
    absent by design; see ``synthesis_removed``).
    Provenance is empty: a replay has no live participants.
    """
    from types import SimpleNamespace

    registry = ClaimRegistry()
    transcript = Transcript()
    interactions: list[dict[str, Any]] = []
    verified_challenges: list[dict] = []
    verified_supports: list[dict] = []
    frozen_ids: set[str] = set()
    seen_phase: str | None = None
    for contrib in contributions:
        name = contrib["participant"]
        phase = contrib["phase"]
        text = contrib["text"]
        if phase != seen_phase:
            if phase in ("response", "revision"):
                frozen_ids = registry.ids()
            elif phase == "opening":
                frozen_ids = set()
            seen_phase = phase
        transcript.append("contribution", name, text)
        analysis = _analyze_contribution(text, author=name,
                                         registry=registry,
                                         frozen_ids=frozen_ids)
        if phase == "revision":
            links = _revision_links(analysis, name, registry)
            registered = registry.register_spans(
                name, "revision", analysis["spans"], links)
            _apply_dispositions(registry, registered, links)
        else:
            registered = registry.register_spans(
                name, phase, analysis["spans"])
        if registry.last_disregarded_model_numbers:
            transcript.append(
                "note", name,
                "model-written number disregarded; system ID assigned "
                f"(model numbers: {', '.join(registry.last_disregarded_model_numbers)}).")
        listing = "\n".join(
            f"{c.id} [{c.participant}, {c.status}]: {c.text}"
            for c in registered
        )
        transcript.append(
            "claims", name,
            "Registered claims:\n" + listing if registered
            else "Registered claims: none.")
        if not registered:
            transcript.append(
                "note", name,
                f"No numbered claims registered from {name}'s {phase}; "
                "recorded with zero claims. Reason: no parseable "
                "claim boundaries found.")
        if phase == "response":
            challenges, supports = _verified_targets_from_spans(
                analysis, registered, name, registry)
            verified_challenges.extend(challenges)
            verified_supports.extend(supports)
        move_targeted = _move_targeted(analysis, name, registry)
        cited_other = bool(analysis["other_citations"])
        entry: dict[str, Any] = {
            "participant": name, "phase": phase,
            "cited_claim_ids": analysis["cited_claim_ids"],
            "dead_citations": analysis["dead_citations"],
            "self_citations": analysis["self_citations"],
            "other_author_citations": analysis["other_citations"],
            "stated_moves": analysis["stated_moves"],
            "cited_other_author": cited_other,
            "move_targeted": move_targeted,
            "addressable": cited_other and move_targeted,
            "substantive_engagement": "unassessed",
            "classification": analysis["classification"],
        }
        if phase == "revision":
            entry["relationship"] = analysis["relationship"]
            entry["relationship_target"] = analysis["relationship_target"]
        interactions.append(entry)
    revision_claims = [c for c in registry.claims if c.phase == "revision"]
    unresolved_objections = compute_unresolved_objections(
        verified_challenges, registry, revision_claims)
    compute_epistemic_assessments(
        verified_challenges, verified_supports, registry)
    unclassified = [i for i in interactions
                    if i.get("classification") == "unclassified"]
    delta_report = build_delta_report(
        registry, verified_challenges,
        unclassified_interactions=unclassified)
    packet = SimpleNamespace(work_item=work_item, question=question)
    return build_draft_artifact_r2(
        meeting_id, packet, transcript, [], registry,
        interactions=interactions,
        unresolved_objections=unresolved_objections,
        delta_report=delta_report,
        generation_timestamps={},
    )


RETROSPECTIVE_RECOVERY_DISCLOSURE = (
    "DERIVED REPLAY — RETROSPECTIVE RECOVERY: this artifact was "
    "derived by re-running the corrected parser over a stored "
    "transcript. Claims with D-ids were recovered retrospectively "
    "from transcript prose and were NOT available to the other "
    "models as registered claims during the original meeting. "
    "Historical C-ids are unchanged; citations in the original "
    "transcript resolve against the historical registry. No "
    "interaction has been manufactured from retrospective recovery."
)


def replay_derived_r2_transcript(contributions: list[dict[str, str]],
                                 historical_claims: list[dict[str, Any]],
                                 *, meeting_id: str = "derived-replay",
                                 historical_meeting_id: str = "",
                                 work_item: str = "",
                                 question: str = "",
                                 historical_objections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Re-run the corrected parser over a stored transcript, DERIVED (A5).

    No live generation. ``contributions`` are dicts with
    ``participant``, ``phase`` (opening/response/revision), and
    ``text``, in phase order. ``historical_claims`` are the original
    run's claim dicts (id, participant, phase, text, status).

    Historical vs derived identity (the legibility amendment): every
    span whose text matches an unmatched historical claim for the
    same participant and phase keeps that claim's HISTORICAL id;
    spans with no historical match (recovered claims, e.g. Claude's
    bold-numbered spans) receive DERIVED ids (``D1``, ``D2``, …)
    that cannot collide with historical ids. Historical ids are
    never reassigned, so stored citations keep the meaning they had
    during the live meeting. Citation validation uses HISTORICAL
    ids only — recovered claims were not available during the
    meeting, so they are never in a frozen citation set.
    The returned artifact carries the mapping, the disclosure, the
    recovered claims, any manufactured-interaction flags (expected
    empty: derived ids cannot be cited, since citations match the
    ``C\\d+`` pattern), unmatched historical ids (expected empty),
    and a diff summary. The original artifact is never mutated.
    ``objection_counts`` preserves BOTH counts instead of replacing
    the historical count with the derived total: ``historical`` is
    the live-record objection count (the length of
    ``historical_objections`` when supplied, else the number of
    derived-list objections not sourced from recovered claims),
    ``derived`` is the total in this derived artifact, and
    ``recovered_sourced`` counts derived-list objections whose source
    is a recovered claim. The disclosure states the counts in prose
    as well as the structured field.
    """
    from types import SimpleNamespace

    # Historical lookup: per (participant, phase), claims in order,
    # matched by exact span-text equality.
    historical_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for claim in historical_claims:
        historical_by_key.setdefault(
            (claim["participant"], claim["phase"]), []).append(claim)
    matched_historical: set[str] = set()

    def match_historical(participant: str, phase: str,
                         span_text: str) -> dict[str, Any] | None:
        # First unmatched historical claim with equal text, in
        # order — duplicate texts match in order, not by set lookup.
        for claim in historical_by_key.get((participant, phase), []):
            if claim["id"] not in matched_historical \
                    and claim["text"] == span_text:
                matched_historical.add(claim["id"])
                return claim
        return None

    historical_ids_by_phase: dict[str, set[str]] = {}
    for claim in historical_claims:
        historical_ids_by_phase.setdefault(claim["phase"], set()).add(claim["id"])

    registry = ClaimRegistry()
    transcript = Transcript()
    interactions: list[dict[str, Any]] = []
    verified_challenges: list[dict] = []
    verified_supports: list[dict] = []
    mapping: list[dict[str, Any]] = []
    recovered: list[dict[str, Any]] = []
    status_changed: list[dict[str, str]] = []
    derived_counter = 0
    seen_phase: str | None = None
    frozen_ids: set[str] = set()
    for contrib in contributions:
        name = contrib["participant"]
        phase = contrib["phase"]
        text = contrib["text"]
        if phase != seen_phase:
            # Historical-only frozen sets: recovered claims were not
            # available during the meeting and are never citable.
            if phase == "opening":
                frozen_ids = set()
            elif phase == "response":
                frozen_ids = set(historical_ids_by_phase.get("opening", set()))
            elif phase == "revision":
                frozen_ids = set(historical_ids_by_phase.get("opening", set()))
                frozen_ids |= historical_ids_by_phase.get("response", set())
            seen_phase = phase
        transcript.append("contribution", name, text)
        analysis = _analyze_contribution(text, author=name,
                                         registry=registry,
                                         frozen_ids=frozen_ids)
        if phase == "revision":
            links = _revision_links(analysis, name, registry)
        else:
            links = [{} for _ in analysis["spans"]]
        registered: list[Claim] = []
        disregarded: list[str] = []
        for span, link in zip(analysis["spans"], links):
            historical = match_historical(name, phase, span.text)
            if historical is not None:
                claim_id = historical["id"]
                if span.status != historical.get("status"):
                    status_changed.append({
                        "id": claim_id,
                        "old_status": historical.get("status", ""),
                        "new_status": span.status,
                    })
            else:
                derived_counter += 1
                claim_id = f"D{derived_counter}"
                mapping.append({
                    "derived_id": claim_id,
                    "participant": name,
                    "phase": phase,
                    "source": "retrospective recovery from transcript prose",
                })
            if span.used_model_number:
                disregarded.append(
                    f"C{span.model_number}" if span.model_number else "C?")
            claim = Claim(
                id=claim_id,
                participant=name,
                phase=phase,
                text=span.text,
                status=span.status,
                relationship=link.get("relationship"),
                relates_to=list(link.get("relates_to") or []),
                supersedes=link.get("supersedes"),
                withdraws=link.get("withdraws"),
                relationship_target=link.get("relationship_target"),
            )
            registry.claims.append(claim)
            registered.append(claim)
            if historical is None:
                recovered.append(claim.to_dict())
        registry.last_disregarded_model_numbers = disregarded
        if phase == "revision":
            _apply_dispositions(registry, registered, links)
        if disregarded:
            transcript.append(
                "note", name,
                "model-written number disregarded; system ID assigned "
                f"(model numbers: {', '.join(disregarded)}).")
        listing = "\n".join(
            f"{c.id} [{c.participant}, {c.status}]: {c.text}"
            for c in registered
        )
        transcript.append(
            "claims", name,
            "Registered claims:\n" + listing if registered
            else "Registered claims: none.")
        if not registered:
            transcript.append(
                "note", name,
                f"No numbered claims registered from {name}'s {phase}; "
                "recorded with zero claims. Reason: no parseable "
                "claim boundaries found.")
        if phase == "response":
            challenges, supports = _verified_targets_from_spans(
                analysis, registered, name, registry)
            verified_challenges.extend(challenges)
            verified_supports.extend(supports)
        move_targeted = _move_targeted(analysis, name, registry)
        cited_other = bool(analysis["other_citations"])
        entry: dict[str, Any] = {
            "participant": name, "phase": phase,
            "cited_claim_ids": analysis["cited_claim_ids"],
            "dead_citations": analysis["dead_citations"],
            "self_citations": analysis["self_citations"],
            "other_author_citations": analysis["other_citations"],
            "stated_moves": analysis["stated_moves"],
            "cited_other_author": cited_other,
            "move_targeted": move_targeted,
            "addressable": cited_other and move_targeted,
            "substantive_engagement": "unassessed",
            "classification": analysis["classification"],
        }
        if phase == "revision":
            entry["relationship"] = analysis["relationship"]
            entry["relationship_target"] = analysis["relationship_target"]
        interactions.append(entry)
    revision_claims = [c for c in registry.claims if c.phase == "revision"]
    unresolved_objections = compute_unresolved_objections(
        verified_challenges, registry, revision_claims)
    compute_epistemic_assessments(
        verified_challenges, verified_supports, registry)
    unclassified = [i for i in interactions
                    if i.get("classification") == "unclassified"]
    delta_report = build_delta_report(
        registry, verified_challenges,
        unclassified_interactions=unclassified)
    # Manufactured-interaction scan: no interaction may target a
    # recovered claim, and no citation may reference a derived id.
    # Both are impossible by construction (citations match C\d+),
    # but the check is explicit, not assumed.
    derived_ids = {m["derived_id"] for m in mapping}
    manufactured_flags: list[dict[str, Any]] = []
    for inter in interactions:
        for cid in inter.get("cited_claim_ids", []):
            if cid in derived_ids:
                manufactured_flags.append({
                    "participant": inter["participant"],
                    "phase": inter["phase"],
                    "cited_derived_id": cid,
                })
        if inter.get("relationship_target") in derived_ids:
            manufactured_flags.append({
                "participant": inter["participant"],
                "phase": inter["phase"],
                "relationship_target_derived_id": inter["relationship_target"],
            })
    unmatched_historical = [
        c["id"] for c in historical_claims if c["id"] not in matched_historical]
    packet = SimpleNamespace(work_item=work_item, question=question)
    artifact = build_draft_artifact_r2(
        meeting_id, packet, transcript, [], registry,
        interactions=interactions,
        unresolved_objections=unresolved_objections,
        delta_report=delta_report,
        generation_timestamps={},
    )
    artifact["derived_from_meeting_id"] = historical_meeting_id
    artifact["historical_derived_mapping"] = mapping
    recovered_sourced = sum(
        1 for o in unresolved_objections
        if o.get("source_claim_id") in derived_ids)
    if historical_objections is not None:
        historical_count = len(historical_objections)
    else:
        historical_count = len(unresolved_objections) - recovered_sourced
    artifact["objection_counts"] = {
        "historical": historical_count,
        "recovered_sourced": recovered_sourced,
        "derived": len(unresolved_objections),
    }
    artifact["retrospective_recovery_disclosure"] = (
        RETROSPECTIVE_RECOVERY_DISCLOSURE
        + f" Objections: {historical_count} historical, "
        + f"{len(unresolved_objections)} in this derived artifact "
        + f"({recovered_sourced} sourced from recovered claims).")
    artifact["recovered_claims"] = recovered
    artifact["manufactured_interaction_flags"] = manufactured_flags
    artifact["unmatched_historical_ids"] = unmatched_historical
    artifact["replay_diff"] = {
        "historical_claims": len(historical_claims),
        "historical_matched": len(matched_historical),
        "recovered_claims": len(recovered),
        "status_changed": status_changed,
    }
    return artifact
