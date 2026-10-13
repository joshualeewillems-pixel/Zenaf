# Agent Intake & Sorting ("The Sorting")

## The problem

Users arrive with AI agents scattered across platforms — custom GPTs, Claude
Projects, specialized bots, single-purpose assistants. Each one represents
real investment: crafted instructions, discovered use cases, tuned behaviors,
hours of "oh, it does *that* well." Today they're siloed in other companies'
products.

Zenaf should be where they all come together: connected, understood, and
sorted into the user's growing digital self — feeding the right strand agents,
linking to the right projects, becoming part of the Living Tree.

This is distinct from presence ingestion (which imports *history*). This
imports *agents* — living, purpose-built entities the user has already trained
through use.

## Connection points

Five intake methods, ordered by friction (lowest first). v1 ships the first
three; interview and import are designed for but not built yet.

1. **Describe** — natural language. "I have a GPT that helps me write cold
   emails." Lowest friction, the default.
2. **Paste instructions** — the agent's system prompt / custom instructions.
   Highest signal per unit of effort; this is the agent telling us what it is.
3. **Paste examples** — 2–3 example interactions showing what it actually does.
   Grounds the description in behavior.
4. **Guided interview** *(future)* — Zenaf asks 3–5 questions for users who
   don't know where to start. ("What do you use it for? What does it do that
   surprises you?")
5. **Import** *(future)* — API / OAuth / file import when platforms allow it.
   The adapter pattern from presence ingestion (`SourceAdapter`) is the model.

All text is redacted at capture, per the existing redaction contract. Nothing
trains until the user reviews and approves it.

## The sorting process

### The core idea: the council sorts itself

Instead of a separate black-box classifier, **the seven strand agents do the
claiming**. When an agent is connected, each strand agent reads its
description / instructions / examples and makes a case — "this belongs to me,
because…" — or passes. Every strand with a claim above threshold trains on
the agent's material, weighted by claim strength.

**Training influence is multi-frame, not winner-take-all.** There is no
reason the same data wouldn't shape several agents: a negotiation coach that
writes brilliant follow-up emails trains the Mediator *and* the Storyteller.
The strongest claim becomes the *display* anchor (the Living Tree branch),
but it gates nothing — the material routes to every qualifying strand.

Why this instead of a keyword classifier:

- **Explainable.** Every placement comes with reasoning the user can read and
  argue with, not a score from a void.
- **Multi-strand native.** A 70% Word / 30% People agent feeds both, weighted.
  No rounding off.
- **Dogfooding.** The product uses itself to grow itself — the council is the
  intake engine, not a sidecar.
- **Progressive.** v1 is rule-based (fast, deterministic, no AI needed, fully
  testable). v2 upgrades the claiming to a frontier LLM (see "Engine choice"
  below). v3 lets the council genuinely deliberate. The contract —
  `sort(agent) -> SortResult` — doesn't change across versions.

### Skill vs. talent vs. project

The user never fills out a "what kind is this" form. The kind is read from
*how the agent is described*:

- **Skill** — a trained capability. "It helps me do X." Procedural language
  ("steps," "process," "template," "always starts by…"), produces artifacts.
  Feeds the strand agent as capability training.
- **Talent** — an innate aptitude. "It just *gets* X." Intuition language
  ("taste," "sense of," "naturally," "you wouldn't believe what it noticed").
  Feeds the strand agent as aptitude signal — weighted differently, because
  talent is about judgment, not procedure.
- **Project** — goal-directed work. "We're working on Y." Project language
  ("my novel," "the launch," "for my course," named endeavors). Links to
  Vision Execution rather than (or in addition to) a strand.

Linguistic markers propose; the user disposes. When the markers are
ambiguous, the system *probes* instead of guessing.

### Probing, not forms

If the description is thin or the classification is low-confidence, Zenaf
asks 2–3 tailored disambiguation questions rather than presenting a taxonomy:

- "You said it's a writing helper — does it help more with *structure*,
  *style*, or *generating ideas*?"
- "Is this for a specific project, or a general capability you use everywhere?"
- "When it does its best work, what did *you* bring vs. what did *it* bring?"

Each answer refines the sort. The interview is a conversation, not a form —
and the answers themselves become training material (with approval).

### The review gate: corrections train the sorter

The user is shown: "Here's where I think your agents belong," with each
placement's reasoning. They accept or correct. Every correction — "no, this
is a People *talent*, not a Word *skill*" — is an **ideals-guidance training
signal** that improves future sorting. The sorter learns the user's personal
taxonomy over time, the same way the strand agents learn everything else.

This is the same review-gate pattern as presence ingestion, applied to
classification instead of redaction.

### Cross-strand as first-class

