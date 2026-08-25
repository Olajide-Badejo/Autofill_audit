"""Ground rule 7: same seed, same bytes.

This is P1's headline gate, and it is a test as well as a manual run because the
manual run proves it once and the test proves it on every push. Spec section 8.1
names the likeliest cause of a generator that fails this: Python's ``hash()`` is
randomised per process for strings, so a per-form seed derived from it is stable
within one run and different in the next. The stable-hash tests below pin that
directly, and the byte-comparison tests pin the consequence.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from autofill_audit.corpus.families import Family
from autofill_audit.corpus.generator import grid_from, iter_forms, stable_hash
from autofill_audit.corpus.manifest import write_corpus
from autofill_audit.corpus.tiers import Tier

SEEDS = (20260825, 1, 999983)


def _small_grid(seed: int) -> object:
    return grid_from(
        seed=seed,
        families=[Family.PAYMENT.value, Family.LOGIN.value],
        locales=["en-US", "ja-JP"],
        tiers=[tier.value for tier in Tier],
        variants=1,
        base_year=2026,
    )


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize("seed", SEEDS)
def test_two_runs_of_one_seed_are_byte_identical(seed: int, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_corpus(_small_grid(seed), first)  # type: ignore[arg-type]
    write_corpus(_small_grid(seed), second)  # type: ignore[arg-type]
    assert _tree(first) == _tree(second)


def test_different_seeds_produce_different_corpora(tmp_path: Path) -> None:
    """Determinism must not have been bought by ignoring the seed."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_corpus(_small_grid(SEEDS[0]), first)  # type: ignore[arg-type]
    write_corpus(_small_grid(SEEDS[1]), second)  # type: ignore[arg-type]
    assert _tree(first) != _tree(second)


def test_stable_hash_is_stable_across_processes() -> None:
    """The per-form seed must not move between interpreter runs.

    Run in a subprocess with hash randomisation deliberately switched on, which
    is what would break a digest built on ``hash()``. Comparing against a value
    computed in this process is the whole point: two calls inside one process
    would agree even if the function were built on the randomised hash.
    """
    expected = stable_hash(20260825, "checkout", "checkout-01", "en-US", "clean", "0")
    program = (
        "import sys; sys.path.insert(0, 'src');"
        "from autofill_audit.corpus.generator import stable_hash;"
        "print(stable_hash(20260825, 'checkout', 'checkout-01', 'en-US', 'clean', '0'))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": "random", "PATH": "/usr/bin:/bin"},
        cwd=Path(__file__).resolve().parent.parent.parent,
    )
    assert int(completed.stdout.strip()) == expected


def test_stable_hash_separates_axis_tuples() -> None:
    """Joining without a separator would let two different tuples collide."""
    first = stable_hash(1, "ab", "c")
    second = stable_hash(1, "a", "bc")
    assert first != second


def test_stable_hash_fits_in_64_bits() -> None:
    for seed in SEEDS:
        value = stable_hash(seed, "checkout", "checkout-01", "en-US", "clean", "0")
        assert 0 <= value < 2**64


def test_base_year_changes_the_bytes(tmp_path: Path) -> None:
    """The base year is a real generator input, so it must show in the output.

    If it did not, recording it in the manifest would be pointless ceremony.
    """
    grid_2026 = grid_from(
        seed=7,
        families=[Family.PAYMENT.value],
        locales=["en-US"],
        tiers=[Tier.CLEAN.value],
        variants=1,
        base_year=2026,
    )
    grid_2031 = grid_from(
        seed=7,
        families=[Family.PAYMENT.value],
        locales=["en-US"],
        tiers=[Tier.CLEAN.value],
        variants=1,
        base_year=2031,
    )
    write_corpus(grid_2026, tmp_path / "a")
    write_corpus(grid_2031, tmp_path / "b")
    assert _tree(tmp_path / "a") != _tree(tmp_path / "b")


def test_rendering_is_pure() -> None:
    """Generating the same grid twice in one process must not drift either.

    Cached Faker instances are reseeded per form. If that reseeding were ever
    dropped, the second pass through a grid would carry the first pass's
    generator state and this test would fail while the two-directory comparison
    above still passed, because that one uses a fresh process per run.
    """
    grid = grid_from(
        seed=42,
        families=[Family.ADDRESS.value],
        locales=["de-DE"],
        tiers=[Tier.CLEAN.value, Tier.HOSTILE.value],
        variants=1,
        base_year=2026,
    )
    first = [html for _, html in iter_forms(grid)]
    second = [html for _, html in iter_forms(grid)]
    assert first == second
