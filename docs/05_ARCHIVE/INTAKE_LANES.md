# Intake lane-based triage — proposal and rules

## Goal

Turn the flat intake queue into a **lane-based triage board** so morning triage is faster. Group items by operational lanes derived from existing `category`, `priority`, and `suggested_action`. No heavy AI; no mailbox automation (still mirror-only).

## Operating constraints (approved)

| Constraint | Behavior |
|------------|----------|
| **Lane placement** | Read-only and **derived only** at ingest. No API to edit lane; taxonomy is a first pass, not a final ontology. |
| **Noise / junk** | Items **remain in the queue** (Likely junk lane). Nothing is dropped after ingest. |
| **Mirror-only** | No mailbox move/archive/label/mark-read; ingestion stays read-only as documented in CLINIC_INTAKE. |
| **Confidence in UI** | Framed as **classifier confidence** (rule-based match strength)—not certainty or ground truth. |

---

## A. Lane rules

Lanes are **derived only** from current fields (no new model). One item → one lane. Order of evaluation matters: more specific rules first.

| Lane | Derivation rules |
|------|------------------|
| **Needs attention** | `priority == "urgent"` OR `suggested_action` contains "immediately" / "Review immediately" |
| **Insurance / MediCal** | `category == "insurance"` OR body/subject patterns for MediCal, prior auth, EOB, eligibility |
| **Ordering / Supplies** | `category` or `suggested_action` suggests orders/supplies; keywords: order, supply, shipment, reorder, formulary |
| **Waiting / FYI** | `priority == "low"` AND (`suggested_action` is "Review and triage" or similar) OR category is `general_inquiry` with low priority |
| **Likely junk / noise** | Detected by noise rules (see B) OR category `other` with very low confidence |
| **Default** | If no rule matches: **Needs attention** when priority is high/urgent, else **Waiting / FYI** |

Implementation: pure function `derive_lane(category, priority, suggested_action, subject, summary, is_noise)` in a small module used by the pipeline after classification. Pipeline sets `item.lane` before returning.

---

## B. Noise / junk rules

**Purpose:** Reduce clutter and triage trust. Do **not** delete or skip ingesting: still add to queue, but assign lane **Likely junk / noise** so staff can review or dismiss in one place.

**Signals (any can trigger; no heavy AI):**

- **Subject patterns:** Unsubscribe, opt-out, no longer wish, newsletter, promotion, discount, limited time, act now, click here, verify your account (common phishing), free shipping, % off, winner, congratulations (generic), notification from [marketing sender]. Case-insensitive.
- **From/List headers:** Not used in MVP (we don’t store From); can add later if we expose a safe sender hint.
- **Body/summary:** Very short body with mostly links; dominant presence of "unsubscribe", "view in browser", "image blocked"; subject + body both match promotional patterns.
- **Combination:** `category == "other"` AND classifier confidence &lt; 0.4 AND (subject or summary matches junk patterns) → treat as noise.

**Output:** Boolean `is_noise` (or a small score). Pipeline uses it to set `lane = "Likely junk / noise"` (overriding other lane logic when true). Items remain in queue; no mailbox changes.

---

## C. HTML cleanup approach

**Where:** `email_ingestion._normalize_body()` when we fall back to `text/html` (no `text/plain`).

**Current:** Strip tags with regex `&lt;[^&gt;]+&gt;`, collapse whitespace. Style/CSS and script content can leak into the extracted text.

**Improvements (lightweight, no new deps):**

1. **Remove &lt;script&gt;…&lt;/script&gt; and &lt;style&gt;…&lt;/style&gt; (and their contents)** before any other processing. Use regex or simple find/replace for block removal so script/style text never appears in the summary.
2. **Strip inline style/class from remaining tags:** Before stripping tags, remove `style="..."` and `class="..."` (and optionally `id="..."`) from tags so that when we replace tags by spaces, we don’t leave long attribute strings. Regex: remove `\s+(?:style|class|id)=["'][^"']*["']` from tag-like spans.
3. **Decode common HTML entities** in the final text: `&amp;`, `&lt;`, `&gt;`, `&quot;`, `&nbsp;` → space, and numeric entities where easy (e.g. `&#32;` → space). Python `html.unescape` is sufficient.
4. **Then:** strip tags, collapse whitespace, trim (as now). Optionally truncate very long runs of non-word characters.

All in the same place as current HTML handling; no BeautifulSoup required for MVP.

---

## D. Where confidence should come from

- **Source:** The existing **classifier** already returns `confidence` (float 0–1). It is based on keyword/match strength and category clarity.
- **Exposure:** Pipeline should take `classification["confidence"]` and:
  - Store a **display tier** on the item: `confidence_display: "high" | "medium" | "low"`:
    - `high`: confidence ≥ 0.7  
    - `medium`: confidence ≥ 0.4 and &lt; 0.7  
    - `low`: confidence &lt; 0.4  
  - Optionally keep raw `confidence` (float) in the item for future use; API can return both.
- **Use:** UI shows the tier (e.g. badge or label) so staff know how much to trust the category/lane. Lane logic can use confidence (e.g. "other" + low confidence → contribute to "Likely junk" lane).

---

## Implementation order

1. **Lane derivation** — Add `lane` to `IntakeItem` and derive it in the pipeline from category, priority, suggested_action (and later subject/summary for noise).
2. **Confidence** — Add `confidence` (float) and `confidence_display` (high/medium/low) to `IntakeItem`; pass classifier confidence through pipeline; expose in API and UI.
3. **Noise detection** — Small rule set over subject + summary (and body excerpt if available); set `is_noise` and force lane to "Likely junk / noise".
4. **HTML cleanup** — In `_normalize_body()`, add script/style removal, attribute stripping, entity decode, then existing tag strip.
5. **Frontend** — Lane-based triage board: one column per lane, cards in columns, show confidence; keep status dropdown and existing actions.

---

## Mirror-only reminder

No mailbox automation in this pass: no move, archive, label, or mark-read. All changes are to queue structure, classification, and UI only.
