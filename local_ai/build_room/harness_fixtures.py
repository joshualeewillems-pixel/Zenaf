"""Shared synthesis-harness fixtures (PR #227, unchanged).

Single source of truth for the bounded fixture states used by BOTH
the test-only harness (``tests/test_build_room_synthesis_harness.py``)
and the staging harness route (``api/routes/build_room_routes.py``,
``/build-room/harness/synthesis-call``). The route MUST construct
exactly these states — same claims, same packet, same unresolved
objections/chains, same telemetry — never a re-invented copy; a
route test asserts identity against these builders.

Fixture D (disagreements): C1/C2 carry the opposing positions,
C3 objects to C1 (unresolved objection), C4 is GPT's authorial
response (revision chain). Fixture E (legitimate empties): a small
state whose honest synthesis has no recommendations or limitations.

Telemetry inputs are fixed constants (phase ``"synthesis"``,
``max_generations`` 16, ``completed`` 15 mirroring a full meeting's
synthesis slot, ``allocated`` 1, ``reserved`` {}), so the assembled
prompt is reproducible. No credentials, no keys, no model calls here.
"""

from __future__ import annotations

import json
from pathlib import Path

from local_ai.build_room.meeting import Claim, ClaimRegistry, EvidencePacket

# Fixed, disclosed telemetry inputs. completed=15 mirrors a full
# meeting's synthesis slot (15 generations completed before synthesis).
TELEMETRY = {
    "phase": "synthesis",
    "max_generations": 16,
    "completed": 15,
    "allocated": 1,
    "reserved": {},
}

QUESTION = (
    "What would make the Build-Council Room fail to function as a "
    "genuine deliberative council?"
)


def fixture_d_state():
    """Fixture D: opposing claims + unresolved objection + response chain."""
    reg = ClaimRegistry()
    reg.register("GPT", "opening",
                 "1. Observed: Assigned roles improve accountability.")
    reg.register("Muse", "opening",
                 "1. Observed: Open roles permit more substantive deliberation.")
    reg.register("Gemini", "response",
                 "1. Inferred: In response to C1, assigned roles risk "
                 "entrenching the convener's framing.")
    reg.register("GPT", "revision",
                 "1. Inferred: Assigned roles improve accountability when "
                 "the role description is itself revisable by the council.")
    packet = EvidencePacket(
        work_item="Harness fixture D",
        question=QUESTION,
        constraints=("The room deliberates and recommends only.",
                     "Roles and jurisdictions are NOT assigned."),
    )
    unresolved = [{"claim_id": "C1", "cited_by": "Gemini",
                   "source_claim_id": "C3", "moves": ["objection"],
                   "state": "unresolved", "responded_by": None}]
    chains = [{"original_claim_id": "C1", "challenge_claim_id": "C3",
               "challenge_move": "objection", "challenger": "Gemini",
               "revision_claim_id": "C4", "revision_relationship": "unstated",
               "author": "GPT"}]
    return packet, reg, unresolved, chains


def fixture_e_state():
    """Fixture E: small state, honestly no recommendations/limitations."""
    reg = ClaimRegistry()
    reg.register("GPT", "opening",
                 "1. Observed: The council recommends only; Joshua decides.")
    reg.register("Muse", "opening",
                 "1. Inferred: Open roles permit more substantive deliberation.")
    packet = EvidencePacket(work_item="Harness fixture E", question=QUESTION)
    return packet, reg, [], []


# ---------------------------------------------------------------------------
# B2 replay fixtures (PR: build-room-b2). Byte-identical copies of the
# B1 recorded-run artifacts, shipped as package data so the staging
# route can load them (tests/ is not deployed). A test pins the
# packaged copies identical to tests/fixtures/b1_*.json.
#
# Provenance (same disclosed gap as B1): rebuilt from meeting
# response artifacts — claims, unresolved objections, revision
# chains, work item + question. Constraints, excerpts, and context
# are not preserved separately in the artifact, so the packet
# carries work item + question only; the resulting rebuilt-vs-
# recorded gap is disclosed, not smoothed over.
# ---------------------------------------------------------------------------

_RECORDED_DIR = Path(__file__).resolve().parent


def _load_recorded(name: str):
    data = json.loads((_RECORDED_DIR / name).read_text())
    reg = ClaimRegistry()
    for c in data["claims"]:
        reg.claims.append(Claim(
            id=c["id"], participant=c["participant"], phase=c["phase"],
            text=c["text"], status=c["status"],
            disposition=c["disposition"],
            disposition_by=c["disposition_by"]))
    packet = EvidencePacket(work_item=data["work_item"],
                            question=data["question"])
    return packet, reg, data["unresolved_objections"], data["revision_chains"]


def fixture_fitting_state():
    """Fitting-run replay: meeting 7eac64190430, 69 claims, 6,705 tokens."""
    return _load_recorded("recorded_fitting_run.json")


def fixture_failed_state():
    """Failed-run replay: meeting 64c36142794b, 68 claims, 8,187 tokens."""
    return _load_recorded("recorded_failed_run.json")


# ---------------------------------------------------------------------------
# B2 upper-range stress fixture (proposal Section 3.4, Tier 2(c)).
#
# A deterministic, full-evidence deliberation targeting ~11,500–
# 12,500 assembled tokens: five seats, opening/response/revision
# phases, competing positions, unresolved objections, and revision
# chains. Size comes from the number of distinct claims, never
# from repeated filler: every claim body is unique, every seat
# speaks from its own angle, and the construction-property test
# asserts uniqueness, five-seat presence, objection and chain
# presence, and the token band. The topic is the cap question
# itself, so the deliberation is genuine council business, not
# padded text. Registration order is fixed, so claim IDs are
# deterministic; objections and chains are built from the
# registered IDs, never hand-numbered.
# ---------------------------------------------------------------------------

_STRESS_WORK_ITEM = "B2 capacity verification — upper-range stress deliberation"
_STRESS_QUESTION = (
    "Should the Build-Council Room adopt a token-denominated synthesis "
    "cap, and if so at what value?"
)
_STRESS_CONSTRAINTS = (
    "The room deliberates and recommends only; Joshua decides.",
    "No silent truncation, no repair layer, no schema change.",
)

