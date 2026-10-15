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


class TestSegmentMoments:
    def test_splits_labeled_turns(self):
        from local_ai.agent_intake.review_claims import segment_moments

        moments = segment_moments([
            "USER: first thought about purpose",
            "assistant: a calm reply with no signal words here at all",
        ])
        assert [m.turn for m in moments] == [1, 2]
        assert moments[0].speaker == "user"
        assert moments[1].speaker == "assistant"
        assert moments[0].turn_ref == "Turn 1 · You"
        assert moments[1].turn_ref == "Turn 2 · Assistant"

    def test_short_turn_merges_into_next_same_speaker(self):
        from local_ai.agent_intake.review_claims import segment_moments

        moments = segment_moments([
            "USER: yes",
            "USER: my purpose is to write essays about what matters most in life",
        ])
        assert len(moments) == 1
        assert moments[0].turn == 1
        assert moments[0].last_turn == 2
        assert moments[0].turn_ref == "Turns 1-2 · You"
        # Verbatim text preserved.
        assert "yes" in moments[0].text
        assert "purpose" in moments[0].text

    def test_no_merge_across_speakers(self):
        from local_ai.agent_intake.review_claims import segment_moments

        moments = segment_moments(["USER: yes", "ASSISTANT: go on"])
        assert len(moments) == 2

    def test_unlabeled_example_is_one_unknown_moment(self):
        from local_ai.agent_intake.review_claims import segment_moments

        moments = segment_moments(["a freeform note about purpose and values"])
        assert len(moments) == 1
        assert moments[0].speaker == "unknown"
        assert moments[0].turn_ref == "Turn 1"


class TestBuildStrandClaims:
    def test_only_above_threshold(self):
        """Threshold is per-moment now: the agent-level sort scores no longer
        gate. A moment with no strand markers yields no card."""
        agent = _agent(sort=_sort())
        claims = build_strand_claims(agent)
        ids = [c.id for c in claims]
        assert any(i.startswith("a1:strand:self:") for i in ids)
        assert any(i.startswith("a1:strand:word:") for i in ids)
        assert not any(":strand:body:" in i for i in ids)

    def test_atomic_not_blanket(self):
        """Each strand claim anchors to ONE moment with named trigger words —
        no whole-conversation blanket summaries."""
        agent = _agent(sort=_sort())
        claims = {c.id: c for c in build_strand_claims(agent)}
        self_claims = [c for i, c in claims.items() if ":strand:self:" in i]
        assert len(self_claims) >= 1
        for c in self_claims:
            # Evidence is verbatim from the transcript.
            assert any(c.evidence in ex for ex in agent.examples)
            # Inference names the strand AND the specific trigger words.
            assert "Guide" in c.inference or "self" in c.inference.lower()
            assert c.scope == "moment"
            assert c.turn_ref.startswith("Turn")

    def test_evidence_is_verbatim(self):
        agent = _agent(sort=_sort())
        claims = build_strand_claims(agent)
        self_claims = [c for c in claims if ":strand:self:" in c.id and c.claim_type == "strand"]
        assert self_claims
        # Each claim's evidence must be one of the actual examples.
        for c in self_claims:
            assert any(c.evidence in ex for ex in agent.examples)

    def test_ids_namespaced_by_agent(self):
        """Claim ids carry the agent id: the claims table keys rows by
        claim_id alone, so bare ids would clobber other agents' cards."""
        agent = _agent(sort=_sort())
        claims = build_strand_claims(agent)
        assert claims
        for c in claims:
            assert c.id.startswith(f"{agent.id}:")

    def test_no_claim_without_anchor(self):
        """A moment with no strand markers above threshold produces nothing —
        no anchored quote means no claim."""
        agent = _agent(
            sort=_sort(),
            examples=["USER: the weather is nice today, quite pleasant indeed"],
        )
        assert build_strand_claims(agent) == []

    def test_per_strand_cap(self):
        """At most _MAX_MOMENT_CARDS_PER_STRAND cards per strand, strongest first."""
        from local_ai.agent_intake.review_claims import _MAX_MOMENT_CARDS_PER_STRAND

        examples = [
            f"USER: thinking hard about my purpose and my values in this long reflective journal entry, number {i}"
            for i in range(_MAX_MOMENT_CARDS_PER_STRAND + 4)
        ]
        agent = _agent(sort=_sort(), examples=examples)
        self_cards = [
            c for c in build_strand_claims(agent)
            if c.claim_type == "strand" and ":strand:self:" in c.id
        ]
        assert len(self_cards) == _MAX_MOMENT_CARDS_PER_STRAND
        # Strongest first — earlier ties keep turn order, so m1..m8 survive.
        assert self_cards[0].id.endswith(":m1")

    def test_alternative_reading(self):
        """A moment qualifying for two strands gets a nested alternative on
        the winner's card — individually respondable, never a silent approval."""
        agent = _agent(
            sort=_sort(),
            examples=[
                "USER: My purpose is to write essays about what matters most in life",
            ],
        )
        claims = build_strand_claims(agent)
        # The moment qualifies for word and self; the winner carries the alternative.
        alts = [c for c in claims if c.claim_type == "alternative"]
        assert len(alts) == 1
        alt = alts[0]
        parents = [c for c in claims if c.claim_type == "strand"]
        assert any(alt.id.startswith(p.id + ":alt:") for p in parents)
        assert alt.scope == "moment"
        assert alt.turn_ref.startswith("Turn 1")
        # The alternative names the runner-up strand; the parent quote is not repeated.
        assert alt.evidence == ""
        assert "Guide" in alt.inference or "self" in alt.inference.lower()

    def test_no_sort_no_claims(self):
        assert build_strand_claims(_agent()) == []

    def test_claim_shape(self):
        agent = _agent(sort=_sort())
        c = build_strand_claims(agent)[0]
        assert c.status == "pending"
        assert c.inference
        assert c.title
        assert c.question


