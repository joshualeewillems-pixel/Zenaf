#!/usr/bin/env python3
"""
Personal inbox cleanup report.

Reads messages from an mbox file or a simple JSONL file (one JSON object per line with
{"subject": "...", "body": "...", "from": "...", "date": "..."}) and:
- Classifies each message into a coarse personal-inbox context.
- Updates sender/domain reputation.
- Prints a summary of top senders, top domains, and context breakdown.

Usage (from repo root):

  python scripts/personal_inbox_report.py --mbox path/to/mailbox.mbox
  python scripts/personal_inbox_report.py --jsonl path/to/messages.jsonl
"""
from __future__ import annotations

import argparse
import json
import mailbox
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Dict, Any, List

ROOT = Path(__file__).resolve().parent.parent

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.personal_inbox import classify_personal_message  # noqa: E402
from local_ai.personal_inbox.reputation import Reputation, load_reputation, save_reputation, update_reputation  # noqa: E402


def _iter_mbox(path: Path) -> Iterable[Dict[str, Any]]:
    mbox = mailbox.mbox(str(path))
    for msg in mbox:
        subj = msg.get("subject") or ""
        sender = msg.get("from") or ""
        date_hdr = msg.get("date") or ""
        try:
            dt = parsedate_to_datetime(date_hdr)
            ts = dt.isoformat()
        except Exception:
            ts = ""
        # Extract a simple text body
        body = ""
        try:
            if msg.is_multipart():
                parts = []
                for part in msg.walk():
                    ctype = part.get_content_type()
                    if ctype == "text/plain":
                        try:
                            parts.append((part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", errors="ignore"))
                        except Exception:
                            continue
                body = "\n".join(parts)
            else:
                body = (msg.get_payload(decode=True) or b"").decode(msg.get_content_charset() or "utf-8", errors="ignore")
        except Exception:
            body = ""
        yield {"subject": subj, "body": body, "from": sender, "date": ts}


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            yield {
                "subject": obj.get("subject") or "",
                "body": obj.get("body") or "",
                "from": obj.get("from") or obj.get("sender") or "",
                "date": obj.get("date") or "",
            }


def _subject_stem(subject: str) -> str:
    """Normalize a subject line into a short stem for clustering."""
    s = (subject or "").strip().lower()
    # Strip common reply/forward prefixes
    s = re.sub(r"^(re|fwd?|fw)\s*:\s*", "", s)
    # Drop trailing bracketed tags, e.g. [List], [Promo]
    s = re.sub(r"\s*\[[^\]]+\]\s*$", "", s)
    # Collapse digits (dates, ids) to '#'
    s = re.sub(r"\d+", "#", s)
    s = s.strip()
    if len(s) > 60:
        s = s[:60]
    return s or "(no subject)"


@dataclass
class Cluster:
    key: str
    kind: str  # 'domain' | 'sender' | 'subject'
    total: int = 0
    context_counts: Counter = field(default_factory=Counter)
    sample_subjects: List[str] = field(default_factory=list)
    sample_senders: List[str] = field(default_factory=list)
    last_seen: str = ""
    sample_messages: List[Dict[str, str]] = field(default_factory=list)


def _update_cluster(cl: Cluster, *, subject: str, sender: str, context: str, ts: str) -> None:
    cl.total += 1
    cl.context_counts[context] += 1
    if subject and subject not in cl.sample_subjects and len(cl.sample_subjects) < 5:
        cl.sample_subjects.append(subject)
    if sender and sender not in cl.sample_senders and len(cl.sample_senders) < 5:
        cl.sample_senders.append(sender)
    if ts and (not cl.last_seen or ts > cl.last_seen):
        cl.last_seen = ts


def main() -> None:
    ap = argparse.ArgumentParser(description="Personal inbox cleanup report")
    ap.add_argument("--mbox", type=str, help="Path to mbox file")
    ap.add_argument("--jsonl", type=str, help="Path to JSONL file with messages")
    ap.add_argument("--update-reputation", action="store_true", help="Update personal_inbox_reputation.json with observed senders/domains")
    ap.add_argument("--interactive", action="store_true", help="Start the clustering-first cleanup shell")
    ap.add_argument("--mode", choices=["dry_run", "apply"], default="dry_run", help="dry_run logs decisions only; apply is for future mailbox actions")
    ap.add_argument("--decision-log", type=str, default="personal_inbox_cluster_decisions.jsonl", help="Path to append cluster decisions (JSONL)")
    args = ap.parse_args()

    src: Iterable[Dict[str, Any]]
    if args.mbox:
        src = _iter_mbox(Path(args.mbox))
    elif args.jsonl:
        src = _iter_jsonl(Path(args.jsonl))
    else:
        ap.error("Provide --mbox or --jsonl")
        return

    rep: Reputation = load_reputation()
    sender_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    context_counts: Counter[str] = Counter()
    total_messages = 0

    domain_clusters: Dict[str, Cluster] = {}
    sender_clusters: Dict[str, Cluster] = {}
    subject_clusters: Dict[str, Cluster] = {}

    for msg in src:
        subject = msg.get("subject") or ""
        body = msg.get("body") or ""
        sender = (msg.get("from") or "").strip().lower()
        ts = msg.get("date") or ""
        ctx = classify_personal_message(subject, body, sender=sender)
        context = ctx.get("context") or "review_manually"
        context_counts[context] += 1
        total_messages += 1

        sender_counts[sender] += 1
        if "@" in sender:
            _, dom = sender.split("@", 1)
            domain_counts[dom.strip().lower()] += 1

        if args.update_reputation and sender:
            update_reputation(rep, sender_email=sender, context=context, timestamp=ts)

        # Clusters
        if "@" in sender:
            _, dom = sender.split("@", 1)
            dom = dom.strip().lower()
            if dom:
                c = domain_clusters.get(dom)
                if not c:
                    c = domain_clusters[dom] = Cluster(key=dom, kind="domain")
                _update_cluster(c, subject=subject, sender=sender, context=context, ts=ts)
                if len(c.sample_messages) < 10:
                    c.sample_messages.append({"sender": sender, "subject": subject, "context": context})
        if sender:
            cs = sender_clusters.get(sender)
            if not cs:
                cs = sender_clusters[sender] = Cluster(key=sender, kind="sender")
            _update_cluster(cs, subject=subject, sender=sender, context=context, ts=ts)
            if len(cs.sample_messages) < 10:
                cs.sample_messages.append({"sender": sender, "subject": subject, "context": context})
        stem = _subject_stem(subject)
        csu = subject_clusters.get(stem)
        if not csu:
            csu = subject_clusters[stem] = Cluster(key=stem, kind="subject")
        _update_cluster(csu, subject=subject, sender=sender, context=context, ts=ts)
        if len(csu.sample_messages) < 10:
            csu.sample_messages.append({"sender": sender, "subject": subject, "context": context})

    if args.update_reputation:
        save_reputation(rep)

    if not args.interactive:
        print("Personal inbox context breakdown:")
        total = sum(context_counts.values())
        for ctx, cnt in context_counts.most_common():
            pct = (cnt / total * 100) if total else 0.0
            print(f"- {ctx:18s}: {cnt:6d} ({pct:5.1f}%)")

        print("\nTop senders by volume:")
        for sender, cnt in sender_counts.most_common(20):
            if not sender:
                continue
            pct = (cnt / total * 100) if total else 0.0
            print(f"- {sender:<40s} {cnt:6d} ({pct:5.1f}%)")

        print("\nTop domains by volume:")
        for dom, cnt in domain_counts.most_common(20):
            pct = (cnt / total * 100) if total else 0.0
            print(f"- {dom:<30s} {cnt:6d} ({pct:5.1f}%)")
        return

    # Interactive clustering-first shell
    log_path = Path(args.decision_log)
    print("=" * 80)
    print("Personal Inbox Cleanup shell (clustering-first)")
    print(f"Total messages scanned: {total_messages}")
    print(f"Mode: {args.mode}")
    print(f"Decision log: {log_path}")
    print("\nTop domain clusters:")
    top_domains = sorted(domain_clusters.values(), key=lambda c: c.total, reverse=True)[:10]
    for idx, cl in enumerate(top_domains, start=1):
        if cl.total <= 0:
            continue
        if cl.context_counts:
            dom_ctx, dom_cnt = cl.context_counts.most_common(1)[0]
            pct = (dom_cnt / cl.total * 100.0) if cl.total else 0.0
        else:
            dom_ctx, pct = "unknown", 0.0
        print(f"{idx:2d}. {cl.key:<30s} {cl.total:6d}  {dom_ctx:18s} {pct:4.0f}%")

    # Session tracking for coverage and summary
    session_clusters_reviewed = 0
    session_messages_covered = 0
    action_counts: Counter[str] = Counter()
    suppressed_domains: Counter[str] = Counter()
    suppressed_senders: Counter[str] = Counter()
    created_rules: List[Dict[str, str]] = []
    quit_shell = False

    def dominant_context(cluster: Cluster) -> tuple[str, float]:
        if not cluster.context_counts or cluster.total <= 0:
            return "unknown", 0.0
        ctx, cnt = cluster.context_counts.most_common(1)[0]
        return ctx, (cnt / cluster.total * 100.0)

    def suggest_action(cluster: Cluster) -> str:
        ctx, pct = dominant_context(cluster)
        if ctx == "newsletter_media" and pct >= 80.0:
            return "label_newsletters_archive"
        if ctx == "junk_promo" and pct >= 80.0:
            return "label_promos_archive"
        if ctx in {"account_fyi"} and pct >= 70.0:
            return "archive_all"
        if ctx in {"important_personal", "transactional_action"}:
            return "skip"
        return "review"

    def confirm_apply(action_label: str, cluster: Cluster) -> bool:
        print(f"\nSelected action: {action_label} for {cluster.kind} cluster '{cluster.key}' "
              f"({cluster.total} messages) in mode={args.mode}")
        if args.mode == "dry_run":
            print("dry_run mode: this will be logged as 'would apply', no mailbox changes.")
        else:
            print("apply mode: this is eligible for future mailbox actions (none implemented yet).")
        ans = input("Proceed? [y/N] ").strip().lower()
        return ans == "y"

    def review_samples(cluster: Cluster) -> None:
        if not cluster.sample_messages:
            print("No sample messages captured for this cluster.")
            return
        print(f"\nSample messages for {cluster.kind} cluster '{cluster.key}':")
        idx = 0
        while idx < len(cluster.sample_messages):
            msg = cluster.sample_messages[idx]
            sender = msg.get("sender") or ""
            subject = msg.get("subject") or ""
            ctx = msg.get("context") or "review_manually"
            print("-" * 80)
            print(f"{idx+1}/{len(cluster.sample_messages)}")
            print(f"Sender  : {sender}")
            print(f"Subject : {subject}")
            print(f"Context : {ctx}")
            new_ctx = input("Press Enter to keep context, or type a new context label (or 'b' to go back): ").strip()
            if new_ctx.lower() == "b":
                break
            if new_ctx:
                # Adjust cluster-level counts
                cluster.context_counts[ctx] -= 1
                if cluster.context_counts[ctx] <= 0:
                    del cluster.context_counts[ctx]
                cluster.context_counts[new_ctx] += 1
                msg["context"] = new_ctx
                print(f"Updated context to '{new_ctx}' for this sample.")
            idx += 1

    # Open log file once for the shell session
    with log_path.open("a", encoding="utf-8") as logf:
        while True:
            print("\nCluster type to review:")
            print("1. domain (recommended first)")
            print("2. sender")
            print("3. subject pattern")
            print("q. quit")
            choice = input("> ").strip().lower()
            if choice in {"", "1"}:
                cluster_kind = "domain"
            elif choice == "2":
                cluster_kind = "sender"
            elif choice == "3":
                cluster_kind = "subject"
            elif choice == "q":
                print("Exiting Personal Inbox Cleanup shell.")
                break
            else:
                print("Please choose 1, 2, 3, or q.")
                continue

            if cluster_kind == "domain":
                clusters = list(domain_clusters.values())
            elif cluster_kind == "sender":
                clusters = list(sender_clusters.values())
            else:
                clusters = list(subject_clusters.values())

            clusters.sort(key=lambda c: c.total, reverse=True)
            if not clusters:
                print(f"No {cluster_kind} clusters available.")
                continue

            page_size = 20
            page = 0
            while True:
                start = page * page_size
                end = start + page_size
                if start >= len(clusters):
                    print("No more clusters.")
                    break
                covered_pct = (session_messages_covered / total_messages * 100.0) if total_messages else 0.0
                print(f"\nClusters ({cluster_kind}) - reviewed {session_clusters_reviewed} clusters "
                      f"covering {session_messages_covered} messages ({covered_pct:4.1f}% of mailbox):")
                for idx, cl in enumerate(clusters[start:end], start=start + 1):
                    ctx, pct = dominant_context(cl)
                    print(f"{idx:4d}. {cl.key:<30s} {cl.total:6d}  {ctx:18s} {pct:4.0f}%")
                print("\nActions: enter cluster number, 'n' next page, 'b' back, 'q' quit")
                sel = input("> ").strip().lower()
                if sel == "n":
                    page += 1
                    continue
                if sel == "b":
                    break
                if sel == "q":
                    print("Exiting Personal Inbox Cleanup shell.")
                    quit_shell = True
                    break
                if not sel.isdigit():
                    print("Enter a cluster number, 'n', 'b', or 'q'.")
                    continue
                idx = int(sel)
                if idx < 1 or idx > len(clusters):
                    print("Cluster number out of range.")
                    continue
                cl = clusters[idx - 1]

                # Cluster detail view
                while True:
                    print("\n" + "=" * 80)
                    print(f"{cl.kind.upper()} cluster: {cl.key}")
                    print(f"Total messages: {cl.total}")
                    if cl.last_seen:
                        print(f"Last seen: {cl.last_seen}")
                    print("Context breakdown:")
                    for cctx, cnt in cl.context_counts.most_common():
                        pct = (cnt / cl.total * 100.0) if cl.total else 0.0
                        print(f"  - {cctx:18s}: {cnt:6d} ({pct:5.1f}%)")
                    if cl.sample_senders and cl.kind != "sender":
                        print("\nSample senders:")
                        for s in cl.sample_senders:
                            print(f"  • {s}")
                    if cl.sample_subjects:
                        print("\nSample subjects:")
                        for s in cl.sample_subjects:
                            print(f"  • {s}")
                    suggested = suggest_action(cl)
                    print(f"\nSuggested action: {suggested}")

                    print("\nChoose action:")
                    print("1. archive all")
                    print("2. label newsletters + archive")
                    print("3. label promos + archive")
                    print("4. suppress domain/sender")
                    print("5. review sample messages")
                    print("6. create rule")
                    print("7. skip")
                    print("8. back")
                    act = input("> ").strip()

                    if act == "8":
                        break
                    if act == "5":
                        review_samples(cl)
                        continue

                    action_map = {
                        "1": "archive_all",
                        "2": "label_newsletters_archive",
                        "3": "label_promos_archive",
                        "4": "suppress_domain_or_sender",
                        "6": "create_rule",
                        "7": "skip",
                    }
                    if act not in action_map:
                        print("Please choose 1-8.")
                        continue

                    action_label = action_map[act]
                    if not confirm_apply(action_label, cl):
                        print("Cancelled.")
                        continue

                    timestamp = datetime.now(timezone.utc).isoformat()
                    record = {
                        "cluster_type": cl.kind,
                        "cluster_key": cl.key,
                        "count": cl.total,
                        "context_breakdown": dict(cl.context_counts),
                        "action": action_label,
                        "mode": args.mode,
                        "timestamp": timestamp,
                    }
                    logf.write(json.dumps(record) + "\n")
                    logf.flush()

                    # Session stats
                    session_clusters_reviewed += 1
                    session_messages_covered += cl.total
                    action_counts[action_label] += 1
                    if action_label == "suppress_domain_or_sender":
                        if cl.kind == "domain":
                            suppressed_domains[cl.key] += cl.total
                        elif cl.kind == "sender":
                            suppressed_senders[cl.key] += cl.total
                    if action_label == "create_rule":
                        created_rules.append({"type": cl.kind, "key": cl.key})

                    # Apply reputation changes only in apply mode
                    if args.mode == "apply" and action_label == "suppress_domain_or_sender":
                        if cl.kind == "domain":
                            rep.suppressed_domains[cl.key] = True
                        elif cl.kind == "sender":
                            rep.suppressed_senders[cl.key] = True

                    # No mailbox actions are performed here; those will be added in a future apply mode.
                    covered_pct = (session_messages_covered / total_messages * 100.0) if total_messages else 0.0
                    print(f"Recorded decision: {action_label} for {cl.kind} '{cl.key}'")
                    print(f"Session coverage so far: {session_clusters_reviewed} clusters, "
                          f"{session_messages_covered} messages ({covered_pct:4.1f}% of mailbox)")
                    break

                if quit_shell:
                    break

            if quit_shell:
                break

    # Save updated reputation after interactive decisions (if any)
    if args.mode == "apply":
        save_reputation(rep)

    # Session summary
    print("\n" + "=" * 80)
    print("Session summary")
    print(f"- clusters reviewed: {session_clusters_reviewed}")
    print(f"- messages covered: {session_messages_covered} / {total_messages}")
    pct_total = (session_messages_covered / total_messages * 100.0) if total_messages else 0.0
    print(f"- mailbox coverage: {pct_total:4.1f}%")
    if action_counts:
        print("- actions by type:")
        for act, cnt in action_counts.most_common():
            print(f"  • {act}: {cnt}")
    if suppressed_domains:
        print("- top suppressed domains (by messages covered):")
        for dom, cnt in suppressed_domains.most_common(5):
            print(f"  • {dom}: {cnt}")
    if suppressed_senders:
        print("- top suppressed senders (by messages covered):")
        for snd, cnt in suppressed_senders.most_common(5):
            print(f"  • {snd}: {cnt}")
    if created_rules:
        print("- rules created this session:")
        for r in created_rules:
            print(f"  • {r['type']}:{r['key']}")


if __name__ == "__main__":
    main()

