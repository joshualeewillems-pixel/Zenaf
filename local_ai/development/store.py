"""The developmental store (Increment N1).

Own SQLite database (``data/development/development.db``), following
the per-domain convention (narrative, feedback, personality). Every
record family the native developmental loop produces lives here:

- ``character_authorship`` — WHO authored a character (C6: authorship
  semantics, distinct from platform administration; the owner gate
  is only the bootstrap enforcement for foundational characters).
- ``character_states`` — character-state version identities, typed
  as character states (``cs-…``), NEVER as commit shas; a git anchor
  may ride as transitional provenance only. States form an ancestry
  chain (``parent_state_id``) and carry a ``visibility`` PROPERTY
  (``author`` = author-scoped, ``published``) at full fidelity.
- ``perspective_material`` — revisable-standing perspective material
  at the signature layer. Append-only in the supersession sense:
  rows are never edited; revision / replacement / retirement are new
  facts (``status`` transitions recorded by new rows superseding old
  ones), so development is TRANSFORMATIVE, not accumulative (C1).
- ``authorial_acts`` — reach-marked authorial acts (conversation- or
  feedback-borne). An explicit correction's act IS its verdict
  (``confirmation_status='verdict'``); derived/ambiguous
  interpretations wait at ``'pending'`` on the author's confirmation
  list. Authority (account + authorship relation) is its own fact,
  never encoded in the reach.
- ``verdict_records`` — the standing change an act effected: before
  state (material + character-state identity, seized in the act) and
  after state. One per confirmed/verdict act.
- ``designations`` — the append-only designation ledger for the two
  ruled purposes. A designation confers NEITHER eligibility NOR
  training authorization; both flags are stored False on every row.
- ``preserved_components`` — Tier-1 preservation from the outset for
  authorized author–character interactions: the bounded,
  otherwise-unrecoverable prompt components, as rendered, keyed to
  the turn's assistant message + manifest fingerprint.
- ``summary_history`` — the Q4.3 leg: each thread-summary state
  preserved BEFORE it is overwritten in ``thread_state``.
- ``expression_links`` — C3 linkage: subsequent interactions,
  further corrections, unsuccessful expression, regressions, and
  generalization evidence associated with a developmental lineage.
  Links record relationships only — no evaluation, no conclusions.

Erasure: this store joins the erasure enumeration at creation —
``DEV_ERASURE_USER_TABLES`` names every user-keyed table and
:meth:`DevelopmentStore.erase_user_material` traverses the store's
dependency edges (act → verdict → states; designation → material;
version → ancestors; links → lineage) under the existing contracts:
erasure reduces rows to content-free tombstones where the row's
existence is itself lineage (states, acts, verdicts, designations)
and deletes content rows outright (preserved components, summary
history, expression-link notes).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "development"
DEFAULT_DB_PATH = DATA_DIR / "development.db"

#: The two founder-ruled designation purposes (R-6 / requirements
#: §12.6). Either may be designated without the other; neither
#: confers training authorization or eligibility.
RULED_PURPOSES: tuple[str, ...] = (
    "native_development",
    "future_model_adaptation",
)

#: The four developmental reaches (R-2: destinations, not chat
#: modes). ``None`` (unmarked) is the visitor-side default.
REACHES: tuple[str, ...] = (
    "immediate_expression",
    "relational_development",
    "character_development",
    "future_model_adaptation",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS character_authorship (
  character_id TEXT NOT NULL,
  author_id TEXT NOT NULL,
  relation TEXT NOT NULL DEFAULT 'author',
  created_at TEXT NOT NULL,
  PRIMARY KEY (character_id, author_id)
);
CREATE TABLE IF NOT EXISTS character_states (
  id TEXT PRIMARY KEY,
  character_id TEXT NOT NULL,
  author_id TEXT NOT NULL,
  visibility TEXT NOT NULL DEFAULT 'author',
  status TEXT NOT NULL DEFAULT 'current',
  parent_state_id TEXT,
  content_json TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  git_anchor TEXT,
  embodiment_json TEXT NOT NULL DEFAULT '{}',
  environment_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dev_states_character
  ON character_states (character_id, created_at, id);
CREATE TABLE IF NOT EXISTS perspective_material (
  id TEXT PRIMARY KEY,
  character_id TEXT NOT NULL,
  author_id TEXT NOT NULL,
  body TEXT NOT NULL,
  fidelity_class TEXT NOT NULL DEFAULT 'author_direct',
  standing TEXT NOT NULL DEFAULT 'revisable',
  status TEXT NOT NULL DEFAULT 'carried',
  supersedes_id TEXT,
  carriage_disposition TEXT NOT NULL DEFAULT 'carry',
  character_state_id TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dev_material_character
  ON perspective_material (character_id, created_at, id);
CREATE TABLE IF NOT EXISTS authorial_acts (
  id TEXT PRIMARY KEY,
  author_id TEXT NOT NULL,
  character_id TEXT NOT NULL,
  surface TEXT NOT NULL DEFAULT 'conversation',
  kind TEXT NOT NULL DEFAULT 'correction',
  reach TEXT,
  authority_json TEXT NOT NULL DEFAULT '{}',
  targets_json TEXT NOT NULL DEFAULT '[]',
  ops_json TEXT NOT NULL DEFAULT '[]',
  occasion_ref TEXT,
  verbatim TEXT NOT NULL DEFAULT '',
  confirmation_status TEXT NOT NULL DEFAULT 'verdict',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dev_acts_author
  ON authorial_acts (author_id, created_at, id);
CREATE TABLE IF NOT EXISTS verdict_records (
  id TEXT PRIMARY KEY,
  act_id TEXT NOT NULL UNIQUE,
  author_id TEXT NOT NULL,
  character_id TEXT NOT NULL,
  before_state_id TEXT,
  after_state_id TEXT,
  before_material_json TEXT NOT NULL DEFAULT '[]',
  after_material_json TEXT NOT NULL DEFAULT '[]',
  standing_change TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS designations (
  id TEXT PRIMARY KEY,
  author_id TEXT NOT NULL,
  material_ref TEXT NOT NULL,
  purpose TEXT NOT NULL,
  origin_time TEXT NOT NULL,
  designation_time TEXT NOT NULL,
  confers_eligibility INTEGER NOT NULL DEFAULT 0,
  confers_training_authorization INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dev_designations_author
  ON designations (author_id, created_at, id);
CREATE TABLE IF NOT EXISTS preserved_components (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  archetype_id TEXT NOT NULL,
  assistant_message_id TEXT,
  manifest_prompt_sha256 TEXT,
  components_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dev_preserved_user
  ON preserved_components (user_id, created_at, id);
CREATE TABLE IF NOT EXISTS summary_history (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  archetype_id TEXT NOT NULL,
  summary TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dev_summary_user
  ON summary_history (user_id, conversation_id, archetype_id, created_at);
CREATE TABLE IF NOT EXISTS expression_links (
  id TEXT PRIMARY KEY,
  author_id TEXT NOT NULL,
  character_id TEXT NOT NULL,
  lineage_act_id TEXT,
  linked_kind TEXT NOT NULL,
  ref TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dev_links_author
  ON expression_links (author_id, character_id, created_at, id);
"""

