"""
Regression tests: curated boundary and adversarial intake cases.

These cases are selected from the synthetic dataset for permanent regression
testing. Failures here indicate pipeline/classifier/lane regressions that
should be fixed before release.

Run from repo root: python -m pytest tests/test_intake_synthetic_regression.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.intake.pipeline import run_pipeline

# Curated subset: (subject, body, expected_lane, expected_category)
# Boundary and adversarial cases that are especially valuable to keep stable.
REGRESSION_CASES = [
    # --- Boundary: request vs records ---
    ("Request a callback", "Would like to schedule a call to discuss my prescription refill.", "needs_attention", "prescription"),  # body has prescription -> needs_attention
    ("Request a callback", "Would like to discuss records release for continuity of care.", "insurance_medical", "records_request"),
    # --- Boundary: appointment with unsubscribe footer ---
    ("Appointment reminder", "Your appointment is tomorrow. Unsubscribe from reminders at link below.", "waiting_fyi", "appointment"),
    # --- Adversarial: subject junk, body important (clinical overrides junk subject) ---
    ("Your daily digest", "URGENT: Patient referral for cardiology. Please route to referral coordinator immediately.", "likely_junk", "referral"),
    ("Notification from System", "New lab results are available for your patient. CBC panel ready for review.", "needs_attention", "lab_result"),  # policy_clinical_overrides_junk_subject
    ("No reply", "Prior authorization required for procedure. Please submit to billing.", "insurance_medical", "insurance"),  # policy_clinical_overrides_junk_subject
    # --- Adversarial: subject important, body marketing ---
    ("Prior auth required", "Limited time offer! Click here to save. Unsubscribe from this list.", "likely_junk", "other"),
    ("Lab results ready", "See what you missed. View in browser. Unsubscribe.", "likely_junk", "other"),
    # Referral subject + promo body -> signal_marketing_body_referral_subject -> likely_junk/other
    ("Referral for Patient", "Congratulations! You've been selected. Act now. Unsubscribe.", "likely_junk", "other"),
    # --- Short / low-signal (empty body -> low confidence; current: other/waiting_fyi) ---
    ("", "Lab.", "needs_attention", "lab_result"),
    ("Lab", "", "waiting_fyi", "other"),  # body empty -> no lab keyword; current behavior
    # --- Medical + marketing mixed -> signal_medical_marketing_mixed -> likely_junk/other ---
    ("Save on your prescription", "Refill your medication today and save 20%. Unsubscribe.", "likely_junk", "other"),
    ("Pharmacy: Your refill is ready", "Your medication refill has been processed. Pick up at your convenience.", "needs_attention", "prescription"),
    # --- Records-request negation: "not a records request" suppresses records_request -> waiting_fyi ---
    ("Request for information", "I would like to request a callback to discuss my appointment. Not a records request.", "waiting_fyi", "appointment"),  # signal_records_request_negated; body has "appointment"
    ("Information request", "Could you please send me the records release form? I need to request my medical records.", "insurance_medical", "records_request"),
    # --- Insurance payment vs action ---
    ("Your payment was received", "Thank you for your payment. This is not a bill. Do not reply.", "waiting_fyi", "other"),
    # --- Software / urgent sales ---
    ("URGENT: Your account will expire", "Act now to renew! Limited time offer. Click here. Unsubscribe.", "likely_junk", "other"),
    # --- FWD/Re: with real content ---
    ("FWD: Lab results", "---------- Forwarded message ---------\nCBC results are available for review.", "needs_attention", "lab_result"),
    ("FWD: Invoice", "---------- Forwarded message ---------\nFrom: Billing\nPrior auth required for patient. EOB attached.", "insurance_medical", "insurance"),
    # --- Newsletter with medical terms (body has lab/prescription -> lab_result; clinical overrides junk subject) ---
    ("Your weekly health digest", "View in browser. This week: lab results, prescription tips, and more. Unsubscribe.", "needs_attention", "lab_result"),
    # --- HTML-ish (pipeline should strip) ---
    ("Lab results available", "Results are ready.<br><br>Please review.<br>&nbsp;<br>Thank you.", "needs_attention", "lab_result"),
]


def test_intake_synthetic_regression_lane():
    """Assert lane for each curated case (primary regression signal)."""
    for i, (subject, body, expected_lane, _expected_category) in enumerate(REGRESSION_CASES):
        item = run_pipeline(body, "email", subject=subject or None)
        assert item.lane == expected_lane, (
            f"Case {i + 1}: subject={subject!r} body={body[:50]!r} -> lane={item.lane} expected {expected_lane}"
        )


def test_intake_synthetic_regression_category():
    """Assert category for each curated case."""
    for i, (subject, body, _expected_lane, expected_category) in enumerate(REGRESSION_CASES):
        item = run_pipeline(body, "email", subject=subject or None)
        assert item.category == expected_category, (
            f"Case {i + 1}: subject={subject!r} -> category={item.category} expected {expected_category}"
        )