# (participant, phase, claim text). Openings first, in stable seat
# order; responses and revisions follow in later lists.
_STRESS_OPENINGS = [
    ("GPT", "opening",
     "1. Observed: The failed run's would-be prompt measured 42,770 "
     "characters and 8,187 tokens under o200k_base, while the fitting "
     "run measured 35,289 characters and 6,705 tokens, so the observed "
     "inter-run variation is about twenty-two percent in tokens and "
     "the failed run exceeded the forty-thousand-character cap by "
     "about six percent on rebuilt numbers. The rebuilt figures carry "
     "a disclosed gap of about eight hundred twenty-two characters "
     "against the recorded scale, because constraints and excerpts "
     "are not preserved separately in the meeting artifact, so the "
     "rebuilt numbers are trustworthy only within that disclosed "
     "bound and any adoption report must state the gap rather than "
     "presenting rebuilt totals as if they were recorded ones."),
    ("GPT", "opening",
     "1. Inferred: A cap of twelve thousand five hundred tokens covers "
     "the worst observed meeting with fifty percent headroom, covers a "
     "hundred-claim meeting at the worst observed verbosity, and "
     "refuses only compounded worst cases, which makes it the smallest "
     "value that does all three rather than a round number chosen for "
     "tidiness. A ten-thousand-token cap would cover the failed run "
     "but leave only about twenty percent headroom, less than the "
     "observed inter-run variation plus one growth step, and would "
     "predictably refuse the next large meeting and repeat this "
     "cycle, while a sixteen-thousand-token cap buys stress capacity "
     "at no measured benefit since cost is negligible and the binding "
     "risk at larger sizes is fidelity rather than tokens."),
    ("GPT", "opening",
     "1. Observed: The chars-per-token ratio varied from 4.80 to 5.26 "
     "across real prompts in the record, so a character gate would "
     "mis-gate by up to about nine percent in either direction, while "
     "an exact token gate counts the unit the provider actually bills "
     "and the model actually consumes. At the lowest observed ratio "
     "the same twelve thousand five hundred tokens is about sixty "
     "thousand characters, and at the highest it is about sixty-five "
     "thousand, so any character equivalent stated for intuition can "
     "mislead a log reader by thousands of characters, which is why "
     "the proposal states the equivalent for readability only and "
     "never lets it govern an admit or refuse decision."),
    ("GPT", "opening",
     "1. Inferred: The one-point-five headroom factor is a disclosed "
     "policy judgment, not a derived optimum, and the measurements "
     "establish only the lower bound required by observed meetings, "
     "so the near-cap fidelity test is evidence for the chosen margin "
     "rather than proof that the margin is optimal. If a realistic "
     "meeting later exceeds the cap, the honest response is a staged-"
     "synthesis design review under the fork, not a quiet re-"
     "derivation of a larger factor, and the adoption report must "
     "carry the judgment label with it so no future reader mistakes "
     "the factor for a measurement."),
    ("GPT", "opening",
     "1. Observed: The synthesis instruction measured 2,877 characters "
     "and 601 tokens exactly, telemetry measured 421 characters, and "
     "the largest observed synthesis output measured 1,390 tokens, "
     "which sizes the output reservation at four thousand tokens as "
     "roughly two-point-nine times the largest observed output. The "
     "reservation is a budget line rather than a request for four "
     "thousand output tokens, so if the true maximum output were "
     "smaller than the reservation, verification would surface the "
     "shortfall as truncation instead of silently succeeding, and "
     "that visibility is part of why the reservation is sized from "
     "observed outputs rather than from any maximum."),
    ("GPT", "opening",
     "1. Inferred: Total budget arithmetic of twelve thousand five "
     "hundred prompt tokens plus a four-thousand-token output "
     "reservation gives sixteen thousand five hundred tokens, which "
     "needs only a context window comfortably above twenty thousand "
     "tokens with margin and therefore does not depend on any "
     "unconfirmed hundred-and-twenty-eight-thousand figure. The "
     "derivation spends no unconfirmed number anywhere, so the "
     "proposal survives any context window comfortably above the "
     "total, and only a window proven below about twenty thousand "
     "tokens with margin would force a re-derivation of the total "
     "budget."),
    ("GPT", "opening",
     "1. Observed: Claim text was ninety-three percent of the "
     "mandatory state in the failed run, with sixty-eight claims "
     "averaging about five hundred thirty-five characters, a median "
     "near four hundred seventy-five, a maximum near one thousand "
     "three hundred forty-five, and the top five claims contributing "
     "about sixteen percent of claim text. That concentration means "
     "a few long claims drive a large share of prompt size, so any "
     "future proposal to cap individual claims would be a different "
     "policy from the synthesis cap, touching contribution budgets "
     "that this proposal explicitly leaves unchanged."),
    ("GPT", "opening",
     "1. Inferred: Because claim text dominates the prompt, any "
     "capacity plan that removes claim text to fit a smaller budget "
     "changes which deliberation the synthesizer sees, while a plan "
     "that keeps every claim in full preserves the deliberation and "
     "moves the boundary instead of editing the evidence. The "
     "proposal chooses evidence over budget in that trade, which is "
     "why the cap moves to twelve thousand five hundred rather than "
     "the prompt shrinking to forty thousand characters, and why a "
     "future over-cap meeting refuses honestly instead of arriving "
     "at a synthesis built from a subset nobody chose."),
    ("Claude", "opening",
     "1. Observed: Phase A fixture D showed a synthesizer collapsing "
     "two opposing positions into a single statement, and fixture E "
     "showed a structural fact about decision authority upgraded "
     "into an evaluative conclusion about limited decision-making, "
     "so both failure modes are already in the record at small scale. "
     "Small-scale failures matter more rather than less for the "
     "adoption decision, because they name the exact modes to watch "
     "for at realistic scale, and collapse and drift are different "
     "defects: collapse erases a disagreement, while drift invents "
     "a conclusion, and each needs its own check."),
    ("Claude", "opening",
     "1. Inferred: Fidelity criteria must hold independently on every "
     "verification call, because treating Phase A as a permissible "
     "error rate would bless the very collapse and drift it "
     "demonstrated, and a single generation per fixture can reveal a "
     "defect or demonstrate a capability but never establish a "
     "reliable error rate. A single successful generation is an "
     "existence proof that the model can do it once, not evidence "
     "that it will do it reliably, and the adoption decision must "
     "carry that limit openly rather than rounding bounded evidence "
     "into statistical confidence."),
    ("Claude", "opening",
     "1. Inferred: A validator correctly reporting an unparseable "
     "field proves detection, not success, so cap adoption must "
     "require all four structured fields to carry valid evaluations, "
     "complete or legitimately empty, with any unparseable field "
     "failing full-artifact acceptance outright. Honest failure "
     "reporting remains valuable as reporting, since a disclosed "
     "failure can be investigated while a hidden one cannot, but "
     "its value is diagnostic rather than adoptive, and no adoption "
     "criterion may be satisfied by the quality of a failure notice."),
    ("Claude", "opening",
     "1. Observed: The disagreement field in Phase A fixture D "
     "validated only after the enum example was added, and the "
     "recommendations and limitations fields validated only after "
     "empty collections gained their own synthesized-empty meaning, "
     "which shows format compliance improving without any change in "
     "the underlying deliberation. That history cautions against "
     "mistaking contract compliance for fidelity, since each format "
     "fix made the output parse while leaving open whether the "
     "parsed content faithfully represented the deliberation, and "
     "the review judgments exist precisely to ask the second "
     "question after the validator answers the first."),
    ("Claude", "opening",
     "1. Inferred: Recommendations must carry supporting claim IDs "
     "or be labeled proposals, because an unevidenced compromise "
     "presented as a conclusion borrows the authority of the "
     "deliberation without doing the work of grounding in it, and "
     "the validator's rejection of such an entry is necessary but "
     "not sufficient evidence about what the model will propose. "
     "The mechanical layer enforces the IDs while the review layer "
     "reads whether the cited claims actually support the "
     "recommendation, and neither layer alone can carry the "
     "fidelity judgment."),
    ("Claude", "opening",
     "1. Inferred: Positions must remain distinct unless the "
     "registry shows agreement through a revision relationship, "
     "because merging positions in prose is the easiest way for a "
     "synthesis to manufacture consensus, and manufactured consensus "
     "is worse than an honestly reported disagreement. A reader who "
     "never sees the registry cannot recover a merged disagreement "
     "from the smoothed version, so the synthesis owes its reader "
     "the disagreement in the same shape the registry holds it, "
     "distinct positions with their supporting claims attached."),
    ("Claude", "opening",
     "1. Observed: Every unresolved objection in the registry must "
     "appear in the output's disagreements or be disclosed as "
     "missing, since a dropped objection is not a resolved "
     "objection, and silence about a live challenge misrepresents "
     "the state of the deliberation to whoever reads the synthesis. "
     "Disclosure as missing is the honest fallback when an output "
     "omits an objection, but it is a fallback rather than a pass, "
     "because the synthesis still failed to carry the objection "
     "even though the failure was reported."),
    ("Claude", "opening",
     "1. Inferred: Empty limitations must reflect the record rather "
     "than the model's convenience, so known omissions such as "
     "unaddressed claims must appear as limitations instead of "
     "vanishing, and an empty field must never be read as proof "
     "that nothing is missing. When review finds a known omission "
     "that the output left out, the correct response is a limitation "
     "entry naming it, not an excuse for leaving the field empty, "
     "since the field's emptiness is a claim about the record that "
     "review can check."),
    ("Gemini", "opening",
     "1. Observed: No latency numbers exist in the record for "
     "synthesis generations, and the one-hundred-twenty-second "
     "timeout is unchanged by the proposal, so any claim about how "
     "larger prompts affect generation time is currently a "
     "prediction awaiting Tier 2 measurement, not a fact. Past "
     "generations completed within the timeout at prompts up to six "
     "thousand seven hundred five tokens, but no timing was "
     "recorded, so no latency curve can be drawn from the record "
     "and no threshold can be defended from it until Tier 2 "
     "records wall-clock time per call."),
    ("Gemini", "opening",
     "1. Inferred: A generation approaching the timeout should be "
     "treated as design-review evidence for smaller per-call "
     "prompts, never as authorization to raise the timeout, because "
     "raising the timeout would buy waiting time without addressing "
     "whatever makes the larger prompt slow or fragile. The "
     "adoption criterion gives that judgment a rule, requiring "
     "margin of at least twenty percent below the timeout, so a "
     "call completing barely inside the limit is recorded as a risk "
     "even when it technically passes."),
    ("Gemini", "opening",
     "1. Observed: Cap-worst synthesis cost is estimated under half "
     "a cent per call at third-party rates, and a year of weekly "
     "cap-worst syntheses would cost under a dollar, so cost is not "
     "a binding constraint on the cap value and must not be used to "
     "argue the cap down. A future argument that the cap must stay "
     "small for cost would need measured costs an order of magnitude "
     "above these estimates, since the estimates themselves leave "
     "so much room that only a large surprise could change the "
     "conclusion."),
    ("Gemini", "opening",
     "1. Inferred: The five-cent tripwire is useful precisely "
     "because it is a pre-agreed review trigger rather than an "
     "automatic decision, since a cost surprise deserves "
     "investigation before it rearranges the architecture, and an "
     "automatic trigger would let a pricing change design the "
     "system by itself. The tripwire value sits at ten times the "
     "cap-worst estimate, so it fires only on a genuine surprise, "
     "and the trigger value itself remains reviewable rather than "
     "being treated as a law of nature."),
    ("Gemini", "opening",
     "1. Observed: Pricing figures for the synthesis model were not "
     "confirmed from the provider's official pages in the proposal's "
     "check, which rendered the newer model family instead, so all "
     "cost figures in the proposal are labeled estimates and none "
     "of them enters the cap derivation. Third-party sources agree "
     "on the rates used, and one claims to have read the provider's "
     "pages earlier, but a figure that cannot be read from the "
     "official page in the check cannot be cited as confirmed from "
     "it, and the proposal is built to stand without that "
     "confirmation."),
    ("Gemini", "opening",
     "1. Inferred: The output reservation is a budget line, not a "
     "request for four thousand output tokens, so if the true "
     "maximum output were smaller, verification would surface it "
     "as truncation rather than silently succeeding, and that "
     "visibility is part of why the reservation is sized from "
     "observed outputs instead of a maximum. Tier 2 records output "
     "completeness for exactly this reason, since a synthesis cut "
     "short by an output limit would otherwise look like a complete "
     "synthesis with short fields."),
    ("Gemini", "opening",
     "1. Observed: Sixteen generations precede synthesis in a full "
     "meeting, and the cap governs one synthesis call only, so the "
     "total meeting cost and the per-participant metering are "
     "unchanged by this proposal and must not be confused with the "
     "synthesis budget when the adoption decision is judged. A "
     "meeting's cost is dominated by deliberation rather than by "
     "the single synthesis call, so shrinking the synthesis cap to "
     "save money would save the smallest share while risking the "
     "artifact the whole meeting exists to produce."),
    ("Gemini", "opening",
     "1. Inferred: Wall-clock time per Tier 2 call must be recorded "
     "alongside tokens, because latency margin is an adoption "
     "criterion with a stated threshold, and a generation that "
     "completes barely inside the timeout is a different risk from "
     "one that completes with room to spare. The report must carry "
     "the margin per call rather than a pass or fail alone, since "
     "the adoption decision needs to see how close to the boundary "
     "each call ran."),
    ("Grok", "opening",
     "1. Inferred: An honest refusal is a better outcome than a "
     "quietly edited synthesis, because a refusal names the "
     "boundary and preserves the evidence for the next decision, "
     "while truncation pretends the deliberation fit when it did "
     "not and leaves the reader unable to tell what was lost. A "
     "refused synthesis still owes its reader the component "
     "diagnostic and the complete transcript, so the meeting "
     "produces numbers and evidence even when it cannot produce a "
     "synthesis, and that partial product is more honest than a "
     "complete-looking artifact built from a subset."),
    ("Grok", "opening",
     "1. Observed: The gate's minimal-state branch deliberately "
     "excludes optional content and answers whether the prompt fits "
     "even with nothing optional, which is why its total of forty-"
     "two thousand four hundred forty-six differs from the would-be "
     "full prompt of forty-two thousand seven hundred seventy by "
     "exactly the three-hundred-twenty-four optional characters. "
     "Each figure is correct on its own basis, and the reconciliation "
     "names the basis for each, so the apparent contradiction "
     "dissolves without changing any number and the exact-"
     "accounting claim now holds for both figures."),
    ("Grok", "opening",
     "1. Inferred: Optional-content eviction must follow a fixed "
     "deterministic order, superseded texts first and then "
     "responded-to details, with links and counts retained, because "
     "any eviction order chosen by judgment in the moment would be "
     "an unrecorded editorial decision about what matters. The "
     "disclosure must name what was omitted in numbers, so a reader "
     "can see that history was set aside rather than erased, and "
     "the full records remain available in the transcript for "
     "anyone who needs them."),
    ("Grok", "opening",
     "1. Inferred: Mandatory state must never be silently removed, "
     "so if mandatory content alone exceeds the cap, synthesis "
     "reports incomplete rather than dropping a claim, an objection, "
     "or a chain to manufacture a fit, and the complete transcript "
     "remains preserved regardless of the synthesis outcome. The "
     "incomplete status is itself informative, since it tells the "
     "reader that the deliberation outgrew the budget instead of "
     "letting a partial synthesis pretend otherwise."),
    ("Grok", "opening",
     "1. Observed: The production meeting path still enforces the "
     "forty-thousand-character gate, and the candidate token cap "
     "governs only the controlled-verification path, so until "
     "adoption no production meeting changes its behavior and no "
     "legacy gate silently survives alongside the candidate gate on "
     "either path. Adoption would switch production to the token "
     "gate in one reviewed change, and until that change the "
     "character gate remains the only production gate, which is "
     "exactly what the split authorization shape requires."),
    ("Grok", "opening",
     "1. Inferred: Two coexisting synthesis gates would produce "
     "inconsistent admit and refuse results, which is why migration "
     "means replacement rather than supplementation, and why the "
     "verification path suspends the character gate openly instead "
     "of letting both gates run and hoping they agree. An open "
     "suspension can be reviewed and reasoned about, while a silent "
     "coexistence would force someone to decide which refusal counts "
     "without any record of that decision."),
    ("Grok", "opening",
     "1. Inferred: A cap whose top third was never tested cannot be "
     "adopted on tests that never went there, so the stress fixture "
     "must exercise the eleven-thousand-five-hundred to twelve-"
     "thousand-five-hundred band itself rather than extrapolating "
     "from smaller prompts that happened to succeed. The new "
     "adoption criterion exists for exactly this reason, requiring "
     "upper-range evidence with the other criteria holding on it, "
     "so sub-capacity success alone can never carry the adoption "
     "decision."),
    ("Grok", "opening",
     "1. Observed: The largest prompt ever actually sent to the "
     "synthesizer measured six thousand seven hundred five tokens, "
     "so every claim about behavior above that size, including the "
     "whole headroom band, is a prediction to be tested rather "
     "than an established fact the adoption decision can assume. "
     "The failed run's eight thousand three hundred fifty tokens "
     "were gate-refused and never sent, so the untested band "
     "stretches from the fitting run all the way to the proposed "
     "cap, and the verification plan must cover it rather than "
     "assume it."),
    ("Muse", "opening",
     "1. Inferred: The contestation graph measures interaction, not "
     "importance, so a packet that keeps only contested claims in "
     "full would reward claims for being argued about and hide "
     "unchallenged strong claims, novel proposals, implicit "
     "limitations, corrections, and overlooked arguments. Each of "
     "those hidden kinds can carry the deliberation's most "
     "consequential content, and a packet that hides them because "
     "nobody challenged them would present a council that argued "
     "only about what it argued about, which is circular."),
    ("Muse", "opening",
     "1. Observed: Removing about sixty-five percent of the prompt "
     "to fix an eight-percent overage redefines which deliberation "
     "deserves to be seen, which is why the bounded packet was set "
     "aside as a production synthesis even though it remains "
     "available as an explicitly labeled contestation-focused "
     "summary artifact under a separate decision. The proportion "
     "itself is the argument, since a remedy wildly larger than the "
     "problem it cures is usually treating a different problem, and "
     "here the different problem would be deciding whose claims "
     "count."),
    ("Muse", "opening",
     "1. Inferred: Staged synthesis, if it ever becomes the "
     "fallback, must put every active claim in full in at least one "
     "partition with objections and revision chains traveling with "
     "their claims, because that full-coverage requirement is what "
     "distinguishes staging from the rejected packet. Repeating "
     "evidence between partitions is acceptable and expected, since "
     "a chain that loses its objection when split has lost the "
     "deliberation it was meant to preserve."),
    ("Muse", "opening",
     "1. Observed: The deliberation's provenance lives in claim IDs, "
     "participant names, and statuses, and intermediate staged "
     "outputs would need to retain that provenance so the "
     "aggregation step could be checked rather than trusted, with "
     "its own fixture tier for cluster outputs and merge output. "
     "An aggregation that cannot be checked against the registry "
     "is a new author rather than a synthesis, and the staged "
     "fallback must therefore validate the merge for collapse, "
     "disagreement loss, and unsupported recommendations "
     "separately."),
    ("Muse", "opening",
     "1. Inferred: A failed capacity or fidelity test cannot itself "
     "authorize a new architecture, so the fork must run trigger, "
     "then investigation, then design approval, then implementation "
     "authorization, with each step needing its own word, or the "
     "fallback will be built by momentum instead of by decision. "
     "The sequence protects the decision from the urgency that "
     "follows a failure, since urgency is when an architecture gets "
     "chosen by default rather than by verdict."),
    ("Muse", "opening",
     "1. Inferred: The candidate cap and the adopted production cap "
     "must stay distinct throughout verification, because confusing "
     "a cap under test with a cap in force would let test results "
     "quietly become production policy without the adoption "
     "decision ever being taken. Every verification report must "
     "therefore label which cap it exercised, and the production "
     "path must show no trace of the candidate until adoption "
     "switches it in a reviewed change."),
    ("Muse", "opening",
     "1. Observed: Serving-code evidence, prompt hash plus deployed "
     "commit ID, is a standing rule for every verification report, "
     "because a result that cannot be tied to the code that "
     "produced it cannot be trusted, repeated, or audited. The "
     "hash ties the result to the exact prompt and the commit ID "
     "ties it to the exact code, so a later reader can reproduce "
     "both or discover that they cannot, and either outcome is "
     "informative."),
    ("Muse", "opening",
     "1. Inferred: The room deliberates and recommends only, and "
     "Joshua decides, so every artifact this process produces is a "
     "recommendation awaiting a verdict rather than an action taken, "
     "and any synthesis that presents itself as a decision has "
     "already misrepresented its authority. The recommend-only "
     "framing is what makes the council safe to argue in, since a "
     "seat that cannot authorize anything cannot smuggle a decision "
     "past the human verdict that alone can take it."),
]
# (Keep the zero-contestation builder after the stress constants;
# it is defined here so the stress lists below read in order.)


