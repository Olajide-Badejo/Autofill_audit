"""Split disjointness and the held-out locale (spec section 8.6).

The leakage rule is the most consequential decision in the corpus design, so
these tests assert the properties directly rather than asserting that a
particular assignment came out a particular way. An assignment can change when
the seed changes; the properties may not change at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autofill_audit.corpus.families import TEMPLATES, Family
from autofill_audit.corpus.generator import grid_from, iter_forms
from autofill_audit.corpus.split import (
    HELD_OUT_LOCALE,
    TRAIN_DEV_TEST_PER_FAMILY,
    build_split,
    partition_of,
    split_sha256,
    template_partitions,
)

SEEDS = (20260825, 3, 71)


def _full_split(seed: int) -> tuple[dict[str, Any], list[Any]]:
    grid = grid_from(
        seed=seed,
        families=[family.value for family in Family],
        locales=None,
        tiers=["clean"],
        variants=1,
        base_year=2026,
    )
    forms = [form for form, _ in iter_forms(grid)]
    return build_split(grid, forms), forms


@pytest.mark.parametrize("seed", SEEDS)
def test_no_template_appears_in_two_partitions(seed: int) -> None:
    split, forms = _full_split(seed)
    seen: dict[str, set[str]] = {}
    for form in forms:
        partition = split["form_partitions"][form.form_id]
        if partition == "excluded":
            continue
        seen.setdefault(form.template_id, set()).add(partition)
    for template_id, partitions in seen.items():
        assert len(partitions) == 1, f"{template_id} is in {sorted(partitions)}"


@pytest.mark.parametrize("seed", SEEDS)
def test_the_held_out_locale_appears_in_no_training_row(seed: int) -> None:
    split, forms = _full_split(seed)
    for form in forms:
        if form.locale == HELD_OUT_LOCALE:
            assert split["form_partitions"][form.form_id] != "train"


@pytest.mark.parametrize("seed", SEEDS)
def test_every_family_reaches_the_test_partition(seed: int) -> None:
    """Spec section 8.6 requires it, and a family missing from test would make
    that family's numbers unreportable without anybody noticing."""
    split, forms = _full_split(seed)
    families = {form.family for form in forms if split["form_partitions"][form.form_id] == "test"}
    assert families == set(Family)


@pytest.mark.parametrize("seed", SEEDS)
def test_every_locale_reaches_the_test_partition(seed: int) -> None:
    split, forms = _full_split(seed)
    locales = {form.locale for form in forms if split["form_partitions"][form.form_id] == "test"}
    assert HELD_OUT_LOCALE in locales
    assert len(locales) == 6


@pytest.mark.parametrize("seed", SEEDS)
def test_template_partitions_follow_the_declared_ratio(seed: int) -> None:
    assignment = template_partitions(seed, list(Family))
    train, dev, test = TRAIN_DEV_TEST_PER_FAMILY
    for family in Family:
        counts = {"train": 0, "dev": 0, "test": 0}
        for template_id, partition in assignment.items():
            if TEMPLATES[template_id].family is family:
                counts[partition] += 1
        assert counts == {"train": train, "dev": dev, "test": test}


@pytest.mark.parametrize("seed", SEEDS)
def test_the_test_partition_can_reach_the_pre_registered_alpha(seed: int) -> None:
    """The property P5R exists to establish, asserted at the split rather than at
    the analysis.

    The template is the clustering unit of spec section 13.3, so the number of
    test-partition templates is the number of clusters a paired sign-flip
    permutation gets, and the smallest two sided p value that design can produce
    is two over two to that count. At five clusters the floor sits above the
    pre-registered alpha and no comparison can ever be significant, which is what
    P5 measured and what no amount of extra resampling fixes. This asserts the
    repair where the repair lives: a later change that shrinks the test partition
    back below the level fails here, rather than silently producing a page of
    inconclusive verdicts three phases later.
    """
    alpha = 0.05
    assignment = template_partitions(seed, list(Family))
    clusters = sum(1 for partition in assignment.values() if partition == "test")
    assert clusters == TRAIN_DEV_TEST_PER_FAMILY[2] * len(Family)
    assert 2 / 2**clusters < alpha


def test_every_form_has_exactly_one_partition() -> None:
    split, forms = _full_split(20260825)
    assert set(split["form_partitions"]) == {form.form_id for form in forms}


def test_the_unseen_locale_slice_is_the_held_out_locale_in_dev_and_test() -> None:
    split, forms = _full_split(20260825)
    expected = {
        form.form_id
        for form in forms
        if form.locale == HELD_OUT_LOCALE
        and split["form_partitions"][form.form_id] in {"dev", "test"}
    }
    assert set(split["slices"]["unseen_locale"]) == expected
    assert expected


def test_the_excluded_partition_is_only_the_held_out_locale_on_train_templates() -> None:
    split, forms = _full_split(20260825)
    for form in forms:
        if split["form_partitions"][form.form_id] != "excluded":
            continue
        assert form.locale == HELD_OUT_LOCALE
        assert split["template_partitions"][form.template_id] == "train"


def test_partition_of_lifts_only_the_held_out_locale_out_of_train() -> None:
    assert partition_of("train", HELD_OUT_LOCALE) == "excluded"
    assert partition_of("dev", HELD_OUT_LOCALE) == "dev"
    assert partition_of("test", HELD_OUT_LOCALE) == "test"
    assert partition_of("train", "en-US") == "train"


def test_split_assignment_is_deterministic_from_the_seed() -> None:
    first, _ = _full_split(20260825)
    second, _ = _full_split(20260825)
    assert first == second
    assert split_sha256(first) == split_sha256(second)


def test_split_sha_changes_with_the_split() -> None:
    first, _ = _full_split(20260825)
    second, _ = _full_split(3)
    assert split_sha256(first) != split_sha256(second)


def test_committed_sample_split_holds_the_locale_rule(sample_corpus: Path) -> None:
    split = json.loads((sample_corpus / "split.json").read_text(encoding="utf-8"))
    assert split["held_out_locale"] == HELD_OUT_LOCALE
    for form_id, partition in split["form_partitions"].items():
        if HELD_OUT_LOCALE in form_id:
            assert partition != "train"
