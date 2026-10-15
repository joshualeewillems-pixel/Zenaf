"""Tests for the atomic insight miner (five-part reviewable insights).

Core guarantees under test:
- Anchoring: a quote that doesn't appear verbatim in the transcript is
  dropped — never invented, never paraphrased into a claim.
- Conservatism: no quote -> no claim; empty transcript -> no insights.
- Scope defaults to "moment" when the miner's label is invalid.
- Alternatives are parsed, capped, and individually structured.
- The rule-based fallback is honest and minimal: it surfaces explicit
  stance statements only, with the conservative null-hypothesis alternative.
- build_insight_claims: stable id scheme, alternatives linked, scope and
  question carried onto each claim.
"""
from __future__ import annotations

import json

import pytest

from local_ai.agent_intake import insight_miner
from local_ai.agent_intake.insight_miner import (
    InsightAlternative,
    MinedInsight,
    mine_insights,
)
from local_ai.agent_intake.review_claims import build_insight_claims

TRANSCRIPT = [
    "USER: I disagree with the Wishcraft summary — it treats the framework as inherently valuable.",
    "ASSISTANT: Interesting. What bothers you about it?",
    "USER: I think experience matters more than conceptual understanding here. I'm allergic to reification.",
]


def _llm_response(payload: dict) -> str:
    return json.dumps(payload)


def _mock_llm(monkeypatch, payload: dict):
    """Pretend the intake LLM returned the given payload."""
    monkeypatch.setattr(
        insight_miner, "_api_key", lambda user_id=None: "test-key"
    )
    import local_ai.agent_intake.llm_keys as llm_keys

    monkeypatch.setattr(
        llm_keys, "generate", lambda *a, **k: _llm_response(payload)
    )


def _insight_payload(**kw):
    base = {
        "turn": 1,
        "evidence": "I disagree with the Wishcraft summary — it treats the framework as inherently valuable.",
        "claim_type": "stance",
        "interpretation": "You rejected the summary's framing, which suggests you don't grant frameworks inherent authority.",
        "interpretation_scope": "moment",
        "interpretation_question": "Does that sound right to you?",
        "strand": None,
        "alternatives": [
            {
                "text": "You objected to this specific summary, not to frameworks in general.",
                "scope": "moment",
                "question": "Was it this summary, or frameworks in general?",
            }
        ],
    }
    base.update(kw)
    return {"insights": [base]}


class TestAnchoring:
    def test_fabricated_quote_is_dropped(self, monkeypatch):
        _mock_llm(
            monkeypatch,
            _insight_payload(
                evidence="You said you hate all frameworks and always have."
            ),
        )
        insights, engine = mine_insights(TRANSCRIPT)
        assert engine == "anthropic"
        assert insights == []

    def test_paraphrase_is_not_a_quote(self, monkeypatch):
        _mock_llm(
            monkeypatch,
            _insight_payload(
                evidence="the user expressed disagreement with summary frameworks"
            ),
        )
        insights, _ = mine_insights(TRANSCRIPT)
        assert insights == []

    def test_verbatim_quote_anchors(self, monkeypatch):
        _mock_llm(monkeypatch, _insight_payload())
        insights, _ = mine_insights(TRANSCRIPT)
        assert len(insights) == 1
        assert insights[0].turn == 1
        assert insights[0].alternatives[0].text.startswith("You objected")

    def test_missing_evidence_means_no_claim(self, monkeypatch):
        _mock_llm(monkeypatch, _insight_payload(evidence=""))
        insights, _ = mine_insights(TRANSCRIPT)
        assert insights == []

    def test_missing_interpretation_means_no_claim(self, monkeypatch):
        _mock_llm(monkeypatch, _insight_payload(interpretation=""))
        insights, _ = mine_insights(TRANSCRIPT)
        assert insights == []

    def test_empty_transcript_means_no_insights(self, monkeypatch):
        _mock_llm(monkeypatch, {"insights": []})
        insights, engine = mine_insights([])
        assert insights == []
        assert engine == "rule_based"