def fixture_zero_contestation_state():
    """Zero-contestation assembly (Tier 1 ONLY — no generation).

    A small deliberation with claims but no objections and no
    revision chains: full-state synthesis with honest refusal is
    the correct behavior, and it is verified deterministically
    (assembly + hash), never by spending a generation. This
    builder is deliberately NOT in the route's fixture map: the
    route must refuse it with 422.
    """
    reg = ClaimRegistry()
    reg.register("GPT", "opening",
                 "1. Observed: The council recommends only; Joshua decides.")
    reg.register("Claude", "opening",
                 "1. Observed: A recommendation is not an authorization.")
    reg.register("Gemini", "opening",
                 "1. Inferred: When no objection is raised, the record "
                 "shows agreement by absence of challenge, not proof "
                 "of correctness.")
    reg.register("Grok", "opening",
                 "1. Inferred: Silence in the record must not be read as "
                 "endorsement of every claim detail.")
    reg.register("Muse", "opening",
                 "1. Observed: Each seat speaks from its own jurisdiction "
                 "and may honestly say a matter is outside its watch.")
    reg.register("GPT", "response",
                 "1. Inferred: With no contested claim, synthesis should "
                 "report positions and note the absence of disagreement "
                 "rather than manufacturing a tension.")
    packet = EvidencePacket(
        work_item="Harness fixture zero-contestation",
        question=QUESTION,
        constraints=("The room deliberates and recommends only.",))
    return packet, reg, [], []


