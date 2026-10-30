"""Moneyball role-only comparison: fixed six-meeting program definition.

This module pins the experiment program that the owner-only program-run
endpoint executes. It never generates, never spends, and never runs a
meeting on its own: it only defines WHAT runs (three frozen packets x
two conditions, A-then-B per packet, sequential) so the endpoint can
invoke ``run_program`` with exactly that program.

Packet pinning. The three packets are the exact request bodies submitted
for the original meetings, vendored byte-identical under
``moneyball_packets/`` (SHA-256 recorded below and asserted by tests):
- m2:    M2 steward-E scope (series M2 request body)
- audit: Weaver encounter architecture audit evaluation request body
- spec:  adapter/referral spec review request body
The packet markdown files carry the same request bodies embedded (verified:
parsed embedded JSON == vendored JSON for M2 and SPEC); the audit packet
has no embedded block, and its request file is the submitted body.
A and B within a pair share the SAME EvidencePacket object, so the Phase 1
base prompts are byte-identical by construction (the room's
comparison_capture hash assert verifies this at runtime).

Estimates are PLANNING figures from the corrected plan doc section 6
(audit/estimate doc method), used only for the runner's reserve-or-stop
decision. They are never passed to admission and never enforced.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from local_ai.build_room.meeting import EvidencePacket
from local_ai.build_room.program_runner import MeetingSpec
from local_ai.build_room.role_briefs import (
    ROLE_BRIEF_VERSION,
    role_prompt_extras,
)

PACKET_DIR = Path(__file__).resolve().parent / "moneyball_packets"

# (packet key, vendored file, estimated reservation USD, expected work item)
# Order is the program order; estimates from the corrected plan doc section 6.
PACKETS: tuple[tuple[str, str, float, str], ...] = (
    (
        "m2",
        "m2.json",
        0.224,
        "Build-Council Room series M2 — steward increment E scope",
    ),
    (
        "audit",
        "audit.json",
        0.255,
        "Zenaf build-council — Weaver encounter architecture audit evaluation (single meeting, packet-only)",
    ),
    (
        "spec",
        "spec.json",
        0.241,
        "Build-Council Room — adapter/referral spec review",
    ),
)

# SHA-256 of each vendored file, recorded at vendoring time. Tests assert
# the files still match: any edit to a packet file fails loudly instead of
# silently changing the experiment's input.
PACKET_SHA256: dict[str, str] = {
    "m2": "bfc78867282f871b6ce4354d75a9b21287677f9634ae62ac66c9e8f23c805ed2",
    "audit": "7d3ce8a2da21ee2510e9a8382933ae21a94cad95c9765eaa07ffda1a4aa0dd90",
    "spec": "bd399742d5ff968d9a9d36af4ae1f7e40e85ecf6bd05ca66c3284c0fa15179d6",
}

PROGRAM_MEETING_COUNT = 6


def _str_list(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"packet field {field!r} must be a list of strings")
    return tuple(value)


def load_packet_file(path: Path | str) -> EvidencePacket:
    """Load one vendored request body as a frozen EvidencePacket.

    Only the EvidencePacket fields are read; anything else in the file
    (e.g. the audit body's ``tools_enabled``/``nominated_paths``) is
    ignored, because the experiment runs tools OFF by spec. Raises
    ValueError on any malformed content: a bad packet fails at program
    construction, never mid-program.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"packet file {path} is not a JSON object")
    work_item = raw.get("work_item", "")
    question = raw.get("question", "")
    if not isinstance(work_item, str) or not work_item.strip():
        raise ValueError(f"packet file {path} has no work_item")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"packet file {path} has no question")
    return EvidencePacket(
        work_item=work_item,
        question=question,
        excerpts=_str_list(raw.get("excerpts"), "excerpts"),
        constraints=_str_list(raw.get("constraints"), "constraints"),
        source_refs=_str_list(raw.get("source_refs"), "source_refs"),
        context=_str_list(raw.get("context"), "context"),
    )


