# Intake Queue Quality: Trust in Mail Triage

**Goal:** Make one connected mailbox produce a queue that feels sane, trustworthy, and useful. No new architecture; no mailbox actions; no new integrations. Focus: noise handling, lane accuracy, scan-ability, conservative mirror-only.

---

## A. Classifier / rule improvements (Gmail-relevant)

Based on typical Gmail inflow and current rule behavior:

### 1. **Noise-first hints (before category)**

- **Subject junk signals:** If subject strongly suggests marketing/automated (see list below), either:
  - **Option (recommended):** Do not promote category confidence; treat as `other` with low confidence so lane logic can send to Likely junk, or
  - Add an explicit “likely_junk” hint that lane logic uses.
- **Patterns to treat as noise-prone (subject):**  
  `receipt|your order|order (?:confirm|shipped)|invitation:.*(?:calendar|event)|don't forget|reminder:.*(?:sale|offer)|verify (?:your )?email|confirm (?:your )?subscription|you have (?:a )?notification|your (?:weekly|daily) (?:digest|summary)|no reply|do not reply|noreply@|unsubscribe` (and existing newsletter/promo list in lanes).
- **Body:** Very short body (e.g. &lt; 30 chars) with no clinical keywords → keep as `other` and low confidence so lane can put in Likely junk when combined with subject.

### 2. **Tighten category rules**

- **records_request:** Current rule uses `\brecord(s)?\b|\brelease\b|\brequest\b|fax\s+record`. “Request” alone is too broad (e.g. “request a callback”, “schedule a request”). Tighten to:  
  - Require “record” or “release” (medical/chart context), or  
  - “request” only when near “record”, “release”, “chart”, “medical record”, “ROI”, “release of information”.  
  This reduces false positives from generic “request” in marketing or scheduling.
- **general_inquiry:** “inquir(y|ies)|question|contact” is broad. Consider requiring absence of strong marketing subject (or demote confidence when subject has promo keywords) so obvious marketing doesn’t get “general_inquiry”.
- **Lab/appointment overlap:** “Schedule” appears in both appointment and marketing (“schedule a demo”). Prefer **subject** for junk: if subject has “demo”, “webinar”, “limited time”, keep as `other` / low confidence. Optionally: “appointment” only when body also has “patient”, “reschedule”, “cancel”, “clinic”, “office” (clinical context).

### 3. **Confidence tuning**

- When subject matches junk patterns above: cap category confidence (e.g. max 0.4) so lane’s “other + low confidence” path reliably sends to Likely junk.
- When both subject and body are short and generic: set confidence to 0.2–0.3 so lane logic can treat as noise.

### 4. **No new headers required for MVP**

- We do not need to parse List-Unsubscribe or From for classifier in the first pass; subject + body are enough. Optionally store `from_address` (or a safe display slice) for **display only** so staff can quickly recognize senders; this does not change mirror-only.

---

## B. Metadata and display improvements (scan-ability)

So a human assistant can triage quickly:

### 1. **Always show and emphasize**

- **Subject** — Primary line on each card (bold or first line). Already present; make it the main identifier.
- **Created / received time** — Relative (“2h ago”, “Yesterday”) or short absolute (“Mar 11, 9:30a”). Enables “newest first” and “what’s old.”
- **Source label** — Which mailbox (e.g. “Gmail” or email address). Already in data; show it on the card when there are multiple mailboxes or for clarity.

### 2. **Within each lane**

- **Sort by `created_at` descending** (newest at top) so the most recent items are visible first.
- **Lane count** — Already present; keep it.

### 3. **Trust signals (no new backend fields)**

- **Category + priority** — Keep visible (e.g. small badges).
- **Confidence** — Keep “Cls. High/Medium/Low” so staff know when to double-check.
- **PHI** — Keep badge.
- **Suggested action** — Keep one line; can be secondary (e.g. smaller text).

### 4. **Optional for later**

- **From address** — If we capture it at ingest (read-only), show a truncated “From: name &lt;email&gt;” for recognition. Not required for first pass.

---

## C. Smallest set of test cases for sorting quality

Use these to validate classifier + lane placement without overbuilding. Each case: **(subject, body_snippet) → expected (category, lane)** or at least **lane**.

