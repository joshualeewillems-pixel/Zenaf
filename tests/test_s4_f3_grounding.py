"""S4 F3 fix: grounded key lines, tiers, selection, migration, citation guard.

Governing law (audit Parts XII–XIII, ratified 2026-10-24):
- Personal artifacts DISTILL, never invent. A key line presented as the
  user's words must be a verbatim span of their material, with source.
- No synthesis in disguise. A Zenaf-written line is never a quotation.
- Adoption is not authorship of wording. Choosing among options is
  user decision-making; the wording keeps the tier it was born with
  unless the user rewrote it.
- If no verbatim passage exists, the quote is OMITTED — never forced.

The LLM is mocked throughout (no network); strand analysis runs for real.
"""

from __future__ import annotations

import ast
import json

import pytest

from local_ai.pipeline import service as pipe
from local_ai.pipeline import stories, tiers
from local_ai.pipeline.store import PipelineStore
from local_ai.pipeline.tier_migration import migrate_story_tiers
from local_ai.provenance.store import ProvenanceStore

ALICE = "user-alice"

JOURNEY_TEXT = (
    "I left my job back in March and started something of my own. The first "
    "months were hard — I failed twice, felt lost and overwhelmed by doubt. "
    "But I kept going, and I finally learned what I actually want from work. "
    "Now I feel grateful for the struggle; it made me stronger and wiser."
)

VERBATIM = "Now I feel grateful for the struggle; it made me stronger and wiser."
VERBATIM_2 = "But I kept going, and I finally learned what I actually want from work."
COMPOSED = "The struggle taught me what I actually want."

PACK_JSON = {
    "pack_title": "Leaving to Begin — song",
    "prompts": ["Verse one... chorus...", "blues, slow tempo"],
    "style_line": "old blues",
    "negative_prompt": "no pop clichés",
}


def _story_json(candidates=None, **overrides):
    data = {
        "title": "Leaving to Begin",
        "narrative": "You left the safe job in March. The first months were hard.",
        "key_line_candidates": candidates if candidates is not None else [],
    }
    data.update(overrides)
    return data


def _fake_generate_for(story_data):
    def _fake(api_key, prompt, **kwargs):
        if "prompt pack" in prompt.lower():
            return json.dumps(PACK_JSON)
        return json.dumps(story_data)

    return _fake


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    import local_ai.providers.meta as meta

    monkeypatch.setattr(meta, "generate", _fake_generate_for(_story_json([VERBATIM])))
    pstore = PipelineStore(tmp_path / "pipe.db")
    prov = ProvenanceStore(tmp_path / "prov.db")
    yield pstore, prov
    pstore.close()
    prov.close()


def _entry_and_story(stores, entry_text=JOURNEY_TEXT):
    pstore, prov = stores
    created = pipe.create_journal_entry(pstore, prov, ALICE, entry_text)
    entry_id = created["entry"]["entry_id"]
    result = pipe.make_story(pstore, prov, ALICE, entry_id)
    return entry_id, result


# -- tier vocabulary + verbatim check ------------------------------------------


def test_verbatim_exact_and_whitespace_only():
    assert tiers.is_verbatim_span(VERBATIM, JOURNEY_TEXT)
    assert tiers.is_verbatim_span(
        "  Now   I feel grateful\nfor the struggle; it made me stronger and wiser. ",
        JOURNEY_TEXT,
    )
    assert (
        tiers.verified_span(
            "  Now   I feel grateful\nfor the struggle; it made me stronger and wiser. ",
            JOURNEY_TEXT,
        )
        == VERBATIM
    )


def test_near_quote_is_not_a_quote():
    # Composed sentence, rewording, case change, punctuation change:
    # none of these is verbatim, however close.
    assert not tiers.is_verbatim_span(COMPOSED, JOURNEY_TEXT)
    assert not tiers.is_verbatim_span(
        "Now I feel grateful for the struggle, it made me stronger and wiser.",
        JOURNEY_TEXT,
    )
    assert not tiers.is_verbatim_span(
        "now I feel grateful for the struggle; it made me stronger and wiser.",
        JOURNEY_TEXT,
    )
    assert tiers.verified_span(COMPOSED, JOURNEY_TEXT) is None


