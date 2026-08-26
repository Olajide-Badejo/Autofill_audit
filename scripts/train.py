#!/usr/bin/env python3
"""Train the n-gram model, calibrate it, and export it to ONNX.

The contract of spec section 10.3, which is a program's contract rather than a
notebook's habit:

```
inputs:   --corpus DIR  --split-file corpus/split.json  --seed INT  --out DIR
reads:    ONLY the train partition for fitting; ONLY the dev partition for
          calibration and for any hyperparameter choice
writes:   out/model.onnx, out/vocab.json, out/calibration.json,
          out/label_map.json, out/train_manifest.json, out/dev_metrics.json
forbids:  reading the test partition at all, enforced by an assertion that
          raises if a test-partition path is opened during training
```

Two files beyond the contract's list are written and are named here so nothing is
silently extra: ``evidence.json``, a slice of the exported weight matrix that the
inference path uses to name the features behind a prediction (onnxruntime does
not hand a caller its own initialisers), and nothing else.

The test-partition guard
------------------------

``TestPartitionGuard`` does two things, and it needs both. It exposes ``check``,
which every path this script resolves goes through before anything opens it,
because the browser reads a form through a URL and no Python-level hook would
ever see that. And it installs a ``sys.audit`` hook, which catches everything
else: a stray line added later, a helper that globs a directory, a debugging
detour that reads one file to see what is in it.

Every project intends not to touch its test set and a meaningful fraction of them
do anyway, through exactly that last category. The guard makes it raise.

The fourth partition
--------------------

P1's split has four partitions, not three. ``excluded`` holds the held-out-locale
forms whose template landed in train: they cannot be trained on because the
locale is held out, and they cannot be evaluated on because their template is a
training template and using them would leak the naming convention the split
exists to separate (spec section 8.6). **At P4 the excluded partition is used for
nothing.** It is not read, not featurised, and not counted anywhere except in the
manifest, where its size is recorded so that the corpus arithmetic adds up.

Usage:
    train.py --corpus corpus --split-file corpus/split.json --seed 20260825 \\
             --out models [--no-sweep] [--cache DIR]

Exit status is 0 when the run completes and the parity self-check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from autofill_audit import __version__  # noqa: E402
from autofill_audit.classify.features import (  # noqa: E402
    FeatureConfig,
    FeatureSpace,
    featurize,
    fit_feature_space,
)
from autofill_audit.classify.onnx_model import (  # noqa: E402
    CALIBRATION_FILE,
    EVIDENCE_FILE,
    EVIDENCE_SCHEMA_VERSION,
    LABEL_MAP_FILE,
    LABEL_MAP_SCHEMA_VERSION,
    MANIFEST_FILE,
    MODEL_FILE,
    VOCAB_FILE,
    Calibration,
    ClassCalibration,
)
from autofill_audit.descriptors import ExtractionResult, FieldDescriptor  # noqa: E402
from autofill_audit.taxonomy import Label  # noqa: E402

DEV_METRICS_FILE = "dev_metrics.json"

TRAIN = "train"
DEV = "dev"
TEST = "test"
EXCLUDED = "excluded"

SWEEP_GRID: tuple[float, ...] = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
"""The regularisation grid, fixed before the run and recorded in the manifest.

