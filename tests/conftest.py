"""Test configuration.

The CI scripts under ``scripts/`` are executable checks rather than library
modules, so they are not importable from the installed package. Putting the
directory on ``sys.path`` here lets the test suite exercise them as code instead
of shelling out to them, which is what makes their failure paths testable.

``tests/`` itself goes on the path for the same kind of reason: ``builders.py``
is shared by the unit and audit suites, and pytest puts the directory of each
test *module* on the path rather than the root of the test tree, so a helper one
level up would not otherwise be importable.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser

from autofill_audit.loader import browser_session

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
SCRIPTS_DIR = REPO_ROOT / "scripts"
SAMPLE_CORPUS = TESTS_DIR / "fixtures" / "sample_corpus"
FIXTURES = TESTS_DIR / "fixtures"

for _directory in (SCRIPTS_DIR, TESTS_DIR):
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repository root, for tests that read committed files."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def sample_corpus() -> Path:
    """The committed sample corpus directory."""
    return SAMPLE_CORPUS


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """The hand-authored fixture directory."""
    return FIXTURES


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    """One Chromium instance for the whole run, shared by every suite.

    Two reasons it is here rather than in each suite's own conftest.

    The cheap one: twenty fixtures at half a second of launch each is ten seconds
    of nothing happening on every run, forever. One launch and a fresh context
    per page costs the launch once and still gives every page its own storage.

    The load-bearing one: **Playwright's synchronous API allows exactly one live
    session per thread.** Two session-scoped fixtures each opening
    ``sync_playwright()`` produce "you are using Playwright Sync API inside the
    asyncio loop", which reads like an async/sync mistake and is nothing of the
    kind. So there is one, and the suites share it.

    The same constraint is why the end-to-end CLI tests run the tool in a
    subprocess: the CLI opens a browser of its own, and it cannot do that while
    this one is alive.
    """
    with browser_session() as instance:
        yield instance