_STRESS_RESPONSES = [
    # Each entry: (participant, text). Objections and supports cite
    # openings by position; the builder wires IDs from registration.
    ("Claude",
     "1. Inferred: In response to C2, the claim that twelve thousand "
     "five hundred is the smallest value doing all three depends on "
     "the growth model whose multipliers are judgment, since a "
     "hundred-claim meeting at plus-twenty-five-percent verbosity "
     "already refuses, so the boundary between realistic and stress "
     "is itself a judgment call rather than a measured line. The "
     "model also omits claim-length drift within a meeting, since "
     "late claims often run longer as positions complicate, so the "
     "safeguard for the boundary cannot be the model itself but "
     "must be the review trigger that fires when a realistic "
     "meeting first exceeds the cap."),
    ("Gemini",
     "1. Inferred: In support of C3, counting the unit the provider "
     "bills removes a conversion error that a character gate cannot "
     "avoid, because the provider never charges by characters and "
     "any character proxy must guess a ratio that real prompts "
     "demonstrably violate. The mis-gating cuts both ways, since "
     "over-admission risks a downstream truncation while over-"
     "refusal blocks a valid meeting, so removing the guess removes "
     "both failure directions at once rather than trading one for "
     "the other."),
    ("Grok",
     "1. Inferred: In response to C4, calling the headroom factor a "
     "disclosed policy judgment does not answer whether one-point-"
     "five is the right judgment, since a disclosed guess is still a "
     "guess, and adoption would entrench that guess until a future "
     "meeting proves it wrong by refusing. Evidence that could "
     "justify the factor would be a second pair of meetings "
     "bracketing it from above and below, and until such evidence "
     "exists the adoption report must carry the judgment label "
     "rather than letting the number harden into a measurement."),
    ("Muse",
     "1. Inferred: In support of C10, independent criteria protect "
     "the adoption decision from the sunk-cost pull of earlier "
     "results, because a comparison baseline lets each new test "
     "inherit the defects of the last one instead of being judged "
     "on its own output. Baselines also hide drift over time, since "
     "each round that passes against a degraded predecessor lowers "
     "the bar for the next round, so independence acts as a ratchet "
     "that holds every call to the same criteria."),
    ("GPT",
     "1. Inferred: In response to C33, interaction density sometimes "
     "tracks importance rather than merely measuring it, since the "
     "claims a council argues about most are often the load-bearing "
     "ones, so dismissing the contestation graph entirely may hide "
     "a real signal along with the false one. The signal still "
     "needs the same scrutiny as the dismissal, because challenged "
     "claims also attract strategic objections that inflate their "
     "interaction count without adding substance, so neither the "
     "graph nor its rejection can be trusted without reading the "
     "challenges themselves."),
    ("Claude",
     "1. Inferred: In response to C25, an honest refusal still leaves "
     "the meeting with no synthesis at all, so honesty about the "
     "boundary, while necessary, does not by itself produce an "
     "artifact, and the council must decide what a refused meeting "
     "owes its reader beyond the refusal notice. The minimum owed "
     "is the component diagnostic plus a pointer to the complete "
     "transcript, since numbers without evidence cannot be checked "
     "and evidence without numbers cannot be understood, and the "
     "refusal notice should carry both rather than one alone."),
    ("Gemini",
     "1. Inferred: In response to C31, a synthetic stress fixture "
     "exercises token size but not real deliberation dynamics, "
     "since constructed claims lack the surprises, corrections, and "
     "uneven verbosity of a live meeting, so passing at the top of "
     "the band is weaker evidence than a real meeting landing there. "
     "The fixture still tests two things genuinely, the gate "
     "arithmetic and the validator at size, so its evidence is "
     "partial rather than empty, and the adoption report must name "
     "both halves instead of presenting the fixture as a stand-in "
     "for a real meeting."),
    ("Muse",
     "1. Inferred: In response to C19, judging cost per synthesis "
     "hides the program-level picture, because a council that meets "
     "daily with sixteen generations per meeting spends mostly on "
     "deliberation rather than synthesis, and the synthesis share "
     "being small does not make the total small. Cadence changes "
     "the conclusion, since weekly meetings make synthesis cost "
     "negligible while daily meetings make deliberation cost the "
     "figure that matters, so any cost claim must state its cadence "
     "assumption alongside its per-call number."),
    ("GPT",
     "1. Inferred: In support of C9, cataloguing known failure modes "
     "is more useful than averaging over them, because a named mode "
     "such as collapse can be watched for in every new output, "
     "while an error rate computed from one generation per fixture "
     "pretends to a precision the sample cannot support. The "
     "catalog also enables targeted regression tests, since each "
     "named mode can gain a fixture designed to provoke it, while "
     "a rate gives no such handle for future testing."),
    ("Claude",
     "1. Inferred: In response to C8, keeping every claim in full "
     "also keeps low-value claims that dilute synthesis attention, "
     "so full evidence preserves the deliberation but does not "
     "guarantee the synthesizer weighs it well, and prominence "
     "without deletion may be the missing middle step. Any ranking "
     "used for prominence must itself be disclosed, including who "
     "ranked and by what rule, or the ranking becomes silent "
     "editing by another name, and the reader cannot tell guidance "
     "apart from omission."),
    ("Grok",
     "1. Inferred: In response to C13, supporting claim IDs can be "
     "gamed by citing tangentially related claims, so an ID list "
     "proves a citation exists rather than proving the reasoning "
     "follows, and the validator cannot distinguish a genuine link "
     "from a decorative one. Decorative citations also pollute "
     "provenance, since future readers who trust cited links will "
     "follow them into reasoning that never actually happened, so "
     "the review layer must read the link rather than count it."),
    ("Muse",
     "1. Inferred: In response to C18, design review is slow, and a "
     "timeout fix might be a configuration change rather than an "
     "architecture, so routing every timeout signal through a full "
     "review could delay a trivial fix while the council waits for "
     "permission to change a number. Review-first still needs a "
     "fast path for genuinely trivial fixes, or review becomes the "
     "bottleneck it warns about, and the fast path itself needs a "
     "rule for what counts as trivial rather than a feeling."),
    ("GPT",
     "1. Inferred: In response to C36, retaining provenance across "
     "partitions multiplies storage and checking cost, since every "
     "claim carried into multiple partitions carries its IDs, "
     "status, and relationships with it, and the checking burden "
     "grows with each partition rather than staying flat. Compact "
     "references bound that growth, since IDs with participant and "
     "status travel cheaply while full text stays in the registry, "
     "and the checker follows references instead of re-reading "
     "duplicated evidence."),
    ("Claude",
     "1. Inferred: In response to C29, verifying a token gate that "
     "production does not yet use leaves a gap between test and "
     "deployment, because the verification proves the gate logic "
     "while production meetings continue under the character gate, "
     "and the two are only reconciled if adoption actually happens. "
     "The reconciling step must itself be reviewed, since the "
     "adoption change gets its own proposal, its own diff, and its "
     "own deploy confirmation, rather than riding along inside the "
     "verification results as if testing implied switching."),
    ("Gemini",
     "1. Inferred: In response to C38, keeping candidate and adopted "
     "caps distinct risks two truths in the room, since readers may "
     "treat candidate results as production guarantees unless every "
     "report labels which cap it exercised, and labels are easy to "
     "drop when results are quoted. The label must therefore travel "
     "with excerpts as well as with full reports, so a quoted "
     "result carries its status with it and cannot silently harden "
     "into a production guarantee in a later document."),
    ("Grok",
     "1. Inferred: In support of C26, the reconciliation of the "
     "three-hundred-twenty-four characters shows why component "
     "accounting matters, because two totals that look contradictory "
     "turned out to measure different things, and naming each "
     "figure's basis dissolved the apparent error without changing "
     "any number. Basis-naming should be a general rule rather than "
     "a one-time fix, since every figure in a verification report "
     "carries a basis that a reader needs in order to trust it, and "
     "an unnamed basis invites exactly the confusion the "
     "reconciliation resolved."),
    ("Muse",
     "1. Inferred: In support of C14, distinct positions are the "
     "unit of deliberation, so a synthesis that merges them has "
     "not summarized the council but replaced it with a smoother "
     "council that never met, and the reader cannot recover the "
     "disagreement from the smoothed version. The registry remains "
     "the ground truth a reader can check, but only if the reader "
     "knows to check it, so the synthesis owes its reader the "
     "disagreement in the same shape the registry holds it rather "
     "than a note saying disagreements exist somewhere."),
    ("GPT",
     "1. Inferred: In support of C21, labeling cost figures as "
     "estimates is the honest move when the provider's pages render "
     "a newer model family, because citing an unread figure as "
     "confirmed would launder a third-party consensus into an "
     "official quote it never was. Third-party agreement across "
     "multiple sources is genuinely reassuring, but reassurance is "
     "not confirmation, and the proposal's labeling preserves that "
     "distinction instead of collapsing it for tidiness."),
    ("Claude",
     "1. Inferred: In support of C30, replacement rather than "
     "supplementation is the only coherent migration shape, since "
     "two gates that disagree force someone to decide which refusal "
     "counts, and that decision would itself be an undocumented "
     "policy hiding inside the implementation. An open suspension "
     "on the verification path can be reviewed and reasoned about, "
     "while a silent coexistence would hide the arbiter problem "
     "until the day the gates disagree on a real meeting."),
    ("Gemini",
     "1. Inferred: In support of C24, recording wall-clock time "
     "alongside tokens turns latency from a worry into a "
     "measurement, and the ninety-six-second margin threshold gives "
     "that measurement a decision rule instead of leaving it as an "
     "impression about whether a call felt slow. The report must "
     "carry the margin per call rather than a pass or fail alone, "
     "since the adoption decision needs to see how close to the "
     "boundary each call ran."),
    ("Grok",
     "1. Inferred: In support of C40, recommend-only authority is "
     "what makes the council safe to argue in, because a seat that "
     "cannot authorize anything cannot smuggle a decision past the "
     "human verdict, and the synthesis inherits that safety only if "
     "it preserves the recommend-only framing. A synthesis that "
     "presents itself as a decision has already misrepresented its "
     "authority, even if its content is sound, since the framing "
     "is part of the content for any reader deciding what to do."),
    ("Muse",
     "1. Inferred: In support of C5, measuring the instruction and "
     "the outputs directly is what lets the reservation be sized "
     "from observation instead of from a maximum, and sizing from "
     "observation is why the four-thousand-token reservation is a "
     "budget line rather than a wish. A maximum-based reservation "
     "would have claimed sixteen thousand tokens of headroom nobody "
     "observed, while the observed-output basis keeps the budget "
     "honest about what syntheses actually cost."),
    ("GPT",
     "1. Inferred: In support of C17, admitting that no latency "
     "numbers exist is stronger than estimating a curve from no "
     "data, because an admitted gap invites measurement while a "
     "fabricated curve invites decisions based on numbers nobody "
     "measured. The admission also scopes the Tier 2 work precisely, "
     "since the first latency numbers the project ever records will "
     "come from the verification calls themselves."),
    ("Claude",
     "1. Inferred: In support of C37, the fork sequence protects "
     "against momentum building the fallback before anyone decides "
     "to build it, since each step needs its own word and a failed "
     "test alone cannot spend the next step's authorization. "
     "Urgency after a failure is exactly when momentum decides, "
     "since a team that just watched a test fail wants a fix more "
     "than it wants a decision, and the sequence forces the decision "
     "to happen before the fix is built."),
    ("Gemini",
     "1. Inferred: In support of C6, needing only a window above "
     "twenty thousand tokens makes the proposal robust to the "
     "unconfirmed hundred-and-twenty-eight-thousand figure, "
     "because the derivation never spends the unconfirmed number "
     "and the budget survives any window comfortably above the "
     "total. Only a window proven below about twenty thousand "
     "tokens with margin would force a re-derivation, and no source "
     "in the record suggests such a window."),
    ("Grok",
     "1. Inferred: In support of C34, the proportion argument cuts "
     "against the packet decisively, since a fix that removes most "
     "of the evidence to cure a small overage has mistaken the "
     "symptom for the disease and treated the deliberation as the "
     "problem. A remedy wildly larger than the problem it cures is "
     "usually treating a different problem, and here the different "
     "problem would be deciding whose claims count."),
    ("Muse",
     "1. Inferred: In support of C27, a fixed eviction order is a "
     "kind of honesty, because it lets any reader predict exactly "
     "what was dropped first and why, while a judgment-based order "
     "would hide an editorial choice inside an implementation "
     "detail. Predictability is checkable in a way that judgment "
     "is not, since a reader can verify that superseded texts went "
     "first and responded-to details second without knowing what "
     "any implementer was thinking."),
    ("GPT",
     "1. Inferred: In support of C39, tying every verification "
     "report to a prompt hash and a deployed commit ID is what "
     "makes the result repeatable, since the same code and the same "
     "prompt must produce the same measurement or the measurement "
     "was never about the code at all. A result that cannot be "
     "tied to its code and prompt cannot be trusted, repeated, or "
     "audited, and the standing rule exists to make that failure "
     "visible rather than letting it pass quietly."),
]

