# Doppelgänger Training Signals — Design Draft

**Status:** Draft for discussion, not implementation spec
**Date:** 2026-10-12
**Context:** Zenaf re-centered on an economy of personally trained AI agents. The doppelgänger trains on the owner's lived use first; rental is the graduation ceremony, not the goal. Training must come before rental mechanics.

---

## 1. The three signal layers

Every training signal — regardless of layer — answers the same question: *what did this person do, in what context, and what does it reveal about how they decide?*

### Layer A — Decisions (discrete, high-signal)

A decision event fires whenever the user resolves something: picking a council recommendation, choosing among alternatives in VE, accepting or overriding a suggestion. This is the most structured layer and the one to build first.

**What's missing today:** council runs produce a `CouncilRunArtifact` (question, seat judgments, synthesis, recommended action) but nothing records *what the user actually did next*. Decisions are scattered across VE entities and judgment history with no single "a decision happened here" event.

### Layer B — Behavior (tacit, domain-plugged)

Brush strokes, strum patterns, calendar habits, communication cadence, what gets escalated vs. handled quietly. Procedural knowledge that never appears in a decision log.

**Key architectural point:** every domain needs its own observation channel. Watching a guitarist has nothing in common with watching a CEO. So this layer is a **plugin architecture**: domain-specific observers that all emit a common signal envelope (see §2). No domain observer is built yet — this layer is greenfield.

**Permission is load-bearing:** observation is always opt-in per channel, per the consent model already started in `frontend/src/settings/sections/PermissionsSection.tsx` and `ConsentOnboardingGate.tsx`.

### Layer C — Guidance interactions (normative)

The system offers guidance shaped by the user's stated ideals; the user accepts, edits, or rejects. **Rejection is as informative as acceptance** — "don't steer me toward that" is a strong signal about who someone is versus who they claim to aspire to be.

**What exists:** `local_ai/aspiration_layer.py` (bounded aspiration profiles, guidance injection into council prompts), `aspiration_profile` / `aspiration_proposals` / `aspiration_inference_log` tables, and `AspirationsFoundationPanel.tsx`. What's missing is closing the loop: recording accept/reject/edit outcomes back into the profile as training signal.

---

## 2. Unified signal envelope

All three layers emit one common envelope. This is deliberately modeled on the existing `LearningRecord` (`local_ai/delegation/learning_capture.py`), which already solved the redaction/provenance/export problem for delegated calls.

```python
@dataclass
class TrainingSignal:
    signal_id: str            # stable id
    ts_ms: int                # when observed
    layer: str                # "decision" | "behavior" | "guidance"
    zone: str                 # specialization scope, e.g. "strategy", "creative"
                              # free-form at first; becomes the rental taxonomy later
    actor: str                # user id (owner); renters' signals stay with renters

    # What happened
    summary: str              # human-readable, redacted
    context_ref: dict         # pointers: council run id, VE entity ids, observer session id
    payload_redacted: str     # layer-specific detail, PII-stripped

    # Training semantics
    valence: str              # "endorsed" | "rejected" | "corrected" | "observed"
                              # endorsed   = user accepted / chose it
                              # rejected   = user dismissed / chose otherwise
                              # corrected  = user edited then accepted (correction IS the signal)
                              # observed   = no explicit judgment (behavior layer default)
    correction_diff: str | None  # when corrected: what changed (redacted)

    # Provenance (non-negotiable — see §5)
    provenance: dict          # source tables/rows, timestamps, software version
    supersedes: str | None     # signal id this replaces, if any
```

**Design rules:**
- Signals are **append-only**. The profile is a fold over signals; history is never rewritten, only superseded by pointer.
- Redaction happens at capture, not at read. Raw PII never enters the signal store.
- Every signal carries its provenance. A doppelgänger that can't show its work can't be rented.

---

## 3. Distillation paths (signal → profile)

Raw signals are not the profile. A **distillation job** (periodic + on-demand) folds signals into the core profile. Each layer distills differently:

| Layer | Distills into | Mechanism |
|-------|--------------|-----------|
| Decisions | Decision fingerprint: risk bias, decision style, time horizon, evidence preference, conflict style (fields already named in `docs/PERSONALITY_PROFILE.md`); promoted heuristics ("default to reversible decisions"); banked example fragments | Aggregate over decision events per zone; LLM-assisted summarization with human approval gate for heuristic promotion |
| Behavior | Style/technique patterns per domain; stored as domain-scoped profile facets, not global traits | Domain observers emit structured summaries (not raw streams); distillation is mostly aggregation + dedup |
| Guidance | Aspiration calibration (which ideals survive contact with reality); preference refinement | Accept/reject/edit tallies per guidance type; persistent rejection of an ideal flags it as aspirational-vs-actual drift |

