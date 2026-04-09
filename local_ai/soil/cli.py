"""CLI for soil append and promotion (python -m local_ai.soil.cli)."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from local_ai.soil.append import append_soil_item
from local_ai.soil.discover import find_soil_md_by_id, parse_soil_frontmatter_ids
from local_ai.soil.manifest import read_manifest
from local_ai.soil.paths import node_dir, relative_path_posix, resolve_soil_root
from local_ai.soil.promotion import write_promotion_record


def _split_csv(s: str | None) -> list[str] | None:
    if s is None or not str(s).strip():
        return None
    return [x.strip() for x in str(s).split(",") if x.strip()]


def _cmd_append(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve() if args.root else resolve_soil_root()

    if args.body_file:
        body = Path(args.body_file).expanduser().read_text(encoding="utf-8")
    elif args.body is not None:
        body = args.body
    else:
        print("error: provide --body-file or --body", file=sys.stderr)
        return 2

    entity_type = args.entity_type.strip().lower()
    if entity_type != "_root" and not (args.entity_id or "").strip():
        print("error: --entity-id is required unless --entity-type is _root", file=sys.stderr)
        return 2

    entity_id: str | None
    if entity_type == "_root":
        entity_id = (args.entity_id or "").strip() or None
    else:
        entity_id = (args.entity_id or "").strip()

    try:
        path, sid = append_soil_item(
            entity_type,
            entity_id,
            soil_type=args.soil_type.strip(),
            body=body,
            capture_source=args.capture_source.strip(),
            root=root,
            status=(args.status or "seed").strip(),
            source_refs=_split_csv(args.source_refs),
            tags=_split_csv(args.tags),
            promotion_score=int(args.promotion_score),
            capture_name=(args.capture_name or "").strip() or None,
            title=(args.title or "").strip(),
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(sid)
    print(relative_path_posix(path, root))
    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve() if args.root else resolve_soil_root()

    entity_type = args.entity_type.strip().lower()
    if entity_type != "_root" and not (args.entity_id or "").strip():
        print("error: --entity-id is required unless --entity-type is _root", file=sys.stderr)
        return 2

    entity_id: str | None
    if entity_type == "_root":
        entity_id = (args.entity_id or "").strip() or None
    else:
        entity_id = (args.entity_id or "").strip()

    from_soil_id = (args.from_soil_id or "").strip()
    if not from_soil_id:
        print("error: --from-soil-id is required", file=sys.stderr)
        return 2

    try:
        nd = node_dir(root, entity_type, entity_id)
        expected_node_id = read_manifest(nd)["node_id"]
    except FileNotFoundError:
        print(
            "error: target node has no node.json; run append or ensure_node first",
            file=sys.stderr,
        )
        return 2
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.from_path_rel:
        soil_path = (root / args.from_path_rel).resolve()
        if not soil_path.is_file():
            print(f"error: soil file not found: {soil_path}", file=sys.stderr)
            return 2
        text = soil_path.read_text(encoding="utf-8")
        sid_fm, nid_fm = parse_soil_frontmatter_ids(text)
        if sid_fm != from_soil_id:
            print(
                f"error: frontmatter soil_id {sid_fm!r} != --from-soil-id {from_soil_id!r}",
                file=sys.stderr,
            )
            return 2
        if not nid_fm:
            print("error: soil file has no node_id in frontmatter", file=sys.stderr)
            return 2
        from_path_rel = Path(args.from_path_rel).as_posix()
        from_node_id = nid_fm
    else:
        try:
            _abs, from_path_rel, from_node_id = find_soil_md_by_id(root, from_soil_id)
        except (FileNotFoundError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

    if from_node_id != expected_node_id:
        print(
            f"error: soil item belongs to node {from_node_id!r} but you targeted "
            f"{expected_node_id!r} (--entity-type/--entity-id). "
            f"Use the matching entity flags or pass --from-path-rel under the correct node.",
            file=sys.stderr,
        )
        return 2

    if args.to_canonical_json:
        p = Path(args.to_canonical_json).expanduser()
        to_canonical_ref = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(to_canonical_ref, dict):
            print("error: --to-canonical-json must contain a JSON object", file=sys.stderr)
            return 2
    else:
        to_canonical_ref = {"kind": "unspecified", "note": "CLI promotion (no --to-canonical-json)"}

    accepted_by = (args.accepted_by or "").strip() or f"cli:{getpass.getuser()}"
    supporting = _split_csv(args.supporting_soil_ids)

    try:
        out = write_promotion_record(
            root,
            entity_type,
            entity_id,
            from_soil_id=from_soil_id,
            from_path_rel=from_path_rel,
            from_node_id=from_node_id,
            to_canonical_ref=to_canonical_ref,
            reason=(args.reason or "").strip() or "(no reason given)",
            accepted_by=accepted_by,
            supporting_soil_ids=supporting,
            to_node_id=(args.to_node_id or "").strip() or None,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(relative_path_posix(out, root))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Zenaf soil layer CLI")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("append", help="Append a soil Markdown item")
    a.add_argument(
        "--root",
        help="Soil root (default: ZENAF_SOIL_ROOT or ~/.zenaf/soil/v1)",
    )
    a.add_argument("--entity-type", required=True)
    a.add_argument("--entity-id", default="", help="Logical entity id (omit for _root default bucket)")
    a.add_argument("--soil-type", required=True)
    a.add_argument("--capture-source", required=True)
    a.add_argument("--capture-name", default="", help="Required for named_system_capture; must be allowlisted")
    a.add_argument("--title", default="")
    a.add_argument("--status", default="seed")
    a.add_argument("--promotion-score", type=int, default=0)
    a.add_argument("--tags", help="Comma-separated")
    a.add_argument("--source-refs", help="Comma-separated evidence pointers")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--body-file", help="Markdown body path")
    g.add_argument("--body", help="Markdown body string")
    a.set_defaults(func=_cmd_append)

    pr = sub.add_parser("promote", help="Write soil/promoted/*.json audit record")
    pr.add_argument(
        "--root",
        help="Soil root (default: ZENAF_SOIL_ROOT or ~/.zenaf/soil/v1)",
    )
    pr.add_argument("--entity-type", required=True, help="Node that owns soil/promoted/")
    pr.add_argument("--entity-id", default="")
    pr.add_argument("--from-soil-id", required=True)
    pr.add_argument(
        "--from-path-rel",
        help="Path relative to soil root to soil .md (optional if unique soil_id)",
    )
    pr.add_argument("--to-node-id", default="", help="Target node id in the graph (e.g. project:abc)")
    pr.add_argument("--reason", default="")
    pr.add_argument("--accepted-by", default="", help="Default: cli:$USER")
    pr.add_argument("--supporting-soil-ids", help="Comma-separated")
    pr.add_argument(
        "--to-canonical-json",
        help="JSON file for to_canonical_ref (default: kind unspecified)",
    )
    pr.set_defaults(func=_cmd_promote)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
