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

import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from local_ai.build_room.artifact import build_draft_artifact
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


@dataclass(frozen=True)
class Budget:
    max_contributions: int = 1
    timeout_seconds: int = 120
    max_prompt_chars: int = 20000
    # R2: response/synthesis prompts carry the packet plus the claim
    # registry, so they get a separate, higher cap (provisional;
    # actual usage is measured in the acceptance test).
    max_response_prompt_chars: int = 40000


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
# round -> optional revision -> synthesis. The transcript stays
# append-only and verbatim; failures are recorded, never raised.
#
# Load-bearing distinctions (approved design §2 + review amendments):
# - The claim registry is MECHANICALLY derived from numbered claims
#   in contributions. No LLM extraction, ever.
# - Position grouping and disagreement identification are ATTRIBUTED,
#   model-authored annotations (the synthesizer, named) with direct
#   claim references — never objective facts, never inferred by the
#   runner. The runner groups nothing itself.
# - "Addressable" is a mechanical check (existing claim cited AND a
#   move word stated). It is NOT a genuineness score: whether the
#   reasoning is good is Joshua's judgment from the transcript.
# - The collapse rule is enforced by preservation, not by runner
#   judgment: positions and disagreements survive alongside the
#   synthesis, so invented agreement is visible.
# ---------------------------------------------------------------------------

from local_ai.build_room.artifact import build_draft_artifact_r2
from local_ai.build_room.participants import (
    SYNTHESIZER_NAME,
    Seat,
    resolve_seat_participants,
)

# Default R2 budget: 5 openings + up to 5 responses + up to 5
# revisions + 1 synthesis = max 16 generations (design §4).
R2_MAX_GENERATIONS = 16

_NUMBERED_CLAIM_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*\S)\s*$")
_CITATION_RE = re.compile(r"\b(C\d+)\b")
_STATUS_PREFIX_RE = re.compile(
    r"^(Observed|Inferred|Proposed|Speculative|Contested)\s*:\s*",
    re.IGNORECASE,
)
_RELATIONSHIP_RE = re.compile(r"\b(revised|defended|withdrawn)\b", re.IGNORECASE)

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
    "instruction only; it says nothing about what to conclude."
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
    "it; a revision may supersede it."
)

_SYNTHESIS_INSTRUCTION = (
    "Write the synthesis, labeled as synthesis (not as your own "
    "position). Under a 'Positions:' heading list the positions you "
    "identify, one per line, each with the claim IDs it groups "
    "(e.g. '- C1, C2: ...'). Under a 'Disagreements:' heading list "
    "the live tensions, one per line, each with the claim IDs in "
    "tension. Disagreements stay unresolved: you may explain a "
    "disagreement or recommend how Joshua could resolve it, but you "
    "must not resolve it, and you must not merge positions unless "
    "both participants agreed to the merge in a revision. Carry "
    "forward every unresolved disagreement without inventing "
    "agreement. Write the synthesis in English."
)