#: Erasure enumeration for this store (requirements X-2 / §12.7):
#: every user-keyed table, named at creation. The dependency edges
#: erasure traverses: act -> verdict -> before/after states;
#: designation -> designated material; state -> ancestor states;
#: expression link -> its lineage act.
DEV_ERASURE_USER_TABLES: tuple[str, ...] = (
    "character_authorship",
    "character_states",
    "perspective_material",
    "authorial_acts",
    "verdict_records",
    "designations",
    "preserved_components",
    "summary_history",
    "expression_links",
)

#: Tables whose rows are lineage: erasure reduces them to
#: content-free tombstones (ids + timestamps only) rather than
#: deleting the row, so the fact that a record existed — and was
#: erased — survives without its content.
_TOMBSTONE_TABLES: dict[str, tuple[str, ...]] = {
    # table -> content columns blanked on erasure
    "character_states": ("content_json", "embodiment_json", "environment_json"),
    "perspective_material": ("body",),
    "authorial_acts": ("verbatim", "targets_json", "authority_json", "ops_json"),
    "verdict_records": ("before_material_json", "after_material_json", "standing_change"),
    "designations": ("material_ref",),
}

#: Tables deleted outright on erasure (pure content, no lineage role).
_DELETE_TABLES: tuple[str, ...] = (
    "preserved_components",
    "summary_history",
    "expression_links",
    "character_authorship",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:20]}"