Chosen on dev macro-F1 and never on test. Six points spanning five doublings is
enough to find the shoulder of the curve on a corpus this size, and a finer grid
would be reading noise."""

ISOTONIC_SWITCHOVER = 100
"""Dev positives at or above which a class is calibrated with isotonic
regression rather than with Platt scaling (spec section 10.4, fixed at P4)."""

MIN_SIGMOID_POSITIVES = 2
"""Below this a class gets the identity calibrator, and ``calibration.json``
records that it is uncalibrated. Fitting a sigmoid to one positive example is
fitting the example."""

RELIABILITY_BINS = 10
"""Equal-width bins for the reliability curve and the expected calibration
error, which is the shape spec section 10.4 asks to be reported."""

INSUFFICIENT_DATA_MINIMUM = 30
"""A per-locale or per-tier cell smaller than this reports its count and no
metric. A macro-F1 over eleven fields is a number that reads like a measurement
and behaves like a coin toss, and spec section 13.2 asks for the rule in code."""

EVIDENCE_PER_CLASS = 40
"""How many of a class's highest weighted features are written to
``evidence.json`` for the inference path to name as evidence."""

TOP_CONFUSIONS = 20

PARITY_TOLERANCE = 1e-5
"""Absolute per-class probability agreement between scikit-learn and onnxruntime
(the pre-registered tolerance). The gate is this plus exact argmax agreement on
every dev row."""


# ---------------------------------------------------------------------------
# The test-partition guard.
# ---------------------------------------------------------------------------


class TestPartitionError(RuntimeError):
    """Training tried to read a test-partition path.

    Not a warning and not a log line. The whole value of the guard is that it
    ends the run, because a run that noticed and continued would produce exactly
    the artefact the guard exists to prevent, with a note about it somewhere in
    the scrollback.
    """


class TestPartitionGuard:
    """Refuses every read of a test-partition form or answer key."""

    def __init__(self, forbidden: frozenset[str]) -> None:
        self._forbidden = forbidden
        self._armed = False

    @property
    def forbidden(self) -> frozenset[str]:
        """The form ids training may not read."""
        return self._forbidden

    def check(self, path: Path | str) -> None:
        """Raise if ``path`` names a test-partition form.

        Called before anything opens a corpus path, including before a path is
        handed to the browser, which reads it through a URL where no audit hook
        would ever see it.
        """
        if Path(os.fsdecode(path)).stem in self._forbidden:
            raise TestPartitionError(
                f"training tried to read {path}, which is in the test partition. "
                "There is no legitimate reason for training to know where the test "
                "split is (spec section 10.3)."
            )

    def arm(self) -> None:
        """Install the audit hook. Irreversible, which is the point.

        ``sys.addaudithook`` cannot be removed for the life of the process, so
        this is called once from ``main`` and never from a library path. A guard
        that could be turned off would be turned off.
        """
        if self._armed:
            return
        self._armed = True
        forbidden = self._forbidden
        check = self.check

        def hook(event: str, arguments: tuple[Any, ...]) -> None:
            if event != "open" or not forbidden:
                return
            target = arguments[0]
            if isinstance(target, str | bytes | os.PathLike):
                check(os.fsdecode(target))

        sys.addaudithook(hook)


# ---------------------------------------------------------------------------
# The corpus.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Example:
    """One classified control: its descriptor, its truth, and its slices."""

    descriptor: FieldDescriptor
    label: str
    form_id: str
    template_id: str
    locale: str
    tier: str


@dataclass(slots=True)
class Dataset:
    """One partition's examples, plus what was dropped and why."""

    partition: str
    examples: list[Example] = field(default_factory=list)
    forms: int = 0
    undetectable: int = 0
    unkeyed: int = 0

    @property
    def descriptors(self) -> list[FieldDescriptor]:
        """The descriptors, in order."""
        return [item.descriptor for item in self.examples]

    @property
    def labels(self) -> list[str]:
        """The truth labels, in order."""
        return [item.label for item in self.examples]