def test_no_evidence_tier_exists():
    assert "evidence" not in tiers.ALL_TIERS
    assert tiers.QUOTE_TIERS == {"certified"}


# -- extract_story ---------------------------------------------------------------


def test_verbatim_candidate_accepted_composed_dropped(monkeypatch):
    import local_ai.providers.meta as meta

    monkeypatch.setattr(
        meta, "generate", _fake_generate_for(_story_json([COMPOSED, VERBATIM]))
    )
    result = stories.extract_story(JOURNEY_TEXT)
    assert result["key_line"] == VERBATIM
    assert result["key_line_tier"] == "certified"
    assert result["key_line_candidates"] == [VERBATIM]


def test_no_candidate_succeeds_with_null_key_line(monkeypatch):
    import local_ai.providers.meta as meta

    monkeypatch.setattr(meta, "generate", _fake_generate_for(_story_json([])))
    result = stories.extract_story(JOURNEY_TEXT)
    assert result["key_line"] is None
    assert result["key_line_tier"] is None
    assert result["key_line_candidates"] == []


def test_composed_only_becomes_null_not_forced(monkeypatch):
    import local_ai.providers.meta as meta

    monkeypatch.setattr(
        meta, "generate", _fake_generate_for(_story_json([COMPOSED]))
    )
    result = stories.extract_story(JOURNEY_TEXT)
    assert result["key_line"] is None


def test_legacy_key_line_field_is_verified_not_trusted(monkeypatch):
    import local_ai.providers.meta as meta

    monkeypatch.setattr(
        meta,
        "generate",
        _fake_generate_for(_story_json([], key_line=VERBATIM)),
    )
    assert stories.extract_story(JOURNEY_TEXT)["key_line"] == VERBATIM
    monkeypatch.setattr(
        meta,
        "generate",
        _fake_generate_for(_story_json([], key_line=COMPOSED)),
    )
    assert stories.extract_story(JOURNEY_TEXT)["key_line"] is None


def test_missing_title_or_narrative_still_raises(monkeypatch):
    import local_ai.providers.meta as meta

    monkeypatch.setattr(
        meta, "generate", _fake_generate_for(_story_json([], title=""))
    )
    with pytest.raises(ValueError):
        stories.extract_story(JOURNEY_TEXT)
    monkeypatch.setattr(
        meta, "generate", _fake_generate_for(_story_json([], narrative=""))
    )
    with pytest.raises(ValueError):
        stories.extract_story(JOURNEY_TEXT)


def test_long_verbatim_span_is_never_truncated(monkeypatch):
    long_sentence = " ".join(["word"] * 80) + "."
    entry = f"Intro here. {long_sentence} Outro here."
    import local_ai.providers.meta as meta

    monkeypatch.setattr(
        meta, "generate", _fake_generate_for(_story_json([long_sentence]))
    )
    result = stories.extract_story(entry)
    assert result["key_line"] == long_sentence
    assert len(result["key_line"]) > 280


# -- make_story + quote-card gate ------------------------------------------------


def test_make_story_records_tier_candidates_source(stores):
    pstore, prov = stores
    entry_id, result = _entry_and_story(stores)
    content = result["content"]
    assert content["key_line"] == VERBATIM
    assert content["key_line_tier"] == "certified"
    assert content["key_line_candidates"] == [VERBATIM]
    artifact = result["artifact"]
    data = json.loads(artifact["description"])
    assert data["key_line_tier"] == "certified"
    assert data["key_line_source"]["entry_id"] == entry_id
    assert data["key_line_selection"] is None
    assert pstore.get_entry(entry_id)["storified"] == 1


def test_make_story_without_line_succeeds(stores, monkeypatch):
    import local_ai.providers.meta as meta

    monkeypatch.setattr(meta, "generate", _fake_generate_for(_story_json([])))
    pstore, prov = stores
    created = pipe.create_journal_entry(pstore, prov, ALICE, JOURNEY_TEXT)
    result = pipe.make_story(pstore, prov, ALICE, created["entry"]["entry_id"])
    assert result["content"]["key_line"] is None
    assert result["content"]["key_line_tier"] is None


