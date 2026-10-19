"""The conversation skeleton — one persistent conversation per user.

The skeleton is the conversation that never ends: it branches into personas
(seat chips tag each turn with an archetype_id) and into site activities
(each turn can carry a live-context snapshot: open sheet, entity in focus).
History carries across seats; per-seat thread_state keeps each persona's
quiet background continuity. The conversation is the front end of the
training economy — suggestions.py reads it to propose review moments,
project proposals, and mint suggestions, all as drafts, never filed.
"""
