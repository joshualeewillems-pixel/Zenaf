#!/usr/bin/env python3
"""
Generate a synthetic intake dataset with ~300-500 labeled examples across all lanes.

Covers: noise (marketing, receipts, newsletters, software notifications), insurance,
referrals, lab results, prescriptions, appointments, records requests, general inquiry.

Labels (lane, category, priority, confidence) are produced by running the real intake
pipeline on each example, so the dataset is consistent with current classifier/lane rules.

Usage (from repo root):
  python scripts/generate_synthetic_intake_dataset.py
  python scripts/generate_synthetic_intake_dataset.py --count 400 --out data/synthetic_intake.json

Output: JSON array of records with subject, body, lane, category, priority, confidence, etc.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

# Repo root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.intake.pipeline import run_pipeline

SEED = 42
LANES = ["needs_attention", "insurance_medical", "ordering_supplies", "waiting_fyi", "likely_junk"]

# --- Templates: (subject_template, body_template) with {placeholders} ---

REFERRAL = [
    ("Referral for {name}", "Referring patient for {specialty} follow-up. Please schedule."),
    ("Referral: {name}", "We are referring this patient to your office for evaluation. Thank you."),
    ("Patient referral - {name}", "Referring patient for cardiology. Records attached."),
    ("Referral to your practice", "Dr. Smith has referred the patient for consultation."),
    ("New referral - {name}", "Please see the attached referral. Patient requested appointment."),
]
LAB_RESULT = [
    ("Lab results ready - {name}", "CBC panel results are available for review in the portal."),
    ("Lab results: {test}", "Results are back. Please review at your earliest convenience."),
    ("{test} results available", "Specimen received. Panel results are ready for clinical review."),
    ("Lab result notification", "New lab result(s) have been posted for your patient."),
    ("Results ready for review", "CBC and metabolic panel results are available."),
]
PRESCRIPTION = [
    ("Refill request - {name}", "Patient requested medication refill. Please approve when convenient."),
    ("Prescription refill request", "Refill requested for ongoing medication. Route to pharmacy or prescriber."),
    ("Medication refill needed", "Patient needs refill authorization. Rx on file."),
    ("Rx refill request", "Refill request received. Please process."),
]
APPOINTMENT = [
    ("Appointment reminder - {name}", "Your appointment is scheduled for {date} at {time}. Please confirm."),
    ("Appointment confirmation", "Your visit is confirmed for next week. Reply to reschedule if needed."),
    ("Reschedule request", "Patient would like to reschedule their appointment. Please call to confirm."),
    ("Appointment cancellation", "Patient has cancelled. Please update schedule."),
]
INSURANCE = [
    ("Prior auth required", "Patient needs prior authorization for the requested procedure. EOB attached."),
    ("Insurance authorization request", "Prior authorization required. Please submit to billing."),
    ("EOB for your review", "Explanation of benefits attached. Route to billing/authorization."),
    ("MediCal eligibility inquiry", "Please verify eligibility for upcoming visit."),
    ("Prior authorization status", "Authorization request is pending. Medical necessity form attached."),
]
RECORDS_REQUEST = [
    ("Records release request", "Please process the attached ROI form. Patient signed release."),
    ("Medical records request", "Request for release of information. Chart requested for dates below."),
    ("ROI form submitted", "Release of records request. Please process within 10 business days."),
    ("Fax record request", "Records request received. Chart copy needed for continuity of care."),
]
GENERAL_INQUIRY = [
    ("Question about my account", "I have a question regarding my recent statement. Please contact me."),
    ("General inquiry", "I would like to speak with someone about my care. Thank you."),
    ("Contact request", "Please have a staff member reach out at your convenience."),
]

# Noise: likely_junk lane (receipts, newsletters, software notifications, marketing)
NOISE_RECEIPT = [
    ("Your receipt from {vendor}", "Thank you for your order. Order #{id}."),
    ("Receipt for your purchase", "Your payment has been processed. See details below."),
    ("Your order confirmation", "Order confirmed. Estimated delivery in 3-5 business days."),
]
NOISE_NEWSLETTER = [
    ("Newsletter: March updates", "View in browser. Unsubscribe to opt out of future emails."),
    ("Your weekly digest", "See what you missed this week. Click here to read more."),
    ("Monthly newsletter", "Top stories and updates. Unsubscribe link at bottom."),
]
NOISE_MARKETING = [
    ("Don't miss our 20% off sale", "Limited time offer. Unsubscribe here. Act now."),
    ("Special offer just for you", "Click here to claim your discount. No longer wish to receive? Unsubscribe."),
    ("Flash sale: 50% off", "Limited time. Free shipping on orders over $50. Unsubscribe."),
]
NOISE_SOFTWARE = [
    ("Your daily digest", "See what you missed. Notification summary attached."),
    ("You have a new notification", "Your account has new activity. Verify your email to continue."),
    ("Reminder: Your subscription", "Your subscription is renewing soon. Do not reply to this email."),
    ("Notification from Service", "You have 3 new updates. Log in to view."),
    ("Software update available", "A new update is available. No reply needed. Unsubscribe from these notifications."),
    ("Alert: Password change", "Your password was changed. If this wasn't you, contact support. Do not reply."),
]
NOISE_INVITE = [
    ("Invitation: Team standup", "You have been invited to a meeting. Accept or decline."),
    ("Invitation: Project kickoff", "You have been invited to a calendar event."),
    ("Calendar invite: 1:1", "You have been invited to a meeting. View in browser."),
]
ORDERING = [
    ("Shipment delayed - Order #{id}", "Your supply order has been delayed. New ETA next week."),
    ("Order shipped", "Your order has shipped. Tracking number attached."),
    ("Reorder reminder", "Inventory low. Please reorder formulary items when convenient."),
    ("Supply order confirmation", "Order received. Supplies will arrive by Friday."),
]

# Placeholder values
FIRST_NAMES = ["Maria", "James", "Yuki", "David", "Ana", "Robert", "Sofia", "Michael", "Elena", "Chris"]
LAST_NAMES = ["Smith", "Garcia", "Chen", "Johnson", "Williams", "Brown", "Lee", "Davis"]
SPECIALTIES = ["cardiology", "dermatology", "orthopedics", "neurology", "oncology"]
TESTS = ["CBC", "metabolic panel", "lipid panel", "HbA1c", "thyroid panel"]
VENDORS = ["Amazon", "Office Depot", "Staples", "Walmart"]
DATES = ["Monday 10am", "Tuesday 2pm", "next Wednesday", "March 15", "tomorrow at 9am"]
TIMES = ["10:00 AM", "2:30 PM", "9:00 AM"]


def fill(template: str, **kwargs: str) -> str:
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", str(v))
    # Remove any remaining {x}
    while "{" in out:
        i = out.index("{")
        j = out.index("}", i) + 1
        out = out[:i] + out[j:]
    return out


def pick(g: random.Random, lst: list) -> str:
    return g.choice(lst)


def generate_examples(g: random.Random, target_count: int) -> list[tuple[str, str, str]]:
    """Generate (subject, body, intended_type) with intended_type hint for balancing."""
    out: list[tuple[str, str, str]] = []
    # Target ~equal distribution across lanes; we'll oversample then trim.
    per_type = max(60, (target_count + 4) // 5)
    # Referrals -> needs_attention
    for _ in range(per_type):
        sub, body = g.choice(REFERRAL)
        name = f"{pick(g, FIRST_NAMES)} {pick(g, LAST_NAMES)}"
        spec = pick(g, SPECIALTIES)
        out.append((fill(sub, name=name), fill(body, name=name, specialty=spec), "referral"))
    # Lab -> needs_attention
    for _ in range(per_type):
        sub, body = g.choice(LAB_RESULT)
        test = pick(g, TESTS)
        out.append((fill(sub, name=pick(g, FIRST_NAMES), test=test), fill(body, test=test), "lab"))
    # Prescription -> needs_attention
    for _ in range(per_type):
        sub, body = g.choice(PRESCRIPTION)
        out.append((fill(sub, name=pick(g, FIRST_NAMES)), body, "rx"))
    # Appointment -> waiting_fyi
    for _ in range(per_type):
        sub, body = g.choice(APPOINTMENT)
        out.append((fill(sub, name=pick(g, FIRST_NAMES), date=pick(g, DATES), time=pick(g, TIMES)), body, "appt"))
    # Insurance -> insurance_medical
    for _ in range(per_type):
        sub, body = g.choice(INSURANCE)
        out.append((sub, body, "insurance"))
    # Records -> insurance_medical
    for _ in range(per_type // 2):
        sub, body = g.choice(RECORDS_REQUEST)
        out.append((sub, body, "records"))
    # General inquiry -> waiting_fyi
    for _ in range(per_type):
        sub, body = g.choice(GENERAL_INQUIRY)
        out.append((sub, body, "inquiry"))
    # Noise: receipts, newsletters, marketing, software, invites
    for _ in range(per_type):
        sub, body = g.choice(NOISE_RECEIPT)
        oid = str(g.randint(10000, 99999))
        out.append((fill(sub, vendor=pick(g, VENDORS), id=oid), fill(body, id=oid), "noise"))
    for _ in range(per_type // 2):
        sub, body = g.choice(NOISE_NEWSLETTER)
        out.append((sub, body, "noise"))
    for _ in range(per_type // 2):
        sub, body = g.choice(NOISE_MARKETING)
        out.append((sub, body, "noise"))
    for _ in range(per_type // 2):
        sub, body = g.choice(NOISE_SOFTWARE)
        out.append((sub, body, "noise"))
    for _ in range(per_type // 2):
        sub, body = g.choice(NOISE_INVITE)
        out.append((sub, body, "noise"))
    # Ordering -> ordering_supplies
    for _ in range(per_type):
        sub, body = g.choice(ORDERING)
        out.append((fill(sub, id=str(g.randint(1000, 9999))), body, "ordering"))
    g.shuffle(out)
    return out[:target_count]


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic intake dataset")
    ap.add_argument("--count", type=int, default=450, help="Target number of examples (default 450)")
    ap.add_argument("--seed", type=int, default=SEED, help="Random seed")
    ap.add_argument("--out", type=str, default=str(ROOT / "data" / "synthetic_intake_dataset.json"), help="Output JSON path")
    ap.add_argument("--csv", type=str, default="", help="Also write CSV to this path")
    args = ap.parse_args()
    g = random.Random(args.seed)
    examples = generate_examples(g, args.count)
    rows: list[dict] = []
    for i, (subject, body, intended_type) in enumerate(examples):
        item = run_pipeline(body, "email", subject=subject)
        row = {
            "id": i + 1,
            "subject": subject,
            "body": body,
            "intended_type": intended_type,
            "lane": item.lane,
            "category": item.category,
            "priority": item.priority,
            "confidence": round(item.confidence, 4),
            "confidence_display": item.confidence_display,
            "suggested_action": item.suggested_action,
            "summary": item.summary[:120] + "..." if len(item.summary) > 120 else item.summary,
        }
        rows.append(row)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(rows)} examples to {out_path}")
    # Lane distribution
    by_lane: dict[str, int] = {}
    for r in rows:
        by_lane[r["lane"]] = by_lane.get(r["lane"], 0) + 1
    for lane in LANES:
        print(f"  {lane}: {by_lane.get(lane, 0)}")
    if args.csv:
        import csv
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "subject", "body", "intended_type", "lane", "category", "priority", "confidence"])
            w.writeheader()
            w.writerows([{k: r.get(k, "") for k in w.fieldnames} for r in rows])
        print(f"Wrote CSV to {csv_path}")


if __name__ == "__main__":
    main()
