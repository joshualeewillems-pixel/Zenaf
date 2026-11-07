"""Deterministic wash-contract benchmark harness (wash-semantic 1.0 /
wash-extraction 1.0).

Governing spec: ``~/workspace/your_files/zenaf-wash-contract-and-evaluation-design-2026-11-06.md``
(§§0-13, revised 2026-11-06). The harness is deterministic code only: it
takes raw model text as input and produces validated rows, measures, a
manifest, and a report. It never calls a model, never loads a runtime, and
never scores by another model.

Layout (all paths relative to this package):

- ``textutil.py`` — deterministic text normalization, similarity, speaker resolution.
- ``validator.py`` — the pinned validator (parse + repair + proposition gate +
  three-part quote gate + dedupe), pinned by contract version, never importing
  pipeline HEAD.
- ``fixtures.py`` — fixture loader + schema validation + version agreement.
- ``measures.py`` — deterministic measure computations (§6.4) + pass rule (§7).
- ``manifest.py`` — manifest writer (§2.2).
- ``report.py`` — report generator (JSON + markdown).
- ``runner.py`` — orchestration + thin CLI for scoring a run's raw outputs.
- ``fixtures/`` — the synthetic gold-labeled fixture set (DRAFT labels).
"""

from __future__ import annotations

# Versioned things (design §2). The semantic contract and the extraction
# implementation are versioned separately; the harness and the pinned
# validator carry their own versions.
SEMANTIC_VERSION = "1.0"  # wash-semantic 1.0
EXTRACTION_VERSION = "1.0"  # wash-extraction 1.0
HARNESS_VERSION = "1.0"
VALIDATOR_VERSION = "1.0"  # pinned validator; tied to extraction 1.0
MANIFEST_VERSION = "1.0"

# Fixture + gold-label versions. DRAFT: the founder approves FROZEN gold
# labels only after the harness proves itself (§8.1). The loader refuses to
# run if the fixture version and the gold-label version disagree.
FIXTURE_SET_VERSION = "1.0-draft"
GOLD_LABEL_VERSION = "1.0-draft"

# Stance vocabulary (design §2.1) and confidence labels (§2.1.3).
STANCE_VALUES = ("proposed", "considered", "committed", "rejected", "unresolved")
CONFIDENCE_VALUES = ("high", "medium", "low")

# Diagnostic confidence reasons (§2.1.3, refinement C). Preserved as a
# harness/diagnostic field; never a displayed tier.
CONFIDENCE_REASON_MISSING = "confidence_missing"
CONFIDENCE_REASON_WEAK = "support_uncertain"

# Failure codes (§2.1.4, runtime-agnostic).
FAILURE_CODES = ("unreachable", "timeout", "invalid_output", "overloaded", "model_missing")

# Forbidden-output classes (measure F, §6.4).
FORBIDDEN_CLASSES = (
    "negation_inversion",
    "commitment_inflation",
    "attribution_error",
    "certainty_upgrade",
    "false_positive",
)

# Gate-rejection reasons (measure G, §2.2 / §6.4).
GATE_REASONS = (
    "missing_quote",
    "quote_not_verbatim",
    "quote_misattributed",
    "quote_unsupported",
    "text_too_short",
    "not_propositional",
    "duplicate",
)

# Variants (§4.3, §8). Default v1 is model-on; the skip rule is an
# experimental benchmark variant only, never the default.
VARIANT_MODEL_ON = "model-on"
VARIANT_SKIP_ENABLED = "skip-enabled"
VARIANTS = (VARIANT_MODEL_ON, VARIANT_SKIP_ENABLED)

__all__ = [
    "SEMANTIC_VERSION",
    "EXTRACTION_VERSION",
    "HARNESS_VERSION",
    "VALIDATOR_VERSION",
    "MANIFEST_VERSION",
    "FIXTURE_SET_VERSION",
    "GOLD_LABEL_VERSION",
    "STANCE_VALUES",
    "CONFIDENCE_VALUES",
    "CONFIDENCE_REASON_MISSING",
    "CONFIDENCE_REASON_WEAK",
    "FAILURE_CODES",
    "FORBIDDEN_CLASSES",
    "GATE_REASONS",
    "VARIANT_MODEL_ON",
    "VARIANT_SKIP_ENABLED",
    "VARIANTS",
]