def _load_split(path: Path) -> Mapping[str, Any]:
    """Read the split document."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise SystemExit(f"{path}: the split file must be an object")
    return document


def _forms_in(split: Mapping[str, Any], partition: str) -> list[str]:
    """Return the form ids of one partition, sorted."""
    assignments = split["form_partitions"]
    return sorted(form_id for form_id, name in assignments.items() if name == partition)


CACHE_KEY_FILE = "corpus.json"
"""Where a descriptor cache records which corpus it was built from."""


class StaleCacheError(RuntimeError):
    """The descriptor cache was built from a different corpus.

    Raised rather than handled, because both quiet alternatives are wrong.
    Reusing the cache would run against last week's pages while reporting this
    week's corpus sha in the manifest, and silently emptying it would delete an
    expensive artefact on the strength of a guess about what the user meant.
    """


def bind_cache(cache: Path | None, corpus_manifest_sha: str) -> None:
    """Tie a descriptor cache to one corpus, or refuse to reuse it.

    P4 left this as a documented sharp edge: the cache was keyed on the form id
    and nothing else, so a corpus regenerated with a different seed or base year
    left a stale cache that nothing would notice. That is survivable for a
    training run, which is iterated on and re-run. It is not survivable from P5
    onward, where a stale cache is a wrong headline number on the test split
    rather than a wrong training run, so the binding is written here.
    """
    if cache is None:
        return
    cache.mkdir(parents=True, exist_ok=True)
    marker = cache / CACHE_KEY_FILE
    if marker.is_file():
        recorded = json.loads(marker.read_text(encoding="utf-8")).get("corpus_manifest_sha")
        if recorded != corpus_manifest_sha:
            raise StaleCacheError(
                f"{cache} was built from corpus {recorded}, and this run is against "
                f"{corpus_manifest_sha}. The cached descriptors are of different pages. "
                "Delete the directory or point --cache somewhere else."
            )
        return
    stale = [path for path in cache.iterdir() if path.suffix == ".json"]
    if stale:
        raise StaleCacheError(
            f"{cache} holds {len(stale)} cached descriptors but records no corpus. It "
            "predates the corpus binding and cannot be shown to match this corpus. "
            "Delete it or point --cache somewhere else."
        )
    marker.write_text(
        json.dumps({"corpus_manifest_sha": corpus_manifest_sha}, indent=2) + "\n",
        encoding="utf-8",
    )


def extract_forms(
    corpus_dir: Path,
    form_ids: Sequence[str],
    guard: TestPartitionGuard,
    cache: Path | None,
    base_year: int,
    timings: MutableMapping[str, float] | None = None,
) -> Iterator[tuple[str, ExtractionResult, Mapping[str, Any]]]:
    """Yield each form's extraction result and answer key.

    The cache exists because extraction drives a real browser over hundreds of
    pages and a training run is something a person iterates on. It is bound to
    one corpus by ``bind_cache``, which the callers run before this, so a
    regenerated corpus is refused rather than quietly reused.

    Public because the evaluation runner needs the same extraction and the same
    cache: an evaluation that re-extracted through a different path could
    disagree with the training run if anything about the extractor moved in
    between, and the disagreement would look like a model result.

    Args:
        timings: accumulates ``load_s``, ``extract_s`` and ``cache_read_s``. An
            explicit out-parameter rather than a return value because this is a
            generator and the totals are only known once it is exhausted. Spec
            section 13.2 wants whole-page wall time split into load, extract,
            classify and render, and the split only means anything if the load
            and the extract are timed where they happen rather than lumped
            together by a caller who can only see the two of them as one call.
    """
    from autofill_audit.extract.walker import ExtractOptions, extract_result
    from autofill_audit.loader import browser_session, load_page

    clock: MutableMapping[str, float] = {} if timings is None else timings
    for name in ("load_s", "extract_s", "cache_read_s"):
        clock.setdefault(name, 0.0)

    options = ExtractOptions(now_year=base_year)
    pending: list[str] = []
    for form_id in form_ids:
        guard.check(form_id)
        cached = None if cache is None else cache / f"{form_id}.json"
        if cached is not None and cached.is_file():
            started = time.perf_counter()
            result = ExtractionResult.from_json(json.loads(cached.read_text(encoding="utf-8")))
            clock["cache_read_s"] += time.perf_counter() - started
            yield form_id, result, _answer_key(corpus_dir, form_id, guard)
            continue
        pending.append(form_id)

    if not pending:
        return
    with browser_session() as browser:
        for form_id in pending:
            page_path = corpus_dir / "forms" / f"{form_id}.html"
            guard.check(page_path)
            started = time.perf_counter()
            with load_page(str(page_path), as_file=True, browser=browser) as loaded:
                loaded_at = time.perf_counter()
                result = extract_result(loaded.page, options=options, settle=loaded.settle)
                extracted_at = time.perf_counter()
            clock["load_s"] += loaded_at - started
            clock["extract_s"] += extracted_at - loaded_at
            if cache is not None:
                cache.mkdir(parents=True, exist_ok=True)
                (cache / f"{form_id}.json").write_text(
                    json.dumps(result.to_json(), ensure_ascii=False), encoding="utf-8"
                )
            yield form_id, result, _answer_key(corpus_dir, form_id, guard)


_extract_forms = extract_forms
"""The former private name, kept so that nothing that used it has to move."""


def _answer_key(corpus_dir: Path, form_id: str, guard: TestPartitionGuard) -> Mapping[str, Any]:
    """Read one answer key, through the guard."""
    path = corpus_dir / "answer_keys" / f"{form_id}.json"
    guard.check(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise SystemExit(f"{path}: an answer key must be an object")
    return document


def examples_for_form(
    form_id: str, result: ExtractionResult, key: Mapping[str, Any]
) -> tuple[list[Example], int, int]:
    """Pair one form's controls with their ground truth.

    Returns the examples, the count of descriptors dropped for naming a blind
    spot, and the count dropped for having no answer-key entry.

    A descriptor that names a blind spot rather than a control is dropped: it has
    no text, no identifiers, and no tokens, so it would contribute a row of
    structural features and a label the model could only learn from position. The
    engines short-circuit those at inference for the same reason, so training on
    them would teach the model something inference never asks it.

    This is one function rather than a loop inside ``build_dataset`` because the
    evaluation runner needs the identical rule and needs the ``ExtractionResult``
    alongside, to run the audit engine's decision procedure over the same page.
    Two implementations of "which controls count" would give two answers to the
    same question, and the answer sets the denominator of every metric.
    """
    truth = {
        str(entry["selector"]): str(entry["label"])
        for entry in key["fields"]
        if isinstance(entry, Mapping)
    }
    examples: list[Example] = []
    undetectable = 0
    unkeyed = 0
    for descriptor in result.fields:
        if descriptor.undetectable_reason is not None:
            undetectable += 1
            continue
        label = truth.get(descriptor.selector)
        if label is None:
            unkeyed += 1
            continue
        examples.append(
            Example(
                descriptor=descriptor,
                label=label,
                form_id=form_id,
                template_id=str(key["template_id"]),
                locale=str(key["locale"]),
                tier=str(key["tier"]),
            )
        )
    return examples, undetectable, unkeyed


def build_dataset(
    corpus_dir: Path,
    split: Mapping[str, Any],
    partition: str,
    guard: TestPartitionGuard,
    cache: Path | None,
    base_year: int,
) -> Dataset:
    """Extract one partition and pair every control with its ground truth."""
    dataset = Dataset(partition=partition)
    form_ids = _forms_in(split, partition)
    for form_id, result, key in extract_forms(corpus_dir, form_ids, guard, cache, base_year):
        dataset.forms += 1
        examples, undetectable, unkeyed = examples_for_form(form_id, result, key)
        dataset.examples.extend(examples)
        dataset.undetectable += undetectable
        dataset.unkeyed += unkeyed
    return dataset


# ---------------------------------------------------------------------------
# Fitting.
# ---------------------------------------------------------------------------


def _to_csr(matrix: Any) -> Any:
    """Adapt the numpy CSR triple to a scipy matrix.

    The two line adapter ``classify/features.py`` promises. scipy lives here
    rather than in ``src/`` so that the installed audit path depends on numpy and
    onnxruntime and nothing else.
    """
    from scipy.sparse import csr_matrix

    return csr_matrix(
        (matrix.data, matrix.indices, matrix.indptr), shape=matrix.shape, dtype="float32"
    )


def _fit(features: Any, labels: Sequence[str], regularisation: float, seed: int) -> Any:
    """Fit one L2 multinomial logistic regression."""
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(
        C=regularisation,
        class_weight="balanced",
        max_iter=4000,
        random_state=seed,
    )
    model.fit(features, labels)
    return model


def _macro_f1(truth: Sequence[str], predicted: Sequence[str]) -> float:
    """Macro-averaged F1 over every label either side names.

    The union rather than the truth's labels alone, which is scikit-learn's own
    default and is the honest denominator: a label the model predicts and the
    truth never carries is a class the model is wrong about, and averaging it
    away would hide exactly that.
    """
    from sklearn.metrics import f1_score

    return float(f1_score(truth, predicted, average="macro", zero_division=0))


def run_sweep(
    train_features: Any,
    train_labels: Sequence[str],
    dev_features: Any,
    dev_labels: Sequence[str],
    grid: Sequence[float],
    seed: int,
) -> tuple[float, list[dict[str, float]]]:
    """Choose the regularisation strength on dev macro-F1.

    On dev, never on test, and recorded cell by cell so that the choice is a
    visible one rather than a number that appeared in a constant.
    """
    results: list[dict[str, float]] = []
    best_value = grid[0]
    best_score = -1.0
    for value in grid:
        model = _fit(train_features, train_labels, value, seed)
        score = _macro_f1(dev_labels, list(model.predict(dev_features)))
        results.append({"C": value, "dev_macro_f1": score})
        print(f"  C={value:<6} dev macro-F1 {score:.4f}")
        if score > best_score:
            best_value, best_score = value, score
    return best_value, results


# ---------------------------------------------------------------------------
# Calibration (spec section 10.4).
# ---------------------------------------------------------------------------


def fit_calibration(raw: Any, dev_labels: Sequence[str], classes: Sequence[str]) -> Calibration:
    """Fit one calibrator per class on dev, one-vs-rest.

    The switchover is the pre-registered one: isotonic where a class has enough
    dev positives for a step function to be stable, Platt scaling below that, and
    the identity where there are too few positives to fit anything at all. The
    method actually used is recorded per label, because the model card has to
    state what happened and not what was intended.
    """
    import numpy as np
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression

    truth = np.asarray(dev_labels)
    fitted: list[ClassCalibration] = []
    for column, name in enumerate(classes):
        scores = raw[:, column]
        binary = (truth == name).astype(int)
        positives = int(binary.sum())
        if positives < MIN_SIGMOID_POSITIVES or positives == len(binary):
            fitted.append(ClassCalibration(label=name, method="identity", dev_positives=positives))
            continue
        if positives >= ISOTONIC_SWITCHOVER:
            isotonic = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            isotonic.fit(scores, binary)
            fitted.append(
                ClassCalibration(
                    label=name,
                    method="isotonic",
                    dev_positives=positives,
                    thresholds=tuple(float(value) for value in isotonic.X_thresholds_),
                    values=tuple(float(value) for value in isotonic.y_thresholds_),
                )
            )
            continue
        logit = np.log(np.clip(scores, 1e-12, 1 - 1e-12) / (1 - np.clip(scores, 1e-12, 1 - 1e-12)))
        platt = LogisticRegression(max_iter=1000)
        platt.fit(logit.reshape(-1, 1), binary)
        fitted.append(
            ClassCalibration(
                label=name,
                method="sigmoid",
                dev_positives=positives,
                slope=float(platt.coef_[0][0]),
                intercept=float(platt.intercept_[0]),
            )
        )
    return Calibration(classes=tuple(fitted), switchover_count=ISOTONIC_SWITCHOVER, fitted_on=DEV)


# ---------------------------------------------------------------------------
# Metrics.
# ---------------------------------------------------------------------------


def reliability(probabilities: Any, truth: Sequence[str], classes: Sequence[str]) -> dict[str, Any]:
    """Return the reliability curve and the expected calibration error.

    Equal-width bins over the winning class's probability, each carrying its
    count, its mean predicted probability, and the fraction it actually got
    right. Expected calibration error is the count-weighted mean gap between
    those last two, which is the number spec section 10.4 asks to be reported
    rather than merely computed.
    """
    import numpy as np

    winner = np.argmax(probabilities, axis=1)
    confidence = probabilities[np.arange(len(winner)), winner]
    correct = np.asarray(
        [classes[int(index)] == label for index, label in zip(winner, truth, strict=True)]
    )
    edges = np.linspace(0.0, 1.0, RELIABILITY_BINS + 1)
    bins: list[dict[str, float]] = []
    error = 0.0
    total = len(confidence)
    for position in range(RELIABILITY_BINS):
        low, high = edges[position], edges[position + 1]
        inside = (confidence > low) & (confidence <= high) if position else (confidence <= high)
        count = int(inside.sum())
        if count == 0:
            bins.append({"low": float(low), "high": float(high), "count": 0})
            continue
        mean_predicted = float(confidence[inside].mean())
        mean_observed = float(correct[inside].mean())
        bins.append(
            {
                "low": float(low),
                "high": float(high),
                "count": count,
                "mean_predicted": mean_predicted,
                "mean_observed": mean_observed,
            }
        )
        error += (count / total) * abs(mean_predicted - mean_observed)
    return {"bins": bins, "expected_calibration_error": error}


def per_label_report(
    truth: Sequence[str], predicted: Sequence[str], train_labels: Sequence[str]
) -> dict[str, dict[str, float]]:
    """Per-label precision, recall, F1, and both supports."""
    from sklearn.metrics import precision_recall_fscore_support

    names = sorted(set(truth) | set(predicted))
    precision, recall, f1, support = precision_recall_fscore_support(
        truth, predicted, labels=names, zero_division=0
    )
    counts = {name: train_labels.count(name) for name in names}
    return {
        name: {
            "precision": float(precision[position]),
            "recall": float(recall[position]),
            "f1": float(f1[position]),
            "dev_support": int(support[position]),
            "train_support": counts[name],
        }
        for position, name in enumerate(names)
    }


def slice_report(
    examples: Sequence[Example], predicted: Sequence[str], key: str
) -> dict[str, dict[str, Any]]:
    """Macro-F1 per slice, with the insufficient-data rule enforced.

    A cell below the minimum reports its count and a null metric rather than a
    number. That rule is in code here rather than in a caveat in prose, because a
    caveat in prose gets dropped when the table is copied into a report.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    for example, prediction in zip(examples, predicted, strict=True):
        groups.setdefault(getattr(example, key), []).append((example.label, prediction))
    report: dict[str, dict[str, Any]] = {}
    for name, pairs in sorted(groups.items()):
        truth = [pair[0] for pair in pairs]
        guesses = [pair[1] for pair in pairs]
        accurate = sum(1 for a, b in pairs if a == b) / len(pairs)
        enough = len(pairs) >= INSUFFICIENT_DATA_MINIMUM
        report[name] = {
            "count": len(pairs),
            "accuracy": accurate if enough else None,
            "macro_f1": _macro_f1(truth, guesses) if enough else None,
            "insufficient_data": not enough,
        }
    return report


