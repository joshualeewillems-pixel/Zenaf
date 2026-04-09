"""Filesystem migration from .atria → .zenaf (idempotent)."""

from __future__ import annotations

from local_ai.legacy_atria_migration import migrate_repo_dot_atria_workspace_identity


def test_migrate_repo_workspace_identity_moves_v1(tmp_path):
    repo = tmp_path / "repo"
    old = repo / ".atria" / "workspace-identity" / "v1"
    old.mkdir(parents=True)
    (old / "brand-profile.json").write_text("{}", encoding="utf-8")

    migrate_repo_dot_atria_workspace_identity(repo)

    new = repo / ".zenaf" / "workspace-identity" / "v1" / "brand-profile.json"
    assert new.is_file()
    assert not old.exists()

    migrate_repo_dot_atria_workspace_identity(repo)
    assert new.is_file()
