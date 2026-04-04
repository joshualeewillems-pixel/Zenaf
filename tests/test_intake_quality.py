"""
Minimal test cases for intake sorting quality (classifier + lane).
Run from repo root: python -m pytest tests/test_intake_quality.py -v
Or: python -m pytest tests/test_intake_quality.py -v --tb=short
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow importing local_ai
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.intake.pipeline import run_pipeline

# Cases: (subject, body_snippet, expected_lane, expected_category or None)
# Lane must match; category is optional check.
CASES = [
    ("Referral for John Doe", "Referring patient for cardiology follow-up.", "needs_attention", "referral"),
    ("Lab results ready", "CBC panel results are available for review.", "needs_attention", "lab_result"),
    ("Don't miss our 20% off sale", "Limited time offer. Unsubscribe here.", "likely_junk", "other"),
    ("Your receipt from Amazon", "Thank you for your order.", "likely_junk", "other"),
    ("Invitation: Team standup", "You have been invited to a meeting.", "likely_junk", "other"),
    ("URGENT: Patient callback", "Please call back ASAP regarding medication.", "needs_attention", None),
    ("Records release request", "Please process the attached ROI form.", "insurance_medical", "records_request"),
    ("Request a callback", "Would like to schedule a call.", "waiting_fyi", None),  # not records_request
    ("Prior auth required", "Patient needs prior authorization for procedure.", "insurance_medical", "insurance"),
    ("Your daily digest", "See what you missed.", "likely_junk", "other"),
    ("Newsletter: March updates", "View in browser. Unsubscribe.", "likely_junk", "other"),
    ("Refill request", "Patient requested medication refill.", "needs_attention", "prescription"),
    ("Appointment reminder", "Your appointment is tomorrow at 10am.", "waiting_fyi", "appointment"),
    ("Routine follow-up", "When convenient, please review.", "waiting_fyi", "other"),
    ("Shipment delayed", "Your supply order has been delayed.", "ordering_supplies", None),
]


def test_intake_quality_lane_and_category():
    for i, (subject, body, expected_lane, expected_category) in enumerate(CASES):
        item = run_pipeline(body, "email", subject=subject or None)
        assert item.lane == expected_lane, (
            f"Case {i + 1}: subject={subject!r} body={body[:50]!r} -> lane={item.lane} expected {expected_lane}"
        )
        if expected_category is not None:
            assert item.category == expected_category, (
                f"Case {i + 1}: subject={subject!r} -> category={item.category} expected {expected_category}"
            )


def test_intake_quality_lane_only():
    """Same cases but only assert lane (for quick regression)."""
    for i, (subject, body, expected_lane, _) in enumerate(CASES):
        item = run_pipeline(body, "email", subject=subject or None)
        assert item.lane == expected_lane, (
            f"Case {i + 1}: lane={item.lane} expected {expected_lane}"
        )
