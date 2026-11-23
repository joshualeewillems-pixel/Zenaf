"""The permission home — aggregation + write-through (P-2).

One surface over the existing engines, per the accepted Permission
Simplification design (§2–§3) and implementation plan (Phase P-2),
including the founder's contract corrections:

- **No engine merge.** Framework stances still live in the stance
  store (``local_ai.permissions.store``); account flags still live
  in ``permissions_json`` (vision-execution storage). This module
  reads both through their own paths and writes through them. The
  intent layer is a view and a writer, never a third store, and
  enforcement never consults it (consistency contract §5).
- **Absolute sets, never toggles.** An intent/layer write names the
  target state of every mapped control; retrying is idempotent.
- **Write, then read back.** Every write response is computed from
  a fresh read of the stores, never from the requested values.
- **Critical-subset ordering (Correction 1).** Each group's mapped
  controls divide into an enforcement-critical subset — the account
  flags enforcement reads today (via ``user_permission_enabled``
  and the steward/fellowship leaf readers) — and presentational
  partners (the paired stances: recorded choices the framework
  check will consume when wired, per the Slice 2 surface's own
  honesty line). On opt-out the critical controls are written
  FIRST; on opt-in LAST. Safety claims come from the critical
  subset's read-back only: a partial opt-out is reported as an
  **incomplete revocation** naming the capabilities still on,
  never as withdrawn.
- **Acknowledgment ≠ authorization (Correction 2).** Flag writes
  go through ``update_user_permission_flags`` (permissions_json
  only); stance writes through ``set_stance`` (stances only).
  Neither path touches the consent fields, and no consent write
  exists in this module at all — the consent record is exposed
  read-only so the surface can label it as what it is.
- **The sync label is presentation, never safety** (Correction 1):
  a mixed read-back on a plain read is labeled
  ``Custom — your granularity`` (best-effort); a mixed read-back
  after a write in the same call is ``Custom — out of sync``,
  naming the controls that did not take and the repair (re-apply
  the declared target — safe because writes are absolute sets).

Intent mapping (design §2–§3, refinement 2):

- **Remember** presents two layers in the intent itself:
  *retention* (R1 rows + personalization / profile_learning /
  interaction_pattern_storage) and *ongoing story* (R2 +
  steward_derivation + fellowship_derivation). Granular-only rows
  under Remember: behavioral_tracking,
  analytics_product_improvement, aspiration_store_explicit,
  aspiration_infer_suggestions (the aspiration trio's store/infer
  facets; the design does not assign behavioral_tracking or
  analytics to a layer, and parity requires them reachable, so
  they live in Remember's expansion).
- **Connect**: R3 + steward_coordination (one choice writing both,
  design §3).
- **Suggest**: R4 per-seat rows + R5; aspiration_use_in_guidance
  is a granular row under Suggest (design §3).
- **Follow Through**: R6 per-commitment rows (dynamic; the bounded
  task-creation control is P-4 and is not built here).
- **Learn**: a distinction, not a toggle — no controls; the
  review surface is its control (design §2). Returned as a marker
  the surface renders with its explanation.
- **Outside Zenaf**: the disclosure grouping (refinement 4) —
  the consent record (read-only), the standing disclosure
  consents (none exist yet; the story-first search consent lands
  here when Story-First Phase 3 builds it), and the always-asks
  classes (the framework's never-coverable vocabulary).

The ``fellowship_derivation`` flag is a full mapped control of the
story layer: it aggregates and writes like every other flag. Its
Settings-row wording was ruled by the founder 2026-11-22 ("Cross-
conversation noticing") and lives with the surface copy, as every
flag's wording does; the ``wording_pending`` marker remains in the
payload shape for any future flag whose wording is outstanding,
and is currently set for none.

Rollout: ``ZENAF_PERMISSION_HOME`` is the rollout control. The
home is enabled unless the variable is set to a false value
(``0`` / ``false`` / ``no`` / ``off``); when disabled, the state
read reports ``enabled: false`` and writes refuse — an operational
off, reported as operational, never as a permission denial
(design §6, surface state 3).

Read discipline matches P-1: direct read-only SELECTs for the
account row (the settings helper INSERTs rows and rewrites the
blob on read — neither belongs in an aggregation read), stance
reads through the stance store's read paths. A no-op visit writes
nothing.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from . import registry as _registry
from . import store as _store

logger = logging.getLogger("zenaf.permissions.home")

# --- Display states --------------------------------------------------------

ON = "on"
OFF = "off"
ASK_ME_STATE = "ask_me"
CUSTOM = "custom"

SYNC_IN_SYNC = "in_sync"
SYNC_GRANULARITY = "granularity"
SYNC_OUT_OF_SYNC = "out_of_sync"

_STANCE_TO_DISPLAY = {
    _registry.JUST_DO_IT: ON,
    _registry.ASK_ME: ASK_ME_STATE,
    _registry.DONT_DO_IT: OFF,
}
_DISPLAY_TO_STANCE = {v: k for k, v in _STANCE_TO_DISPLAY.items()}

# --- The intent map ----------------------------------------------------------
#
# Control spec: ("flag", key) or ("stance", capability). A group's
# member list is (spec, critical) in definition order; write order
# is derived from it by the Correction 1 ordering rule.

def _flag(key: str) -> tuple[str, str]:
    return ("flag", key)


def _stance(capability: str) -> tuple[str, str]:
    return ("stance", capability)


#: Group id -> ordered [(control spec, is_critical), ...]. A stance
#: spec names a capability ONCE; _group_controls expands it to the
#: capability's rows (every enumerated row, or the single "all" row).
#: R6 is dynamic (per-commitment rows discovered at read time) and
#: is assembled in _group_controls instead.
GROUP_CONTROLS: dict[str, list[tuple[tuple[str, str], bool]]] = {
    "retention": [
        (_stance("R1"), False),
        (_flag("personalization"), True),
        (_flag("interaction_pattern_storage"), True),
        (_flag("profile_learning"), True),
    ],
    "story": [
        (_stance("R2"), False),
        (_flag("steward_derivation"), True),
        (_flag("fellowship_derivation"), True),
    ],
    "connect": [
        (_stance("R3"), False),
        (_flag("steward_coordination"), True),
    ],
    "suggest": [
        (_stance("R4"), True),
        (_stance("R5"), True),
    ],
    "follow_through": [],  # dynamic: R6 rows from the stance store
}

#: Intent id -> its layer/group ids, in presentation order.
INTENT_GROUPS: dict[str, tuple[str, ...]] = {
    "remember": ("retention", "story"),
    "connect": ("connect",),
    "suggest": ("suggest",),
    "follow_through": ("follow_through",),
}

#: Granular-only flag rows per intent (design §3): editable in the
#: expansion, members of no layer aggregate.
INTENT_GRANULAR_FLAGS: dict[str, tuple[str, ...]] = {
    "remember": (
        "behavioral_tracking",
        "analytics_product_improvement",
        "aspiration_store_explicit",
        "aspiration_infer_suggestions",
    ),
    "connect": (),
    "suggest": ("aspiration_use_in_guidance",),
    "follow_through": (),
}

#: Flags whose Settings-row wording is a pending founder content
#: decision. Such a flag aggregates and writes normally; only its
#: copy is outstanding, and the surface renders a pending state
#: rather than substitute wording. Currently empty:
#: fellowship_derivation's wording was ruled 2026-11-22.
WORDING_PENDING_FLAGS = frozenset()

#: Stance surface label recorded on writes issued from the home —
#: the same Settings surface label the framework routes use.
_HOME_SURFACE = _store.SURFACE_SETTINGS

#: The always-asks classes for the Outside Zenaf grouping: the
#: framework's per-transaction vocabulary (the capabilities'
#: never_authorizes union, in design §1's order).
ALWAYS_ASKS_CLASSES = ("train", "publish", "share", "spend", "execute")


def home_enabled() -> bool:
    """The rollout control: enabled unless explicitly switched off."""
    raw = os.environ.get("ZENAF_PERMISSION_HOME")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


# --- Store reads (read-only) -------------------------------------------------


def _default_connection():
    from local_ai.vision_execution.storage import get_connection

    return get_connection()


def _read_account(conn, user_id: str) -> dict[str, Any]:
    """Consent + flags from one direct SELECT, normalized in memory.

    Tolerates a minimal permissions table (permissions_json only),
    mirroring the P-1 diagnostics fallback: unreadable consent
    fields resolve as absent, exactly as enforcement resolves them.
    """
    from local_ai.vision_execution.storage import normalize_user_permission_prefs

    try:
        row = conn.execute(
            "SELECT consent_given, consent_version, consent_at, permissions_json "
            "FROM user_permissions_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            consent_given, consent_version, consent_at, blob = None, None, None, None
        else:
            consent_given, consent_version, consent_at, blob = (
                row[0],
                row[1],
                row[2],
                row[3],
            )
    except Exception:
        row = conn.execute(
            "SELECT permissions_json FROM user_permissions_settings "
            "WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        consent_given, consent_version, consent_at = None, None, None
        blob = None if row is None else row[0]
    try:
        parsed = json.loads(blob or "{}")
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return {
        "consent": {
            "given": bool(consent_given),
            "version": str(consent_version or ""),
            "at": consent_at,
        },
        "flags": normalize_user_permission_prefs(parsed),
    }


# --- Control assembly --------------------------------------------------------


def _flag_control(key: str, flags: dict[str, bool], *, critical: bool) -> dict[str, Any]:
    on = bool(flags.get(key, False))
    return {
        "id": f"flag:{key}",
        "kind": "flag",
        "key": key,
        "state": ON if on else OFF,
        "display_state": ON if on else OFF,
        "value": on,
        "stance": None,
        "stance_source": None,
        "supported_stances": [],
        "critical": critical,
        "wording_pending": key in WORDING_PENDING_FLAGS,
    }


def _stance_control(
    capability: str,
    row_key: str,
    stances: dict[str, dict[str, dict[str, Any]]],
    *,
    critical: bool,
) -> dict[str, Any]:
    entry = _registry.CAPABILITIES[capability]
    record = (stances.get(capability) or {}).get(row_key)
    if isinstance(record, dict) and record.get("stance") in _STANCE_TO_DISPLAY:
        stance = record["stance"]
        source = "user"
    else:
        stance = entry.default_stance
        source = "default"
    row_label = row_key
    for row in entry.rows:
        if row.key == row_key:
            row_label = row.label
            break
    return {
        "id": f"stance:{capability}:{row_key}",
        "kind": "stance",
        "capability": capability,
        "row_key": row_key,
        "label": row_label,
        "covers": entry.covers,
        "does_not_allow": entry.does_not_allow,
        "state": stance,
        "display_state": _STANCE_TO_DISPLAY[stance],
        "value": None,
        "stance": stance,
        "stance_source": source,
        "supported_stances": list(entry.supported_stances),
        "critical": critical,
        "wording_pending": False,
    }


def _group_controls(
    group_id: str,
    account: dict[str, Any],
    stances: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """The group's member controls with read-back state, in
    definition order (R6 rows in stored order)."""
    flags = account["flags"]
    controls: list[dict[str, Any]] = []
    if group_id == "follow_through":
        for row_key in (stances.get("R6") or {}).keys():
            controls.append(_stance_control("R6", row_key, stances, critical=True))
        return controls
    for (kind, key), critical in GROUP_CONTROLS[group_id]:
        if kind == "flag":
            controls.append(_flag_control(key, flags, critical=critical))
        else:
            entry = _registry.CAPABILITIES[key]
            if entry.row_scheme == "enumerated":
                row_keys = [row.key for row in entry.rows]
            else:
                row_keys = ["all"]
            for row_key in row_keys:
                controls.append(
                    _stance_control(key, row_key, stances, critical=critical)
                )
    return controls


def _aggregate_state(controls: list[dict[str, Any]], group_id: str) -> str:
    if not controls:
        # No member rows exist (Follow Through before any commitment
        # is authorized): the registry default is the truthful state.
        if group_id == "follow_through":
            return _STANCE_TO_DISPLAY[_registry.CAPABILITIES["R6"].default_stance]
        return OFF
    states = {c["display_state"] for c in controls}
    if len(states) == 1:
        return next(iter(states))
    return CUSTOM


def _writable_states(group_id: str, controls: list[dict[str, Any]]) -> list[str]:
    """States every mapped control can represent (the absolute-set
    targets a group write accepts). Flags are binary, so any group
    whose map contains a flag accepts on/off only; a stance-only
    group accepts the intersection of its capabilities' supported
    stances, in display terms."""
    if group_id == "follow_through":
        capabilities = ["R6"]
    else:
        specs = GROUP_CONTROLS[group_id]
        if any(spec[0] == "flag" for spec, _critical in specs):
            return [ON, OFF]
        capabilities = [
            spec[1] for spec, _critical in specs if spec[0] == "stance"
        ]
    supported: set[str] | None = None
    for capability in capabilities:
        displays = {
            _STANCE_TO_DISPLAY[s]
            for s in _registry.CAPABILITIES[capability].supported_stances
        }
        supported = displays if supported is None else supported & displays
    return [
        s for s in (ON, OFF, ASK_ME_STATE) if supported and s in supported
    ]


def _group_payload(
    group_id: str,
    account: dict[str, Any],
    stances: dict[str, dict[str, dict[str, Any]]],
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    controls = _group_controls(group_id, account, stances)
    state = _aggregate_state(controls, group_id)
    payload: dict[str, Any] = {
        "id": group_id,
        "state": state,
        "sync": SYNC_GRANULARITY if state == CUSTOM else SYNC_IN_SYNC,
        "writable_states": _writable_states(group_id, controls),
        "has_rows": bool(controls) if group_id == "follow_through" else True,
        "controls": controls,
    }
    if diagnostics:
        payload["diagnostics"] = diagnostics
    return payload


# --- The aggregation read ----------------------------------------------------


def permission_home_state(
    user_id: str | None,
    *,
    connection=None,
) -> dict[str, Any]:
    """The full home payload for ``user_id``. Read-only.

    Unknown/absent users read as all-defaults (consent absent, flags
    off, registry default stances) without creating any row.
    """
    if not home_enabled():
        return {"enabled": False}
    conn = connection if connection is not None else _default_connection()
    if user_id:
        account = _read_account(conn, user_id)
        stances = _store.get_stances(user_id, connection=conn)
    else:
        from local_ai.vision_execution.storage import normalize_user_permission_prefs

        account = {
            "consent": {"given": False, "version": "", "at": None},
            "flags": normalize_user_permission_prefs({}),
        }
        stances = {}

    from .diagnostics import permission_diagnostics

    diag = permission_diagnostics(user_id, connection=conn) if user_id else {}

    intents: list[dict[str, Any]] = []
    for intent_id, group_ids in INTENT_GROUPS.items():
        groups = []
        for group_id in group_ids:
            group_diag = None
            if group_id == "story":
                group_diag = {"derivation": diag.get("derivation"),
                              "candidate_capture": diag.get("candidate_capture")}
            elif group_id == "connect":
                group_diag = {"coordination": diag.get("coordination")}
            groups.append(
                _group_payload(group_id, account, stances, diagnostics=group_diag)
            )
        granular = [
            _flag_control(key, account["flags"], critical=False)
            for key in INTENT_GRANULAR_FLAGS[intent_id]
        ]
        intents.append(
            {"id": intent_id, "groups": groups, "granular": granular}
        )

    return {
        "enabled": True,
        "consent": account["consent"],
        "intents": intents,
        "learn": {"kind": "distinction"},
        "outside_zenaf": {
            "always_asks": list(ALWAYS_ASKS_CLASSES),
            "never_coverable_classes": list(_registry.NEVER_COVERABLE_CLASSES),
            "standing_consents": [],
        },
    }


# --- Writes ------------------------------------------------------------------
#
# The two apply seams. Tests monkeypatch these to force a partial
# failure; production code must not call them outside this module's
# write path.


def _apply_flag(user_id: str, key: str, on: bool, *, connection=None) -> None:
    from local_ai.vision_execution.storage import update_user_permission_flags

    update_user_permission_flags(user_id, {key: on}, connection=connection)


def _apply_stance(
    user_id: str, capability: str, row_key: str, stance: str, *, connection=None
) -> None:
    _store.set_stance(
        user_id,
        capability,
        row_key,
        stance,
        surface=_HOME_SURFACE,
        connection=connection,
    )


def _ordered_controls(
    controls: list[dict[str, Any]], target: str
) -> list[dict[str, Any]]:
    """Correction 1 ordering: opt-out writes critical controls
    first; opt-in writes them last. Definition order is preserved
    within each class."""
    critical = [c for c in controls if c["critical"]]
    presentational = [c for c in controls if not c["critical"]]
    if target == OFF:
        return critical + presentational
    return presentational + critical


def _write_one(
    user_id: str, control: dict[str, Any], target: str, *, connection=None
) -> None:
    if control["kind"] == "flag":
        _apply_flag(user_id, control["key"], target == ON, connection=connection)
    else:
        _apply_stance(
            user_id,
            control["capability"],
            control["row_key"],
            _DISPLAY_TO_STANCE[target],
            connection=connection,
        )


def apply_group_write(
    user_id: str,
    group_id: str,
    target: str,
    *,
    connection=None,
) -> dict[str, Any]:
    """Apply an absolute-set write of ``target`` to a whole group,
    then read back and report the truth (consistency contract).

    Returns the write report; the caller pairs it with a fresh
    :func:`permission_home_state`. Raises ValueError for an unknown
    group or a target the group cannot represent.
    """
    if group_id not in GROUP_CONTROLS:
        raise ValueError(f"unknown permission group: {group_id!r}")
    if target not in (ON, OFF, ASK_ME_STATE):
        raise ValueError(f"unknown target state: {target!r}")
    conn = connection if connection is not None else _default_connection()
    account = _read_account(conn, user_id)
    stances = _store.get_stances(user_id, connection=conn)
    controls = _group_controls(group_id, account, stances)
    if not controls:
        # Follow Through before any commitment exists: there is
        # nothing to write, and claiming a state change would be
        # false. The surface disables the control in this state.
        raise ValueError(
            f"group {group_id} has no controls to write yet"
        )
    if target not in _writable_states(group_id, controls):
        raise ValueError(
            f"group {group_id} cannot be set to {target!r}: "
            "not every mapped control can represent that state"
        )

    write_errors: dict[str, str] = {}
    for control in _ordered_controls(controls, target):
        try:
            _write_one(user_id, control, target, connection=conn)
        except Exception as exc:  # a failed write leaves the prior value
            write_errors[control["id"]] = type(exc).__name__
            logger.warning(
                "permission home: write of %s for user %r failed (%s)",
                control["id"],
                user_id,
                type(exc).__name__,
            )

    # Read back from the stores; the report is the read-back truth.
    account = _read_account(conn, user_id)
    stances = _store.get_stances(user_id, connection=conn)
    read_back = _group_controls(group_id, account, stances)
    read_back_state = _aggregate_state(read_back, group_id)
    failed = [
        c["id"] for c in read_back if c["display_state"] != target
    ]
    critical = [c for c in read_back if c["critical"]]
    if target == OFF:
        still_on = [c["id"] for c in critical if c["display_state"] != OFF]
        complete = not still_on
        revocation = "complete" if complete else "incomplete"
    elif target == ON:
        still_on = []
        complete = all(c["display_state"] == ON for c in critical)
        revocation = None
    else:  # ask_me (stance-only groups)
        still_on = []
        complete = all(c["display_state"] == ASK_ME_STATE for c in critical)
        revocation = None
    out_of_sync = bool(failed)
    return {
        "group": group_id,
        "declared_target": target,
        "read_back_state": read_back_state,
        "sync": SYNC_OUT_OF_SYNC if out_of_sync else SYNC_IN_SYNC,
        "complete": complete,
        "revocation": revocation,
        "still_on": still_on,
        "failed_controls": failed,
        "write_errors": write_errors,
        "repair": (
            {"group": group_id, "state": target} if out_of_sync else None
        ),
        "controls": read_back,
    }


def apply_control_write(
    user_id: str,
    control_id: str,
    value: Any,
    *,
    connection=None,
) -> dict[str, Any]:
    """Write ONE granular control through the separated primitives
    (Correction 2): a flag goes to the flags-only write, a stance to
    the stance store. ``value`` is a bool for flags, a stance string
    for stances. Returns the read-back control. Raises ValueError
    for an unknown control id or an unrepresentable value.
    """
    conn = connection if connection is not None else _default_connection()
    kind, _, rest = control_id.partition(":")
    if kind == "flag":
        key = rest
        from local_ai.vision_execution.storage import _USER_PERMISSION_KEYS

        if key not in _USER_PERMISSION_KEYS:
            raise ValueError(f"unknown permission flag: {key!r}")
        if not isinstance(value, bool):
            raise ValueError(f"flag {key} takes a boolean value")
        _apply_flag(user_id, key, value, connection=conn)
        account = _read_account(conn, user_id)
        return _flag_control(key, account["flags"], critical=False)
    if kind == "stance":
        capability, _, row_key = rest.partition(":")
        if capability not in _registry.CAPABILITIES or not row_key:
            raise ValueError(f"unknown stance control: {control_id!r}")
        if value not in _registry.STANCES:
            raise ValueError(f"unknown stance: {value!r}")
        _apply_stance(user_id, capability, row_key, value, connection=conn)
        stances = _store.get_stances(user_id, connection=conn)
        return _stance_control(capability, row_key, stances, critical=False)
    raise ValueError(f"unknown control id: {control_id!r}")
