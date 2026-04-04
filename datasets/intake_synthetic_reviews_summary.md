# Intake synthetic reviews summary

From `datasets/intake_synthetic_reviews.json`.

---

## 1) needs_rule_change (5 cases)

| ID  | Subject / situation | Expected | Actual | Reviewer note |
|-----|---------------------|----------|--------|----------------|
| 18  | "Save on your prescription" / body: refill, save 20%, Unsubscribe | other → likely_junk | prescription → needs_attention | Medical + marketing keywords together → treat as marketing |
| 222 | "No reply" / body: Prior authorization required, submit to billing | insurance → insurance_medical | insurance → likely_junk | Clinical/billing keywords should override junk; insurance should not route to likely_junk |
| 263 | "Notification from System" / body: New lab results, CBC panel | lab_result → needs_attention | lab_result → likely_junk | Clinical notifications should override junk; lab alerts → needs_attention |
| 268 | "Request for information" / body: …request callback… **Not a records request.** | general_inquiry → waiting_fyi | records_request → insurance_medical | Phrase "not a records request" should suppress records_request |
| 413 | "Referral for Patient" / body: Congratulations! Act now. Unsubscribe. | other → likely_junk | other → waiting_fyi | Marketing signals should override; referral wording used as spam bait → should be likely_junk |

---

## 2) fix_expected (16 cases)

**Meaning:** Pipeline behavior is correct; the synthetic dataset’s *expected* label is wrong.

| Pattern | Count | Case IDs | Reviewer note |
|---------|-------|----------|----------------|
| Referral questions | 14 | 5, 9, 27, 37, 42, 47, 66, 75, 80, 97, 117, 121, 125, 134 | "I have a question about my referral" → should be referral / needs_attention; dataset incorrectly labeled general_inquiry / waiting_fyi |
| Payment confirmation | 1 | 51 | "Your payment was received" → legitimate notification; waiting_fyi correct; dataset had expected likely_junk |
| Subject-only lab, empty body | 1 | 208 | Subject hints lab, content empty → should default waiting_fyi; fix expected |
| EOB informational | 1 | 370 | EOB "no action needed" → waiting_fyi correct; dataset expected insurance_medical |

**Action:** Update synthetic dataset expected_category / expected_lane for these IDs; no classifier or lane code change.

---

## 3) Rule proposals (from needs_rule_change)

### 3.1 Medical + marketing mixed (case 18)

**Problem:** Prescription/refill/medication keywords plus strong marketing (save %, unsubscribe) → currently classified as prescription → needs_attention; should be treated as marketing → likely_junk.

**Classifier proposal:**

- **Rule:** If body/subject contains both (a) medical terms: `prescription`, `refill`, `medication` and (b) marketing terms: `unsubscribe`, `save\s*\d+%`, `sale`, `offer`, then do **not** classify as prescription. Prefer `category = "other"` and set confidence low (e.g. 0.35).
- **Signal:** Add `signal_medical_marketing_mixed` when both sets match. Lane policy can then send to likely_junk when this signal is present.

**Lane proposal:** In `derive_lane` or `_is_noise`, when `signal_medical_marketing_mixed` is in signal_codes, treat as noise and return `likely_junk` (or add an explicit branch before clinical categories).

---

### 3.2 Clinical category overrides junk subject (cases 222, 263)

**Problem:** Subject matches junk patterns ("no reply", "notification from") so confidence is capped and/or _is_noise sends to likely_junk, even when category is insurance or lab_result and body is clearly clinical.

**Lane policy proposal:**

- **Rule:** In `lanes.derive_lane`, evaluate noise **after** category-based lanes, or add an override: if category is `insurance` or `lab_result`, do **not** send to likely_junk based on subject junk alone.
- **Implementation options:**  
  - (A) In `_is_noise`, add: if `category in ("insurance", "lab_result")` return False.  
  - (B) In `derive_lane`, call `_is_noise(...)` only when the category-based branch would not already assign needs_attention or insurance_medical; or after computing a candidate lane, if it is likely_junk but category is insurance or lab_result, override to insurance_medical or needs_attention respectively.
