"""Tests for per-inference review claims (granular interactive assimilation)."""
from __future__ import annotations

import pytest

from local_ai.agent_intake.review_claims import (
    ReviewClaim,
    build_kind_claim,
    build_mined_claims,
    build_strand_claims,
    find_evidence_chunk,
    humanize_strand_inference,
)
from local_ai.agent_intake.schema import ConnectedAgent, SortResult, StrandClaim


def _agent(**kw):
    base = dict(
        id="a1",
        name="Test chat",
        source_platform="chatgpt_share",
        description="Shared chat",
        instructions=None,
        examples=[
            "USER: I've been thinking a lot about my purpose and what really matters to me.",
            "ASSISTANT: Purpose is a good place to start. What values feel most alive right now?",
            "USER: I want to write about the death of explanation in my new essay.",
        ],
        sort=None,
        status="pending_review",
        created_at="2026-10-14T00:00:00Z",
    )
    base.update(kw)
    return ConnectedAgent(**base)


def _sort():
    return SortResult(
        primary_strand="self",
        claims=[
            StrandClaim(strand="self", score=0.9, reasoning="mentions purpose, values — strong self signals"),
            StrandClaim(strand="word", score=0.7, reasoning="mentions writing, essay — strong word signals"),
            StrandClaim(strand="body", score=0.1, reasoning="no clear body markers — passing"),
        ],
        strand_weights={"self": 0.9, "word": 0.7},
        kind="project",
        kind_reasoning="project language ('working on') — reads as goal-directed work",
    )


class TestFindEvidenceChunk:
    def test_returns_verbatim_chunk_with_most_hits(self):
        examples = [
            "USER: hello there",
            "USER: I've been thinking about my purpose and values a lot lately",
        ]
        out = find_evidence_chunk(examples, ("purpose", "values", "meaning"))
        assert out == examples[1]

    def test_returns_empty_when_no_match(self):
        out = find_evidence_chunk(["USER: hello"], ("quantum", "physics"))
        assert out == ""

    def test_returns_empty_for_no_examples(self):
        assert find_evidence_chunk([], ("purpose",)) == ""

    def test_trims_long_chunks(self):
        long = "USER: " + "purpose " * 100
        out = find_evidence_chunk([long], ("purpose",))
        assert len(out) <= 401
        assert out.startswith("USER:")


class TestHumanize:
    def test_rule_based_becomes_plain_language(self):
        out = humanize_strand_inference("self", "mentions purpose, values — strong self signals", 0.9)
        assert "mentions" not in out
        assert "markers" not in out
        assert "purpose" in out

    def test_llm_reasoning_kept(self):
        out = humanize_strand_inference(
            "self", "You return repeatedly to questions of who you're becoming.", 0.8
        )
        assert "who you're becoming" in out


class TestBuildStrandClaims:
    def test_only_above_threshold(self):
        agent = _agent(sort=_sort())
        claims = build_strand_claims(agent)
        ids = [c.id for c in claims]
        assert "strand:self" in ids
        assert "strand:word" in ids
        assert "strand:body" not in ids  # 0.1 < 0.25

    def test_evidence_is_verbatim(self):
        agent = _agent(sort=_sort())
        claims = {c.id: c for c in build_strand_claims(agent)}
        # The self claim's evidence must be one of the actual examples.
        assert any(claims["strand:self"].evidence in ex for ex in agent.examples)

    def test_no_sort_no_claims(self):
        assert build_strand_claims(_agent()) == []

    def test_claim_shape(self):
        agent = _agent(sort=_sort())
        c = build_strand_claims(agent)[0]
        assert c.status == "pending"
        assert c.inference
        assert c.title


class TestBuildKindClaim:
    def test_kind_claim(self):
        agent = _agent(sort=_sort())
        c = build_kind_claim(agent)
        assert c is not None
        assert c.id == "kind"
        assert "project" in c.title

    def test_no_claim_when_undecided(self):
        s = _sort()
        s.kind = "undecided"
        assert build_kind_claim(_agent(sort=s)) is None


class TestBuildMinedClaims:
    def _mining(self):
        from local_ai.agent_intake.project_miner import (
            MiningResult, ProposedInitiative, ProposedProject, ProposedTask, ProposedIdea,
        )
        return MiningResult(
            initiatives=[ProposedInitiative(title="Write the book", brief="A book", source_quote="USER: I want to write a book")],
            projects=[ProposedProject(title="Draft chapter one", goal="First draft", source_quote="USER: starting chapter one")],
            standalone_tasks=[ProposedTask(title="Outline", source_quote="USER: need an outline")],
            ideas=[ProposedIdea(title="Podcast idea", source_quote="USER: maybe a podcast")],
            engine="rule_based",
        )

    def test_all_sections_become_claims(self):
        claims = build_mined_claims(self._mining())
        types = [c.claim_type for c in claims]
        assert types == ["initiative", "project", "task", "idea"]

    def test_evidence_is_source_quote_verbatim(self):
        claims = build_mined_claims(self._mining())
        assert claims[0].evidence == "USER: I want to write a book"
        assert claims[1].evidence == "USER: starting chapter one"

    def test_ids_are_stable(self):
        claims = build_mined_claims(self._mining())
        assert [c.id for c in claims] == ["initiative:0", "project:0", "task:0", "idea:0"]


class TestClaimStore:
    def test_save_and_get_roundtrip(self, tmp_path):
        from local_ai.agent_intake.store import AgentStore

        store = AgentStore(db_path=tmp_path / "t.db", user_id="u1")
        claims = [
            ReviewClaim(id="strand:self", claim_type="strand", title="Guide",
                        evidence="q", inference="i", status="pending"),
        ]
        store.save_claims("a1", claims)
        got = store.get_claims("a1")
        assert len(got) == 1
        assert got[0].id == "strand:self"
        assert got[0].status == "pending"
        store.close()

    def test_update_claim_status(self, tmp_path):
        from local_ai.agent_intake.store import AgentStore

        store = AgentStore(db_path=tmp_path / "t.db", user_id="u1")
        store.save_claims("a1", [
            ReviewClaim(id="strand:self", claim_type="strand", title="Guide",
                        evidence="q", inference="i"),
        ])
        assert store.update_claim("strand:self", "explained", "because reasons")
        got = store.get_claims("a1")[0]
        assert got.status == "explained"
        assert got.user_note == "because reasons"
        store.close()

    def test_claims_are_per_user(self, tmp_path):
        from local_ai.agent_intake.store import AgentStore

        db = tmp_path / "t.db"
        s1 = AgentStore(db_path=db, user_id="u1")
        s1.save_claims("a1", [ReviewClaim(id="c1", claim_type="strand", title="t", evidence="", inference="")])
        s1.close()
        s2 = AgentStore(db_path=db, user_id="u2")
        assert s2.get_claims("a1") == []
        s2.close()
