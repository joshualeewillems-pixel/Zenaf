"""Coarse synthesis vs seat support heuristic (bounded integrity)."""

from local_ai.atria_tools import _compute_synthesis_support_vs_seats


def test_support_high_overlap():
    seats = [
        "Strategist: We should accelerate the Q3 roadmap and mitigate vendor risk.",
        "Operator: Focus on delivery milestones and staff the critical path.",
    ]
    syn = (
        "The Q3 roadmap acceleration matters; vendor risk and delivery milestones "
        "should stay on the critical path with adequate staffing."
    )
    assert _compute_synthesis_support_vs_seats(syn, seats) == "supported"


def test_partial_overlap():
    seats = ["Analyst: Revenue declined in the Midwest region last quarter."]
    syn = (
        "Revenue midwest region quarter matters; add parallel planning for contingency "
        "scenarios beyond the core narrative."
    )
    assert _compute_synthesis_support_vs_seats(syn, seats) == "partially_supported"


def test_unsupported_many_novel_terms():
    seats = ["Risk: Monitor the integration deadline."]
    syn = (
        "Furthermore zebronics quantum plasmonics xenolith repurposing mandates "
        "completely orthogonal bifurcated stratospheres unrelated to deadlines."
    )
    assert _compute_synthesis_support_vs_seats(syn, seats) == "unsupported_expansion"


def test_short_synthesis_defaults_supported():
    seats = ["A: Hello there."]
    assert _compute_synthesis_support_vs_seats("Yes.", seats) == "supported"


def test_strips_atria_synthesis_header():
    seats = ["Governance: Compliance review before launch."]
    # Header line stripped; vocabulary echoes seats (stopwords like "before" are omitted from overlap tokens).
    syn = "Atria synthesis:\nGovernance compliance review launch."
    assert _compute_synthesis_support_vs_seats(syn, seats) == "supported"
