#!/usr/bin/env python3
"""Regenerate the committed sample corpus under ``tests/fixtures/sample_corpus``.

The full corpus is gitignored and regenerable from its seed. A small slice of it
is committed so that the test suite, and the reachability check in CI, have
something to read without generating six hundred forms first.

The sample is a deterministic subset of the real corpus at the default seed, so
a sample form is byte-identical to the same form in a full run. That property is
what makes the sample worth committing: a hand-trimmed sample would be a second
corpus with its own drift.

Usage:
    make_sample_corpus.py [--seed INT] [--base-year INT] [--out DIR]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from autofill_audit.corpus.families import TEMPLATES, Family  # noqa: E402
from autofill_audit.corpus.generator import grid_from  # noqa: E402
from autofill_audit.corpus.manifest import write_corpus  # noqa: E402
from autofill_audit.corpus.tiers import Tier  # noqa: E402

DEFAULT_SEED = 20260825
DEFAULT_BASE_YEAR = 2026
"""The sample is pinned to a fixed base year rather than the current one. The
committed bytes must not change when the year turns, and a sample that
regenerated differently every January would show up as an unexplained diff in
whatever phase happened to run first that year."""

SAMPLE_RELATIVE = Path("tests") / "fixtures" / "sample_corpus"

EXTRA_LOCALE_CELLS: tuple[tuple[str, str, str], ...] = (
    ("checkout-01", "de-DE", Tier.CLEAN.value),
    ("address-02", "de-DE", Tier.HOSTILE.value),
    ("checkout-01", "ja-JP", Tier.CLEAN.value),
    ("address-02", "ja-JP", Tier.HOSTILE.value),
)
"""Two locales beyond ``en-US``, each at a clean and a hostile tier.

German reorders the address so the postal code precedes the town, drops the
administrative-area field entirely, and carries the diacritics and the eszett
that the normalisation step of spec section 9.7 exists for. Japanese changes the
script, puts the postal code first, adds the kana name pair, and is the case
where NFKC normalisation actually does work. Between them they cover every
structural difference the profiles encode that ``en-US`` cannot show, which is
what a fixture needs to be worth committing."""


def _sample_cells() -> list[tuple[str, str, Tier, int]]:
    """Choose the cells the sample holds.

    One form per family and tier at ``en-US``, cycling through each family's
    templates so the sample is not four copies of one skeleton, plus the
    other-locale cells above. Small enough to commit, wide enough that a test
    can reach every tier, every family, and every selector strategy.
    """
    cells: list[tuple[str, str, Tier, int]] = []
    tiers = list(Tier)
    for family in Family:
        template_ids = sorted(
            template_id for template_id, template in TEMPLATES.items() if template.family is family
        )
        for index, tier in enumerate(tiers):
            cells.append((template_ids[index % len(template_ids)], "en-US", tier, 0))
    for template_id, locale, tier_value in EXTRA_LOCALE_CELLS:
        cells.append((template_id, locale, Tier(tier_value), 0))
    return cells


def build(seed: int, base_year: int, out: Path) -> int:
    """Write the sample corpus and return the number of forms."""
    if out.exists():
        shutil.rmtree(out)
    cells = _sample_cells()
    grid = grid_from(
        seed=seed,
        families=[family.value for family in Family],
        locales=sorted({locale for _, locale, _, _ in cells}),
        tiers=[tier.value for tier in Tier],
        variants=1,
        base_year=base_year,
    )
    grid = replace(grid, explicit_cells=tuple(cells))
    result = write_corpus(grid, out)
    return result.form_count


def main(argv: Sequence[str] | None = None) -> int:
    """Regenerate the sample corpus."""
    parser = argparse.ArgumentParser(description="Regenerate the committed sample corpus.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--base-year", type=int, default=DEFAULT_BASE_YEAR)
    parser.add_argument("--out", type=Path, default=_REPO_ROOT / SAMPLE_RELATIVE)
    args = parser.parse_args(argv)

    count = build(args.seed, args.base_year, args.out)
    print(f"sample corpus: {count} forms written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
