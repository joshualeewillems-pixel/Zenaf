"""Phase B1: exact token measurement + telemetry-inclusive gate.

No model is called here; every token count is an offline tiktoken
measurement of a string the system already builds. The recorded-run
fixtures are rebuilt from the meeting response artifacts (claims,
unresolved objections, revision chains, work item + question); the
packet carries work_item + question only, because constraints /
excerpts / context are not preserved separately in the artifact —
the resulting rebuilt-vs-recorded gap is disclosed in the B1
measurement report, not smoothed over.
"""

import hashlib
import json
import re
from pathlib import Path

from local_ai.build_room.meeting import (
    Budget,
    Claim,
    ClaimRegistry,
    EvidencePacket,
    _SYNTHESIS_INSTRUCTION,
    _telemetry_block,
    build_synthesis_state,
    count_tokens_exact,
)
from local_ai.build_room.harness_fixtures import (
    TELEMETRY,
    fixture_d_state,
    fixture_e_state,
)
from local_ai.llm.tokenizer import count_tokens, tokenizer_info

CAP = 40000
FIXTURES = Path(__file__).parent / "fixtures"


def _telemetry():
    return _telemetry_block(**TELEMETRY)


def _load_recorded(name):
    data = json.loads((FIXTURES / name).read_text())
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


def _parse_reason(reason):
    nums = dict(re.findall(
        r"(mandatory|optional|instruction|disclosure|telemetry|separators|total|excess|cap)=(\d+)",
        reason))
    return {k: int(v) for k, v in nums.items()}


def test_tokenizer_resolves_expected_encoding():
    info = tokenizer_info()
    assert info["available"] is True
    assert info["model"] == "gpt-4o-mini"
    assert info["encoding"] == "o200k_base"
    assert info["encoding_matches_expected"] is True


def test_token_counts_deterministic_and_pinned():
    assert count_tokens("") == 0
    assert count_tokens("Hello world") == 2
    text = "The council recommends only; Joshua decides."
    assert count_tokens(text) == count_tokens(text)


def test_fixture_prompts_pinned_after_fidelity_instruction_revision():
    # Phase A prompt hashes, re-pinned for the fidelity-correction
    # instruction revision (design: zenaf-build-council-fidelity-
    # correction-design.md). The ONLY delta vs the Phase A pins is
    # the appended instruction paragraph (+1288 chars / +223 tokens).
    # NOTE: these deterministic prompts now differ from the
    # live-verified D/E prompt hashes of 2026-10-26 (fc12eb57...,
    # 241d012b...); live harness equivalence would need fresh
    # authorization to re-verify, and is NOT claimed here.
    cases = [("D", fixture_d_state, 6091, 1224,
              "5dfb71128a61d607bb1ee72f3bb93b02bca3359c60eec3955f1305946ba21f06"),
             ("E", fixture_e_state, 5664, 1124,
              "b21b5fe82117348a840bbe253d7a901d0570ec31c31f0c00187cf23371c5d331")]
    for fid, builder, chars, toks, digest in cases:
        packet, reg, unres, chains = builder()
        tel = _telemetry()
        state = build_synthesis_state(packet, reg, unres, chains,
                                      cap_chars=CAP, telemetry=tel)
        assert state["prompt"] is not None
        assembled = state["prompt"] + "\n\n" + tel
        assert len(assembled) == chars
        assert count_tokens(assembled) == toks
        assert state["assembled_chars"] == chars
        assert state["assembled_tokens"] == toks
        assert hashlib.sha256(assembled.encode()).hexdigest() == digest
        assert 4.0 < chars / toks < 6.0  # sane chars/token band, not a claim


def test_cap_still_40000():
    assert Budget().max_response_prompt_chars == 40000


def test_gate_without_telemetry_preserves_227_arithmetic():
    reg = ClaimRegistry()
    for i in range(150):
        reg.register("GPT", "opening", "1. Observed: " + "x" * 280 + f" claim {i}.")
    packet = EvidencePacket(work_item="B1 legacy-gate fixture",
                            question="Q?")
    state = build_synthesis_state(packet, reg, [], [], cap_chars=CAP)
    assert state["prompt"] is None
    parts = _parse_reason(state["reason"])
    assert parts["cap"] == CAP
    assert parts["total"] == (parts["mandatory"] + parts["instruction"]
                              + parts["disclosure"])
    assert parts["excess"] == parts["total"] - CAP
    assert state["reason"].startswith("budget_exceeded")
    assert "nothing was truncated" in state["reason"]