class TestBuildKindClaim:
    def test_kind_claim(self):
        agent = _agent(sort=_sort())
        c = build_kind_claim(agent)
        assert c is not None
        assert c.id == f"{agent.id}:kind"
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


class TestInsightClaimStore:
    def test_new_fields_roundtrip(self, tmp_path):
        from local_ai.agent_intake.store import AgentStore

        store = AgentStore(db_path=tmp_path / "t.db", user_id="u1")
        claims = [
            ReviewClaim(id="insight:0", claim_type="stance", title="Stance",
                        evidence="q", inference="i",
                        question="Does that sound right to you?",
                        scope="subject", turn_ref="Turn 3"),
            ReviewClaim(id="insight:0:alt:0", claim_type="alternative", title="Alternative reading",
                        evidence="", inference="alt",
                        question="Could it be this instead?",
                        scope="moment", turn_ref="Turn 3"),
        ]
        store.save_claims("a1", claims)
        got = {c.id: c for c in store.get_claims("a1")}
        assert got["insight:0"].question == "Does that sound right to you?"
        assert got["insight:0"].scope == "subject"
        assert got["insight:0"].turn_ref == "Turn 3"
        assert got["insight:0:alt:0"].question == "Could it be this instead?"
        assert got["insight:0:alt:0"].scope == "moment"
        store.close()

    def test_migration_adds_columns_to_old_table(self, tmp_path):
        import sqlite3

        from local_ai.agent_intake.store import AgentStore

        db = tmp_path / "old.db"
        # Simulate a pre-migration review_claims table (no question/scope/turn_ref).
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE review_claims (claim_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,"
            " claim_type TEXT NOT NULL, title TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '',"
            " inference TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '',"
            " status TEXT NOT NULL DEFAULT 'pending', user_note TEXT NOT NULL DEFAULT '',"
            " created_at TEXT NOT NULL, updated_at TEXT NOT NULL, user_id TEXT NOT NULL DEFAULT '')"
        )
        conn.execute(
            "INSERT INTO review_claims VALUES ('c1','a1','strand','t','e','i','',"
            " 'accepted','note','2026-01-01','2026-01-01','u1')"
        )
        conn.commit()
        conn.close()

        store = AgentStore(db_path=db, user_id="u1")
        got = store.get_claims("a1")
        assert len(got) == 1
        # Old row reads back with safe defaults; nothing breaks.
        assert got[0].question == ""
        assert got[0].scope == "moment"
        assert got[0].turn_ref == ""
        assert got[0].status == "accepted"
        # And new-field writes work on the migrated table.
        store.save_claims("a1", [
            ReviewClaim(id="insight:0", claim_type="stance", title="Stance",
                        evidence="e", inference="i", question="q?", scope="pattern"),
        ])
        got2 = {c.id: c for c in store.get_claims("a1")}
        assert got2["insight:0"].scope == "pattern"
        store.close()

    def test_delete_claim_types_keeps_mined(self, tmp_path):
        from local_ai.agent_intake.store import AgentStore

        store = AgentStore(db_path=tmp_path / "t.db", user_id="u1")
        store.save_claims("a1", [
            ReviewClaim(id="strand:self", claim_type="strand", title="t", evidence="", inference=""),
            ReviewClaim(id="insight:0", claim_type="stance", title="t", evidence="", inference=""),
            ReviewClaim(id="insight:0:alt:0", claim_type="alternative", title="t", evidence="", inference=""),
            ReviewClaim(id="project:0", claim_type="project", title="t", evidence="", inference=""),
        ])
        n = store.delete_claim_types("a1", ("strand", "stance", "alternative"))
        assert n == 3
        remaining = [c.id for c in store.get_claims("a1")]
        assert remaining == ["project:0"]
        store.close()

    def test_new_statuses_roundtrip(self, tmp_path):
        from local_ai.agent_intake.store import AgentStore

        store = AgentStore(db_path=tmp_path / "t.db", user_id="u1")
        store.save_claims("a1", [
            ReviewClaim(id="c1", claim_type="stance", title="t", evidence="", inference=""),
        ])
        assert store.update_claim("c1", "rejected")
        assert store.update_claim("c1", "unresolved")
        assert store.get_claims("a1")[0].status == "unresolved"
        store.close()
