"""Steward increment D — inspectable read model (pure, no writes).

Mirrors ``local_ai/fellowship/attention.py``'s contract: pure read
over stored rows, never re-scores at serve time, serving never
transitions anything, markers derive from stored status so there
is no second state store to drift. The read model assembles its
response from ONE snapshot (``NarrativeStore.snapshot_for_read``):
all narrative-store reads for a response happen under one lock
acquisition there, so consultation, content, and totals cohere.
This module performs no store calls at all — it is pure Python
over the snapshot — and it never imports the turn path, the
sweep, the friction pass, or any derivation writer.

Honesty rules baked into the shapes (proposal §3, revised):

- No invitation-permission field exists anywhere in the output.
  Decline consultation reports coverage AND result; ``no_match``
  among consulted scopes is never clearance, and invitation scope
  is always ``not_checked`` for stored signals (its keys are
  proposal-time, not stored).
- Origin is not confirmation: ``origin`` is served verbatim,
  ``steward_proposed`` is an initiation fact, and
  ``confirmation_state`` is ``unknown`` (no confirmation field
  exists on threads or readings). No D-computed provisional
  boolean: provisional presentation is E's rendering rule.
- Provenance is kind-specific, never universally nonempty refs,
  with ``ref_state`` never collapsed: complete / not_applicable /
  expected_but_missing / present_but_unresolved.
- Delivery state is separate from verdict state, carried only by
  participating kinds (steward/seat-authored readings +
  observables); everything else is ``not_applicable``, never
  default ``pending``. ``surfaced`` means presented in a
  visitor-facing interface, never proof of seeing, never an API
  fetch. Serving never transitions anything.
- Groups are retrieval units, NOT consent units: nothing here
  implies that reviewing or approving one reading authorizes
  action on any other signal in its thread. Batch-action
  permissions are E's specification, not D's.
- Grouping follows stored identity, never inference: meeting
  groups are O1-only and exact; threads carry no meeting field,
  so no thread->meeting link is ever invented.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import quote, urlencode

from local_ai.council.jurisdictions import SEAT_JURISDICTIONS
from local_ai.narrative.derivation import (
    consult_offer_declines,
    subject_key_for_thread,
)
from local_ai.narrative.refs import tier_of

#: Signal kinds D serves (proposal §3.2). Decline rows ride in the
#: response's ``declines`` section, not in the signal list.
SIGNAL_KINDS: tuple[str, ...] = (
    "thread",
    "reading",
    "observable",
    "suppressed_proposal",
)

#: Delivery filter values (proposal §4.2). ``not_applicable`` is a
#: real filterable state here, unlike the list endpoint's delivery
#: filter where not_applicable signals are omitted by any filter.
DELIVERY_VALUES: tuple[str, ...] = (
    "pending",
    "surfaced",
    "discussed",
    "dismissed",
    "not_applicable",
)

DECLINE_RESULTS: tuple[str, ...] = ("matched", "ambiguous", "no_match_found")
UNCONSULTED_SCOPES: tuple[str, ...] = ("invitation", "subject", "class")

GROUP_LIMIT_DEFAULT = 50
GROUP_LIMIT_MAX = 200
SIGNAL_CAP = 5000
MEMBER_LIMIT_DEFAULT = 100
MEMBER_LIMIT_MAX = 500

_INVITATION_UNCONSULTED = {
    "scope": "invitation",
    "reason": "invitation keys are proposal-time, not stored",
}
_CLASS_UNCONSULTED = {
    "scope": "class",
    "reason": "not derivable without inference",
}


def _b64_encode(payload: dict) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")


def _b64_decode(cursor: str) -> dict:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode())
    except Exception as exc:  # noqa: BLE001 — any malformation is a 400
        raise ValueError(f"malformed cursor: {cursor!r}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"malformed cursor: {cursor!r}")
    return value


def _validate_limit(limit: int | None, default: int, maximum: int) -> int:
    if limit is None:
        return default
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError(f"limit must be an integer: {limit!r}")
    if limit < 1 or limit > maximum:
        raise ValueError(f"limit outside 1..{maximum}: {limit!r}")
    return limit


def _validate_filters(
    *,
    kind: str | None,
    delivery_status: str | None,
    decline_result: str | None,
    unconsulted_scope: str | None,
    seat: str | None,
) -> None:
    if kind is not None and kind not in SIGNAL_KINDS:
        raise ValueError(f"unknown signal kind: {kind!r}")
    if delivery_status is not None and delivery_status not in (
        "pending",
        "surfaced",
        "discussed",
        "dismissed",
    ):
        raise ValueError(f"unknown delivery status: {delivery_status!r}")
    if decline_result is not None and decline_result not in DECLINE_RESULTS:
        raise ValueError(f"unknown decline result: {decline_result!r}")
    if (
        unconsulted_scope is not None
        and unconsulted_scope not in UNCONSULTED_SCOPES
    ):
        raise ValueError(f"unknown unconsulted scope: {unconsulted_scope!r}")
    if seat is not None and seat not in SEAT_JURISDICTIONS:
        raise ValueError(f"unknown seat: {seat!r}")


def _ref_tier(ref_kind: str) -> str | None:
    """A ref's tier, or None for an unknown kind (defensive: an
    unknown kind labels the ref, never drops the signal)."""
    try:
        tier = tier_of(ref_kind)
    except ValueError:
        return None
    return str(tier)


def _resolve_refs(
    ref_ids: list[str], evidence_by_id: dict[str, Any]
) -> tuple[list[dict], list[str]]:
    """Resolve evidence-row ids to rows. Returns (resolved, missing)."""
    resolved: list[dict] = []
    missing: list[str] = []
    for ref_id in ref_ids:
        row = evidence_by_id.get(ref_id)
        if row is None:
            missing.append(ref_id)
            continue
        resolved.append(
            {
                "ref_kind": row.ref_kind,
                "ref_id": row.ref_id,
                "note": row.note,
                "entity_ref": row.entity_ref,
                "created_at": row.created_at,
                "tier": _ref_tier(row.ref_kind),
            }
        )
    return resolved, missing


def _provenance_for_evidence_refs(
    ref_ids: list[str], evidence_by_id: dict[str, Any], *, detail: bool
) -> dict:
    """Kind-agnostic evidence-ref provenance (readings, O2, O4,
    suppressed rows): refs are narrative evidence-row ids."""
    if not ref_ids:
        return {
            "evidence_refs": [],
            "ref_state": "expected_but_missing",
            "provenance_resolved": False,
            "unresolved_ids": [],
            "evidence_rows": [],
        }
    resolved, missing = _resolve_refs(ref_ids, evidence_by_id)
    if missing:
        return {
            "evidence_refs": list(ref_ids),
            "ref_state": "present_but_unresolved",
            "provenance_resolved": False,
            "unresolved_ids": missing,
            "evidence_rows": resolved if detail else [],
        }
    return {
        "evidence_refs": list(ref_ids),
        "ref_state": "complete",
        "provenance_resolved": True,
        "unresolved_ids": [],
        "evidence_rows": resolved if detail else [],
    }


class _Assembler:
    """Builds envelopes from one snapshot. Pure: no store calls."""

    def __init__(self, snapshot: dict) -> None:
        self.threads = {t.id: t for t in snapshot["threads"]}
        self.threads_ordered = list(snapshot["threads"])
        self.evidence_by_thread: dict[str, list] = {}
        self.evidence_ids_by_thread: dict[str, dict[str, Any]] = {}
        for row in snapshot["evidence"]:
            self.evidence_by_thread.setdefault(row.thread_id, []).append(row)
            self.evidence_ids_by_thread.setdefault(row.thread_id, {})[
                row.id
            ] = row
        self.readings_by_thread: dict[str, list] = {}
        for row in snapshot["readings"]:
            self.readings_by_thread.setdefault(row.thread_id, []).append(row)
        self.observables_by_thread: dict[str, list] = {}
        self.meeting_observables: list = []
        for row in snapshot["observables"]:
            if row.thread_id is None:
                self.meeting_observables.append(row)
            else:
                self.observables_by_thread.setdefault(row.thread_id, []).append(
                    row
                )
        self.suppressed_by_thread: dict[str, list] = {}
        for row in snapshot["suppressed"]:
            self.suppressed_by_thread.setdefault(row["thread_id"], []).append(
                row
            )
        self.changes_by_thread: dict[str, list] = {}
        for row in snapshot["changes"]:
            self.changes_by_thread.setdefault(row.thread_id, []).append(row)
        self.delivery: dict = snapshot["delivery"]
        self.dismissals = list(snapshot["dismissals"])
        self.dismissed_pairs = {
            (r.kind, r.signature) for r in self.dismissals
        }
        self.has_subject_dismissal = any(
            r.kind == "offer_subject" for r in self.dismissals
        )
        self._decline_cache: dict[str, dict] = {}

    # -- decline consultation (per thread, computed once) --------------

    def decline_for_thread(self, thread: Any) -> dict:
        if thread.id in self._decline_cache:
            return self._decline_cache[thread.id]
        evidence = self.evidence_by_thread.get(thread.id, [])
        key, precision = subject_key_for_thread(
            None,  # type: ignore[arg-type] — evidence supplied, no store read
            "",
            thread,
            evidence_rows=evidence,
        )
        is_birth = thread.origin == "steward_proposal"
        result = consult_offer_declines(
            dismissed_pairs=self.dismissed_pairs,
            has_subject_dismissal=self.has_subject_dismissal,
            subject_key=key,
            subject_precision=precision,
            class_label="birth" if is_birth else None,
        )
        consulted = ["subject"] + (["class"] if is_birth else [])
        unconsulted = [dict(_INVITATION_UNCONSULTED)]
        if not is_birth:
            unconsulted.append(dict(_CLASS_UNCONSULTED))
        if result in ("subject", "class", "invitation"):
            state = {
                "result": "matched",
                "matched_scope": result,
                "ambiguous_reason": None,
                "consulted_scopes": consulted,
                "unconsulted_scopes": unconsulted,
            }
        elif result == "ambiguous":
            state = {
                "result": "ambiguous",
                "matched_scope": None,
                "ambiguous_reason": (
                    f"{precision} subject key with subject declines "
                    "standing"
                ),
                "consulted_scopes": consulted,
                "unconsulted_scopes": unconsulted,
            }
        else:
            state = {
                "result": "no_match_found",
                "matched_scope": None,
                "ambiguous_reason": None,
                "consulted_scopes": consulted,
                "unconsulted_scopes": unconsulted,
            }
        self._decline_cache[thread.id] = state
        return state

    def decline_for_meeting_group(self) -> dict:
        """O1 rows have no thread, so no subject identity exists to
        consult: nothing consulted, everything unconsulted, and the
        vacuous no_match_found says only that — nothing more."""
        return {
            "result": "no_match_found",
            "matched_scope": None,
            "ambiguous_reason": None,
            "consulted_scopes": [],
            "unconsulted_scopes": [
                {
                    "scope": "subject",
                    "reason": "no thread to derive subject identity",
                },
                dict(_CLASS_UNCONSULTED),
                dict(_INVITATION_UNCONSULTED),
            ],
        }

    # -- delivery --------------------------------------------------------

    def delivery_for(
        self, signal_kind: str, signal_id: str, *, participates: bool
    ) -> str:
        if not participates:
            return "not_applicable"
        return self.delivery.get((signal_kind, signal_id), "pending")

    # -- envelopes ---------------------------------------------------------

    def envelope(
        self,
        *,
        signal_kind: str,
        signal_id: str,
        signal_key: str | None,
        group: str,
        content: dict,
        provenance: dict,
        tier: str | None,
        origin: str | None,
        steward_proposed: bool,
        delivery_status: str,
        decline_state: dict,
    ) -> dict:
        return {
            "signal_kind": signal_kind,
            "id": signal_id,
            "signal_key": signal_key,
            "group": group,
            "content": content,
            "provenance": provenance,
            "tier": tier,
            "origin": origin,
            "steward_proposed": steward_proposed,
            "confirmation_state": "unknown",
            "delivery_status": delivery_status,
            "decline_state": decline_state,
        }

    def thread_envelope(self, thread: Any, decline_state: dict) -> dict:
        provenance = {
            "evidence_refs": [],
            "ref_state": "not_applicable",
            "provenance_resolved": True,
            "unresolved_ids": [],
            "evidence_rows": [],
            "derivation": {
                "origin": thread.origin,
                "created_at": thread.created_at,
            },
        }
        return self.envelope(
            signal_kind="thread",
            signal_id=thread.id,
            signal_key=None,
            group=thread.id,
            content=thread.to_dict(),
            provenance=provenance,
            tier=None,
            origin=thread.origin,
            steward_proposed=thread.origin == "steward_proposal",
            delivery_status="not_applicable",
            decline_state=decline_state,
        )

    def reading_envelope(
        self, reading: Any, thread: Any, decline_state: dict, *, detail: bool
    ) -> dict:
        evidence_by_id = self.evidence_ids_by_thread.get(thread.id, {})
        provenance = _provenance_for_evidence_refs(
            list(reading.evidence_refs or []), evidence_by_id, detail=detail
        )
        provenance["derivation"] = {
            "author": reading.author,
            "scales": list(reading.scales or []),
            "primary_scale": reading.primary_scale,
            "progression": reading.progression.to_dict(),
            "created_at": reading.created_at,
        }
        participates = reading.author != "user"
        return self.envelope(
            signal_kind="reading",
            signal_id=reading.id,
            signal_key=None,
            group=thread.id,
            content=reading.to_dict(),
            provenance=provenance,
            tier="Interpretation",
            origin=thread.origin,
            steward_proposed=thread.origin == "steward_proposal",
            delivery_status=self.delivery_for(
                "reading", reading.id, participates=participates
            ),
            decline_state=decline_state,
        )

    def observable_envelope(
        self,
        observable: Any,
        thread: Any | None,
        decline_state: dict,
        *,
        detail: bool,
    ) -> dict:
        group = thread.id if thread is not None else self._meeting_group_id(
            observable
        )
        if observable.kind == "impression_unanswered":
            # O1: refs are a meeting key (+ intake claim id), NOT
            # narrative evidence rows — never resolve them against
            # thread evidence. The stored basis (detail.meeting_key)
            # is the provenance; a missing key is the gap.
            meeting_key = (observable.detail or {}).get("meeting_key")
            if meeting_key:
                ref_state, resolved = "complete", True
            else:
                ref_state, resolved = "expected_but_missing", False
            provenance = {
                "evidence_refs": list(observable.evidence_refs or []),
                "ref_state": ref_state,
                "provenance_resolved": resolved,
                "unresolved_ids": [],
                "evidence_rows": [],
                "derivation": {
                    "kind": observable.kind,
                    "detail": dict(observable.detail or {}),
                },
            }
        elif observable.kind == "thread_quiet":
            # O3: the thread row's clock IS the fact. Complete when
            # the thread exists (it does, in group context).
            provenance = {
                "evidence_refs": list(observable.evidence_refs or []),
                "ref_state": "complete" if thread is not None else (
                    "present_but_unresolved"
                ),
                "provenance_resolved": thread is not None,
                "unresolved_ids": (
                    [] if thread is not None else list(
                        observable.evidence_refs or []
                    )
                ),
                "evidence_rows": [],
                "derivation": {
                    "kind": observable.kind,
                    "detail": dict(observable.detail or {}),
                },
            }
        else:
            # O2 / O4 / unknown kinds: refs are narrative evidence
            # row ids (O2: the corrected claim's evidence row; O4:
            # the shared evidence rows) — resolve them.
            evidence_by_id = (
                self.evidence_ids_by_thread.get(thread.id, {})
                if thread is not None
                else {}
            )
            provenance = _provenance_for_evidence_refs(
                list(observable.evidence_refs or []),
                evidence_by_id,
                detail=detail,
            )
            provenance["derivation"] = {
                "kind": observable.kind,
                "detail": dict(observable.detail or {}),
            }
        origin = thread.origin if thread is not None else None
        return self.envelope(
            signal_kind="observable",
            signal_id=observable.id,
            signal_key=observable.signal_key,
            group=group,
            content=observable.to_dict(),
            provenance=provenance,
            tier="observable",
            origin=origin,
            # No thread exists to source an origin from; False here
            # follows mechanically from "origin is steward_proposal"
            # being false when origin is absent — it is not a claim
            # about who derived the row (the friction pass did).
            steward_proposed=False if thread is None else (
                thread.origin == "steward_proposal"
            ),
            delivery_status=self.delivery_for(
                "observable", observable.signal_key, participates=True
            ),
            decline_state=decline_state,
        )

    def suppressed_envelope(
        self, row: dict, thread: Any | None, decline_state: dict, *, detail: bool
    ) -> dict:
        import json as _json

        try:
            refs = _json.loads(row.get("evidence_refs_json") or "[]")
        except ValueError:
            refs = []
        if not isinstance(refs, list):
            refs = []
        refs = [str(r) for r in refs]
        # Suppressed refs are provenance KEYS ("kind:ref_id"), not
        # evidence-row ids (proposal §3.8: refs are provenance keys,
        # not verbatim text). Resolve each key against the thread's
        # evidence rows by (ref_kind, ref_id); a key with no colon
        # falls back to a row-id match. Unresolvable keys are
        # present_but_unresolved, never dropped, never fabricated.
        evidence_rows = (
            self.evidence_by_thread.get(thread.id, [])
            if thread is not None
            else []
        )
        by_key = {
            f"{row.ref_kind}:{row.ref_id}": row for row in evidence_rows
        }
        by_id = {row.id: row for row in evidence_rows}
        resolved: list[dict] = []
        missing: list[str] = []
        for ref in refs:
            matched = by_key.get(ref) or by_id.get(ref)
            if matched is None:
                missing.append(ref)
                continue
            resolved.append(
                {
                    "ref_kind": matched.ref_kind,
                    "ref_id": matched.ref_id,
                    "note": matched.note,
                    "entity_ref": matched.entity_ref,
                    "created_at": matched.created_at,
                    "tier": _ref_tier(matched.ref_kind),
                }
            )
        if not refs:
            ref_state, resolved_flag = "expected_but_missing", False
        elif missing:
            ref_state, resolved_flag = "present_but_unresolved", False
        else:
            ref_state, resolved_flag = "complete", True
        provenance = {
            "evidence_refs": refs,
            "ref_state": ref_state,
            "provenance_resolved": resolved_flag,
            "unresolved_ids": missing,
            "evidence_rows": resolved if detail else [],
        }
        provenance["derivation"] = {
            "suppressed_scope": row.get("suppressed_scope"),
            "suppressed_key": row.get("suppressed_key"),
            "created_at": row.get("created_at"),
        }
        group = thread.id if thread is not None else "ungrouped"
        return self.envelope(
            signal_kind="suppressed_proposal",
            signal_id=row["id"],
            signal_key=None,
            group=group,
            content={
                "status": "suppressed_by_decline",
                "kind": row.get("kind"),
                "thread_id": row.get("thread_id"),
                "evidence_refs": [str(r) for r in refs],
                "verbatim_texts": [],
                "texts_cleared": True,
                "suppressed_by": {
                    "scope": row.get("suppressed_scope"),
                    "key": row.get("suppressed_key"),
                },
                "created_at": row.get("created_at"),
            },
            provenance=provenance,
            tier=None,
            origin=thread.origin if thread is not None else None,
            steward_proposed=False if thread is None else (
                thread.origin == "steward_proposal"
            ),
            delivery_status="not_applicable",
            decline_state=decline_state,
        )

    @staticmethod
    def _meeting_group_id(observable: Any) -> str:
        key = (observable.detail or {}).get("meeting_key")
        return f"meeting:{key}" if key else "ungrouped"

    # -- group assembly ----------------------------------------------------

    def thread_group_signals(
        self, thread: Any, *, detail: bool
    ) -> list[dict]:
        decline = self.decline_for_thread(thread)
        signals = [self.thread_envelope(thread, decline)]
        rest: list[tuple[str, str, dict]] = []
        for reading in self.readings_by_thread.get(thread.id, []):
            rest.append(
                (
                    reading.created_at,
                    reading.id,
                    self.reading_envelope(reading, thread, decline,
                                           detail=detail),
                )
            )
        for obs in self.observables_by_thread.get(thread.id, []):
            rest.append(
                (
                    obs.created_at,
                    obs.id,
                    self.observable_envelope(obs, thread, decline,
                                             detail=detail),
                )
            )
        for row in self.suppressed_by_thread.get(thread.id, []):
            rest.append(
                (
                    row.get("created_at") or "",
                    row["id"],
                    self.suppressed_envelope(row, thread, decline,
                                             detail=detail),
                )
            )
        rest.sort(key=lambda item: (item[0], item[1]))
        signals.extend(item[2] for item in rest)
        return signals

    def meeting_groups(self, *, detail: bool) -> list[dict]:
        by_key: dict[str, list] = {}
        ungrouped: list = []
        for obs in self.meeting_observables:
            key = (obs.detail or {}).get("meeting_key")
            if key:
                by_key.setdefault(str(key), []).append(obs)
            else:
                ungrouped.append(obs)
        decline = self.decline_for_meeting_group()
        groups: list[dict] = []
        for key in sorted(by_key):
            rows = sorted(by_key[key], key=lambda o: (o.created_at, o.id))
            signals = [
                self.observable_envelope(o, None, decline, detail=detail)
                for o in rows
            ]
            groups.append(
                {
                    "group_id": f"meeting:{key}",
                    "group_kind": "meeting",
                    "thread": None,
                    "meeting_key": key,
                    "signals": signals,
                    "signal_count": len(signals),
                    "sort_time": rows[0].created_at,
                }
            )
        if ungrouped:
            rows = sorted(ungrouped, key=lambda o: (o.created_at, o.id))
            signals = [
                self.observable_envelope(o, None, decline, detail=detail)
                for o in rows
            ]
            groups.append(
                {
                    "group_id": "ungrouped",
                    "group_kind": "ungrouped",
                    "thread": None,
                    "meeting_key": None,
                    "signals": signals,
                    "signal_count": len(signals),
                    "sort_time": rows[0].created_at,
                }
            )
        return groups

    def thread_groups(self, *, detail: bool) -> list[dict]:
        groups: list[dict] = []
        for thread in self.threads_ordered:
            signals = self.thread_group_signals(thread, detail=detail)
            groups.append(
                {
                    "group_id": thread.id,
                    "group_kind": "thread",
                    "thread": thread.to_dict(),
                    "meeting_key": None,
                    "signals": signals,
                    "signal_count": len(signals),
                    "sort_time": thread.created_at,
                }
            )
        # Defensive-only: suppressed rows whose thread row is absent
        # (impossible through delete_thread's cascade, but specified).
        orphan_rows = [
            row
            for rows in self.suppressed_by_thread.values()
            for row in rows
            if row["thread_id"] not in self.threads
        ]
        if orphan_rows:
            decline = self.decline_for_meeting_group()
            signals = [
                self.suppressed_envelope(row, None, decline, detail=detail)
                for row in sorted(
                    orphan_rows,
                    key=lambda r: (r.get("created_at") or "", r["id"]),
                )
            ]
            groups.append(
                {
                    "group_id": "ungrouped",
                    "group_kind": "ungrouped",
                    "thread": None,
                    "meeting_key": None,
                    "signals": signals,
                    "signal_count": len(signals),
                    "sort_time": signals[0]["content"]["created_at"],
                }
            )
        return groups

    def declines_section(self) -> list[dict]:
        return [
            {
                "id": r.id,
                "kind": r.kind,
                "signature": r.signature,
                "created_at": r.created_at,
            }
            for r in self.dismissals
        ]


# ---------------------------------------------------------------------------
# Filtering, pagination, response assembly
# ---------------------------------------------------------------------------


def _signal_matches(signal: dict, *, kind, delivery_status, decline_result,
                    unconsulted_scope) -> bool:
    if kind is not None and signal["signal_kind"] != kind:
        return False
    if delivery_status is not None:
        # not_applicable signals are omitted by ANY delivery filter
        # (proposal §4.2): they are not pending, surfaced, discussed,
        # or dismissed, and must never match one of those by accident.
        if signal["delivery_status"] != delivery_status:
            return False
    if decline_result is not None:
        if signal["decline_state"]["result"] != decline_result:
            return False
    if unconsulted_scope is not None:
        scopes = [
            entry["scope"]
            for entry in signal["decline_state"]["unconsulted_scopes"]
        ]
        if unconsulted_scope not in scopes:
            return False
    return True


def _apply_signal_filters(
    signals: list[dict], *, kind, delivery_status, decline_result,
    unconsulted_scope,
) -> list[dict]:
    if (
        kind is None
        and delivery_status is None
        and decline_result is None
        and unconsulted_scope is None
    ):
        return signals
    return [
        s
        for s in signals
        if _signal_matches(
            s,
            kind=kind,
            delivery_status=delivery_status,
            decline_result=decline_result,
            unconsulted_scope=unconsulted_scope,
        )
    ]


def _merge_ungrouped(groups: list[dict]) -> list[dict]:
    """Merge every ``ungrouped`` group into one (defensive-only paths
    from thread groups and meeting groups can each produce one)."""
    merged: dict | None = None
    out: list[dict] = []
    for group in groups:
        if group["group_id"] != "ungrouped":
            out.append(group)
            continue
        if merged is None:
            merged = dict(group)
            merged["signals"] = list(group["signals"])
        else:
            merged["signals"].extend(group["signals"])
            merged["signal_count"] += group["signal_count"]
            merged["sort_time"] = min(
                merged["sort_time"], group["sort_time"]
            )
    if merged is not None:
        merged["signals"].sort(
            key=lambda s: (
                s["content"].get("created_at") or "",
                s["id"],
            )
        )
        out.append(merged)
    return out


def _group_sort_key(group: dict) -> tuple[str, str]:
    return (group["sort_time"], group["group_id"])


def _members_url(group_id: str, *, kind, delivery_status, decline_result,
                 unconsulted_scope) -> str:
    params: dict[str, Any] = {}
    if kind is not None:
        params["kind"] = kind
    if delivery_status is not None:
        params["delivery_status"] = delivery_status
    if decline_result is not None:
        params["decline_result"] = decline_result
    if unconsulted_scope is not None:
        params["unconsulted_scope"] = unconsulted_scope
    query = urlencode(params)
    base = f"/steward/groups/{quote(group_id, safe='')}/members"
    return base + (f"?{query}" if query else "")


def build_signals_response(
    snapshot: dict,
    *,
    user_id: str,
    derivation_active: bool,
    thread_id: str | None = None,
    meeting_key: str | None = None,
    seat: str | None = None,
    scope: str | None = None,
    kind: str | None = None,
    delivery_status: str | None = None,
    decline_result: str | None = None,
    unconsulted_scope: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict:
    """Assemble the grouped list response from one snapshot.

    Pure: no store calls, no writes, no transitions. Raises
    ValueError for unknown filter values / limits / cursors (the
    route maps these to 400). Cross-user ids in filters yield empty
    groups, never partial data (the snapshot holds only this user's
    rows, so a foreign id simply matches nothing).
    """
    _validate_filters(
        kind=kind,
        delivery_status=delivery_status,
        decline_result=decline_result,
        unconsulted_scope=unconsulted_scope,
        seat=seat,
    )
    limit = _validate_limit(limit, GROUP_LIMIT_DEFAULT, GROUP_LIMIT_MAX)
    assembler = _Assembler(snapshot)

    # -- group selection (thread_id / meeting_key / seat / scope) -----
    all_groups: list[dict] = []
    if meeting_key is not None:
        all_groups = [
            g
            for g in assembler.meeting_groups(detail=False)
            if g["group_id"] == f"meeting:{meeting_key}"
        ]
    elif thread_id is not None:
        all_groups = [
            g
            for g in assembler.thread_groups(detail=False)
            if g["group_id"] == thread_id
        ]
    else:
        thread_groups = assembler.thread_groups(detail=False)
        if seat is not None or scope is not None:
            # Seat/scope select thread groups only: meeting groups
            # carry no seat or scope, so they cannot match.
            selected: list[dict] = []
            for group in thread_groups:
                if group["group_kind"] != "thread":
                    continue
                thread = assembler.threads[group["group_id"]]
                if scope is not None and thread.scope != scope:
                    continue
                if seat is not None:
                    in_cast = any(
                        c.get("seat") == seat for c in (thread.cast or [])
                    )
                    authored = any(
                        r.author == seat
                        for r in assembler.readings_by_thread.get(
                            thread.id, []
                        )
                    )
                    if not in_cast and not authored:
                        continue
                selected.append(group)
            all_groups = selected
        else:
            all_groups = thread_groups + assembler.meeting_groups(
                detail=False
            )
    all_groups = _merge_ungrouped(all_groups)

    # -- signal filtering within groups --------------------------------
    # Seat narrows readings to the seat's authorship; observables
    # and suppressed rows are facts about the thread, not
    # seat-authored content, so they stay. The thread header signal
    # participates in kind/delivery/decline filtering like any
    # signal, but the group header (group["thread"]) remains as
    # context even when the header signal itself is filtered out
    # (clarification: headers stay available as group context).
    filtered: list[dict] = []
    for group in all_groups:
        signals = group["signals"]
        if seat is not None and group["group_kind"] == "thread":
            signals = [
                s
                for s in signals
                if s["signal_kind"] != "reading"
                or s["content"].get("author") == seat
            ]
        signals = _apply_signal_filters(
            signals,
            kind=kind,
            delivery_status=delivery_status,
            decline_result=decline_result,
            unconsulted_scope=unconsulted_scope,
        )
        if not signals:
            continue
        filtered.append({**group, "signals": signals,
                         "signal_count": len(signals)})
    filtered.sort(key=_group_sort_key)

    totals = {
        "group_count": len(filtered),
        "signal_count": sum(g["signal_count"] for g in filtered),
        "decline_count": len(assembler.dismissals),
    }

    # -- pagination over groups + the signal cap -----------------------
    if cursor is not None:
        decoded = _b64_decode(cursor)
        if "c" not in decoded or "g" not in decoded:
            raise ValueError(f"malformed cursor: {cursor!r}")
        cursor_key = (decoded["c"], decoded["g"])
        filtered = [g for g in filtered if _group_sort_key(g) > cursor_key]
    page = filtered[:limit]
    returned: list[dict] = []
    running = 0
    truncated = False
    last_key: tuple[str, str] | None = None
    for group in page:
        count = group["signal_count"]
        if count > SIGNAL_CAP:
            # Oversized-group escape hatch (proposal §4.4): the
            # descriptor occupies exactly one position; the list
            # cursor advances past the group; members come only
            # from the bounded members endpoint. Never a silent
            # skip, never a repeated descriptor, never a false
            # completeness claim (truncated is true).
            returned.append(
                {
                    "group_id": group["group_id"],
                    "group_kind": group["group_kind"],
                    "thread": group["thread"],
                    "meeting_key": group["meeting_key"],
                    "signals": [],
                    "signal_count": count,
                    "oversized": True,
                    "members_url": _members_url(
                        group["group_id"],
                        kind=kind,
                        delivery_status=delivery_status,
                        decline_result=decline_result,
                        unconsulted_scope=unconsulted_scope,
                    ),
                }
            )
            truncated = True
            last_key = _group_sort_key(group)
            continue
        if running + count > SIGNAL_CAP:
            # Truncate at the group boundary below the cap; the
            # next page resumes after the last returned group, so
            # nothing is skipped.
            truncated = True
            break
        running += count
        out = {k: v for k, v in group.items() if k != "sort_time"}
        out["oversized"] = False
        out["members_url"] = None
        returned.append(out)
        last_key = _group_sort_key(group)
    # Cursor: the last returned group, or None when nothing remains
    # past this page (page shorter than limit AND no cap truncation).
    remaining_after_page = filtered[len(page):]
    if truncated or remaining_after_page:
        next_cursor = (
            _b64_encode({"c": last_key[0], "g": last_key[1]})
            if last_key is not None
            else None
        )
    else:
        next_cursor = None
    # A page carrying a descriptor is truncated by definition, even
    # when it is also the last page.
    return {
        "user_id": user_id,
        "derivation_active": derivation_active,
        "groups": returned,
        "declines": assembler.declines_section(),
        "totals": totals,
        "pagination": {
            "cursor": next_cursor,
            "limit": limit,
            "truncated": truncated,
        },
    }


def get_signal_detail(
    snapshot: dict, *, kind: str, signal_id: str
) -> dict:
    """One signal with FULL provenance (resolved evidence rows).

    Raises ValueError for an unknown kind (route maps to 400) and
    LookupError for an unknown id — including an id belonging to
    another user, which is indistinguishable by construction (the
    snapshot holds only this user's rows; route maps both to 404).
    Detail never transitions delivery state and never touches a
    clock: it only reads the snapshot.
    """
    if kind not in SIGNAL_KINDS:
        raise ValueError(f"unknown signal kind: {kind!r}")
    assembler = _Assembler(snapshot)
    if kind == "thread":
        thread = assembler.threads.get(signal_id)
        if thread is None:
            raise LookupError(f"unknown thread: {signal_id!r}")
        envelope = assembler.thread_envelope(
            thread, assembler.decline_for_thread(thread)
        )
        envelope["changes"] = [
            c.to_dict()
            for c in assembler.changes_by_thread.get(thread.id, [])
        ]
        return envelope
    if kind == "reading":
        for thread in assembler.threads_ordered:
            for reading in assembler.readings_by_thread.get(thread.id, []):
                if reading.id == signal_id:
                    return assembler.reading_envelope(
                        reading, thread,
                        assembler.decline_for_thread(thread), detail=True
                    )
        raise LookupError(f"unknown reading: {signal_id!r}")
    if kind == "observable":
        for thread in assembler.threads_ordered:
            for obs in assembler.observables_by_thread.get(thread.id, []):
                if obs.id == signal_id or obs.signal_key == signal_id:
                    return assembler.observable_envelope(
                        obs, thread,
                        assembler.decline_for_thread(thread), detail=True
                    )
        for obs in assembler.meeting_observables:
            if obs.id == signal_id or obs.signal_key == signal_id:
                return assembler.observable_envelope(
                    obs, None, assembler.decline_for_meeting_group(),
                    detail=True
                )
        raise LookupError(f"unknown observable: {signal_id!r}")
    # kind == "suppressed_proposal"
    for rows in assembler.suppressed_by_thread.values():
        for row in rows:
            if row["id"] == signal_id:
                thread = assembler.threads.get(row["thread_id"])
                decline = (
                    assembler.decline_for_thread(thread)
                    if thread is not None
                    else assembler.decline_for_meeting_group()
                )
                return assembler.suppressed_envelope(
                    row, thread, decline, detail=True
                )
    raise LookupError(f"unknown suppressed proposal: {signal_id!r}")


def get_group_members(
    snapshot: dict,
    *,
    group_id: str,
    kind: str | None = None,
    delivery_status: str | None = None,
    decline_result: str | None = None,
    unconsulted_scope: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict:
    """Bounded member pages for one group (oversized-group path).

    The members endpoint exists for oversized groups, but serving
    bounded pages for an ordinary group is harmless and keeps the
    endpoint total (no separate code path to drift): the list
    endpoint remains the canonical path for ordinary groups.
    Parent-request signal filters are preserved, so member pages
    describe the same set as the descriptor's totals. Raises
    LookupError for an unknown group (route maps to 404) and
    ValueError for bad filters/limits/cursors (route maps to 400).
    """
    _validate_filters(
        kind=kind,
        delivery_status=delivery_status,
        decline_result=decline_result,
        unconsulted_scope=unconsulted_scope,
        seat=None,
    )
    limit = _validate_limit(limit, MEMBER_LIMIT_DEFAULT, MEMBER_LIMIT_MAX)
    assembler = _Assembler(snapshot)
    signals: list[dict] = []
    group_kind = "thread"
    if group_id == "ungrouped":
        groups = assembler.thread_groups(detail=False) + \
            assembler.meeting_groups(detail=False)
        merged = _merge_ungrouped(groups)
        target = next(
            (g for g in merged if g["group_id"] == "ungrouped"), None
        )
        if target is None:
            raise LookupError(f"unknown group: {group_id!r}")
        signals = target["signals"]
        group_kind = "ungrouped"
    elif group_id.startswith("meeting:"):
        target = next(
            (
                g
                for g in assembler.meeting_groups(detail=False)
                if g["group_id"] == group_id
            ),
            None,
        )
        if target is None:
            raise LookupError(f"unknown group: {group_id!r}")
        signals = target["signals"]
        group_kind = "meeting"
    else:
        thread = assembler.threads.get(group_id)
        if thread is None:
            raise LookupError(f"unknown group: {group_id!r}")
        signals = assembler.thread_group_signals(thread, detail=False)
    signals = _apply_signal_filters(
        signals,
        kind=kind,
        delivery_status=delivery_status,
        decline_result=decline_result,
        unconsulted_scope=unconsulted_scope,
    )
    signals.sort(
        key=lambda s: (s["content"].get("created_at") or "", s["id"])
    )
    total = len(signals)
    if cursor is not None:
        decoded = _b64_decode(cursor)
        if "c" not in decoded or "g" not in decoded:
            raise ValueError(f"malformed cursor: {cursor!r}")
        cursor_key = (decoded["c"], decoded["g"])
        signals = [
            s
            for s in signals
            if (s["content"].get("created_at") or "", s["id"]) > cursor_key
        ]
    page = signals[:limit]
    if len(signals) > limit and page:
        last = page[-1]
        next_cursor = _b64_encode(
            {"c": last["content"].get("created_at") or "",
             "g": last["id"]}
        )
    else:
        next_cursor = None
    return {
        "group_id": group_id,
        "group_kind": group_kind,
        "signals": page,
        "signal_count": total,
        "pagination": {
            "cursor": next_cursor,
            "limit": limit,
            "truncated": next_cursor is not None,
        },
    }