def confusion_pairs(truth: Sequence[str], predicted: Sequence[str]) -> list[dict[str, Any]]:
    """The most frequent wrong pairs, which is what the write-up calls out."""
    counts: dict[tuple[str, str], int] = {}
    for actual, guess in zip(truth, predicted, strict=True):
        if actual != guess:
            counts[(actual, guess)] = counts.get((actual, guess), 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"truth": pair[0], "predicted": pair[1], "count": count}
        for pair, count in ordered[:TOP_CONFUSIONS]
    ]


# ---------------------------------------------------------------------------
# Export.
# ---------------------------------------------------------------------------


def export_onnx(model: Any, width: int, destination: Path) -> int:
    """Export the linear layer, at the newest opset onnxruntime will accept.

    Probed rather than copied from anywhere (spec section 10.5). The probe walks
    down from the newest opset the installed ``onnx`` package defines and takes
    the first that both converts and opens in a session, so the recorded number
    is a fact about this machine's resolved versions rather than a number that
    was true once somewhere else.
    """
    import onnx
    import onnxruntime
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    initial = [("features", FloatTensorType([None, width]))]
    highest = int(onnx.defs.onnx_opset_version())
    failures: list[str] = []
    for opset in range(highest, highest - 12, -1):
        try:
            graph = convert_sklearn(
                model,
                initial_types=initial,
                target_opset=opset,
                options={id(model): {"zipmap": False}},
            )
            payload = graph.SerializeToString()
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = 1
            onnxruntime.InferenceSession(
                payload, sess_options=options, providers=["CPUExecutionProvider"]
            )
        except Exception as error:
            failures.append(f"opset {opset}: {type(error).__name__}: {error}")
            continue
        destination.write_bytes(payload)
        for line in failures:
            print(f"  probe rejected {line}")
        print(f"  probe accepted opset {opset}")
        return opset
    raise SystemExit(
        "no opset in the probed range converted and loaded:\n  " + "\n  ".join(failures)
    )


