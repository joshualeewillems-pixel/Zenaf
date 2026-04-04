"""Externalization helpers for compiled initiative_evaluate (narrow identifiers)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.execution_policy.externalization import (
    INITIATIVE_EVALUATE_INTENT,
    apply_ordered_identifier_mappings,
    maybe_externalize_structured_initiative_evaluate_for_cloud,
    make_placeholder_token,
)


def test_apply_ordered_mappings_longest_first():
    short = "ab"
    long_id = f"x{short}yz"  # contains short as substring
    prompt = f"see {long_id} and {short} end"
    ext, pm = apply_ordered_identifier_mappings(
        prompt,
        [("user_id", short), ("initiative_id", long_id)],
    )
    assert short not in ext or long_id not in ext
    tok_l = make_placeholder_token("initiative_id", long_id)
    tok_s = make_placeholder_token("user_id", short)
    assert tok_l in ext
    assert tok_s in ext


def test_maybe_externalize_initiative_noop_when_id_absent_from_prompt():
    p = "Title: x\nBrief:\ny\n"
    r = maybe_externalize_structured_initiative_evaluate_for_cloud(
        routing_context={"action_intent": INITIATIVE_EVALUATE_INTENT},
        exec_meta={"provider_used": "openai"},
        internal_prompt=p,
        initiative_id="never-appears-in-text",
        user_id=None,
    )
    assert r.strategy == "none"
    assert p == r.external_prompt


def test_maybe_externalize_initiative_wrong_intent():
    r = maybe_externalize_structured_initiative_evaluate_for_cloud(
        routing_context={"action_intent": "idea_evaluate"},
        exec_meta={"provider_used": "openai"},
        internal_prompt="initiative-abc in brief",
        initiative_id="initiative-abc",
        user_id=None,
    )
    assert r.strategy == "none"
