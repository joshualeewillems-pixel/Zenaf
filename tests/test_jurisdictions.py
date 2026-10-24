"""Tests for the council jurisdiction registry (Fellowship Runtime P0).

Covers:
  * registry completeness — all 7 stock seats, canonical order, every
    field of the audit §A schema present and non-empty;
  * consolidation consistency — each seat's register.warmth in the
    registry is the seat's WARMTH_REGISTERS text verbatim, so the
    consolidated record cannot silently drift from the existing source;
  * Weaver consumption — build_archetype_prompt_lines('conductor')
    actually contains the registry's focus/register values (asserted
    against the registry objects themselves, not hardcoded strings, so
    the test proves the wiring rather than the wording);
  * non-consumption — the other six seats' prompts carry no
    jurisdiction lines and are byte-identical to the pre-P0
    construction. Byte-identity is pinned by SHA-256 of the joined
    prompt, captured from origin/main before P0 landed. Honest scope:
    a hash mismatch proves the prompt DRIFTED but not where; that is
    the right semantics for a non-consumption guard — any change to a
    non-migrated seat's prompt, intended or not, should fail loudly
    here until that seat's own migration updates the pin.
  * API — GET /council/jurisdictions (all seats, §A shape) and
    GET /council/jurisdictions/{id} (one seat; 404 unknown).
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI

import api.routes.council_jurisdiction_routes as jur_routes
from api.routes.auth_routes import get_current_user
from local_ai.council import archetypes as arch
from local_ai.council import jurisdictions as jur

try:
    from fastapi.testclient import TestClient
except Exception:  # starlette's TestClient needs httpx2 (absent in some dev envs)
    TestClient = None  # type: ignore[assignment]

requires_testclient = pytest.mark.skipif(
    TestClient is None,
    reason="TestClient unavailable (httpx2 missing in this environment)",
)

ALICE = {"id": "user-alice", "email": "alice@x", "display_name": "Alice"}

# SHA-256 of "\n".join(build_archetype_prompt_lines(seat)) per seat,
# captured on origin/main at 3876e75 (post-#193), before P0. The
# conductor is deliberately absent: P0 changes her prompt by design.
_PRE_P0_PROMPT_SHA256 = {
    "mentor": "8b08339e544b4a8dbb200b22051c9c85f2c9c4c5a631c56c7cccf8d13b8ad9d4",
    "champion": "672a62a81d8165fe4571c776882cd86e913c59ceebde10dd0b7a6be88b4b50cc",
    "guardian": "8851068e216606772242bb06f2ae487d4c43fb66a15f8d391391b31dc41e6dcc",
    "maverick": "265a84292ea5a92900c3abe874dfd2bcc967a03c558a6d94160affb8f18a22ca",
    "ambassador": "15476eeea27e941876b5d71023419389244963dcc2cc81f6b9f20dcbb29cf219",
    "skeptic": "e0447f7ecf33c5f716fffd0ae8374692824ee9f2c002048a3a8b486ccf8ca39d",
}


# --- registry completeness ---------------------------------------------------


def test_registry_covers_exactly_the_stock_seats_in_canonical_order():
    assert jur.jurisdiction_ids() == arch.stock_archetype_ids()
    assert set(jur.SEAT_JURISDICTIONS) == set(arch.stock_archetype_ids())


def test_every_record_is_complete():
    for seat_id in jur.jurisdiction_ids():
        rec = jur.get_jurisdiction(seat_id)
        assert rec is not None, seat_id
        assert rec.archetype_id == seat_id
        assert rec.focus.strip(), seat_id
        # Periphery: 2-4 adjacent concerns, each a real sentence.
        assert 2 <= len(rec.periphery) <= 4, seat_id
        assert all(p.strip() for p in rec.periphery), seat_id
        # Conflicts: contested ground both ways + an overreach.
        assert len(rec.conflicts.overlaps) >= 2, seat_id
        assert all(o.strip() for o in rec.conflicts.overlaps), seat_id
        assert rec.conflicts.overreach.strip(), seat_id
        assert len(rec.conflicts.defers_to) >= 2, seat_id
        assert all(d.strip() for d in rec.conflicts.defers_to), seat_id
        # Register: all four dimensions present.
        reg = rec.register
        assert reg.diction.strip(), seat_id
        assert reg.tempo.strip(), seat_id
        assert reg.metaphor_family.strip(), seat_id
        assert reg.warmth.strip(), seat_id


def test_peripheries_are_distinct_per_seat():
    # Each seat's edge is its own — no periphery text is shared between
    # seats (a copy-pasted periphery would fail the doctrine's point).
    seen: dict[str, str] = {}
    for seat_id in jur.jurisdiction_ids():
        for item in jur.get_jurisdiction(seat_id).periphery:
            assert item not in seen, f"periphery shared: {seat_id} / {seen.get(item)}"
            seen[item] = seat_id


def test_get_jurisdiction_unknown_and_case():
    assert jur.get_jurisdiction("nope") is None
    assert jur.get_jurisdiction("") is None
    assert jur.get_jurisdiction("Conductor") is jur.get_jurisdiction("conductor")
    assert jur.jurisdiction_prompt_lines("nope") == []


# --- consolidation consistency -------------------------------------------------


def test_registry_warmth_matches_warmth_registers_verbatim():
    # The registry consolidates WARMTH_REGISTERS; until all seats
    # migrate, the two records must agree exactly, seat by seat.
    for seat_id in jur.jurisdiction_ids():
        rec = jur.get_jurisdiction(seat_id)
        assert rec.register.warmth == arch.WARMTH_REGISTERS[seat_id], seat_id


# --- Weaver consumption ---------------------------------------------------------


def test_weaver_prompt_is_sourced_from_the_registry():
    rec = jur.get_jurisdiction("conductor")
    lines = arch.build_archetype_prompt_lines("conductor")
    text = "\n".join(lines)
    # Focus and every register dimension appear, read from the record.
    assert rec.focus in text
    assert rec.register.diction in text
    assert rec.register.tempo in text
    assert rec.register.metaphor_family in text
    # The prompt lines are exactly the registry's prompt lines.
    for line in jur.jurisdiction_prompt_lines("conductor"):
        assert line in lines
    # Warmth arrives via the registry exactly once — not duplicated
    # from WARMTH_REGISTERS by the pre-P0 code path.
    assert lines.count(rec.register.warmth) == 1
    # The rest of the Weaver's voice is intact around the new block.
    assert lines[0].startswith("Archetype: Conductor — ")
    assert any(line.startswith("Foundational ideal:") for line in lines)
    assert any(
        line.startswith("Strand blend (faculties this seat draws on")
        for line in lines
    )


def test_jurisdiction_lines_carry_no_other_seats_register():
    # Consumption is wired for the conductor only: her block holds her
    # own record's values, nobody else's.
    rec = jur.get_jurisdiction("conductor")
    own = jur.jurisdiction_prompt_lines("conductor")
    for seat_id in jur.jurisdiction_ids():
        if seat_id == "conductor":
            continue
        other = jur.get_jurisdiction(seat_id)
        assert other.focus not in "\n".join(own), seat_id
        assert other.register.diction not in "\n".join(own), seat_id
    assert rec.focus in "\n".join(own)


# --- the dictionaries (Weaver-pattern release, 2026-10-23) ---------------------


def test_every_dictionary_is_complete():
    # Joshua's table, filled for all seven seats: domain, jurisdiction
    # triad, a real lexicon, a distinctive perspective, a signature
    # line — no seat's dictionary left as a placeholder.
    for seat_id in jur.jurisdiction_ids():
        dic = jur.get_jurisdiction(seat_id).dictionary
        assert dic.domain.strip(), seat_id
        assert len(dic.jurisdiction_triad) == 3, seat_id
        assert all(t.strip() for t in dic.jurisdiction_triad), seat_id
        assert len(dic.lexicon) >= 8, seat_id
        assert all(w.strip() for w in dic.lexicon), seat_id
        assert dic.perspective.strip(), seat_id
        assert dic.signature_line.strip(), seat_id


def test_dictionary_content_is_joshuas_table():
    # The ratified selections, pinned verbatim — a change here is a
    # content change that needs his verdict, not an incidental edit.
    weaver = jur.get_jurisdiction("conductor").dictionary
    assert weaver.domain == "Music & Composition"
    assert weaver.jurisdiction_triad == ("harmony", "integration", "coordination")
    assert "counterpoint" in weaver.lexicon
    assert "dissonance" in weaver.lexicon
    assert weaver.signature_line == "Not every voice needs to sing the same note."
    assert weaver.provisional is False

    gardener = jur.get_jurisdiction("mentor").dictionary
    assert gardener.domain == "Horticulture & Ecology"
    assert gardener.signature_line == (
        "You can prune a branch, but you can't command it to bear fruit."
    )

    raven = jur.get_jurisdiction("skeptic").dictionary
    assert raven.domain == "Investigation & Forensics"
    assert raven.signature_line == (
        "I'm not saying you're wrong. I'm asking how we'd find out."
    )

    crane = jur.get_jurisdiction("ambassador").dictionary
    assert crane.domain == "Language & Diplomacy"
    assert crane.signature_line == (
        "Sometimes two people are fighting over an answer to questions "
        "neither one asked."
    )

    firebrand = jur.get_jurisdiction("champion").dictionary
    assert firebrand.domain == "Warfare & Strategy"
    assert firebrand.signature_line == (
        "Before you draw your sword, decide what victory would actually mean."
    )


def test_provisional_dictionaries_are_marked():
    # Bear (warmth under review) and Fox (trickster/inventor/escape
    # artist still being explored) are recorded as provisional —
    # visibly, on the record, not as silent placeholders.
    assert jur.get_jurisdiction("guardian").dictionary.provisional is True
    assert jur.get_jurisdiction("maverick").dictionary.provisional is True
    for seat_id in ("mentor", "champion", "ambassador", "conductor", "skeptic"):
        assert (
            jur.get_jurisdiction(seat_id).dictionary.provisional is False
        ), seat_id


def test_weaver_dictionary_reaches_her_prompt_as_available_context():
    # Consumption (this release): the Weaver's prompt lines carry her
    # dictionary — as AVAILABLE context under the three-layers rule,
    # with the no-obligation wording present in the line itself.
    rec = jur.get_jurisdiction("conductor")
    text = "\n".join(jur.jurisdiction_prompt_lines("conductor"))
    assert rec.dictionary.domain in text
    assert rec.dictionary.perspective in text
    for word in rec.dictionary.lexicon:
        assert word in text, word
    # The three-layers framing: ordinary speech is the default, and
    # the lexicon is never owed.
    assert "ordinary speech is your" in text
    assert "never owed, never a quota" in text
    # And it flows into the built voice prompt exactly once.
    prompt = "\n".join(arch.build_archetype_prompt_lines("conductor"))
    assert prompt.count(rec.dictionary.perspective) == 1


def test_no_other_seat_consumes_its_dictionary_yet():
    # The other six seats' prompts carry no dictionary content — the
    # byte-identity test below is the strong form; this makes the
    # intent readable at the failure site.
    conductor_text = "\n".join(jur.jurisdiction_prompt_lines("conductor"))
    for seat_id in jur.jurisdiction_ids():
        if seat_id == "conductor":
            continue
        other = jur.get_jurisdiction(seat_id)
        assert other.dictionary.domain not in conductor_text, seat_id
        assert other.dictionary.signature_line not in conductor_text, seat_id


# --- non-consumption: the other six seats are untouched --------------------------


def test_other_seats_prompts_are_byte_identical_to_pre_p0():
    for seat_id, expected_sha in _PRE_P0_PROMPT_SHA256.items():
        text = "\n".join(arch.build_archetype_prompt_lines(seat_id))
        got = hashlib.sha256(text.encode()).hexdigest()
        assert got == expected_sha, (
            f"{seat_id}: prompt drifted from the pre-P0 construction "
            "(see module docstring — this pin is intentional)"
        )
        # And the direct invariant: no jurisdiction marker line.
        assert "Your jurisdiction" not in text, seat_id
        assert "Your diction:" not in text, seat_id


# --- API -------------------------------------------------------------------------


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(jur_routes.router)
    app.dependency_overrides[get_current_user] = lambda: ALICE
    return TestClient(app)


@requires_testclient
def test_api_lists_all_seats_in_order(client):
    r = client.get("/council/jurisdictions")
    assert r.status_code == 200, r.text
    records = r.json()["jurisdictions"]
    assert [rec["archetype_id"] for rec in records] == list(
        jur.jurisdiction_ids()
    )
    for rec in records:
        assert rec["focus"]
        assert 2 <= len(rec["periphery"]) <= 4
        assert set(rec["conflicts"]) == {"overlaps", "overreach", "defers_to"}
        assert set(rec["register"]) == {
            "diction",
            "tempo",
            "metaphor_family",
            "warmth",
        }


@requires_testclient
def test_api_get_one_seat_matches_registry(client):
    r = client.get("/council/jurisdictions/conductor")
    assert r.status_code == 200, r.text
    assert r.json() == jur.jurisdiction_as_dict(
        jur.get_jurisdiction("conductor")
    )


@requires_testclient
def test_api_unknown_seat_is_404(client):
    r = client.get("/council/jurisdictions/nope")
    assert r.status_code == 404, r.text


def test_api_handlers_directly():
    # The handlers are plain functions; call them without HTTP so the
    # serialization and 404 logic are verified even where TestClient
    # cannot run (see the httpx2 note at the top of this file).
    from fastapi import HTTPException

    body = jur_routes.list_jurisdictions(current_user=ALICE)
    records = body["jurisdictions"]
    assert [rec["archetype_id"] for rec in records] == list(
        jur.jurisdiction_ids()
    )
    one = jur_routes.get_jurisdiction_record("conductor", current_user=ALICE)
    assert one == jur.jurisdiction_as_dict(jur.get_jurisdiction("conductor"))
    with pytest.raises(HTTPException) as excinfo:
        jur_routes.get_jurisdiction_record("nope", current_user=ALICE)
    assert excinfo.value.status_code == 404
