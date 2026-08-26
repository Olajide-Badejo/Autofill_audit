"""The train/dev/test split, and the held-out locale (spec section 8.6).

Spec section 8.6 calls this the most consequential decision in the corpus design
and the easiest one to get wrong, so the reasoning is repeated here rather than
left in the specification.

**Templates are partitioned, not forms and not fields.** Fields within a form
are not independent: a German checkout template's postal-code field and its
street field share their author's naming convention, class prefix, and
label-writing style. Shuffle rows and split them and the test set contains
fields from templates the model trained on, and the reported accuracy measures
template memorisation. All locales and all tiers of a template therefore land in
the same partition. The template is the atom.

**One locale is additionally held out of training.** ``fr-FR`` appears in no
training row, whatever partition its template landed in. That is the only honest
test of the cross-locale generalisation claim, and the choice is recorded in
``docs/adr/0005-held-out-locale.md``.

**Held-out-locale forms of training templates go to a fourth partition.** This
is the one place the implementation has to decide something the specification
leaves open. A ``fr-FR`` form whose template is in train cannot go to train,
because the locale is held out. It must not go to dev or test either, because
its template is a training template and putting it there would leak exactly the
template convention the split exists to separate. So it goes to ``excluded``:
generated, recorded, and used by nothing. The unseen-locale slice that the
headline table reports is the ``fr-FR`` forms in dev and test, which come from
dev and test templates and are therefore clean on both axes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, Final

import numpy as np

from autofill_audit.corpus.families import TEMPLATES, Family
from autofill_audit.corpus.generator import GeneratedForm, GridSpec, stable_hash

__all__ = [
    "HELD_OUT_LOCALE",
    "PARTITIONS",
    "SPLIT_SCHEMA_VERSION",
    "TRAIN_DEV_TEST_PER_FAMILY",
    "build_split",
    "partition_of",
    "split_sha256",
]

HELD_OUT_LOCALE: Final[str] = "fr-FR"
"""Recorded in ``docs/adr/0005-held-out-locale.md``. Changing it later to make a
number look better is a law-4 violation dressed as an experiment."""

TRAIN_DEV_TEST_PER_FAMILY: Final[tuple[int, int, int]] = (5, 1, 2)
"""Templates per family in each partition. Eight templates per family at 5/1/2
keeps the roughly 60/20/20 of spec section 8.6 and guarantees the two properties
that section requires: the test partition holds at least one template from every
family, and every locale appears in it, because every template is generated in
every locale.

**Why the test share is two rather than one.** The template is the clustering
unit of spec section 13.3, so the test partition's template count is the number
of clusters the paired sign-flip permutation gets, and the design's power is
decided entirely by that number:

    clusters   arrangements   smallest attainable two sided p
        5            32                   0.0625
        6            64                   0.0313
        8           256                   0.0078
       10          1024                   0.0020

At one template per family the test partition held five, whose floor sits above
the pre-registered alpha, so no comparison clustered by template could reach
significance at any effect size. P5 measured on that design and reported eleven
inconclusive comparisons for exactly that reason. Two per family gives ten
clusters and a floor two orders of magnitude below the level. The dev share stays
at one per family: dev decides hyperparameters and thresholds rather than
significance, and nothing computed there is a clustered test."""

PARTITIONS: Final[tuple[str, ...]] = ("train", "dev", "test", "excluded")
SPLIT_SCHEMA_VERSION: Final[int] = 1


def _shuffled_templates(family: Family, seed: int) -> list[str]:
    """Return one family's templates in a seeded, stable order.

    Seeded from the same value the corpus is, through the same stable digest, so
    the split is reproducible from the seed alone and does not depend on the
    order the template set happens to be declared in.
    """
    ids = sorted(
        template_id for template_id, template in TEMPLATES.items() if template.family is family
    )
    rng = np.random.default_rng(stable_hash(seed, "split", family.value))
    order = rng.permutation(len(ids))
    return [ids[int(index)] for index in order]


def template_partitions(seed: int, families: Sequence[Family]) -> dict[str, str]:
    """Assign every template of the given families to train, dev, or test."""
    train_count, dev_count, _ = TRAIN_DEV_TEST_PER_FAMILY
    assignment: dict[str, str] = {}
    for family in families:
        ordered = _shuffled_templates(family, seed)
        for index, template_id in enumerate(ordered):
            if index < train_count:
                assignment[template_id] = "train"
            elif index < train_count + dev_count:
                assignment[template_id] = "dev"
            else:
                assignment[template_id] = "test"
    return assignment


def partition_of(template_partition: str, locale: str) -> str:
    """Return the partition of one form, given its template's partition.

    The held-out locale is removed from training here, and nowhere else, so
    there is exactly one place in the codebase that decides it.
    """
    if locale == HELD_OUT_LOCALE and template_partition == "train":
        return "excluded"
    return template_partition


def build_split(grid: GridSpec, forms: Sequence[GeneratedForm]) -> dict[str, Any]:
    """Build the split document written to ``corpus/split.json``."""
    templates = template_partitions(grid.seed, grid.families)
    form_partitions = {
        form.form_id: partition_of(templates[form.template_id], form.locale) for form in forms
    }

    counts = {name: 0 for name in PARTITIONS}
    for name in form_partitions.values():
        counts[name] += 1

    unseen_locale_slice = sorted(
        form.form_id
        for form in forms
        if form.locale == HELD_OUT_LOCALE and form_partitions[form.form_id] in {"dev", "test"}
    )

    return {
        "schema_version": SPLIT_SCHEMA_VERSION,
        "seed": grid.seed,
        "held_out_locale": HELD_OUT_LOCALE,
        "templates_per_family": {
            "train": TRAIN_DEV_TEST_PER_FAMILY[0],
            "dev": TRAIN_DEV_TEST_PER_FAMILY[1],
            "test": TRAIN_DEV_TEST_PER_FAMILY[2],
        },
        "template_partitions": dict(sorted(templates.items())),
        "form_partitions": dict(sorted(form_partitions.items())),
        "form_counts": counts,
        "slices": {"unseen_locale": unseen_locale_slice},
    }


def split_sha256(document: dict[str, Any]) -> str:
    """Return the sha of a split document, over its canonical serialisation.

    Canonical means sorted keys and a fixed separator set, so that the sha
    identifies the split's content rather than the whitespace it was written
    with. The manifest records this value, per spec section 18.
    """
    payload = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
