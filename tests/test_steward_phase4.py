"""Narrative Steward Phase 4 — tier enforcement completion (audit S4).

Phase 4 verifies and completes work the S0/S4 increments started:
- Registry-level tier enforcement: the provenance ``tier`` column
  (verified absent, added additively here), Tier-D inadmissibility
  by ref-kind type on the derivation, claims, and thread-evidence
  paths — never by prompt wording.
- Key-line fallback per Part XII (T1): verbatim span with source, or
  omitted; story succeeds without a line; quote cards still refuse
  without a certified line.
- M1 retroactive re-label migration: verbatim → certified with
  source; not verbatim or uncheckable → dramatization, quotation
  presentation removed. Idempotent, fixture-tested, never touches
  Tier-E, never certifies by guess. M1 is an explicit operator run
  (dry run first) — it does NOT run at boot or deploy.
- Selection-as-license (Part XIII): choice + alternatives +
  attribution recorded; adopted ≠ authored kept in separate ledgers
  (word provenance vs choice provenance); edited-then-chosen =
  user-authored, NOT a verbatim span. Rejected options are NOT
  recorded (arch §6.7 default).
- T2: a rejected fitting never reappears in context and is not
  re-proposed without new evidence + user reopen.
- Scene renderer disposition (Part IX): RETIRED — verified zero
  production callers, no unique behavior beyond the minting
  pipeline's story path.
- Journal→story pipeline tier-complete: pipeline artifacts are
  Tier-D only and inadmissible as evidence; the pipeline never
  becomes a thread writer.

The LLM is mocked throughout (no network).
"""

from __future__ import annotations

import ast
import json
import sqlite3

import pytest

from local_ai.narrative import NarrativeStore, SourceRef
from local_ai.narrative.derivation import EvidenceItem, derive_batch
from local_ai.narrative.refs import InadmissibleEvidenceError
from local_ai.pipeline import service as pipe
from local_ai.pipeline import stories, tiers
from local_ai.pipeline.store import PipelineStore
from local_ai.pipeline.tier_migration import migrate_story_tiers
from local_ai.provenance.store import ProvenanceStore

USER = "user-alice"
JOURNEY_TEXT = (
    "I left my job back in March and started something of my own. The first "
    "months were hard — I failed twice, felt lost and overwhelmed by doubt. "
    "But I kept going, and I finally learned what I actually want from work. "
    "Now I feel grateful for the struggle; it made me stronger and wiser."
)
VERBATIM = "Now I feel grateful for the struggle; it made me stronger and wiser."
VERBATIM_2 = "But I kept going, and I finally learned what I actually want from work."
COMPOSED = "The struggle taught me what I actually want."
LENS_ID = "descent_and_return"

PACK_JSON = {
    "pack_title": "Leaving to Begin — song",
    "prompts": ["Verse one... chorus...", "blues, slow tempo"],
    "style_line": "old blues",
    "negative_prompt": "no pop clichés",
}

FLAGS_ON = {"steward_derivation": True, "steward_coordination": True}
EVENT_REF = SourceRef(kind="event", ref_id="evt-8", evidence_kind="entity_ref")
CLAIM_REF = SourceRef(kind="claim", ref_id="claim-9", evidence_kind="quote")
DRAMA_REF = SourceRef(kind="story_artifact", ref_id="story-1")
SCENE_REF = SourceRef(kind="scene_render", ref_id="scene-1")
READING_REF = SourceRef(kind="reading", ref_id="rdg-elsewhere")


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


@pytest.fixture()
def nstore(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _entry_and_story(stores, entry_text=JOURNEY_TEXT):
    pstore, prov = stores
    created = pipe.create_journal_entry(pstore, prov, USER, entry_text)
    entry_id = created["entry"]["entry_id"]
    result = pipe.make_story(pstore, prov, USER, entry_id)
    return entry_id, result


def _perm_conn(flags_by_user):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in flags_by_user.items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
            (user_id, json.dumps(flags), "2026-10-31T00:00:00Z"),
        )
    conn.commit()
    return conn


