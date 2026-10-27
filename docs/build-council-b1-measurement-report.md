# Build-Council Room B1 measurement report

**Status: MEASUREMENT ONLY (Phase B1, authorized 2026-10-26).**
No cap change is proposed as a decision here; the resource budget in
§5 is a proposal with its assumptions stated, and any cap value
change needs Joshua's separate authorization (B2). No model was
called, no meeting was run. Base commit: `5aa5d7a`.

## 1. Method

- Tokenizer: `tiktoken` 0.14.0, model `gpt-4o-mini` →
  encoding `o200k_base` (resolved via
  `tiktoken.encoding_for_model`, recorded in
  `local_ai/llm/tokenizer.py`). All token counts below are exact
  offline counts of strings the system already builds — no API
  call, no key, no generation.
- The chars/4 estimate (`meeting.estimate_tokens`) is NOT used
  anywhere below; §4 shows it overestimates the failed run by
  ~31%, which is why it must never derive a cap.
- Recorded runs are rebuilt from the meeting response artifacts
  (`claim_registry`, `unresolved_objections`,
  `delta_report.revision_chains`, work item + question). The
  packet carries work_item + question only: constraints, excerpts,
  and context are not preserved separately in the artifact, so
  the rebuilt mandatory state is 822 chars short of the recorded
  39,808 for the failed run (38,986 rebuilt). That gap is
  disclosed, not smoothed over; it does not change any
  conclusion (the run fails under either number).
- Synthesis telemetry for rebuilt runs uses the harness constants
  (phase `synthesis`, max 16, completed 15, allocated 1), which
  match a full meeting's synthesis slot. Telemetry text: 421
  chars. Instruction: 2,877 chars. Disclosure (none omitted):
  154 chars.

## 2. Measured prompt sizes (chars + exact tokens)

| Prompt | State chars | Assembled chars | Assembled tokens | Chars/token | Cap headroom |
|---|---|---|---|---|---|
| Fixture D (Phase A) | 4,380 | 4,803 | 1,001 | 4.80 | 35,197 |
| Fixture E (Phase A) | 3,953 | 4,376 | 901 | 4.86 | 35,624 |
| Fitting run 7eac64190430 | 34,866 | 35,289 | 6,705 | 5.26 | 4,711 |
| Failed run 64c36142794b | refused | refused | — | — | −2,446 |

- Fixture prompt hashes are unchanged from Phase A (D
  `fc12eb57…`, E `241d012b…`): the B1 gate change alters no
  prompt content, only whether an over-budget state is refused.
- Failed run, gate arithmetic (telemetry path): mandatory
  38,986 + instruction 2,877 + disclosure 154 + telemetry 421 +
  separators 8 = **42,446 total, excess 2,446** (6.1% over the
  40,000 cap). The previous gate reported 42,017 — it
  undercounted by exactly telemetry + joins (429 chars).
- Failed run, would-be full assembled prompt (built with a huge
  cap for measurement only): 42,770 chars / **8,187 tokens**
  (5.22 chars/token). The gate's minimal-state total (42,446)
  excludes optional content; the full assembled string is 324
  chars longer (the responded-to objection lines).
- Fitting run: 35,289 assembled chars / 6,705 tokens, headroom
  4,711 chars. It fits — and still failed in production for an
  unrelated reason (the quoted-ID failure Phase A later fixed).
  Fitting the cap is necessary, not sufficient.

## 3. Claim-text distribution (rebuilt registries)

| Run | Claims | Claim text chars | Mean | Median | Max | Top-5 total |
|---|---|---|---|---|---|---|
| Failed 64c36142794b | 68 | 36,350 | 534.6 | 474.5 | 1,345 (C37) | 5,722 (15.7%) |
| Fitting 7eac64190430 | 69 | 29,091 | 421.6 | 374 | 961 (C60) | — |

- Failed run by phase (claims / text chars): openings 27 /
  8,897; responses 26 / 16,769; revisions 15 / 10,684.
- Capacity pressure is driven by verbosity, not count: 68
  claims failed while 69 fit. The five longest claims (all
  Claude response/revision texts) carry 15.7% of all claim text.

## 4. Why chars/4 must never derive a cap

Failed-run would-be assembled prompt: chars/4 estimate 10,692
vs exact 8,187 tokens — the estimate overshoots by 2,505
tokens (~31%). A cap derived from chars/4 would be wrong in
the conservative direction (it would understate headroom), and
any token figure that is not an exact count must be labeled
an estimate, never a measurement.

## 5. Proposed resource budget (PROPOSAL ONLY — not a cap change)

- **Prompt-token ceiling (illustrative): 16,000 tokens.**
  Covers the failed run's 8,187 tokens at ~2× headroom, and the
  fitting run's 6,705 at ~2.4×. At the measured ~5.2
  chars/token, 16,000 tokens ≈ 83,000 chars — roughly double
  the current 40,000-char cap.
- **Output reservation: 16,000 tokens**, per the Phase B design
  §3 (observed synthesis outputs are a few thousand tokens, so
  16K is generous, not tight).
- **Total: ~32,000 tokens** before any safety margin — well
  within a 128K-token context window *if* that window figure is
  confirmed against OpenAI's own model page (today it rests on
  third-party references only and is NOT confirmed).
- **Assumptions:** encoding `o200k_base` for gpt-4o-mini;
  chars/token ratio ~5.2 measured on these prompts (it varies
  by text and must not be treated as a constant); the failed
  run is representative of realistic R2 meeting sizes.
- **Limitations (explicit):** context headroom does not prove
  synthesis quality at larger sizes — fidelity at 5k chars is
  already fragile (Phase A: position collapse, interpretive
  drift), and longer inputs may weaken it further; cost and
  latency at larger sizes are unmeasured; future meetings may
  exceed any fixed budget and must still refuse honestly.
- **What adoption requires (B2):** Joshua's separate decision
  weighing cost, latency, confirmed context headroom, and
  fidelity evidence from realistic synthesis fixtures. Until
  then the 40,000-char cap stands unchanged.

## 6. What B1 changed (code)

- `local_ai/llm/tokenizer.py` (new): exact offline counting,
  raises rather than falling back to chars/4 when tiktoken is
  missing. New dependency `tiktoken>=0.8.0` in
  `api/requirements.txt` (the repo's manifest; flagged here for
  review).
- `local_ai/build_room/meeting.py`: `build_synthesis_state`
  accepts `telemetry`; when passed, the gate compares the
  ASSEMBLED length (mandatory + optional + disclosure +
  instruction + separators + telemetry) and the diagnostic
  reports every component with `total == sum(components)` and
  `excess == total - cap`. Without telemetry, the previous
  #227 gate and arithmetic are preserved exactly. Production
  call sites (meeting synthesis phase, harness route) pass
  telemetry; the harness helper mirrors production. Cap value
  unchanged (40,000). No schema, contract, validator, phase,
  participant, generation-budget, packet, staged-synthesis, or
  instruction change.
- Tests: `tests/test_build_room_b1.py` (11 tests) +
  `tests/fixtures/b1_failed_run.json` +
  `tests/fixtures/b1_fitting_run.json` (rebuilt recorded-run
  registries). Serving-code evidence for this report: base
  commit `5aa5d7a`; fixture prompt hashes above (unchanged
  from Phase A).
- Resilience note: `count_tokens_exact` returns None (never a
  chars/4 estimate, never an exception) when tiktoken is
  unavailable, so production synthesis paths cannot fail for
  want of a measurement dependency. Direct measurement via
  `tokenizer.count_tokens` still raises loudly when tiktoken
  is missing, so a missing measurement is never silently
  replaced.
