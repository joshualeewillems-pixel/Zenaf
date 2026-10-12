from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class Segment:
  segment_id: str
  start_offset: int
  end_offset: int
  text: str
  speaker: str | None = None


def _split_segments_blank_lines(text: str) -> List[Segment]:
  """Segmentation fallback: split on blank lines into topic-sized chunks."""
  segments: List[Segment] = []
  if not text:
    return segments
  parts = re.split(r"\n\s*\n+", text)
  offset = 0
  seg_idx = 1
  for part in parts:
    part_stripped = part.strip()
    if not part_stripped:
      offset += len(part) + 2  # approximate; not critical
      continue
    start = text.find(part_stripped, offset)
    if start == -1:
      start = offset
    end = start + len(part_stripped)
    segments.append(Segment(segment_id=f"seg_{seg_idx}", start_offset=start, end_offset=end, text=part_stripped))
    seg_idx += 1
    offset = end
  return segments


def _split_segments_with_speakers(text: str, speaker_labels: List[Dict[str, Any]]) -> List[Segment]:
  """
  If speaker labels are present, use them as primary segment boundaries.
  Expected label shape: { "offset": int, "length": int, "speaker": "Alice" }.
  """
  segments: List[Segment] = []
  if not text or not speaker_labels:
    return segments
  # Ensure labels are ordered by offset
  labels_sorted = sorted(
    [lbl for lbl in speaker_labels if isinstance(lbl, dict) and "offset" in lbl and "length" in lbl],
    key=lambda l: int(l.get("offset", 0)),
  )
  seg_idx = 1
  for lbl in labels_sorted:
    try:
      start = int(lbl.get("offset", 0))
      length = int(lbl.get("length", 0))
    except (TypeError, ValueError):
      continue
    if start < 0 or length <= 0 or start >= len(text):
      continue
    end = min(start + length, len(text))
    slice_text = text[start:end].strip()
    if not slice_text:
      continue
    speaker = str(lbl.get("speaker") or "").strip() or None
    segments.append(
      Segment(segment_id=f"seg_{seg_idx}", start_offset=start, end_offset=end, text=slice_text, speaker=speaker)
    )
    seg_idx += 1
  return segments


def _first_sentence(text: str, max_len: int = 160) -> str:
  if not text:
    return ""
  # Simple sentence boundary heuristic
  m = re.search(r"[.!?]\s", text)
  sent = text[: m.end()] if m else text
  sent = sent.strip()
  if len(sent) > max_len:
    sent = sent[: max_len].rstrip() + "…"
  return sent


def _sentence_split(text: str) -> List[str]:
  # Very lightweight sentence split
  raw = re.split(r"(?<=[.!?])\s+", text.strip())
  return [s.strip() for s in raw if s.strip()]


def sort_transcript(
  raw_transcript_text: str,
  call_context: Dict[str, Any] | None = None,
  speaker_labels: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
  """
  Thinnest real transcript sorter:
  - segments by blank lines
  - topic labels from first sentence
  - rudimentary heuristics for deliverables, open questions, candidate tasks/decisions
  No model calls; fully inspectable behavior.
  """
  call_context = call_context or {}
  text = raw_transcript_text or ""

  segments = _split_segments_with_speakers(text, speaker_labels or []) if speaker_labels else _split_segments_blank_lines(text)
  topics: List[Dict[str, Any]] = []
  deliverables: List[Dict[str, Any]] = []
  open_questions: List[Dict[str, Any]] = []
  candidate_tasks: List[Dict[str, Any]] = []
  candidate_decisions: List[Dict[str, Any]] = []
  candidate_ideas: List[Dict[str, Any]] = []

  ct_idx = 1
  cd_idx = 1
  deliv_idx = 1
  q_idx = 1

  for seg in segments:
    sentences = _sentence_split(seg.text)
    title = _first_sentence(seg.text, max_len=80) or "Topic"
    summary = _first_sentence(seg.text, max_len=280)
    substantive = any(
      kw in seg.text.lower()
      for kw in ["should", "need to", "we will", "we'll", "we are going to", "decide", "decided", "agree", "agreed", "?"]
    )
    topics.append(
      {
        "segment_id": seg.segment_id,
        "start_offset": seg.start_offset,
        "end_offset": seg.end_offset,
        "topic_title": title,
        "topic_summary": summary,
        "substantive": substantive,
        "speaker": seg.speaker,
      }
    )

    for sent in sentences:
      sent_l = sent.lower()
      # Open questions
      if "?" in sent:
        open_questions.append(
          {
            "question_id": f"q_{q_idx}",
            "segment_id": seg.segment_id,
            "source_text": sent,
            "description": sent,
            "suggested_owner": None,
            "confidence": "medium",
          }
        )
        q_idx += 1

      # Deliverables / tasks / ideas
      deliverable_trigger = any(
        kw in sent_l
        for kw in ["we should", "should ", "need to", "let's ", "lets ", "we will", "we'll", "we are going to"]
      )
      decision_trigger = any(
        kw in sent_l
        for kw in ["we decided", "we've decided", "we agree", "we agreed", "we will", "we'll", "we're going to", "decision is"]
      )
      idea_trigger = (
        not deliverable_trigger
        and not decision_trigger
        and any(kw in sent_l for kw in ["could ", "might ", "maybe we", "we could", "we might", "consider ", "explore "])
      )

      if deliverable_trigger:
        deliverables.append(
          {
            "deliverable_id": f"deliv_{deliv_idx}",
            "segment_id": seg.segment_id,
            "source_text": sent,
            "description": sent,
          }
        )
        deliv_idx += 1

        # Candidate task from same sentence
        title = sent
        if len(title) > 80:
          title = title[:80].rstrip() + "…"
        candidate_tasks.append(
          {
            "candidate_task_id": f"ct_{ct_idx}",
            "segment_id": seg.segment_id,
            "source_text": sent,
            "title": title,
            "description": sent,
            "suggested_owner": None,
            "confidence": "medium",
            "evidence_excerpt": sent,
            "segment_text": seg.text,
            "kind": "task",
          }
        )
        ct_idx += 1

      # Candidate decisions
      if decision_trigger:
        summary = sent
        if len(summary) > 120:
          summary = summary[:120].rstrip() + "…"
        candidate_decisions.append(
          {
            "candidate_decision_id": f"cd_{cd_idx}",
            "segment_id": seg.segment_id,
            "source_text": sent,
            "summary": summary,
            "rationale": None,
            "participants": None,
            "confidence": "medium",
            "evidence_excerpt": sent,
            "segment_text": seg.text,
            "kind": "decision",
          }
        )
        cd_idx += 1

      # Candidate ideas / follow-ups (directional but not yet a committed task/decision)
      if idea_trigger:
        summary = sent
        if len(summary) > 120:
          summary = summary[:120].rstrip() + "…"
        candidate_ideas.append(
          {
            "candidate_idea_id": f"ci_{len(candidate_ideas) + 1}",
            "segment_id": seg.segment_id,
            "source_text": sent,
            "summary": summary,
            "confidence": "medium",
            "evidence_excerpt": sent,
            "segment_text": seg.text,
            "kind": "idea",
          }
        )

  out: Dict[str, Any] = {
    "transcript_id": None,  # caller/front-end may assign a stable id if desired
    "call_context": call_context,
    "topics": topics,
    "deliverables": deliverables,
    "open_questions": open_questions,
    "candidate_tasks": candidate_tasks,
    "candidate_decisions": candidate_decisions,
    "candidate_ideas": candidate_ideas,
  }
  return out

