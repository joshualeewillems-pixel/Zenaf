"""Prose evidence-claim audit (mandate reliability, 2026-10-28).

Pure, deterministic check of prose inspection-assertions against the
runner's tool-call log. Stdlib only; no imports from meeting.py, so
this module cannot mutate the record it reads.

The citation validator already checks parseable citations against the
generation's tool log (fail-closed). This module covers the hole beside
it: prose that asserts an inspection happened ("Read completed ...",
"I performed reads", "the request for <path> was made") without a
citation the validator can check. The audit verdicts the INSPECTION
assertion only — never the claim's content. A "verified" inspection
means the log shows the read/request happened; it says nothing about
whether the claim's conclusion is true.

Verdicts:
- ``verified`` — the log supports the asserted inspection (a returned
  read covering the path, or any logged attempt for a request/attempt
  assertion).
- ``unverified`` — the log neither supports nor contradicts the
  assertion (no matching entry and completeness not established, or
  the participant is not runner-mediated at all).
- ``contradicted`` — ONLY when the caller attests the log is complete
  for the participant's tool operations (``log_complete_participants``)
  and no matching entry exists. Absence of evidence is not evidence
  of absence: without that attestation the verdict is ``unverified``,
  never ``contradicted``.

Honest negatives are never flagged: a sentence that negates the
inspection ("No file reads have been performed", "I did not perform
any file reads") is not an assertion, and patterns require a ``/`` in
any extracted path so "I read the packet" (not a file) is ignored.

Inputs are plain dicts: claims as produced by ``Claim.to_dict()`` and
tool calls as stored in the artifact's ``tool_access.tool_calls``
(each with participant, requested_path, outcome). Outputs are plain
dicts, one finding per asserted inspection.
"""

from __future__ import annotations

import re

__all__ = [
    "audit_prose_evidence_claims",
    "render_evidence_audit",
]

# Inspection-assertion patterns. Each yields (kind, path-or-None).
# Path extraction requires a "/" so non-file objects are ignored.
_READ_COMPLETED_RE = re.compile(
    r"\bread completed\s*:?\s*`?([A-Za-z0-9_./-]*\/[A-Za-z0-9_./-]*)", re.IGNORECASE)
_PERFORMED_READS_RE = re.compile(
    r"\b(?:I|we)\s+(?:have\s+)?performed\s+(?:any\s+)?(?:file\s+)?reads?\b",
    re.IGNORECASE)
_ATTEMPTED_READ_RE = re.compile(
    r"\battempted\s+to\s+read\b[^`\n]{0,80}?`?"
    r"([A-Za-z0-9_./-]*\/[A-Za-z0-9_./-]*)",
    re.IGNORECASE)
_REQUEST_MADE_RE = re.compile(
    r"\brequest\s+for\s+`?([A-Za-z0-9_./-]*\/[A-Za-z0-9_./-]*)`?\s+was\s+made\b",
    re.IGNORECASE)
_I_READ_RE = re.compile(
    r"\bI\s+read\s+(?:the\s+file\s+at\s+)?`?([A-Za-z0-9_./-]*\/[A-Za-z0-9_./-]*)",
    re.IGNORECASE)
_NEGATION_RE = re.compile(
    r"\b(not|never|don't|doesn't|didn't|do not|does not|did not|cannot)\b",
    re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text or "") if p.strip()]


def _find_assertions(text: str) -> list[dict]:
    """Inspection assertions in a claim's text.

    Returns [{kind, path}] with kinds: read_completed, performed_reads,
    attempted_read, request_made, i_read. Negated sentences are skipped
    (an honest negative is not an assertion). Duplicates removed.
    """
    found: list[dict] = []
    seen: set[tuple[str, str | None]] = set()

    def add(kind: str, path: str | None) -> None:
        key = (kind, path)
        if key not in seen:
            seen.add(key)
            found.append({"kind": kind, "path": path})

    for sentence in _sentences(text):
        for rx, kind, has_path in (
            (_READ_COMPLETED_RE, "read_completed", True),
            (_PERFORMED_READS_RE, "performed_reads", False),
            (_ATTEMPTED_READ_RE, "attempted_read", True),
            (_REQUEST_MADE_RE, "request_made", True),
            (_I_READ_RE, "i_read", True),
        ):
            for m in rx.finditer(sentence):
                # Negation immediately before the match voids the
                # assertion ("I never performed reads"). The window
                # is deliberately narrow: a distant label ("Not
                # Inspected: ... request was made") must not void an
                # unrelated assertion later in the sentence.
                if _NEGATION_RE.search(sentence[max(0, m.start() - 16):m.start()]):
                    continue
                path = m.group(1) if has_path else None
                if path is not None:
                    path = path.strip("`.,;:") or None
                    if path is None:
                        continue
                add(kind, path)
    return found


