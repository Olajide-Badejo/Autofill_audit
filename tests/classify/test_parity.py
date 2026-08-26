"""The parity gate: the exported graph computes what its own weights say.

Spec section 10.5 makes P4's gate a parity test rather than a successful export,
because "do not assume the export is faithful because it succeeded" is the whole
lesson of that section. Three things are asserted here and they cover different
halves of the same worry.

**The recorded full-split run.** ``models/dev_metrics.json`` carries the parity
result of the training run over the entire dev split, scikit-learn against
onnxruntime, row by row. That comparison needs the fitted scikit-learn estimator,
which is deliberately not committed (a pickle binds the artefact to one
scikit-learn version, which spec section 5.4 calls a hostile property), so it is
run once at training time and its result is committed. The test asserts the
committed record is a passing one, which is what makes a checkout carrying a
failing model impossible.

**A live comparison on a slice.** The graph is compared, today, in CI, against a
numpy reference built from the graph's own coefficients, over descriptors
extracted from the committed sample corpus through a real browser. This is the
half that keeps running after the training machine is gone: it catches an
onnxruntime upgrade that changes what ``LinearClassifier`` means, which is
exactly the failure the recorded record cannot notice.

**The evidence table.** ``evidence.json`` is a slice of the same weight matrix,
written by the training run because onnxruntime does not hand a caller its own
initialisers. A stale one would make a finding name the wrong n-grams, and law 1
would be satisfied in form and violated in substance. It is checked against the
graph here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from autofill_audit.classify.features import featurize
from autofill_audit.classify.onnx_model import (
    EVIDENCE_FILE,
    MODEL_FILE,
    ModelBundle,
    NgramClassifier,
)
from autofill_audit.descriptors import FieldDescriptor

PARITY_TOLERANCE = 1e-5
"""The pre-registered tolerance: per-class probabilities within this, absolute,
and exact argmax agreement on every row."""


def _linear_layer(path: Path) -> tuple[np.ndarray, np.ndarray, list[str], str]:
    """Read the coefficients, intercepts, class order, and transform from the graph.

    The exported graph is one ``ai.onnx.ml.LinearClassifier`` node followed by an
    L1 ``Normalizer``, and both the weights and the class order live in the
    node's attributes rather than in initialisers. That is why the inference path
    cannot read them: it would need the ``onnx`` package to do it, and this test
    has that package because it is a development dependency.
    """
    onnx = pytest.importorskip("onnx")
    model = onnx.load(str(path))
    node = next(item for item in model.graph.node if item.op_type == "LinearClassifier")
    attributes = {attribute.name: attribute for attribute in node.attribute}
    labels = [value.decode("utf-8") for value in attributes["classlabels_strings"].strings]
    coefficients = np.asarray(attributes["coefficients"].floats, dtype=np.float64)
    intercepts = np.asarray(attributes["intercepts"].floats, dtype=np.float64)
    transform = attributes["post_transform"].s.decode("utf-8")
    return coefficients.reshape(len(labels), -1), intercepts, labels, transform


def _reference(weights: np.ndarray, intercepts: np.ndarray, dense: np.ndarray) -> np.ndarray:
    """The softmax of the affine map, in float64 numpy.

    Written out rather than borrowed so that the comparison has two independent
    arithmetics on either side of it. A shifted softmax, because the unshifted
    one overflows on a logit a regularised model reaches often enough to matter.
    """
    logits = dense.astype(np.float64) @ weights.T + intercepts
    shifted = logits - logits.max(axis=1, keepdims=True)
    exponentiated = np.exp(shifted)
    return np.asarray(exponentiated / exponentiated.sum(axis=1, keepdims=True))


# ---------------------------------------------------------------------------
# The recorded full-split gate.
# ---------------------------------------------------------------------------


def _metrics(model_dir: Path) -> dict[str, Any]:
    path = model_dir / "dev_metrics.json"
    if not path.is_file():
        pytest.skip(f"no dev metrics at {path}")
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_the_recorded_full_dev_parity_passed(model_dir: Path) -> None:
    """The committed model's own parity record, over the entire dev split."""
    parity = _metrics(model_dir)["parity"]
    assert parity["rows"] > 0
    assert parity["argmax_agreements"] == parity["rows"]
    assert parity["argmax_agreement_rate"] == 1.0
    assert parity["max_absolute_probability_delta"] <= PARITY_TOLERANCE
    assert parity["tolerance"] == PARITY_TOLERANCE
    assert parity["passed"] is True


