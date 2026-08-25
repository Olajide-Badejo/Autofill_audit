#!/usr/bin/env python3
"""Rebuild the committed expected descriptors for the layer 2 fixtures.

Spec section 15 layer 2 requires every hand-authored fixture to carry a
committed expected ``FieldDescriptor`` list. Those files are golden data: they
are what turns a change in a selector, a signal, or an ordering into a reviewable
diff instead of a silent behaviour change.

Regenerating them is therefore a **deliberate act**, run by hand, producing a
diff somebody reads. It is not a side effect of running the tests, and there is
no ``--update`` flag on the test suite that would make it one. Ground rule 12 and
the snapshot policy of spec section 15 layer 3 both rest on that being true.

The bounding box is dropped on the way out, and only the bounding box. It
depends on the fonts the machine has and the window the browser opened, so a
committed one would be a committed flake. What the box is used for,
``is_visible``, is written out and compared exactly.

Usage:
    refresh_fixtures.py [--check] [NAME ...]

``--check`` rebuilds nothing and reports which expectations are stale, which is
what a human runs before wondering why a test failed. Exit status is 0 when
everything is current and 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from autofill_audit.descriptors import ExtractionResult  # noqa: E402
from autofill_audit.extract.walker import ExtractOptions, extract_result  # noqa: E402
from autofill_audit.loader import browser_session, load_page  # noqa: E402

PAGES = _REPO_ROOT / "tests" / "fixtures" / "extract" / "pages"
EXPECTED = _REPO_ROOT / "tests" / "fixtures" / "extract" / "expected"

FROZEN_YEAR = 2026
"""The clock the expiry window is frozen to, matching ``tests/extract/conftest``."""

SKIPPED: frozenset[str] = frozenset({"settle_budget_expiry", "long_label"})
"""Pages that are fixtures for a behaviour rather than for a descriptor list.

The settle-budget page never stops mutating, so its control count is a function
of how fast the machine ran and there is nothing stable to commit. The long
label page normalises to nearly two thousand tokens, and a golden file carrying
those is one nobody can review, which defeats the point of having golden
files."""


def _comparable(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop the one member that is not reproducible across machines."""
    payload.pop("bbox", None)
    return payload


def snapshot(result: ExtractionResult) -> dict[str, Any]:
    """The committed shape of one extraction."""
    return {
        "fields": [_comparable(item.to_json()) for item in result.fields],
        "honeypots": [_comparable(item.to_json()) for item in result.honeypots],
        "canvas_regions": [item.to_json() for item in result.canvas_regions],
        "warnings": [item.to_json() for item in result.warnings],
        "truncated": result.truncated,
        "frame_count": result.frame_count,
    }


def render(document: dict[str, Any]) -> str:
    """Serialise an expectation the way it is committed."""
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def targets(names: list[str]) -> list[Path]:
    """Resolve the pages to rebuild."""
    if names:
        return [PAGES / f"{name}.html" for name in names]
    return [path for path in sorted(PAGES.glob("*.html")) if path.stem not in SKIPPED]


def main(argv: list[str] | None = None) -> int:
    """Rebuild or check the expectations and return the process exit status."""
    parser = argparse.ArgumentParser(description="Rebuild layer 2 fixture expectations.")
    parser.add_argument("names", nargs="*", help="fixture stems; default is all of them")
    parser.add_argument("--check", action="store_true", help="report staleness, write nothing")
    args = parser.parse_args(argv)

    EXPECTED.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    with browser_session() as browser:
        for page in targets(args.names):
            with load_page(str(page), as_file=True, browser=browser) as loaded:
                result = extract_result(
                    loaded.page, options=ExtractOptions(now_year=FROZEN_YEAR), settle=loaded.settle
                )
            text = render(snapshot(result))
            destination = EXPECTED / f"{page.stem}.json"
            current = destination.read_text(encoding="utf-8") if destination.is_file() else None
            if current == text:
                print(f"  [same] {page.stem}")
                continue
            stale.append(page.stem)
            if args.check:
                print(f"  [stale] {page.stem}")
                continue
            destination.write_text(text, encoding="utf-8")
            print(f"  [wrote] {page.stem}: {len(result.fields)} field(s)")

    if args.check and stale:
        print(f"refresh_fixtures: {len(stale)} expectation(s) stale", file=sys.stderr)
        return 1
    print(f"refresh_fixtures: {'checked' if args.check else 'refreshed'} {len(stale)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