_STRESS_REVISIONS = [
    ("GPT",
     "1. Inferred: Revised in light of the challenge to C8, full "
     "evidence is retained without deletion, and the synthesis may "
     "rank prominence explicitly while keeping every claim present, "
     "so attention is guided rather than manufactured by omission, "
     "and the ranking itself becomes checkable against the registry. "
     "The ranking criteria must come from the registry rather than "
     "from judgment, using revision relationships and explicit "
     "agreement, so the guidance cannot smuggle in a preference the "
     "registry does not show."),
    ("Claude",
     "1. Inferred: Revised in light of the challenge to C13, "
     "supporting claim IDs are necessary but not sufficient, and a "
     "recommendation must also show the link in reasoning rather "
     "than merely citing, so a decorative citation fails review "
     "even when the validator accepts the IDs. Showing the link "
     "means quoting or paraphrasing the cited claim's content and "
     "stating the inferential step, since an ID alone proves only "
     "that a claim exists, not that it supports anything."),
    ("Gemini",
     "1. Inferred: Revised in light of the challenge to C18, "
     "timeout pressure triggers review first and the review may "
     "conclude with a configuration change, so review-first does "
     "not forbid a trivial fix but forbids skipping the judgment "
     "about whether the fix is trivial. A conclusion of triviality "
     "must itself be recorded with a reason, since an unrecorded "
     "triviality judgment is exactly the skipped judgment the "
     "review-first rule exists to prevent."),
    ("Muse",
     "1. Inferred: Revised in light of the challenge to C36, "
     "provenance travels as compact references, claim IDs with "
     "participant and status, while full text stays in the "
     "registry, so partitions carry checkability without carrying "
     "duplicated text. A checker follows the references "
     "mechanically through registry lookups rather than re-reading "
     "evidence, so compactness shifts no labor onto human readers "
     "and the checking burden stays bounded as partitions multiply."),
    ("Grok",
     "1. Inferred: Revised in light of the challenge to C29, the "
     "test-deployment gap is closed by adoption itself, since "
     "adoption switches production to the verified token gate in "
     "one reviewed change, and until adoption the gap is disclosed "
     "rather than hidden. The adoption change carries its own "
     "deploy confirmation, which must match the reviewed commit ID "
     "rather than merely reporting that something deployed, since a "
     "deploy of the wrong commit would close the gap on paper while "
     "leaving it open in fact."),
    ("Muse",
     "1. Inferred: Revised in light of the challenge to C38, every "
     "verification report labels candidate versus adopted cap on "
     "every page, so a quoted result carries its status with it "
     "and cannot silently harden into a production guarantee. The "
     "label rule covers excerpts as well as full reports, since a "
     "status that survives only in the full document will be lost "
     "the first time anyone quotes a paragraph of it."),
    ("GPT",
     "1. Inferred: Revised in light of the growth-model challenge, "
     "the realistic-versus-stress boundary is acknowledged as "
     "judgment, and the adoption decision carries a review trigger "
     "for the first realistic meeting that exceeds the cap, so the "
     "boundary is revisited on evidence rather than defended as "
     "measurement. The trigger fires on the refusal notice itself, "
     "which is visible by construction, so no separate monitoring "
     "is needed to notice that the boundary was crossed."),
    ("Claude",
     "1. Inferred: Revised in light of the sufficiency challenge, "
     "valid structured fields are necessary for adoption but never "
     "sufficient for fidelity, and the six review judgments remain "
     "decisive, so a valid JSON that misrepresents the deliberation "
     "still fails even though the validator passed it. Both layers "
     "are required because the validator checks shape while review "
     "checks substance, and either layer alone would let a different "
     "kind of failure through."),
    ("Gemini",
     "1. Inferred: Revised in light of the reservation challenge, "
     "the output reservation stays a budget line sized from "
     "observed outputs, and any truncation surfaces visibly in "
     "verification, so the reservation neither requests tokens nor "
     "hides a shortfall. Distinguishing truncation from genuinely "
     "short content requires the output-completeness record, since "
     "short fields alone are ambiguous and only the completeness "
     "record tells review whether the model stopped early."),
    ("Grok",
     "1. Inferred: Revised in light of the refusal challenge, a "
     "refused synthesis still reports the component diagnostic and "
     "the complete transcript remains preserved, so the meeting "
     "owes its reader the boundary, the numbers, and the evidence, "
     "even when it cannot offer a synthesis. The refusal notice "
     "should carry the diagnostic summary inline rather than "
     "behind a pointer alone, since numbers behind a pointer help "
     "only readers who follow it, while the summary serves every "
     "reader of the notice itself."),
    ("Muse",
     "1. Inferred: Revised in light of the staged-coverage "
     "challenge, every active claim appears in full in at least one "
     "partition with its objections and chains traveling alongside, "
     "so staging changes where evidence is read, never whether it "
     "is read. Reading order across partitions can still affect "
     "interpretation, so the staged design must also say how "
     "partitions are ordered for the aggregator, rather than "
     "assuming order effects away."),
    ("GPT",
     "1. Inferred: Revised in light of the distribution challenge, "
     "claim-length statistics guide capacity planning but never "
     "decide which claims matter, since a short claim can carry a "
     "decisive objection and a long claim can restate what is "
     "already established. Length is weak evidence in both "
     "directions, so a short slogan without argument deserves no "
     "more weight than a long restatement, and the registry's "
     "relationships must decide weight rather than character "
     "counts."),
    ("Claude",
     "1. Inferred: Revised in light of the limitation challenge, an "
     "empty limitations field must be read against the record, and "
     "any known omission found in review becomes a limitation entry "
     "rather than an excuse for leaving the field empty. Review-"
     "found omissions depend on reviewer diligence, so the process "
     "owes diligence a structure, such as checking unaddressed "
     "claims explicitly, rather than treating diligence as a "
     "personal virtue that may or may not appear."),
    ("Gemini",
     "1. Inferred: Revised in light of the tripwire challenge, the "
     "five-cent threshold stays a review trigger and never an "
     "automatic decision, so a pricing change prompts investigation "
     "before it rearranges the architecture. Investigation without "
     "a deadline can stall indefinitely, so the trigger should "
     "carry a time box after which design review convenes "
     "regardless of whether the investigation finished, keeping "
     "the review a decision point rather than a waiting room."),
]