An agent with strong secondary claims is not rounded off. It is placed
primarily, linked secondarily, and the user is asked before any training
transfers across strands — the existing ask-before-apply rule. The yes/no is
itself a training signal: it teaches the system which cross-zone transfers
this user endorses.

## Data model

```python
@dataclass
class StrandClaim:
    strand: StrandKey          # which strand agent is claiming
    score: float               # 0.0–1.0
    reasoning: str             # why, in plain language

@dataclass
class SortResult:
    primary_strand: StrandKey
    claims: list[StrandClaim]  # all seven, sorted by score
    kind: Literal["skill", "talent", "project", "undecided"]
    kind_reasoning: str
    linked_projects: list[str] # vision-execution IDs, when kind == "project"
    confidence: float          # 0.0–1.0; low confidence triggers probing
    needs_probing: bool

@dataclass
class ConnectedAgent:
    id: str
    name: str
    source_platform: str       # "chatgpt" | "claude" | "manual" | ...
    description: str            # redacted
    instructions: str | None   # redacted system prompt, if pasted
    examples: list[str]        # redacted
    sort: SortResult | None
    status: Literal["pending_review", "active", "archived"]
    created_at: str
```

## Pipeline

```
connect(name, platform, description, instructions?, examples?)
  → redact at capture
  → sort() → SortResult
  → if confidence < threshold: probe (ask 2–3 questions, re-sort with answers)
  → review queue (user accepts / corrects)
  → on accept: status=active, link to strand agent(s), optionally link project
  → on correct: record correction as ideals-guidance signal, re-sort
```

## Integration with the existing system

- **Living Tree** — connected agents appear as branches under their primary
  strand; tap a branch to see the agent's story (what it does, where it came
  from, what it feeds).
- **Training signals** — an agent's instructions and examples become training
  material for its strand agent, once approved. This is the fastest way to
  bootstrap strand training: the user has *already* done the training work
  elsewhere; Zenaf harvests it with consent.
- **Identity license** — connecting an agent requires an active license; the
  agent's data is the user's contribution (their instructions, their examples),
  scoped accordingly.
- **Presence ingestion** — when the user imports conversation history with the
  same agent, the two are linked: history grounds the agent's claimed
  capabilities in observed behavior.
- **Vision Execution** — project-kind agents link to projects by semantic
  match; the agent becomes a resource *of* the project.

## v1 scope

- `local_ai/agent_intake/`: `schema.py`, `sorter.py` (rule-based strand
  markers + kind markers), `pipeline.py`, `store.py` (SQLite).
- API: `POST /agents/connect`, `GET /agents/pending`,
  `POST /agents/{id}/confirm`, `GET /agents`.
- Tests: sorter accuracy on a labeled fixture set; pipeline redaction +
  review-queue behavior.
- v2 (not this PR): frontier-LLM claiming, probing questions, Tree branches,
  project semantic linking, account scrubbing (below).

## Engine choice: frontier LLMs for the scrub, not slow local models

The claiming/scrubbing step is a *batch* job — it runs at intake time, not in
a real-time loop. For batch understanding work, a frontier LLM (GPT, Claude)
returns better judgments in seconds than a slow local pipeline returns in
minutes. v1's rule-based sorter stays as the instant offline default (and the
testable contract), but v2's claiming engine should call out to a frontier
model with the seven strand personas as the prompt framing — each strand
reads the material and argues its claim. Local models remain an option for
the privacy-maximal path, but they are not the default for this job.

## Account scrubbing: the seven as harvesters

Beyond one-at-a-time agent intake, the user connects *accounts* — ChatGPT,
Claude, and whatever else exposes access — and the seven strand agents scrub
them for material: custom instructions, conversation patterns, recurring
topics, demonstrated capabilities. Each strand pulls what belongs to it;
everything lands in the review queue before it trains anything.

Honest constraints: neither ChatGPT nor Claude offers a public personal-data
API today, so "log in and scrub" can't be a direct integration yet. The
feasible v1 paths are: OAuth where it exists (Gmail already works), official
exports (ChatGPT/Claude/X — the presence-ingestion adapters), and
browser-assisted capture later. The architecture treats every source as an
adapter behind the same `sort()` contract, so a real ChatGPT/Claude account
adapter slots in the day the platform allows it — no redesign.

## What makes this cleverer than what exists

The existing intake (`local_ai/intake/`) is rule-based classification for a
fixed domain (clinic mail). Presence ingestion parses *formats*. Neither
*understands* what it's holding.

The Sorting understands: it reads an agent's own words about itself, lets the
seven strand agents argue over it, asks the user smart questions when it's
unsure, learns from every correction, and places the agent in a living
taxonomy instead of a folder. The intake process is itself the first training
interaction — by the time an agent is connected, the system already knows
something about how its user thinks.
