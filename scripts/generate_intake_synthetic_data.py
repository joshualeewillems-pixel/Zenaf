#!/usr/bin/env python3
"""
Generate labeled synthetic intake emails for adversarial triage testing.

Focus: realistic and intentionally confusing examples across all lanes and categories,
including boundary and adversarial cases (subject/body mismatch, low signal, marketing
disguised as clinical, etc.). Template-based, deterministic with --seed.

Output: datasets/intake_synthetic_cases.json with id, difficulty, subject, body,
expected_category, expected_lane, notes. 300-500 examples by default.

Usage (from repo root):
  python scripts/generate_intake_synthetic_data.py
  python scripts/generate_intake_synthetic_data.py --count 400 --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Lane and category constants (must match local_ai.intake)
LANES = ["needs_attention", "insurance_medical", "ordering_supplies", "waiting_fyi", "likely_junk"]
CATEGORIES = [
    "referral", "lab_result", "prescription", "appointment", "insurance",
    "records_request", "general_inquiry", "other",
]


def _t(
    difficulty: str,
    subject: str,
    body: str,
    expected_category: str,
    expected_lane: str,
    notes: str = "",
) -> dict:
    return {
        "difficulty": difficulty,
        "subject": subject,
        "body": body,
        "expected_category": expected_category,
        "expected_lane": expected_lane,
        "notes": notes or "",
    }


def _fill(g: random.Random, template: str, **kwargs: str) -> str:
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", str(v))
    while "{" in out:
        i, j = out.index("{"), out.index("}", out.index("{")) + 1
        out = out[:i] + out[j:]
    return out


def _pick(g: random.Random, lst: list) -> str:
    return g.choice(lst)


def build_cases(g: random.Random) -> list[dict]:
    """Build all case templates; use g only for placeholders where needed."""
    cases: list[dict] = []

    # --- EASY: clear-cut ---
    easy_referral = [
        ("Referral for Maria Garcia", "Referring patient for cardiology follow-up. Please schedule.", "Clear referral wording."),
        ("Patient referral - James Chen", "We are referring this patient to your office for evaluation.", "Direct referral."),
    ]
    for sub, body, note in easy_referral:
        cases.append(_t("easy", sub, body, "referral", "needs_attention", note))

    easy_lab = [
        ("Lab results ready", "CBC panel results are available for review.", "Clear lab result."),
        ("Lab results: metabolic panel", "Results are back. Please review at your earliest convenience.", "Lab keywords."),
    ]
    for sub, body, note in easy_lab:
        cases.append(_t("easy", sub, body, "lab_result", "needs_attention", note))

    easy_rx = [
        ("Refill request - Patient Smith", "Patient requested medication refill. Please approve.", "Clear prescription refill."),
    ]
    for sub, body, note in easy_rx:
        cases.append(_t("easy", sub, body, "prescription", "needs_attention", note))

    easy_insurance = [
        ("Prior auth required", "Patient needs prior authorization for procedure. EOB attached.", "Clear insurance action."),
        ("MediCal eligibility inquiry", "Please verify eligibility for upcoming visit.", "Insurance/MediCal."),
    ]
    for sub, body, note in easy_insurance:
        cases.append(_t("easy", sub, body, "insurance", "insurance_medical", note))

    easy_records = [
        ("Records release request", "Please process the attached ROI form. Patient signed release.", "Clear records request."),
    ]
    for sub, body, note in easy_records:
        cases.append(_t("easy", sub, body, "records_request", "insurance_medical", note))

    easy_appt = [
        ("Appointment reminder", "Your appointment is tomorrow at 10am. Please confirm.", "Clear appointment."),
    ]
    for sub, body, note in easy_appt:
        cases.append(_t("easy", sub, body, "appointment", "waiting_fyi", note))

    easy_ordering = [
        ("Shipment delayed", "Your supply order has been delayed. New ETA next week.", "Clear ordering."),
    ]
    for sub, body, note in easy_ordering:
        cases.append(_t("easy", sub, body, "other", "ordering_supplies", note))

    easy_inquiry = [
        ("Question about my account", "I have a question regarding my recent statement. Please contact me.", "General inquiry."),
    ]
    for sub, body, note in easy_inquiry:
        cases.append(_t("easy", sub, body, "general_inquiry", "waiting_fyi", note))

    easy_junk = [
        ("Your receipt from Amazon", "Thank you for your order. Order #12345.", "Clear receipt."),
        ("Newsletter: March updates", "View in browser. Unsubscribe to opt out.", "Clear newsletter."),
        ("Don't miss our 20% off sale", "Limited time offer. Unsubscribe here.", "Clear marketing."),
    ]
    for sub, body, note in easy_junk:
        cases.append(_t("easy", sub, body, "other", "likely_junk", note))

    # --- BOUNDARY: could go either way ---
    boundary_list = [
        ("Routine follow-up", "When convenient, please review the attached lab results.", "other", "waiting_fyi", "Low priority but has lab; often waiting_fyi."),
        ("Request a callback", "Would like to schedule a call to discuss my prescription refill.", "other", "waiting_fyi", "Request + prescription; not records_request."),
        ("Re: Your message", "Please see below. Patient needs prior authorization. Thanks.", "insurance", "insurance_medical", "Re: with insurance content; body carries signal."),
        ("FWD: Lab results", "---------- Forwarded message ---------\nCBC results are available for review.", "lab_result", "needs_attention", "FWD chain; content is lab."),
        ("Request a callback", "Would like to discuss records release for continuity of care.", "records_request", "insurance_medical", "Request + records context; should be records_request."),
        ("Appointment reminder", "Your appointment is tomorrow. Unsubscribe from reminders at link below.", "appointment", "waiting_fyi", "Appointment with unsubscribe footer; still appointment."),
    ]
    for sub, body, exp_cat, exp_lane, note in boundary_list:
        cases.append(_t("boundary", sub, body, exp_cat, exp_lane, note))

    # --- ADVERSARIAL: subject/body mismatch, low signal, disguised ---
    # Each: (subject, body, expected_category, expected_lane, notes)
    adversarial_list = [
        # Subject suggests junk, body suggests important
        ("Your daily digest", "URGENT: Patient referral for cardiology. Please route to referral coordinator immediately.", "referral", "needs_attention", "Subject junk (digest), body urgent referral; may get likely_junk from subject."),
        ("Notification from System", "New lab results are available for your patient. CBC panel ready for review.", "lab_result", "needs_attention", "Subject notification-ish, body is lab; classifier may cap confidence."),
        ("No reply", "Prior authorization required for procedure. Please submit to billing.", "insurance", "insurance_medical", "Subject no-reply, body insurance; could be missed."),
        # Subject suggests important, body is marketing
        ("Prior auth required", "Limited time offer! Click here to save. Unsubscribe from this list.", "other", "likely_junk", "Subject insurance, body marketing; should be likely_junk."),
        ("Lab results ready", "See what you missed. View in browser. Unsubscribe.", "other", "likely_junk", "Subject lab, body newsletter; likely_junk."),
        ("Referral for Patient", "Congratulations! You've been selected. Act now. Unsubscribe.", "other", "likely_junk", "Subject referral, body promo; likely_junk."),
        # Short body / low-signal
        ("Update", "Please review.", "other", "waiting_fyi", "Very short; low signal."),
        ("Re: Question", "Thanks.", "other", "waiting_fyi", "Near-empty; ambiguous."),
        ("", "Lab.", "lab_result", "needs_attention", "Empty subject, one-word body; lab."),
        # HTML-ish fragments
        ("Lab results available", "Results are ready.<br><br>Please review.<br>&nbsp;<br>Thank you.", "lab_result", "needs_attention", "HTML fragments; pipeline strips tags."),
        ("Prescription refill", "Refill request received.&nbsp; Process when convenient.", "prescription", "needs_attention", "Entity in body."),
        # RE: / FWD chains
        ("Re: Lab results", "On Mon, Mar 1, someone wrote:\n> CBC results are available for review.\nPlease advise.", "lab_result", "needs_attention", "Re: with quoted lab content."),
        ("FWD: Invoice", "---------- Forwarded message ---------\nFrom: Billing\nPrior auth required for patient. EOB attached.", "insurance", "insurance_medical", "FWD invoice subject but body is insurance."),
        # Newsletter containing medical terms
        ("Your weekly health digest", "View in browser. This week: lab results, prescription tips, and more. Unsubscribe.", "other", "likely_junk", "Newsletter + medical terms; likely_junk."),
        ("Monthly newsletter", "Topics: referral process, insurance updates, appointment reminders. Unsubscribe.", "other", "likely_junk", "Newsletter with clinical terms."),
        # Appointment reminder with promo footer
        ("Appointment reminder - Tomorrow 10am", "Your appointment is confirmed. We look forward to seeing you.\n\n---\nLimited time offer on flu shots. Unsubscribe.", "appointment", "waiting_fyi", "Appointment + promo footer."),
        # Pharmacy promo vs actual prescription need
        ("Save on your prescription", "Refill your medication today and save 20%. Unsubscribe.", "other", "likely_junk", "Pharmacy promo; likely_junk."),
        ("Pharmacy: Your refill is ready", "Your medication refill has been processed. Pick up at your convenience.", "prescription", "needs_attention", "Real refill notice."),
        # "Request" in non-records context
        ("Request for information", "I would like to request a callback to discuss my appointment. Not a records request.", "general_inquiry", "waiting_fyi", "Request but not records."),
        ("Information request", "Could you please send me the records release form? I need to request my medical records.", "records_request", "insurance_medical", "Request + records; records_request."),
        # Insurance payment confirmation vs real action
        ("Your payment was received", "Thank you for your payment. This is not a bill. Do not reply.", "other", "likely_junk", "Payment confirmation; not action item."),
        ("EOB for your records", "Explanation of benefits attached for your records. No action needed.", "insurance", "waiting_fyi", "EOB but no action needed."),
        # Software/tool notifications with business-like language
        ("Action required: Verify your account", "Please verify your email to continue. This is an automated message. Do not reply.", "other", "likely_junk", "Urgent-sounding but software."),
        ("Reminder: Document signed", "Your document has been signed. Log in to view. Notification from DocuSign.", "other", "likely_junk", "Business notification."),
        # Urgent-sounding sales language
        ("URGENT: Your account will expire", "Act now to renew! Limited time offer. Click here. Unsubscribe.", "other", "likely_junk", "Urgent subject, sales body."),
        ("Important: Action required", "Don't miss out. 50% off today only. Unsubscribe.", "other", "likely_junk", "Important + action but marketing."),
        # Empty or near-empty body with ambiguous subject
        ("Lab", "", "lab_result", "needs_attention", "Subject only; one word lab; body empty."),
        ("Referral", " ", "referral", "needs_attention", "Subject referral, body whitespace only."),
        ("Prior auth", "\n", "insurance", "insurance_medical", "Subject insurance, body newline only."),
    ]
    for sub, body, exp_cat, exp_lane, note in adversarial_list:
        cases.append(_t("adversarial", sub, body, exp_cat, exp_lane, note))

    # Additional variety: duplicate and vary placeholders for count
    names = ["Maria G.", "James C.", "Patient Smith", "Yuki W."]
    specialties = ["cardiology", "dermatology"]
    more_easy = [
        _t("easy", f"Referral for {n}", f"Referring patient for {s} follow-up.", "referral", "needs_attention", "Varied referral")
        for n in names for s in specialties
    ]
    more_easy += [
        _t("easy", "Your receipt from Staples", "Thank you for your order. Order #99999.", "other", "likely_junk", "Receipt"),
        _t("easy", "Invitation: Team standup", "You have been invited to a meeting. Accept or decline.", "other", "likely_junk", "Calendar invite"),
        _t("easy", "Order shipped", "Your supply order has shipped. Tracking attached.", "other", "ordering_supplies", "Ordering"),
        _t("easy", "General inquiry", "I have a question about my prescription. Please contact me.", "general_inquiry", "waiting_fyi", "Inquiry re prescription"),
    ]
    cases.extend(more_easy)

    # Pad with variety to hit 300-500
    pad_templates = [
        ("Re: Referral", "Referring patient for cardiology. Please schedule.", "referral", "needs_attention"),
        ("Re: Lab results", "CBC results are available for review.", "lab_result", "needs_attention"),
        ("Re: Prior auth", "Patient needs prior authorization. EOB attached.", "insurance", "insurance_medical"),
        ("FWD: Refill request", "Patient requested medication refill. Please approve.", "prescription", "needs_attention"),
        ("Re: Appointment", "Your appointment is tomorrow at 10am.", "appointment", "waiting_fyi"),
        ("Order status", "Your supply order has shipped. Tracking attached.", "other", "ordering_supplies"),
        ("Inquiry", "I have a question about my referral. Please contact me.", "general_inquiry", "waiting_fyi"),
        ("ROI request", "Please process the attached records release form. Patient signed.", "records_request", "insurance_medical"),
        ("Your receipt", "Thank you for your order. Unsubscribe.", "other", "likely_junk"),
    ]
    while len(cases) < 500:
        sub, body, exp_cat, exp_lane = g.choice(pad_templates)
        cases.append(_t("easy", sub, body, exp_cat, exp_lane, "Padded variety."))

    return cases


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate adversarial synthetic intake dataset")
    ap.add_argument("--count", type=int, default=450, help="Target number of examples (default 450)")
    ap.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    ap.add_argument("--out", type=str, default=str(ROOT / "datasets" / "intake_synthetic_cases.json"), help="Output JSON path")
    args = ap.parse_args()
    g = random.Random(args.seed)
    cases = build_cases(g)
    g.shuffle(cases)
    cases = cases[: args.count]
    out_list = []
    for i, c in enumerate(cases):
        out_list.append({
            "id": i + 1,
            "difficulty": c["difficulty"],
            "subject": c["subject"],
            "body": c["body"],
            "expected_category": c["expected_category"],
            "expected_lane": c["expected_lane"],
            "notes": c["notes"],
        })
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_list, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(out_list)} cases to {out_path}")
    by_difficulty: dict[str, int] = {}
    by_lane: dict[str, int] = {}
    for r in out_list:
        by_difficulty[r["difficulty"]] = by_difficulty.get(r["difficulty"], 0) + 1
        by_lane[r["expected_lane"]] = by_lane.get(r["expected_lane"], 0) + 1
    print("By difficulty:", by_difficulty)
    print("By expected_lane:", by_lane)


if __name__ == "__main__":
    main()
