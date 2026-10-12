"""Distillation: PresenceEvents -> candidate TrainingSignals (LLM-assisted).

Events are grouped into conversation-sized batches. Each batch is sent to a
*local* LLM (Ollama) with an extraction prompt; the model's extractions become
candidate TrainingSignals with status="pending". Nothing is approved here —
candidates require explicit user review before they can enter the profile.

If Ollama is unreachable, distillation raises DistillError. It never
fabricates signals. Tests inject a stub complete_fn.
"""
from __future__ import annotations

import json
import time
import urllib.request
from collections import defaultdict
from typing import Callable
from uuid import uuid4

from .schema import PresenceEvent, SignalLayer, SignalValence, TrainingSignal

CompleteFn = Callable[[str], str]

_BATCH_SIZE = 40  # max events per LLM prompt
_MAX_SIGNALS_PER_BATCH = 8


class DistillError(RuntimeError):
    """Distillation could not run (e.g. Ollama unreachable)."""


def _default_complete(prompt: str, *, timeout: float = 180.0) -> str:
    """Call the local Ollama instance. User content never leaves the machine."""
    from local_ai.config import OLLAMA_MODEL, OLLAMA_URL

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
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise DistillError(
            f"Ollama unreachable at {OLLAMA_URL}: {exc}. "
            "Start Ollama (`ollama serve`) or pass complete_fn explicitly."
        ) from exc
    text = payload.get("response", "")
    if not isinstance(text, str) or not text.strip():
        raise DistillError("Ollama returned an empty response; no signals fabricated.")
    return text


def _batch_key(event: PresenceEvent) -> str:
    ctx = event.context or {}
    return str(
        ctx.get("conversation_id")
        or ctx.get("conversation_title")
        or f"{event.source}:{event.kind}"
    )


def _group_batches(events: list[PresenceEvent]) -> list[list[PresenceEvent]]:
    groups: dict[str, list[PresenceEvent]] = defaultdict(list)
    order: list[str] = []
    for event in events:
        key = _batch_key(event)
        if key not in groups:
            order.append(key)
        groups[key].append(event)
    batches: list[list[PresenceEvent]] = []
    for key in order:
        chunk = groups[key]
        for i in range(0, len(chunk), _BATCH_SIZE):
            batches.append(chunk[i : i + _BATCH_SIZE])
    return batches


def _build_prompt(batch: list[PresenceEvent], zone_hint: str) -> str:
    lines = []
    for i, event in enumerate(batch):
        ts = event.ts.isoformat() if event.ts else "unknown time"
        title = (event.context or {}).get("conversation_title", "")
        header = f"[{i}] {event.actor} @ {ts}"
        if title:
            header += f" (in: {title})"
        lines.append(header)
        lines.append(event.text)
        lines.append("")
    transcript = "\n".join(lines)
    return f"""You are distilling training signal for a personal AI doppelganger from the user's own digital history. The excerpts below are already redacted (PII replaced with tokens like [EMAIL]); do not attempt to recover it.

Extract up to {_MAX_SIGNALS_PER_BATCH} candidate training signals. Focus on:
(a) decisions the user made or leaned toward,
(b) values/beliefs revealed — what they praised, rejected, or pushed back on,
(c) communication and decision-making style observations.

For each signal return an object with:
- "layer": one of "decision" | "behavior" | "guidance"
- "zone": a short specialization label (e.g. "strategy", "creative", "relationships", "career", or "{zone_hint}")
- "valence": one of "endorsed" | "rejected" | "corrected" | "observed"
- "summary": one sentence, redacted, describing what this reveals about how the user decides or acts
- "detail": 1-3 sentences of redacted supporting evidence from the excerpts

Rules:
- Only include signals with real evidence in the excerpts. Do not invent, infer beyond what is shown, or restate PII.
- Prefer "observed" valence unless the user clearly endorsed/rejected/corrected something.
- Keep summaries and detail free of PII (use the [EMAIL]/[PHONE]/[NUMBER] tokens if referring to redacted content).

Return ONLY a JSON array of these objects. No other text.

Excerpts:
{transcript}"""


_VALID_LAYERS: set[str] = {"decision", "behavior", "guidance"}
_VALID_VALENCES: set[str] = {"endorsed", "rejected", "corrected", "observed"}


def _parse_extractions(raw: str) -> list[dict]:
    """Defensively extract a JSON array of extraction dicts from LLM output."""
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)][: _MAX_SIGNALS_PER_BATCH]


def _coerce_extraction(item: dict) -> dict | None:
    layer = str(item.get("layer", "")).strip().lower()
    valence = str(item.get("valence", "")).strip().lower()
    summary = str(item.get("summary", "")).strip()
    if layer not in _VALID_LAYERS or valence not in _VALID_VALENCES or not summary:
        return None
    zone = str(item.get("zone", "")).strip() or "general"
    detail = str(item.get("detail", "")).strip()
    return {
        "layer": layer,
        "valence": valence,
        "summary": summary[:500],
        "detail": detail[:2000],
        "zone": zone[:64],
    }


def distill_events(
    events: list[PresenceEvent],
    *,
    complete_fn: CompleteFn | None = None,
    zone_hint: str = "general",
    actor: str = "user",
    session_id: str = "",
) -> list[TrainingSignal]:
    """Distill events into candidate TrainingSignals (status=pending).

    Raises DistillError if the LLM is unreachable. Never fabricates signals:
    a batch whose extractions fail to parse simply yields no candidates.
    """
    if not events:
        return []
    complete = complete_fn or _default_complete
    now_ms = int(time.time() * 1000)
    candidates: list[TrainingSignal] = []
    for batch in _group_batches(events):
        prompt = _build_prompt(batch, zone_hint)
        raw = complete(prompt)  # may raise DistillError — propagated, not swallowed
        event_ids = [e.event_id for e in batch]
        sources = sorted({e.source for e in batch})
        for item in _parse_extractions(raw):
            coerced = _coerce_extraction(item)
            if coerced is None:
                continue
            candidates.append(
                TrainingSignal(
                    signal_id=f"sig-{uuid4().hex[:12]}",
                    ts_ms=now_ms,
                    layer=coerced["layer"],  # type: ignore[typeddict-item]
                    zone=coerced["zone"],
                    actor=actor,
                    summary=coerced["summary"],
                    context_ref={
                        "session_id": session_id,
                        "source_events": event_ids,
                    },
                    payload_redacted=coerced["detail"],
                    valence=coerced["valence"],  # type: ignore[typeddict-item]
                    correction_diff=None,
                    provenance={
                        "sources": sources,
                        "source_events": len(batch),
                        "adapter": "presence_ingest.distill",
                        "distilled_at_ms": now_ms,
                        "zone_hint": zone_hint,
                    },
                    supersedes=None,
                    status="pending",
                    session_id=session_id,
                )
            )
    return candidates
