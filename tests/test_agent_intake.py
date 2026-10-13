"""Tests for Agent Intake & Sorting ("The Sorting") v1.

Covers: rule-based sorter accuracy on labeled fixtures, pipeline redaction
at capture, the review queue, and confirm-with-corrections.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_ai.agent_intake import pipeline
from local_ai.agent_intake.pipeline import AgentIntakeError, confirm_agent, connect_agent
from local_ai.agent_intake.schema import ConnectedAgent, SortResult
from local_ai.agent_intake.sorter import sort
from local_ai.agent_intake.store import AgentStore


# ---------------------------------------------------------------------------
# Sorter fixtures: (name, description, instructions, examples, want_strand, want_kind)
# ---------------------------------------------------------------------------

FIXTURES = [
    (
        "Cold Email Writer",
        "A GPT that helps me write cold emails. It follows a process: research "
        "the prospect, draft three subject lines, then write the body using my "
        "template. The steps are always the same.",
        None,
        [],
        "word",
        "skill",
    ),
    (
        "Spreadsheet Analyst",
        "Helps me analyze sales data every week. It calculates metrics, builds "
        "charts, and forecasts trends for my dashboard, following a template.",
        None,
        [],
        "number",
        "skill",
    ),
    (
        "Logo Muse",
        "It just gets my visual taste. I describe a vibe and it naturally "
        "proposes logo directions with a strong sense of color and typography.",
        None,
        [],
        "image",
        "talent",
    ),
    (
        "Mix Assistant",
        "Helps me with mixing and mastering my podcast episodes. Workflow: "
        "balance levels, cut silences, then master the track from my checklist.",
        None,
        [],
        "sound",
        "skill",
    ),
    (
        "Sourdough Coach",
        "My bread-baking helper. It walks me through each bake: feed the "
        "starter, mix and shape the dough, then bake, following my recipe "
        "template with steps for timing.",
        None,
        [],
        "body",
        "skill",
    ),
    (
        "Hiring Gut-Check",
        "It has a great sense of people. I paste interview notes and it "
        "naturally spots what I missed — its intuition for team fit surprises me.",
        None,
        [],
        "people",
        "talent",
    ),
    (
        "Morning Planner",
        "Helps me plan my day. The process: review my goals, prioritize three "
        "tasks, then time-block my calendar for focus.",
        None,
        [],
        "self",
        "skill",
    ),
    (
        "Novel Engine",
        "A Claude Project I'm working on for my novel. It helps me develop "
        "chapters and track the story arc across drafts.",
        None,
        [],
        "word",  # story/draft markers lean Word; kind is what matters here
        "project",
    ),
]


@pytest.mark.parametrize(
    "name,description,instructions,examples,want_strand,want_kind", FIXTURES
)
def test_sorter_fixture(name, description, instructions, examples, want_strand, want_kind):
    result = sort(name, description, instructions, examples)
    assert isinstance(result, SortResult)
    assert result.primary_strand == want_strand, (
        f"{name}: got {result.primary_strand}, claims="
        f"{[(c.strand, c.score) for c in result.claims]}"
    )
    assert result.kind == want_kind, f"{name}: got kind {result.kind}"
    # All seven strands make a claim, sorted by score desc.
    assert len(result.claims) == 7
    scores = [c.score for c in result.claims]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert all(c.reasoning for c in result.claims)
    assert result.kind_reasoning


def test_sorter_is_deterministic():
    name, description = "Cold Email Writer", FIXTURES[0][1]
    first = sort(name, description).to_dict()
    second = sort(name, description).to_dict()
    assert first == second


def test_sorter_low_confidence_probes():
    result = sort("Helper", "It helps with stuff.")
    assert result.confidence < 0.35
    assert result.needs_probing is True
    assert result.kind == "undecided"


def test_sorter_uses_instructions_and_examples():
    # Bare description is vague; instructions carry the signal.
    vague = sort("Assistant", "Does things for me.")
    assert vague.needs_probing is True
    grounded = sort(
        "Assistant",
        "Does things for me.",
        instructions="You are a music composition helper. Write melodies, "
        "suggest chord progressions, and help with songwriting.",
        examples=["User: write me a chorus\nAssistant: here's a melody..."],
    )
    assert grounded.primary_strand == "sound"
    assert grounded.needs_probing is False


# ---------------------------------------------------------------------------
# Pipeline: redaction at capture, review queue, confirm
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> AgentStore:
    s = AgentStore(db_path=tmp_path / "agents.db")
    yield s
    s.close()


@pytest.fixture()
def corrections_log(tmp_path: Path) -> Path:
    return tmp_path / "corrections.jsonl"


def test_pipeline_redacts_pii_at_capture(store: AgentStore):
    agent = connect_agent(
        name="Outreach Bot",
        platform="chatgpt",
        description="Writes cold emails for me. Contact me at josh@example.com "
        "or 555-123-4567 for follow-ups.",
        instructions="My phone is 555-987-6543. Always sign as Josh.",
        examples=["Email josh@example.com the draft"],
        store=store,
    )
    assert isinstance(agent, ConnectedAgent)
    assert agent.status == "pending_review"
    assert agent.sort is not None
    for text in [agent.description, agent.instructions or "", *agent.examples]:
        assert "josh@example.com" not in text
        assert "555-123-4567" not in text
        assert "555-987-6543" not in text
    assert "[EMAIL]" in agent.description
    assert "[PHONE]" in agent.description
    # Stored copy is redacted too.
    stored = store.get(agent.id)
    assert stored is not None
    assert "josh@example.com" not in stored.description


def test_review_queue_lists_pending(store: AgentStore):
    assert store.list_pending() == []
    a1 = connect_agent("A1", "chatgpt", "Helps me write essays.", store=store)
    a2 = connect_agent("A2", "claude", "Analyzes my data.", store=store)
    pending = store.list_pending()
    assert {a.id for a in pending} == {a1.id, a2.id}
    assert len(store.list_all()) == 2


def test_confirm_accept_activates(store: AgentStore, corrections_log: Path):
    agent = connect_agent("A1", "chatgpt", "Helps me write essays.", store=store)
    updated = confirm_agent(
        agent.id, accepted=True, store=store, corrections_log=corrections_log
    )
    assert updated.status == "active"
    assert store.get(agent.id).status == "active"
    assert store.list_pending() == []
    # No correction logged on a clean accept.
    assert not corrections_log.exists()


def test_confirm_with_corrections_applies_and_logs(
    store: AgentStore, corrections_log: Path
):
    agent = connect_agent(
        "Mediator Bot",
        "chatgpt",
        "Helps me write difficult emails to my team.",
        store=store,
    )
    original_strand = agent.sort.primary_strand
    updated = confirm_agent(
        agent.id,
        accepted=True,
        corrections={"primary_strand": "people", "kind": "talent"},
        store=store,
        corrections_log=corrections_log,
    )
    assert updated.status == "active"
    assert updated.sort.primary_strand == "people"
    assert updated.sort.kind == "talent"
    assert updated.sort.needs_probing is False
    # Original claims preserved; correction recorded separately.
    assert len(updated.sort.claims) == 7
    lines = corrections_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["agent_id"] == agent.id
    assert entry["correction"] == {"primary_strand": "people", "kind": "talent"}
    assert entry["original"]["primary_strand"] == original_strand
    assert "ts" in entry


def test_confirm_reject_archives(store: AgentStore, corrections_log: Path):
    agent = connect_agent("A1", "chatgpt", "Helps me write essays.", store=store)
    updated = confirm_agent(
        agent.id, accepted=False, store=store, corrections_log=corrections_log
    )
    assert updated.status == "archived"
    assert store.list_pending() == []


def test_confirm_unknown_agent_raises(store: AgentStore, corrections_log: Path):
    with pytest.raises(AgentIntakeError):
        confirm_agent(
            "nope", accepted=True, store=store, corrections_log=corrections_log
        )


def test_confirm_invalid_correction_raises(store: AgentStore, corrections_log: Path):
    agent = connect_agent("A1", "chatgpt", "Helps me write essays.", store=store)
    with pytest.raises(AgentIntakeError):
        confirm_agent(
            agent.id,
            accepted=True,
            corrections={"primary_strand": "moon"},
            store=store,
            corrections_log=corrections_log,
        )


def test_connect_requires_name_and_description(store: AgentStore):
    with pytest.raises(AgentIntakeError):
        connect_agent("", "chatgpt", "Helps me write.", store=store)
    with pytest.raises(AgentIntakeError):
        connect_agent("Bot", "chatgpt", "  ", store=store)


def test_schema_round_trip():
    result = sort("Cold Email Writer", FIXTURES[0][1])
    agent = ConnectedAgent(
        id="abc",
        name="Cold Email Writer",
        source_platform="chatgpt",
        description="redacted",
        instructions=None,
        examples=[],
        sort=result,
        status="pending_review",
        created_at="2026-10-12T00:00:00+00:00",
    )
    restored = ConnectedAgent.from_dict(agent.to_dict())
    assert restored == agent
    assert restored.sort.primary_strand == "word"


def test_multi_frame_weights():
    # An agent with strong signals in two strands trains both, not just the top.
    result = sort(
        "Negotiation Coach",
        "It coaches me through difficult conversations and writes brilliant "
        "follow-up emails. Helps with team leadership and drafting proposals.",
    )
    assert result.primary_strand in ("people", "word")
    assert len(result.strand_weights) >= 2, (
        f"expected multi-strand weights, got {result.strand_weights}"
    )
    assert "people" in result.strand_weights
    assert "word" in result.strand_weights
    # weights survive the round trip
    restored = SortResult.from_dict(result.to_dict())
    assert restored.strand_weights == result.strand_weights


# ---------------------------------------------------------------------------
# Share-link intake
# ---------------------------------------------------------------------------

def test_share_link_detect_chatgpt():
    from local_ai.agent_intake.share_link import detect_source
    src = detect_source("https://chatgpt.com/share/abc123-def456")
    assert src is not None and src.key == "chatgpt"
    src = detect_source("https://chatgpt.com/share/e/abc123")
    assert src is not None and src.key == "chatgpt"


def test_share_link_detect_claude():
    from local_ai.agent_intake.share_link import detect_source
    src = detect_source("https://claude.ai/share/abc123-def456")
    assert src is not None and src.key == "claude"


def test_share_link_rejects_unknown():
    from local_ai.agent_intake.share_link import detect_source, fetch_shared_conversation
    assert detect_source("https://example.com/foo") is None
    with pytest.raises(ValueError):
        fetch_shared_conversation("https://example.com/foo")


def test_share_link_parse_next_data():
    from local_ai.agent_intake.share_link import _parse_chatgpt
    html = '''
    <html><head><title>My GPT Chat</title></head><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"props": {"pageProps": {"messages": [
        {"role": "user", "text": "Write me a cold email"},
        {"role": "assistant", "text": "Here is a cold email template..."}
    ]}}}
    </script></body></html>
    '''
    conv = _parse_chatgpt("https://chatgpt.com/share/x", html)
    assert conv.source == "chatgpt"
    assert not conv.needs_browser
    roles = [m.role for m in conv.messages]
    assert "user" in roles and "assistant" in roles


def test_share_link_redacts_pii():
    from local_ai.agent_intake.share_link import _parse_chatgpt
    html = '''
    <html><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"messages": [{"role": "user", "text": "Contact me at jane@example.com please"}]}
    </script></body></html>
    '''
    conv = _parse_chatgpt("https://chatgpt.com/share/x", html)
    assert conv.messages
    assert "jane@example.com" not in conv.messages[0].text
    assert "[EMAIL]" in conv.messages[0].text


def test_share_link_needs_browser_when_empty():
    from local_ai.agent_intake.share_link import _parse_chatgpt
    html = '<html><head></head><body><div id="root"></div><script src="/app.js"></script></body></html>'
    conv = _parse_chatgpt("https://chatgpt.com/share/x", html)
    assert conv.needs_browser


# ---------------------------------------------------------------------------
# LLM sorter (primary engine, rule-based fallback)
# ---------------------------------------------------------------------------

def test_llm_sorter_falls_back_without_key(monkeypatch):
    from local_ai.agent_intake import sorter_llm
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result, engine = sorter_llm.sort_primary(
        "Writer", "It helps me write cold emails with a clear process."
    )
    assert engine == "rule_based"
    assert result.primary_strand == "word"


def test_llm_sorter_parses_claims(monkeypatch):
    import json
    from local_ai.agent_intake import sorter_llm
    fake_response = json.dumps({
        "claims": [
            {"strand": "self", "score": 0.9, "reasoning": "philosophical judgment throughout"},
            {"strand": "word", "score": 0.6, "reasoning": "refines writing voice"},
            {"strand": "people", "score": 0.4, "reasoning": "relational exploration"},
            {"strand": "number", "score": 0.0, "reasoning": "no data here"},
            {"strand": "image", "score": 0.0, "reasoning": "passing"},
            {"strand": "sound", "score": 0.0, "reasoning": "passing"},
            {"strand": "body", "score": 0.0, "reasoning": "passing"},
        ],
        "kind": "talent",
        "kind_reasoning": "intuition and taste language",
    })
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "local_ai.providers.anthropic.generate", lambda *a, **k: fake_response
    )
    result = sorter_llm.sort_with_llm("Wishcraft", "philosophical partner")
    assert result.primary_strand == "self"
    assert result.kind == "talent"
    # multi-frame: self + word + people all above threshold
    assert set(result.strand_weights) == {"self", "word", "people"}
    assert len(result.claims) == 7


def test_llm_sorter_invalid_kind_defaults_undecided(monkeypatch):
    import json
    from local_ai.agent_intake import sorter_llm
    fake_response = json.dumps({
        "claims": [{"strand": "word", "score": 0.8, "reasoning": "writing"}],
        "kind": "superpower",
        "kind_reasoning": "x",
    })
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "local_ai.providers.anthropic.generate", lambda *a, **k: fake_response
    )
    result = sorter_llm.sort_with_llm("X", "writing")
    assert result.kind == "undecided"
    assert len(result.claims) == 7  # missing strands filled as passes


# ---------------------------------------------------------------------------
# Project mining
# ---------------------------------------------------------------------------

def test_project_miner_parses_llm_json(monkeypatch):
    import json
    from local_ai.agent_intake import project_miner as pm
    fake = json.dumps({
        "initiatives": [
            {"title": "Become a published philosopher", "brief": "body of work",
             "source_quote": "philosophy", "project_titles": ["Write the book"]},
        ],
        "projects": [
            {"title": "Write the book", "goal": "finish draft", "status_hint": "in progress",
             "source_quote": "my novel", "initiative_title": "Become a published philosopher",
             "tasks": [
                 {"title": "Outline chapter 3", "detail": "", "source_quote": "chapter 3"}]},
        ],
        "standalone_tasks": [
            {"title": "Summarize the doc", "detail": "", "source_quote": "please summarize"},
        ],
        "ideas": [
            {"title": "A podcast on thresholds", "detail": "maybe someday", "source_quote": "podcast"},
        ],
    })
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("local_ai.providers.anthropic.generate", lambda *a, **k: fake)
    result = pm.mine_projects("my novel ... please summarize the doc")
    assert result.engine == "anthropic"
    assert len(result.initiatives) == 1
    assert result.initiatives[0].project_titles == ["Write the book"]
    assert len(result.projects) == 1
    assert result.projects[0].title == "Write the book"
    assert result.projects[0].initiative_title == "Become a published philosopher"
    assert len(result.projects[0].tasks) == 1
    assert len(result.standalone_tasks) == 1
    assert len(result.ideas) == 1
    # VE payload mapping
    pc = result.projects[0].to_project_create(initiative_id="init-1")
    assert pc["initiative_id"] == "init-1" and pc["title"] == "Write the book"
    ic = result.initiatives[0].to_initiative_create()
    assert ic["title"] == "Become a published philosopher"


def test_project_miner_empty_transcript():
    from local_ai.agent_intake.project_miner import mine_projects
    result = mine_projects("   ")
    assert result.projects == [] and result.standalone_tasks == []


def test_project_miner_rule_fallback_without_key(monkeypatch):
    from local_ai.agent_intake.project_miner import mine_projects
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = mine_projects("USER: can you please summarize this long document for me today?")
    assert result.engine == "rule_based"
    assert len(result.standalone_tasks) >= 1


# ---------------------------------------------------------------------------
# Bookmarklet-extracted text intake
# ---------------------------------------------------------------------------

def test_connect_via_extracted_text(tmp_path, monkeypatch):
    from local_ai.agent_intake import pipeline as P
    from local_ai.agent_intake.store import AgentStore
    # rule-based fallback (no API key)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store = AgentStore(db_path=str(tmp_path / "t.db"))
    agent = P.connect_via_extracted_text(
        url="https://chatgpt.com/share/abc123",
        transcript="USER: help me write better\n\nASSISTANT: tell me about your voice",
        title="Writing help",
        store=store,
    )
    assert agent.source_platform == "chatgpt_share"
    assert agent.status == "pending_review"
    assert len(agent.examples) >= 1


def test_connect_via_extracted_text_requires_transcript(tmp_path):
    from local_ai.agent_intake import pipeline as P
    from local_ai.agent_intake.store import AgentStore
    from local_ai.agent_intake.pipeline import AgentIntakeError
    import pytest
    store = AgentStore(db_path=str(tmp_path / "t.db"))
    with pytest.raises(AgentIntakeError):
        P.connect_via_extracted_text(url="https://chatgpt.com/share/abc", transcript="  ", store=store)


def test_split_transcript():
    from local_ai.agent_intake.pipeline import _split_transcript
    chunks = _split_transcript("USER: one\n\nASSISTANT: two\n\nUSER: three")
    assert len(chunks) == 3
    assert chunks[0].startswith("USER:")


# ---------------------------------------------------------------------------
# Render jobs — registered browsers instead of browser_required dead-ends
# ---------------------------------------------------------------------------

def test_render_job_lifecycle(tmp_path):
    from local_ai.agent_intake.render_jobs import RenderJobStore
    rs = RenderJobStore(db_path=str(tmp_path / "rj.db"))
    job = rs.create("https://chatgpt.com/share/abc", agent_id="a1")
    assert job.status == "pending"

    claimed = rs.next_pending("worker-1")
    assert claimed and claimed.id == job.id
    assert claimed.status == "claimed"
    assert claimed.claimed_by == "worker-1"

    # second worker gets nothing while it's claimed
    assert rs.next_pending("worker-2") is None

    done = rs.complete(job.id, "USER: hello\n\nASSISTANT: hi", title="Test chat")
    assert done.status == "completed"
    assert done.transcript.startswith("USER:")

    assert rs.pending_count() == 0


def test_share_link_queues_render_job_instead_of_error(tmp_path, monkeypatch):
    from local_ai.agent_intake import pipeline as P
    from local_ai.agent_intake.render_jobs import RenderJobStore
    from local_ai.agent_intake.share_link import SharedConversation

    monkeypatch.setattr(
        P, "fetch_shared_conversation",
        lambda url: SharedConversation(source="chatgpt", url=url, title="T",
                                       messages=[], needs_browser=True),
    )
    rs = RenderJobStore(db_path=str(tmp_path / "rj2.db"))
    agent, job = P.connect_via_share_link("https://chatgpt.com/share/abc", render_store=rs)
    assert agent is None
    assert job is not None and job.status == "pending"
    assert job.url == "https://chatgpt.com/share/abc"


def test_resume_from_render(tmp_path, monkeypatch):
    from local_ai.agent_intake import pipeline as P
    from local_ai.agent_intake.render_jobs import RenderJobStore
    from local_ai.agent_intake.store import AgentStore

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rs = RenderJobStore(db_path=str(tmp_path / "rj3.db"))
    store = AgentStore(db_path=str(tmp_path / "t.db"))
    job = rs.create("https://chatgpt.com/share/abc")
    rs.complete(job.id, "USER: help me write\n\nASSISTANT: sure", title="Writing")

    agent = P.resume_from_render(job.id, store=store, render_store=rs)
    assert agent.status == "pending_review"
    assert agent.source_platform == "chatgpt_share"
    assert len(agent.examples) >= 1


# ---------------------------------------------------------------------------
# Multi-user hardening: per-user stores, render jobs, and consent scopes
# ---------------------------------------------------------------------------

def _agent(name: str) -> ConnectedAgent:
    return ConnectedAgent(
        id=f"a-{name}",
        name=name,
        source_platform="manual",
        description="test agent",
        instructions=None,
        examples=[],
        sort=None,
        status="pending_review",
        created_at="2026-10-13T00:00:00",
    )


def test_store_isolates_users(tmp_path):
    db = str(tmp_path / "agents.db")
    sa = AgentStore(db_path=db, user_id="user-a")
    sb = AgentStore(db_path=db, user_id="user-b")
    sa.save(_agent("alice-agent"))
    sb.save(_agent("bob-agent"))

    assert [a.name for a in sa.list_all()] == ["alice-agent"]
    assert [a.name for a in sb.list_all()] == ["bob-agent"]
    assert [a.name for a in sa.list_pending()] == ["alice-agent"]
    # cross-user get/update is denied
    assert sa.get("a-bob-agent") is None
    assert sb.update_status("a-alice-agent", "active") is False
    assert sa.update_status("a-alice-agent", "active") is True


def test_store_unscoped_sees_all(tmp_path):
    """Local single-user mode (no user_id) keeps the old behavior."""
    db = str(tmp_path / "agents.db")
    AgentStore(db_path=db, user_id="user-a").save(_agent("x"))
    assert len(AgentStore(db_path=db).list_all()) == 1


def test_pipeline_tags_agent_owner(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store = AgentStore(db_path=str(tmp_path / "t.db"), user_id="user-a")
    agent = connect_agent(
        name="Writer", platform="manual", description="writes things", store=store
    )
    assert agent.user_id == "user-a"
    assert store.get(agent.id) is not None
    assert AgentStore(db_path=str(tmp_path / "t.db"), user_id="user-b").get(agent.id) is None


def test_render_jobs_isolated_by_user(tmp_path):
    from local_ai.agent_intake.render_jobs import RenderJobStore

    rs = RenderJobStore(db_path=str(tmp_path / "rj.db"))
    ja = rs.create("https://chatgpt.com/share/a", user_id="user-a")
    jb = rs.create("https://chatgpt.com/share/b", user_id="user-b")

    # each user only sees their own jobs
    got_a = rs.next_pending("w1", user_id="user-a")
    assert got_a is not None and got_a.id == ja.id
    got_b = rs.next_pending("w1", user_id="user-b")
    assert got_b is not None and got_b.id == jb.id

    # completing another user's job is denied
    assert rs.complete(jb.id, "USER: x", user_id="user-a") is None
    done = rs.complete(ja.id, "USER: hello", user_id="user-a")
    assert done is not None and done.status == "completed"

    # status polling is owner-only
    assert rs.get(jb.id, user_id="user-a") is None
    assert rs.get(jb.id, user_id="user-b") is not None


def test_scopes_are_per_user(tmp_path, monkeypatch):
    from local_ai.identity import service as svc
    from local_ai.identity.scopes import check_scope
    from local_ai.identity.store import IdentityStore

    monkeypatch.setenv("ZENAF_DATA_DIR", str(tmp_path))
    store = IdentityStore()
    assert check_scope("train:self", store=store, user_id="u1") is False
    svc.grant_scope("train:self", store=store, user_id="u1")
    assert check_scope("train:self", store=store, user_id="u1") is True
    assert check_scope("train:self", store=store, user_id="u2") is False
    # revoking for u1 doesn't touch a global grant
    svc.grant_scope("train:self", store=store)  # global
    svc.revoke_scope("train:self", store=store, user_id="u1")
    assert check_scope("train:self", store=store, user_id="u2") is True


def test_intake_chat_routes_paste_to_pipeline(tmp_path, monkeypatch):
    from local_ai.agent_intake import intake_chat as ichat

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ZENAF_DATA_DIR", str(tmp_path))
    long_text = "USER: help me plan my novel\n\nASSISTANT: sure, let's outline it\n\n" * 30
    out = ichat.handle_message(long_text, user_id="user-a")
    assert out["agent"] is not None
    assert out["agent"]["user_id"] == "user-a"
    assert "review" in out["reply"].lower()
