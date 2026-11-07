"""Fixture loader for the wash benchmark harness (design §5.1, §8).

Loads the frozen synthetic fixture set + gold labels (DRAFT — the founder
approves FROZEN gold labels only after the harness proves itself, §8.1).
The loader refuses to run when versions disagree:

- the fixture-set version and the gold-label version must agree (§8: "refuses
  to run if the fixture version and the gold-label version disagree");
- the file's semantic-contract version must be ``wash-semantic 1.0`` and its
  extraction version ``wash-extraction 1.0`` (the versions this harness pins).

Gold-integrity checks at load (fail loudly, never silently): fixture ids
unique; categories known; segments non-empty; every expected quote and every
supporting quote an exact substring of its segment; stance vocabulary;
forbidden classes known; ``has_explicit_speakers`` consistent with the
segment text (a segment claiming explicit speakers must actually carry a
speaker-prefixed line, and vice versa).

Fixtures are synthetic text only — no real user data, no exports, no staging
reads (§5.1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from local_ai.eval.wash import (
    EXTRACTION_VERSION,
    FIXTURE_SET_VERSION,
    FORBIDDEN_CLASSES,
    GOLD_LABEL_VERSION,
    SEMANTIC_VERSION,
    STANCE_VALUES,
)
from local_ai.eval.wash.textutil import segment_has_explicit_speakers

CATEGORIES = (
    "negation",
    "uncertainty",
    "commitments",
    "rejections",
    "attribution",
    "evidence_preservation",
    "empty",
)

_VALID_STANCES = frozenset(STANCE_VALUES)
_VALID_FORBIDDEN = frozenset(FORBIDDEN_CLASSES)


class FixtureError(ValueError):
    """The fixture file is invalid or its versions disagree — refuse to run."""


@dataclass(frozen=True)
class ExpectedRow:
    """One gold proposition a correct output must recover."""

    text: str
    stance: str
    speaker: str | None  # e.g. "Speaker A" when boundaries are explicit, else None
    quote: str  # the exact verbatim span the row must carry
    equivalents: tuple[str, ...] = ()  # frozen semantic-equivalence judgments (§6.4.1)
    supporting_quotes: tuple[str, ...] = ()  # quotes that support this proposition


@dataclass(frozen=True)
class ForbiddenRow:
    """One forbidden output: what must NOT be emitted (measure F, §6.4)."""

    forbidden_class: str  # one of FORBIDDEN_CLASSES
    text: str
    equivalents: tuple[str, ...] = ()
    stance: str | None = None  # when set, the row must also carry this stance to count
    note: str = ""


@dataclass(frozen=True)
class Fixture:
    """One synthetic segment + its frozen (draft) gold labels."""

    id: str
    category: str
    segment: str
    segment_id: str  # stable, deterministic: seg-0000, ... (file order)
    has_explicit_speakers: bool
    expected: tuple[ExpectedRow, ...] = ()
    forbidden: tuple[ForbiddenRow, ...] = ()
    notes: str = ""


@dataclass
class FixtureSet:
    """A loaded fixture set: fixtures + the versions they were authored under."""

    fixtures: list[Fixture] = field(default_factory=list)
    fixture_set_version: str = ""
    gold_label_version: str = ""
    semantic_contract_version: str = ""
    extraction_version: str = ""

    def by_id(self, fixture_id: str) -> Fixture:
        for fx in self.fixtures:
            if fx.id == fixture_id:
                return fx
        raise KeyError(f"unknown fixture id: {fixture_id!r}")

    def by_category(self, category: str) -> list[Fixture]:
        return [fx for fx in self.fixtures if fx.category == category]

    @property
    def ids(self) -> list[str]:
        return [fx.id for fx in self.fixtures]


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise FixtureError(msg)


def _parse_expected(raw: Any, fixture_id: str) -> ExpectedRow:
    _require(isinstance(raw, dict), f"{fixture_id}: expected row must be an object")
    text = raw.get("text")
    _require(isinstance(text, str) and text.strip(), f"{fixture_id}: expected.text required")
    stance = raw.get("stance")
    _require(
        stance in _VALID_STANCES,
        f"{fixture_id}: expected.stance {stance!r} is not in the stance vocabulary",
    )
    speaker = raw.get("speaker")
    _require(
        speaker is None or (isinstance(speaker, str) and speaker.strip()),
        f"{fixture_id}: expected.speaker must be a string or null",
    )
    quote = raw.get("quote")
    _require(
        isinstance(quote, str) and quote.strip(),
        f"{fixture_id}: expected.quote required (the exact verbatim span)",
    )
    equivalents = raw.get("equivalents", [])
    _require(
        isinstance(equivalents, list)
        and all(isinstance(e, str) and e.strip() for e in equivalents),
        f"{fixture_id}: expected.equivalents must be a list of non-empty strings",
    )
    supporting = raw.get("supporting_quotes", [])
    _require(
        isinstance(supporting, list)
        and all(isinstance(s, str) and s.strip() for s in supporting),
        f"{fixture_id}: expected.supporting_quotes must be a list of non-empty strings",
    )
    return ExpectedRow(
        text=text.strip(),
        stance=stance,
        speaker=speaker.strip() if isinstance(speaker, str) else None,
        quote=quote.strip(),
        equivalents=tuple(e.strip() for e in equivalents),
        supporting_quotes=tuple(s.strip() for s in supporting),
    )


def _parse_forbidden(raw: Any, fixture_id: str) -> ForbiddenRow:
    _require(isinstance(raw, dict), f"{fixture_id}: forbidden row must be an object")
    fclass = raw.get("class")
    _require(
        fclass in _VALID_FORBIDDEN,
        f"{fixture_id}: forbidden.class {fclass!r} is not a known forbidden-output class",
    )
    text = raw.get("text")
    _require(isinstance(text, str) and text.strip(), f"{fixture_id}: forbidden.text required")
    equivalents = raw.get("equivalents", [])
    _require(
        isinstance(equivalents, list)
        and all(isinstance(e, str) and e.strip() for e in equivalents),
        f"{fixture_id}: forbidden.equivalents must be a list of non-empty strings",
    )
    stance = raw.get("stance")
    _require(
        stance is None or stance in _VALID_STANCES,
        f"{fixture_id}: forbidden.stance {stance!r} is not in the stance vocabulary",
    )
    note = raw.get("note", "")
    _require(isinstance(note, str), f"{fixture_id}: forbidden.note must be a string")
    return ForbiddenRow(
        forbidden_class=fclass,
        text=text.strip(),
        equivalents=tuple(e.strip() for e in equivalents),
        stance=stance,
        note=note,
    )


def load_fixture_set(path: str | Path) -> FixtureSet:
    """Load + validate a fixture file. Raises FixtureError on any problem."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FixtureError(f"fixture file not found: {path}")
    except json.JSONDecodeError as exc:
        raise FixtureError(f"fixture file is not valid JSON: {path}: {exc}")

    _require(isinstance(data, dict), "fixture file root must be an object")
    fsv = data.get("fixture_set_version")
    glv = data.get("gold_label_version")
    _require(isinstance(fsv, str) and fsv, "fixture_set_version is required")
    _require(isinstance(glv, str) and glv, "gold_label_version is required")
    _require(
        fsv == glv,
        f"fixture version {fsv!r} and gold-label version {glv!r} disagree — refusing to run (§8)",
    )
    _require(
        fsv == FIXTURE_SET_VERSION and glv == GOLD_LABEL_VERSION,
        f"fixture/gold versions {fsv!r} do not match this harness's pinned "
        f"versions ({FIXTURE_SET_VERSION!r}) — refusing to run",
    )
    scv = data.get("semantic_contract_version")
    exv = data.get("extraction_version")
    _require(
        scv == SEMANTIC_VERSION,
        f"semantic contract version {scv!r} != pinned {SEMANTIC_VERSION!r} — refusing to run",
    )
    _require(
        exv == EXTRACTION_VERSION,
        f"extraction version {exv!r} != pinned {EXTRACTION_VERSION!r} — refusing to run",
    )

    raw_fixtures = data.get("fixtures")
    _require(isinstance(raw_fixtures, list) and raw_fixtures, "fixtures must be a non-empty list")

    fixtures: list[Fixture] = []
    seen_ids: set[str] = set()
    for idx, raw in enumerate(raw_fixtures):
        _require(isinstance(raw, dict), f"fixture #{idx}: must be an object")
        fid = raw.get("id")
        _require(isinstance(fid, str) and fid.strip(), f"fixture #{idx}: id is required")
        fid = fid.strip()
        _require(fid not in seen_ids, f"duplicate fixture id: {fid!r}")
        seen_ids.add(fid)
        category = raw.get("category")
        _require(
            category in CATEGORIES,
            f"{fid}: unknown category {category!r} (known: {', '.join(CATEGORIES)})",
        )
        segment = raw.get("segment")
        _require(
            isinstance(segment, str) and segment.strip(),
            f"{fid}: segment is required",
        )
        segment = segment.strip()
        expected = tuple(
            _parse_expected(e, fid) for e in (raw.get("expected") or [])
        )
        forbidden = tuple(
            _parse_forbidden(f, fid) for f in (raw.get("forbidden") or [])
        )
        # Gold integrity: every expected quote and supporting quote must be an
        # exact substring of the segment, or the gold itself is broken.
        for gold in expected:
            _require(
                gold.quote in segment,
                f"{fid}: expected quote is not an exact substring of the segment: {gold.quote!r}",
            )
            for sq in gold.supporting_quotes:
                _require(
                    sq in segment,
                    f"{fid}: supporting quote is not an exact substring of the segment: {sq!r}",
                )
        # Speaker-boundary consistency: the flag must match the segment text.
        has_speakers = segment_has_explicit_speakers(segment)
        declared = raw.get("has_explicit_speakers")
        _require(
            isinstance(declared, bool),
            f"{fid}: has_explicit_speakers must be true/false",
        )
        _require(
            declared == has_speakers,
            f"{fid}: has_explicit_speakers={declared} but the segment text "
            f"{'has' if has_speakers else 'has no'} speaker-prefixed lines",
        )
        if category == "empty":
            _require(
                len(expected) == 0,
                f"{fid}: empty-category fixtures must have no expected rows",
            )
        notes = raw.get("notes", "")
        _require(isinstance(notes, str), f"{fid}: notes must be a string")
        fixtures.append(
            Fixture(
                id=fid,
                category=category,
                segment=segment,
                segment_id=f"seg-{idx:04d}",
                has_explicit_speakers=declared,
                expected=expected,
                forbidden=forbidden,
                notes=notes,
            )
        )

    return FixtureSet(
        fixtures=fixtures,
        fixture_set_version=fsv,
        gold_label_version=glv,
        semantic_contract_version=scv,
        extraction_version=exv,
    )


def default_fixture_path() -> Path:
    """Path of the shipped synthetic fixture set (DRAFT labels)."""
    return Path(__file__).parent / "fixtures" / "wash-fixtures-v1-draft.json"


__all__ = [
    "CATEGORIES",
    "FixtureError",
    "ExpectedRow",
    "ForbiddenRow",
    "Fixture",
    "FixtureSet",
    "load_fixture_set",
    "default_fixture_path",
]