def test_quote_card_gate_certified_only(stores):
    pstore, prov = stores
    _, result = _entry_and_story(stores)
    story_id = result["artifact"]["artifact_id"]
    card = pipe.make_quote_card(pstore, prov, ALICE, story_id, badge=False)
    assert card["artifact"]["title"].startswith("Quote card")
    card_data = json.loads(card["artifact"]["description"])
    assert card_data["key_line_tier"] == "certified"
    assert card_data["key_line"] == VERBATIM


def test_quote_card_refuses_no_line(stores, monkeypatch):
    import local_ai.providers.meta as meta

    monkeypatch.setattr(meta, "generate", _fake_generate_for(_story_json([])))
    pstore, prov = stores
    created = pipe.create_journal_entry(pstore, prov, ALICE, JOURNEY_TEXT)
    result = pipe.make_story(pstore, prov, ALICE, created["entry"]["entry_id"])
    with pytest.raises(ValueError):
        pipe.make_quote_card(
            pstore, prov, ALICE, result["artifact"]["artifact_id"], badge=False
        )


def _legacy_story_artifact(prov, description):
    """Mint a pre-tier story artifact exactly as the old code did."""
    artifact = prov.create_artifact(
        creator_user_id=ALICE,
        custodian_user_id=ALICE,
        title="Legacy story",
        description=json.dumps(description),
        modality="text",
        visibility="unlisted",
        remix_policy="open",
        imported=False,
        creator_declared=True,
    )
    return artifact


def test_quote_card_refuses_uncertified_legacy_line(stores):
    pstore, prov = stores
    artifact = _legacy_story_artifact(
        prov, {"narrative": "old story", "key_line": COMPOSED}
    )
    with pytest.raises(ValueError):
        pipe.make_quote_card(
            pstore, prov, ALICE, artifact["artifact_id"], badge=False
        )


# -- selection ---------------------------------------------------------------------


def test_choose_verbatim_candidate(stores, monkeypatch):
    import local_ai.providers.meta as meta

    monkeypatch.setattr(
        meta,
        "generate",
        _fake_generate_for(_story_json([VERBATIM, VERBATIM_2])),
    )
    pstore, prov = stores
    _, result = _entry_and_story(stores)
    story_id = result["artifact"]["artifact_id"]
    chosen = pipe.choose_key_line(
        pstore, prov, ALICE, story_id, candidate=VERBATIM_2
    )
    content = chosen["content"]
    assert content["key_line"] == VERBATIM_2
    assert content["key_line_tier"] == "certified"
    sel = content["key_line_selection"]
    assert sel["kind"] == "chosen_verbatim"
    assert sel["chosen"] == VERBATIM_2
    assert sel["alternatives"] == [VERBATIM, VERBATIM_2]
    assert sel["attribution"] == "verbatim from your journal entry"
    # A certified choice still mints a card.
    pipe.make_quote_card(pstore, prov, ALICE, story_id, badge=False)


def test_choose_non_candidate_rejected(stores):
    pstore, prov = stores
    _, result = _entry_and_story(stores)
    with pytest.raises(ValueError):
        pipe.choose_key_line(
            pstore, prov, ALICE, result["artifact"]["artifact_id"],
            candidate="A line from nowhere",
        )


def test_choose_edit_is_user_authored_not_a_span(stores):
    pstore, prov = stores
    _, result = _entry_and_story(stores)
    story_id = result["artifact"]["artifact_id"]
    edited = "Grateful for the struggle, on my own terms."
    chosen = pipe.choose_key_line(
        pstore, prov, ALICE, story_id, edited_text=edited
    )
    content = chosen["content"]
    assert content["key_line"] == edited
    assert content["key_line_tier"] == "user_authored"
    assert content["key_line_selection"]["kind"] == "edited"
    assert content["key_line_selection"]["edited_from"] == VERBATIM
    assert content["key_line_source"] == {}
    # User-authored is the user's words, but NOT a quotation from the
    # entry — so it must not mint as a quote card.
    with pytest.raises(ValueError):
        pipe.make_quote_card(pstore, prov, ALICE, story_id, badge=False)