class TestScopeConservatism:
    def test_invalid_scope_defaults_to_moment(self, monkeypatch):
        _mock_llm(monkeypatch, _insight_payload(interpretation_scope="universal-truth"))
        insights, _ = mine_insights(TRANSCRIPT)
        assert insights[0].interpretation_scope == "moment"

    def test_invalid_alternative_scope_defaults_to_moment(self, monkeypatch):
        payload = _insight_payload()
        payload["insights"][0]["alternatives"][0]["scope"] = "everything"
        _mock_llm(monkeypatch, payload)
        insights, _ = mine_insights(TRANSCRIPT)
        assert insights[0].alternatives[0].scope == "moment"

    def test_valid_scopes_pass_through(self, monkeypatch):
        payload = _insight_payload(interpretation_scope="pattern")
        payload["insights"][0]["alternatives"][0]["scope"] = "subject"
        _mock_llm(monkeypatch, payload)
        insights, _ = mine_insights(TRANSCRIPT)
        assert insights[0].interpretation_scope == "pattern"
        assert insights[0].alternatives[0].scope == "subject"

    def test_invalid_claim_type_defaults(self, monkeypatch):
        _mock_llm(monkeypatch, _insight_payload(claim_type="vibe"))
        insights, _ = mine_insights(TRANSCRIPT)
        assert insights[0].claim_type == "value_inference"

    def test_alternatives_capped(self, monkeypatch):
        payload = _insight_payload()
        payload["insights"][0]["alternatives"] = [
            {"text": f"alt {i}", "scope": "moment", "question": "q?"}
            for i in range(10)
        ]
        _mock_llm(monkeypatch, payload)
        insights, _ = mine_insights(TRANSCRIPT)
        assert len(insights[0].alternatives) == 3

    def test_out_of_range_turn_becomes_none(self, monkeypatch):
        _mock_llm(monkeypatch, _insight_payload(turn=99))
        insights, _ = mine_insights(TRANSCRIPT)
        assert insights[0].turn is None


class TestRuleBasedFallback:
    def _no_key(self, monkeypatch):
        monkeypatch.setattr(insight_miner, "_api_key", lambda user_id=None: None)

    def test_finds_explicit_stance(self, monkeypatch):
        self._no_key(monkeypatch)
        insights, engine = mine_insights(TRANSCRIPT)
        assert engine == "rule_based"
        assert len(insights) >= 1
        # Evidence is the person's own verbatim line.
        assert any("I disagree with the Wishcraft summary" in s.evidence for s in insights)

    def test_scope_is_moment_and_alternative_is_honest(self, monkeypatch):
        self._no_key(monkeypatch)
        insights, _ = mine_insights(TRANSCRIPT)
        for s in insights:
            assert s.interpretation_scope == "moment"
            assert len(s.alternatives) == 1
            # The null hypothesis, not an invented depth.
            assert "specific moment" in s.alternatives[0].text

    def test_no_markers_no_insights(self, monkeypatch):
        self._no_key(monkeypatch)
        insights, _ = mine_insights(["USER: hello", "ASSISTANT: hi there"])
        assert insights == []

    def test_llm_failure_falls_back(self, monkeypatch):
        import local_ai.agent_intake.llm_keys as llm_keys

        monkeypatch.setattr(insight_miner, "_api_key", lambda user_id=None: "k")
        monkeypatch.setattr(
            llm_keys, "generate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        insights, engine = mine_insights(TRANSCRIPT)
        assert engine == "rule_based"
        assert len(insights) >= 1


class TestBuildInsightClaims:
    def _mined(self):
        return [
            MinedInsight(
                turn=3,
                evidence="I'm allergic to reification.",
                claim_type="stance",
                interpretation="You resist granting abstract frameworks inherent authority.",
                interpretation_scope="moment",
                interpretation_question="Does that sound right to you?",
                strand=None,
                alternatives=[
                    InsightAlternative(
                        text="You objected to this summary's application, not frameworks in general.",
                        scope="moment",
                        question="Was it this summary, or frameworks in general?",
                    )
                ],
            )
        ]

    def test_id_scheme_and_linkage(self):
        claims = build_insight_claims(self._mined(), "a1")
        assert [c.id for c in claims] == ["a1:insight:0", "a1:insight:0:alt:0"]
        assert claims[0].claim_type == "stance"
        assert claims[1].claim_type == "alternative"

    def test_five_parts_present(self):
        claims = build_insight_claims(self._mined(), "a1")
        main, alt = claims
        # 1. Evidence
        assert main.evidence == "I'm allergic to reification."
        assert main.turn_ref == "Turn 3"
        # 2. Interpretation
        assert "inherent authority" in main.inference
        # 3. Alternatives carry their own text...
        assert "this summary's application" in alt.inference
        # 4. ...and their own scope
        assert main.scope == "moment"
        assert alt.scope == "moment"
        # 5. ...and their own question
        assert main.question == "Does that sound right to you?"
        assert alt.question == "Was it this summary, or frameworks in general?"

    def test_alternatives_do_not_repeat_evidence(self):
        # The parent card shows the quote; per-alternative repetition is noise.
        claims = build_insight_claims(self._mined(), "a1")
        assert claims[1].evidence == ""

    def test_all_pending_initially(self):
        claims = build_insight_claims(self._mined(), "a1")
        assert all(c.status == "pending" for c in claims)

    def test_empty_in_empty_out(self):
        assert build_insight_claims([], "a1") == []
