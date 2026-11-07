"""Upload rapid-fire S1 — the extraction job (brief §§3, 4, 5).

One job per (document, document_version, lens-set) extracts the
document's evidence (Layer 1: spans + observations) and
interpretations (Layer 2) from the stored redacted text. The job
never creates outcomes, never writes VE records, never trains.

Reliability (addendum A4, brief §3): sequential within a job,
global extraction-concurrency bound 1 (one shared semaphore — the
same instance the distill path takes, §3.5), atomic claim with a
lease, heartbeat + 240s stale threshold, a startup reconciler that
marks dead jobs 'interrupted' (never resumes them mid-call), and
resume as a new job over the same version, missing chunks only.

Per-chunk pipeline (A5.2, §3.6): for each chunk, the evidence call
then the interpretation call(s) over that chunk's rows, committed
per chunk — so the first interpretation commits after the first
chunk's calls (P5, N=1). The call budget is unchanged: <=12
evidence calls + <=4 interpretation calls per lens per job.

Interpretation batching (brief-gap resolution, surfaced in the PR
body — the brief's "one per lens per chunk-batch" names no batch
rule, and per-chunk interpretation calls cannot hold for a 12-chunk
document under the 4-call cap): the first call covers chunk 1
alone (P5); the remaining chunks split into at most 3 further
contiguous batches. Every chunk is interpreted within the cap; the
rule is deterministic and lives in one place
(interpretation_batches).

Log rule (reconciliation §9, binding): the job logs counts,
character counts, failure codes, and durations only — never span
text, never observation text, never prompt text, never model-output
excerpts. Tests assert it (T51).

No live behavior is claimed by this module's tests: they use
injected complete_fn/probe_fn stubs returning canned JSON. S0's
evaluation approval is required before the first real run (§0).
"""

from __future__ import annotations

import json
import logging
import os
import re
import resource
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from local_ai.config import OLLAMA_MODEL, OLLAMA_URL
from local_ai.conversation.store import ConversationStore, _upload_job_dict

logger = logging.getLogger(__name__)

# -- budgets + constants (brief §3) ------------------------------------------

#: Stale threshold (A4.1): longest single-call timeout (180s) + 60s
#: margin. A running job with no heartbeat for this long is presumed
#: interrupted, never presumed complete.
JOB_HEARTBEAT_STALE_S = 240

#: Lease length (A4.4): one call timeout + margin, renewed by each
#: heartbeat. Either the lease or the heartbeat expiring alone does
#: not reassign the job — both must be stale first.
_JOB_LEASE_S = 240

#: Per-call output cap (U-8 owns the benchmark value; if U-8 changes
#: it, this constant changes with it, one line).
UPLOAD_MAX_INTERPRETATIONS_PER_CALL = 30

#: Per-call model timeout (distill.py:45 precedent).
_MODEL_TIMEOUT_S = 180

#: Chunker: 4000-char chunks at paragraph boundaries, oversized
#: paragraphs split by sentence (rev2 §4.2).
_CHUNK_CHARS = 4000

#: Chunk cap (reconciliation §5(c)): a document over 12 chunks
#: extracts its first 12 and records the remainder as unextracted
#: (the offer states the coverage, §11.3).
_MAX_CHUNKS = 12

#: Call budget (reconciliation §5(b)): <=12 evidence calls + <=4
#: interpretation calls per lens per job.
_MAX_EVIDENCE_CALLS = 12
_MAX_INTERPRETATION_CALLS_PER_LENS = 4

#: Failure codes (wash-contract codes, §3.6).
FAILURE_CODES = (
    "unreachable",
    "timeout",
    "invalid_output",
    "overloaded",
    "model_missing",
    "interrupted",
)

# -- global model-call concurrency (A4.5, §3.5) ------------------------------
#
# ONE concurrent extraction-model call, system-wide. The semaphore
# is one instance, shared by the upload worker (below) and the
# distill path (local_ai/presence_ingest/distill.py takes it around
# each batch call) — two independently instantiated Semaphore(1)
# objects would enforce nothing. The bound covers EXTRACTION calls
# only; build-room meetings are out of scope. In-process only: the
# app runs as one process on Fly today; if it ever runs
# multi-process, the bound becomes a DB lease (a future design).
# ZENAF_EXTRACTION_CONCURRENCY is the seam (default 1).

_EXTRACTION_CONCURRENCY = max(
    1, int(os.environ.get("ZENAF_EXTRACTION_CONCURRENCY", "1") or 1)
)
EXTRACTION_MODEL_SEMAPHORE = threading.Semaphore(_EXTRACTION_CONCURRENCY)


class UploadModelError(Exception):
    """A model call failed, with its wash-contract failure code."""

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in FAILURE_CODES:
            raise ValueError(f"Unknown failure code: {code!r}")
        super().__init__(detail or code)
        self.code = code


class UploadExtractionError(Exception):
    """The job cannot proceed (unresolvable source, bad record)."""


# -- prompts (§3.7) -----------------------------------------------------------
#
# Jurisdictional criteria are prompt text, not code branches. The
# evidence prompt is lens-blind; the interpretation prompt carries
# the lens's criteria (reconciliation §3.1). The Maverick prompt
# carries the creative-transformation instruction (M1 reuse + M2
# boundary) as the C2 generative default ("make something of what
# they brought"), not a question-led default.

