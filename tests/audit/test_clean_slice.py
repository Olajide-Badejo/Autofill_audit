"""The false-positive gate: nothing above INFO on any clean-tier form.

Spec section 15's layer four names this as a property over the corpus, spec
section 8.4 makes any finding above ``INFO`` on a clean form a defect, and spec
section 19 makes it a P3 gate item. It is the single most important test in this
repository, because it is the one that decides whether the tool is worth
installing.

The argument is short. This tool's output is a list of accusations about somebody
else's page. A missed finding costs a developer a broken field they were going to
find eventually. A wrong finding costs them an afternoon and costs this project
its credibility, and after two of them the check gets deleted from the pipeline.
So the clean tier, which is by construction correct markup, must be met with
silence.

The slice is generated rather than read from ``corpus/``, which is gitignored and
regenerable (spec section 18). The seed and the base year are pinned here for the
same reason ``check_reachability.py`` pins its own: a gate whose input changed
when the year turned would go red for a reason that has nothing to do with the
commit under test.

Every locale and every family, one variant each. That is the **entire** clean
slice of the full corpus, not a sample of it: twenty five templates across six
locales. The gate says "the entire clean-tier corpus slice" and the count is
asserted below so that a generator change which quietly shrank it would fail
here rather than pass on a smaller denominator.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest
from playwright.sync_api import Browser

from autofill_audit.audit.engine import AuditOptions, audit
from autofill_audit.audit.findings import Finding, Severity, at_or_above
from autofill_audit.audit.thresholds import load_thresholds
from autofill_audit.classify.rules import RuleClassifier
from autofill_audit.corpus.families import Family
from autofill_audit.corpus.generator import grid_from, iter_forms
from autofill_audit.corpus.profiles import LOCALE_IDS
from autofill_audit.corpus.tiers import Tier
from autofill_audit.extract.walker import ExtractOptions, extract_result
from autofill_audit.loader import load_page

pytestmark = pytest.mark.e2e

SEED: Final[int] = 20260825
BASE_YEAR: Final[int] = 2026
"""Pinned, not read from the clock. See the module docstring."""

EXPECTED_FORMS: Final[int] = 150
"""Twenty five templates across six locales, one variant each. Asserted rather
than trusted: a generator change that shrank the slice would otherwise make this
gate easier to pass without anybody noticing."""

REPORTABLE: Final[Severity] = Severity.INFO
"""The line spec section 8.4 draws. Above this, meaning WARNING and CRITICAL, is
a defect on a clean form. INFO and NOTE are allowed and are not emitted either,
as the second test records."""


@dataclass(frozen=True, slots=True)
class SliceResult:
    """What one sweep of the clean slice found."""

    forms: int
    fields: int
    above_info: tuple[tuple[str, Finding], ...]
    all_findings: tuple[tuple[str, Finding], ...]

    def render(self) -> str:
        """A failure message a reader can act on without rerunning anything."""
        lines = [
            f"{len(self.above_info)} finding(s) above {REPORTABLE.value} on the clean slice "
            f"({self.forms} forms, {self.fields} fields):"
        ]
        for form_id, finding in self.above_info[:25]:
            lines.append(
                f"  {form_id}: {finding.code.value} on {finding.selector} "
                f"label={finding.label} declared={finding.declared} "
                f"signals={','.join(finding.signals)}"
            )
        return "\n".join(lines)


def _clean_forms() -> Iterator[tuple[str, str]]:
    """Yield every clean-tier form of the full grid, as ``(form_id, html)``."""
    grid = grid_from(
        seed=SEED,
        families=[family.value for family in Family],
        locales=list(LOCALE_IDS),
        tiers=[Tier.CLEAN.value],
        variants=1,
        base_year=BASE_YEAR,
    )
    for form, html in iter_forms(grid):
        yield form.form_id, html


@pytest.fixture(scope="session")
def clean_slice(browser: Browser) -> SliceResult:
    """Audit every clean-tier form once."""
    options = ExtractOptions(now_year=BASE_YEAR)
    classifier = RuleClassifier()
    audit_options = AuditOptions(thresholds=load_thresholds())
    above: list[tuple[str, Finding]] = []
    every: list[tuple[str, Finding]] = []
    forms = 0
    fields = 0
    with tempfile.TemporaryDirectory() as work:
        workdir = Path(work)
        for form_id, html in _clean_forms():
            page_path = workdir / f"{form_id}.html"
            page_path.write_text(html, encoding="utf-8")
            with load_page(str(page_path), as_file=True, browser=browser) as loaded:
                result = extract_result(loaded.page, options=options, settle=loaded.settle)
            report = audit(result, classifier, audit_options)
            forms += 1
            fields += len(report.fields)
            for finding in report.findings:
                every.append((form_id, finding))
                if at_or_above(finding.severity, REPORTABLE) and finding.severity is not REPORTABLE:
                    above.append((form_id, finding))
    return SliceResult(
        forms=forms, fields=fields, above_info=tuple(above), all_findings=tuple(every)
    )


def test_the_slice_is_the_whole_clean_tier(clean_slice: SliceResult) -> None:
    """The denominator, asserted so the gate cannot be passed by shrinking it."""
    assert clean_slice.forms == EXPECTED_FORMS
    assert clean_slice.fields > 0


def test_no_finding_above_info_on_any_clean_tier_form(clean_slice: SliceResult) -> None:
    """The gate. Zero, across the entire slice."""
    assert clean_slice.above_info == (), clean_slice.render()


def test_the_clean_slice_is_in_fact_entirely_silent(clean_slice: SliceResult) -> None:
    """Stronger than the gate asks, and worth recording separately.

    Spec section 8.4 only forbids ``WARNING`` and ``CRITICAL`` here, so ``INFO``
    and ``NOTE`` would be within the rules. The rule table as it stands emits
    neither, and that is a fact worth pinning: if a future change starts putting
    notes on correct markup, this fails while the gate above still passes, which
    is the earliest possible warning that the tool has begun to be noisy.
    """
    counts = Counter(finding.code.value for _, finding in clean_slice.all_findings)
    assert clean_slice.all_findings == (), dict(counts)
