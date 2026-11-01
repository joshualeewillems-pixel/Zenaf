"""Retroactive key-line tier migration (S4, audit Part XII §4).

Previously created story and quote-card artifacts were minted before
tiers existed: their records hold a key line with no statement of
whether those words are the user's. This migration re-verifies each
line against its source journal entry and stamps the record:

- verbatim span of the source entry → ``certified`` (with source)
- anything else, or source entry missing → ``dramatization``
  (uncheckable defaults to dramatization, NEVER to certified)

Idempotency: an artifact whose description already carries
``tier_migrated: true`` is skipped on later runs. A dry run computes
every outcome without writing anything.

Classification (structural, not by title — titles are editable):

- A STORY artifact is one whose description JSON contains "narrative".
  (Journal-entry artifacts carry an empty description; packs carry
  modality/style_line/preview; neither contains "narrative".)
- A QUOTE-CARD artifact is one whose description JSON contains
  "key_line" but NOT "narrative". Cards inherit their outcome from
  their parent story (stories migrate first, cards second): a card is
  certified only when its parent story is certified AND the card's
  line matches the story's certified line.

The migration corrects the RECORD. It cannot un-bake the curly quotes
out of an already-rendered card PNG; that is why the frontend renders
quotation presentation from the tier, not from the artifact kind —
a migrated dramatization card is displayed with an honest label, not
as a quotation, whatever pixels the old PNG holds.

This is a library function, deliberately NOT an HTTP route: the
operator runs it against the production stores and reviews the counts
before applying (dry run first). It never touches S0/S1 narrative
stores, training signals, or review claims.

RUN MECHANISM (Phase 4, stated explicitly for the merge decision):
this migration does NOT run automatically at boot or deploy. There is
no caller in the codebase, no route, and no startup wiring — the
operator invokes ``migrate_story_tiers`` explicitly (dry run first,
then a real run) and reviews the counts. Any future auto-run would be
a separate, separately authorized change.

Phase 4 addition: every story/card artifact the migration touches
(including already-migrated rows on backfill, and no-line rows) also
gets the provenance ``tier`` column stamped ``"dramatization"`` — the
artifact is Tier D by kind, whatever its key line graded as. The
column is never stamped on journal-entry artifacts (Tier E) or on
non-story/card artifacts.
"""

from __future__ import annotations

import json
from typing import Any

from local_ai.provenance.store import ProvenanceStore

from .store import PipelineStore
from .tiers import (
    TIER_CERTIFIED,
    TIER_DRAMATIZATION,
    is_verbatim_span,
    normalize_text,
)

_DRAMATIZATION_NOTE = (
    "Legacy line could not be verified against its source entry; "
    "re-labeled as dramatization, not a quotation."
)


