"""Per-seat "You" profiles — the user's trained echo of each council seat.

The Zenaf/You switch: Zenaf = the canonical archetype character; You = the
user's own echo of that seat, fashioned by their approved training data.

HARD PRINCIPLE (Joshua, 2026-10-19): personal identity is a durable
first-class record — NEVER stored in thread_state, which is ephemeral
conversation state (rolling summaries, rebuilt every 20 turns).

Data design — REFERENCE, not duplication: this store holds only the identity
fields that exist nowhere else (the echo's co-named personal name, its avatar
reference, a pinned snapshot pointer). Depth lives in the naming/depth
machinery; training signals live in the canonical TrainingSignal store;
persona versions and snapshots live in the PersonalityStore. Those are
ground truth; this record is the consolidation index that points at them.
"""
