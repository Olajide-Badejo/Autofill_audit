"""Shared plumbing for the extractor tests.

The browser itself lives in the root ``conftest.py`` from P3 onwards, because
Playwright's synchronous API allows exactly one live session per thread and the
audit suite needs one too. Everything else about the arrangement is unchanged:
one launch for the whole run, a fresh context per page, so no page can see
another page's storage.

Every fixture is opened through ``file://``, with no network and no server, so
the suite behaves the same offline as online.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from playwright.sync_api import Browser

from autofill_audit.descriptors import ExtractionResult
from autofill_audit.extract.walker import ExtractOptions, extract_result
from autofill_audit.loader import LoadBudget, load_page

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
