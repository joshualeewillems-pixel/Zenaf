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
