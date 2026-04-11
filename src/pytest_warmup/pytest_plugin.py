"""Pytest plugin integration for pytest-warmup."""

from __future__ import annotations

import pytest

from .core import CURRENT_FIXTURE_REQUEST, WarmupManager, WarmupSessionState

STATE_KEY: pytest.StashKey[WarmupSessionState] = pytest.StashKey()


def pytest_configure(config: pytest.Config) -> None:
    config.stash[STATE_KEY] = WarmupSessionState()


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
