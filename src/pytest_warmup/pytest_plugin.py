"""Pytest plugin integration for pytest-warmup."""

from __future__ import annotations

import pytest

from .core import CURRENT_FIXTURE_REQUEST, WarmupManager, WarmupSessionState

STATE_KEY: pytest.StashKey[WarmupSessionState] = pytest.StashKey()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("pytest-warmup")
    group.addoption(
        "--warmup-snapshot",
        action="store",
        default=None,
        dest="warmup_snapshot",
        help=(
            "Load a versioned scoped snapshot file. Overrides are resolved per producer "
            "scope from the file's 'scopes' mapping."
        ),
    )
    group.addoption(
        "--warmup-snapshot-for",
        action="append",
        default=[],
        dest="warmup_snapshot_for",
        help=(
            "Attach a versioned snapshot fragment to one producer snapshot_id using the "
            "form '<snapshot_id>=<path>'. May be provided multiple times."
        ),
    )
    group.addoption(
        "--warmup-export-template",
        action="store",
        default=None,
        dest="warmup_export_template",
        help="Write a JSON template snapshot for the selected warmup graph and continue.",
    )
    group.addoption(
        "--warmup-report",
        action="store",
        default=None,
        dest="warmup_report",
        help="Write a JSON warmup preparation report for the selected graph.",
    )
    group.addoption(
        "--warmup-save-on-fail",
        action="store",
        default=None,
        dest="warmup_save_on_fail",
        help="Write a partial JSON snapshot if warmup preparation fails.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.stash[STATE_KEY] = WarmupSessionState()


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(
    session: pytest.Session,
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    del session
    config.stash[STATE_KEY].items = list(items)


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest):
    del fixturedef
    token = CURRENT_FIXTURE_REQUEST.set(request)
    try:
        yield
    finally:
        CURRENT_FIXTURE_REQUEST.reset(token)


@pytest.fixture(scope="session")
def warmup_mgr(pytestconfig: pytest.Config) -> WarmupManager:
    """Session-scoped manager used by producer fixtures."""
    return WarmupManager(pytestconfig.stash[STATE_KEY])