def test_gate_telemetry_path_refuses_old_fitting_state():
    # Size one claim so the state fits the OLD gate (mandatory +
    # disclosure + instruction <= cap) but exceeds the ASSEMBLED
    # length once telemetry (~421) + joins (8) are counted.
    tel = _telemetry()
    assert len(tel) == 421
    packet = EvidencePacket(work_item="B1 gate fixture", question="Q?")
    probe = ClaimRegistry()
    probe.register("GPT", "opening", "1. Observed: " + "y" * 100)
    base = build_synthesis_state(packet, probe, [], [],
                                 cap_chars=10 ** 9)["mandatory_chars"]
    # Target mandatory so mandatory + 154 + 4165 lands in (39571, 40000].
    # Re-targeted by exactly the instruction delta (4165 - 2877 = 1288)
    # so the test's intent is unchanged: fits the legacy gate, refuses
    # once telemetry + joins are counted.
    target_mandatory = 35612
    pad = target_mandatory - base + 100  # +100 offsets the probe text
    reg = ClaimRegistry()
    reg.register("GPT", "opening", "1. Observed: " + "y" * pad)
    old = build_synthesis_state(packet, reg, [], [], cap_chars=CAP)
    assert old["prompt"] is not None  # fits the legacy gate
    assert old["mandatory_chars"] + 154 + len(_SYNTHESIS_INSTRUCTION) <= CAP
    new = build_synthesis_state(packet, reg, [], [], cap_chars=CAP,
                                telemetry=tel)
    assert new["prompt"] is None  # refuses under assembled-length gating
    parts = _parse_reason(new["reason"])
    assert parts["telemetry"] == 421
    assert parts["separators"] == 8
    assert parts["total"] == (parts["mandatory"] + parts["optional"]
                              + parts["instruction"] + parts["disclosure"]
                              + parts["telemetry"] + parts["separators"])
    assert parts["excess"] == parts["total"] - CAP
    assert parts["total"] > CAP
    assert new["total_chars"] == parts["total"]
    assert new["excess_chars"] == parts["excess"]


def test_gate_telemetry_path_evicts_optional_then_fits():
    tel = _telemetry()
    reg = ClaimRegistry()
    reg.claims.append(Claim(id="C1", participant="GPT", phase="opening",
                            text="Observed: " + "a" * 30000, status="Observed"))
    reg.claims.append(Claim(id="C2", participant="Claude", phase="opening",
                            text="Observed: " + "b" * 8000, status="Observed",
                            disposition="revised", disposition_by="C9"))
    packet = EvidencePacket(work_item="B1 eviction fixture", question="Q?")
    responded = [{"claim_id": "C1", "cited_by": "Claude",
                  "source_claim_id": "C2", "moves": ["objection"],
                  "state": "responded_to", "responded_by": "C9"}]
    state = build_synthesis_state(packet, reg, responded, [],
                                  cap_chars=CAP, telemetry=tel)
    assert state["prompt"] is not None
    assert state["omitted"]["superseded_texts"] == 1
    assert state["assembled_chars"] == (len(state["prompt"])
                                        + len(tel) + 2)
    assert state["assembled_chars"] <= CAP
    assert state["assembled_tokens"] is not None
    assert state["assembled_tokens"] > 0


def test_failed_run_fixture_refuses_under_both_gates():
    packet, reg, unres, chains = _load_recorded("b1_failed_run.json")
    assert len(reg.claims) == 68
    old = build_synthesis_state(packet, reg, unres, chains, cap_chars=CAP)
    assert old["prompt"] is None
    assert old["mandatory_chars"] == 38986
    tel = _telemetry()
    new = build_synthesis_state(packet, reg, unres, chains, cap_chars=CAP,
                                telemetry=tel)
    assert new["prompt"] is None
    parts = _parse_reason(new["reason"])
    assert parts["mandatory"] == 38986
    assert parts["telemetry"] == 421
    assert parts["separators"] == 8
    assert parts["total"] == 43734
    assert parts["excess"] == 3734
    # The old gate already undercounted by telemetry + joins (429).
    assert parts["total"] - (38986 + 154 + len(_SYNTHESIS_INSTRUCTION)) == 429


def test_fitting_run_fixture_fits_with_telemetry_and_tokens_pinned():
    packet, reg, unres, chains = _load_recorded("b1_fitting_run.json")
    assert len(reg.claims) == 69
    tel = _telemetry()
    state = build_synthesis_state(packet, reg, unres, chains, cap_chars=CAP,
                                  telemetry=tel)
    assert state["prompt"] is not None
    assembled = state["prompt"] + "\n\n" + tel
    assert len(assembled) == 36577
    assert count_tokens(assembled) == 6928
    assert state["assembled_chars"] == 36577
    assert state["assembled_tokens"] == 6928
    assert hashlib.sha256(assembled.encode()).hexdigest()[:16] == "ed0d28b45cc896e3"
    assert CAP - len(assembled) == 3423


def test_failed_run_would_be_tokens_measured_not_estimated():
    packet, reg, unres, chains = _load_recorded("b1_failed_run.json")
    tel = _telemetry()
    big = build_synthesis_state(packet, reg, unres, chains,
                                cap_chars=10 ** 9, telemetry=tel)
    assert big["prompt"] is not None
    would = big["prompt"] + "\n\n" + tel
    assert len(would) == 44058
    assert count_tokens(would) == 8410
    # chars/4 overestimates the exact count by ~31% on this prompt:
    # it must never be used to derive a cap.
    assert len(would) // 4 == 11014
    assert count_tokens(would) < len(would) // 4


def test_count_tokens_exact_returns_none_free_int():
    assert count_tokens_exact("hello world") == 2
