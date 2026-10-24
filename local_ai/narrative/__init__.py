"""Narrative Steward — narrative state, kept outside the characters.

Audit + architecture: ~/workspace/your_files/zenaf-narrative-
steward-audit.md (Parts II–IV, as amended by the ratified Part VII
rulings on authorship/synthesis and the Part IX decisions of
2026-10-23). The Steward is the restoration of a responsibility
that was always supposed to live outside the seven seats:
recognizing, developing, and maintaining the user's ongoing
stories — grounded in evidence, in relation to the user's chosen
aspirations, without imposing a predetermined narrative or
inventing evidence (Joshua's governing principle).

Phase S0 (this package as built) is STATE ONLY:

  refs.py   — typed source references and the three evidence tiers
              (Evidence / Interpretation / Dramatization), enforced
              by type: a dramatization ref is inadmissible as
              evidence, mechanically.
  lenses.py — the lens library as canonical data (attributed
              narrative frameworks with phases, fit signals, and
              cautions), in the jurisdictions.py pattern.
  models.py — the records: threads, thread evidence, versioned
              readings, thread changes, lens fittings, and the
              involvement ledger measure (Part VII). Scale and
              progression are represented per Part IX: threads carry
              an optional scope; readings carry multiple scales plus
              a primary; progression positions are bound to a
              particular lens and may be unknown or inapplicable.
              Part X adds the recursive structure: arc associations
              (ThreadLink — many-to-many nesting between threads,
              optional and inert) and a nullable thread-local
              progression position in the same lens-bound shape.
  store.py  — NarrativeStore, the only writer of thread records,
              enforcing the two invariants in code: no reading
              without evidence; no change without NEW evidence.

Explicitly NOT in S0: any LLM call or import (the package must stay
importable with no model machinery), any narrative analysis (S1),
any prepared context for surfaces (S2), any HTTP route, and any
change to an existing surface's behavior. The Steward has no
user-facing prose voice at any phase; seats speak, the Steward
keeps the story straight.
"""

from .lenses import LENSES, NarrativeLens, LensPhase, get_lens, lens_ids
from .models import (
    THREAD_LINK_RELATIONS,
    InvolvementMeasure,
    LensFitting,
    NarrativeThread,
    ProgressionPosition,
    ThreadChange,
    ThreadEvidence,
    ThreadLink,
    ThreadReading,
)
from .refs import (
    InadmissibleEvidenceError,
    RefTier,
    SourceRef,
    tier_of,
)
from .store import NarrativeStore

__all__ = [
    "LENSES",
    "THREAD_LINK_RELATIONS",
    "InadmissibleEvidenceError",
    "InvolvementMeasure",
    "LensFitting",
    "LensPhase",
    "NarrativeLens",
    "NarrativeStore",
    "NarrativeThread",
    "ProgressionPosition",
    "RefTier",
    "SourceRef",
    "ThreadChange",
    "ThreadEvidence",
    "ThreadLink",
    "ThreadReading",
    "get_lens",
    "lens_ids",
    "tier_of",
]
