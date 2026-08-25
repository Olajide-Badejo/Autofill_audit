#!/usr/bin/env python3
"""Extract every form in a corpus and reconcile it against its answer key.

This is the P2 gate's third item: extraction over the whole generated corpus,
completing with zero unhandled exceptions and reporting a count of controls
found versus answer-key entries with any discrepancy explained.

It is a script rather than a test because the full corpus is gitignored and
regenerable (spec section 18), so the suite cannot depend on it existing. The
committed sample corpus is swept by the test suite on every run; this sweeps
whatever corpus it is pointed at, and the two use the same reconciliation rules
from ``autofill_audit.extract.reconcile`` so their numbers mean the same thing.

Every form is opened through ``file://``, one context each, one browser for the
whole run. No network is involved at any point.

Usage:
    corpus_sweep.py [--corpus-dir DIR] [--limit N] [--base-year YEAR] [--quiet]

Exit status is 0 when every form reconciles and nothing raised, and 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from autofill_audit.extract.reconcile import SweepTotals, reconcile  # noqa: E402
from autofill_audit.extract.walker import ExtractOptions, extract_result  # noqa: E402
from autofill_audit.loader import browser_session, load_page  # noqa: E402


def _base_year(corpus_dir: Path, override: int | None) -> int:
    """The year the expiry window is measured against.

    Read from the corpus manifest rather than from the clock. A corpus records
    the base year it was generated with precisely so that a run against it is
    reproducible after the year turns (spec section 18), and measuring a fixed
    corpus against a moving clock would make this sweep's answer depend on the
    day it was run.
    """
    if override is not None:
        return override
    manifest = corpus_dir / "manifest.json"
    if manifest.is_file():
        document = json.loads(manifest.read_text(encoding="utf-8"))
        recorded = document.get("base_year")
        if isinstance(recorded, int):
            return recorded
    return time.gmtime().tm_year


def main(argv: list[str] | None = None) -> int:
    """Run the sweep and return the process exit status."""
    parser = argparse.ArgumentParser(description="Sweep a corpus with the extractor.")
    parser.add_argument("--corpus-dir", type=Path, default=Path("corpus"))
    parser.add_argument("--limit", type=int, default=0, help="stop after N forms")
    parser.add_argument("--base-year", type=int, default=None)
    parser.add_argument("--quiet", action="store_true", help="print only the summary")
    args = parser.parse_args(argv)

    corpus_dir: Path = args.corpus_dir
    forms_dir = corpus_dir / "forms"
    keys_dir = corpus_dir / "answer_keys"
    if not forms_dir.is_dir() or not keys_dir.is_dir():
        print(f"corpus_sweep: {corpus_dir} has no forms/ and answer_keys/", file=sys.stderr)
        return 1

    pages = sorted(forms_dir.glob("*.html"))
    if args.limit:
        pages = pages[: args.limit]
    options = ExtractOptions(now_year=_base_year(corpus_dir, args.base_year))

    totals = SweepTotals()
    started = time.monotonic()
    with browser_session() as browser:
        for page in pages:
            key_path = keys_dir / f"{page.stem}.json"
            if not key_path.is_file():
                totals.errors.append((page.stem, "no answer key"))
                continue
            key = json.loads(key_path.read_text(encoding="utf-8"))
            try:
                with load_page(str(page), as_file=True, browser=browser) as loaded:
                    result = extract_result(loaded.page, options=options, settle=loaded.settle)
            except Exception as error:
                # The gate is "zero unhandled exceptions", so one is caught,
                # named, and counted rather than ending the sweep on form four.
                totals.errors.append((page.stem, f"{type(error).__name__}: {error}"))
                continue
            item = reconcile(result, key)
            totals.add(item)
            if not args.quiet and not item.ok:
                print(item.render())
                for selector in item.missing:
                    print(f"      missing  {selector}")
                for selector in item.unexpected:
                    print(f"      extra    {selector}")

    elapsed = time.monotonic() - started
    print(f"corpus_sweep: {corpus_dir}, base year {options.resolved_year()}")
    print(f"  forms swept              {totals.forms}")
    print(f"  unhandled exceptions     {len(totals.errors)}")
    print(f"  controls found           {totals.found}")
    print(f"  answer key entries       {totals.expected}")
    print(f"  injected controls found  {totals.injected_found} of {totals.injected_expected}")
    print(f"  shadow controls found    {totals.shadow_found} of {totals.shadow_expected}")
    print(f"  canvas regions found     {totals.canvas_found} of {totals.canvas_expected}")
    print(f"  honeypots excluded       {totals.honeypots}")
    print(f"  forms not reconciling    {len(totals.failures)}")
    print(f"  forms whose key order differs from document order   {totals.order_differs}")
    print(f"  elapsed                  {elapsed:.1f}s")

    for name, detail in totals.errors:
        print(f"  raised: {name}: {detail}", file=sys.stderr)
    if not totals.ok:
        return 1
    print("corpus_sweep: every form reconciles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