EVIDENCE_PROMPT_TEMPLATE = """You are reading one chunk of a document the user uploaded for
interpretation. Return ONLY a JSON object (no other text) with this
shape:
{"spans": [{"text": "<exact substring of the chunk>"}], "observations": [{"claim": "<a claim about the document, in your own words>", "spans": ["<exact span text it rests on>", ...]}]}

Rules, all binding:
- Every span "text" MUST be an exact substring of the chunk text
  below, copied verbatim. Never invent or paraphrase a span.
- An observation's "claim" must be IN YOUR OWN WORDS about the
  document — never a quotation of its span. A claim that repeats a
  span's words is not a claim.
- Cite every observation's spans by their exact text.
- At most 30 spans and 30 observations. Empty lists are allowed
  when the chunk holds nothing worth keeping.

CHUNK:
"""

INTERPRETATION_PROMPT_TEMPLATE = """You are reading {lens_label} over evidence drawn from a document
the user uploaded. Return ONLY a JSON object (no other text) with
this shape:
{"interpretations": [{"text": "<your reading, in your own words>", "spans": [{"text": "<exact span text it rests on>", "role": "primary|supporting|contrast"}], "observations": ["<exact observation claim it rests on>", ...], "proposed_outcome": "project|task|idea|null", "is_transformation": false}]}

Rules, all binding:
- {lens_criteria}
- An interpretation rests on its cited spans and observations:
  cite them by their exact text. A transformation (a making, not
  a claim — is_transformation true) cites its spans directly and
  carries no observations; a transformation with no cited span is
  rejected.
- "proposed_outcome" names what this reading proposes (project,
  task, idea) or null when it proposes nothing.
- At most {max_interpretations} interpretations.

EVIDENCE:
"""

#: Lens criteria, as prompt text (reconciliation §3.1; Gardener
#: G1–G3, Maverick M1+M2, Logic, Heart). Seat lenses take the
#: seat's own criteria; unknown lenses fall back to the plain
#: reading instruction.
_LENS_CRITERIA = {
    "heart": (
        "Read for what matters: what the document cares about, "
        "what it holds dear, what it would protect."
    ),
    "hands": (
        "Read for what is made: what was built, how it was built, "
        "what the making reveals."
    ),
    "logic": (
        "Read for distinctions and structure: what follows from "
        "what, where the reasoning holds and where it slips."
    ),
    "voice": (
        "Read for expression: how the document says what it says, "
        "and what the saying itself reveals."
    ),
    "ear": (
        "Read for rhythm and resonance: what repeats, what echoes, "
        "what the document listens to."
    ),
    "compass": (
        "Read for direction: what the document aspires to, what it "
        "takes as true, where it points."
    ),
    "eye": (
        "Read for what is beautiful: what the document finds worth "
        "looking at, and why."
    ),
    "maverick": (
        "Make something of what they brought — a metaphor, a story, "
        "a reframed image, a completed creative thought — and ask a "
        "question only when a question is honestly the contribution. "
        "Reuse the passage's material in a new form; keep the "
        "fact/fiction boundary: what you imagine from their material "
        "is yours, not theirs — never present an invention as their "
        "words, a fact about them, or a read-back."
    ),
    "mentor": (
        "Offer knowledge, interpretations, distinctions, and "
        "guidance freely when useful. Do not substitute your "
        "judgment for the visitor's where the judgment is theirs to "
        "make. Teach by creating the conditions for insight: name "
        "patterns, offer distinctions, recognize what is growing."
    ),
}

_LENS_LABELS = {
    "heart": "the Heart strand",
    "hands": "the Hands strand",
    "logic": "the Logic strand",
    "voice": "the Voice strand",
    "ear": "the Ear strand",
    "compass": "the Compass strand",
    "eye": "the Eye strand",
    "maverick": "the Maverick (Fox)",
    "mentor": "the Gardener (Mentor)",
}


def _lens_label(lens: str, lens_kind: str) -> str:
    if lens_kind == "seat":
        return _LENS_LABELS.get(lens, f"the {lens} seat")
    return _LENS_LABELS.get(lens, f"the {lens} strand")


def _lens_criteria(lens: str, lens_kind: str) -> str:
    criteria = _LENS_CRITERIA.get(lens)
    if criteria:
        return criteria
    return (
        "Read plainly: what does this evidence say, and what does "
        "it mean for the user?"
    )


# -- chunker (§3.6) -----------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


def chunk_upload_text(text: str) -> tuple[list[dict[str, Any]], int]:
    """Deterministic chunking: 4000-char chunks at paragraph
    boundaries, oversized paragraphs split by sentence (the
    segment_notes_for_evidence shape). Same stored text + same
    parameters -> same segments, same ids (seg-0000, seg-0001, ...).

    Returns (chunks, total_chunks): chunks is capped at 12 — a
    document over 12 chunks extracts its first 12 and records the
    remainder as unextracted (the offer states the coverage).
    """
    paragraphs = [p for p in (text or "").split("\n\n") if p.strip()]
    segments: list[str] = []
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if len(paragraph) > _CHUNK_CHARS:
            # Oversized paragraph: flush the current chunk, then
            # split the paragraph by sentence.
            if current:
                segments.append(current)
                current = ""
            for sentence in _SENTENCE_SPLIT_RE.split(paragraph):
                sentence = sentence.strip()
                if not sentence:
                    continue
                if len(sentence) > _CHUNK_CHARS:
                    # One sentence still too long: hard-split it.
                    for i in range(0, len(sentence), _CHUNK_CHARS):
                        segments.append(sentence[i : i + _CHUNK_CHARS])
                elif current and len(current) + 1 + len(sentence) > _CHUNK_CHARS:
                    segments.append(current)
                    current = sentence
                else:
                    current = f"{current} {sentence}".strip() if current else sentence
            continue
        if current and len(current) + 2 + len(paragraph) > _CHUNK_CHARS:
            segments.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip() if current else paragraph
    if current:
        segments.append(current)
    total = len(segments)
    chunks = [
        {"segment_id": f"seg-{i:04d}", "text": segment}
        for i, segment in enumerate(segments[:_MAX_CHUNKS])
    ]
    return chunks, total