| # | Description | Subject (or “”) | Body snippet | Expected lane (min) | Expected category (optional) |
|---|-------------|-----------------|--------------|---------------------|------------------------------|
| 1 | True referral | “Referral for John Doe” | “Referring patient for cardiology follow-up.” | needs_attention or waiting_fyi | referral |
| 2 | Lab result | “Lab results ready” | “CBC panel results are available for review.” | needs_attention or waiting_fyi | lab_result |
| 3 | Marketing subject | “Don’t miss our 20% off sale” | “Limited time offer. Unsubscribe here.” | likely_junk | other |
| 4 | Receipt/order (Gmail common) | “Your receipt from Amazon” | “Thank you for your order.” | likely_junk | other |
| 5 | Calendar invite | “Invitation: Team standup” | “You have been invited to a meeting.” | likely_junk | other |
| 6 | Urgent clinical | “URGENT: Patient callback” | “Please call back ASAP regarding medication.” | needs_attention | (any) |
| 7 | Records request | “Records release request” | “Please process the attached ROI form.” | insurance_medical or waiting_fyi | records_request |
| 8 | Generic “request” (not records) | “Request a callback” | “Would like to schedule a call.” | waiting_fyi; not records_request | general_inquiry or other |
| 9 | Insurance | “Prior auth required” | “Patient needs prior authorization for procedure.” | insurance_medical | insurance |
| 10 | Short junk | “Your daily digest” | “See what you missed.” | likely_junk | other |
| 11 | Newsletter | “Newsletter: March updates” | “View in browser. Unsubscribe.” | likely_junk | other |
| 12 | Prescription | “Refill request” | “Patient requested medication refill.” | needs_attention or waiting_fyi | prescription |
| 13 | Appointment | “Appointment reminder” | “Your appointment is tomorrow at 10am.” | waiting_fyi | appointment |
| 14 | Low priority | “Routine follow-up” | “When convenient, please review.” | waiting_fyi | other |
| 15 | Ordering | “Shipment delayed” | “Your supply order has been delayed.” | ordering_supplies | other |

Implementation: a single test module (e.g. `tests/test_intake_quality.py` or `local_ai/intake/test_quality.py`) that runs pipeline (or classifier + lanes) on each case and asserts **lane** (and optionally category). Add/change cases as you see real Gmail misclassifications.

---

## D. Lightweight filters / search / sort (without overbuilding)

### 1. **API: GET /intake/queue**

- **Existing:** `limit` (1–500).
- **Add (query params):**
  - `lane` — filter by lane id (e.g. `likely_junk`, `needs_attention`). Optional.
  - `status` — filter by status (`new`, `reviewed`, `done`). Optional.
  - `search` — substring match in `subject` + `summary` (case-insensitive). Optional.
  - `sort` — `created_desc` (default) or `created_asc`. Optional.
- **Behavior:** Apply filters in memory (queue is in-memory); sort by `created_at`; then apply limit. No new storage layer.

### 2. **Frontend**

- **Lane filter** — Dropdown or tabs: “All lanes” | “Needs attention” | “Likely junk” | etc. Calls API with `?lane=...`.
- **Status filter** — “All” | “New” | “Reviewed” | “Done”. Calls API with `?status=...`.
- **Search** — Single text input; debounced (e.g. 300ms); calls API with `?search=...`. Clear button.
- **Sort** — Default “Newest first”; optional “Oldest first” toggle → `sort=created_asc`.
- Keep lane columns when “All lanes”; when a single lane is selected, show a single list (or same columns with one populated) so staff can focus. No need for saved views or complex UX.

### 3. **What we are not adding**

- No full-text search engine.
- No saved filters or user preferences (can add later if needed).
- No mailbox actions (move, archive, label, mark read).

---

## Summary

- **A.** Classifier: noise-first subject/body hints, cap confidence for junk subjects, tighten records_request and general_inquiry; optional clinical context for appointment/lab.
- **B.** Display: subject as primary, created_at relative, source_label; sort by created_at desc in lane.
- **C.** Tests: 15 minimal cases (subject + body → lane, optional category) in one test module.
- **D.** API + UI: optional `lane`, `status`, `search`, `sort` on GET /queue; simple filter dropdowns and search box.

This keeps mirror-only, avoids new integrations, and focuses on making the existing queue trustworthy and scannable.