- **Signal:** Keep `signal_subject_junk_hint`; add policy_code when overridden, e.g. `policy_clinical_overrides_junk_subject`.

**Suggested signal_codes:** No new classifier signal; use existing `signal_subject_junk_hint` plus new policy_code `policy_clinical_overrides_junk_subject` when lane is overridden from likely_junk to insurance_medical/needs_attention.

---

### 3.3 Records-request negation (case 268)

**Problem:** Body says "Not a records request" but phrase "request" + "record" still triggers records_request.

**Classifier proposal:**

- **Rule:** Before or after the records_request pattern, check for negation phrases, e.g. `not a records request`, `not requesting (?:my )?records`, `not a (?:medical )?record release`. If found, do **not** set category to records_request; use general_inquiry or other and lower confidence.
- **Signal:** Add `signal_records_request_negated` when negation is detected (for auditing). Alternatively, simply suppress or override the records_request classification when negation is present and do not emit `signal_records_release_context` for that case.

---

### 3.4 Referral subject + marketing body (case 413)

**Problem:** Subject "Referral for Patient" but body is pure marketing ("Congratulations! Act now. Unsubscribe."). Currently classified other → waiting_fyi; should be likely_junk.

**Classifier / lane proposal:**

- **Rule (lane):** In `_is_noise`, extend body/summary checks: if combined subject+summary contains strong marketing (e.g. `congratulations`, `act now`, `unsubscribe`) and also "referral" in subject, but body does not contain substantive referral context (e.g. patient name, referring provider, clinical reason), treat as noise.  
  Or: in classifier, if subject matches referral but body is dominated by marketing buzzwords (e.g. "act now", "unsubscribe", "selected", "congratulations") without referral detail, set category to other and confidence to 0.35 so _is_noise can send to likely_junk.
- **Signal (optional):** `signal_marketing_body_referral_subject` when subject hints referral but body is marketing-only.

---

## 4) Concise rule checklist

| # | Rule | Where | Suggested signal_codes / policy_codes |
|---|------|--------|----------------------------------------|
| 1 | Medical + marketing coexistence → other, low conf; lane → likely_junk | classifier + lanes | `signal_medical_marketing_mixed`; lane uses it for likely_junk |
| 2 | category insurance/lab_result overrides subject junk → do not send to likely_junk | lanes (`_is_noise` or `derive_lane`) | `policy_clinical_overrides_junk_subject` |
| 3 | "Not a records request" (and similar) → suppress records_request | classifier | `signal_records_request_negated` or suppress `signal_records_release_context` |
| 4 | Referral in subject + marketing body only → other + noise | classifier and/or lanes | optional `signal_marketing_body_referral_subject` |

---

## 5) fix_expected dataset updates (no code change)

Update `intake_synthetic_cases.json` (or the source used to generate failures) so that:

- **Referral questions (14 cases):** expected_category = `referral`, expected_lane = `needs_attention`.
- **51:** expected_lane = `waiting_fyi` (keep expected_category as is).
- **208:** expected_category / expected_lane = appropriate for “subject-only, empty body” (e.g. waiting_fyi).
- **370:** expected_lane = `waiting_fyi`.

This keeps the evaluator aligned with reviewer intent without changing pipeline behavior.

---

## 6) Post-implementation (rule changes + dataset corrections)

**Evaluator run after implementation:** `python scripts/evaluate_intake_synthetic_data.py`

- **Total cases:** 450  
- **Category match:** 442 / 450 (98.2%)  
- **Lane match:** 443 / 450 (98.4%)  
- **Both match:** 440 / 450 (97.8%)  
- **Mismatches:** 10  

**Reviewed needs_rule_change cases (5):**  
- **18** (medical+marketing): now other → likely_junk ✓  
- **222** (no reply + prior auth): now insurance → insurance_medical ✓  
- **263** (notification + lab): now lab_result → needs_attention ✓  
- **268** (not a records request): now lane waiting_fyi ✓ (category is appointment due to “appointment” in body; records_request suppressed)  
- **413** (referral subject + marketing body): now other → likely_junk ✓  

**Regression tests:** `tests/test_intake_synthetic_regression.py` — 21 cases, all passing (includes the 5 needs_rule_change behaviors above).