def _path_matches(logged_path: str, asserted_path: str) -> bool:
    """True when a logged path covers the asserted path.

    Matches on the requested form or on a resolved-path suffix (the
    snapshot resolves local_ai/build_room/X to build_room/X).
    """
    if logged_path == asserted_path:
        return True
    return logged_path.endswith("/" + asserted_path) or asserted_path.endswith("/" + logged_path)


def _calls_for(calls: list[dict], participant: str) -> list[dict]:
    return [c for c in calls if c.get("participant") == participant]


def audit_prose_evidence_claims(
    claims: list[dict],
    tool_calls: list[dict],
    *,
    log_complete_participants: frozenset[str] | set[str] = frozenset(),
) -> list[dict]:
    """Audit prose inspection-assertions in claims against the log.

    ``log_complete_participants`` names the participants whose tool
    operations the log is attested complete for (runner-mediated tool
    seats with attempt logging). Only for those participants can an
    absent entry yield ``contradicted``; everyone else gets
    ``unverified`` at most. The attestation is the caller's
    responsibility and must be documented where it is made — this
    function never assumes completeness.
    """
    findings: list[dict] = []
    for claim in claims:
        assertions = _find_assertions(claim.get("text", "") or "")
        if not assertions:
            continue
        participant = claim.get("participant", "")
        calls = _calls_for(tool_calls, participant)
        complete = participant in log_complete_participants
        for assertion in assertions:
            kind = assertion["kind"]
            path = assertion["path"]
            if path is not None:
                matching = [c for c in calls
                            if _path_matches(c.get("requested_path") or "", path)
                            or _path_matches(c.get("resolved_path") or "", path)]
            else:
                matching = calls
            returned = [c for c in matching if c.get("outcome") == "returned"]
            if kind in ("request_made", "attempted_read"):
                # The assertion is about the attempt itself: any logged
                # attempt (returned, refused, capped) verifies it.
                if matching:
                    verdict, basis = "verified", (
                        f"logged {matching[0].get('outcome', 'attempt')} "
                        f"for {path}" if path else "logged tool attempt")
                elif complete:
                    verdict, basis = "contradicted", (
                        f"log complete for {participant}; "
                        f"no attempt for {path}" if path
                        else f"log complete for {participant}; no attempt")
                else:
                    verdict, basis = "unverified", (
                        f"no logged attempt for {path}" if path
                        else "no logged attempt")
            else:
                # The assertion is about a completed inspection: only a
                # returned read verifies it.
                if returned:
                    verdict, basis = "verified", (
                        f"logged returned read of {path}" if path
                        else "logged returned read")
                elif complete:
                    verdict, basis = "contradicted", (
                        f"log complete for {participant}; "
                        f"no returned read of {path}" if path
                        else f"log complete for {participant}; no returned read")
                else:
                    verdict, basis = "unverified", (
                        f"no logged returned read of {path}" if path
                        else "no logged returned read")
            findings.append({
                "claim_id": claim.get("id", ""),
                "participant": participant,
                "phase": claim.get("phase", ""),
                "assertion": kind,
                "asserted_path": path,
                "inspection_verdict": verdict,
                "basis": basis,
            })
    return findings


def render_evidence_audit(findings: list[dict]) -> str:
    """Deterministic text rendering of audit findings."""
    lines = [
        "Prose evidence audit (inspection assertions only; verdicts say "
        "nothing about claim content):"
    ]
    for f in findings:
        path = f" {f['asserted_path']}" if f.get("asserted_path") else ""
        lines.append(
            f"{f['claim_id']} [{f['participant']}, {f['assertion']}{path}]: "
            f"{f['inspection_verdict']} ({f['basis']})")
    return "\n".join(lines)