def test_choose_adopted_never_a_quotation(stores):
    pstore, prov = stores
    _, result = _entry_and_story(stores)
    story_id = result["artifact"]["artifact_id"]
    chosen = pipe.choose_key_line(
        pstore, prov, ALICE, story_id, adopted_text=COMPOSED
    )
    content = chosen["content"]
    assert content["key_line_tier"] == "adopted"
    assert (
        content["key_line_selection"]["attribution"]
        == "chosen by you from Zenaf's options"
    )
    with pytest.raises(ValueError):
        pipe.make_quote_card(pstore, prov, ALICE, story_id, badge=False)


def test_choose_requires_exactly_one_input(stores):
    pstore, prov = stores
    _, result = _entry_and_story(stores)
    story_id = result["artifact"]["artifact_id"]
    with pytest.raises(ValueError):
        pipe.choose_key_line(pstore, prov, ALICE, story_id)
    with pytest.raises(ValueError):
        pipe.choose_key_line(
            pstore, prov, ALICE, story_id,
            candidate=VERBATIM, edited_text="x",
        )


# -- packs with a null key line ------------------------------------------------------


def test_packs_tolerate_null_key_line(monkeypatch):
    from local_ai.pipeline import packs

    captured: dict[str, str] = {}

    def _capture(api_key, prompt, **kwargs):
        captured["prompt"] = prompt
        return json.dumps(PACK_JSON)

    import local_ai.providers.meta as meta

    monkeypatch.setattr(meta, "generate", _capture)
    packs.generate_pack(
        {
            "title": "T",
            "narrative": "N",
            "key_line": None,
            "archetype_cast": [],
        },
        "song",
    )
    assert "None" not in captured["prompt"]


# -- PipelineStore lookup ---------------------------------------------------------------


def test_get_entry_by_artifact_id(stores):
    pstore, prov = stores
    created = pipe.create_journal_entry(pstore, prov, ALICE, JOURNEY_TEXT)
    entry = created["entry"]
    found = pstore.get_entry_by_artifact_id(entry["artifact_id"])
    assert found is not None and found["entry_id"] == entry["entry_id"]
    assert pstore.get_entry_by_artifact_id("no-such-artifact") is None


# -- migration ----------------------------------------------------------------------------


def _legacy_pair(stores, entry_text, line, link=True):
    """A legacy (pre-tier) story artifact + optional link to its entry."""
    pstore, prov = stores
    created = pipe.create_journal_entry(pstore, prov, ALICE, entry_text)
    entry = created["entry"]
    story = _legacy_story_artifact(
        prov, {"narrative": "legacy story", "key_line": line}
    )
    if link:
        prov.add_link(story["artifact_id"], entry["artifact_id"], "linked")
    return entry, story


def test_migration_certifies_verbatim_and_card_inherits(stores):
    pstore, prov = stores
    entry, story = _legacy_pair(stores, JOURNEY_TEXT, VERBATIM)
    card = _legacy_story_artifact(prov, {"key_line": VERBATIM})
    prov.add_link(card["artifact_id"], story["artifact_id"], "linked")
    result = migrate_story_tiers(pstore, prov, dry_run=False)
    assert result["counts"]["stories_certified"] == 1
    assert result["counts"]["cards_certified"] == 1
    data = json.loads(prov.get_artifact(story["artifact_id"])["description"])
    assert data["key_line_tier"] == "certified"
    assert data["key_line_source"]["entry_id"] == entry["entry_id"]
    card_data = json.loads(prov.get_artifact(card["artifact_id"])["description"])
    assert card_data["key_line_tier"] == "certified"


def test_migration_dramatizes_invented_line(stores):
    pstore, prov = stores
    _, story = _legacy_pair(stores, JOURNEY_TEXT, COMPOSED)
    card = _legacy_story_artifact(prov, {"key_line": COMPOSED})
    prov.add_link(card["artifact_id"], story["artifact_id"], "linked")
    result = migrate_story_tiers(pstore, prov, dry_run=False)
    assert result["counts"]["stories_dramatization"] == 1
    assert result["counts"]["cards_dramatization"] == 1
    data = json.loads(prov.get_artifact(story["artifact_id"])["description"])
    assert data["key_line_tier"] == "dramatization"
    assert data["key_line"] == COMPOSED  # record keeps the line, re-tiered
    assert "tier_note" in data


