"""Brand profile read path and Brand-seat persona injection."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.zenaf_tools import _build_council_persona_block, _built_in_persona_dict, _council_seat_is_brand
from local_ai.context import brand_profile as bp


def test_read_brand_profile_missing_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "brand-profile.json"
    bp._brand_cache_path = None
    bp._brand_cache_mtime = None
    bp._brand_cache_profile = {}
    with patch.object(bp, "brand_profile_path", return_value=missing):
        assert bp.read_brand_profile() == {}


def test_read_brand_profile_normalizes_and_caps_display_name(tmp_path: Path) -> None:
    p = tmp_path / "brand-profile.json"
    p.write_text(
        json.dumps(
            {
                "displayName": "  Org  ",
                "missionStatement": "x",
                "avoid": ["a" * 900, "ok"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    bp._brand_cache_path = None
    bp._brand_cache_mtime = None
    bp._brand_cache_profile = {}
    with patch.object(bp, "brand_profile_path", return_value=p):
        out = bp.read_brand_profile()
    assert out.get("displayName") == "Org"
    assert len(out.get("avoid", [])) == 2
    assert all(len(x) <= 801 for x in out.get("avoid", []))


def test_describe_brand_profile_preflight(tmp_path: Path) -> None:
    p = tmp_path / "brand-profile.json"
    p.write_text(json.dumps({"displayName": "Acme", "missionStatement": "m"}), encoding="utf-8")
    bp._brand_cache_path = None
    bp._brand_cache_mtime = None
    bp._brand_cache_profile = {}
    with patch.object(bp, "brand_profile_path", return_value=p):
        s = bp.describe_brand_profile_preflight()
    assert s["brand_profile_loaded"] is True
    assert s["brand_profile_display_name"] == "Acme"


def test_council_seat_is_brand() -> None:
    assert _council_seat_is_brand({"id": "brand", "name": "Brand"})
    assert _council_seat_is_brand({"name": "Brand"})
    assert not _council_seat_is_brand({"id": "operator", "name": "Operator"})


def test_brand_persona_block_includes_profile_text() -> None:
    defn = _built_in_persona_dict("brand")
    with patch.object(bp, "read_brand_profile", return_value={"missionStatement": "Mission line one."}):
        block = _build_council_persona_block(defn, council_clarify_only=False)
    assert "Mission line one." in block
    assert "Brand identity constraints" in block


def test_operator_persona_block_does_not_include_brand_profile() -> None:
    defn = _built_in_persona_dict("operator")
    with patch.object(bp, "read_brand_profile", return_value={"missionStatement": "Secret"}):
        block = _build_council_persona_block(defn, council_clarify_only=False)
    assert "Secret" not in block