**Convergence rule:** nothing enters the profile silently. Heuristic promotion and fingerprint shifts above a threshold require explicit user approval — the profile is *trained with* the user, not *on* them. This is also what makes the training legible later: "your strategist seat learned X from 40 decisions you approved."

**Hook points in existing code:**
- `CouncilRunArtifact` → emit a decision signal when the user acts on a council outcome (new: capture the *resolution*, not just the deliberation).
- `LearningRecord.user_outcome` (`applied`/`edited`/`dismissed`) → map directly onto signal valence. The pattern already exists; extend it beyond delegation calls.
- `aspiration_proposals` status changes → guidance signals.
- Core profile reconcile (`local_ai/vision_execution/core_profile_reconcile.py`) → add a decision-distillation pass alongside the conversation pass.

---

## 4. The training metric (per zone)

The publicly visible score that makes a rental legible. Computed from signals, never self-reported:

- **Volume:** observed signals in this zone (decisions + behaviors + guidance interactions).
- **Consistency:** how stable the distilled fingerprint is over recent signals (a seat that flip-flops is honest about it).
- **Outcome validation:** where outcomes are knowable (did the decision work out?), the hit rate. Sparse at first; grows with use.
- **Endorsement ratio:** share of guidance/suggestions accepted vs. rejected — a live measure of "does it act like me."
- **Renter feedback** (later, post-marketplace): structured, per-zone.

The metric is what goes on the rental listing. It rises symbiotically: more owner use → sharper profile → higher metric → more rentals → more diverse signal → sharper profile.

---

## 5. Non-negotiables (carried over from existing policy)

These already exist in `docs/01_TRUTH/FRUIT_MINT_POLICY.md` and the charter; they become load-bearing under the rental vision:

- **Provenance or it didn't happen.** No signal without a traceable source. No profile claim without signals behind it.
- **No false precision.** The metric reports what was measured, not what it implies about the person. "412 observed strategy decisions, 89% consistency" — never "this person is a great strategist."
- **Ideals are gravity, not identity.** The profile tracks both the descriptive (what you do) and the normative (what you aspire to); they must never be conflated in what a rented seat presents.
- **Observation is consent-gated, always.** Per channel, revocable, with visible state.

---

## 6. Build order

**Phase 1 — Decisions (now):** decision signal emission on council resolution + VE decision points; signal store (SQLite, append-only); distillation job v1 (fingerprint aggregation + heuristic proposals with approval gate).

**Phase 2 — Guidance loop:** close the aspiration accept/reject loop into signals; aspiration calibration in distillation.

**Phase 3 — Behavior plugins:** observer plugin interface + one reference observer (pick the domain you personally care about most — dogfood it); behavior signals into the same store.

**Phase 4 — Metric:** per-zone training score computed from the signal store; surfaced in the profile UI. This is the last training milestone before rental mechanics make sense.

**Explicitly deferred:** listing, pricing, metering, payout (rental mechanics); cross-user signal sharing; the frozen tokenomics/fruit layer (revisit only if the value layer needs a native unit).

---

## Resolved design decisions (2026-10-12, with Joshua)

1. **Zone taxonomy: free-form surface, learned underlying taxonomy.** Zones are user-defined strings, but the system builds cross-zone relevance underneath: a signal in one zone can inform traits in another. An aggressive brush stroke in a creative zone legitimately trains the confidence/risk-taking trait that a strategy zone also reads. Transfer is learned from co-occurrence, not hand-mapped — the taxonomy emerges from the signal graph.
2. **Correction as signal:** store the diff summary plus redacted before/after snippets (same pattern as `LearningRecord.outcome_diff_summary`). No further definition needed.
3. **Decay with archival snapshots.** Signals decay where parallels don't persist — stale patterns fade. But profile builds are occasionally archived as immutable snapshots, creating a *temporal version history* of the doppelgänger. This unlocks era-rental as a product feature: someone might rather rent the decision-making of 1980s Steve Jobs for their small business than later Steve Jobs with a different priority set. Each snapshot is a distinct rentable SKU with its own training metric.
4. **Actor attribution via device biometrics.** Multi-user/shared-machine disambiguation rides on the biometrics already present on devices (Face ID, fingerprint), not on app-level login discipline.

## Open questions (remaining)

1. **Snapshot cadence — resolved:** all three triggers. (a) Time-based: one automatic snapshot per year by default. (b) Volume-based: after a substantial training uptick in a zone — heuristic starting point is ~100% growth in zone signal volume or a dramatic fingerprint shift; exact metric definitions still need algorithmic work. (c) User-initiated: manual "save this version of me" at any time.
2. **Cross-zone transfer weights — resolved:** the system proposes, the user disposes. When the system detects transferable signal it asks explicitly: "I noticed you did X, which can translate to Y in this way — do you want this training to apply?" The response itself becomes training signal (same accept/reject pattern as ideals guidance). Transfer starts conservative and only applies on confirmation.
