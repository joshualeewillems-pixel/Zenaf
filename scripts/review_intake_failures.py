#!/usr/bin/env python3
"""
Minimal Streamlit UI to review exported intake failures (single or batch).

Mark each mismatch as: keep_expected | fix_expected | needs_rule_change | skip.
Optional reviewer note per case. Decisions and notes saved to a JSON file
(default: same dir as failures, intake_synthetic_reviews.json). Local-only:
no auth, no database, no external APIs.

Modes: Single (one case at a time) or Batch (multiple per page, save together).

Run from repo root:
  streamlit run scripts/review_intake_failures.py

Requires: streamlit (pip install streamlit)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FAILURES_PATH = ROOT / "datasets" / "intake_synthetic_failures.json"
DECISION_OPTIONS = ("keep_expected", "fix_expected", "needs_rule_change", "skip")


def load_failures(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _normalize_entry(raw: str | dict) -> dict:
    """One review entry: { decision, note, timestamp }."""
    if isinstance(raw, dict):
        return {
            "decision": raw.get("decision", ""),
            "note": raw.get("note", ""),
            "timestamp": raw.get("timestamp", ""),
        }
    return {"decision": (raw or ""), "note": "", "timestamp": ""}


def load_reviews(reviews_path: Path) -> dict[str, dict]:
    """Returns dict[case_id, { decision, note, timestamp }]."""
    if not reviews_path.is_file():
        return {}
    with open(reviews_path, encoding="utf-8") as f:
        data = json.load(f)
    decisions = data.get("decisions") if isinstance(data, dict) else data
    if not isinstance(decisions, dict):
        return {}
    return {k: _normalize_entry(v) for k, v in decisions.items()}


def save_reviews(reviews_path: Path, decisions: dict[str, dict]) -> None:
    """decisions: dict[case_id, { decision, note, timestamp }]."""
    reviews_path.parent.mkdir(parents=True, exist_ok=True)
    with open(reviews_path, "w", encoding="utf-8") as f:
        json.dump({"decisions": decisions}, f, indent=2, ensure_ascii=False)


def get_decision(decisions: dict[str, dict], case_id: str) -> str:
    entry = decisions.get(str(case_id)) or {}
    return entry.get("decision", "") if isinstance(entry, dict) else str(entry)


def main() -> None:
    st.set_page_config(page_title="Review intake failures", layout="wide")
    st.title("Review intake failures")

    failures_path = Path(
        st.sidebar.text_input("Failures JSON path", value=str(DEFAULT_FAILURES_PATH))
    )
    default_reviews = str(failures_path.parent / "intake_synthetic_reviews.json")
    reviews_path = Path(st.sidebar.text_input("Reviews JSON path", value=default_reviews))

    failures = load_failures(failures_path)
    if not failures:
        st.warning(f"No failures found at {failures_path}. Run the evaluator with --export-failures first.")
        return

    decisions = load_reviews(reviews_path)

    # Filters (sidebar) — empty selection = no filter; all unique values so rare ones (e.g. adversarial) appear
    def all_values(items: list[dict], key: str) -> list[str]:
        vals = [str(m.get(key, "") or "") for m in items]
        return sorted(set(vals), key=lambda v: (v == "", v.lower()))

    st.sidebar.markdown("### Filters")
    difficulties = all_values(failures, "difficulty")
    expected_lanes = all_values(failures, "expected_lane")
    actual_lanes = all_values(failures, "actual_lane")

    filter_difficulty = st.sidebar.multiselect("Difficulty", options=difficulties, default=[], key="filter_diff")
    filter_expected_lane = st.sidebar.multiselect("Expected lane", options=expected_lanes, default=[], key="filter_exp_lane")
    filter_actual_lane = st.sidebar.multiselect("Actual lane", options=actual_lanes, default=[], key="filter_act_lane")

    def apply_filters(items: list[dict]) -> list[dict]:
        out = items
        if filter_difficulty:
            out = [m for m in out if (str(m.get("difficulty") or "") in filter_difficulty)]
        if filter_expected_lane:
            out = [m for m in out if (str(m.get("expected_lane") or "") in filter_expected_lane)]
        if filter_actual_lane:
            out = [m for m in out if (str(m.get("actual_lane") or "") in filter_actual_lane)]
        return out

    filtered = apply_filters(failures)
    hide_reviewed = st.sidebar.checkbox("Hide already reviewed", value=False, key="hide_reviewed")
    if hide_reviewed:
        filtered = [m for m in filtered if get_decision(decisions, m.get("id", "")) == ""]

    if not filtered:
        st.warning("No cases match the current filters.")
        return

    mode = st.sidebar.radio("Mode", ["Single", "Batch"], key="review_mode")
    batch_size = 20
    if mode == "Batch":
        batch_size = st.sidebar.number_input("Batch size", min_value=5, max_value=100, value=20, step=5, key="batch_size")
        if "batch_start" not in st.session_state:
            st.session_state.batch_start = 0
        batch_start = max(0, min(st.session_state.batch_start, len(filtered) - 1))
        batch_end = min(batch_start + batch_size, len(filtered))
        batch_items = filtered[batch_start:batch_end]
        num_batches = (len(filtered) + batch_size - 1) // batch_size
        current_batch_num = (batch_start // batch_size) + 1 if batch_size else 1
        st.sidebar.caption(f"Batch {current_batch_num} of {num_batches} ({len(batch_items)} items)")
        reviewed_count = sum(1 for e in decisions.values() if (e.get("decision") if isinstance(e, dict) else e) in DECISION_OPTIONS)
        st.sidebar.caption(f"Decided: {reviewed_count} | In file: {len(decisions)}")

        st.subheader("Batch review")
        st.caption(f"Cases {batch_start + 1}–{batch_end} of {len(filtered)}. Set decision and optional note, then **Save this batch**.")

        pending: dict[str, dict] = {}
        for i, m in enumerate(batch_items):
            case_id = m.get("id", batch_start + i)
            sid = str(case_id)
            entry = decisions.get(sid) or {}
            if isinstance(entry, dict):
                cur_dec = entry.get("decision", "")
                cur_note = entry.get("note", "")
            else:
                cur_dec = str(entry)
                cur_note = ""

            with st.container():
                st.markdown(f"### Case {case_id}")
                st.text("Subject: " + (m.get("subject") or "(no subject)"))
                st.caption(f"Difficulty: {m.get('difficulty', '—')}")
                st.markdown("**Expected**")
                st.caption(f"Category: {m.get('expected_category', '—')}  ·  Lane: {m.get('expected_lane', '—')}")
                st.markdown("**Actual**")
                st.caption(f"Category: {m.get('actual_category', '—')}  ·  Lane: {m.get('actual_lane', '—')}")
                conf = m.get("confidence")
                conf_disp = m.get("confidence_display", conf)
                st.caption(f"Confidence: {conf_disp if conf_disp is not None else '—'}")
                for label, key in [
                    ("Signal codes", "signal_codes"),
                    ("Interpretation codes", "interpretation_codes"),
                    ("Policy codes", "policy_codes"),
                ]:
                    vals = m.get(key)
                    if vals is not None and (isinstance(vals, list) and len(vals) > 0 or vals):
                        st.caption(f"{label}: {', '.join(str(x) for x in vals) if isinstance(vals, list) else vals}")
                st.text("Summary: " + (m.get("summary") or "—"))
                st.text("Suggested action: " + (m.get("suggested_action") or "—"))
                with st.expander("Body"):
                    st.text(m.get("body", ""))
                st.markdown("**Your decision**")
                col_dec, col_note = st.columns([1, 2])
                opts = [""] + list(DECISION_OPTIONS)
                try:
                    dec_index = opts.index(cur_dec) if cur_dec else 0
                except ValueError:
                    dec_index = 0
                with col_dec:
                    dec = st.selectbox(
                        "Decision",
                        options=opts,
                        index=dec_index,
                        key=f"batch_dec_{sid}",
                        label_visibility="collapsed",
                    )
                with col_note:
                    note = st.text_area("Note", value=cur_note, key=f"batch_note_{sid}", height=60, label_visibility="collapsed", placeholder="Optional note")
                pending[sid] = {"decision": dec, "note": (note or "").strip()}
                st.divider()

        if st.button("Save this batch", type="primary", key="save_batch"):
            ts = datetime.now(timezone.utc).isoformat()
            for sid, p in pending.items():
                if p["decision"] or p["note"]:
                    decisions[sid] = {
                        "decision": p["decision"] or (decisions.get(sid) or {}).get("decision", ""),
                        "note": p["note"],
                        "timestamp": ts,
                    }
            save_reviews(reviews_path, decisions)
            st.session_state.batch_start = min(batch_end, len(filtered) - 1)
            st.success(f"Saved {len([p for p in pending.values() if p['decision'] or p['note']])} entries.")
            st.rerun()

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Previous batch", key="batch_prev") and batch_start > 0:
                st.session_state.batch_start = max(0, batch_start - batch_size)
                st.rerun()
        with c2:
            if st.button("Next batch", key="batch_next") and batch_end < len(filtered):
                st.session_state.batch_start = batch_end
                st.rerun()
        with c3:
            jump_batch = st.number_input("Go to batch #", min_value=1, max_value=num_batches, value=current_batch_num, key="jump_batch")
            if st.button("Go to batch", key="batch_go") and jump_batch != current_batch_num:
                st.session_state.batch_start = (jump_batch - 1) * batch_size
                st.rerun()

        return

    # --- Single mode below ---
    if "index" not in st.session_state:
        st.session_state.index = 0
    idx = st.session_state.index
    idx = max(0, min(idx, len(filtered) - 1))
    st.session_state.index = idx

    m = filtered[idx]
    case_id = m.get("id", idx)
    entry = decisions.get(str(case_id)) or {}
    if isinstance(entry, dict):
        current_decision = entry.get("decision", "")
        current_note = entry.get("note", "")
    else:
        current_decision = str(entry)
        current_note = ""

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Item {idx + 1} of {len(filtered)} (of {len(failures)} total)")
    st.sidebar.progress((idx + 1) / len(filtered))
    reviewed_count = sum(1 for e in decisions.values() if (e.get("decision") if isinstance(e, dict) else e) in DECISION_OPTIONS)
    st.sidebar.caption(f"Decided: {reviewed_count} | In file: {len(decisions)}")

    # Main: case id + subject
    st.subheader(f"Case id: {case_id}")
    st.markdown("**Subject**")
    st.text(m.get("subject", "(no subject)"))

    # Clear comparison block
    st.markdown("---")
    st.markdown("**Difficulty**")
    st.text(m.get("difficulty", "—"))

    st.markdown("**Expected**")
    c1, c2 = st.columns(2)
    with c1:
        st.text(f"Category: {m.get('expected_category', '—')}")
    with c2:
        st.text(f"Lane: {m.get('expected_lane', '—')}")

    st.markdown("**Actual**")
    c3, c4 = st.columns(2)
    with c3:
        st.text(f"Category: {m.get('actual_category', '—')}")
    with c4:
        st.text(f"Lane: {m.get('actual_lane', '—')}")

    st.markdown("**Confidence**")
    conf = m.get("confidence")
    conf_disp = m.get("confidence_display", conf)
    st.text(f"{conf_disp}" if conf_disp is not None else "—")

    st.markdown("**Codes**")
    for label, key in [
        ("Signal codes", "signal_codes"),
        ("Interpretation codes", "interpretation_codes"),
        ("Policy codes", "policy_codes"),
    ]:
        vals = m.get(key)
        if vals is not None and (isinstance(vals, list) and len(vals) > 0 or vals):
            st.text(f"{label}: {', '.join(str(x) for x in vals) if isinstance(vals, list) else vals}")
        else:
            st.caption(f"{label}: —")

    st.markdown("**Summary**")
    st.text(m.get("summary", ""))
    st.markdown("**Suggested action**")
    st.text(m.get("suggested_action", ""))

    with st.expander("Body"):
        st.text(m.get("body", ""))

    st.markdown("---")
    st.markdown("**Reviewer note**")
    note_value = st.text_area("Optional note for this case", value=current_note, key="review_note", height=100, label_visibility="collapsed")

    st.markdown("**Decision**")
    cols = st.columns(5)
    for i, opt in enumerate(DECISION_OPTIONS):
        with cols[i]:
            if st.button(opt.replace("_", " ").title(), key=opt):
                decisions[str(case_id)] = {
                    "decision": opt,
                    "note": (note_value or "").strip(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                save_reviews(reviews_path, decisions)
                st.session_state.index = min(idx + 1, len(filtered) - 1)
                st.rerun()
    with cols[4]:
        if st.button("Save note only", key="save_note"):
            decisions[str(case_id)] = {
                "decision": current_decision,
                "note": (note_value or "").strip(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            save_reviews(reviews_path, decisions)
            st.rerun()
    if current_decision:
        st.info(f"Current decision: **{current_decision}**")

    st.sidebar.markdown("---")
    if st.sidebar.button("Previous", key="prev") and idx > 0:
        st.session_state.index = idx - 1
        st.rerun()
    if st.sidebar.button("Next", key="next") and idx < len(filtered) - 1:
        st.session_state.index = idx + 1
        st.rerun()
    jump = st.sidebar.number_input("Jump to index (0-based)", min_value=0, max_value=max(0, len(filtered) - 1), value=idx, key="jump_idx")
    if st.sidebar.button("Go", key="go") and jump != idx:
        st.session_state.index = jump
        st.rerun()


if __name__ == "__main__":
    main()