def evidence_table(model: Any, space: FeatureSpace) -> dict[str, list[list[Any]]]:
    """The highest weighted features per class, for the inference path.

    A slice of the exported matrix rather than a second source of truth: the
    parity suite reads the weights back out of the graph and asserts this table
    agrees with them, so a stale evidence file fails the build rather than
    quietly naming the wrong n-grams.
    """
    import numpy as np

    table: dict[str, list[list[Any]]] = {}
    coefficients = np.asarray(model.coef_)
    for position, name in enumerate(model.classes_):
        row = coefficients[position]
        order = np.argsort(-row)[:EVIDENCE_PER_CLASS]
        table[str(name)] = [
            [space.names[int(column)], float(row[int(column)])]
            for column in order
            if float(row[int(column)]) > 0.0
        ]
    return table


def parity_check(model: Any, path: Path, dense: Any) -> dict[str, Any]:
    """Compare scikit-learn and onnxruntime over every row given.

    The gate of spec section 10.5. Exact argmax agreement on every row plus
    per-class probability agreement within the pre-registered tolerance. Run here
    so that a training run cannot produce an artefact that fails it, and again in
    the committed test suite so that a checkout cannot carry one.
    """
    import numpy as np
    import onnxruntime

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = onnxruntime.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    output = next(item.name for item in session.get_outputs() if len(item.shape) == 2)
    onnx_probabilities = np.asarray(
        session.run([output], {session.get_inputs()[0].name: dense})[0], dtype=np.float64
    )
    sklearn_probabilities = np.asarray(model.predict_proba(dense), dtype=np.float64)

    agreement = int(
        (np.argmax(onnx_probabilities, axis=1) == np.argmax(sklearn_probabilities, axis=1)).sum()
    )
    delta = float(np.max(np.abs(onnx_probabilities - sklearn_probabilities)))
    return {
        "rows": int(dense.shape[0]),
        "argmax_agreements": agreement,
        "argmax_agreement_rate": agreement / max(int(dense.shape[0]), 1),
        "max_absolute_probability_delta": delta,
        "tolerance": PARITY_TOLERANCE,
        "passed": agreement == int(dense.shape[0]) and delta <= PARITY_TOLERANCE,
    }


