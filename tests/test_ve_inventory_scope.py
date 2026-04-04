"""VE working-set scoping for inventory-style council questions."""
from __future__ import annotations

import local_ai.council_preflight as cp


def test_extract_quoted_spans():
    q = "what do we still need to do to the 'finalize website' idea?"
    assert cp._extract_quoted_spans(q) == ["finalize website"]


def test_score_name_question_finalize_website():
    q = "what do we still need to do to the 'finalize website' idea?"
    assert cp._score_name_in_question(q, "Finalize Website") >= 14


def test_score_substring_title_tokens():
    q = "Still need on finalize website rollout"
    assert cp._score_name_in_question(q, "Finalize Website Rollout") >= 4
