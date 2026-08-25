"""The extractor against the committed sample corpus.

The P2 gate's third item is a sweep of the whole generated corpus. That corpus
is gitignored and regenerable (spec section 18), so the full sweep is
``scripts/corpus_sweep.py`` and this is the part of it that can run on every
commit: the twenty-four form sample P1 committed, which is a byte-identical
subset of a full run and covers every family, every tier, and three locales.

Both use the same reconciliation rules from
``autofill_audit.extract.reconcile``, so the numbers here and the numbers in a
full sweep mean the same thing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser

from autofill_audit.extract.reconcile import SweepTotals, reconcile
from autofill_audit.extract.walker import ExtractOptions, extract_result
from autofill_audit.loader import load_page

pytestmark = pytest.mark.e2e

SAMPLE_BASE_YEAR = 2026
"""The base year the committed sample corpus was generated with.

Read from its manifest by the test below rather than trusted from here; the
constant exists so that a mismatch is a named failure rather than a mysterious
one."""


@pytest.fixture(scope="session")
def sample_sweep(browser: Browser, repo_root: Path) -> tuple[SweepTotals, list[Any]]:
    """Extract every form in the committed sample corpus, once."""
    corpus = repo_root / "tests" / "fixtures" / "sample_corpus"
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    options = ExtractOptions(now_year=int(manifest["base_year"]))
    totals = SweepTotals()
    items: list[Any] = []
    for page in sorted((corpus / "forms").glob("*.html")):
        key = json.loads((corpus / "answer_keys" / f"{page.stem}.json").read_text(encoding="utf-8"))
        try:
            with load_page(str(page), as_file=True, browser=browser) as loaded:
                result = extract_result(loaded.page, options=options, settle=loaded.settle)
        except Exception as error:
            totals.errors.append((page.stem, f"{type(error).__name__}: {error}"))
            continue
        item = reconcile(result, key)
        totals.add(item)
        items.append(item)
    return totals, items


def test_the_sample_manifest_records_the_expected_base_year(repo_root: Path) -> None:
    """A moving corpus and a frozen expectation would drift silently."""
    corpus = repo_root / "tests" / "fixtures" / "sample_corpus"
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["base_year"] == SAMPLE_BASE_YEAR


def test_no_form_raises(sample_sweep: tuple[SweepTotals, list[Any]]) -> None:
    """The gate's own wording: zero unhandled exceptions."""
    totals, _ = sample_sweep
    assert totals.errors == []


def test_every_form_reconciles_against_its_answer_key(
    sample_sweep: tuple[SweepTotals, list[Any]],
) -> None:
    """Every control in every key is found, and nothing extra is invented."""
    totals, _ = sample_sweep
    detail = "\n".join(
        f"{item.render()} missing={item.missing} extra={item.unexpected}"
        for item in totals.failures
    )
    assert totals.failures == [], detail


def test_the_control_count_matches_the_key_count(
    sample_sweep: tuple[SweepTotals, list[Any]],
) -> None:
    """The headline number the gate asks for."""
    totals, _ = sample_sweep
    assert totals.found == totals.expected


def test_every_injected_control_is_caught_by_the_settle(
    sample_sweep: tuple[SweepTotals, list[Any]],
) -> None:
    """One control per hostile form does not exist at load.

    P1's handoff calls this out as the discrepancy a walk without a bounded wait
    would produce. The settle is what closes it, and the count closing exactly is
    the evidence.
    """
    totals, _ = sample_sweep
    assert totals.injected_expected > 0
    assert totals.injected_found == totals.injected_expected


def test_every_shadow_hosted_control_is_walked(
    sample_sweep: tuple[SweepTotals, list[Any]],
) -> None:
    """One control per hostile form lives inside an open shadow root."""
    totals, _ = sample_sweep
    assert totals.shadow_expected > 0
    assert totals.shadow_found == totals.shadow_expected


def test_canvas_regions_match_the_page_notes(
    sample_sweep: tuple[SweepTotals, list[Any]],
) -> None:
    """The counting rule P1's handoff states.

    A canvas is recorded as a region and is never a field, which is what keeps
    the control count comparable to the key's field count on the hostile
    checkouts that have both.
    """
    totals, _ = sample_sweep
    assert totals.canvas_expected > 0
    assert totals.canvas_found == totals.canvas_expected


def test_no_corpus_form_has_a_honeypot(
    sample_sweep: tuple[SweepTotals, list[Any]],
) -> None:
    """The generator emits none, so any honeypot here is a visibility bug.

    Worth asserting rather than assuming: a rule that wrongly called ordinary
    controls invisible would show up as a silently shrinking field count, which
    is exactly the failure the reconciliation is meant to catch.
    """
    totals, _ = sample_sweep
    assert totals.honeypots == 0


def test_key_order_differs_only_on_the_mixed_tier(
    sample_sweep: tuple[SweepTotals, list[Any]],
) -> None:
    """The one explained discrepancy in the whole sweep.

    An answer key lists its fields in the generator's slot order, which appends
    a tier's extra controls to the end of the list. The extractor returns
    document order (spec section 9.1 step 7). Those two agree everywhere except
    the mixed tier, where a hostile block sits in the middle of a form whose
    extra controls belong to that block and therefore render in the middle
    while the key lists them last. The selectors are the contract; the order of
    the list is not.
    """
    _, items = sample_sweep
    differing = {item.form_id for item in items if item.order_differs}
    assert differing
    assert all("mixed" in form_id for form_id in differing), differing
