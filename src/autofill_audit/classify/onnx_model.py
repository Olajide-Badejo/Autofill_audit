"""The onnxruntime CPU session, the calibration it applies, and the engine.

Spec sections 5.4, 10.4, and 10.5. CPU execution provider named explicitly, with
intra-op threads pinned to one: a per-field classification is far too small to
benefit from threading, and thread-pool spin-up would dominate the measurement
and make every latency number meaningless.

What is in the graph and what is not
------------------------------------

The exported graph holds the linear layer and nothing else: a matrix multiply, a
bias, and a softmax. Featurisation happens in ``classify/features.py``, in
Python, on both sides of the train/serve boundary, and calibration happens in
this module after the session returns. That is the spec section 10.5 fallback
route, taken deliberately and recorded with its evidence in
``docs/adr/0006-onnx-export-path.md``.

The consequence worth stating plainly: what the parity test compares is the
linear layer, because the linear layer is the whole of what was exported. There
is no vectorizer inside the graph whose tokenisation could diverge from Python's,
because there is no vectorizer inside the graph.

Calibration
-----------

Findings quote confidence, and a confidence is a frequency claim (spec section
10.4). The raw softmax of an L2-regularised linear model on a small corpus is
systematically overconfident, so quoting it would be a fabricated number with
extra steps. ``calibration.json`` carries one calibrator per class, fitted on
dev, with the method actually used recorded per label, and this module applies
them one-vs-rest and renormalises.

**Applying the calibration lives here rather than in the training script**, for
the same reason featurisation lives in one module: the expected calibration error
recorded in ``dev_metrics.json`` has to describe what the tool actually does. The
training script imports this applier, so the number it reports and the number a
user experiences come from one implementation.

Abstention
----------

When the winning class is ``UNKNOWN`` the reported confidence is zero, exactly as
the rule engine reports it, rather than the calibrated probability of the
``UNKNOWN`` class. The decision procedure of spec section 11.2 treats ``UNKNOWN``
as "the tool has nothing to say", and it reaches that outcome through
``declaration_for`` returning nothing rather than through the confidence, which
means a model emitting a high confidence there would be relying on an accident.
This is the explicit branch P3's handoff asked for. The calibrated probability is
not lost: the second class and its probability are on ``runner_up``.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Self

import numpy as np

from autofill_audit import __version__
from autofill_audit.classify.base import (
    CONFIDENCE_KIND_KEY,
    CONFIDENCE_KIND_PROBABILITY,
)
from autofill_audit.classify.features import (
    FeatureSpace,
    FeatureSpaceError,
    featurize,
    signal_name,
)
from autofill_audit.descriptors import FieldDescriptor, Prediction
from autofill_audit.taxonomy import Label

__all__ = [
    "CALIBRATION_FILE",
    "CALIBRATION_SCHEMA_VERSION",
    "ENGINE_NAME",
    "EVIDENCE_FILE",
    "EVIDENCE_SCHEMA_VERSION",
    "LABEL_MAP_FILE",
    "LABEL_MAP_SCHEMA_VERSION",
    "MAX_SIGNALS",
    "MODEL_DIR_ENV",
    "MODEL_FILE",
    "VOCAB_FILE",
    "Calibration",
    "ClassCalibration",
    "ModelBundle",
    "ModelLoadError",
    "NgramClassifier",
    "find_model_dir",
    "load_bundle",
    "load_ngram_engine",
]

ENGINE_NAME: Final[str] = "ngram"
"""What lands in ``Prediction.engine``, and the value ``--engine ngram`` takes."""

MODEL_FILE: Final[str] = "model.onnx"
VOCAB_FILE: Final[str] = "vocab.json"
CALIBRATION_FILE: Final[str] = "calibration.json"
LABEL_MAP_FILE: Final[str] = "label_map.json"
EVIDENCE_FILE: Final[str] = "evidence.json"
MANIFEST_FILE: Final[str] = "train_manifest.json"

MODEL_DIR_ENV: Final[str] = "AUTOFILL_AUDIT_MODEL_DIR"
"""Overrides the search. A test that wants a particular bundle sets this rather
than arranging a working directory, and an operator who keeps models elsewhere
does the same thing for the same reason."""

_MODEL_DIRNAME: Final[str] = "models"

CALIBRATION_SCHEMA_VERSION: Final[int] = 1
LABEL_MAP_SCHEMA_VERSION: Final[int] = 1
EVIDENCE_SCHEMA_VERSION: Final[int] = 1

MAX_SIGNALS: Final[int] = 8
"""How many features a prediction names as evidence.

