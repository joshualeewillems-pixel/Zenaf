# Bounded Reliability Mandate v1 — Evidence Summary

Branch `mandate-reliability`, base 0ba8061 (= origin/main, includes PR #246).
No merge, push, PR, deploy, flag change, staging/production write, or
model spend at any point. All acceptance evidence is local replay of
the two stored stage-1 response files plus unit tests.

## 1. Root causes (each verified from stored registries + raw texts)

- **R1. Preamble bleed + first-match precedence → C54 "defended".**
  Claude's probe revision header contains "**Relationship:** Defended
  with clarification…" and "**Defending C6–C13 against C31, C33, C37,
  C39, C44, C45**". Old scope (preamble + text) matched "Defending
  C6" before the span's own "(Revised)" stance. Result: a
  reclassification was recorded as a defense, and C6's disposition
  became "maintained" by C54. (Note: `claim_standing.py` ignores
  defended links, so C6's derived "active" came from absence of valid
  moves, not from the defense — the defense corrupted the record,
  not the derived standing directly.)
- **R2. Parenthetical stance markers never attach → C55, C56 dropped.**
  "(Defended)", "(Withdrawn)", "(Revised)" followed by ")" fail the
  tight verb-target pattern (requires whitespace after the word), and
  the bare-word fallback requires "in response to" or "my claim" —
  absent → ("unstated", "unstated"). The genuine defense (C55) AND
  the citation withdrawal (C56) both dropped.
- **R3. Vocabulary gap → C68 dropped.** "retract/retracted" was not in
  the relationship word set (only withdraw/revised/defended families).
  C68's "they are retracted" yielded no word at all.
- **R4. List/range blindness → C70, C56, C54 targets lost.** No
  pattern handled "Withdrawn: C27, C28, C29, C30–C44" (colon + list +
  en-dash range) or "citations in C6–C9". `claim_standing.py`
  `_expand_reference` existed but only for SIGNALS, never for moves.
  (The stage-3 prompt contract — "a range such as C6–C9 is not a
  move" — governs what models are ASKED to emit going forward and is
  unchanged; the parser must still not silently drop explicit
  withdrawals when models emit ranges anyway.)
- **R5. No reclassification record → C54's downgrade had no derived
  state.** Even with R1 fixed, the vocabulary had no "reclassify"
  move: revised→supersedes would make C6 "superseded", misrepresenting
  "still asserted, just inferred" and conflicting with A7's principle.
- **R6. First-wins disposition vs last-wins standing (latent).**
  `_apply_dispositions` freezes disposition at the first revision;
  standing derivation is last-wins. For the named cases this did not
  independently block anything (no later valid move existed), but it
  is a hazard after a defense-then-withdrawal sequence. Standing is
  authoritative; disposition is display-only. Out of minimal scope —
  see backlog.
- **R7 (Gap 2). No prose-evidence audit existed at all.** The citation
  validator checks parseable citations against the generation's tool
  log (fail-closed, good), but prose inspection-assertions ("*[Read
  completed…]*", "The request… was made") were never checked against
  any log. The tool log itself IS complete for runner-mediated
  attempts: `tool_log_sink.extend(entries)` is unconditional and
  `_drain_tool_log` appends all entries; empirically the probe
  transcript shows refused entries (3× meeting.py refused
  not_nominated, aggregate_token_budget_exceeded refusals,
  call_budget_exceeded cap).

## 2. Mechanism chosen per gap

**Gap 1 — parser (`meeting.py`), derivation (`claim_standing.py`),
table rendering (headline `effective:`), completeness
(`record_completeness.py`).**
- Retract-family vocabulary added to both tight patterns, normalized
  via `_normalize_stance_word` (retract* → withdrawn).
- Sentence-scoped stance rescue `_stance_move_in_scope`, running ONLY
  when tight patterns yield no target (previously working parses
  unchanged): P2 immediate list, P3 object phrasing, P4 anaphoric
  range. Negation guard (40-char window, bare "no" excluded, same
  precedent as signals). Range expansion cap 50, fail-closed.
  List grammar terminates on non-list tokens (so "revised: C4 in
  response to objection C34" yields [C4] only).
- Span-own precedence in `_analyze_span`: span text first; preamble
  fallback only when span text carries no stance word; plus a
  same-stance preamble-target fallback (a span stance word with no
  target takes the preamble's target for the SAME stance only —
  added after catching a regression, see §6).
- Reclassification detector `_reclassification_in_span`: requires ALL
  three — revised-family word, status-pair pattern, framing-retraction
  cue (retract*/framing/"presented as"). Without the cue, a bare
  status correction stays ordinary supersession (documented boundary).
- P3 scope split: evidence nouns (citations, sources, references,
  read statements) → citation scope; content nouns (claims,
  statements, values, figures, numbers) → claim scope. A
  citation-scope withdrawal links as `withdraws_citations`, a
  recorded non-move that derivation and disposition both ignore
  (A7). A citation-scope revision/defense moves no claim at all.
- Claim dataclass gains optional `relationship_targets: list[str]`,
  `reclassified_status: str | None`. Consumers use the list when
  non-empty, else single fields. Single-target convention: tight
  parses still fill single fields; rescue parses fill the list
  (first target also in `relationship_target` for display).
- Derivation validates multi-target links per target (exists,
  strictly earlier, same author; bad targets → rejected_moves;
  cross-author → proposal, never a move, never a rejection).
  Reclassification links build `reclassification_chain`; entry gains
  `effective_status` (last valid reclassification, else authored).
  Headline appends " | effective: X" only when effective != authored.
  Table version stays 1 (additive fields).

**Gap 2 — new pure module `evidence_audit.py` (stdlib only).**
`audit_prose_evidence_claims(claims, tool_calls,
log_complete_participants=frozenset())` + `render_evidence_audit`.
Verdicts concern the INSPECTION assertion only, never claim content.
Patterns: read-completed narrations (path, requires "/"),
first-person performed reads, attempted reads, request-made, I-read.
Path matching on requested_path equality or resolved-path suffix.
Attempt assertions: any logged attempt (returned/refused/capped)
verifies. Completed-read assertions: only a returned read verifies.
`log_complete_participants` is caller-attested, default empty
(conservative); the function never assumes completeness.
Contradicted ONLY under attestation + no matching entry; otherwise
unverified — never contradicted, never verified without support.
Honest negatives ("I performed no read_file calls", "No file reads
have been performed", "I read the packet") and meta-discussion
("GPT's performed reads", quoted narrations) are never flagged.
The citation validator is untouched; no second LLM; no
factual-truth scoring. Runner wiring / artifact persistence of the
audit is NOT included (acceptance needs replay + tests only) — see
backlog.

**A9 completeness reasoning (documented, not pre-decided).**
(1) GPT is runner-mediated (12 logged calls in live validation).
(2) The runner logs every attempt including refusals/caps (code +
probe demonstration: refused meeting.py entries ARE in the log).
(3) Same runner code version for both meetings (33ef4cc).
Live-validation log holds 12 GPT attempts, none for meeting.py →
the asserted request did not occur through the runner. Caveat
preserved: this proves no RUNNER-MEDIATED request; C5's conclusion
("not inspected") remains accurate — only the "request was made"
premise is contradicted.

## 3. Derived tables — before / after (local replay)

Before = derivation over the STORED registries (which contain no
structured moves, so old and new derivation agree on them).
After = derivation over the REPLAYED registries (fixed parser).
Replay identity: probe 71/71 claims, live 75/75 claims, zero text
mismatches, zero missing/extra claims.

### Probe (meeting 3f602c4d2163) — A3, A4, A5, A6, A7

| claim | before: standing / authored / effective | after: standing / authored / effective |
|---|---|---|
| C6 | active / Observed / Observed | active / Observed / **Inferred** |
| C7–C10 | active / Observed / Observed | active / Observed / **Inferred** |
| C11–C13 | active / unknown / unknown | active / unknown / **Inferred** |
| C61 | active | active (unchanged — A5) |
| C6–C9 | assessment challenged, standing active | assessment challenged, standing active (A6) |

Record changes (probe): C54 defended → **reclassifies** C6–C13
Inferred; C55 unstated → **defended** C6–C13; C56 unstated →
**withdraws_citations** C6–C9 (content stays active — A7; C6–C9
citations were already validator-unverified in the stored record);
C62 unstated → **proposes_revision_of** C4 (cross-author proposal,
no standing effect); C69 supersedes field → list form [C27]
(derivation-equivalent); dispositions C6–C13 "maintained" by C55
(display-only; standing authoritative; C6's disposition_by moves
C54 → C55 because C54 is no longer a defense).

### Live validation (meeting fbf4d08ef239) — A1, A2, A9

| claim | before: standing | after: standing |
|---|---|---|
| C30–C37 (authored Observed) | active | **withdrawn** |
| C27–C29, C38–C44 | active | **withdrawn** |

Record changes (live): C68 unstated → **withdrawn** 18 targets
(C27–C44); C70 unstated → **withdrawn** 18 targets (C27, C28, C29 +
C30–C44); dispositions C27–C44 "withdrawn" by C68 (first-wins
display; C70's later identical move does not change standing);
C71/C72/C73 list-form targets [C1]/[C4]/[C5] (derivation-equivalent
record-shape change, see §6).

### Evidence audit — A8, A9

Probe (complete={GPT}): C1 **verified** (attempt + logged refusal),
C48 **verified** (same), C8/C10/C12 **unverified** (narrated reads,
zero Claude tool calls). No other findings — honest negatives and
meta-quotes (C33, C35, C42, C54, C68-Muse) not flagged.
Live (complete={GPT}): C5/C26/C65 **contradicted** (request-made,
complete log, no meeting.py attempt). Same claims without the
attestation: **unverified**. Nothing is ever presented as verified
without a logged supporting attempt.

## 4. Tests

- New file `tests/test_build_room_mandate_reliability.py`: **34 tests**
  (12 parser, 8 derivation, 7 audit-unit, 7 replay), all passing.
- Fixtures `tests/fixtures/mandate_{probe,live}_replay.json`: reduced
  copies of the stored responses (contributions + phases, claim
  registries, interactions, tool logs). Zero model spend.
- Build-room subset (r2, legibility, claim_standing, runner,
  standing_completeness, standing_migration, migration_execution,
  migration_inventory): **90 passed**. The mandate file passes its
  **34 tests standalone**.

## 5. Full-suite comparison (A10)

- Baseline (pre-change, HEAD 0ba8061, measured 2026-10-28):
  **20 failed, 1798 passed, 5 errors.**
- Final (branch mandate-reliability, all stages):
  **20 failed, 1832 passed, 5 errors.**
- Fail sets **identical** (diff exit 0); error sets identical
  (parked/test_soil_api.py, parked/test_soil_kernel.py,
  tests/test_intake_quality.py, tests/test_intake_synthetic_regression.py,
  tests/test_sqlite_pragmas.py).
- Passed delta **+34 = exactly the 34 new mandate tests**. Zero new
  failures, zero changed failure signatures, nothing to explain
  away.
- Note: the mandate plan cites "20 failures + 3 errors"; the measured
  baseline has 5 errors (the 3 tests/ collection errors plus 2
  parked/ collection errors, all pre-existing). A10 is judged against
  the measured 20+5, the conservative reading.

## 6. Regression caught and fixed during verification

The intermediate full-suite run showed 21 failures: one NEW failure,
`tests/test_build_room_r2.py::test_revision_relationships_revised_defended_withdrawn`.
Cause: stage-1 span-own precedence overcorrected — a span stance word
with no target ("Withdrawn: Gamma is retracted.") never consulted
the preamble, but that test's target lives in the preamble
("Relationship: withdrawn. In response to C3, I withdraw it:").
Fix (committed): same-stance preamble-target fallback (§2). The
final full-suite run above is clean; the intermediate failure is
reported here, not hidden. Two unit tests lock the rule and its
boundary (different preamble stance never overrides the span).

Record-shape note (not a regression): rescue parses store targets in
`relationship_targets` (first target also in `relationship_target`
for display); tight single parses still use single fields only. The
replay-divergence test pins the exact set of record changes, so any
future parser change that alters another record fails loudly.

## 7. Commits (branch mandate-reliability, none pushed)

- 666000f — stage 1: withdrawal/range/reclassification parsing
  (`meeting.py`).
- f3c6db7 — stage 2: multi-target moves + effective status
  (`claim_standing.py`, `record_completeness.py`).
- b10c71c — stage 3: prose evidence-claim audit (`evidence_audit.py`).
- 53f62fb — citation-scope stances never move content, A7
  (`meeting.py`).
- 3ac947b — stage 4: acceptance tests + fixtures (34 tests at that
  point; 2 more added by c3f8716).
- c3f8716 — same-stance preamble target fallback + 2 tests.

Files changed: `local_ai/build_room/meeting.py`,
`local_ai/build_room/claim_standing.py`,
`local_ai/build_room/record_completeness.py`,
`local_ai/build_room/evidence_audit.py` (new),
`tests/test_build_room_mandate_reliability.py` (new),
`tests/fixtures/mandate_probe_replay.json` (new),
`tests/fixtures/mandate_live_replay.json` (new).

## 8. Backlog (one line each; none in scope, none auto-activated)

- Disposition first-wins can disagree with last-wins standing after
  a defense-then-withdrawal sequence.
- C61-style "(Contested, preserved)" has no relationship vocabulary
  (stays "unstated"; standing outcome correct, record legibility
  could gain a "preserves" non-move label).
- Persist the evidence audit as an artifact section + runner wiring
  (acceptance needs replay + tests only).
- Audit negative absence-claims (e.g. live C70 "No read_file tool
  has been invoked or logged" vs 12 logged invocations) — same Gap-2
  class, opposite direction, not in A8/A9.
- Reclassification detector requires a framing-retraction cue; bare
  status corrections ("I revise C6: it is Inferred, not Observed"
  without retract/framing language) parse as ordinary supersession.
- Tight verb-target patterns carry no negation check ("I do not
  withdraw C6" still parses as withdrawn); only the rescue loop is
  negation-guarded.
- Citation-scope revised/defended stances are not recorded as links
  (only citation-scope withdrawals are); no named case needs them.
- Live validation's C5/C26/C65 conclusion ("not inspected") stays
  accurate; only the "request was made" premise is contradicted —
  the audit verdicts the premise, never the conclusion.

## 9. Verdict

**R1-ready: A1–A11 all hold.** No R2 exception. No merge, push, PR,
deploy, or flag change performed; the PR set is for the parent to
assemble at R1. No third issue found; backlog above is one-liners
only.
