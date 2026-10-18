"""Follow-through engine v1 — backend.

Watches the user's tasks, projects, growth states, and explicit commitments,
and surfaces gentle, explainable nudges. Principles (decided with Joshua):

- Dates are optional. Many things don't have them; the engine never requires them.
- Non-linear things get growth states, not timelines (the rehabilitated "stones").
- Nudge once, never nag: the engine logs every nudge and never re-surfaces the
  same (kind, entity) while one is unacknowledged, or within a cooldown of an ack.
- Every nudge carries its why: traceable, falsifiable, never a bare "do this."
- Nudges share the "seat wants to talk" surface with the persona unlock
  mechanic — each nudge carries an optional ``suggested_seat`` as the
  integration contract for that UI.

``GET /followthrough/nudges`` is the feed the future today-aggregate consumes;
its response schema is the stable integration contract.
"""

from local_ai.followthrough.service import FollowthroughService
from local_ai.followthrough.store import FollowthroughStore

__all__ = ["FollowthroughService", "FollowthroughStore"]
