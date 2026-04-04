import requests
import textwrap

API_BASE = "http://127.0.0.1:8010"  # adjust if you changed the host/port

def fetch_queue():
    # No lane filter here so we can match the UI's effective lane
    resp = requests.get(f"{API_BASE}/intake/queue", params={"limit": 500})
    resp.raise_for_status()
    return resp.json()

def fetch_judgment(item_id: str):
    resp = requests.get(f"{API_BASE}/intake/queue/{item_id}/judgment")
    # If no judgment or error, just return an empty chain
    if not resp.ok:
        return {"item_id": item_id, "chain": []}
    return resp.json()

def main():
    items = fetch_queue()
    # UI behavior: effective lane = lane_override or lane
    needs_items = [
        it for it in items
        if (it.get("lane_override") or it.get("lane") or "").lower() == "needs_attention"
    ]

    print(f"Needs attention items: {len(needs_items)}\n")

    for idx, it in enumerate(needs_items, start=1):
        subject = it.get("subject") or "(No subject)"
        sender = it.get("source_label") or "-"
        created = it.get("created_at") or "-"
        category = it.get("category") or "-"
        priority = it.get("priority") or "-"
        conf_disp = it.get("confidence_display") or it.get("confidence")
        suggested = it.get("suggested_action") or "-"
        summary = it.get("summary") or "-"
        has_phi = bool(it.get("has_phi"))
        status = it.get("status") or "new"

        print(f"{'='*80}")
        print(f"{idx}. {subject}")
        print(f"   From: {sender}")
        print(f"   When: {created}")
        print(f"   Status: {status}")
        print(f"   Category: {category} | Priority: {priority} | Confidence: {conf_disp}"
              + (" | PHI" if has_phi else ""))
        print(f"   Suggested: {suggested}")
        print("   Summary:")
        for line in textwrap.wrap(summary, width=76, initial_indent="      ", subsequent_indent="      "):
            print(line)

        # Fetch Why? (judgment chain)
        jid = it.get("judgment_id")
        if not jid:
            print("\n   Why?: (no judgment_id on item)\n")
            continue

        j = fetch_judgment(it["id"])
        chain = j.get("chain") or []
        print("\n   Why? (judgment chain):")
        if not chain:
            print("      (no judgment record)")
            continue

        for j_idx, rec in enumerate(chain, start=1):
            label = "Original" if j_idx == 1 and len(chain) > 1 else (
                "Correction" if len(chain) > 1 else "Judgment"
            )
            lane = (rec.get("proposed_action") or {}).get("lane")
            print(f"      [{j_idx}] {label}"
                  + (f" → lane={lane}" if lane is not None else ""))

            if rec.get("correction_note"):
                print(f"         Note: {rec['correction_note']}")

            sig = rec.get("signal_codes") or []
            if sig:
                print(f"         signal_codes: {', '.join(sig)}")

            interp = rec.get("interpretation_codes") or []
            if interp:
                print(f"         interpretation_codes: {', '.join(interp)}")

            policy = rec.get("policy_codes") or []
            if policy:
                print(f"         policy_codes: {', '.join(policy)}")

            obs = rec.get("observation_ref") or {}
            if obs:
                sp = (obs.get("subject_preview") or "")[:80]
                bl = obs.get("body_length", 0)
                ms = obs.get("matched_signals") or []
                extra = f"matched_signals={', '.join(ms)}" if ms else "no matched_signals"
                print(f"         observation: subject_preview='{sp}', body_length={bl}, {extra}")

        print()  # blank line between items

if __name__ == "__main__":
    main()