def test_the_recorded_metrics_carry_a_reliability_curve_and_an_ece(model_dir: Path) -> None:
    """Spec section 10.4: report calibration quality, not just its existence."""
    calibration = _metrics(model_dir)["calibration"]
    for phase in ("before", "after"):
        curve = calibration[phase]
        assert len(curve["bins"]) == 10
        assert sum(item["count"] for item in curve["bins"]) > 0
        assert 0.0 <= curve["expected_calibration_error"] <= 1.0
    assert set(calibration["methods"].values()) <= {"isotonic", "sigmoid", "identity"}
    assert calibration["switchover_count"] > 0


def test_the_recorded_metrics_never_touched_the_test_split(model_dir: Path) -> None:
    """The training contract, asserted from the artefact rather than the script."""
    metrics = _metrics(model_dir)
    assert metrics["split"] == "dev"
    assert metrics["counts"]["excluded_forms"] >= 0
    manifest = json.loads((model_dir / "train_manifest.json").read_text(encoding="utf-8"))
    assert manifest["excluded_partition_used_for"] == "nothing at P4"
    assert manifest["chosen_hyperparameters"]["class_weight"] == "balanced"
    assert manifest["machine"]["gpu_used"] is False


# ---------------------------------------------------------------------------
# The live comparison.
# ---------------------------------------------------------------------------


def test_the_graph_agrees_with_its_own_weights_on_a_real_slice(
    model_dir: Path,
    bundle: ModelBundle,
    engine: NgramClassifier,
    sample_dev_slice: list[tuple[FieldDescriptor, str]],
) -> None:
    """onnxruntime against a numpy reference, over extracted descriptors.

    The rows are real: extracted from the committed sample corpus through a real
    browser, not synthesised, so the featurisation under test is the one a page
    produces.
    """
    weights, intercepts, labels, transform = _linear_layer(model_dir / MODEL_FILE)
    assert transform == "SOFTMAX"
    assert labels == list(bundle.labels)

    descriptors = [descriptor for descriptor, _ in sample_dev_slice]
    assert descriptors, "the sample corpus dev partition produced no controls"

    dense = featurize(descriptors, bundle.space).to_dense()
    assert dense.shape == (len(descriptors), weights.shape[1])

    from_session = engine.raw_probabilities(descriptors)
    from_numpy = _reference(weights, intercepts, dense)

    agreements = int((np.argmax(from_session, axis=1) == np.argmax(from_numpy, axis=1)).sum())
    delta = float(np.max(np.abs(from_session - from_numpy)))
    assert agreements == len(descriptors), (
        f"argmax disagreed on {len(descriptors) - agreements} of {len(descriptors)} rows"
    )
    assert delta <= PARITY_TOLERANCE, f"largest probability gap {delta:.3e}"


def test_every_session_row_is_a_probability_distribution(
    engine: NgramClassifier, sample_dev_slice: list[tuple[FieldDescriptor, str]]
) -> None:
    """The graph's own normaliser, checked rather than assumed."""
    rows = engine.raw_probabilities([descriptor for descriptor, _ in sample_dev_slice])
    assert np.all(rows >= 0.0)
    assert rows.sum(axis=1) == pytest.approx(np.ones(rows.shape[0]))


# ---------------------------------------------------------------------------
# The evidence table.
# ---------------------------------------------------------------------------


def test_the_evidence_table_is_a_faithful_slice_of_the_graph(
    model_dir: Path, bundle: ModelBundle
) -> None:
    """A stale evidence file would make a finding name the wrong n-grams."""
    weights, _, labels, _ = _linear_layer(model_dir / MODEL_FILE)
    document = json.loads((model_dir / EVIDENCE_FILE).read_text(encoding="utf-8"))
    index = bundle.space.index
    for position, label in enumerate(labels):
        entries = document["classes"].get(label, [])
        for name, weight in entries:
            column = index[name]
            assert weights[position][column] == pytest.approx(weight, abs=1e-6)


def test_the_evidence_table_holds_each_class_strongest_features(
    model_dir: Path, bundle: ModelBundle
) -> None:
    """It is the top of the row, not an arbitrary sample of it."""
    weights, _, labels, _ = _linear_layer(model_dir / MODEL_FILE)
    document = json.loads((model_dir / EVIDENCE_FILE).read_text(encoding="utf-8"))
    cap = document["features_per_class"]
    for position, label in enumerate(labels):
        entries = document["classes"].get(label, [])
        assert len(entries) <= cap
        if not entries:
            continue
        expected = np.sort(weights[position])[-len(entries) :][::-1]
        assert [weight for _, weight in entries] == pytest.approx(expected, abs=1e-6)
        assert all(name in bundle.space.index for name, _ in entries)