def _no_asp(uid):
    return None


# -- provenance tier column -----------------------------------------------------


def test_tier_column_exists_on_fresh_db(tmp_path):
    prov = ProvenanceStore(tmp_path / "prov.db")
    try:
        cols = {
            row[1]  # PRAGMA table_info: (cid, name, type, ...)
            for row in sqlite3.connect(str(tmp_path / "prov.db")).execute(
                "PRAGMA table_info(provenance_artifacts)"
            )
        }
        assert "tier" in cols
        artifact = prov.create_artifact(
            creator_user_id=USER, custodian_user_id=USER, title="t"
        )
        assert artifact["tier"] is None  # unlabeled, never read as a tier
        labeled = prov.create_artifact(
            creator_user_id=USER,
            custodian_user_id=USER,
            title="t2",
            tier="dramatization",
        )
        assert labeled["tier"] == "dramatization"
        assert prov.get_artifact(labeled["artifact_id"])["tier"] == "dramatization"
    finally:
        prov.close()


def test_tier_column_added_to_pre_phase4_db(tmp_path):
    """A DB created with the old schema gains the column on open."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE provenance_artifacts ("
        "artifact_id TEXT PRIMARY KEY, creator_user_id TEXT,"
        "custodian_user_id TEXT, created_at TEXT NOT NULL,"
        "title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',"
        "archetype_cast TEXT NOT NULL DEFAULT '[]', source_hash TEXT,"
        "modality TEXT NOT NULL DEFAULT 'image', phash TEXT, sha256 TEXT,"
        "visibility TEXT NOT NULL DEFAULT 'unlisted',"
        "remix_policy TEXT NOT NULL DEFAULT 'open',"
        "minted INTEGER NOT NULL DEFAULT 0, imported INTEGER NOT NULL DEFAULT 0,"
        "disputed INTEGER NOT NULL DEFAULT 0, creator_declared INTEGER NOT NULL DEFAULT 0,"
        "reach_cached REAL NOT NULL DEFAULT 0, reach_updated_at TEXT,"
        "c2pa_manifest BLOB, styled_by TEXT, variation_of TEXT)"
    )
    conn.execute(
        "INSERT INTO provenance_artifacts (artifact_id, created_at) VALUES ('a1', '2026-01-01')"
    )
    conn.commit()
    conn.close()
    prov = ProvenanceStore(db_path)
    try:
        row = prov.get_artifact("a1")
        assert row is not None and row["tier"] is None
        assert prov.update_artifact("a1", tier="evidence")["tier"] == "evidence"
    finally:
        prov.close()


def test_bad_provenance_tier_raises(tmp_path):
    prov = ProvenanceStore(tmp_path / "prov.db")
    try:
        with pytest.raises(ValueError):
            prov.create_artifact(
                creator_user_id=USER, custodian_user_id=USER, tier="quotation"
            )
    finally:
        prov.close()


# -- pipeline writes tier at creation --------------------------------------------


def test_pipeline_artifacts_carry_provenance_tier(stores):
    pstore, prov = stores
    created = pipe.create_journal_entry(pstore, prov, USER, JOURNEY_TEXT)
    entry_artifact = prov.get_artifact(created["entry"]["artifact_id"])
    assert entry_artifact["tier"] == "evidence"
    _, result = _entry_and_story(stores)
    story = prov.get_artifact(result["artifact"]["artifact_id"])
    assert story["tier"] == "dramatization"
    card = pipe.make_quote_card(
        pstore, prov, USER, result["artifact"]["artifact_id"], badge=False
    )
    assert prov.get_artifact(card["artifact"]["artifact_id"])["tier"] == "dramatization"
    packs = pipe.generate_packs(
        pstore, prov, USER, result["artifact"]["artifact_id"],
        modalities=["song"],
        answers={"modality": "song", "style": "blues", "tools": "Suno"},
        confirmed=True,
    )
    assert packs["packs"]
    for item in packs["packs"]:
        assert prov.get_artifact(item["artifact"]["artifact_id"])["tier"] == "dramatization"


# -- T1: key-line fallback end to end ----------------------------------------------


def test_t1_fixture_entry_story_and_card(stores, monkeypatch):
    """Every presented quotation is verbatim in the entry; the story
    succeeds without a line and the card still refuses without one."""
    import local_ai.providers.meta as meta

    pstore, prov = stores
    entry_id, result = _entry_and_story(stores)
    content = result["content"]
    assert content["key_line"] == VERBATIM
    assert tiers.is_verbatim_span(content["key_line"], JOURNEY_TEXT)
    assert content["key_line_tier"] == "certified"
    card = pipe.make_quote_card(
        pstore, prov, USER, result["artifact"]["artifact_id"], badge=False
    )
    card_data = json.loads(card["artifact"]["description"])
    assert card_data["key_line"] == VERBATIM
    assert card_data["key_line_tier"] == "certified"
    # The artifact record carries tier metadata on both axes: the
    # artifact is Tier D, the line is certified verbatim.
    assert prov.get_artifact(result["artifact"]["artifact_id"])["tier"] == "dramatization"

    monkeypatch.setattr(meta, "generate", _fake_generate_for(_story_json([])))
    created = pipe.create_journal_entry(pstore, prov, USER, JOURNEY_TEXT)
    no_line = pipe.make_story(
        pstore, prov, USER, created["entry"]["entry_id"]
    )
    assert no_line["content"]["key_line"] is None
    assert no_line["content"]["key_line_tier"] is None
    with pytest.raises(ValueError):
        pipe.make_quote_card(
            pstore, prov, USER, no_line["artifact"]["artifact_id"], badge=False
        )


# -- Tier-D inadmissibility, three paths -------------------------------------------


def test_thread_evidence_path_refuses_all_non_evidence_kinds(nstore):
    thread = nstore.create_thread(
        USER, origin="user_declared", title="T", evidence_refs=(EVENT_REF,)
    )
    for ref in (DRAMA_REF, SCENE_REF, READING_REF):
        with pytest.raises(InadmissibleEvidenceError):
            nstore.add_evidence(USER, thread.id, ref)
    assert len(nstore.evidence_for(USER, thread.id)) == 1


def test_derivation_path_yields_zero_citations_for_tier_d_text(nstore):
    """Tier-D text fed to the derivation path yields zero evidence
    citations — and spends zero generations (prefilter, by ref-kind)."""

    def _must_not_generate(*args, **kwargs):
        raise AssertionError("generation must not run for Tier-D items")

    items = [
        EvidenceItem(ref=DRAMA_REF, text="A dramatic retelling."),
        EvidenceItem(ref=SCENE_REF, text="A rendered scene."),
    ]
    result = derive_batch(USER, items, nstore, generate_fn=_must_not_generate)
    assert result.calls == 0
    assert result.births == []
    assert nstore.threads_for(USER) == []
    assert any("non-evidence-tier" in s for s in result.skipped)


def test_claims_path_refuses_tier_d_evidence(nstore):
    """Claim-origin threads and fitting proposals cite through the
    same tier gate: a story artifact can never become claim evidence."""
    with pytest.raises(InadmissibleEvidenceError):
        nstore.create_thread(
            USER, origin="claim", title="From a story",
            evidence_refs=[DRAMA_REF],
        )
    thread = nstore.create_thread(
        USER, origin="claim", title="From a claim",
        evidence_refs=[CLAIM_REF],
    )
    assert len(nstore.evidence_for(USER, thread.id)) == 1
    with pytest.raises(InadmissibleEvidenceError):
        nstore.set_fitting(
            USER, thread.id, lens_id=LENS_ID, evidence_refs=[DRAMA_REF]
        )
    # Positive control: a real claim ref is Tier E and attaches fine.
    fitting = nstore.set_fitting(
        USER, thread.id, lens_id=LENS_ID, evidence_refs=[CLAIM_REF]
    )
    assert fitting.evidence_refs


def test_claim_builders_still_cannot_see_pipeline_or_provenance():
    """The claims path enforcement, pinned: claim builders import
    neither the pipeline nor the provenance registry (S4 pin, kept)."""
    tree = ast.parse(
        open("local_ai/agent_intake/review_claims.py", encoding="utf-8").read()
    )
    imported = []
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


# -- T2: rejected fittings ------------------------------------------------------------


def _fitting_thread(nstore):
    thread = nstore.create_thread(
        USER, origin="user_declared", title="T", evidence_refs=(EVENT_REF,)
    )
    return thread


def test_rejected_fitting_not_reproposed_without_new_evidence_or_reopen(nstore):
    thread = _fitting_thread(nstore)
    fitting = nstore.set_fitting(
        USER, thread.id, lens_id=LENS_ID, evidence_refs=[EVENT_REF]
    )
    nstore.set_fitting_status(USER, fitting.id, "rejected")
    # Same lens + same evidence → refused.
    with pytest.raises(ValueError):
        nstore.set_fitting(
            USER, thread.id, lens_id=LENS_ID, evidence_refs=[EVENT_REF]
        )
    # New evidence → allowed without any reopen.
    other = SourceRef(kind="event", ref_id="evt-9", evidence_kind="entity_ref")
    allowed = nstore.set_fitting(
        USER, thread.id, lens_id=LENS_ID, evidence_refs=[other]
    )
    assert allowed.status == "proposed"
    # Same evidence + explicit reopen naming the rejection → allowed.
    reopened = nstore.set_fitting(
        USER, thread.id, lens_id=LENS_ID, evidence_refs=[EVENT_REF],
        reopen_of=fitting.id,
    )
    assert reopened.status == "proposed"
    # The rejection itself stays recorded, unmutated.
    assert nstore.fittings_for(USER, thread.id, status="rejected")[0].id == fitting.id


def test_reopen_of_must_name_the_matching_rejection(nstore):
    thread = _fitting_thread(nstore)
    fitting = nstore.set_fitting(
        USER, thread.id, lens_id=LENS_ID, evidence_refs=[EVENT_REF]
    )
    nstore.set_fitting_status(USER, fitting.id, "rejected")
    with pytest.raises(ValueError):
        nstore.set_fitting(
            USER, thread.id, lens_id=LENS_ID, evidence_refs=[EVENT_REF],
            reopen_of="fit-nope",
        )
    other_lens = nstore.set_fitting(
        USER, thread.id, lens_id="departure_initiation_return",
        evidence_refs=[EVENT_REF],
    )
    nstore.set_fitting_status(USER, other_lens.id, "rejected")
    # A rejection for a different lens does not authorize this reopen.
    with pytest.raises(ValueError):
        nstore.set_fitting(
            USER, thread.id, lens_id=LENS_ID, evidence_refs=[EVENT_REF],
            reopen_of=other_lens.id,
        )


def test_rejected_fitting_never_reappears_in_review_or_context(nstore):
    from local_ai.narrative.context import narrative_context_for
    from local_ai.narrative.review import pending_review_items

    thread = nstore.create_thread(
        USER, origin="user_declared", title="Quinlin's school story",
        evidence_refs=(EVENT_REF,),
    )
    nstore.annotate_evidence_entities(
        USER, thread.id, {("event", "evt-8"): "person:quinlin"}
    )
    nstore.set_thread_status(USER, thread.id, "active")
    fitting = nstore.set_fitting(
        USER, thread.id, lens_id=LENS_ID, evidence_refs=[EVENT_REF]
    )
    assert any(
        item.item_kind == "fitting" and item.item_id.endswith(fitting.id)
        for item in pending_review_items(nstore, USER)
    )
    nstore.set_fitting_status(USER, fitting.id, "rejected")
    assert not any(
        item.item_kind == "fitting"
        for item in pending_review_items(nstore, USER)
    )
    conn = _perm_conn({USER: FLAGS_ON})
    prepared = narrative_context_for(
        nstore, USER, "seat:conductor",
        attended_entity_refs=("person:quinlin",),
        connection=conn,
        aspiration_reader=_no_asp,
        aspiration_permission_check=_no_asp,
    )
    assert prepared.available is True
    assert thread.title in (prepared.block or "")
    assert LENS_ID not in (prepared.block or "")
    assert "fitting" not in (prepared.block or "").lower()


# -- M1: certified vs re-labeled, Tier-E untouched --------------------------------------


def _legacy_story_artifact(prov, description):
    return prov.create_artifact(
        creator_user_id=USER,
        custodian_user_id=USER,
        title="Legacy story",
        description=json.dumps(description),
        modality="text",
        visibility="unlisted",
        remix_policy="open",
        imported=False,
        creator_declared=True,
    )


def _legacy_pair(stores, entry_text, line, link=True):
    pstore, prov = stores
    created = pipe.create_journal_entry(pstore, prov, USER, entry_text)
    entry = created["entry"]
    story = _legacy_story_artifact(
        prov, {"narrative": "legacy story", "key_line": line}
    )
    if link:
        prov.add_link(story["artifact_id"], entry["artifact_id"], "linked")
    return entry, story


def test_m1_stamps_tier_column_and_leaves_tier_e_untouched(stores, nstore):
    pstore, prov = stores
    entry, story = _legacy_pair(stores, JOURNEY_TEXT, VERBATIM)
    card = _legacy_story_artifact(prov, {"key_line": VERBATIM})
    prov.add_link(card["artifact_id"], story["artifact_id"], "linked")
    composed_story = _legacy_story_artifact(
        prov, {"narrative": "legacy story", "key_line": COMPOSED}
    )
    # Tier-E records that must survive the migration byte-identical.
    thread = nstore.create_thread(
        USER, origin="user_declared", title="T", evidence_refs=(EVENT_REF,)
    )
    evidence_before = nstore.evidence_for(USER, thread.id)
    entry_before = pstore.get_entry(entry["entry_id"])
    entry_artifact_before = prov.get_artifact(entry["artifact_id"])

    result = migrate_story_tiers(pstore, prov, dry_run=False)
    assert result["counts"]["stories_certified"] == 1
    assert result["counts"]["stories_dramatization"] == 1
    assert result["counts"]["cards_certified"] == 1
    assert prov.get_artifact(story["artifact_id"])["tier"] == "dramatization"
    assert prov.get_artifact(card["artifact_id"])["tier"] == "dramatization"
    assert (
        prov.get_artifact(composed_story["artifact_id"])["tier"] == "dramatization"
    )
    data = json.loads(prov.get_artifact(story["artifact_id"])["description"])
    assert data["key_line_tier"] == "certified"
    assert data["key_line_source"]["entry_id"] == entry["entry_id"]
    # Tier-E untouched: narrative evidence, journal entry, entry artifact.
    assert nstore.evidence_for(USER, thread.id) == evidence_before
    assert pstore.get_entry(entry["entry_id"]) == entry_before
    after = prov.get_artifact(entry["artifact_id"])
    assert after["description"] == entry_artifact_before["description"]
    assert after["tier"] == "evidence"


def test_m1_dry_run_writes_neither_description_nor_tier(stores):
    pstore, prov = stores
    _, story = _legacy_pair(stores, JOURNEY_TEXT, VERBATIM)
    result = migrate_story_tiers(pstore, prov, dry_run=True)
    assert result["counts"]["stories_certified"] == 1
    after = prov.get_artifact(story["artifact_id"])
    assert "key_line_tier" not in json.loads(after["description"])
    assert after["tier"] is None


def test_m1_backfills_tier_on_already_migrated_rows(stores):
    pstore, prov = stores
    entry, story = _legacy_pair(stores, JOURNEY_TEXT, VERBATIM)
    first = migrate_story_tiers(pstore, prov, dry_run=False)
    assert first["counts"]["stories_certified"] == 1
    # Simulate a row migrated before the tier column existed: strip
    # the column value but keep the classification.
    prov.update_artifact(story["artifact_id"], tier=None)
    assert prov.get_artifact(story["artifact_id"])["tier"] is None
    second = migrate_story_tiers(pstore, prov, dry_run=False)
    assert second["counts"]["stories_already_migrated"] == 1
    assert second["counts"]["stories_certified"] == 0
    after = prov.get_artifact(story["artifact_id"])
    assert after["tier"] == "dramatization"
    # Classification untouched by the backfill.
    assert json.loads(after["description"])["key_line_tier"] == "certified"


def test_m1_never_certifies_by_guess(stores):
    """Uncheckable (no linkable source entry) → dramatization, always."""
    pstore, prov = stores
    _, story = _legacy_pair(stores, JOURNEY_TEXT, VERBATIM, link=False)
    result = migrate_story_tiers(pstore, prov, dry_run=False)
    assert result["counts"]["stories_dramatization"] == 1
    data = json.loads(prov.get_artifact(story["artifact_id"])["description"])
    assert data["key_line_tier"] == "dramatization"


# -- selection ledgers ----------------------------------------------------------------------


def test_selection_ledgers_separate_and_rejected_options_unrecorded(stores):
    """Word provenance (key_line_tier) and choice provenance
    (key_line_selection) are distinct fields; no rejected-options
    record exists anywhere in the selection (arch §6.7 default)."""
    pstore, prov = stores
    _, result = _entry_and_story(stores)
    story_id = result["artifact"]["artifact_id"]
    chosen = pipe.choose_key_line(
        pstore, prov, USER, story_id, adopted_text=COMPOSED
    )
    content = chosen["content"]
    assert content["key_line_tier"] == "adopted"
    sel = content["key_line_selection"]
    assert sel["kind"] == "adopted"
    assert sel["chosen"] == COMPOSED
    assert "rejected" not in sel
    assert "rejected" not in content
    assert sel["attribution"] == "chosen by you from Zenaf's options"
    # Adopted wording is never a quotation: the card gate refuses it.
    with pytest.raises(ValueError):
        pipe.make_quote_card(pstore, prov, USER, story_id, badge=False)


def test_edited_then_chosen_is_user_authored_not_a_span(stores):
    pstore, prov = stores
    _, result = _entry_and_story(stores)
    story_id = result["artifact"]["artifact_id"]
    edited = "Grateful for the struggle, on my own terms."
    chosen = pipe.choose_key_line(
        pstore, prov, USER, story_id, edited_text=edited
    )
    content = chosen["content"]
    assert content["key_line"] == edited
    assert content["key_line_tier"] == "user_authored"
    assert not tiers.is_verbatim_span(edited, JOURNEY_TEXT)
    assert content["key_line_selection"]["kind"] == "edited"
    with pytest.raises(ValueError):
        pipe.make_quote_card(pstore, prov, USER, story_id, badge=False)


# -- scene renderer fate -----------------------------------------------------------------------


def test_scene_renderer_retired_but_casting_machinery_survives():
    """Phase 4 disposition: RETIRE. The renderer and its prompt
    builder are gone; strand analysis + casting still work; the
    journal router stays mounted but empty."""
    import local_ai.journal.story as story_mod
    from api.routes.journal_routes import router as journal_router

    assert not hasattr(story_mod, "render_archetype_story")
    assert not hasattr(story_mod, "_build_story_prompt")
    weights = story_mod.analyze_entry_strands(
        "I feel grateful and my heart is full of love for my family "
        "today, we laughed and shared stories."
    )
    assert isinstance(weights, dict) and weights
    cast = story_mod.select_cast(
        story_mod.detect_active_archetypes(weights, user_id=None)
    )
    assert isinstance(cast, list)
    assert list(journal_router.routes) == []


# -- journal→story pipeline tier-complete -------------------------------------------------------


def test_pipeline_and_journal_never_write_narrative_state():
    """Pin: no pipeline or journal module imports the narrative
    package, so the pipeline can never become a thread writer."""
    import pathlib

    for package in ("local_ai/pipeline", "local_ai/journal"):
        for path in pathlib.Path(package).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported += [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.append(node.module)
            assert not any(
                m == "local_ai.narrative" or m.startswith("local_ai.narrative.")
                for m in imported
            ), f"{path} imports narrative state"