def interpretation_batches(chunk_count: int) -> list[list[int]]:
    """Deterministic interpretation batching (see the module
    docstring): the first call covers chunk 0 alone (P5 — the first
    interpretation commits after the first chunk); the remaining
    chunks split into at most 3 further contiguous batches. Total
    calls per lens per job: <= 4. Returns chunk-index groups."""
    if chunk_count <= 0:
        return []
    if chunk_count == 1:
        return [[0]]
    remaining = list(range(1, chunk_count))
    size = -(-len(remaining) // 3)  # ceil division
    groups = [
        remaining[i : i + size] for i in range(0, len(remaining), size)
    ]
    return [[0]] + groups[:3]


def chunk_index_for_offset(
    chunks: list[dict[str, Any]], offset: int
) -> int | None:
    """Which chunk holds a character offset into the joined stored
    text (chunks joined with "\\n\\n", the chunker's shape)."""
    pos = 0
    for i, chunk in enumerate(chunks):
        text = chunk["text"]
        if pos <= offset < pos + len(text):
            return i
        pos += len(text) + 2
    return None


# -- model calls --------------------------------------------------------------


def probe_ollama(url: str | None = None, timeout: float = 5.0) -> bool:
    """Liveness probe for the configured Ollama instance: GET the
    tags endpoint derived from OLLAMA_URL. Any HTTP response means
    reachable (even an error status — the server is up); a
    connection error or timeout means unreachable. Used before the
    worker's first call (§3.7)."""
    target = url or OLLAMA_URL
    try:
        parsed = urllib.parse.urlparse(target)
        tags = urllib.parse.urlunparse(parsed._replace(path="/api/tags"))
        req = urllib.request.Request(tags, method="GET")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _ollama_complete(prompt: str, *, timeout: float = _MODEL_TIMEOUT_S) -> str:
    """Call the local Ollama instance (the distill._default_complete
    shape: same URL, model, temperature). Raises UploadModelError
    with its wash-contract code — never a silent degradation."""
    body = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 502, 503, 504):
            raise UploadModelError(
                "overloaded", f"Ollama returned HTTP {exc.code}"
            ) from exc
        raise UploadModelError(
            "unreachable", f"Ollama returned HTTP {exc.code}"
        ) from exc
    except TimeoutError as exc:
        raise UploadModelError("timeout", "Ollama call timed out") from exc
    except urllib.error.URLError as exc:
        raise UploadModelError("unreachable", f"Ollama unreachable: {exc}") from exc
    except Exception as exc:
        raise UploadModelError("invalid_output", f"Bad Ollama response: {exc}") from exc
    text = (payload.get("response") or "").strip()
    if not text:
        raise UploadModelError("invalid_output", "Ollama returned no text")
    return text


