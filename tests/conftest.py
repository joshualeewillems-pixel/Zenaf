"""
Pytest hooks: extra context on failure for extraction-related tests (nightly / CI logs).
"""

from __future__ import annotations

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    outcome = yield
    rep = outcome.get_result()
    if rep.when != "call" or not rep.failed:
        return
    nodeid = item.nodeid.lower()
    if "healing_haven" not in nodeid and "meeting_harvest" not in nodeid:
        return
    rep.sections.append(
        (
            "extraction debugging",
            "On failure: search the assertion output for 'Formation summary' and `signals` "
            "(model timeout/variance vs lexical recovery vs reducer promotion). "
            "Full detail remains under _diagnostics['evidence'] when return_diagnostics=True.",
        ),
    )
