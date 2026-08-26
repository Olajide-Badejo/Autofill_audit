"""Shared plumbing for the model tests.

The committed bundle and a small extracted dev slice, both session scoped,
because opening an onnxruntime session and driving a browser over four pages are
both things worth doing once per run rather than once per test.

The slice comes from the committed sample corpus rather than from the full
generated one. The full corpus is gitignored and regenerable (spec section 18),
so a test that needed it would pass on the build machine and skip in CI, which is
the same as not having it. The full dev split's parity is recorded in the
committed ``dev_metrics.json`` by the training run and is asserted from there.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser

from autofill_audit.classify.onnx_model import (
    MODEL_FILE,
    ModelBundle,
    NgramClassifier,
    load_bundle,
)
from autofill_audit.descriptors import FieldDescriptor
from autofill_audit.extract.walker import ExtractOptions, extract_result
from autofill_audit.loader import load_page

DEV_PARTITION = "dev"
BASE_YEAR = 2026
"""The year the committed sample corpus was generated against. Pinned rather
than taken from the clock, for the reason every other pinned year here is."""


def requires_model(model_dir: Path) -> None:
    """Skip a test when no bundle is checked out.

    A model is committed, so this should never fire in this repository. It exists
    so that a checkout with ``models/`` removed reports a skip naming the reason
    rather than a stack of errors about a missing file.
    """
    if not (model_dir / MODEL_FILE).is_file():
        pytest.skip(f"no model bundle at {model_dir}")


@pytest.fixture(scope="session")
def bundle(model_dir: Path) -> ModelBundle:
    """The committed model bundle, loaded once."""
    requires_model(model_dir)
    return load_bundle(model_dir)


@pytest.fixture(scope="session")
def engine(bundle: ModelBundle) -> NgramClassifier:
    """One session over the committed model, shared by the suite."""
    return NgramClassifier(bundle)


@pytest.fixture(scope="session")
def sample_dev_slice(
    browser: Browser, sample_corpus: Path
) -> Iterator[list[tuple[FieldDescriptor, str]]]:
    """Extract the sample corpus dev partition and pair it with its truth.

    Marked nowhere and needing no marker: it drives the shared browser, which
    every suite in this repository already shares for the reason the root
    conftest explains.
    """
    split = json.loads((sample_corpus / "split.json").read_text(encoding="utf-8"))
    form_ids = sorted(
        form_id
        for form_id, partition in split["form_partitions"].items()
        if partition == DEV_PARTITION
    )
    options = ExtractOptions(now_year=BASE_YEAR)
    paired: list[tuple[FieldDescriptor, str]] = []
    for form_id in form_ids:
        key = json.loads(
            (sample_corpus / "answer_keys" / f"{form_id}.json").read_text(encoding="utf-8")
        )
        truth = {entry["selector"]: entry["label"] for entry in key["fields"]}
        page_path = sample_corpus / "forms" / f"{form_id}.html"
        with load_page(str(page_path), as_file=True, browser=browser) as loaded:
            result = extract_result(loaded.page, options=options, settle=loaded.settle)
        for descriptor in result.fields:
            if descriptor.undetectable_reason is not None:
                continue
            label = truth.get(descriptor.selector)
            if label is not None:
                paired.append((descriptor, label))
    yield paired