def _parse_model_json(raw: str) -> dict[str, Any]:
    """Parse a model JSON response, tolerating markdown fences.
    Raises UploadModelError('invalid_output') on anything else."""
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except Exception as exc:
        raise UploadModelError("invalid_output", f"Unparseable model JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise UploadModelError("invalid_output", "Model JSON is not an object")
    return parsed


def _run_model_call(
    prompt: str,
    complete_fn: Callable[[str], str] | None,
    *,
    timeout: float = _MODEL_TIMEOUT_S,
) -> str:
    """One model call, under the shared extraction semaphore (§3.5).
    A stub complete_fn (tests) is called in place of Ollama; its
    exceptions are mapped to UploadModelError codes."""
    with EXTRACTION_MODEL_SEMAPHORE:
        if complete_fn is not None:
            try:
                return complete_fn(prompt)
            except UploadModelError:
                raise
            except Exception as exc:
                raise UploadModelError(
                    "invalid_output", f"Stub model call failed: {exc}"
                ) from exc
        return _ollama_complete(prompt, timeout=timeout)


# -- source resolution --------------------------------------------------------

def resolve_upload_source_text(
    store: ConversationStore, user_id: str, document_id: str
) -> tuple[str, str, str] | None:
    """Resolve a document's stored redacted text: (text, kind,
    redaction_stage). Paste: the stored full text (U-2), falling
    back honestly to the 2000-char excerpt when only it exists.
    File: the linked ingest session's redacted events, joined.
    None when the source is missing, foreign, or has no text —
    the extract route fails closed on it."""
    source = store.get_strand_source(user_id, document_id)
    if source is None:
        return None
    if source.get("kind") == "paste":
        full = store.get_paste_full_text(document_id)
        if full:
            return full, "paste-full", "redacted"
        excerpt = (source.get("excerpt_redacted") or "").strip()
        if excerpt:
            return excerpt, "paste-excerpt", "redacted"
        return None
    if source.get("kind") == "file":
        try:
            from local_ai.presence_ingest.store import PresenceStore

            events = PresenceStore().list_events(str(source.get("ref") or ""))
        except Exception:
            return None
        texts = [
            (getattr(e, "text", "") or "").strip()
            for e in events
        ]
        joined = "\n\n".join(t for t in texts if t)
        if not joined:
            return None
        return joined, "file", "redacted"
    return None


# -- P1–P5 measurement (§3.8) -------------------------------------------------

def measure_job_row(job: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    """P1–P5 from a job row + its call rows (pure: no store reads).
    All values are numbers (counts / durations) — the log rule
    allows them; no text is carried."""
    created = _parse_iso(job.get("created_at"))
    first = _parse_iso(job.get("first_interpretation_at"))
    p1_ms = None
    if created is not None and first is not None:
        p1_ms = int((first - created).total_seconds() * 1000)
    durations: dict[str, list[int]] = {"evidence": [], "interpretation": []}
    for call in calls:
        kind = call.get("call_kind")
        ms = call.get("duration_ms")
        if kind in durations and isinstance(ms, int):
            durations[kind].append(ms)
    p2 = {
        kind: _percentiles(sorted(values))
        for kind, values in durations.items()
    }
    try:
        p3_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        p3_kb = None
    wall_ms = None
    if created is not None:
        updated = _parse_iso(job.get("updated_at"))
        if updated is not None:
            wall_ms = int((updated - created).total_seconds() * 1000)
    p4_per_hour = None
    if wall_ms:
        p4_per_hour = round(3600_000 / wall_ms, 2)
    return {
        "p1_first_interpretation_ms": p1_ms,
        "p2_latency_ms": p2,
        "p3_peak_rss_kb": p3_kb,
        "p4_docs_per_hour": p4_per_hour,
        "p4_wall_ms": wall_ms,
        "p5_useful_first_result_n": 1,
    }


def _percentiles(sorted_values: list[int]) -> dict[str, int | None]:
    if not sorted_values:
        return {"p50": None, "p95": None}

    def pick(q: float) -> int:
        idx = min(len(sorted_values) - 1, max(0, int(q * len(sorted_values))))
        return sorted_values[idx]

    return {"p50": pick(0.5), "p95": pick(0.95)}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

# -- the worker ---------------------------------------------------------------

def _evidence_prompt(chunk_text: str) -> str:
    return EVIDENCE_PROMPT_TEMPLATE + chunk_text


def _interpretation_prompt(
    lens: str,
    lens_kind: str,
    evidence_text: str,
) -> str:
    # Plain replacement, NOT .format(): the template's JSON example
    # carries literal braces that .format() would read as fields.
    return (
        INTERPRETATION_PROMPT_TEMPLATE.replace(
            "{lens_label}", _lens_label(lens, lens_kind)
        )
        .replace("{lens_criteria}", _lens_criteria(lens, lens_kind))
        .replace(
            "{max_interpretations}",
            str(UPLOAD_MAX_INTERPRETATIONS_PER_CALL),
        )
        + evidence_text
    )


def _resolve_span_in_chunk(
    span_text: str, chunk_text: str, segment_id: str
) -> tuple[str, str] | None:
    """Resolve a model-returned span to (span_text, location) by
    exact substring in the chunk text (first occurrence — a repeated
    phrase is recorded at its first occurrence, deterministically).
    None when the text is not an exact substring: the span is
    dropped, never invented."""
    text = (span_text or "").strip()
    if not text:
        return None
    start = chunk_text.find(text)
    if start < 0:
        return None
    return text, f"{segment_id}:{start}-{start + len(text)}"


def run_upload_extraction_job(
    store: ConversationStore,
    job_id: str,
    *,
    complete_fn: Callable[[str], str] | None = None,
    probe_fn: Callable[[], bool] | None = None,
    source_text_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run one extraction job to completion (or partial / failed).
    Called on a daemon thread; the job row + call table are the
    durable record. Returns the final job row.

    - Claims the job atomically (a lost race returns the job as-is).
    - Probes Ollama before the first call; unreachable -> the job
      fails with code 'model_missing' and a plain message, never a
      silent degradation to clause recovery.
    - Processes chunks in order (missing chunks only on a resume);
      per chunk, the evidence call then the interpretation call(s)
      over that chunk's rows, committed per chunk (P5).
    - Checks for cancellation between calls; completed chunks are
      preserved.
    - Logs counts, codes, and durations only (never text).
    """
    job = _get_job_by_id(store, job_id)
    if job is None:
        raise UploadExtractionError(f"Job not found: {job_id!r}")
    user_id = job["user_id"]
    if job["state"] not in ("queued", "running"):
        return job
    worker_id = f"{os.getpid()}:{threading.current_thread().name}"
    now = datetime.now(timezone.utc).isoformat()
    lease_until = (
        datetime.now(timezone.utc) + timedelta(seconds=_JOB_LEASE_S)
    ).isoformat()
    if job["state"] == "queued":
        if not store.claim_upload_job(job_id, worker_id, now, lease_until):
            return store.get_upload_job(user_id, job_id) or job
        job = store.get_upload_job(user_id, job_id) or job

    document_id = job["document_id"]
    document_version = job["document_version"]
    try:
        return _run_claimed_job(
            store, job, complete_fn=complete_fn, probe_fn=probe_fn,
            source_text_fn=source_text_fn,
        )
    except Exception:
        # A worker bug must never leave a job 'running' forever with
        # a fresh heartbeat: mark it failed (the reconciler's 240s
        # backstop would catch it anyway) and log the failure type
        # only — never the text that was being processed.
        logger.exception("upload extraction: job %s failed", job_id)
        try:
            store.set_upload_job_state(job_id, "failed")
        except Exception:
            pass
        return store.get_upload_job(user_id, job_id) or job


def _get_job_by_id(
    store: ConversationStore, job_id: str
) -> dict[str, Any] | None:
    """A job row by id alone (the worker's entry read — the route
    already owner-scoped the accept, and every later read is
    owner-scoped by the row's own user_id)."""
    with store._lock:
        row = store._conn.execute(
            "SELECT job_id, user_id, document_id, document_version, state, "
            "worker_id, last_heartbeat_at, lease_until, "
            "first_interpretation_at, total_calls, completed_calls, "
            "failed_calls, failed_chunks, created_at, updated_at "
            "FROM upload_extraction_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    return _upload_job_dict(row)


def _run_claimed_job(
    store: ConversationStore,
    job: dict[str, Any],
    *,
    complete_fn: Callable[[str], str] | None,
    probe_fn: Callable[[], bool] | None,
    source_text_fn: Callable[..., Any] | None,
) -> dict[str, Any]:
    user_id = job["user_id"]
    job_id = job["job_id"]
    document_id = job["document_id"]
    document_version = job["document_version"]
    failed_chunks: list[int] = list(job.get("failed_chunks") or [])
    first_interpretation_at = job.get("first_interpretation_at")

    def heartbeat() -> None:
        now = datetime.now(timezone.utc).isoformat()
        lease = (
            datetime.now(timezone.utc) + timedelta(seconds=_JOB_LEASE_S)
        ).isoformat()
        store.heartbeat_upload_job(job_id, now, lease)

    def cancelled() -> bool:
        current = store.get_upload_job(user_id, job_id)
        return current is not None and current.get("state") == "cancelled"

    # Resolve the stored source text (injected in tests).
    if source_text_fn is not None:
        resolved = source_text_fn(store, user_id, document_id)
    else:
        resolved = resolve_upload_source_text(store, user_id, document_id)
    if resolved is None:
        store.set_upload_job_state(job_id, "failed")
        logger.info(
            "upload extraction: job %s failed (source unresolvable)", job_id
        )
        return store.get_upload_job(user_id, job_id) or job
    stored_text, source_kind, redaction_stage = resolved
    source = store.get_strand_source(user_id, document_id)
    lens = (source or {}).get("strand_key") or "heart"
    lens_kind = "strand"
    chunks, total_chunks = chunk_upload_text(stored_text)
    logger.info(
        "upload extraction: job %s started (document_chars=%d, chunks=%d, total=%d, kind=%s)",
        job_id, len(stored_text), len(chunks), total_chunks, source_kind,
    )

    # Probe before the first call (§3.7): unreachable -> fail closed.
    reachable = probe_fn() if probe_fn is not None else probe_ollama()
    if not reachable:
        call = store.start_upload_job_call(job_id, None, "evidence")
        store.complete_upload_call(
            call["call_id"], state="failed", code="model_missing"
        )
        store.set_upload_job_state(job_id, "failed")
        logger.info(
            "upload extraction: job %s failed (model_missing)", job_id
        )
        return store.get_upload_job(user_id, job_id) or job

    # Resume: chunks whose evidence already committed in this version
    # are skipped; interpretation still runs for chunks whose rows
    # were never interpreted.
    existing_spans = store.list_upload_spans(user_id, document_id, document_version)
    extracted_segments = {s["segment_id"] for s in existing_spans}
    missing = [
        i for i, c in enumerate(chunks) if c["segment_id"] not in extracted_segments
    ]
    # Evidence phase: missing chunks only, in order.
    for chunk_index in missing:
        if cancelled():
            break
        chunk = chunks[chunk_index]
        call = store.start_upload_job_call(job_id, chunk_index, "evidence")
        try:
            raw = _run_model_call(
                _evidence_prompt(chunk["text"]), complete_fn
            )
            parsed = _parse_model_json(raw)
            written, dropped = _write_evidence_chunk(
                store, user_id, document_id, document_version, chunk, parsed,
                redaction_stage,
            )
            store.complete_upload_call(
                call["call_id"], state="complete", rows_written=written
            )
            if written == 0:
                failed_chunks.append(chunk_index)
                logger.info(
                    "upload extraction: job %s chunk %d evidence wrote 0 rows "
                    "(dropped=%d)",
                    job_id, chunk_index, dropped,
                )
            heartbeat()
        except UploadModelError as exc:
            store.complete_upload_call(
                call["call_id"], state="failed", code=exc.code
            )
            failed_chunks.append(chunk_index)
            logger.info(
                "upload extraction: job %s chunk %d evidence failed (%s)",
                job_id, chunk_index, exc.code,
            )
            heartbeat()
        except Exception:
            store.complete_upload_call(
                call["call_id"], state="failed", code="invalid_output"
            )
            failed_chunks.append(chunk_index)
            logger.exception(
                "upload extraction: job %s chunk %d evidence errored",
                job_id, chunk_index,
            )
            heartbeat()

    # Interpretation phase: chunks that have evidence but no citing
    # interpretation yet (this run's chunks, plus any stranded by an
    # earlier interrupted job). Batches: first chunk alone (P5),
    # the rest in at most 3 groups — <=4 calls per lens per job.
    if not cancelled():
        targets = _chunks_needing_interpretation(
            store, user_id, document_id, document_version, chunks
        )
        groups = interpretation_batches(len(targets))
        for group_positions in groups:
            if cancelled():
                break
            batch_indexes = [targets[p] for p in group_positions]
            call = store.start_upload_job_call(job_id, None, "interpretation")
            try:
                evidence_text, span_lookup, obs_lookup = _batch_evidence(
                    store, user_id, document_id, document_version,
                    [chunks[i] for i in batch_indexes],
                )
                raw = _run_model_call(
                    _interpretation_prompt(lens, lens_kind, evidence_text),
                    complete_fn,
                )
                parsed = _parse_model_json(raw)
                written = _write_interpretation_batch(
                    store, user_id, document_id, document_version, lens,
                    lens_kind, parsed, span_lookup, obs_lookup,
                )
                if written > 0 and first_interpretation_at is None:
                    first_interpretation_at = datetime.now(
                        timezone.utc
                    ).isoformat()
                    store.set_upload_job_state(
                        job_id, "running",
                        first_interpretation_at=first_interpretation_at,
                    )
                store.complete_upload_call(
                    call["call_id"], state="complete", rows_written=written
                )
                heartbeat()
            except UploadModelError as exc:
                store.complete_upload_call(
                    call["call_id"], state="failed", code=exc.code
                )
                logger.info(
                    "upload extraction: job %s interpretation failed (%s)",
                    job_id, exc.code,
                )
                heartbeat()
            except Exception:
                store.complete_upload_call(
                    call["call_id"], state="failed", code="invalid_output"
                )
                logger.exception(
                    "upload extraction: job %s interpretation errored", job_id
                )
                heartbeat()

    # Final state + counters (the call table is the source of truth).
    calls = store.list_upload_job_calls(job_id)
    completed_calls = sum(1 for c in calls if c["state"] == "complete")
    failed_calls = sum(1 for c in calls if c["state"] == "failed")
    total_calls = len(calls)
    # A chunk counts as succeeded when it has spans in this version.
    succeeded_segments = {
        s["segment_id"]
        for s in store.list_upload_spans(user_id, document_id, document_version)
    }
    succeeded_chunks = sum(
        1 for c in chunks if c["segment_id"] in succeeded_segments
    )
    current = store.get_upload_job(user_id, job_id) or job
    if current.get("state") == "cancelled":
        final_state = "cancelled"
    elif succeeded_chunks == 0:
        final_state = "failed"
    elif succeeded_chunks < len(chunks):
        final_state = "partial"
    else:
        final_state = "complete"
    store.set_upload_job_state(
        job_id,
        final_state,
        total_calls=total_calls,
        completed_calls=completed_calls,
        failed_calls=failed_calls,
        failed_chunks=sorted(set(failed_chunks)),
    )
    final = store.get_upload_job(user_id, job_id) or job
    measures = measure_job_row(final, calls)
    logger.info(
        "upload extraction: job %s %s (total_calls=%d, completed=%d, "
        "failed=%d, chunks=%d/%d, p1_ms=%s, p2=%s, p3_kb=%s)",
        job_id, final_state, total_calls, completed_calls, failed_calls,
        succeeded_chunks, len(chunks), measures["p1_first_interpretation_ms"],
        measures["p2_latency_ms"], measures["p3_peak_rss_kb"],
    )
    return final


def _write_evidence_chunk(
    store: ConversationStore,
    user_id: str,
    document_id: str,
    document_version: int,
    chunk: dict[str, Any],
    parsed: dict[str, Any],
    redaction_stage: str,
) -> tuple[int, int]:
    """Write one chunk's evidence rows (spans first, observations
    second, §4.2). Returns (rows_written, dropped). A span that is
    not an exact substring is dropped; an observation whose claim
    is a quotation of its span is rejected at write (the store
    raises) and counted as a failed row write, not a model failure
    (§4.3)."""
    chunk_text = chunk["text"]
    segment_id = chunk["segment_id"]
    written = 0
    dropped = 0
    span_by_text: dict[str, str] = {}
    for item in (parsed.get("spans") or [])[:30]:
        if not isinstance(item, dict):
            dropped += 1
            continue
        resolved = _resolve_span_in_chunk(
            item.get("text") or "", chunk_text, segment_id
        )
        if resolved is None:
            dropped += 1
            continue
        span_text, location = resolved
        try:
            row = store.save_upload_span(
                user_id, document_id, document_version, segment_id,
                span_text, redaction_stage, location,
            )
        except Exception:
            dropped += 1
            continue
        span_by_text[span_text] = row["span_id"]
        written += 1
    for item in (parsed.get("observations") or [])[:30]:
        if not isinstance(item, dict):
            dropped += 1
            continue
        claim = (item.get("claim") or "").strip()
        cited = [
            span_by_text[t]
            for t in (item.get("spans") or [])
            if isinstance(t, str) and t in span_by_text
        ]
        if not claim or not cited:
            dropped += 1
            continue
        try:
            store.save_upload_observation(
                user_id, document_id, document_version, claim, cited
            )
        except ValueError:
            # Never-a-quotation rejection: a failed row write, not a
            # model failure (§4.3). Counted, not fatal.
            dropped += 1
            continue
        written += 1
    return written, dropped


def _chunks_needing_interpretation(
    store: ConversationStore,
    user_id: str,
    document_id: str,
    document_version: int,
    chunks: list[dict[str, Any]],
) -> list[int]:
    """Chunk indexes whose evidence exists but no interpretation in
    this version cites any of their spans — the interpretation
    phase's target set (this run's chunks, plus any stranded by an
    earlier interrupted job)."""
    interpretations = store.list_upload_interpretations(
        user_id, document_id, document_version=document_version
    )
    cited_span_ids: set[str] = set()
    for interp in interpretations:
        for entry in interp.get("evidence_ids") or []:
            if isinstance(entry, dict) and entry.get("span_id"):
                cited_span_ids.add(entry["span_id"])
    targets: list[int] = []
    for i, chunk in enumerate(chunks):
        spans = store.list_upload_spans(
            user_id, document_id, document_version, chunk["segment_id"]
        )
        # A chunk needs a reading when it has evidence none of whose
        # spans any interpretation in this version cites yet (a chunk
        # is interpreted as a whole, not span-by-span).
        if spans and not any(
            s["span_id"] in cited_span_ids for s in spans
        ):
            targets.append(i)
    return targets


def _batch_evidence(
    store: ConversationStore,
    user_id: str,
    document_id: str,
    document_version: int,
    batch_chunks: list[dict[str, Any]],
) -> tuple[str, dict[str, str], dict[str, str]]:
    """The evidence text for one interpretation call (the batch's
    spans + observations), plus lookups for resolving the model's
    citations (span text -> span_id, observation claim ->
    observation_id)."""
    lines = ["SPANS:"]
    span_lookup: dict[str, str] = {}
    for chunk in batch_chunks:
        for span in store.list_upload_spans(
            user_id, document_id, document_version, chunk["segment_id"]
        ):
            span_lookup[span["span_text"]] = span["span_id"]
            lines.append(f'- "{span["span_text"]}" [{span["location"]}]')
    lines.append("OBSERVATIONS:")
    obs_lookup: dict[str, str] = {}
    all_observations = store.list_upload_observations(
        user_id, document_id, document_version
    )
    batch_span_ids = set(span_lookup.values())
    for obs in all_observations:
        if not set(obs.get("span_ids") or []) & batch_span_ids:
            continue
        obs_lookup[obs["claim"]] = obs["observation_id"]
        lines.append(f'- {obs["claim"]}')
    return "\n".join(lines), span_lookup, obs_lookup


def _write_interpretation_batch(
    store: ConversationStore,
    user_id: str,
    document_id: str,
    document_version: int,
    lens: str,
    lens_kind: str,
    parsed: dict[str, Any],
    span_lookup: dict[str, str],
    obs_lookup: dict[str, str],
) -> int:
    """Write one interpretation call's readings (capped at 30,
    §3.6). Returns rows written. A reading with no resolvable
    evidence (no cited span, no cited observation) is dropped — an
    extracted reading must be grounded; only promoted readings may
    be ungrounded (§10)."""
    written = 0
    items = parsed.get("interpretations") or []
    if not isinstance(items, list):
        raise UploadModelError("invalid_output", "interpretations is not a list")
    for item in items[:UPLOAD_MAX_INTERPRETATIONS_PER_CALL]:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        evidence: list[dict[str, Any]] = []
        for entry in item.get("spans") or []:
            if not isinstance(entry, dict):
                continue
            span_text = (entry.get("text") or "").strip()
            role = (entry.get("role") or "supporting").strip().lower()
            if span_text in span_lookup and role in (
                "primary", "supporting", "contrast",
            ):
                evidence.append(
                    {"span_id": span_lookup[span_text], "role": role}
                )
        observation_ids = [
            obs_lookup[c]
            for c in (item.get("observations") or [])
            if isinstance(c, str) and c in obs_lookup
        ]
        is_transformation = bool(item.get("is_transformation"))
        if not evidence and not observation_ids:
            continue
        proposed = item.get("proposed_outcome")
        if proposed not in ("project", "task", "idea", None):
            proposed = None
        try:
            store.save_upload_interpretation(
                user_id, document_id, document_version, lens, lens_kind,
                text,
                evidence_ids=evidence,
                observation_ids=observation_ids,
                origin="extracted",
                is_transformation=is_transformation,
                proposed_outcome=proposed,
            )
        except ValueError:
            # A transformation with no cited span, an unknown id, a
            # bad role: a failed row write, not a model failure.
            continue
        written += 1
    return written


# -- startup reconciler (§3.3) ------------------------------------------------

def reconcile_stale_upload_jobs(
    store: ConversationStore | None = None,
    *,
    stale_s: int = JOB_HEARTBEAT_STALE_S,
    now: datetime | None = None,
) -> int:
    """One deterministic pass (startup only, never per request):
    jobs 'running' (or 'queued' with a stale claim) whose heartbeat
    is older than the stale threshold — or NULL with an age beyond
    it — are marked 'interrupted' (new terminal state) in their own
    transaction, with any in-flight call marked 'failed' (code
    'interrupted'). Completed chunks are preserved (their rows were
    committed per chunk). The job is NEVER silently resumed mid-call:
    the in-flight call is dead with its worker, retried only as a
    new call in a resume job. Returns the number interrupted."""
    store = store if store is not None else ConversationStore()
    moment = now if now is not None else datetime.now(timezone.utc)
    stale_before = (moment - timedelta(seconds=stale_s)).isoformat()
    stale = store.list_stale_upload_jobs(stale_before)
    count = 0
    for job in stale:
        job_id = job["job_id"]
        try:
            for call in store.list_upload_job_calls(job_id):
                if call["state"] == "started":
                    store.complete_upload_call(
                        call["call_id"], state="failed", code="interrupted"
                    )
            if store.set_upload_job_state(job_id, "interrupted"):
                count += 1
        except Exception:
            logger.exception(
                "upload extraction: reconciler failed for job %s", job_id
            )
    if count:
        logger.info("upload extraction: reconciler interrupted %d job(s)", count)
    return count


# -- thread starter (§3.1) ----------------------------------------------------

def start_upload_extraction_job(
    job_id: str,
    db_path: str | None = None,
    *,
    complete_fn: Callable[[str], str] | None = None,
    probe_fn: Callable[[], bool] | None = None,
) -> threading.Thread:
    """Spawn the worker on a daemon thread (moneyball precedent).
    The thread opens its own ConversationStore — the request's
    store must never be shared across the request boundary. The
    thread is the worker; the job row + call table are the durable
    record."""
    from pathlib import Path

    def _target() -> None:
        store = ConversationStore(Path(db_path) if db_path else None)
        try:
            run_upload_extraction_job(
                store, job_id, complete_fn=complete_fn, probe_fn=probe_fn
            )
        finally:
            try:
                store.close()
            except Exception:
                pass

    thread = threading.Thread(
        target=_target,
        name=f"upload-extract-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    return thread

# -- promotion citation resolution (§10.3) ------------------------------------
#
# The noting brief §2.2/§2.3 rule, implemented here because the noting
# module itself lives on an unmerged branch (not in main): the quote
# and the stored text are normalized identically for matching ONLY
# (whitespace runs collapsed, curly quotes straightened — case and
# punctuation preserved), the normalized quote must occur as exactly
# one contiguous substring of the normalized stored text, and the
# matched passage is recorded verbatim from the stored text (mapped
# back through the normalization index map). Zero or multiple
# occurrences → no promotion, no repair, no fuzzy match.

_CURLY_QUOTE_MAP = {
    "\u2018": "'",  # left single quotation mark
    "\u2019": "'",  # right single quotation mark
    "\u201c": '"',  # left double quotation mark
    "\u201d": '"',  # right double quotation mark
}

_WS_RUN_RE = re.compile(r"\s+")


def normalize_quote_for_matching(text: str) -> str:
    """§2.2, for matching only: collapse every run of whitespace to
    a single space, strip, map curly quotation marks to straight
    ones. Case preserved, punctuation preserved, nothing else."""
    collapsed = _WS_RUN_RE.sub(" ", text or "").strip()
    return "".join(_CURLY_QUOTE_MAP.get(ch, ch) for ch in collapsed)


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """The §2.2 normalization of ``text`` plus the index map: entry
    i is the raw offset of normalized character i (a collapsed
    whitespace run maps to its first raw character)."""
    chars: list[str] = []
    raw_offsets: list[int] = []
    pending_space = False
    for raw_index, ch in enumerate(text or ""):
        if ch.isspace():
            if chars and not pending_space:
                pending_space = True
                chars.append(" ")
                raw_offsets.append(raw_index)
            continue
        pending_space = False
        chars.append(_CURLY_QUOTE_MAP.get(ch, ch))
        raw_offsets.append(raw_index)
    # Strip the trailing collapsed space, if any.
    while chars and chars[-1] == " ":
        chars.pop()
        raw_offsets.pop()
    return "".join(chars), raw_offsets


def resolve_quote_in_text(
    quote: str, stored_text: str
) -> dict[str, Any]:
    """Resolve one quoted passage against the stored source text
    (§2.3). Returns {"status": "ok", "span_text", "start", "end"}
    on exactly one match — the span is the VERBATIM substring of
    the stored text (raw offsets) — or {"status": "no_match"} /
    {"status": "ambiguous"} with no span. The caller renders the
    same plain message for both failures."""
    normalized_quote = normalize_quote_for_matching(quote)
    if not normalized_quote:
        return {"status": "no_match"}
    normalized_text, raw_map = _normalized_with_map(stored_text)
    if not normalized_text:
        return {"status": "no_match"}
    occurrences = normalized_text.count(normalized_quote)
    if occurrences == 0:
        return {"status": "no_match"}
    if occurrences > 1:
        return {"status": "ambiguous"}
    start_n = normalized_text.find(normalized_quote)
    end_n = start_n + len(normalized_quote)
    raw_start = raw_map[start_n]
    raw_end = raw_map[end_n - 1] + 1
    return {
        "status": "ok",
        "span_text": stored_text[raw_start:raw_end],
        "start": raw_start,
        "end": raw_end,
    }


_QUOTED_SPAN_RE = re.compile(
    r'"([^"]+)"'  # straight double quotes
    r'|“([^”]+)”'  # curly double quotes
)


def extract_quoted_passages(body: str) -> list[str]:
    """The double-quoted passages in a spoken reading, in order
    (straight or curly double quotes; empty quotes skipped). Single
    quotes are not citations — they are usually scare quotes, not
    passages the seat is citing."""
    passages: list[str] = []
    for match in _QUOTED_SPAN_RE.finditer(body or ""):
        passage = match.group(1) if match.group(1) is not None else match.group(2)
        if passage and passage.strip():
            passages.append(passage)
    return passages
