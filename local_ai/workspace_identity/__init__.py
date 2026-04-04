"""Local workspace identity mirror (gitignored). Not a system of record."""

from local_ai.workspace_identity.snapshot import (
    build_workspace_identity_snapshot,
    build_workspace_packet_from_snapshot,
    compute_branch_key,
    default_workspace_identity_dir,
    normalize_snapshot_for_extract,
    read_snapshot_and_meta,
    write_workspace_identity_snapshot,
)

__all__ = [
    "build_workspace_identity_snapshot",
    "build_workspace_packet_from_snapshot",
    "compute_branch_key",
    "default_workspace_identity_dir",
    "normalize_snapshot_for_extract",
    "read_snapshot_and_meta",
    "write_workspace_identity_snapshot",
]
