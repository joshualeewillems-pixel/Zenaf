"""Pinned validator for the wash benchmark harness (design §2.2, §6.3).

The validator is PINNED by contract version, not imported from pipeline HEAD:
it re-implements the frozen parse + repair + proposition gate + three-part
quote gate + dedupe from the §2.2 specification, mirroring the pipeline
functions it cites. If the pipeline changes, this file does not move with it
— the extraction version bumps (§2.2) and the comparison re-runs.

Mirrors (all at b216955, read-only):
- parse/repair/coercion: ``meeting_evidence_pipeline.py:797-894``
  (``_repair_json_outer``, ``_json_loads_lenient``,
  ``_coerce_candidate_rows_from_parsed``, ``parse_candidate_segment_llm_json``).
- ``title_is_propositional``: vendored verbatim from
  ``meeting_proposition.py:60-91`` (pure logic; cited, not imported).
- confidence word mapping: ``meeting_evidence_pipeline.py:152-158``.
- speaker resolution: ``textutil.split_speaker_line`` (mirrors pipeline :478-484).
- dedupe similarity: Jaccard word similarity, threshold 0.72
  (``entity_judgment_primitives.py:201``).

Contract rules this validator enforces (design §2.1.5, refinements A/B/C):
- Verbatim-quote-or-drop, three-part: exactness (deterministic substring),
  attribution (deterministic where speaker boundaries are explicit, otherwise
  scored against frozen gold), support (frozen semantic judgment). Each
  failure drops the row with its own diagnostic reason; passing one never
  counts as passing the others.
- 100% exact-substring compliance for emitted rows: a missing quote is NOT
  substituted with the title (the pipeline's ``eq = text[:800]`` fallback at
  :1044-1046 is reversed here) — the row is dropped (``missing_quote``).
- Missing confidence is ``low`` with diagnostic reason ``confidence_missing``
  (the pipeline's 0.55 default at :1049 is reversed here); explicitly low
  confidence carries reason ``support_uncertain``. The three displayed labels
  are unchanged; no fourth tier.
- A failed model call (failure code) is never an empty: the validator reports
  the failure and emits nothing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from local_ai.eval.wash import (
    CONFIDENCE_REASON_MISSING,
    CONFIDENCE_REASON_WEAK,
    CONFIDENCE_VALUES,
    FAILURE_CODES,
    STANCE_VALUES,
    VALIDATOR_VERSION,
)
from local_ai.eval.wash.textutil import (
    count_quote_occurrences,
    jaccard_word_similarity,
    normalize_text,
    resolve_quote_speaker,
    texts_equivalent,
)

if TYPE_CHECKING:
    from local_ai.eval.wash.fixtures import ExpectedRow, Fixture

# Dedupe threshold (§2.2): title similarity >= 0.72 drops the later row.
DEDUPE_SIMILARITY = 0.72

_VALID_CONFIDENCE_WORDS = frozenset(CONFIDENCE_VALUES)
_VALID_STANCES = frozenset(STANCE_VALUES)

_WRAPPER_KEYS = ("data", "result", "items", "evidence", "claims", "extracted_rows", "output")


# ---------------------------------------------------------------------------
# Pinned parse + repair (mirrors pipeline :797-894)
# ---------------------------------------------------------------------------

def repair_json_outer(s: str) -> str:
    """Strip fences, recover a top-level array/object from surrounding text."""
    t = (s or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    t = t.strip()
    if t.startswith("["):
        if not t.rstrip().endswith("]"):
            j = t.rfind("]")
            if j != -1:
                t = t[: j + 1]
        return t
    if t and not t.startswith("{"):
        i = t.find("{")
        if i != -1:
            t = t[i:]
    if t and not t.rstrip().endswith("}"):
        j = t.rfind("}")
        if j != -1:
            t = t[: j + 1]
    return t


def json_loads_lenient(s: str) -> tuple[Any | None, bool]:
    """Parse JSON; repair common LLM mistakes (trailing commas) before giving up.

    Returns ``(data, was_repaired)`` — ``was_repaired`` is True only when the
    trailing-comma repair was needed (measure 6's "parse clean pre-repair").
    """
    t = (s or "").strip()
    if not t:
        return None, False
    try:
        return json.loads(t), False
    except json.JSONDecodeError:
        pass
    t2 = re.sub(r",\s*}", "}", t)
    t2 = re.sub(r",\s*]", "]", t2)
    if t2 != t:
        try:
            return json.loads(t2), True
        except json.JSONDecodeError:
            pass
    return None, False


def coerce_candidate_rows(data: Any) -> list[dict[str, Any]]:
    """Normalize alternate model shapes to a list of row dicts.

    Handles: top-level array, ``rows``, nested wrappers (``data``/``result``/
    ``items``/``evidence``/``claims``/``extracted_rows``/``output``),
    single-row root object. Rows must carry non-empty ``text``.
    """
    if data is None:
        return []
    if isinstance(data, list):
        if data and all(
            isinstance(x, dict) and str(x.get("text") or "").strip() for x in data
        ):
            return [x for x in data if isinstance(x, dict)]
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("rows")
    if isinstance(rows, list) and rows:
        if all(isinstance(r, dict) and str(r.get("text") or "").strip() for r in rows):
            return [r for r in rows if isinstance(r, dict)]
    for key in _WRAPPER_KEYS:
        v = data.get(key)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict):
            inner = v.get("rows")
            if isinstance(inner, list):
                got = [r for r in inner if isinstance(r, dict)]
                if got:
                    return got
            nested = coerce_candidate_rows(v)
            if nested:
                return nested
    if data.get("claim_type") or data.get("type") or data.get("label"):
        return [data]
    return []


def parse_raw_model_text(raw: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse raw model text into candidate row dicts + parse metadata.

    Meta keys: ``decode_ok``, ``reason`` (``ok`` / ``json_decode_error`` /
    ``zero_rows_after_coerce``), ``hard_empty`` (explicit ``{"rows": []}``),
    ``parsed_row_count``, ``clean_parse`` (strict parse, no trailing-comma
    repair), ``root_type`` (when nothing coerced).
    """
    meta: dict[str, Any] = {"decode_ok": False, "clean_parse": False}
    t = repair_json_outer(raw)
    data, repaired = json_loads_lenient(t)
    if data is None:
        meta["reason"] = "json_decode_error"
        return [], meta
    meta["decode_ok"] = True
    meta["clean_parse"] = not repaired
    if isinstance(data, dict):
        rows_key = data.get("rows")
        if isinstance(rows_key, list) and len(rows_key) == 0:
            meta["reason"] = "ok"
            meta["parsed_row_count"] = 0
            meta["hard_empty"] = True
            return [], meta
    rows = coerce_candidate_rows(data)
    if rows:
        meta["reason"] = "ok"
        meta["parsed_row_count"] = len(rows)
        return rows, meta
    meta["reason"] = "zero_rows_after_coerce"
    meta["root_type"] = type(data).__name__
    return [], meta


# ---------------------------------------------------------------------------
# Proposition gate (title_is_propositional vendored verbatim, meeting_proposition.py:60-91)
# ---------------------------------------------------------------------------

def title_is_propositional(title: str, *, source_stage: str | None = None) -> bool:
    """
    Hard gate: reject single-token labels, ALL-CAPS shout, raw diarized lines, transcript junk.
    Literal anchors use the same bar (they should already be expanded to full headlines).
    """
    _ = source_stage
    t = (title or "").strip()
    if not t:
        return False
    low = t.lower()
    wc = len(t.split())

    if re.match(r"^speaker\s+[a-z0-9]", low):
        return False
    if re.match(r"^(transcript of|meeting notes|created on)\b", low):
        return False
    if wc <= 1:
        return False
    if t.isupper() and len(t) <= 14 and " " not in t:
        return False
    if re.fullmatch(r"[A-Z]{2,15}", t.strip()):
        return False

    # Propositions are phrases, not bare entity names: need length or word count.
    if wc >= 4 and len(t) >= 18:
        return True
    if wc == 3 and len(t) >= 30:
        return True
    return False


def normalize_confidence_label(score: float) -> str:
    """Word label from a numeric self-report (pipeline :152-158)."""
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Row model + validation result
# ---------------------------------------------------------------------------

@dataclass
class ProposedRow:
    """A model-proposed row after normalization, before the quote gate."""

    text: str
    summary: str | None
    evidence_quote: str
    confidence: str  # high / medium / low (word label)
    confidence_raw: float | None
    confidence_reason: str | None  # confidence_missing / support_uncertain / None
    stance: str | None  # proposed / considered / committed / rejected / unresolved
    source_stage: str  # "model" for model rows
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class DroppedRow:
    """A proposed row the gate dropped, with its diagnostic reason."""

    row: ProposedRow
    reason: str  # one of GATE_REASONS
    detail: str


@dataclass
class ValidationResult:
    """Everything the validator knows about one segment's raw model output."""

    emitted: list[ProposedRow] = field(default_factory=list)
    dropped: list[DroppedRow] = field(default_factory=list)
    proposed_count: int = 0
    parse_meta: dict[str, Any] = field(default_factory=dict)
    failure: dict[str, Any] | None = None  # {"code": ...} when the call failed
    diagnostics: list[str] = field(default_factory=list)

    @property
    def gate_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in self.dropped:
            counts[d.reason] = counts.get(d.reason, 0) + 1
        return counts

    @property
    def hard_empty(self) -> bool:
        return bool(self.parse_meta.get("hard_empty"))


# ---------------------------------------------------------------------------
# Three-part quote gate (§2.1.5)
# ---------------------------------------------------------------------------

def _match_gold(row_text: str, expected: list["ExpectedRow"]) -> "ExpectedRow | None":
    """First gold proposition the row's text expresses (frozen judgments)."""
    for gold in expected:
        if texts_equivalent(row_text, gold.text):
            return gold
        for eq in gold.equivalents:
            if texts_equivalent(row_text, eq):
                return gold
    return None


def _quote_supports(quote: str, gold: "ExpectedRow") -> bool:
    """Support check: the quote is one of the gold proposition's supporting quotes."""
    nq = normalize_text(quote)
    return any(normalize_text(sq) == nq for sq in gold.supporting_quotes)


def _normalize_row(row_dict: dict[str, Any]) -> ProposedRow:
    """Normalize one parsed row dict (no gate decisions here)."""
    text = str(row_dict.get("text") or "").strip()
    summary_raw = str(
        row_dict.get("summary") or row_dict.get("paraphrase") or ""
    ).strip()
    quote = str(
        row_dict.get("evidence_quote") or row_dict.get("evidenceQuote") or ""
    ).strip()

    # Confidence: a numeric self-report maps by the word rule; a word label is
    # taken as-is; a missing/invalid value is LOW with reason
    # confidence_missing (contract §2.1.5 — the pipeline's 0.55 default is
    # reversed). An explicitly low value carries reason support_uncertain
    # (evidence assessed as weak, §2.1.3).
    raw_conf = row_dict.get("confidence_raw", row_dict.get("confidenceRaw"))
    conf_value = row_dict.get("confidence")
    confidence_raw: float | None = None
    confidence = "low"
    reason: str | None = None
    if isinstance(raw_conf, (int, float)) and not isinstance(raw_conf, bool):
        confidence_raw = float(raw_conf)
    if isinstance(conf_value, (int, float)) and not isinstance(conf_value, bool):
        confidence_raw = float(conf_value)
        confidence = normalize_confidence_label(confidence_raw)
    elif isinstance(conf_value, str) and conf_value.strip().lower() in _VALID_CONFIDENCE_WORDS:
        confidence = conf_value.strip().lower()
    else:
        reason = CONFIDENCE_REASON_MISSING
    if reason is None and confidence == "low":
        reason = CONFIDENCE_REASON_WEAK

    stance_raw = row_dict.get("stance")
    stance = (
        str(stance_raw).strip().lower()
        if isinstance(stance_raw, str) and str(stance_raw).strip().lower() in _VALID_STANCES
        else None
    )

    return ProposedRow(
        text=text,
        summary=summary_raw[:2000] if summary_raw else None,
        evidence_quote=quote[:2000],
        confidence=confidence,
        confidence_raw=confidence_raw,
        confidence_reason=reason,
        stance=stance,
        source_stage="model",
        raw=row_dict,
    )


def validate_segment_output(
    raw: str,
    segment_text: str,
    fixture: "Fixture",
    *,
    failure_code: str | None = None,
) -> ValidationResult:
    """Validate one segment's raw model output against its fixture gold labels.

    Order per proposed row: proposition gate (text length + propositional
    shape) → exactness → attribution → support → dedupe. The first failure
    drops the row with that reason. A failed model call (``failure_code``)
    emits nothing and is never an empty.
    """
    if failure_code is not None:
        if failure_code not in FAILURE_CODES:
            raise ValueError(f"unknown failure code: {failure_code!r}")
        return ValidationResult(
            proposed_count=0,
            parse_meta={
                "decode_ok": False,
                "reason": "model_call_failed",
                "failure_code": failure_code,
                "hard_empty": False,
                "parsed_row_count": 0,
                "clean_parse": False,
            },
            failure={"code": failure_code},
        )

    row_dicts, meta = parse_raw_model_text(raw)
    result = ValidationResult(proposed_count=len(row_dicts), parse_meta=meta)
    if meta.get("hard_empty"):
        return result
    if not row_dicts:
        return result

    segment = segment_text or ""
    has_speakers = fixture.has_explicit_speakers
    expected = fixture.expected

    for row_dict in row_dicts:
        row = _normalize_row(row_dict)

        # Proposition gate (§2.2): text >= 4 chars and propositional shape.
        if len(row.text) < 4:
            result.dropped.append(
                DroppedRow(row, "text_too_short", f"text is {len(row.text)} chars")
            )
            continue
        if not title_is_propositional(row.text):
            result.dropped.append(
                DroppedRow(row, "not_propositional", "text fails the propositional-shape rule")
            )
            continue

        # Exactness (1): the quote must be an exact substring of the segment.
        # A missing quote is dropped, never substituted with the title.
        if not row.evidence_quote:
            result.dropped.append(
                DroppedRow(row, "missing_quote", "row carries no evidence_quote")
            )
            continue
        if row.evidence_quote not in segment:
            result.dropped.append(
                DroppedRow(
                    row,
                    "quote_not_verbatim",
                    "evidence_quote is not an exact substring of the segment",
                )
            )
            continue

        # Ambiguity diagnostic (§2.1.2): the quote matches more than one span.
        occurrences = count_quote_occurrences(segment, row.evidence_quote)
        if occurrences > 1:
            result.diagnostics.append(
                f"quote_ambiguous: quote occurs {occurrences}x in the segment"
            )

        gold = _match_gold(row.text, expected)

        # Attribution (2): the quote must belong to the speaker whose position
        # the row represents. Deterministic where boundaries are explicit.
        if has_speakers and gold is not None and gold.speaker is not None:
            line_speaker, ambiguous = resolve_quote_speaker(segment, row.evidence_quote)
            if line_speaker is not None:
                if line_speaker != gold.speaker:
                    result.dropped.append(
                        DroppedRow(
                            row,
                            "quote_misattributed",
                            f"quote is from {line_speaker}, gold attributes it to {gold.speaker}",
                        )
                    )
                    continue
            else:
                # Ambiguous or prefix-less line: fall back to the gold quote.
                if not _quote_supports(row.evidence_quote, gold):
                    result.dropped.append(
                        DroppedRow(
                            row,
                            "quote_misattributed",
                            "quote cannot be resolved to the gold speaker's line",
                        )
                    )
                    continue

        # Support (3): the quoted words must support the proposed interpretation.
        if gold is None:
            result.dropped.append(
                DroppedRow(
                    row,
                    "quote_unsupported",
                    "row matches no gold proposition",
                )
            )
            continue
        if not _quote_supports(row.evidence_quote, gold):
            result.dropped.append(
                DroppedRow(
                    row,
                    "quote_unsupported",
                    "quote is not one of the gold proposition's supporting quotes",
                )
            )
            continue

        if row.stance is None and row_dict.get("stance") is not None:
            result.diagnostics.append(
                f"invalid_stance: {row_dict.get('stance')!r} is not in the stance vocabulary"
            )

        result.emitted.append(row)

    # Dedupe (§2.2): title similarity >= 0.72 drops the later row.
    deduped: list[ProposedRow] = []
    for row in result.emitted:
        if any(
            jaccard_word_similarity(row.text, kept.text) >= DEDUPE_SIMILARITY
            for kept in deduped
        ):
            result.dropped.append(
                DroppedRow(row, "duplicate", "near-duplicate of an earlier emitted row (>= 0.72)")
            )
        else:
            deduped.append(row)
    result.emitted = deduped
    return result


__all__ = [
    "DEDUPE_SIMILARITY",
    "VALIDATOR_VERSION",
    "ProposedRow",
    "DroppedRow",
    "ValidationResult",
    "repair_json_outer",
    "json_loads_lenient",
    "coerce_candidate_rows",
    "parse_raw_model_text",
    "title_is_propositional",
    "normalize_confidence_label",
    "validate_segment_output",
]