# Wiring by 0-based position in registration order (openings, then
# responses, then revisions). Positions are converted to claim IDs
# from the registered claims — never hand-numbered.
# (target_position, challenger_position)
_STRESS_UNRESOLVED = [
    (1, 40),    # Claude challenges GPT's "smallest value" claim.
    (3, 42),    # Grok challenges the 1.5x policy judgment.
    (18, 47),   # Muse challenges per-synthesis cost framing.
    (32, 44),   # GPT challenges interaction-vs-importance dismissal.
    (24, 45),   # Claude challenges refusal-without-artifact.
    (30, 46),   # Gemini challenges synthetic-vs-real evidence.
]
# (original_position, challenge_position, revision_position,
#  challenge_move, challenger, relationship, author)
_STRESS_CHAINS = [
    (7, 49, 68, "objection", "Claude", "revised", "GPT"),
    (12, 50, 69, "objection", "Grok", "revised", "Claude"),
    (17, 51, 70, "objection", "Muse", "revised", "Gemini"),
    (35, 52, 71, "objection", "GPT", "revised", "Muse"),
    (28, 53, 72, "objection", "Claude", "revised", "Grok"),
    (37, 54, 73, "objection", "Gemini", "revised", "Muse"),
]


# Second round: responses to revisions, then revisions answering
# them. Positions continue from round 1: openings 0-39, responses
# 40-67, revisions 68-81, so round-2 responses are 82-95 and
# round-2 revisions are 96-105 (106 claims total).
_STRESS_RESPONSES_2 = [
    ("Claude",
     "1. Inferred: In response to the prominence ranking revision, "
     "ranking by registry relationships is safer than ranking by "
     "judgment, but ranking by objection counts would reintroduce "
     "interaction-as-importance through the back door, since the "
     "most challenged claims would rise to the top for being "
     "challenged rather than for being right, and the ranking rule "
     "must therefore exclude objection counts explicitly."),
    ("Grok",
     "1. Inferred: In response to the shown-link revision, quoting "
     "a cited claim's content does not prove the inference follows, "
     "since a selective quote can support a conclusion the full "
     "claim would undermine, so the revision must state the "
     "inferential step in words rather than letting the quote do "
     "the work silently, and review must read the step rather than "
     "the quotation."),
    ("Muse",
     "1. Inferred: In response to the review-first revision, a "
     "recorded reason for triviality can itself be boilerplate, so "
     "review quality cannot be guaranteed by requiring a reason "
     "alone, and the process needs a second reader or a spot check "
     "before recorded reasons become a rubber stamp for whatever "
     "was decided quickly."),
    ("GPT",
     "1. Inferred: In response to the compact-provenance revision, "
     "following references costs checker time even when the lookup "
     "is mechanical, since each reference followed is a context "
     "switch, and compactness therefore shifts cost onto checkers "
     "rather than eliminating it, which matters when partitions "
     "multiply the references to follow."),
    ("Claude",
     "1. Inferred: In response to the adoption-closes-the-gap "
     "revision, deploy confirmation must match the reviewed commit "
     "ID rather than merely reporting that something deployed, "
     "since a deploy of the wrong commit would close the gap on "
     "paper while leaving it open in fact, and serving-code "
     "evidence exists precisely to catch that difference."),
    ("Gemini",
     "1. Inferred: In response to the label-every-page revision, "
     "labels on excerpts cannot be enforced once text leaves the "
     "system, since a quoted paragraph carries no mechanism that "
     "forces its status along with it, so the label rule reduces "
     "risk without eliminating it, and the residual risk must be "
     "acknowledged rather than described away."),
    ("Grok",
     "1. Inferred: In support of the boundary-trigger revision, the "
     "trigger fires on the refusal notice itself, which is visible "
     "by construction, so no separate monitoring is needed to "
     "notice that the boundary was crossed, and the safeguard is "
     "as automatic as the refusal it follows."),
    ("Muse",
     "1. Inferred: In support of the both-layers revision, review "
     "judgment must outrank the validator when the two disagree, "
     "since the validator checks shape while review checks "
     "substance, and a shape-passing output that misrepresents the "
     "deliberation must fail on review even though no mechanical "
     "rule caught it."),
    ("GPT",
     "1. Inferred: In support of the truncation-visibility revision, "
     "short fields alone are ambiguous, since genuinely short "
     "content and truncated content look alike in the output, so "
     "the output-completeness record is what lets review tell the "
     "two apart rather than guessing from field lengths."),
    ("Claude",
     "1. Inferred: In response to the refusal-owes revision, a "
     "transcript pointer helps only readers who follow it, so the "
     "refusal notice must carry the diagnostic summary inline for "
     "readers who never open the transcript, with the pointer "
     "serving depth rather than serving as the whole disclosure."),
    ("Gemini",
     "1. Inferred: In response to the staged-order revision, "
     "partition reading order can affect interpretation even when "
     "every claim appears somewhere, since the aggregator reads "
     "partitions in some sequence and early partitions frame later "
     "ones, so the staged design must specify the order rather "
     "than assuming order effects away."),
    ("Grok",
     "1. Inferred: In support of the length-is-weak-evidence "
     "revision, short claims can also be slogans without argument, "
     "so length fails as evidence in both directions and the "
     "registry's relationships must decide weight rather than "
     "character counts, which is the same conclusion reached from "
     "the opposite direction."),
    ("Muse",
     "1. Inferred: In support of the diligence-structure revision, "
     "checking unaddressed claims explicitly turns diligence from "
     "a personal virtue into a procedure, since a checklist item "
     "can be verified while a virtue cannot, and the limitation "
     "field improves exactly to the extent that its checks become "
     "mechanical."),
    ("GPT",
     "1. Inferred: In response to the time-boxed-investigation "
     "revision, a time box keeps review a decision point rather "
     "than a waiting room, but the box must be long enough for a "
     "genuine investigation, since a box too short forces design "
     "review to convene on incomplete findings, which trades one "
     "failure mode for another."),
]