Bounded because the rule engine's list is bounded by the tier that answered and
this one has no such natural bound. A hundred feature weights in ``signals``
would make the JSON report several times larger than the page it describes, and
the terminal renderer shows six of them anyway."""

_RUNNER_UP_SIGNALS: Final[int] = 2
"""How many of those go to the class that did not win.

P3's convention is that every rule which fired is recorded, not only the
winner's, because the losing candidate's evidence is the explanation for why it
lost. The analogue for a model is the runner-up's strongest contributors."""

_ABSTAIN_SIGNAL: Final[str] = "ngram:abstain:unknown-class"
"""Recorded when the winning class is the abstention, so that a report says the
model looked and had nothing rather than saying nothing at all."""

_EPSILON: Final[float] = 1e-12
"""Guards a division by a renormalisation total and a logit of zero or one."""

type Probabilities = np.typing.NDArray[np.float64]
"""A row per control, a column per class. Named because the shape appears in
five signatures and a reader should not have to reconstruct it in each of them."""


class ModelLoadError(RuntimeError):
    """A model bundle is absent, incomplete, or unreadable.

    One exception for every way loading can fail, because the caller's decision
    is the same in every case: ``auto`` falls back to the rule baseline and says
    so, and a named engine refuses. Distinguishing "no file" from "corrupt file"
    would give the caller a choice it does not want to make.
    """