def test_migration_uncheckable_defaults_to_dramatization(stores):
    pstore, prov = stores
    _, story = _legacy_pair(stores, JOURNEY_TEXT, VERBATIM, link=False)
    result = migrate_story_tiers(pstore, prov, dry_run=False)
    assert result["counts"]["stories_dramatization"] == 1
    data = json.loads(prov.get_artifact(story["artifact_id"])["description"])
    assert data["key_line_tier"] == "dramatization"


def test_migration_dry_run_writes_nothing(stores):
    pstore, prov = stores
    _, story = _legacy_pair(stores, JOURNEY_TEXT, VERBATIM)
    result = migrate_story_tiers(pstore, prov, dry_run=True)
    assert result["counts"]["stories_certified"] == 1
    data = json.loads(prov.get_artifact(story["artifact_id"])["description"])
    assert "key_line_tier" not in data
    assert "tier_migrated" not in data


def test_migration_idempotent(stores):
    pstore, prov = stores
    _, story = _legacy_pair(stores, JOURNEY_TEXT, VERBATIM)
    first = migrate_story_tiers(pstore, prov, dry_run=False)
    assert first["counts"]["stories_certified"] == 1
    second = migrate_story_tiers(pstore, prov, dry_run=False)
    assert second["counts"]["stories_already_migrated"] == 1
    assert second["counts"]["stories_certified"] == 0


def test_migration_no_line_story(stores):
    pstore, prov = stores
    _, story = _legacy_pair(stores, JOURNEY_TEXT, "")
    result = migrate_story_tiers(pstore, prov, dry_run=False)
    assert result["counts"]["stories_no_line"] == 1


# -- citation guard ---------------------------------------------------------------------------


def test_review_claims_never_import_pipeline_or_provenance():
    """Story artifacts must never become claim evidence. Pin the current
    architecture: the claim builders import neither the pipeline nor
    the provenance registry, so no story artifact can reach them."""
    path = "local_ai/agent_intake/review_claims.py"
    tree = ast.parse(open(path, encoding="utf-8").read())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any(
        m == "local_ai.pipeline" or m.startswith("local_ai.pipeline.")
        for m in imported
    )
    assert not any(
        m == "local_ai.provenance" or m.startswith("local_ai.provenance.")
        for m in imported
    )


def test_story_record_tier_is_never_evidence(stores):
    _, result = _entry_and_story(stores)
    data = json.loads(result["artifact"]["description"])
    assert data["key_line_tier"] in tiers.ALL_TIERS | {None}
    assert data["key_line_tier"] != "evidence"


# -- route -------------------------------------------------------------------------------------


def _asgi_call(app, method: str, path: str, body: dict | None):
    """Drive one request through the ASGI app (no httpx/TestClient)."""
    import asyncio

    raw = json.dumps(body).encode() if body is not None else b""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(raw)).encode()),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    messages: list[dict] = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    payload = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    return start["status"], json.loads(payload.decode() or "{}")


def test_choose_key_line_route(stores, tmp_path, monkeypatch):
    from fastapi import FastAPI

    import api.routes.pipeline_routes as pipe_routes
    from api.routes.auth_routes import get_current_user

    pstore, prov = stores
    monkeypatch.setattr(pipe_routes, "_store", lambda: prov)
    monkeypatch.setattr(pipe_routes, "_pstore", lambda: pstore)
    app = FastAPI()
    app.include_router(pipe_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": ALICE}

    _, result = _entry_and_story(stores)
    story_id = result["artifact"]["artifact_id"]
    status, body = _asgi_call(
        app,
        "POST",
        "/pipeline/story/key-line",
        {"story_id": story_id, "candidate": VERBATIM},
    )
    assert status == 200, body
    assert body["content"]["key_line_tier"] == "certified"
    assert body["content"]["key_line_selection"]["kind"] == "chosen_verbatim"

    status, _ = _asgi_call(
        app,
        "POST",
        "/pipeline/story/key-line",
        {"story_id": story_id, "candidate": VERBATIM, "edited_text": "x"},
    )
    assert status == 422