_STRESS_REVISIONS_2 = [
    ("GPT",
     "1. Inferred: Revised in light of the ranking challenge, the "
     "prominence rule excludes objection counts explicitly and "
     "uses revision relationships and explicit agreement only, so "
     "a claim cannot rise by being challenged, and the exclusion "
     "is stated in the rule itself rather than left as an "
     "implementation habit."),
    ("Claude",
     "1. Inferred: Revised in light of the selective-quote "
     "challenge, a shown link must state the inferential step in "
     "words alongside any quotation, since the step is what review "
     "judges, and a quotation without a stated step fails review "
     "even when the quoted content is accurate."),
    ("Muse",
     "1. Inferred: Revised in light of the reference-cost "
     "challenge, reference-following is mechanical registry lookup "
     "rather than reader labor, since the checker resolves IDs to "
     "claims without re-reading evidence, and the cost that remains "
     "is bounded by the number of references rather than by the "
     "size of the evidence behind them."),
    ("Grok",
     "1. Inferred: Revised in light of the deploy-confirmation "
     "challenge, deploy confirmation means commit-ID match against "
     "the reviewed change, not a report that something deployed, "
     "so a wrong-commit deploy fails confirmation openly instead "
     "of passing it silently."),
    ("Grok",
     "1. Inferred: Revised in light of the inline-summary "
     "challenge, the refusal notice carries the diagnostic summary "
     "inline for every reader, with the transcript pointer serving "
     "depth for readers who want the evidence behind the numbers, "
     "so disclosure no longer depends on following a link."),
    ("Gemini",
     "1. Inferred: Revised in light of the time-box challenge, the "
     "investigation box is set long enough for genuine findings "
     "and short enough to force a decision, with the box length "
     "itself recorded, so a review convened on incomplete findings "
     "can say so rather than pretending completeness."),
    ("GPT",
     "1. Inferred: Revised in light of the recommend-only "
     "challenge, the synthesis header carries the recommend-only "
     "framing in its first lines, so no reader encounters content "
     "before encountering the authority limit that governs it, and "
     "the framing is part of the artifact rather than a note "
     "attached to it."),
    ("Gemini",
     "1. Inferred: Revised in light of the total-budget challenge, "
     "the sixteen-thousand-five-hundred-token total survives any "
     "context window comfortably above twenty thousand tokens, and "
     "the adoption report states that threshold explicitly, so a "
     "future window change can be judged against a number rather "
     "than against a feeling about headroom."),
    ("Claude",
     "1. Inferred: Revised in light of the limitations challenge, "
     "the limitation check runs over unaddressed claims explicitly "
     "before the field is allowed to stand empty, so an empty "
     "limitations field means the check ran and found nothing, "
     "rather than meaning nobody looked."),
    ("Muse",
     "1. Inferred: Revised in light of the basis-naming challenge, "
     "every figure in a verification report carries its basis in "
     "the same line, so a reader never has to hunt for what a "
     "number measures, and the reconciliation of the two gate "
     "totals becomes the standing example of the rule rather than "
     "an exception to it."),
]

