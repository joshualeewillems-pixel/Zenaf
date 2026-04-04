"""
Strict behavioral contracts for the workspace identity buffer stack.

Pipeline (no skips): recognition → grouping → structure → function → reasoning.
Each layer may only consume outputs from layers at or below it. Raw literals from
Buffer 0 must not be re-published as first-class reasoning outputs (no upward
leakage of shallow tokens into Buffer 4).

**Behavioral boundaries** — Each buffer has ``allowed_output_examples`` and
``disallowed_output_examples`` in ``BUFFER_BEHAVIORAL_CONTRACTS``. These describe
valid *resolution* at that layer (what conclusions may look like), not desired
domain content. Use ``validate_buffer_output_shape()`` for lightweight drift
checks on emitted buffer payloads.

Exposure policy
---------------
- **Default decision surface** (operator / council / “what should I decide?”): only
  Buffer 3 (functional) and Buffer 4 (reasoning). Callers should use
  ``decision_surface_from_buffers()`` for that view.
- **Extraction grounding** (meeting extract, packet ``domainHints`` / ``literalAnchors``):
  may still use Buffer 0 phrases as *controlled literals* — that path is grounding,
  not interpretive reasoning. Those fields are not the default operator surface.
  Circumstance-specific renames, blocks, and hints belong in ``translation-template.json``
  (applied when building the packet, not inside buffer passes).

Buffer roles (strict)
---------------------
**Buffer 0 — surface_shallow**
    Extract literal phrases (and path sketches) from scan evidence only.
    No interpretation, no domain assignment, no purpose labels.

**Buffer 1 — associative_cluster**
    Group co-occurring labels under a parent sketch. No semantics: weights and
    membership only; do not assign “what this cluster means” beyond co-occurrence.

**Buffer 2 — structural_translation**
    Map evidence to *system structure types* (content, workflow, data, media,
    integrations, configuration, …). Today’s snapshot uses deterministic bucket
    labels such as ``engine``, ``ui``, ``docs`` as the implementation’s encoding
    of those types; filenames are inputs only, not the bucket *name*.

**Buffer 3 — functional**
    Assign operational purpose (onboarding, regulation, tracking, outreach, …).
    May collapse dissimilar surface strings under the same functional tag
    (functional similarity allowed).

**Buffer 4 — reasoning**
    Compose higher-level lines for judgment: themes, tensions, opportunities.
    Inputs: structured outputs from buffers 1–3 only at snapshot build time;
    product context may later merge VE state + transcript *outside* this module
    when generating council / decision copy. Must not treat Buffer 0 phrases as
    authoritative labels in ``namedPrograms``; themes must not paste raw shallow
    literals (only counts / sketches derived from deeper buffers).

Enforcement in code
-------------------
- ``BUFFER_PIPELINE_KEYS``: canonical build order; ``build_all_buffers`` follows it.
- ``decision_surface_from_buffers``: default safe projection for UI/policy.
- Reasoning ``namedPrograms`` are derived from functional/structural signals only,
  not from the surface phrase list (see ``build_reasoning_buffer``).
- ``BUFFER_BEHAVIORAL_CONTRACTS`` / ``validate_buffer_output_shape``: resolution
  boundaries for reviewers and optional drift checks (not ML).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Layer index → snapshot buffer key (matches buffers.BUFFER_GRAPH topology).
BUFFER_LAYER_SURFACE = 0
BUFFER_LAYER_ASSOCIATIVE = 1
BUFFER_LAYER_STRUCTURAL = 2
BUFFER_LAYER_FUNCTIONAL = 3
BUFFER_LAYER_REASONING = 4

BUFFER_PIPELINE_KEYS: tuple[tuple[int, str], ...] = (
    (BUFFER_LAYER_SURFACE, "surface_shallow"),
    (BUFFER_LAYER_ASSOCIATIVE, "associative_cluster"),
    (BUFFER_LAYER_STRUCTURAL, "structural_translation"),
    (BUFFER_LAYER_FUNCTIONAL, "functional"),
    (BUFFER_LAYER_REASONING, "reasoning"),
)

# Default operator / decision-making projection: functional + reasoning only.
DECISION_SURFACE_BUFFER_KEYS: frozenset[str] = frozenset({"functional", "reasoning"})

# Keys allowed in extraction grounding packet literals (Buffer 0 family only).
EXTRACTION_GROUNDING_BUFFER_KEYS: frozenset[str] = frozenset({"surface_shallow"})


@dataclass(frozen=True)
class BufferBehavioralContract:
    """Resolution boundaries for one buffer layer (behavior, not content goals)."""

    key: str
    layer_index: int
    question: str
    rule: str
    allowed_output_examples: tuple[str, ...]
    disallowed_output_examples: tuple[str, ...]


BUFFER_BEHAVIORAL_CONTRACTS: dict[str, BufferBehavioralContract] = {
    "surface_shallow": BufferBehavioralContract(
        key="surface_shallow",
        layer_index=BUFFER_LAYER_SURFACE,
        question="What exists here, literally?",
        rule="Name only. No interpretation.",
        allowed_output_examples=(
            "Northwind Portal",
            "client onboarding",
            "morning sync",
        ),
        disallowed_output_examples=(
            "this is an onboarding flow",
            "this supports stress reduction",
            "this is strategically important",
        ),
    ),
    "associative_cluster": BufferBehavioralContract(
        key="associative_cluster",
        layer_index=BUFFER_LAYER_ASSOCIATIVE,
        question="What tends to appear together?",
        rule="Co-occurrence only. No meaning.",
        allowed_output_examples=(
            "email, opt-in, welcome letter appear together",
            "invoice, PO line, vendor record cluster together",
            "signup, settings export, audit trail share one parent folder",
        ),
        disallowed_output_examples=(
            "this is a unified intake workflow",
            "this is a growth opportunity",
        ),
    ),
    "structural_translation": BufferBehavioralContract(
        key="structural_translation",
        layer_index=BUFFER_LAYER_STRUCTURAL,
        question="What kind of thing is this?",
        rule="System shape only. No purpose.",
        allowed_output_examples=(
            "this cluster looks like a content sequence",
            "this cluster looks like a data workflow",
            "this cluster looks like media assets",
        ),
        disallowed_output_examples=(
            "this is for customer retention",
            "this is similar to a well-known external program",
        ),
    ),
    "functional": BufferBehavioralContract(
        key="functional",
        layer_index=BUFFER_LAYER_FUNCTIONAL,
        question="What does this do?",
        rule="Purpose, not judgment.",
        allowed_output_examples=(
            "this supports onboarding",
            "this supports status tracking",
            "this supports follow-up cadence",
            "these items share a similar role",
        ),
        disallowed_output_examples=(
            "this is the highest priority",
            "this is a strategic bottleneck",
        ),
    ),
    "reasoning": BufferBehavioralContract(
        key="reasoning",
        layer_index=BUFFER_LAYER_REASONING,
        question="What matters?",
        rule="Judgment built from lower layers only.",
        allowed_output_examples=(
            "onboarding is partially defined but lacks a clear entry point",
            "existing reference content could support a reusable follow-up sequence",
            "operational data exists but is not yet leveraged in a coherent workflow",
        ),
        disallowed_output_examples=(
            "meditation",
            "email, opt-in, welcome",
        ),
    ),
}


# Lightweight drift patterns derived from disallowed *behavior* (not domain text).
_SURFACE_DRIFT: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("interpretation_clause", re.compile(r"\bthis is (a|an)\b", re.IGNORECASE)),
    ("supports_claim", re.compile(r"\bthis supports\b", re.IGNORECASE)),
    ("strategic_judgment", re.compile(r"\bstrategically\b|\bstrategic importance\b", re.IGNORECASE)),
)

_ASSOCIATIVE_DRIFT: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("meaning_assignment", re.compile(r"\bthis is a\b.*\b(workflow|opportunity|strategy)\b", re.IGNORECASE)),
    ("growth_framing", re.compile(r"\bgrowth opportunity\b", re.IGNORECASE)),
)

_STRUCTURAL_DRIFT: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("business_purpose", re.compile(r"\bthis is for\b.*\b(retention|revenue|conversion)\b", re.IGNORECASE)),
    ("external_analogy", re.compile(r"\bis similar to\b", re.IGNORECASE)),
)

_FUNCTIONAL_DRIFT: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("priority_judgment", re.compile(r"\bhighest priority\b|\bmost important\b", re.IGNORECASE)),
    ("bottleneck_judgment", re.compile(r"\bstrategic bottleneck\b|\bcritical path\b.*\b(block|blocker)\b", re.IGNORECASE)),
)

# Reasoning must not paste shallow-style “a, b, c” lines (whole string is three bare tokens).
_REASONING_TRIPLE_COMMA_TOKEN_LINE = re.compile(
    r"^\s*[\w][\w\-]{0,40},\s*[\w][\w\-]{0,40},\s*[\w][\w\-]{0,40}\s*$",
    re.IGNORECASE,
)
_REASONING_SINGLE_TOKEN_THEME = re.compile(r"^[a-z][a-z\-]{1,40}$", re.IGNORECASE)


def _collect_strings_from_buffer_output(buffer_key: str, output: Any) -> list[str]:
    if not isinstance(output, dict):
        return []
    texts: list[str] = []
    if buffer_key == "surface_shallow":
        for k in ("phrases", "pathSketches"):
            for x in output.get(k) or []:
                if isinstance(x, str) and x.strip():
                    texts.append(x)
    elif buffer_key == "associative_cluster":
        for c in output.get("clusters") or []:
            if not isinstance(c, dict):
                continue
            ps = c.get("parentSketch")
            if isinstance(ps, str) and ps.strip():
                texts.append(ps)
            for m in c.get("members") or []:
                if isinstance(m, str) and m.strip():
                    texts.append(m)
    elif buffer_key == "structural_translation":
        for b in output.get("buckets") or []:
            if not isinstance(b, dict):
                continue
            for lab in b.get("labels") or []:
                if isinstance(lab, str) and lab.strip():
                    texts.append(lab)
    elif buffer_key == "functional":
        for k in ("activityTags", "roleHints"):
            for x in output.get(k) or []:
                if isinstance(x, str) and x.strip():
                    texts.append(x)
    elif buffer_key == "reasoning":
        for k in ("themes", "namedPrograms", "tags"):
            for x in output.get(k) or []:
                if isinstance(x, str) and x.strip():
                    texts.append(x)
    return texts


def validate_buffer_output_shape(buffer_name: str, output: Any) -> list[str]:
    """
    Heuristic drift check: strings in *output* should not match disallowed behavioral
    patterns for *buffer_name*. Returns human-readable issues (empty = no hits).

    This does not prove correctness; it flags obvious resolution leaks (e.g.
    interpretation in surface, priority language in functional).
    """
    if buffer_name not in BUFFER_BEHAVIORAL_CONTRACTS:
        return [f"unknown buffer: {buffer_name!r}"]
    issues: list[str] = []
    texts = _collect_strings_from_buffer_output(buffer_name, output)
    if not texts:
        return []

    pattern_groups: tuple[tuple[str, re.Pattern[str]], ...]
    if buffer_name == "surface_shallow":
        pattern_groups = _SURFACE_DRIFT
    elif buffer_name == "associative_cluster":
        pattern_groups = _ASSOCIATIVE_DRIFT
    elif buffer_name == "structural_translation":
        pattern_groups = _STRUCTURAL_DRIFT
    elif buffer_name == "functional":
        pattern_groups = _FUNCTIONAL_DRIFT
    elif buffer_name == "reasoning":
        pattern_groups = ()  # custom below
    else:
        pattern_groups = ()

    for s in texts:
        low = s.lower().strip()
        for code, pat in pattern_groups:
            if pat.search(s):
                issues.append(f"{buffer_name}: {code!r} matched in {s[:120]!r}")

    if buffer_name == "reasoning":
        for s in texts:
            low = s.lower()
            if _REASONING_TRIPLE_COMMA_TOKEN_LINE.match(s) and "appear" not in low and "cluster" not in low:
                issues.append(f"reasoning: shallow comma-list suspected in {s[:120]!r}")
        for s in _themes_only_strings(output):
            t = s.strip()
            if len(t) <= 48 and _REASONING_SINGLE_TOKEN_THEME.match(t) and " " not in t:
                issues.append(f"reasoning: theme looks like raw literal token: {t!r}")

    return issues


def _themes_only_strings(output: Any) -> list[str]:
    if not isinstance(output, dict):
        return []
    return [x for x in (output.get("themes") or []) if isinstance(x, str) and x.strip()]


def validate_buffer_stack_present(buffers: dict[str, Any]) -> list[str]:
    """
    Return a list of human-readable issues if any pipeline stage is missing.
    Empty list means all layers are present (values may still be empty dicts).
    """
    issues: list[str] = []
    for _layer, key in BUFFER_PIPELINE_KEYS:
        if key not in buffers:
            issues.append(f"missing buffer layer: {key}")
    return issues


def decision_surface_from_buffers(buffers: dict[str, Any]) -> dict[str, Any]:
    """
    Operator-default view: purpose (functional) + synthesized judgment (reasoning).
    Does not include surface literals, clusters, or structural buckets.
    """
    fn = buffers.get("functional")
    rs = buffers.get("reasoning")
    return {
        "functional": fn if isinstance(fn, dict) else {},
        "reasoning": rs if isinstance(fn, dict) else {},
    }


def extraction_grounding_from_buffers(buffers: dict[str, Any]) -> dict[str, Any]:
    """Literal grounding slice only (Buffer 0)."""
    sh = buffers.get("surface_shallow")
    return {"surface_shallow": sh if isinstance(sh, dict) else {}}


def decision_surface_excludes_literal_buffer_layers(surface: dict[str, Any]) -> list[str]:
    """
    Return issues if *surface* (typically from decision_surface_from_buffers) exposes
    wrong keys or Buffer-0-style containers. Empty list means shape is acceptable.
    """
    issues: list[str] = []
    forbidden_top = frozenset({"surface_shallow", "associative_cluster", "structural_translation"})
    for k in surface:
        if k in forbidden_top:
            issues.append(f"decision surface must not include key {k!r}")
    for key in ("functional", "reasoning"):
        block = surface.get(key)
        if not isinstance(block, dict):
            continue
        for leak in ("phrases", "pathSketches", "clusters", "buckets"):
            if leak in block:
                issues.append(f"decision surface.{key} must not embed buffer field {leak!r}")
    return issues
