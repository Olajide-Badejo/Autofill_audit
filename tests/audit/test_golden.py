"""Golden report snapshots (spec section 15, layer 3).

For a fixed fixture set and a fixed engine, the exact terminal, JSON, and HTML
output is committed under ``tests/golden/``. Any change to finding text,
ordering, or severity shows up here as a diff, and must be an intentional
CHANGELOG-bearing change. **These tests are the enforcement mechanism for ground
rule 12.**

The engine is the rule baseline on purpose, so that the snapshots do not churn
every time a model is retrained. When the n-gram engine lands at P4 it gets its
own comparison against the corpus, not a snapshot: a snapshot suite whose
expected output moves with a training run has stopped being a snapshot suite.

**How to regenerate.** ``python scripts/refresh_golden.py``, by hand, after a
deliberate change, and then read the diff before committing it. There is
deliberately no ``--update`` flag on the test suite: a snapshot that refreshes as
a side effect of running the tests is a snapshot that gets refreshed instead of
read.

The report builder lives in that script and is imported here rather than copied,
so the thing that writes a snapshot and the thing that checks one cannot drift.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Browser

from autofill_audit.audit.engine import AuditReport
from refresh_golden import (
    GOLDEN_FIXTURES,
    RENDERERS,
    build_report,
    golden_path,
    render_all,
    snapshot_name,
)

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def rendered(browser: Browser, repo_root: Path) -> dict[str, dict[str, str]]:
    """Render every golden fixture once, in every format."""
    return {
        fixture: render_all(build_report(browser, repo_root, fixture))
        for fixture in GOLDEN_FIXTURES
    }


@pytest.mark.parametrize("fixture", GOLDEN_FIXTURES)
@pytest.mark.parametrize("suffix", RENDERERS)
def test_the_rendered_report_matches_its_committed_snapshot(
    fixture: str, suffix: str, rendered: dict[str, dict[str, str]], repo_root: Path
) -> None:
    """Byte for byte."""
    path = golden_path(repo_root, fixture, suffix)
    assert path.is_file(), (
        f"{path} is missing. Run python scripts/refresh_golden.py and read the diff."
    )
    expected = path.read_text(encoding="utf-8")
    actual = rendered[fixture][suffix]
    assert actual == expected, (
        f"{path.name} no longer matches. If the change was deliberate, run "
        "python scripts/refresh_golden.py, read the diff, and put it in the CHANGELOG."
    )


@pytest.mark.parametrize("fixture", GOLDEN_FIXTURES)
def test_rendering_twice_produces_the_same_bytes(
    browser: Browser, repo_root: Path, fixture: str
) -> None:
    """The property the whole layer rests on.

    A snapshot suite over a renderer that is not deterministic is a suite that
    fails at random, gets marked flaky, and then gets deleted. So the
    determinism is asserted directly rather than inferred from the snapshots
    happening to pass.
    """
    first = render_all(build_report(browser, repo_root, fixture))
    second = render_all(build_report(browser, repo_root, fixture))
    assert first == second


def test_the_html_report_is_self_contained(rendered: dict[str, dict[str, str]]) -> None:
    """No external asset, no script, no network fetch at view time.

    The most likely reader was emailed the file. Spec section 11.4 is explicit
    and this is the mechanical check of it.
    """
    for fixture in GOLDEN_FIXTURES:
        document = rendered[fixture]["html"]
        assert "<script" not in document.lower(), fixture
        assert "http://" not in document, fixture
        assert "https://" not in document, fixture
        assert "<style>" in document, fixture


def test_the_terminal_report_shows_tiers_and_never_percentages(
    rendered: dict[str, dict[str, str]],
) -> None:
    """Spec section 10.1: printing a percentage from a regex table is forbidden."""
    document = rendered["checkout_hostile.html"]["txt"]
    assert "rule tier HIGH" in document
    assert "%" not in document


def test_the_report_carries_no_composite_score(rendered: dict[str, dict[str, str]]) -> None:
    """Spec section 11.4: a count, never an invented index or a letter grade."""
    document = rendered["checkout_hostile.html"]["txt"]
    assert "autofill readiness" in document
    assert "controls declare autocomplete" in document
    assert "score" not in document.lower()
    assert "grade" not in document.lower()


def test_every_golden_fixture_has_a_snapshot_in_every_format(repo_root: Path) -> None:
    """A format added without a snapshot is a format nothing pins."""
    for fixture in GOLDEN_FIXTURES:
        for suffix in RENDERERS:
            assert golden_path(repo_root, fixture, suffix).is_file(), (
                f"{snapshot_name(fixture)}.{suffix}"
            )


def test_a_report_built_for_a_snapshot_carries_no_machine_specific_target(
    browser: Browser, repo_root: Path
) -> None:
    """The neutralisation the snapshots depend on, asserted rather than assumed."""
    report: AuditReport = build_report(browser, repo_root, GOLDEN_FIXTURES[0])
    assert report.url.startswith("fixture://")
    assert set(report.timing_ms.values()) == {0.0}
