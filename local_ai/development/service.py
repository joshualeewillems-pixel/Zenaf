"""The developmental service (Increment N1).

The governed operations over :mod:`local_ai.development.store`:

- **Authorship resolution (C6).** Authorship is a relation between
  an account and a character, recorded in the store. Platform
  administration appears nowhere in the semantics: the platform
  owner account is merely the BOOTSTRAP author of the seven
  foundational characters (the owner-gate precedent), and any
  account may be registered as the author of characters it created
  — independently owned characters need no architectural change.
- **Correction-as-verdict (R-1).** An explicit authorial correction
  IS its verdict: recording it applies its material operations and
  writes the verdict record (before state seized in the act, after
  state minted) in the same operation — no second confirmation act.
  Derived or ambiguous interpretations are recorded as ``pending``
  and take effect only on the author's confirmation.
- **Carriage.** Carried perspective material renders as one bounded
  block, framed as revisable standing, for the author's own turns.
- **Pinned-state resolution (C4).** A caller may resolve a
  DESIGNATED character-state identity (a pinned state, as an
  evaluation or experiment does); pinned resolution returns that
  state exactly, independent of the author's current developmental
  state. Unpinned resolution returns the current state as visible
  to the viewer.

Everything here is inert unless the caller acts: the Talk path
consults this module only under ``ZENAF_NATIVE_DEVELOPMENT``.
No model calls, no evaluation, no conclusions are manufactured —
expression links record relationships only (C3).
"""

from __future__ import annotations

from typing import Any

from .store import DevelopmentStore

#: The seven foundational characters (archetype ids). Their author
#: is the platform owner account, by bootstrap — recorded in the
#: store as an ordinary authorship relation on first use, after
#: which the store is the authority.
FOUNDATIONAL_CHARACTERS: tuple[str, ...] = (
    "mentor",
    "champion",
    "guardian",
    "ambassador",
    "conductor",
    "skeptic",
    "maverick",
)

#: Carriage budget for the perspective block: the block is one
#: bounded section inside the existing prompt budget discipline.
MAX_CARRIAGE_CHARS = 2000

_CARRIAGE_HEADER = (
    "Developmental perspective (revisable standing — the author's "
    "current, revisable direction for this character; it informs "
    "your judgment, it is not a script and does not override your "
    "canonical definition):"
)


class AuthorshipError(PermissionError):
    """Raised when an account acts developmentally over a character
    it does not author. Fail-closed: no record is written."""


def _platform_owner_id() -> str | None:
    try:
        from local_ai.vision_execution.storage import get_owner_user_id

        return get_owner_user_id()
    except Exception:
        return None


