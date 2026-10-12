# Presence Ingestion — Design

**Status:** Implemented (2026-10-12), branch `feature/presence-ingestion`
**Context:** Zenaf re-centered on an economy of personally trained AI agents.
The doppelgänger trains on the owner's lived use first — but a brand-new user
has no lived use yet. That's the cold-start problem.

## Why: "your conversations trained their models, now let them train yours"

People already talk to their AIs as intimately as their personal therapists —
sometimes more so. Years of revealed preferences sit in ChatGPT and Claude
exports today: what they ask, how they push back, what they vent about, which
advice they take or reject. And it doesn't stop at AI chats: posts, emails,
notes — any digital presence is potential training signal.

The pitch is the mechanism: with the user's explicit permission, Zenaf imports
their existing digital presence and distills it into training signal for
*their* doppelgänger. The intimacy that currently trains corporate models
becomes the user's own asset. This is the AI–human solidarity story in one
feature: your data trains you, not them.

As onboarding it's a wedge: upload your history → your council already knows
you on day one.

## Pipeline stages

```
upload -> detect source -> parse (redact at capture) -> distill (candidates)
       -> review (user approves/rejects) -> approved signals join training set
```

1. **Upload** (`POST /ingest/upload`, 200 MB cap): the raw export is stored
   under `data/presence_ingest/uploads/<session_id>/`, local disk only.
2. **Detect + parse**: the adapter registry probes the file; the winning
   adapter emits `PresenceEvent`s. Text is redacted *at capture* (emails,
   phones, SSNs, long digit runs → tokens) and capped at 8000 chars.
   Malformed records are skipped and counted, never fatal — real exports
   are messy.
3. **Distill** (`POST /ingest/sessions/{sid}/distill`): events are grouped
   into conversation-sized batches and sent to the **local** Ollama instance
   with an extraction prompt. The model extracts candidate `TrainingSignal`s
   (status=`pending`). If Ollama is unreachable, distillation raises
   `DistillError` — it never fabricates signals.
4. **Review** (`POST /ingest/sessions/{sid}/review`): the user approves or
   rejects each candidate. Rejected rows are kept as an audit trail, never
   deleted. Only approved signals become training data.
5. **Delete** (`DELETE /ingest/sessions/{sid}`): removes the raw upload and
   the session's events. Approved signals deliberately **remain** — they are
   the user's training data now; deleting the source must not rewrite
   training history.

## Adapter contract (adding new sources)

Subclass `SourceAdapter` in `local_ai/presence_ingest/adapters/`:

- `source_id` / `display_name` — stable identifiers.
- `detect(path) -> bool` — cheap, side-effect-free probe; must not raise.
- `iter_events(path) -> Iterator[PresenceEvent]` — defensive parse; skip +
  count malformed records via `self.last_skipped`; redact every event's text
  with `redact_text()` and cap with `cap_text()` before yielding.

Then append an instance to `ADAPTERS` in `adapters/registry.py` (more
specific detectors first). Shipped adapters: `chatgpt` (conversations.json),
`claude` (conversations.json, tolerates `conversation_messages` variant),
`x` (tweets.js — proves the "any digital presence" extensibility).

## Privacy rules

- **Local-only.** No external API is ever called. Distillation uses Ollama on
  localhost; the store is SQLite under `data/presence_ingest/`.
- **Redaction at capture, not at read.** Raw PII never enters the event or
  signal store. No endpoint returns unredacted text.
- **Approval gate.** Nothing enters the profile silently: every distilled
  signal starts `pending` and requires explicit user approval, per the
  convergence rule in the training-signal spec.
- **Raw export deletable.** The user can delete the uploaded export and its
  events at any time. Approved signals persist as training history.
- **Provenance on everything.** Each signal records its source events,
  adapter, and distillation timestamp — a doppelgänger that can't show its
  work can't be rented.

## Mapping onto the three training layers

The distillation prompt asks the LLM to extract along the spec's three layers
(`TRAINING_SIGNAL_DESIGN.md` §1):

| Layer | What the import reveals |
|-------|------------------------|
| Decisions | Choices the user made or leaned toward in past conversations (what they picked, committed to, decided against) |
| Behavior | Communication and decision-making style: how they frame problems, what they escalate, cadence, tone |
| Guidance | Values and beliefs: what they praised, rejected, or pushed back on — including pushback against the AI itself, which is ideals-guidance signal |

Valence follows the spec: `endorsed` / `rejected` / `corrected` / `observed`,
defaulting to `observed` unless the evidence is explicit.

## Contribution claims ("I played guitar in this song")

Imported material is often collaborative — and the doppelganger must learn
from the *user's part*, not the whole. A contribution claim is the user's
assertion of their role in a collaborative work: role ("guitar"), parts
("lead guitar, verses; not the solo"), optional extent (sections, time
ranges), and collaborators if known.

Three reasons claims exist:

1. **Epistemic.** Signals distilled from claimed events learn from the
   contribution; the rest of the work — other contributors' parts, the
   overall production — becomes context, not training data. Without this,
   the model would train on the drummer's playing and call it yours.
2. **License honesty.** The identity license covers the user's
   *contributions*, never whole works. Claims are what keep re-anchoring
   truthful: importing a song re-anchors *your guitar performance*, not
   the song.
3. **Zones.** A claim's role maps naturally onto specialization zones
   (guitar → music), timestamped, feeding the temporal snapshots that
   enable era rental.

Lifecycle: define (`POST /ingest/sessions/{sid}/contributions`, opt-in per
item — never a gate on the simple path) → distill (the extraction prompt is
injected with "the user's contribution was X; learn from the contribution
only"; resulting signals are tagged with `contribution_claim_id` and
`contribution_role`) → review (the usual approval gate still applies).

Claims are user assertions, not audit records: freely editable and
deletable, unlike append-only signals. The schema carries an `attestations`
field, reserved and always empty for now, for future multi-party
confirmation — when both collaborators are on Zenaf, contributions can be
mutually confirmed, becoming the trust layer for collaborative training
data the way the training metric is for rentals.

## Honest caveats

- An import is a **foundation, not the whole picture**. People roleplay and
  perform with AIs too; the live training loop (decisions, behavior
  observation, ideals guidance) is what separates performance from person.
- Official exports only — no scraping, no credential harvesting. The user
  downloads their own data and hands it to Zenaf.
- LLM extraction is lossy and occasionally wrong. That's what the review gate
  is for: the user is the final arbiter of what their doppelgänger learns.