# ---------------------------------------------------------------------------
# Calibration (spec section 10.4).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClassCalibration:
    """One class's calibrator, and the record of which method produced it.

    Three methods, and the third is the honest one. ``isotonic`` for a class with
    enough dev examples for a step function to be stable, ``sigmoid`` for one
    without, and ``identity`` for a class the dev split barely contains at all,
    where fitting anything would be fitting noise. An identity calibrator passes
    the raw probability through, which is uncalibrated, and ``calibration.json``
    says so per label so that the model card can too.
    """

    label: str
    method: str
    dev_positives: int
    thresholds: tuple[float, ...] = ()
    values: tuple[float, ...] = ()
    slope: float = 1.0
    intercept: float = 0.0

    def apply(self, raw: Probabilities) -> Probabilities:
        """Map raw one-vs-rest probabilities to calibrated ones."""
        if self.method == "isotonic" and self.thresholds:
            interpolated = np.asarray(
                np.interp(raw, np.asarray(self.thresholds), np.asarray(self.values)),
                dtype=np.float64,
            )
            return np.asarray(np.clip(interpolated, 0.0, 1.0), dtype=np.float64)
        if self.method == "sigmoid":
            clipped = np.clip(raw, _EPSILON, 1.0 - _EPSILON)
            logit = np.log(clipped / (1.0 - clipped))
            return np.asarray(1.0 / (1.0 + np.exp(-(self.slope * logit + self.intercept))))
        return np.asarray(np.clip(raw, 0.0, 1.0), dtype=np.float64)

    def to_json(self) -> dict[str, Any]:
        """Emit the committed form."""
        payload: dict[str, Any] = {
            "label": self.label,
            "method": self.method,
            "dev_positives": self.dev_positives,
        }
        if self.method == "isotonic":
            payload["thresholds"] = list(self.thresholds)
            payload["values"] = list(self.values)
        elif self.method == "sigmoid":
            payload["slope"] = self.slope
            payload["intercept"] = self.intercept
        return payload

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the committed form."""
        label = payload.get("label")
        method = payload.get("method")
        if not isinstance(label, str) or not isinstance(method, str):
            raise ModelLoadError(f"{CALIBRATION_FILE}: a class needs a label and a method")
        positives = payload.get("dev_positives", 0)
        if isinstance(positives, bool) or not isinstance(positives, int):
            raise ModelLoadError(f"{CALIBRATION_FILE}: {label}: dev_positives must be an integer")
        return cls(
            label=label,
            method=method,
            dev_positives=positives,
            thresholds=_float_tuple(payload, "thresholds", label),
            values=_float_tuple(payload, "values", label),
            slope=_float(payload, "slope", label, 1.0),
            intercept=_float(payload, "intercept", label, 0.0),
        )


def _float_tuple(payload: Mapping[str, Any], key: str, label: str) -> tuple[float, ...]:
    """Read a list of numbers, treating absence as empty."""
    raw = payload.get(key, ())
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        raise ModelLoadError(f"{CALIBRATION_FILE}: {label}: {key} must be a list of numbers")
    values: list[float] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise ModelLoadError(f"{CALIBRATION_FILE}: {label}: {key} must be a list of numbers")
        values.append(float(item))
    return tuple(values)


def _float(payload: Mapping[str, Any], key: str, label: str, default: float) -> float:
    """Read a number, treating absence as the default."""
    raw = payload.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ModelLoadError(f"{CALIBRATION_FILE}: {label}: {key} must be a number")
    return float(raw)


@dataclass(frozen=True, slots=True)
class Calibration:
    """The per-class calibrators, applied one-vs-rest with renormalisation."""

    classes: tuple[ClassCalibration, ...]
    switchover_count: int
    fitted_on: str

    def methods(self) -> dict[str, str]:
        """Label to method, for the model card and for ``describe()``."""
        return {item.label: item.method for item in self.classes}

    def apply(self, probabilities: Probabilities) -> Probabilities:
        """Return calibrated, renormalised probabilities for a batch of rows.

        One-vs-rest per spec section 10.4, then a renormalisation step, because
        independently calibrated per-class probabilities do not sum to one and a
        confidence taken from a row summing to one point three would be a
        frequency claim about nothing.

        A row whose calibrated values all collapse to zero keeps its raw
        distribution rather than becoming a division by zero or a uniform
        fabrication. That happens when every class was mapped to zero by an
        isotonic step, and the raw row is the only honest thing left to report.
        """
        if probabilities.shape[1] != len(self.classes):
            raise ModelLoadError(
                f"{CALIBRATION_FILE}: carries {len(self.classes)} classes but the model "
                f"emits {probabilities.shape[1]}"
            )
        calibrated = np.empty_like(probabilities, dtype=np.float64)
        for column, item in enumerate(self.classes):
            calibrated[:, column] = item.apply(probabilities[:, column])
        totals = calibrated.sum(axis=1, keepdims=True)
        safe = totals > _EPSILON
        result = np.where(safe, calibrated / np.where(safe, totals, 1.0), probabilities)
        return np.asarray(result, dtype=np.float64)

    def to_json(self) -> dict[str, Any]:
        """Emit the committed document."""
        return {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "fitted_on": self.fitted_on,
            "switchover_count": self.switchover_count,
            "classes": [item.to_json() for item in self.classes],
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the committed document."""
        version = payload.get("schema_version")
        if version != CALIBRATION_SCHEMA_VERSION:
            raise ModelLoadError(
                f"{CALIBRATION_FILE}: this build reads schema version "
                f"{CALIBRATION_SCHEMA_VERSION}, found {version!r}"
            )
        raw = payload.get("classes")
        if not isinstance(raw, list) or not raw:
            raise ModelLoadError(f"{CALIBRATION_FILE}: classes must be a non-empty list")
        switchover = payload.get("switchover_count", 0)
        if isinstance(switchover, bool) or not isinstance(switchover, int):
            raise ModelLoadError(f"{CALIBRATION_FILE}: switchover_count must be an integer")
        fitted_on = payload.get("fitted_on")
        if not isinstance(fitted_on, str) or not fitted_on:
            raise ModelLoadError(f"{CALIBRATION_FILE}: fitted_on must name the split")
        return cls(
            classes=tuple(ClassCalibration.from_json(_mapping(item)) for item in raw),
            switchover_count=switchover,
            fitted_on=fitted_on,
        )