class DevelopmentService:
    def __init__(self, store: DevelopmentStore | None = None) -> None:
        self.store = store or DevelopmentStore()

    # -- authorship (C6) ---------------------------------------------------

    def authorship_relation(
        self, *, user_id: str, character_id: str
    ) -> str | None:
        """The caller's authorship relation over a character, if any.

        Store-recorded relations win. For a foundational character
        with no recorded relation, the platform owner is its
        bootstrap author; that relation is recorded on first
        developmental use so the store becomes the authority.
        """
        relation = self.store.authorship_relation(character_id, user_id)
        if relation:
            return relation
        if (
            character_id in FOUNDATIONAL_CHARACTERS
            and user_id
            and user_id == _platform_owner_id()
        ):
            return "author"
        return None

    def is_author(self, *, user_id: str, character_id: str) -> bool:
        return self.authorship_relation(user_id=user_id, character_id=character_id) is not None

    def _require_author(self, *, user_id: str, character_id: str) -> str:
        relation = self.authorship_relation(user_id=user_id, character_id=character_id)
        if relation is None:
            raise AuthorshipError(
                f"account {user_id!r} does not author character {character_id!r}"
            )
        # Record the bootstrap relation so the store is the
        # authority from the first developmental act onward.
        self.store.register_authorship(character_id, user_id, relation)
        return relation

    def authority_facts(self, *, user_id: str, character_id: str) -> dict[str, Any]:
        """Authority as its own recorded fact (R-2): the account and
        its authorship relation — never encoded in the reach."""
        relation = self.authorship_relation(user_id=user_id, character_id=character_id)
        return {"account_id": user_id, "authorship_relation": relation}

    # -- correction-as-verdict (families 1–2) -------------------------------

    def record_correction(
        self,
        *,
        author_id: str,
        character_id: str,
        verbatim: str,
        ops: list[dict[str, Any]] | None = None,
        reach: str | None = "character_development",
        surface: str = "conversation",
        kind: str = "correction",
        targets: list[dict[str, Any]] | None = None,
        occasion_ref: str | None = None,
        derived: bool = False,
    ) -> dict[str, Any]:
        """Record an authorial act over a character the caller authors.

        ``ops`` are the material operations the act directs, each a
        dict: ``{"op": "add", "body": …}``,
        ``{"op": "replace", "material_id": …, "body": …}``,
        ``{"op": "revise", "material_id": …, "body": …}`` (alias of
        replace), or ``{"op": "retire", "material_id": …}``. An
        explicit correction (``derived=False``) is its own verdict:
        the ops apply now and a verdict record is written. A derived
        or ambiguous interpretation (``derived=True``) is recorded
        ``pending`` — nothing applies — until :meth:`confirm_act`.
        A creative act needs no occasion and may carry no ops at all
        (C5): it is recorded, with its reach, as directed development
        whose expression is a separate, later fact (C3).
        """
        relation = self._require_author(
            user_id=author_id, character_id=character_id
        )
        ops = list(ops or [])
        act = self.store.record_act(
            author_id=author_id,
            character_id=character_id,
            verbatim=verbatim,
            kind=kind,
            surface=surface,
            reach=reach,
            authority={
                "account_id": author_id,
                "authorship_relation": relation,
            },
            targets=targets,
            ops=ops,
            occasion_ref=occasion_ref,
            confirmation_status="pending" if derived else "verdict",
        )
        if derived:
            return {"act": act, "verdict": None}
        verdict = self._apply_act(act)
        return {"act": act, "verdict": verdict}

    def confirm_act(self, *, act_id: str, author_id: str) -> dict[str, Any]:
        """Confirm a pending (derived/ambiguous) act: its ops apply
        and its verdict record is written, by the author's act."""
        act = self.store.get_act(act_id)
        if act is None or act["author_id"] != author_id:
            raise AuthorshipError("no such pending act for this author")
        if act["confirmation_status"] != "pending":
            raise ValueError("act is not pending confirmation")
        self._require_author(user_id=author_id, character_id=act["character_id"])
        verdict = self._apply_act(act)
        self.store.set_act_confirmation(act_id, "verdict")
        return {"act": self.store.get_act(act_id), "verdict": verdict}

    def pending_confirmations(self, author_id: str) -> list[dict[str, Any]]:
        return self.store.pending_confirmations(author_id)

    def _apply_act(self, act: dict[str, Any]) -> dict[str, Any]:
        """Apply an act's material ops and write its verdict record.

        The BEFORE state is seized here, in the act: the carried
        material as it stands and the character-state identity in
        force, captured before any op runs. The AFTER state is a
        newly minted character state whose content is the resulting
        carried material — content-complete by construction (the
        material itself), typed as a character state, parented on
        the before state.
        """
        author_id = act["author_id"]
        character_id = act["character_id"]
        before_state = self.store.current_character_state(
            character_id, viewer_id=author_id
        )
        before_material = self.store.carried_material(
            character_id, author_id=author_id
        )
        standing_changes: list[str] = []
        for op in act.get("ops") or []:
            kind = (op.get("op") or "").strip().lower()
            if kind == "add":
                row = self.store.add_perspective_material(
                    character_id=character_id,
                    author_id=author_id,
                    body=op.get("body") or "",
                    fidelity_class=op.get("fidelity_class") or "author_direct",
                    carriage_disposition=op.get("carriage_disposition") or "carry",
                )
                standing_changes.append(f"added:{row['id']}")
            elif kind in ("replace", "revise"):
                row = self.store.add_perspective_material(
                    character_id=character_id,
                    author_id=author_id,
                    body=op.get("body") or "",
                    fidelity_class=op.get("fidelity_class") or "author_direct",
                    supersedes_id=op.get("material_id"),
                    carriage_disposition=op.get("carriage_disposition") or "carry",
                )
                standing_changes.append(f"replaced:{op.get('material_id')}->{row['id']}")
            elif kind == "retire":
                ok = self.store.retire_perspective_material(
                    op.get("material_id") or "", author_id
                )
                standing_changes.append(
                    f"retired:{op.get('material_id')}" if ok else
                    f"retire_noop:{op.get('material_id')}"
                )
            else:
                standing_changes.append(f"unknown_op:{kind or '(empty)'}")
        after_material = self.store.carried_material(
            character_id, author_id=author_id
        )
        after_state = None
        if after_material:
            after_state = self.store.mint_character_state(
                character_id=character_id,
                author_id=author_id,
                content={
                    "material": [m["body"] for m in after_material],
                    "material_ids": [m["id"] for m in after_material],
                },
                visibility=(before_state or {}).get("visibility", "author"),
                parent_state_id=(before_state or {}).get("id"),
            )
            # The material rows name the state they belong to.
            for m in after_material:
                if m.get("character_state_id") != after_state["id"]:
                    self.store.set_material_state(m["id"], after_state["id"])
        return self.store.record_verdict(
            act_id=act["id"],
            author_id=author_id,
            character_id=character_id,
            before_state_id=(before_state or {}).get("id"),
            after_state_id=(after_state or {}).get("id"),
            before_material=before_material,
            after_material=after_material,
            standing_change="; ".join(standing_changes),
        )

    # -- carriage (family 4) --------------------------------------------------

    def carriage_block(
        self, *, character_id: str, author_id: str
    ) -> tuple[str | None, list[str], str | None]:
        """Render carried perspective material for an author's turn.

        Returns (block, material_ids, character_state_id). The block
        is bounded and framed as revisable standing. Material whose
        recorded carriage disposition is not ``carry`` is excluded —
        carriage was decided at adoption, and adopted-but-uncarried
        material is auditable via :meth:`uncarried_adopted`.
        """
        rows = [
            m
            for m in self.store.carried_material(character_id, author_id=author_id)
            if (m.get("carriage_disposition") or "carry") == "carry"
        ]
        if not rows:
            return None, [], None
        lines = [_CARRIAGE_HEADER]
        used = len(lines[0])
        served: list[dict[str, Any]] = []
        for m in rows:
            line = f"- {m['body']}"
            if used + len(line) + 1 > MAX_CARRIAGE_CHARS:
                break
            lines.append(line)
            used += len(line) + 1
            served.append(m)
        if not served:
            return None, [], None
        state = self.store.current_character_state(
            character_id, viewer_id=author_id
        )
        return (
            "\n".join(lines),
            [m["id"] for m in served],
            (state or {}).get("id"),
        )

    def uncarried_adopted(self, *, character_id: str, author_id: str) -> list[dict[str, Any]]:
        """The loud audit (item 3, minimum form): carried-standing
        material whose recorded carriage disposition is NOT carry —
        visible, never a silent veto."""
        return [
            m
            for m in self.store.carried_material(character_id, author_id=author_id)
            if (m.get("carriage_disposition") or "carry") != "carry"
        ]

    # -- state resolution (C4) ---------------------------------------------

    def resolve_character_state(
        self,
        *,
        character_id: str,
        viewer_id: str | None = None,
        pinned_state_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Resolve the character state a turn or run operates under.

        PINNED resolution (evaluations, frozen experiments): the
        designated state is returned exactly as recorded, entirely
        independent of the author's current developmental state —
        later corrections, replacements, and retirements cannot move
        it. Unpinned resolution returns the current state as visible
        to the viewer (author-scoped states only to their author).
        """
        if pinned_state_id:
            state = self.store.get_character_state(pinned_state_id)
            if state is not None and state["character_id"] != character_id:
                return None
            return state
        return self.store.current_character_state(
            character_id, viewer_id=viewer_id
        )

    # -- designation (family 5) --------------------------------------------

    def designate(
        self,
        *,
        author_id: str,
        character_id: str,
        material_ref: str,
        purpose: str,
        origin_time: str | None = None,
    ) -> dict[str, Any]:
        """Direct designation of the author's own material for one
        ruled purpose. Confers neither eligibility nor training
        authorization (the store writes both flags False)."""
        self._require_author(user_id=author_id, character_id=character_id)
        return self.store.designate(
            author_id=author_id,
            material_ref=material_ref,
            purpose=purpose,
            origin_time=origin_time,
        )

    # -- expression linkage (C3) -------------------------------------------

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
        A relationship record only — no evaluation is performed."""
        self._require_author(user_id=author_id, character_id=character_id)
        return self.store.link_expression(
            author_id=author_id,
            character_id=character_id,
            linked_kind=linked_kind,
            lineage_act_id=lineage_act_id,
            ref=ref,
            note=note,
        )

    # -- preservation gate (Tier 1) -----------------------------------------

    def is_author_interaction(
        self, *, user_id: str, character_id: str
    ) -> bool:
        """Tier-1 preservation scope: an author account interacting
        with that author's OWN characters. Visitor interactions are
        never swept in by this gate."""
        return self.is_author(user_id=user_id, character_id=character_id)
