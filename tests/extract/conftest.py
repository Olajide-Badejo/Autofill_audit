"""Shared browser plumbing for the extractor tests.

One browser launch for the whole session. Twenty fixtures at half a second of
launch each is ten seconds of nothing happening on every run, forever; one
launch and twenty fresh contexts costs the launch once and still gives every
page its own storage, its own cookies, and no way to see another page's state.

Every fixture is opened through ``file://``, with no network and no server, so
the suite behaves the same offline as online.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser

from autofill_audit.descriptors import ExtractionResult
from autofill_audit.extract.walker import ExtractOptions, extract_result
from autofill_audit.loader import LoadBudget, browser_session, load_page

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "extract"
PAGES_DIR = FIXTURE_ROOT / "pages"
EXPECTED_DIR = FIXTURE_ROOT / "expected"

FROZEN_YEAR = 2026
"""The year the fixture expectations were built against.

Spec section 9.5 forbids a hardcoded expiry window, so the window is relative
and this is the clock the tests freeze it to. A fixture whose year list is
literal and whose clock is real would pass until one January morning and then
fail for a reason that has nothing to do with the code under test."""

ExtractPage = Callable[..., ExtractionResult]


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    """One Chromium instance for the whole session."""
    with browser_session() as instance:
        yield instance


@pytest.fixture(scope="session")
def pages_dir() -> Path:
    """The directory holding the hand-authored fixture pages."""
    return PAGES_DIR


@pytest.fixture(scope="session")
def expected_dir() -> Path:
    """The directory holding the committed expected descriptor lists."""
    return EXPECTED_DIR


@pytest.fixture(scope="session")
def extract_page(browser: Browser) -> ExtractPage:
    """Return a callable that loads one fixture page and extracts it."""

    def run(
        name: str,
        *,
        options: ExtractOptions | None = None,
        budget: LoadBudget | None = None,
    ) -> ExtractionResult:
        resolved = options if options is not None else ExtractOptions(now_year=FROZEN_YEAR)
        target = str(PAGES_DIR / name)
        with load_page(target, as_file=True, browser=browser, budget=budget) as loaded:
            return extract_result(loaded.page, options=resolved, settle=loaded.settle)

    return run