# ---------------------------------------------------------------------------
# The manifest.
# ---------------------------------------------------------------------------


def _git(*arguments: str) -> str:
    """Run one git command in the repository, or return the empty string."""
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:  # pragma: no cover - git is present on the build machine
        return ""
    return completed.stdout.strip()


def _dirty(out: Path) -> bool:
    """Whether the tree differs from HEAD, ignoring the output directory.

    Spec section 18: a result produced from a dirty tree is marked dirty and is
    not citable, so this flag decides whether the artefact beside it can be cited
    at all and it is worth getting exactly right.

    The output directory is excluded, and only it. On a first run models/ does
    not exist in HEAD, so counting it would mark every first training run dirty by
    construction and make the flag mean nothing. Everything else counts, untracked
    files included: a source file nobody committed is a source file nobody can
    reproduce the run from.
    """
    status = _git("status", "--porcelain")
    if not status:
        return False
    try:
        relative = out.resolve().relative_to(_REPO_ROOT)
    except ValueError:
        relative = out
    prefix = f"{relative}/"
    for line in status.splitlines():
        path = line[3:].strip().strip('"')
        if path == str(relative) or path.startswith(prefix):
            continue
        return True
    return False


def _dependency_versions() -> dict[str, str]:
    """The resolved versions of everything this run depended on."""
    from importlib.metadata import PackageNotFoundError, version

    names = (
        "numpy",
        "onnx",
        "onnxruntime",
        "playwright",
        "scikit-learn",
        "scipy",
        "skl2onnx",
    )
    resolved: dict[str, str] = {"python": platform.python_version()}
    for name in names:
        try:
            resolved[name] = version(name)
        except PackageNotFoundError:  # pragma: no cover - the lock file installs all of them
            resolved[name] = "absent"
    return resolved


