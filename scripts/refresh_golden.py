#!/usr/bin/env python3
"""Regenerate the committed golden report snapshots (spec section 15, layer 3).

Run by hand, on purpose. There is no ``--update`` flag on the test suite and
adding one would defeat the whole mechanism: a snapshot that can be refreshed as
a side effect of running the tests is a snapshot that gets refreshed instead of
read, and the diff it was supposed to force somebody to look at goes past
unnoticed.

    python scripts/refresh_golden.py          # rewrite tests/golden/
    python scripts/refresh_golden.py --check  # what the test does, without pytest

**When to run it.** After any deliberate change to finding text, finding
ordering, severity, the rule table, the thresholds, or a renderer. Every one of
those is a change a reader of the report will notice, so every one of them is a
CHANGELOG entry (ground rule 12) and the snapshot diff is the evidence that the
entry is complete.

**When not to run it.** When a snapshot fails and you do not know why. That is
the mechanism working.

What is pinned, and what is neutralised
---------------------------------------

Three things about a real run are facts about the machine rather than about the
page, and all three are replaced with fixed values before rendering:

- the target URL, which is an absolute ``file://`` path;
- the timings, which are a measurement of the run;
- the expiry-year window, which is relative to the current year (spec 9.5).

Everything else is left exactly as a real invocation produces it. In particular
the descriptors are not trimmed beyond the geometry the renderer already prunes,
because a snapshot of a tidied report is a snapshot of something the tool does
not produce.

This module is imported by ``tests/audit/test_golden.py`` rather than duplicated
there, so the file that writes a snapshot and the test that checks one cannot
disagree about how a report is built.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Final

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from playwright.sync_api import Browser  # noqa: E402

from autofill_audit.audit.engine import AuditOptions, AuditReport, audit  # noqa: E402
from autofill_audit.audit.thresholds import load_thresholds  # noqa: E402
from autofill_audit.classify.rules import RuleClassifier  # noqa: E402
from autofill_audit.extract.walker import ExtractOptions, extract_result  # noqa: E402
from autofill_audit.loader import load_page  # noqa: E402
from autofill_audit.report import html_report, json_report, terminal  # noqa: E402

FIXTURE_DIR: Final[Path] = Path("tests") / "fixtures"
GOLDEN_DIR: Final[Path] = Path("tests") / "golden"

GOLDEN_FIXTURES: Final[tuple[str, ...]] = (
    # Everything the catalogue can say about a page that gets it wrong.
    "checkout_hostile.html",
    # The modifier rule of spec section 7.1, and the shape of a report with
    # nothing in it, which is the output a well-built page must produce.
    "checkout_modifiers.html",
    # A page with controls a user cannot see, so the honeypot key is pinned too.
    "extract/pages/honeypot.html",
)
"""The fixed fixture set. Fixed, because a snapshot suite whose inputs move is a
snapshot suite that never fails for the reason it was built to fail for."""

FROZEN_YEAR: Final[int] = 2026
"""The clock the expiry window is measured against. Frozen so that a snapshot
taken today still compares equal in April, which spec section 15's flake policy
requires of every timing-adjacent test."""

FROZEN_TIMING: Final[dict[str, float]] = {"load_ms": 0.0, "extract_ms": 0.0, "audit_ms": 0.0}
"""The one part of a report that is not a pure function of the page."""

_TARGET_SCHEME: Final[str] = "fixture://"
"""What the absolute ``file://`` target becomes. A scheme this tool would refuse
to open, chosen so that nobody can mistake a snapshot for a real run's output."""

RENDERERS: Final[tuple[str, ...]] = ("txt", "json", "html")
"""The three formats, by the suffix their snapshot carries."""


def snapshot_name(fixture: str) -> str:
    """The snapshot stem for one fixture path."""
    return Path(fixture).stem


def build_report(browser: Browser, root: Path, fixture: str) -> AuditReport:
    """Audit one fixture and neutralise everything machine dependent."""
    page_path = root / FIXTURE_DIR / fixture
    options = ExtractOptions(now_year=FROZEN_YEAR)
    with load_page(str(page_path), as_file=True, browser=browser) as loaded:
        result = extract_result(loaded.page, options=options, settle=loaded.settle)
    frozen = replace(result, url=f"{_TARGET_SCHEME}{Path(fixture).name}")
    report = audit(frozen, RuleClassifier(), AuditOptions(thresholds=load_thresholds()))
    return replace(report, timing_ms=dict(FROZEN_TIMING))


def render_all(report: AuditReport) -> dict[str, str]:
    """Render one report in all three formats, keyed by snapshot suffix."""
    return {
        "txt": terminal.render(report),
        "json": json_report.render(report),
        "html": html_report.render(report),
    }


def golden_path(root: Path, fixture: str, suffix: str) -> Path:
    """Where one snapshot lives."""
    return root / GOLDEN_DIR / f"{snapshot_name(fixture)}.{suffix}"


def main(argv: Sequence[str] | None = None) -> int:
    """Write, or check, every snapshot."""
    parser = argparse.ArgumentParser(description="Regenerate the golden report snapshots.")
    parser.add_argument("--root", type=Path, default=_REPO_ROOT, help="repository root")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report differences instead of writing, and exit non-zero on any",
    )
    args = parser.parse_args(argv)
    root: Path = args.root
    (root / GOLDEN_DIR).mkdir(parents=True, exist_ok=True)

    from autofill_audit.loader import browser_session

    stale: list[str] = []
    written = 0
    with browser_session() as browser:
        for fixture in GOLDEN_FIXTURES:
            rendered = render_all(build_report(browser, root, fixture))
            for suffix, text in rendered.items():
                path = golden_path(root, fixture, suffix)
                if args.check:
                    current = path.read_text(encoding="utf-8") if path.is_file() else ""
                    if current != text:
                        stale.append(str(path.relative_to(root)))
                    continue
                path.write_text(text, encoding="utf-8")
                written += 1

    if args.check:
        for name in stale:
            print(f"stale: {name}")
        print(f"refresh_golden: {len(stale)} stale snapshot(s)")
        return 1 if stale else 0
    print(f"refresh_golden: wrote {written} snapshot(s) to {GOLDEN_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
