"""Growth states and engine tuning constants.

Growth states rehabilitate the old "stones" concept: non-linear work gets
*progression* instead of timelines. ``None`` means "linear / not applicable" —
most entities will never have a growth state, and that's fine.
"""

from __future__ import annotations

# Forward-only progression: seed → sprout → sapling → bloom → fruit.
GROWTH_STATES: tuple[str, ...] = ("seed", "sprout", "sapling", "bloom", "fruit")

# Entity types that may carry a growth state.
GROWTH_ENTITY_TYPES: tuple[str, ...] = ("task", "project")

# --- watcher tuning (constants, per spec) ------------------------------------
# Days before a due date that it counts as "approaching".
APPROACH_DAYS = 3
# Days without updated_at movement before an active entity counts as stalled.
STALL_DAYS = 7
# Days without a growth transition before a growth-state entity gets a gentle nudge.
GROWTH_STALL_DAYS = 14
# Days after an ack during which the same (kind, entity) stays quiet.
RE_NUDGE_COOLDOWN_DAYS = 7

# --- severity ordering --------------------------------------------------------
SEVERITY_ORDER = {"must": 0, "should": 1, "could": 2}


def validate_growth_state(state: str | None) -> str | None:
    """Validate a requested growth state; ``None`` clears it. Raises ValueError."""
    if state is None:
        return None
    s = str(state).strip().lower()
    if s not in GROWTH_STATES:
        raise ValueError(
            f"unknown growth state {state!r}; expected one of {list(GROWTH_STATES)} or null"
        )
    return s


def allowed_transitions(current: str | None) -> list[str]:
    """Forward-only transitions from ``current`` (None → any state; clear always allowed)."""
    if current is None:
        return list(GROWTH_STATES)
    idx = GROWTH_STATES.index(current)
    return list(GROWTH_STATES[idx + 1 :])


def check_transition(current: str | None, new: str | None) -> None:
    """Raise ValueError unless ``new`` is a legal forward transition from ``current``."""
    new = validate_growth_state(new)
    if current is not None:
        validate_growth_state(current)
    if new is None:
        return  # clearing is always allowed
    if current is None:
        return  # any first state is allowed
    if new not in allowed_transitions(current):
        raise ValueError(
            f"growth states only move forward: {current!r} cannot become {new!r} "
            f"(allowed: {allowed_transitions(current)} or clear)"
        )