def _sha256_of(path: Path) -> str:
    """The sha256 of a file, for the manifest."""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _corpus_manifest_sha(corpus_dir: Path) -> str:
    """The sha the corpus recorded for itself, which identifies the corpus."""
    manifest = corpus_dir / "manifest.json"
    if not manifest.is_file():
        return "absent"
    return _sha256_of(manifest)


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line of spec section 14's ``train``.

    There is no ``--test`` flag and there will not be one. Spec section 14 states
    it as a contract rather than as an omission, and the guard above enforces the
    same thing from the other end.
    """
    parser = argparse.ArgumentParser(description="Train the n-gram model (spec section 10.3).")
    parser.add_argument("--corpus", type=Path, default=Path("corpus"))
    parser.add_argument("--split-file", type=Path, default=None)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--sweep",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="choose the regularisation strength on dev; --no-sweep takes the grid's middle",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="reuse extracted descriptors from this directory, and write them there",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Train, calibrate, export, and write every artefact of the contract."""
    args = _arguments(argv)
    corpus_dir: Path = args.corpus
    split_path: Path = args.split_file if args.split_file else corpus_dir / "split.json"
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    started = datetime.now(UTC)
    split = _load_split(split_path)
    guard = TestPartitionGuard(frozenset(_forms_in(split, TEST)))
    guard.arm()
    print(f"train.py: guarding {len(guard.forbidden)} test-partition forms")

    manifest_document = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    base_year = int(manifest_document.get("base_year", time.gmtime().tm_year))

    cache: Path | None = args.cache
    bind_cache(cache, _corpus_manifest_sha(corpus_dir))
    print(f"train.py: extracting the {TRAIN} partition")
    train_set = build_dataset(corpus_dir, split, TRAIN, guard, cache, base_year)
    print(f"  {train_set.forms} forms, {len(train_set.examples)} rows")
    print(f"train.py: extracting the {DEV} partition")
    dev_set = build_dataset(corpus_dir, split, DEV, guard, cache, base_year)
    print(f"  {dev_set.forms} forms, {len(dev_set.examples)} rows")

    config = FeatureConfig()
    space = fit_feature_space(train_set.descriptors, config)
    print(f"train.py: {space.width} features {space.block_counts()}")

    train_features = _to_csr(featurize(train_set.descriptors, space))
    dev_matrix = featurize(dev_set.descriptors, space)
    dev_features = _to_csr(dev_matrix)

    grid = SWEEP_GRID if args.sweep else (1.0,)
    print("train.py: sweeping the regularisation strength on dev")
    chosen, sweep_results = run_sweep(
        train_features, train_set.labels, dev_features, dev_set.labels, grid, args.seed
    )
    print(f"train.py: chose C={chosen}")
    model = _fit(train_features, train_set.labels, chosen, args.seed)
    classes = [str(name) for name in model.classes_]

    import numpy as np

    raw_dev = np.asarray(model.predict_proba(dev_features), dtype=np.float64)
    calibration = fit_calibration(raw_dev, dev_set.labels, classes)
    calibrated_dev = calibration.apply(raw_dev)

    raw_predictions = [classes[int(index)] for index in np.argmax(raw_dev, axis=1)]
    calibrated_predictions = [classes[int(index)] for index in np.argmax(calibrated_dev, axis=1)]

    macro = _macro_f1(dev_set.labels, calibrated_predictions)
    micro = sum(
        1 for a, b in zip(dev_set.labels, calibrated_predictions, strict=True) if a == b
    ) / max(len(dev_set.labels), 1)
    print(f"train.py: dev macro-F1 {macro:.4f}, dev accuracy {micro:.4f}")

    model_path = out / MODEL_FILE
    opset = export_onnx(model, space.width, model_path)
    dense = dev_matrix.to_dense()
    parity = parity_check(model, model_path, dense)
    print(
        f"train.py: parity over {parity['rows']} dev rows, "
        f"argmax agreements {parity['argmax_agreements']}, "
        f"max probability delta {parity['max_absolute_probability_delta']:.3e}"
    )
    if not parity["passed"]:
        raise SystemExit("train.py: the parity self-check failed; nothing was written")

    (out / VOCAB_FILE).write_text(
        json.dumps(space.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / LABEL_MAP_FILE).write_text(
        json.dumps(
            {"schema_version": LABEL_MAP_SCHEMA_VERSION, "labels": classes},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / CALIBRATION_FILE).write_text(
        json.dumps(calibration.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / EVIDENCE_FILE).write_text(
        json.dumps(
            {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "features_per_class": EVIDENCE_PER_CLASS,
                "classes": evidence_table(model, space),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = {
        "schema_version": 1,
        "split": DEV,
        "generated_on": started.date().isoformat(),
        "corpus_manifest_sha256": _corpus_manifest_sha(corpus_dir),
        "counts": {
            "train_forms": train_set.forms,
            "train_rows": len(train_set.examples),
            "dev_forms": dev_set.forms,
            "dev_rows": len(dev_set.examples),
            "excluded_forms": len(_forms_in(split, EXCLUDED)),
            "classes_fitted": len(classes),
            "labels_in_dev_only": sorted(set(dev_set.labels) - set(train_set.labels)),
            "dropped_undetectable": train_set.undetectable + dev_set.undetectable,
            "dropped_unkeyed": train_set.unkeyed + dev_set.unkeyed,
        },
        "sweep": {"grid": list(grid), "results": sweep_results, "chosen_C": chosen},
        "headline": {"dev_macro_f1": macro, "dev_accuracy": micro},
        "per_label": per_label_report(dev_set.labels, calibrated_predictions, train_set.labels),
        "slices": {
            "per_locale": slice_report(dev_set.examples, calibrated_predictions, "locale"),
            "per_tier": slice_report(dev_set.examples, calibrated_predictions, "tier"),
        },
        "insufficient_data_minimum": INSUFFICIENT_DATA_MINIMUM,
        "calibration": {
            "switchover_count": ISOTONIC_SWITCHOVER,
            "methods": calibration.methods(),
            "dev_positives": {item.label: item.dev_positives for item in calibration.classes},
            "before": reliability(raw_dev, dev_set.labels, classes),
            "after": reliability(calibrated_dev, dev_set.labels, classes),
            "macro_f1_before_calibration": _macro_f1(dev_set.labels, raw_predictions),
        },
        "abstention": _abstention(dev_set.labels, calibrated_predictions),
        "confusions": confusion_pairs(dev_set.labels, calibrated_predictions),
        "parity": parity,
    }
    (out / DEV_METRICS_FILE).write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    manifest = {
        "schema_version": 1,
        "tool_version": __version__,
        "git_sha": _git("rev-parse", "HEAD"),
        "git_dirty": _dirty(out),
        "seed": args.seed,
        "corpus_manifest_sha256": _corpus_manifest_sha(corpus_dir),
        "split_file_sha256": _sha256_of(split_path),
        "split_counts": split.get("form_counts", {}),
        "held_out_locale": split.get("held_out_locale"),
        "excluded_partition_used_for": "nothing at P4",
        "feature_config": config.to_json(),
        "feature_width": space.width,
        "feature_blocks": space.block_counts(),
        "sweep_grid": list(grid),
        "chosen_hyperparameters": {
            "C": chosen,
            "penalty": "l2",
            "class_weight": "balanced",
            "solver": "lbfgs",
        },
        "calibration_switchover": ISOTONIC_SWITCHOVER,
        "onnx_opset": opset,
        "dependencies": _dependency_versions(),
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor() or "unrecorded",
            "cpu_count": os.cpu_count() or 0,
            "gpu_used": False,
        },
        "command_line": " ".join([Path(sys.argv[0]).name, *sys.argv[1:]]),
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    (out / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"train.py: wrote the bundle to {out}")
    return 0


def _abstention(truth: Sequence[str], predicted: Sequence[str]) -> dict[str, float]:
    """The abstention rate and the accuracy on what was not abstained.

    Spec section 13.2 asks for both, because a classifier that abstains often and
    is right when it commits is a legitimate design and reporting only accuracy
    hides it.
    """
    unknown = Label.UNKNOWN.value
    committed = [
        (actual, guess) for actual, guess in zip(truth, predicted, strict=True) if guess != unknown
    ]
    total = max(len(predicted), 1)
    return {
        "unknown_rate": (len(predicted) - len(committed)) / total,
        "accuracy_when_committed": (
            sum(1 for a, b in committed if a == b) / len(committed) if committed else 0.0
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