def _mapping(value: Any) -> Mapping[str, Any]:
    """Return ``value`` as a mapping, or raise."""
    if not isinstance(value, Mapping):
        raise ModelLoadError(f"expected an object, found {type(value).__name__}")
    return value


# ---------------------------------------------------------------------------
# The bundle on disk.
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    """Return a file's sha256, which is what ``describe()`` reports as identity."""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def find_model_dir(start: Path | None = None) -> Path | None:
    """Return the model directory, or None when there is not one.

    Search order: the environment override, then a ``models`` directory found by
    walking up from the working directory, then one found by walking up from this
    package. The last of those is what makes an editable install and a source
    checkout behave identically without either of them configuring anything.

    A wheel built today does not carry the artefacts, so a ``pipx`` install finds
    nothing here and ``auto`` falls back to the rule baseline with its notice,
    which is the documented behaviour of spec section 10.1 rather than a failure.
    Whether a release wheel should carry a model is a packaging decision, it is
    recorded as one in ADR 0006, and P7 is the phase that makes it.
    """
    override = os.environ.get(MODEL_DIR_ENV)
    if override:
        candidate = Path(override)
        return candidate if (candidate / MODEL_FILE).is_file() else None
    roots = [start if start is not None else Path.cwd(), Path(__file__).resolve()]
    for root in roots:
        for directory in (root, *root.parents):
            candidate = directory / _MODEL_DIRNAME
            if (candidate / MODEL_FILE).is_file():
                return candidate
    return None


@dataclass(frozen=True, slots=True)
class ModelBundle:
    """Everything one trained model consists of, loaded and checked together.

    Loaded as a unit because the four files are one artefact: a vocabulary from
    one run beside a calibration from another would produce confident nonsense
    with nothing to notice it. The cross-checks below are the cheap version of
    noticing.
    """

    directory: Path
    space: FeatureSpace
    labels: tuple[str, ...]
    calibration: Calibration
    evidence: Mapping[str, tuple[tuple[str, float], ...]]
    shas: Mapping[str, str]
    opset: str

    def identity(self) -> dict[str, str]:
        """The identity keys ``describe()`` copies into the run manifest."""
        return {
            "model_sha256": self.shas[MODEL_FILE],
            "vocab_sha256": self.shas[VOCAB_FILE],
            "calibration_sha256": self.shas[CALIBRATION_FILE],
            "label_map_sha256": self.shas[LABEL_MAP_FILE],
            "feature_width": str(self.space.width),
            "class_count": str(len(self.labels)),
            "onnx_opset": self.opset,
        }


