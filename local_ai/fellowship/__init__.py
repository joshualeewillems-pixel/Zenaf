"""Fellowship Runtime — the shared event → evidence → interpretation layer.

Fellowship Runtime P1 (Joshua's doctrine, 2026-10-23 —
~/workspace/your_files/zenaf-fellowship-runtime-doctrine.md §2/§3):
the seven seats share one reality, but each interprets it through its
own jurisdiction. The doctrine pipeline is

    Event → Evidence → Character interpretation → Proposed action
          → User decision → Artifact

This package builds the pipeline's first three steps as durable
records:

  events.py       — the runtime event vocabulary, emitted at existing
                    chokepoints (conversation turns, claim verdicts,
                    task completions, meeting completions, decision
                    records) onto the append-only activity log
                    (local_ai/activity.py stays the transport; the
                    canonical entities stay in their own stores).
  observations.py — the observations store: one row per derived
                    observation — a seat's attributable, inspectable,
                    correctable reading of shared evidence.
  derivation.py   — the slow path: a deterministic, jurisdiction-
                    filtered pre-filter decides which seats even
                    consider an event; an LLM interprets only for
                    candidate seats. Runs off the reply path
                    (two-speed law): emitting code never waits on it,
                    and its failures are logged and swallowed.

Control invariants (doctrine §9): observations are proposals, not
claims; nothing here files into the review queue and nothing writes a
training signal. Evidence on an observation is the verbatim quote or
the entity reference — never a paraphrase presented as evidence.
Surfacing (the "!" attention layer) is P2, not this package.
"""
