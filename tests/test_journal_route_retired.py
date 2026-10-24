"""POST /journal/story was retired (overnight backend comb-over): it had
zero callers repo-wide and its job is covered by POST /pipeline/story.

Pins the retirement at the route table (no TestClient needed — several
TestClient-based suites error in minimal envs over the starlette/httpx
mismatch, unrelated to this change) and pins the dependency that forced
the module to stay: ``local_ai/journal/story.py`` must remain importable
with the casting machinery ``pipeline/stories.py`` depends on.
"""

from __future__ import annotations


def _mounted_paths():
    from api.main import app

    paths = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
            continue
        original = getattr(route, "original_router", None)
        if original is None:
            continue
        include_prefix = getattr(getattr(route, "include_context", None), "prefix", "") or ""
        for inner in getattr(original, "routes", []):
            inner_path = getattr(inner, "path", None)
            if inner_path:
                paths.add(include_prefix + inner_path)
    return paths


def test_journal_story_route_is_gone():
    assert "/journal/story" not in _mounted_paths()


def test_journal_router_still_mounts_without_load_error():
    # main.py must not have recorded a journal load error: the empty
    # router keeps the import/include path intact.
    import api.main as main_module

    assert not any(e.startswith("journal:") for e in main_module._router_load_errors)


def test_journal_story_module_stays_for_pipeline_dependency():
    from local_ai.journal.story import (
        analyze_entry_strands,
        build_cast,
        detect_active_archetypes,
        select_cast,
    )
    from local_ai.pipeline.stories import extract_story  # noqa: F401  (import = dependency)

    assert callable(analyze_entry_strands)
    assert callable(detect_active_archetypes)
    assert callable(select_cast)
    assert callable(build_cast)