def load_program_packets(packet_dir: Path | str | None = None) -> dict[str, EvidencePacket]:
    """Load all three frozen packets, verifying hashes and work items.

    Hash verification runs on every load: the endpoint builds specs
    synchronously at POST time, so a corrupted or edited packet file
    refuses the start instead of running a changed experiment.
    """
    directory = Path(packet_dir) if packet_dir is not None else PACKET_DIR
    packets: dict[str, EvidencePacket] = {}
    for key, filename, _estimate, expected_work_item_prefix in PACKETS:
        path = directory / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != PACKET_SHA256[key]:
            raise ValueError(
                f"packet file {filename} hash mismatch: vendored bytes changed; "
                "refusing to run a changed experiment"
            )
        packet = load_packet_file(path)
        if not packet.work_item.startswith(expected_work_item_prefix):
            raise ValueError(
                f"packet file {filename} work_item mismatch: expected prefix "
                f"{expected_work_item_prefix!r}, got {packet.work_item[:80]!r}"
            )
        packets[key] = packet
    return packets


def build_program_specs(
    principal: Any,
    packet_dir: Path | str | None = None,
) -> list[MeetingSpec]:
    """Build the fixed six-meeting program, A-then-B per packet.

    A and B within a pair share the SAME EvidencePacket object (byte
    identity, not just equality), so only the Condition B extras differ.
    Tools are OFF (MeetingSpec default); seats default to SEAT_SPECS
    (MeetingSpec default); the caller principal is set on every spec so
    spend follows the caller, exactly like the existing routes.
    """
    packets = load_program_packets(packet_dir)
    briefs = role_prompt_extras()
    specs: list[MeetingSpec] = []
    for key, _filename, estimate, _work_item in PACKETS:
        packet = packets[key]
        specs.append(
            MeetingSpec(
                packet=packet,
                condition="A",
                estimated_reservation_usd=estimate,
                principal=principal,
            )
        )
        specs.append(
            MeetingSpec(
                packet=packet,
                condition="B",
                estimated_reservation_usd=estimate,
                principal=principal,
                role_prompt_extras=dict(briefs),
                role_brief_version=ROLE_BRIEF_VERSION,
            )
        )
    return specs


def program_plan() -> list[dict[str, str]]:
    """The six planned meetings (packet work item + condition), for status.

    Work-item titles only — no packet content, no keys.
    """
    packets = load_program_packets()
    plan: list[dict[str, str]] = []
    for key, _filename, _estimate, _work_item in PACKETS:
        plan.append({"packet": packets[key].work_item, "condition": "A"})
        plan.append({"packet": packets[key].work_item, "condition": "B"})
    return plan


class ProgramRunTracker:
    """In-process record of one program run's liveness.

    This tracks ONLY whether a run thread is alive and how it finished.
    It holds no money accounting: the persistent ProgramLedger is the
    sole source of truth for cumulative reservations and completed
    meetings, and status reads that ledger from disk. After a server
    restart this tracker is empty by design; status then derives state
    from the ledger alone (completed / interrupted / not started).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, Any] | None = None
        self._last: dict[str, Any] | None = None

    def try_start(self, run_id: str) -> bool:
        """Claim the active slot. False if a run thread is already live."""
        with self._lock:
            if self._active is not None:
                return False
            self._active = {
                "run_id": run_id,
                "state": "running",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "finished_at": None,
                "result_status": None,
                "reason": None,
                "error": None,
            }
            return True

    def finish(
        self,
        *,
        result_status: str | None = None,
        reason: str | None = None,
        error: str | None = None,
    ) -> None:
        """Release the active slot, keeping the outcome as the last record."""
        with self._lock:
            if self._active is None:
                return
            record = dict(self._active)
            record["state"] = "finished"
            record["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            record["result_status"] = result_status
            record["reason"] = reason
            record["error"] = error
            self._active = None
            self._last = record

    def snapshot(self) -> dict[str, Any] | None:
        """The active record if a run is live, else the last finished one."""
        with self._lock:
            if self._active is not None:
                return dict(self._active)
            return dict(self._last) if self._last is not None else None

    def is_active(self) -> bool:
        with self._lock:
            return self._active is not None

    def reset(self) -> None:
        """Clear all records. Refuses while a run is live (never hide one)."""
        with self._lock:
            if self._active is not None:
                raise RuntimeError("cannot reset while a program run is active")
            self._last = None


PROGRAM_TRACKER = ProgramRunTracker()


def new_run_id() -> str:
    return uuid.uuid4().hex