def default_db_path() -> Path:
    override = os.environ.get("ZENAF_DEV_DB_PATH")
    if override:
        return Path(override)
    return DEFAULT_DB_PATH


class DevelopmentStore:
    """SQLite-backed store for the N1 developmental loop records."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- authorship (C6) ------------------------------------------------

    def register_authorship(
        self, character_id: str, author_id: str, relation: str = "author"
    ) -> None:
        """Record an authorship relation over a character.

        This is the data model's authorship semantics: any account
        may be the author of characters it created. Platform
        administration never appears here.
        """
        if not character_id or not author_id:
            raise ValueError("character_id and author_id are required")
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO character_authorship "
                "(character_id, author_id, relation, created_at) VALUES (?, ?, ?, ?)",
                (character_id, author_id, relation or "author", _utcnow()),
            )
            self._conn.commit()

    def authorship_relation(self, character_id: str, author_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT relation FROM character_authorship "
                "WHERE character_id = ? AND author_id = ?",
                (character_id, author_id),
            ).fetchone()
        return row["relation"] if row else None

    # -- character states (family 3) -------------------------------------

    def mint_character_state(
        self,
        *,
        character_id: str,
        author_id: str,
        content: dict[str, Any],
        visibility: str = "author",
        parent_state_id: str | None = None,
        git_anchor: str | None = None,
        embodiment: dict[str, Any] | None = None,
        environment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mint a character-state identity against a content-complete
        referent.

        Content-completeness is a PRECONDITION of minting, not a
        carriable deficit (requirements §12.1, family 3): ``content``
        must be a mapping carrying a non-empty ``material`` list —
        the state's actual definition material — or minting is
        refused. The identity is typed as a character state
        (``cs-…``); a git anchor, when supplied, is transitional
        provenance only and never the identity.
        """
        if not isinstance(content, dict) or not content.get("material"):
            raise ValueError(
                "character state minting requires a content-complete "
                "referent: a mapping with a non-empty 'material' list"
            )
        if visibility not in ("author", "published"):
            raise ValueError("visibility must be 'author' or 'published'")
        content_json = json.dumps(content, ensure_ascii=True, sort_keys=True)
        state_id = _new_id("cs")
        now = _utcnow()
        with self._lock:
            # The parent, if any, must be a state of the SAME
            # character by the SAME author — a state chain never
            # crosses characters or authors — and stops being the
            # current state.
            if parent_state_id:
                parent = self._conn.execute(
                    "SELECT character_id, author_id FROM character_states "
                    "WHERE id = ?",
                    (parent_state_id,),
                ).fetchone()
                if parent is None:
                    raise ValueError(
                        f"parent_state_id names no state: {parent_state_id!r}"
                    )
                if (
                    parent["character_id"] != character_id
                    or parent["author_id"] != author_id
                ):
                    raise ValueError(
                        "parent state belongs to a different character or author"
                    )
                self._conn.execute(
                    "UPDATE character_states SET status = 'superseded' "
                    "WHERE id = ? AND status = 'current'",
                    (parent_state_id,),
                )
            self._conn.execute(
                "INSERT INTO character_states (id, character_id, author_id, "
                "visibility, status, parent_state_id, content_json, "
                "content_sha256, git_anchor, embodiment_json, "
                "environment_json, created_at) "
                "VALUES (?, ?, ?, ?, 'current', ?, ?, ?, ?, ?, ?, ?)",
                (
                    state_id,
                    character_id,
                    author_id,
                    visibility,
                    parent_state_id,
                    content_json,
                    hashlib.sha256(content_json.encode("utf-8")).hexdigest(),
                    git_anchor,
                    json.dumps(embodiment or {}, ensure_ascii=True),
                    json.dumps(environment or {}, ensure_ascii=True),
                    now,
                ),
            )
            self._conn.commit()
        return self.get_character_state(state_id)  # type: ignore[return-value]

    def get_character_state(self, state_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM character_states WHERE id = ?", (state_id,)
            ).fetchone()
        return _state_dict(row) if row else None

    def current_character_state(
        self, character_id: str, *, viewer_id: str | None = None
    ) -> dict[str, Any] | None:
        """The current state of a character, as visible to ``viewer_id``.

        Published states are visible to anyone; author-scoped states
        only to their author (visibility is a property of the record,
        served at full fidelity within the author's jurisdiction).
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM character_states WHERE character_id = ? "
                "AND status = 'current' ORDER BY created_at DESC, id DESC",
                (character_id,),
            ).fetchall()
        for row in rows:
            state = _state_dict(row)
            if state["visibility"] == "published" or state["author_id"] == viewer_id:
                return state
        return None

    def set_state_status(self, state_id: str, status: str) -> None:
        if status not in ("current", "superseded", "retired"):
            raise ValueError("status must be current, superseded, or retired")
        with self._lock:
            self._conn.execute(
                "UPDATE character_states SET status = ? WHERE id = ?",
                (status, state_id),
            )
            self._conn.commit()

    def publish_state(self, state_id: str, author_id: str) -> dict[str, Any] | None:
        """Publish one state, by its author's act alone.

        Publication is per-version: ancestors keep their own
        visibility (a successor's publication publishes no
        ancestors, and extinguishes no derivative obligations).
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM character_states WHERE id = ? AND author_id = ?",
                (state_id, author_id),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE character_states SET visibility = 'published' WHERE id = ?",
                (state_id,),
            )
            self._conn.commit()
        return self.get_character_state(state_id)

    # -- perspective material (family 4 / C1) ----------------------------

    def add_perspective_material(
        self,
        *,
        character_id: str,
        author_id: str,
        body: str,
        fidelity_class: str = "author_direct",
        supersedes_id: str | None = None,
        carriage_disposition: str = "carry",
        character_state_id: str | None = None,
    ) -> dict[str, Any]:
        """Add revisable-standing perspective material.

        When ``supersedes_id`` names existing material, that row's
        status becomes ``superseded`` (or ``replaced`` when the new
        row is a replacement in kind) — the old text is never edited;
        supersession is the mechanism, so development can revise,
        replace, and retire rather than only accumulate (C1).
        """
        if not (body or "").strip():
            raise ValueError("perspective material body must be non-empty")
        material_id = _new_id("pm")
        now = _utcnow()
        with self._lock:
            if supersedes_id:
                self._conn.execute(
                    "UPDATE perspective_material SET status = 'replaced' "
                    "WHERE id = ? AND status = 'carried'",
                    (supersedes_id,),
                )
            self._conn.execute(
                "INSERT INTO perspective_material (id, character_id, author_id, "
                "body, fidelity_class, standing, status, supersedes_id, "
                "carriage_disposition, character_state_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'revisable', 'carried', ?, ?, ?, ?)",
                (
                    material_id,
                    character_id,
                    author_id,
                    body,
                    fidelity_class,
                    supersedes_id,
                    carriage_disposition,
                    character_state_id,
                    now,
                ),
            )
            self._conn.commit()
        return self.get_perspective_material(material_id)  # type: ignore[return-value]

    def set_material_state(self, material_id: str, state_id: str | None) -> None:
        """Name the character state a material row belongs to (the
        carriage stamp's store half: what was served is provable
        against the state in force)."""
        with self._lock:
            self._conn.execute(
                "UPDATE perspective_material SET character_state_id = ? "
                "WHERE id = ?",
                (state_id, material_id),
            )
            self._conn.commit()

    def retire_perspective_material(self, material_id: str, author_id: str) -> bool:
        """Retire carried material (C1): it stops being carried; the
        row remains as lineage with status ``retired``."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE perspective_material SET status = 'retired' "
                "WHERE id = ? AND author_id = ? AND status = 'carried'",
                (material_id, author_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def get_perspective_material(self, material_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM perspective_material WHERE id = ?", (material_id,)
            ).fetchone()
        return dict(row) if row else None

    def carried_material(
        self, character_id: str, *, author_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Currently carried (revisable-standing) material, oldest first."""
        with self._lock:
            if author_id:
                rows = self._conn.execute(
                    "SELECT * FROM perspective_material WHERE character_id = ? "
                    "AND author_id = ? AND status = 'carried' "
                    "ORDER BY created_at ASC, id ASC",
                    (character_id, author_id),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM perspective_material WHERE character_id = ? "
                    "AND status = 'carried' ORDER BY created_at ASC, id ASC",
                    (character_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def all_material(self, character_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM perspective_material WHERE character_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (character_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- authorial acts + verdict records (families 1–2) ------------------

    def record_act(
        self,
        *,
        author_id: str,
        character_id: str,
        verbatim: str,
        kind: str = "correction",
        surface: str = "conversation",
        reach: str | None = None,
        authority: dict[str, Any] | None = None,
        targets: list[dict[str, Any]] | None = None,
        ops: list[dict[str, Any]] | None = None,
        occasion_ref: str | None = None,
        confirmation_status: str = "verdict",
    ) -> dict[str, Any]:
        if reach is not None and reach not in REACHES:
            raise ValueError(f"unknown reach: {reach!r}")
        if confirmation_status not in ("verdict", "pending"):
            raise ValueError("confirmation_status must be 'verdict' or 'pending'")
        act_id = _new_id("act")
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO authorial_acts (id, author_id, character_id, "
                "surface, kind, reach, authority_json, targets_json, "
                "ops_json, occasion_ref, verbatim, confirmation_status, "
                "created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    act_id,
                    author_id,
                    character_id,
                    surface,
                    kind,
                    reach,
                    json.dumps(authority or {}, ensure_ascii=True),
                    json.dumps(targets or [], ensure_ascii=True),
                    json.dumps(ops or [], ensure_ascii=True),
                    occasion_ref,
                    verbatim or "",
                    confirmation_status,
                    now,
                ),
            )
            self._conn.commit()
        return self.get_act(act_id)  # type: ignore[return-value]

    def get_act(self, act_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM authorial_acts WHERE id = ?", (act_id,)
            ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["authority"] = json.loads(out.pop("authority_json") or "{}")
        out["targets"] = json.loads(out.pop("targets_json") or "[]")
        out["ops"] = json.loads(out.pop("ops_json") or "[]")
        return out

    def set_act_confirmation(self, act_id: str, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE authorial_acts SET confirmation_status = ? WHERE id = ?",
                (status, act_id),
            )
            self._conn.commit()

    def pending_confirmations(self, author_id: str) -> list[dict[str, Any]]:
        """The author-only confirmation list: derived or ambiguous
        interpretations awaiting the author's confirmation."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM authorial_acts WHERE author_id = ? "
                "AND confirmation_status = 'pending' "
                "ORDER BY created_at ASC, id ASC",
                (author_id,),
            ).fetchall()
        return [self.get_act(r["id"]) for r in rows]  # type: ignore[misc]

    def record_verdict(
        self,
        *,
        act_id: str,
        author_id: str,
        character_id: str,
        before_state_id: str | None,
        after_state_id: str | None,
        before_material: list[dict[str, Any]],
        after_material: list[dict[str, Any]],
        standing_change: str,
    ) -> dict[str, Any]:
        verdict_id = _new_id("vrd")
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO verdict_records (id, act_id, author_id, "
                "character_id, before_state_id, after_state_id, "
                "before_material_json, after_material_json, standing_change, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    verdict_id,
                    act_id,
                    author_id,
                    character_id,
                    before_state_id,
                    after_state_id,
                    json.dumps(before_material, ensure_ascii=True),
                    json.dumps(after_material, ensure_ascii=True),
                    standing_change,
                    now,
                ),
            )
            self._conn.commit()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM verdict_records WHERE id = ?", (verdict_id,)
            ).fetchone()
        out = dict(row)
        out["before_material"] = json.loads(out.pop("before_material_json") or "[]")
        out["after_material"] = json.loads(out.pop("after_material_json") or "[]")
        return out

    def verdict_for_act(self, act_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM verdict_records WHERE act_id = ?", (act_id,)
            ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["before_material"] = json.loads(out.pop("before_material_json") or "[]")
        out["after_material"] = json.loads(out.pop("after_material_json") or "[]")
        return out

    # -- designations (family 5) ------------------------------------------

    def designate(
        self,
        *,
        author_id: str,
        material_ref: str,
        purpose: str,
        origin_time: str | None = None,
    ) -> dict[str, Any]:
        """Designate the author's own material for one ruled purpose.

        Designation is a direct act by the author, not a request:
        no approval is sought or recorded. It confers NEITHER
        eligibility NOR training authorization — both flags are
        written False and are not settable through this API.
        Retroactive designation is supported with honest temporal
        provenance: ``origin_time`` (when the material originated)
        and the designation time are both recorded; designation is
        claimed from the designation act, never backdated.
        """
        if purpose not in RULED_PURPOSES:
            raise ValueError(
                f"purpose must be one of the ruled purposes {RULED_PURPOSES}"
            )
        if not material_ref:
            raise ValueError("material_ref is required")
        now = _utcnow()
        designation_id = _new_id("dsg")
        with self._lock:
            self._conn.execute(
                "INSERT INTO designations (id, author_id, material_ref, "
                "purpose, origin_time, designation_time, confers_eligibility, "
                "confers_training_authorization, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?)",
                (
                    designation_id,
                    author_id,
                    material_ref,
                    purpose,
                    origin_time or now,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM designations WHERE id = ?", (designation_id,)
            ).fetchone()
        out = dict(row)
        out["confers_eligibility"] = bool(out["confers_eligibility"])
        out["confers_training_authorization"] = bool(
            out["confers_training_authorization"]
        )
        return out

    def list_designations(self, author_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM designations WHERE author_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (author_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["confers_eligibility"] = bool(d["confers_eligibility"])
            d["confers_training_authorization"] = bool(
                d["confers_training_authorization"]
            )
            out.append(d)
        return out

    # -- preservation (Tier 1) + summary history (Q4.3) -------------------

    def preserve_components(
        self,
        *,
        user_id: str,
        conversation_id: str,
        archetype_id: str,
        assistant_message_id: str | None,
        manifest_prompt_sha256: str | None,
        components: dict[str, Any],
    ) -> str:
        """Preserve one author turn's bounded unrecoverable
        components, as rendered, keyed to its manifest."""
        row_id = _new_id("prv")
        with self._lock:
            self._conn.execute(
                "INSERT INTO preserved_components (id, user_id, "
                "conversation_id, archetype_id, assistant_message_id, "
                "manifest_prompt_sha256, components_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row_id,
                    user_id,
                    conversation_id,
                    archetype_id,
                    assistant_message_id,
                    manifest_prompt_sha256,
                    json.dumps(components, ensure_ascii=True),
                    _utcnow(),
                ),
            )
            self._conn.commit()
        return row_id

    def preserved_for_message(self, assistant_message_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM preserved_components WHERE assistant_message_id = ?",
                (assistant_message_id,),
            ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["components"] = json.loads(out.pop("components_json") or "{}")
        return out

    def preserve_summary(
        self, *, user_id: str, conversation_id: str, archetype_id: str, summary: str
    ) -> None:
        """Q4.3 leg: preserve a summary state BEFORE it is
        overwritten in thread_state (same keying as thread_state)."""
        if not summary:
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO summary_history (id, user_id, conversation_id, "
                "archetype_id, summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _new_id("sum"),
                    user_id,
                    conversation_id,
                    archetype_id,
                    summary,
                    _utcnow(),
                ),
            )
            self._conn.commit()

    def summary_history(
        self, user_id: str, conversation_id: str, archetype_id: str
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM summary_history WHERE user_id = ? AND "
                "conversation_id = ? AND archetype_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (user_id, conversation_id, archetype_id),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- expression links (C3) ---------------------------------------------

    def link_expression(
        self,
        *,
        author_id: str,
        character_id: str,
        linked_kind: str,
        lineage_act_id: str | None = None,
        ref: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        """Associate a later event with a developmental lineage.

        Kinds: ``interaction``, ``correction``, ``expression``,
        ``unsuccessful_expression``, ``regression``,
        ``generalization``. A link records a RELATIONSHIP for future
        examination — it manufactures no evaluation or conclusion.
        """
        allowed = {
            "interaction",
            "correction",
            "expression",
            "unsuccessful_expression",
            "regression",
            "generalization",
        }
        if linked_kind not in allowed:
            raise ValueError(f"unknown linked_kind: {linked_kind!r}")
        link_id = _new_id("lnk")
        with self._lock:
            self._conn.execute(
                "INSERT INTO expression_links (id, author_id, character_id, "
                "lineage_act_id, linked_kind, ref, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    link_id,
                    author_id,
                    character_id,
                    lineage_act_id,
                    linked_kind,
                    ref,
                    note,
                    _utcnow(),
                ),
            )
            self._conn.commit()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM expression_links WHERE id = ?", (link_id,)
            ).fetchone()
        return dict(row)

    def expression_links_for_act(self, lineage_act_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM expression_links WHERE lineage_act_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (lineage_act_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- erasure ------------------------------------------------------------

    def erase_user_material(self, user_id: str) -> dict[str, int]:
        """Erase one user's developmental material under the existing
        contracts: lineage rows reduce to content-free tombstones;
        pure-content rows are deleted. Traverses this store's
        dependency edges by construction — every table in
        ``DEV_ERASURE_USER_TABLES`` is treated in this one operation,
        keyed by the user's author/user id wherever it appears.
        Returns per-table affected counts.
        """
        counts: dict[str, int] = {}
        with self._lock:
            for table in _DELETE_TABLES:
                key = "author_id" if table == "character_authorship" else "user_id"
                if table == "expression_links":
                    key = "author_id"
                cur = self._conn.execute(
                    f"DELETE FROM {table} WHERE {key} = ?", (user_id,)
                )
                counts[table] = cur.rowcount
            for table, columns in _TOMBSTONE_TABLES.items():
                sets = ", ".join(f"{c} = ''" for c in columns)
                # Tombstone only rows not already tombstoned.
                cur = self._conn.execute(
                    f"UPDATE {table} SET {sets} WHERE author_id = ?",
                    (user_id,),
                )
                counts[table] = cur.rowcount
            self._conn.commit()
        return counts


def _state_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    out["content"] = json.loads(out.pop("content_json") or "{}")
    out["embodiment"] = json.loads(out.pop("embodiment_json") or "{}")
    out["environment"] = json.loads(out.pop("environment_json") or "{}")
    return out