@dataclass
class Claim:
    """One mechanically registered claim (design §2A).

    ``text`` is verbatim. ``status`` is the epistemic label prefix
    when the participant wrote one, else "". ``relationship`` /
    ``relates_to`` / ``supersedes`` / ``withdraws`` describe a
    follow-up's link to earlier claims (design §2C); they are None /
    empty for openings and responses.
    """

    id: str
    participant: str
    phase: str
    text: str
    status: str = ""
    relationship: str | None = None
    relates_to: list[str] = field(default_factory=list)
    supersedes: str | None = None
    withdraws: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ClaimRegistry:
    """Append-only, mechanically derived claim list (design §2A)."""

    def __init__(self) -> None:
        self.claims: list[Claim] = []

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

        A numbered line starts a claim; following non-blank lines
        extend it until the next numbered line. Nothing here judges
        content: no extraction model, no grouping, no interpretation.
        """
        parsed: list[tuple[str, str]] = []  # (text, status)
        current: list[str] | None = None
        for line in (text or "").splitlines():
            m = _NUMBERED_CLAIM_RE.match(line)
            if m:
                if current is not None:
                    parsed.append((" ".join(current), _claim_status(current[0])))
                current = [m.group(2).strip()]
            elif line.strip() and current is not None:
                current.append(line.strip())
        if current is not None:
            parsed.append((" ".join(current), _claim_status(current[0])))
        registered: list[Claim] = []
        for claim_text, status in parsed:
            claim = Claim(
                id=f"C{len(self.claims) + 1}",
                participant=participant,
                phase=phase,
                text=claim_text,
                status=status,
                relationship=relationship,
                relates_to=list(relates_to or []),
                supersedes=supersedes,
                withdraws=withdraws,
            )
            self.claims.append(claim)
            registered.append(claim)
        return registered

    def render(self) -> str:
        lines = ["Claim registry (meeting-local IDs):"]
        for c in self.claims:
            status = f", {c.status}" if c.status else ""
            lines.append(f"{c.id} [{c.participant}{status}]: {c.text}")
        return "\n".join(lines)


def _claim_status(first_line: str) -> str:
    m = _STATUS_PREFIX_RE.match(first_line.strip())
    return m.group(1).capitalize() if m else ""


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


def _render_transcript(transcript: Transcript) -> str:
    lines = []
    for e in transcript.entries:
        lines.append(f"{e.kind} [{e.participant}]: {e.text}")
    return "\n".join(lines)


def _parse_synthesis_sections(text: str, attributed_to: str) -> tuple[list[dict], list[dict], bool]:
    """Mechanically parse the synthesizer's Positions/Disagreements lists.

    Returns (positions, disagreements, sections_found). Entries are
    attributed annotations carrying verbatim lines + claim refs; the
    runner never groups claims itself. Unparseable or absent sections
    yield empty lists, not inferred content.
    """
    positions: list[dict] = []
    disagreements: list[dict] = []
    section: str | None = None
    found = False
    for line in (text or "").splitlines():
        stripped = line.strip()
        if re.match(r"^Positions:\s*$", stripped, re.IGNORECASE):
            section = "positions"
            found = True
            continue
        if re.match(r"^Disagreements:\s*$", stripped, re.IGNORECASE):
            section = "disagreements"
            found = True
            continue
        if section == "positions" and stripped.startswith(("-", "*")):
            ids = _find_citations(stripped)
            if ids:
                positions.append({"claim_ids": ids, "attributed_to": attributed_to,
                                  "verbatim": stripped})
        elif section == "disagreements" and stripped.startswith(("-", "*")):
            ids = _find_citations(stripped)
            if ids:
                disagreements.append({"claim_ids": ids, "status": "unresolved",
                                      "attributed_to": attributed_to,
                                      "verbatim": stripped})
        elif section and stripped and not stripped.startswith(("-", "*")):
            # A non-list line outside a list item keeps the section only
            # if it looks like a continuation; otherwise close it.
            if re.match(r"^[A-Z][A-Za-z ]*:\s*$", stripped):
                section = None
    return positions, disagreements, found


def _run_phase_parallel(
    jobs: list[tuple[str, Any, str]],
    budget: Budget,
) -> list[tuple[str, str | None, str | None, float]]:
    """Run one phase's generations in parallel (design §4).

    ``jobs`` are (participant_name, participant, prompt) in stable
    order. Returns (name, text_or_None, error_or_None, completed_ts)
    IN STABLE ORDER, never completion order. One participant's
    failure never affects another's result.
    """
    if not jobs:
        return []

    def work(job: tuple[str, Any, str]) -> tuple[str, str | None, str | None, float]:
        name, participant, _prompt = job
        try:
            text = participant.generate(_prompt, timeout=budget.timeout_seconds)
            return name, text, None, time.time()
        except Exception as exc:  # recorded per participant, not raised
            return name, None, f"{type(exc).__name__}: {str(exc)[:200]}", time.time()

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
) -> MeetingResult:
    """Run one R2 meeting. Never raises for participant/generation
    failure: failures are recorded in the transcript and reflected
    in ``ok``.

    ``seats`` overrides resolution (tests inject fake participants);
    otherwise all five seats resolve under the caller's principal in
    stable SEAT_SPECS order.
    """
    budget = budget or Budget(
        max_contributions=R2_MAX_GENERATIONS,
        timeout_seconds=120,
        max_prompt_chars=20000,
        max_response_prompt_chars=40000,
    )
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    meeting_id = uuid.uuid4().hex[:12]
    transcript = Transcript()
    registry = ClaimRegistry()
    interactions: list[dict[str, Any]] = []
    generation_timestamps: dict[str, dict[str, float]] = {}
    attempts = 0

    transcript.append(
        "convene", "Reynard (convener)",
        f"Work item: {packet.work_item}\nQuestion: {packet.question}\n"
        f"Budget: max {budget.max_contributions} generations, "
        f"{budget.timeout_seconds}s per call, openings capped at "
        f"{budget.max_prompt_chars} chars, response/synthesis prompts capped at "
        f"{budget.max_response_prompt_chars} chars.")

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

    def _budget_blocked() -> str | None:
        if attempts >= budget.max_contributions:
            return (f"budget_exceeded: generation cap of "
                    f"{budget.max_contributions} reached; no generation attempted")
        return None

    def _record_phase(phase: str, results: list[tuple[str, str | None, str | None, float]],
                      frozen_ids: set[str] | None = None,
                      register: bool = True) -> list[tuple[str, str]]:
        """Append a phase's results to the transcript in stable order.

        Returns [(participant_name, contribution_text)] for generated
        contributions. ``frozen_ids`` is the registry snapshot the
        phase's prompts were built from: citations are validated
        against it, and unknown IDs become dead-citation notes.
        """
        generated: list[tuple[str, str]] = []
        generation_timestamps.setdefault(phase, {})
        for name, text, error, completed_ts in results:
            generation_timestamps[phase][name] = completed_ts
            seat = next(s for s in seats if s.name == name)
            if error is not None:
                transcript.append("failure", name, error)
                _log_usage(store, meeting_id=meeting_id, participant=name,
                           provider=seat.provider_id,
                           key_source=seat.participant.key_source,
                           operation="build_room_r2_meeting", outcome="failed",
                           phase=phase, cited_claim_ids=[],
                           token_usage="unavailable")
                continue
            transcript.append("contribution", name, text or "")
            generated.append((name, text or ""))
            cited = _find_citations(text or "")
            valid = [c for c in cited if frozen_ids is None or c in frozen_ids]
            dead = [c for c in cited if frozen_ids is not None and c not in frozen_ids]
            moves = _stated_moves(text or "")
            if dead:
                transcript.append(
                    "note", name,
                    f"Dead citation: {', '.join(dead)} cited by {name} "
                    "does not exist; it counts for nothing.")
            if register:
                registered = registry.register(name, phase, text or "")
                listing = "\n".join(
                    f"{c.id} [{c.participant}"
                    f"{', ' + c.status if c.status else ''}]: {c.text}"
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
                        "recorded with zero claims.")
            interactions.append({
                "participant": name, "phase": phase,
                "cited_claim_ids": valid, "dead_citations": dead,
                "stated_moves": moves,
                # Mechanical addressability only, NOT a genuineness
                # score: substance is Joshua's judgment.
                "addressable": bool(valid and moves),
            })
            _log_usage(store, meeting_id=meeting_id, participant=name,
                       provider=seat.provider_id,
                       key_source=seat.participant.key_source,
                       operation="build_room_r2_meeting", outcome="generated",
                       phase=phase, cited_claim_ids=valid,
                       token_usage="unavailable")
        return generated

    def _generate_jobs(phase: str, prompt: str, cap: int,
                       members: list[Seat]) -> list[tuple[str, Any, str]]:
        """Build parallel jobs, enforcing caps and the generation budget."""
        nonlocal attempts
        jobs: list[tuple[str, Any, str]] = []
        for seat in members:
            assert seat.participant is not None
            blocked = _budget_blocked()
            if blocked is not None:
                transcript.append("failure", seat.name, blocked)
                _log_usage(store, meeting_id=meeting_id, participant=seat.name,
                           provider=seat.provider_id,
                           key_source=seat.participant.key_source,
                           operation="build_room_r2_meeting",
                           outcome="failed", phase=phase,
                           cited_claim_ids=[], token_usage="unavailable")
                continue
            if len(prompt) > cap:
                transcript.append(
                    "failure", seat.name,
                    f"budget_exceeded: prompt of {len(prompt)} chars exceeds "
                    f"cap={cap} for {phase}; no generation attempted")
                _log_usage(store, meeting_id=meeting_id, participant=seat.name,
                           provider=seat.provider_id,
                           key_source=seat.participant.key_source,
                           operation="build_room_r2_meeting",
                           outcome="failed", phase=phase,
                           cited_claim_ids=[], token_usage="unavailable")
                continue
            attempts += 1
            jobs.append((seat.name, seat.participant, prompt))
        return jobs

    # -- Phase 1: independent openings (baseline control). Each
    # participant receives ONLY the packet; no other contribution.
    opening_prompt = (
        packet.render_prompt() + "\n\n" + _CLAIM_NUMBERING_INSTRUCTION
        + "\n\n" + _LANGUAGE_LINE
    )
    opening_jobs = _generate_jobs("opening", opening_prompt,
                                  budget.max_prompt_chars, present)
    opening_results = _run_phase_parallel(opening_jobs, budget)
    openings = _record_phase("opening", opening_results, frozen_ids=set())

    synthesis_failure: str | None = None
    synthesis: dict[str, Any] | None = None
    positions: list[dict] = []
    disagreements: list[dict] = []
    unresolved_objections: list[dict] = []

    if not openings:
        transcript.append(
            "failure", "Reynard (convener)",
            "no opening contributions; response, revision, and synthesis "
            "phases skipped")
        synthesis_failure = "no opening contributions; synthesis skipped"
        ok = False
    else:
        # -- Phase 2: one response round. All responders share the
        # same frozen opening registry (one cross-examination round,
        # not an open conversation).
        frozen_ids = registry.ids()
        response_prompt = (
            packet.render_prompt() + "\n\n" + _CLAIM_NUMBERING_INSTRUCTION
            + "\n\n" + registry.render()
            + "\n\n" + _RESPONSE_INSTRUCTION
            + "\n\n" + _LANGUAGE_LINE
        )
        for seat in seats:
            if seat.participant is None:
                transcript.append(
                    "note", seat.name,
                    f"{seat.name} did not respond: absent from openings.")
        response_jobs = _generate_jobs("response", response_prompt,
                                       budget.max_response_prompt_chars, present)
        response_results = _run_phase_parallel(response_jobs, budget)
        _record_phase("response", response_results, frozen_ids=frozen_ids)

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
            revision_prompt = (
                packet.render_prompt() + "\n\n" + _CLAIM_NUMBERING_INSTRUCTION
                + "\n\n" + registry.render()
                + "\n\n" + _FOLLOWUP_INSTRUCTION
                + "\n\n" + _LANGUAGE_LINE
            )
            revision_frozen = registry.ids()
            revision_jobs = _generate_jobs(
                "revision", revision_prompt,
                budget.max_response_prompt_chars, invited)
            revision_results = _run_phase_parallel(revision_jobs, budget)
            # Follow-ups register with relationship links, not plain claims.
            rev_generated: list[tuple[str, str]] = []
            generation_timestamps.setdefault("revision", {})
            for name, text, error, completed_ts in revision_results:
                generation_timestamps["revision"][name] = completed_ts
                seat = next(s for s in seats if s.name == name)
                if error is not None:
                    transcript.append("failure", name, error)
                    _log_usage(store, meeting_id=meeting_id, participant=name,
                               provider=seat.provider_id,
                               key_source=seat.participant.key_source,
                               operation="build_room_r2_meeting",
                               outcome="failed", phase="revision",
                               cited_claim_ids=[], token_usage="unavailable")
                    continue
                transcript.append("contribution", name, text or "")
                rev_generated.append((name, text or ""))
                cited = _find_citations(text or "")
                valid = [c for c in cited if c in revision_frozen]
                dead = [c for c in cited if c not in revision_frozen]
                moves = _stated_moves(text or "")
                if dead:
                    transcript.append(
                        "note", name,
                        f"Dead citation: {', '.join(dead)} cited by {name} "
                        "does not exist; it counts for nothing.")
                rel_match = _RELATIONSHIP_RE.search(text or "")
                relationship = rel_match.group(1).lower() if rel_match else "unstated"
                if relationship == "unstated":
                    transcript.append(
                        "note", name,
                        f"No relationship stated in {name}'s follow-up; "
                        "recorded as unstated.")
                own_ids = [c for c in valid
                           if registry.by_id(c) is not None
                           and registry.by_id(c).participant == name]
                supersedes = own_ids[0] if relationship == "revised" and own_ids else None
                withdraws = own_ids[0] if relationship == "withdrawn" and own_ids else None
                registered = registry.register(
                    name, "revision", text or "", relationship=relationship,
                    relates_to=valid, supersedes=supersedes, withdraws=withdraws)
                listing = "\n".join(
                    f"{c.id} [{c.participant}"
                    f"{', ' + c.status if c.status else ''}]: {c.text}"
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
                        "recorded with zero claims.")
                interactions.append({
                    "participant": name, "phase": "revision",
                    "cited_claim_ids": valid, "dead_citations": dead,
                    "stated_moves": moves,
                    "addressable": bool(valid and moves),
                    "relationship": relationship,
                })
                _log_usage(store, meeting_id=meeting_id, participant=name,
                           provider=seat.provider_id,
                           key_source=seat.participant.key_source,
                           operation="build_room_r2_meeting",
                           outcome="generated", phase="revision",
                           cited_claim_ids=valid, token_usage="unavailable")

        # Unresolved objections: objection/evidence-request citations
        # no follow-up related to.
        related: set[str] = set()
        for inter in interactions:
            if inter["phase"] == "revision":
                related.update(inter["cited_claim_ids"])
        for inter in interactions:
            if inter["phase"] != "response":
                continue
            if not any(m in _OBJECTION_MOVES for m in inter["stated_moves"]):
                continue
            for cid in inter["cited_claim_ids"]:
                if cid in related:
                    continue
                claim = registry.by_id(cid)
                if claim is None:
                    continue
                if not any(u["claim_id"] == cid for u in unresolved_objections):
                    unresolved_objections.append({
                        "claim_id": cid, "originator": claim.participant,
                        "cited_by": inter["participant"],
                        "moves": [m for m in inter["stated_moves"]
                                  if m in _OBJECTION_MOVES],
                    })

        # -- Phase 4: synthesis (test parameter: GPT, design §5).
        synth_seat = next((s for s in seats if s.name == SYNTHESIZER_NAME), None)
        if synth_seat is None or synth_seat.participant is None:
            synthesis_failure = (
                f"synthesizer {SYNTHESIZER_NAME} absent; synthesis skipped")
            transcript.append("failure", SYNTHESIZER_NAME, synthesis_failure)
            ok = False
        else:
            synthesis_prompt = (
                packet.render_prompt() + "\n\n" + registry.render()
                + "\n\nFull transcript (verbatim):\n"
                + _render_transcript(transcript)
                + "\n\n" + _SYNTHESIS_INSTRUCTION
            )
            blocked = _budget_blocked()
            if blocked is not None:
                synthesis_failure = blocked
                transcript.append("failure", SYNTHESIZER_NAME, blocked)
                synthesis = {"status": "INCOMPLETE", "text": None,
                             "reason": blocked,
                             "attributed_to": SYNTHESIZER_NAME}
                ok = False
            elif len(synthesis_prompt) > budget.max_response_prompt_chars:
                # Never silently truncate: the complete transcript is
                # preserved in the transcript file regardless, and the
                # artifact says INCOMPLETE out loud.
                synthesis_failure = (
                    f"budget_exceeded: synthesis input of "
                    f"{len(synthesis_prompt)} chars exceeds "
                    f"cap={budget.max_response_prompt_chars}; no synthesis "
                    "attempted and nothing was truncated to fit")
                transcript.append("failure", SYNTHESIZER_NAME, synthesis_failure)
                synthesis = {"status": "INCOMPLETE", "text": None,
                             "reason": synthesis_failure,
                             "attributed_to": SYNTHESIZER_NAME}
                ok = False
            else:
                attempts += 1
                try:
                    synth_text = synth_seat.participant.generate(
                        synthesis_prompt, timeout=budget.timeout_seconds)
                    generation_timestamps.setdefault("synthesis", {})[SYNTHESIZER_NAME] = time.time()
                    transcript.append("contribution", SYNTHESIZER_NAME, synth_text)
                    positions, disagreements, sections_found = _parse_synthesis_sections(
                        synth_text, SYNTHESIZER_NAME)
                    if not sections_found:
                        transcript.append(
                            "note", SYNTHESIZER_NAME,
                            "Synthesis did not list positions/disagreements in "
                            "parseable form; positions and disagreements are "
                            "empty, not inferred.")
                    synthesis = {
                        "status": "complete",
                        "text": synth_text,
                        "attributed_to": SYNTHESIZER_NAME,
                        "positions_represented": [
                            cid for p in positions for cid in p["claim_ids"]],
                        "disagreements_carried": [
                            cid for d in disagreements for cid in d["claim_ids"]],
                    }
                    _log_usage(store, meeting_id=meeting_id,
                               participant=SYNTHESIZER_NAME,
                               provider=synth_seat.provider_id,
                               key_source=synth_seat.participant.key_source,
                               operation="build_room_r2_meeting",
                               outcome="generated", phase="synthesis",
                               cited_claim_ids=synthesis["positions_represented"]
                               + synthesis["disagreements_carried"],
                               token_usage="unavailable")
                    ok = True
                except Exception as exc:  # recorded, not raised
                    synthesis_failure = f"{type(exc).__name__}: {str(exc)[:200]}"
                    transcript.append("failure", SYNTHESIZER_NAME, synthesis_failure)
                    synthesis = None
                    ok = False

    artifact = build_draft_artifact_r2(
        meeting_id, packet, transcript, seats, registry,
        interactions=interactions,
        synthesis=synthesis, synthesis_failure=synthesis_failure,
        positions=positions, disagreements=disagreements,
        unresolved_objections=unresolved_objections,
        generation_timestamps=generation_timestamps,
    )
    t_path = store / f"meeting_{meeting_id}.transcript.json"
    a_path = store / f"meeting_{meeting_id}.draft_artifact.json"
    _write_json(t_path, {"meeting_id": meeting_id, **transcript.to_dict()})
    _write_json(a_path, artifact)
    return MeetingResult(meeting_id, transcript, artifact, ok, t_path, a_path)