def _read_json(path: Path) -> Any:
    """Read one JSON document, naming the file when it cannot be read."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ModelLoadError(f"{path.name}: cannot be read ({error})") from error
    except json.JSONDecodeError as error:
        raise ModelLoadError(f"{path.name}: not valid JSON ({error})") from error


def _load_labels(path: Path) -> tuple[str, ...]:
    """Read ``label_map.json``, in the class order the model emits."""
    payload = _read_json(path)
    if not isinstance(payload, Mapping):
        raise ModelLoadError(f"{LABEL_MAP_FILE}: expected an object")
    version = payload.get("schema_version")
    if version != LABEL_MAP_SCHEMA_VERSION:
        raise ModelLoadError(
            f"{LABEL_MAP_FILE}: this build reads schema version "
            f"{LABEL_MAP_SCHEMA_VERSION}, found {version!r}"
        )
    raw = payload.get("labels")
    if not isinstance(raw, list) or not raw:
        raise ModelLoadError(f"{LABEL_MAP_FILE}: labels must be a non-empty list")
    labels: list[str] = []
    known = {label.value for label in Label}
    for item in raw:
        if not isinstance(item, str) or item not in known:
            raise ModelLoadError(f"{LABEL_MAP_FILE}: {item!r} is not a taxonomy label")
        labels.append(item)
    return tuple(labels)


def _load_evidence(path: Path) -> Mapping[str, tuple[tuple[str, float], ...]]:
    """Read the per-class top weights the evidence list is drawn from.

    A slice of the exported weight matrix, written by the same training run and
    checked against the graph by the parity suite. It exists because onnxruntime
    does not hand a caller its own initialisers, and reading the graph would put
    the ``onnx`` package on the runtime dependency list to produce one line of a
    report.
    """
    if not path.is_file():
        return {}
    payload = _read_json(path)
    if not isinstance(payload, Mapping):
        raise ModelLoadError(f"{EVIDENCE_FILE}: expected an object")
    version = payload.get("schema_version")
    if version != EVIDENCE_SCHEMA_VERSION:
        raise ModelLoadError(
            f"{EVIDENCE_FILE}: this build reads schema version "
            f"{EVIDENCE_SCHEMA_VERSION}, found {version!r}"
        )
    classes = payload.get("classes")
    if not isinstance(classes, Mapping):
        raise ModelLoadError(f"{EVIDENCE_FILE}: classes must be an object")
    table: dict[str, tuple[tuple[str, float], ...]] = {}
    for label, entries in classes.items():
        if not isinstance(entries, list):
            raise ModelLoadError(f"{EVIDENCE_FILE}: {label}: expected a list")
        table[str(label)] = tuple(_evidence_pair(entry, str(label)) for entry in entries)
    return table


def _evidence_pair(entry: Any, label: str) -> tuple[str, float]:
    """Read one feature name and weight pair."""
    if isinstance(entry, str) or not isinstance(entry, Sequence) or len(entry) != 2:
        raise ModelLoadError(f"{EVIDENCE_FILE}: {label}: expected name and weight pairs")
    name, weight = entry[0], entry[1]
    if not isinstance(name, str) or isinstance(weight, bool):
        raise ModelLoadError(f"{EVIDENCE_FILE}: {label}: expected name and weight pairs")
    if not isinstance(weight, int | float):
        raise ModelLoadError(f"{EVIDENCE_FILE}: {label}: expected name and weight pairs")
    return name, float(weight)


def load_bundle(directory: Path) -> ModelBundle:
    """Load and cross-check one model directory.

    Raises:
        ModelLoadError: anything that would make the bundle unsafe to run.
    """
    missing = [
        name
        for name in (MODEL_FILE, VOCAB_FILE, CALIBRATION_FILE, LABEL_MAP_FILE)
        if not (directory / name).is_file()
    ]
    if missing:
        raise ModelLoadError(f"{directory}: the model bundle is missing {', '.join(missing)}")

    try:
        space = FeatureSpace.from_json(_mapping(_read_json(directory / VOCAB_FILE)))
    except FeatureSpaceError as error:
        raise ModelLoadError(str(error)) from error
    labels = _load_labels(directory / LABEL_MAP_FILE)
    calibration = Calibration.from_json(_mapping(_read_json(directory / CALIBRATION_FILE)))
    if len(calibration.classes) != len(labels):
        raise ModelLoadError(
            f"{CALIBRATION_FILE}: carries {len(calibration.classes)} classes where "
            f"{LABEL_MAP_FILE} carries {len(labels)}"
        )
    for position, item in enumerate(calibration.classes):
        if item.label != labels[position]:
            raise ModelLoadError(
                f"{CALIBRATION_FILE}: class {position} is {item.label} where "
                f"{LABEL_MAP_FILE} says {labels[position]}"
            )

    return ModelBundle(
        directory=directory,
        space=space,
        labels=labels,
        calibration=calibration,
        evidence=_load_evidence(directory / EVIDENCE_FILE),
        shas={
            name: _sha256(directory / name)
            for name in (MODEL_FILE, VOCAB_FILE, CALIBRATION_FILE, LABEL_MAP_FILE)
        },
        opset=_recorded_opset(directory / MANIFEST_FILE),
    )


def _recorded_opset(path: Path) -> str:
    """Return the opset the training manifest recorded, or that it did not."""
    if not path.is_file():
        return "unrecorded"
    document = _read_json(path)
    if isinstance(document, Mapping):
        recorded = document.get("onnx_opset")
        if isinstance(recorded, int | str) and not isinstance(recorded, bool):
            return str(recorded)
    return "unrecorded"


# ---------------------------------------------------------------------------
# The engine.
# ---------------------------------------------------------------------------


class NgramClassifier:
    """The n-gram model behind the ``Classifier`` protocol.

    Construction opens the onnxruntime session, which is the expensive part and
    happens once per process. ``predict`` featurises a whole page in one call and
    runs one batch through the session, because a page of sixty fields as sixty
    single-row calls would measure the call overhead rather than the model.
    """

    name: str = ENGINE_NAME

    def __init__(self, bundle: ModelBundle) -> None:
        self._bundle = bundle
        self._session = _open_session(bundle.directory / MODEL_FILE)
        self._input_name = str(self._session.get_inputs()[0].name)
        self._probability_output = _probability_output(self._session)

    @property
    def bundle(self) -> ModelBundle:
        """The loaded artefacts, for a caller that wants their identity."""
        return self._bundle

    def raw_probabilities(self, fields: Sequence[FieldDescriptor]) -> Probabilities:
        """Return the session's own output, before calibration.

        Exposed because the parity test and the training script both need the
        uncalibrated matrix, and because a calibration comparison that ran the
        session a second way would be comparing two implementations rather than
        one.
        """
        dense = featurize(fields, self._bundle.space).to_dense()
        outputs = self._session.run([self._probability_output], {self._input_name: dense})
        return np.asarray(outputs[0], dtype=np.float64)

    def predict(self, fields: Sequence[FieldDescriptor]) -> list[Prediction]:
        """Return one prediction per descriptor, in the order given."""
        if not fields:
            return []
        started = time.perf_counter()
        classifiable = [item for item in fields if item.undetectable_reason is None]
        calibrated = (
            self._bundle.calibration.apply(self.raw_probabilities(classifiable))
            if classifiable
            else None
        )
        matrix = featurize(classifiable, self._bundle.space) if classifiable else None
        per_field = ((time.perf_counter() - started) * 1e6) / len(fields)

        predictions: list[Prediction] = []
        row = 0
        for descriptor in fields:
            if descriptor.undetectable_reason is not None:
                predictions.append(_undetectable_prediction(descriptor, per_field))
                continue
            if calibrated is None or matrix is None:  # pragma: no cover - unreachable
                raise ModelLoadError("the classifiable batch went missing between two lines")
            predictions.append(
                self._prediction(descriptor, calibrated[row], matrix.row_items(row), per_field)
            )
            row += 1
        return predictions

    def _prediction(
        self,
        descriptor: FieldDescriptor,
        row: Probabilities,
        present: Sequence[tuple[int, float]],
        latency_us: float,
    ) -> Prediction:
        """Assemble one prediction, with its evidence and its runner-up."""
        order = np.argsort(-row)
        best = self._bundle.labels[int(order[0])]
        runner_up: tuple[str, float] | None = None
        if len(order) > 1:
            runner_up = (self._bundle.labels[int(order[1])], float(row[int(order[1])]))

        signals = self._evidence(best, runner_up, present)
        confidence = float(row[int(order[0])])
        if best == Label.UNKNOWN.value:
            # The explicit abstention branch. See the module docstring.
            signals = (_ABSTAIN_SIGNAL, *signals)[:MAX_SIGNALS]
            confidence = 0.0
        return Prediction(
            selector=descriptor.selector,
            label=best,
            confidence=confidence,
            engine=ENGINE_NAME,
            signals=signals,
            runner_up=runner_up,
            latency_us=latency_us,
        )

    def _evidence(
        self,
        best: str,
        runner_up: tuple[str, float] | None,
        present: Sequence[tuple[int, float]],
    ) -> tuple[str, ...]:
        """Name the features that drove this row, winner first.

        A contribution is the feature's value times the class weight, which is
        exactly the term that entered the logit, so this is the model's own
        account of itself rather than an explanation reconstructed beside it.
        That decomposition is the third argument of spec section 5.3 for putting
        a linear model first, and it is the thing law 1 needs.
        """
        values = dict(present)
        signals = [
            signal_name(name)
            for name, _ in self._contributions(best, values)[: MAX_SIGNALS - _RUNNER_UP_SIGNALS]
        ]
        if runner_up is not None:
            for name, _ in self._contributions(runner_up[0], values)[:_RUNNER_UP_SIGNALS]:
                candidate = signal_name(name)
                if candidate not in signals:
                    signals.append(candidate)
        return tuple(signals[:MAX_SIGNALS])

    def _contributions(self, label: str, values: Mapping[int, float]) -> list[tuple[str, float]]:
        """Return the present features of one class, strongest contribution first."""
        index = self._bundle.space.index
        scored: list[tuple[str, float]] = []
        for name, weight in self._bundle.evidence.get(label, ()):
            column = index.get(name)
            if column is None:
                continue
            value = values.get(column)
            if value is None:
                continue
            contribution = value * weight
            if contribution > 0.0:
                scored.append((name, contribution))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored

    def describe(self) -> dict[str, str]:
        """Return the engine identity the run log and the report copy verbatim.

        ``confidence_kind`` is the load-bearing key, and it says
        ``calibrated-probability`` here, which is what makes every renderer print
        a number where the rule engine makes them print a tier. Nothing in any
        renderer changes to make that happen (P3's handoff).

        The four shas are here because law 3 has to be able to answer which exact
        artefact produced a number, and asking the artefact is more reliable than
        remembering.
        """
        identity = {
            "engine": ENGINE_NAME,
            "tool_version": __version__,
            "model_dir": str(self._bundle.directory),
            "providers": ",".join(str(name) for name in self._session.get_providers()),
            "intra_op_threads": "1",
            "calibration_fitted_on": self._bundle.calibration.fitted_on,
            CONFIDENCE_KIND_KEY: CONFIDENCE_KIND_PROBABILITY,
        }
        identity.update(self._bundle.identity())
        return identity


def _undetectable_prediction(descriptor: FieldDescriptor, latency_us: float) -> Prediction:
    """The answer for a descriptor that names a blind spot rather than a control.

    Short-circuited before featurisation for the reason the rule engine
    short-circuits it: a synthetic descriptor has no text, no identifiers, and no
    normalised tokens, so featurising it would produce a row of structural
    features only and a confident-looking answer with no evidence behind it.
    """
    return Prediction(
        selector=descriptor.selector,
        label=Label.UNKNOWN.value,
        confidence=0.0,
        engine=ENGINE_NAME,
        signals=(f"undetectable:{descriptor.undetectable_reason}",),
        latency_us=latency_us,
    )


def _open_session(path: Path) -> Any:
    """Open the CPU session with threads pinned (spec section 10.5).

    onnxruntime is imported here rather than at module import because it takes a
    noticeable fraction of a second to import, and the rule engine, which is what
    most runs use, has no business paying for it.
    """
    try:
        import onnxruntime  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover - onnxruntime is a hard dependency
        raise ModelLoadError(f"onnxruntime is not importable ({error})") from error

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    try:
        return onnxruntime.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        )
    except Exception as error:
        raise ModelLoadError(f"{path.name}: onnxruntime refused it ({error})") from error


def _probability_output(session: Any) -> str:
    """Return the name of the session output carrying the probabilities."""
    for output in session.get_outputs():
        if len(output.shape) == 2:
            return str(output.name)
    raise ModelLoadError(f"{MODEL_FILE}: no output carries a probability matrix")


def load_ngram_engine(directory: Path | None = None) -> NgramClassifier:
    """Load the engine, or explain in one sentence why it cannot run.

    Raises:
        ModelLoadError: no bundle was found, or the one found is unusable.
    """
    resolved = directory if directory is not None else find_model_dir()
    if resolved is None:
        raise ModelLoadError(
            "no trained model was found. Train one with autofill-audit train, or point "
            f"{MODEL_DIR_ENV} at a directory holding {MODEL_FILE}"
        )
    return NgramClassifier(load_bundle(resolved))