# Round-2 wiring (positions in the full 106-claim order).
_STRESS_UNRESOLVED_2 = [
    (70, 84),   # Muse challenges review quality (no revision answers).
    (73, 87),   # Gemini challenges unenforceable excerpt labels.
    (78, 92),   # Gemini challenges partition order effects.
]
_STRESS_CHAINS_2 = [
    (68, 82, 96, "objection", "Claude", "revised", "GPT"),
    (69, 83, 97, "objection", "Grok", "revised", "Claude"),
    (71, 85, 98, "objection", "GPT", "revised", "Muse"),
    (72, 86, 99, "objection", "Claude", "revised", "Grok"),
    (77, 91, 100, "objection", "Claude", "revised", "Grok"),
    (81, 95, 101, "objection", "GPT", "revised", "Gemini"),
]


# Round-3 tuning claims (positions 106-113): supports and
# refinements that bring the assembled prompt into the middle of
# the 11,500-12,500 band. No new wiring: supports need none, and
# refinements stand without chain entries.
_STRESS_RESPONSES_3 = [
    ("Muse",
     "1. Inferred: In support of the ranking-exclusion revision, "
     "excluding objection counts from prominence is the cleaner "
     "rule, since a rule that counts challenges as importance "
     "would let a coordinated objection campaign promote any claim "
     "it targeted, and the exclusion closes that path even though "
     "it also discards the genuine signal that heavily challenged "
     "claims sometimes carry."),
    ("GPT",
     "1. Inferred: In support of the commit-ID-match revision, "
     "matching the deployed commit against the reviewed change is "
     "the smallest check that actually closes the gap, since any "
     "weaker confirmation, such as a deploy timestamp or a version "
     "string, could describe a different build than the one "
     "reviewed, and the check costs one comparison."),
    ("Claude",
     "1. Inferred: In support of the review-outranks-validator "
     "revision, the hierarchy between layers must be explicit "
     "before they disagree, since a disagreement resolved by "
     "whoever speaks last is not a hierarchy but a race, and the "
     "explicit rule that review decides substance while the "
     "validator decides shape gives each layer its own jurisdiction."),
    ("Gemini",
     "1. Inferred: In support of the checklist-diligence revision, "
     "turning diligence into procedure is what makes the limitation "
     "field auditable, since an auditor can verify that the "
     "unaddressed-claims check ran, while no auditor can verify "
     "that a reviewer was diligent in the abstract."),
]

_STRESS_REVISIONS_3 = [
    ("GPT",
     "1. Inferred: Revised in light of the full deliberation, the "
     "cap value stands with its companions rather than alone, "
     "since twelve thousand five hundred tokens plus the review "
     "trigger plus the candidate-versus-adopted label together form "
     "the proposal, and judging the number without its companions "
     "misjudges a system as if it were a constant."),
    ("Claude",
     "1. Inferred: Revised in light of the full deliberation, "
     "validity and fidelity are joint requirements with distinct "
     "owners, since the validator owns shape and review owns "
     "substance, and adoption fails if either owner reports "
     "failure, which is why the criteria list both rather than "
     "letting one stand in for the other."),
    ("Gemini",
     "1. Inferred: Revised in light of the full deliberation, the "
     "tripwire time box is recorded with its length and its reason, "
     "so a later reader can judge whether the box was generous or "
     "stingy, and the box itself becomes evidence about how "
     "seriously the investigation was taken."),
    ("Muse",
     "1. Inferred: Revised in light of the full deliberation, "
     "staged coverage requires both full appearance and a stated "
     "partition order, since appearance without order leaves the "
     "aggregator's framing to chance, and order without appearance "
     "leaves claims unread, so the staged design must specify both "
     "before it can be judged."),
]


def fixture_stress_state():
    """Upper-range stress fixture: deterministic full-evidence deliberation.

    114 claims, 5 seats, opening/response/revision phases across
    three rounds, 9 unresolved objections, 12 revision chains.
    Assembled prompt (with harness telemetry): 60,977 chars /
    11,935 tokens, inside the 11,500-12,500 band, sha256
    a8093c6ee28481f6f8a5db7ad29c51d8ec8d226263e786a96e3b41d4305cf65e.
    (Re-pinned for the fidelity-correction instruction revision;
    the pre-revision values were 59,689 chars / 11,712 tokens.)
    Size comes from distinct claims, never repeated filler (a test
    asserts unique claim bodies).
    """
    reg = ClaimRegistry()
    ordered: list = []
    for participant, phase, text in _STRESS_OPENINGS:
        ordered.extend(reg.register(participant, phase, text))
    for participant, text in _STRESS_RESPONSES:
        ordered.extend(reg.register(participant, "response", text))
    for participant, text in _STRESS_REVISIONS:
        ordered.extend(reg.register(participant, "revision", text))
    for participant, text in _STRESS_RESPONSES_2:
        ordered.extend(reg.register(participant, "response", text))
    for participant, text in _STRESS_REVISIONS_2:
        ordered.extend(reg.register(participant, "revision", text))
    for participant, text in _STRESS_RESPONSES_3:
        ordered.extend(reg.register(participant, "response", text))
    for participant, text in _STRESS_REVISIONS_3:
        ordered.extend(reg.register(participant, "revision", text))
    unresolved = [{
        "claim_id": ordered[t].id,
        "cited_by": ordered[c].participant,
        "source_claim_id": ordered[c].id,
        "moves": ["objection"],
        "state": "unresolved",
        "responded_by": None,
    } for t, c in _STRESS_UNRESOLVED + _STRESS_UNRESOLVED_2]
    chains = [{
        "original_claim_id": ordered[o].id,
        "challenge_claim_id": ordered[ch].id,
        "challenge_move": move,
        "challenger": challenger,
        "revision_claim_id": ordered[r].id,
        "revision_relationship": relationship,
        "author": author,
    } for o, ch, r, move, challenger, relationship, author in _STRESS_CHAINS + _STRESS_CHAINS_2]
    packet = EvidencePacket(
        work_item=_STRESS_WORK_ITEM,
        question=_STRESS_QUESTION,
        constraints=_STRESS_CONSTRAINTS,
    )
    return packet, reg, unresolved, chains
