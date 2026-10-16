"""Multi-strand entity weighting — people, projects, tasks, assets, and jobs
get 7-strand weight vectors instead of single categories.

"I hang out with X for wisdom and Y for jokes" -> a person weights toward
Logic and Voice. "This project exercises Logic and Hands" -> a project
weights toward Logic and Hands. "I use these tools for Eye" -> an asset
weights toward Eye.

This is the multi-frame routing principle applied to entities: everything
in Zenaf routes to multiple strands with weights. Single-category filing
is a legacy concept.

Design: ~/workspace/zenaf-council-archetype-plan.md §5
Approved by Joshua 2026-10-16.

Storage: a standalone ``strand_weightings`` table in the Vision Execution
SQLite DB, keyed by (user_id, entity_type, entity_id). Entities without a
row return ``weights=None`` — unknown is honest, never zero.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from local_ai.council.archetypes import PLAIN_TO_KEY


#: Entity kinds that can carry strand weights.
ENTITY_TYPES: tuple[str, ...] = ("person", "project", "task", "asset", "job")

#: Where a weighting came from.
SOURCES: tuple[str, ...] = ("user_stated", "inferred", "mined")

#: Epsilon for weight-sum validation.
_SUM_EPSILON = 1e-6


def validate_weights(weights: dict) -> dict[str, float]:
    """Validate a strand weight mapping and return it normalized.

    Keys must be the 7 plain-spoken strand names (Voice, Logic, Eye, Ear,
    Hands, Heart, Compass); values must be non-negative numbers summing
    to 1.0. Returns a new dict with all 7 strands present (missing -> 0.0).

    Raises ValueError with a plain-language message on any violation.
    """
    if not isinstance(weights, dict) or not weights:
        raise ValueError("weights must be a non-empty mapping of strand name to weight")
    unknown = [k for k in weights if k not in PLAIN_TO_KEY]
    if unknown:
        raise ValueError(
            f"unknown strand names: {sorted(unknown)} — "
            f"expected {sorted(PLAIN_TO_KEY)}"
        )
    full: dict[str, float] = {}
    for name in PLAIN_TO_KEY:
        raw = weights.get(name, 0.0)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"weight for {name} is not a number: {raw!r}")
        if val < 0:
            raise ValueError(f"weight for {name} is negative: {val}")
        full[name] = val
    total = sum(full.values())
    if total <= 0:
        raise ValueError("weights sum to 0 — at least one strand must have a positive weight")
    if abs(total - 1.0) > _SUM_EPSILON:
        raise ValueError(
            f"weights sum to {total:.4f}, expected 1.0 "
            f"(off by {abs(total - 1.0):.4f})"
        )
    return full


def uniform_weights() -> dict[str, float]:
    """Even 1/7 split — a starting guess, not a claim of knowledge."""
    share = 1.0 / len(PLAIN_TO_KEY)
    return {name: share for name in PLAIN_TO_KEY}


def suggest_weights(strand_scores: dict) -> dict[str, float] | None:
    """Inference hook: turn raw strand scores into a validated weight vector.

    Returns None when the scores carry no usable signal (nothing to infer).
    Callers store the result with source="inferred" — the user confirms.
    """
    if not strand_scores:
        return None
    try:
        return validate_weights(dict(strand_scores))
    except ValueError:
        return None


@dataclass
class StrandWeighting:
    """A strand weight vector attached to one entity."""

    entity_id: str
    entity_type: str
    strand_weights: dict[str, float] | None  # None = never weighed (unknown, honest)
    source: str | None
    updated_at: str

    def __post_init__(self) -> None:
        if self.entity_type not in ENTITY_TYPES:
            raise ValueError(
                f"unknown entity_type {self.entity_type!r} — expected one of {list(ENTITY_TYPES)}"
            )
        if self.source is not None and self.source not in SOURCES:
            raise ValueError(
                f"unknown source {self.source!r} — expected one of {list(SOURCES)}"
            )
        if self.strand_weights is not None:
            self.strand_weights = validate_weights(self.strand_weights)

    def dominant(self, n: int = 2) -> list[tuple[str, float]]:
        """Top-n strands by weight, for display."""
        if not self.strand_weights:
            return []
        return sorted(self.strand_weights.items(), key=lambda kv: kv[1], reverse=True)[:n]

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "weights": self.strand_weights,
            "source": self.source,
            "updated_at": self.updated_at,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    # Imported lazily to avoid import cycles at module load.
    from local_ai.vision_execution.storage import get_connection

    return get_connection()


def set_entity_strands(
    user_id: str,
    entity_type: str,
    entity_id: str,
    weights: dict,
    source: str = "user_stated",
) -> StrandWeighting:
    """Record (or replace) a strand weight vector for an entity.

    Raises ValueError on bad entity_type, source, or weights.
    """
    if entity_type not in ENTITY_TYPES:
        raise ValueError(
            f"unknown entity_type {entity_type!r} — expected one of {list(ENTITY_TYPES)}"
        )
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r} — expected one of {list(SOURCES)}")
    full = validate_weights(weights)
    updated_at = _now_iso()
    conn = _conn()
    conn.execute(
        """
        INSERT INTO strand_weightings (user_id, entity_type, entity_id, weights_json, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (user_id, entity_type, entity_id)
        DO UPDATE SET weights_json = excluded.weights_json,
                      source = excluded.source,
                      updated_at = excluded.updated_at
        """,
        (user_id, entity_type, entity_id, json.dumps(full), source, updated_at),
    )
    conn.commit()
    return StrandWeighting(
        entity_id=entity_id,
        entity_type=entity_type,
        strand_weights=full,
        source=source,
        updated_at=updated_at,
    )


def get_entity_strands(
    user_id: str, entity_type: str, entity_id: str
) -> StrandWeighting:
    """Fetch the recorded weights for an entity.

    Never raises for missing rows: entities that were never weighed return
    ``strand_weights=None`` — unknown is honest, never zero.
    """
    if entity_type not in ENTITY_TYPES:
        raise ValueError(
            f"unknown entity_type {entity_type!r} — expected one of {list(ENTITY_TYPES)}"
        )
    conn = _conn()
    row = conn.execute(
        """
        SELECT weights_json, source, updated_at FROM strand_weightings
        WHERE user_id = ? AND entity_type = ? AND entity_id = ?
        """,
        (user_id, entity_type, entity_id),
    ).fetchone()
    if row is None:
        return StrandWeighting(
            entity_id=entity_id,
            entity_type=entity_type,
            strand_weights=None,
            source=None,
            updated_at=_now_iso(),
        )
    try:
        weights = json.loads(row[0] or "{}") or None
    except (json.JSONDecodeError, TypeError):
        weights = None
    return StrandWeighting(
        entity_id=entity_id,
        entity_type=entity_type,
        strand_weights=weights,
        source=row[1] or None,
        updated_at=row[2] or _now_iso(),
    )


def clear_entity_strands(user_id: str, entity_type: str, entity_id: str) -> bool:
    """Remove a recorded weighting. Returns True if a row was deleted."""
    conn = _conn()
    cur = conn.execute(
        """
        DELETE FROM strand_weightings
        WHERE user_id = ? AND entity_type = ? AND entity_id = ?
        """,
        (user_id, entity_type, entity_id),
    )
    conn.commit()
    return cur.rowcount > 0