def _description(artifact: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(artifact.get("description") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _is_story(data: dict[str, Any]) -> bool:
    return "narrative" in data


def _is_quote_card(data: dict[str, Any]) -> bool:
    return "key_line" in data and "narrative" not in data


def _parent_story_ids(
    prov_store: ProvenanceStore, artifact_id: str
) -> list[str]:
    return [link["parent_id"] for link in prov_store.parents_of(artifact_id)]


def _find_source_entry(
    pstore: PipelineStore,
    prov_store: ProvenanceStore,
    story: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """Recover the journal entry a story was made from, if it still exists."""
    # Post-fix stories record their source directly.
    source = data.get("key_line_source") or {}
    if source.get("entry_id"):
        entry = pstore.get_entry(source["entry_id"])
        if entry is not None:
            return entry
    # Legacy stories link to the entry's registry artifact.
    for parent_id in _parent_story_ids(prov_store, story["artifact_id"]):
        entry = pstore.get_entry_by_artifact_id(parent_id)
        if entry is not None:
            return entry
    return None


def migrate_story_tiers(
    pstore: PipelineStore,
    prov_store: ProvenanceStore,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Classify legacy story + quote-card artifacts by key-line tier.

    Returns {"counts": {...}, "details": [(artifact_id, kind, outcome)]}.
    With dry_run=True nothing is written; with dry_run=False the
    description JSON of each processed artifact is updated in place
    (all other description keys preserved).
    """
    counts: dict[str, int] = {
        "stories_certified": 0,
        "stories_dramatization": 0,
        "stories_no_line": 0,
        "stories_already_migrated": 0,
        "cards_certified": 0,
        "cards_dramatization": 0,
        "cards_no_line": 0,
        "cards_already_migrated": 0,
        "errors": 0,
    }
    details: list[tuple[str, str, str]] = []

    def record(artifact_id: str, kind: str, outcome: str) -> None:
        counts_key = f"{kind}_{outcome}"
        counts[counts_key] = counts.get(counts_key, 0) + 1
        details.append((artifact_id, kind, outcome))

    artifacts = prov_store.list_artifacts()
    stories: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for artifact in artifacts:
        data = _description(artifact)
        if data.get("tier_migrated"):
            # Phase 4: already-classified rows keep their
            # classification (idempotency), but a row migrated
            # before the provenance tier column existed gets its
            # column backfilled — description untouched, counts
            # unchanged. Only NULL is backfilled, never overwritten.
            if _is_story(data):
                record(artifact["artifact_id"], "stories", "already_migrated")
            elif _is_quote_card(data):
                record(artifact["artifact_id"], "cards", "already_migrated")
            else:
                continue
            if not dry_run and artifact.get("tier") is None:
                prov_store.update_artifact(
                    artifact["artifact_id"], tier="dramatization"
                )
            continue
        if _is_story(data):
            stories.append(artifact)
        elif _is_quote_card(data):
            cards.append(artifact)

    # Pass 1 — stories (cards inherit from these in pass 2).
    story_outcomes: dict[str, dict[str, Any]] = {}
    for story in stories:
        artifact_id = story["artifact_id"]
        try:
            data = _description(story)
            key_line = (data.get("key_line") or "").strip()
            if not key_line:
                outcome = "no_line"
                if not dry_run:
                    data["tier_migrated"] = True
                    prov_store.update_artifact(
                        artifact_id,
                        description=json.dumps(data),
                        # Phase 4: the artifact itself is Tier D
                        # by kind, whatever its key line graded as.
                        tier="dramatization",
                    )
                record(artifact_id, "stories", outcome)
                story_outcomes[artifact_id] = {"tier": None}
                continue
            entry = _find_source_entry(pstore, prov_store, story, data)
            if entry is not None and is_verbatim_span(key_line, entry["text"]):
                span = normalize_text(key_line)
                if not dry_run:
                    data["key_line"] = span
                    data["key_line_tier"] = TIER_CERTIFIED
                    data["key_line_source"] = {
                        "entry_id": entry["entry_id"],
                        "entry_artifact_id": entry["artifact_id"],
                    }
                    data["tier_migrated"] = True
                    prov_store.update_artifact(
                        artifact_id,
                        description=json.dumps(data),
                        # Phase 4: the artifact itself is Tier D
                        # by kind, whatever its key line graded as.
                        tier="dramatization",
                    )
                record(artifact_id, "stories", "certified")
                story_outcomes[artifact_id] = {
                    "tier": TIER_CERTIFIED,
                    "key_line": span,
                }
            else:
                if not dry_run:
                    data["key_line_tier"] = TIER_DRAMATIZATION
                    data["key_line_source"] = {}
                    data["tier_note"] = _DRAMATIZATION_NOTE
                    data["tier_migrated"] = True
                    prov_store.update_artifact(
                        artifact_id,
                        description=json.dumps(data),
                        # Phase 4: the artifact itself is Tier D
                        # by kind, whatever its key line graded as.
                        tier="dramatization",
                    )
                record(artifact_id, "stories", "dramatization")
                story_outcomes[artifact_id] = {"tier": TIER_DRAMATIZATION}
        except Exception:
            counts["errors"] += 1
            details.append((artifact_id, "stories", "error"))

    # Pass 2 — quote cards inherit from their parent story.
    for card in cards:
        artifact_id = card["artifact_id"]
        try:
            data = _description(card)
            key_line = (data.get("key_line") or "").strip()
            if not key_line:
                if not dry_run:
                    data["tier_migrated"] = True
                    prov_store.update_artifact(
                        artifact_id,
                        description=json.dumps(data),
                        # Phase 4: the artifact itself is Tier D
                        # by kind, whatever its key line graded as.
                        tier="dramatization",
                    )
                record(artifact_id, "cards", "no_line")
                continue
            certified = False
            source: dict[str, Any] = {}
            for parent_id in _parent_story_ids(prov_store, artifact_id):
                outcome = story_outcomes.get(parent_id)
                if outcome is None:
                    # Parent story was already migrated in an earlier
                    # run: read its stored tier instead.
                    parent = prov_store.get_artifact(parent_id)
                    if parent is None:
                        continue
                    parent_data = _description(parent)
                    if not _is_story(parent_data):
                        continue
                    outcome = {
                        "tier": parent_data.get("key_line_tier"),
                        "key_line": parent_data.get("key_line"),
                    }
                if (
                    outcome.get("tier") == TIER_CERTIFIED
                    and normalize_text(key_line)
                    == normalize_text(outcome.get("key_line") or "")
                ):
                    certified = True
                    parent = prov_store.get_artifact(parent_id)
                    if parent is not None:
                        source = _description(parent).get("key_line_source") or {}
                    break
            if not dry_run:
                if certified:
                    data["key_line_tier"] = TIER_CERTIFIED
                    data["key_line_source"] = source
                else:
                    data["key_line_tier"] = TIER_DRAMATIZATION
                    data["key_line_source"] = {}
                    data["tier_note"] = _DRAMATIZATION_NOTE
                data["tier_migrated"] = True
                prov_store.update_artifact(
                    artifact_id,
                    description=json.dumps(data),
                    # Phase 4: the artifact itself is Tier D
                    # by kind, whatever its key line graded as.
                    tier="dramatization",
                )
            record(
                artifact_id, "cards", "certified" if certified else "dramatization"
            )
        except Exception:
            counts["errors"] += 1
            details.append((artifact_id, "cards", "error"))

    return {"counts": counts, "details": details}
