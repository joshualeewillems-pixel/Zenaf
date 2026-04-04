"""Workspace translation template merge on workspace packet."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.workspace_identity.snapshot import build_workspace_packet_from_snapshot
from local_ai.workspace_identity.translation_template import (
    apply_workspace_translation_template,
    read_translation_template,
    write_translation_template,
)


def test_apply_block_preferred_allow_order() -> None:
    tpl = {
        "preferredPhrases": ["Zebra First"],
        "blockFromMirror": ["Beta Noise"],
        "alwaysAllow": ["Always Here"],
        "functionalHints": ["intake"],
    }
    core = ["Beta Noise", "Gamma Core", "alpha tail"]
    cap = {"themes": ["t1"], "namedPrograms": [], "tags": ["legacy"]}
    out, c2 = apply_workspace_translation_template(core, cap, tpl, max_hints=10)
    assert out[0] == "Zebra First"
    assert "Always Here" in out
    assert "Beta Noise" not in out
    assert "Gamma Core" in out
    assert "intake" in c2["tags"]
    assert "legacy" in c2["tags"]


def test_blocked_phrase_prefix_star() -> None:
    tpl = {
        "blockedPhrases": ["www-main-desktop-*"],
        "preferredPhrases": [],
        "alwaysAllow": [],
        "aliases": {},
        "functionalMappings": {},
        "functionalHints": [],
        "structuralHints": [],
    }
    core = ["www-main-desktop-home-page-skeleton", "clinical", "WWW-Main-Desktop-Noise"]
    cap = {"themes": [], "namedPrograms": [], "tags": []}
    out, _ = apply_workspace_translation_template(core, cap, tpl, max_hints=20)
    assert "clinical" in out
    assert not any(x.lower().startswith("www-main-desktop") for x in out)


def test_blocked_phrases_alias() -> None:
    tpl = {
        "blockedPhrases": ["Noise"],
        "aliases": {"old llc": "Canonical Org Name"},
        "preferredPhrases": [],
        "alwaysAllow": [],
        "functionalMappings": {},
        "functionalHints": [],
        "structuralHints": [],
    }
    core = ["Noise", "old llc", "Other"]
    cap = {"themes": [], "namedPrograms": [], "tags": []}
    out, _ = apply_workspace_translation_template(core, cap, tpl, max_hints=20)
    assert "Noise" not in out
    assert "old llc" not in out
    assert "Canonical Org Name" in out
    assert "Other" in out


def test_functional_mappings_conditional() -> None:
    tpl = {
        "functionalMappings": {"Healing Haven": ["intake", "clinic"], "Absent Co": "never"},
        "functionalHints": [],
    }
    core = ["Healing Haven", "Other"]
    cap = {"themes": [], "namedPrograms": [], "tags": ["base"]}
    _, c2 = apply_workspace_translation_template(core, cap, tpl)
    tags = c2["tags"]
    assert "intake" in tags
    assert "clinic" in tags
    assert "never" not in tags
    assert "base" in tags


def test_structural_hints_prepended_to_themes() -> None:
    tpl = {"structuralHints": ["Spine A", "Spine B"], "functionalHints": []}
    core = ["x"]
    cap = {"themes": ["core theme"], "namedPrograms": [], "tags": []}
    _, c2 = apply_workspace_translation_template(core, cap, tpl)
    assert c2["themes"][:2] == ["Spine A", "Spine B"]
    assert "core theme" in c2["themes"]


def test_template_only_packet_when_core_empty(tmp_path: Path) -> None:
    write_translation_template(
        {
            "preferredPhrases": ["Only Phrase"],
            "alwaysAllow": [],
            "blockedPhrases": [],
            "aliases": {},
            "functionalMappings": {},
            "functionalHints": [],
            "structuralHints": [],
        },
        base_dir=tmp_path,
    )
    snap = {
        "schemaVersion": 2,
        "branchKey": "x",
        "domainHints": [],
        "buffers": {
            "surface_shallow": {"phrases": [], "pathSketches": []},
            "associative_cluster": {"clusters": []},
            "structural_translation": {"buckets": []},
            "functional": {"activityTags": [], "roleHints": []},
            "reasoning": {"themes": [], "namedPrograms": [], "tags": []},
        },
    }
    p = build_workspace_packet_from_snapshot(snap, translation_base_dir=tmp_path)

    assert p is not None
    assert p["domainHints"][0] == "Only Phrase"


def test_build_packet_reads_template_from_disk(tmp_path: Path) -> None:
    tpl_path = tmp_path / "translation-template.json"
    tpl_path.write_text(
        json.dumps(
            {
                "preferredPhrases": ["Preferred Org"],
                "blockedPhrases": ["drop me"],
                "alwaysAllow": [],
                "functionalHints": ["onboarding"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    snap = {
        "schemaVersion": 2,
        "branchKey": "x",
        "domainHints": [],
        "buffers": {
            "surface_shallow": {"phrases": ["drop me", "keep phrase"], "pathSketches": []},
            "associative_cluster": {"clusters": []},
            "structural_translation": {"buckets": []},
            "functional": {"activityTags": [], "roleHints": []},
            "reasoning": {"themes": [], "namedPrograms": [], "tags": []},
        },
    }
    p = build_workspace_packet_from_snapshot(snap, translation_base_dir=tmp_path)

    assert p is not None
    assert p["domainHints"][0] == "Preferred Org"
    assert "drop me" not in p["domainHints"]
    assert "keep phrase" in p["domainHints"]
    assert "onboarding" in (p["reasoningCapsule"].get("tags") or [])


def test_read_missing_template_empty() -> None:
    assert read_translation_template(Path("/nonexistent/does-not-exist-xyz")) == {}
