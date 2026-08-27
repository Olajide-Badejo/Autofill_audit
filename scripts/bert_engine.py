#!/usr/bin/env python3
"""The transformer engine of spec section 10.7: serialisation, session, engine.

This module is the inference half of P8. It holds three things and nothing else:
the one function that turns a ``FieldDescriptor`` into the string the encoder
reads, the onnxruntime session that runs the quantized graph on the CPU, and the
engine that puts the two behind the ``Classifier`` protocol.

Why it lives in ``scripts/`` rather than in ``src/``
----------------------------------------------------

Because P8 is conditional and the condition is not decided here. Spec section
10.7 says the transformer ships only if it wins a pre-stated metric by a
pre-stated margin inside a pre-stated latency budget, and
``experiments/predictions/p8-transformer.md`` fixes all three before any of this
runs. Until that condition is evaluated, the transformer is a research artefact
of the same kind as the training script beside it: something the repository
measures, not something the installed tool offers. Putting it in ``src/`` first
would add a tokenizer to the runtime dependency list, put a second model format
in the wheel, and make ``--engine bert`` appear in the help text of a tool that
has not decided whether it has that engine.

If the ship condition is met, this module moves into
``src/autofill_audit/classify/`` with its tests, and the move is the wiring the
ship branch is for. If it is not met, it stays here, where it is exactly what it
is: the code that produced a committed measurement.

What the encoder is shown, and what it is not
---------------------------------------------

The same field view the language model gets at P6, for the reason P6 gave: two
text models compared against each other on different views of the same field are
not being compared. ``field_text`` renders the signals of
``llm/prompts.py::prune`` as a compact string: the intrinsics, the identifier
attributes, every text signal, the option list truncated with its true count
alongside, and the structural position. It renders them itself rather than
importing the pruner, because the string layout is a modelling decision of this
engine's own and because a module that ships into ``src/`` may not import the
research layer (ground rule 11).

**The declared ``autocomplete`` value is never rendered.** It is the answer key
written on the page, and a clean-tier score computed with it in the input would
be a measurement of copying. ``assert_no_declaration_leaks`` checks that by
independence rather than by substring search: the string built from a descriptor
and the string built from the same descriptor with its declaration stripped must
be identical.

Evidence, and the honest limit of it
------------------------------------

Law 1 requires every finding to carry a named evidence list. A linear model can
name the features that entered the logit, and ``classify/onnx_model.py`` does. A
transformer cannot, and this module does not pretend otherwise. What it records
is which input segments were present on the field, which is a true statement
about what the model was shown, together with an explicit
``bert:attribution:unavailable`` marker so that no reader mistakes a list of
segment names for a decomposition of the decision. That is a real cost of the
architecture and it is stated here, in the model card, and in the decision
record, in the same terms spec section 10.2 uses about the hashing fallback.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np

from autofill_audit import __version__
from autofill_audit.classify.base import (
    CONFIDENCE_KIND_KEY,
    CONFIDENCE_KIND_PROBABILITY,
)
from autofill_audit.classify.onnx_model import (
    CALIBRATION_FILE,
    LABEL_MAP_FILE,
    Calibration,
    ModelLoadError,
)
from autofill_audit.descriptors import DeclaredAutocomplete, FieldDescriptor, GroupRole, Prediction
from autofill_audit.taxonomy import Label

__all__ = [
    "BERT_MODEL_DIR_ENV",
    "CONFIG_FILE",
    "ENGINE_NAME",
    "MODEL_FP32_FILE",
    "MODEL_INT8_FILE",
    "TOKENIZER_FILE",
    "BertBundle",
    "BertClassifier",
    "assert_no_declaration_leaks",
    "field_text",
    "field_texts",
    "load_bert_engine",
    "load_bundle",
    "softmax",
]

ENGINE_NAME: Final[str] = "bert"
"""What lands in ``Prediction.engine`` and what names the threshold block."""

MODEL_FP32_FILE: Final[str] = "model.onnx"
MODEL_INT8_FILE: Final[str] = "model.int8.onnx"
TOKENIZER_FILE: Final[str] = "tokenizer.json"
CONFIG_FILE: Final[str] = "bert_config.json"
MANIFEST_FILE: Final[str] = "train_manifest.json"

BERT_MODEL_DIR_ENV: Final[str] = "AUTOFILL_AUDIT_BERT_DIR"
"""Where the bundle is, when it is not passed on the command line."""

CONFIG_SCHEMA_VERSION: Final[int] = 1

TEXT_MAX_CHARS: Final[int] = 120
"""Every free-text signal is cut here. Spec section 15 requires a 10 000
character label to produce a diagnostic rather than a wrong answer, and here it
must additionally not push the one signal that matters off the end of a
sequence that is capped at a few dozen tokens anyway."""

OPTION_LABEL_LIMIT: Final[int] = 8
OPTION_LABEL_MAX_CHARS: Final[int] = 24
"""A ``<select>`` with five thousand options contributes eight of them and its
true count. The count survives the truncation as a fact even though the options
do not, which is the same trade ``llm/prompts.py`` makes and for the same
reason."""

SEGMENT_SEPARATOR: Final[str] = " | "

_ATTRIBUTION_SIGNAL: Final[str] = "bert:attribution:unavailable"
"""On every prediction this engine makes. See the module docstring."""

_ABSTAIN_SIGNAL: Final[str] = "bert:abstain:unknown-class"

MAX_SIGNALS: Final[int] = 8
"""How many entries a prediction carries, bounded as the n-gram engine's are."""


# ---------------------------------------------------------------------------
# Serialisation. One implementation, imported by training and by inference.
# ---------------------------------------------------------------------------


def _clip(value: str | None, limit: int = TEXT_MAX_CHARS) -> str | None:
    """Return ``value`` stripped and cut to ``limit``, or None when it is empty."""
    if value is None:
        return None
    stripped = " ".join(value.split())
    if not stripped:
        return None
    return stripped[:limit]


def _flags(descriptor: FieldDescriptor) -> list[str]:
    """The boolean intrinsics that are true, named. Absent means false."""
    named: list[tuple[str, bool]] = [
        ("required", descriptor.required),
        ("readonly", descriptor.readonly),
        ("disabled", descriptor.disabled),
        ("hidden", not descriptor.is_visible),
        ("in-shadow-root", bool(descriptor.shadow_path)),
        ("in-frame", bool(descriptor.frame_path)),
        ("in-form", descriptor.form_index is not None),
        ("in-fieldset", descriptor.fieldset_index is not None),
    ]
    return [name for name, present in named if present]


def _option_segment(descriptor: FieldDescriptor) -> str | None:
    """The option list, truncated, with the count the truncation hides."""
    labels = descriptor.option_labels
    values = descriptor.option_values
    if not labels and not values:
        return None
    shown = [
        clipped
        for raw in (labels or values)[:OPTION_LABEL_LIMIT]
        if (clipped := _clip(raw, OPTION_LABEL_MAX_CHARS)) is not None
    ]
    count = max(len(labels), len(values))
    body = ", ".join(shown)
    return f"options {count}: {body}" if body else f"options {count}"


def field_text(descriptor: FieldDescriptor) -> str:
    """Return the string the encoder reads for one control.

    Deterministic, computed from this descriptor alone, and never reading the
    declared ``autocomplete`` value. The segment order is fixed so that two runs
    over the same page produce the same bytes and so that a diff of two rendered
    fields is readable.
    """
    segments: list[str] = []

    head = [f"tag {descriptor.tag}"]
    if descriptor.input_type:
        head.append(f"type {descriptor.input_type}")
    if descriptor.inputmode:
        head.append(f"inputmode {descriptor.inputmode}")
    segments.append(" ".join(head))

    flags = _flags(descriptor)
    if flags:
        segments.append(" ".join(flags))
    if descriptor.maxlength is not None:
        segments.append(f"maxlength {descriptor.maxlength}")
    pattern = _clip(descriptor.pattern)
    if pattern is not None:
        segments.append(f"pattern {pattern}")

    for key, value in (
        ("name", _clip(descriptor.name)),
        ("id", _clip(descriptor.element_id)),
    ):
        if value is not None:
            segments.append(f"{key} {value}")
    classes = [
        clipped
        for raw in descriptor.css_classes
        if (clipped := _clip(raw, OPTION_LABEL_MAX_CHARS)) is not None
    ]
    if classes:
        segments.append("class " + " ".join(classes))
    data_keys = [
        clipped
        for raw in descriptor.data_keys
        if (clipped := _clip(raw, OPTION_LABEL_MAX_CHARS)) is not None
    ]
    if data_keys:
        segments.append("data " + " ".join(data_keys))

    text = descriptor.text
    for key, value in (
        ("label", _clip(text.label_for or text.label_ancestor)),
        ("aria-label", _clip(text.aria_label)),
        ("aria-labelledby", _clip(text.aria_labelledby_text)),
        ("aria-describedby", _clip(text.aria_describedby_text)),
        ("title", _clip(text.title)),
        ("placeholder", _clip(text.placeholder)),
        ("preceding", _clip(text.preceding_text)),
        ("legend", _clip(text.legend)),
        ("heading", _clip(text.section_heading)),
        ("form", _clip(text.form_accessible_name)),
    ):
        if value is not None:
            segments.append(f"{key} {value}")

    options = _option_segment(descriptor)
    if options is not None:
        segments.append(options)

    if descriptor.group_role is not GroupRole.NONE:
        segments.append(f"group {descriptor.group_role.value}")
    segments.append(
        f"position {descriptor.document_index} siblings {descriptor.sibling_control_count}"
    )
    if descriptor.undetectable_reason:
        segments.append(f"undetectable {descriptor.undetectable_reason}")

    return SEGMENT_SEPARATOR.join(segments)


def field_texts(fields: Sequence[FieldDescriptor]) -> list[str]:
    """Serialise a whole page, in the order the descriptors were given."""
    return [field_text(descriptor) for descriptor in fields]


PRESENCE_SIGNALS: Final[tuple[tuple[str, str], ...]] = (
    ("bert:input:label", "label "),
    ("bert:input:aria", "aria-"),
    ("bert:input:placeholder", "placeholder "),
    ("bert:input:identifier", "name "),
    ("bert:input:identifier", "id "),
    ("bert:input:class", "class "),
    ("bert:input:context", "preceding "),
    ("bert:input:context", "legend "),
    ("bert:input:context", "heading "),
    ("bert:input:options", "options "),
    ("bert:input:intrinsic", "type "),
)
"""Which rendered segments count as which named input. Not a decomposition of
the decision, which this architecture cannot produce. See the module docstring."""


def presence_signals(rendered: str) -> tuple[str, ...]:
    """Name the input segments this field actually carried, in a fixed order."""
    found: list[str] = []
    for name, marker in PRESENCE_SIGNALS:
        if name in found:
            continue
        for segment in rendered.split(SEGMENT_SEPARATOR):
            if segment.startswith(marker):
                found.append(name)
                break
    return tuple(found)


def assert_no_declaration_leaks(fields: Sequence[FieldDescriptor]) -> None:
    """Raise unless the declared ``autocomplete`` value changed no rendered field.

    Independence rather than a substring search, for the reason
    ``llm/prompts.py`` gives about the same check: a field named ``email`` that
    also declares ``autocomplete="email"`` would trip a substring search, and a
    declaration reaching the string through some derived value would not.

    Raises:
        ValueError: a declaration changed what the encoder would be shown.
    """
    import dataclasses

    for descriptor in fields:
        if not descriptor.declared.raw and not descriptor.declared.token:
            continue
        stripped = dataclasses.replace(descriptor, declared=DeclaredAutocomplete())
        if field_text(descriptor) != field_text(stripped):
            raise ValueError(
                f"{descriptor.selector}: the declared autocomplete value "
                f"{descriptor.declared.raw!r} changed the string the encoder reads. It is "
                "the answer written on the page, and leaving it in would make every "
                "clean-tier number a measurement of copying."
            )


def softmax(logits: Any) -> Any:
    """Row-wise softmax in float64, which is what the calibrators expect."""
    values = np.asarray(logits, dtype=np.float64)
    shifted = values - values.max(axis=1, keepdims=True)
    exponentiated = np.exp(shifted)
    return np.asarray(exponentiated / exponentiated.sum(axis=1, keepdims=True), dtype=np.float64)


# ---------------------------------------------------------------------------
# The bundle on disk.
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    """A file's sha256, which is what ``describe()`` reports as identity."""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    """Read one JSON document, naming the file when it cannot be read."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ModelLoadError(f"{path.name}: cannot be read ({error})") from error
    except json.JSONDecodeError as error:
        raise ModelLoadError(f"{path.name}: not valid JSON ({error})") from error


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    """Return ``value`` as a mapping, or raise."""
    if not isinstance(value, Mapping):
        raise ModelLoadError(f"{name}: expected an object, found {type(value).__name__}")
    return value


@dataclass(frozen=True, slots=True)
class BertBundle:
    """Everything one fine-tuned encoder consists of, loaded and cross-checked."""

    directory: Path
    model_path: Path
    tokenizer_path: Path
    labels: tuple[str, ...]
    calibration: Calibration
    max_length: int
    base_model: str
    quantization: str
    shas: Mapping[str, str]

    def identity(self) -> dict[str, str]:
        """The identity keys ``describe()`` copies into the run manifest."""
        return {
            "model_file": self.model_path.name,
            "model_sha256": self.shas[self.model_path.name],
            "tokenizer_sha256": self.shas[TOKENIZER_FILE],
            "calibration_sha256": self.shas[CALIBRATION_FILE],
            "label_map_sha256": self.shas[LABEL_MAP_FILE],
            "base_model": self.base_model,
            "quantization": self.quantization,
            "max_length": str(self.max_length),
            "class_count": str(len(self.labels)),
        }


def _load_labels(path: Path) -> tuple[str, ...]:
    """Read ``label_map.json`` in the class order the model emits."""
    payload = _mapping(_read_json(path), LABEL_MAP_FILE)
    raw = payload.get("labels")
    if not isinstance(raw, list) or not raw:
        raise ModelLoadError(f"{LABEL_MAP_FILE}: labels must be a non-empty list")
    known = {item.value for item in Label}
    labels: list[str] = []
    for item in raw:
        if not isinstance(item, str) or item not in known:
            raise ModelLoadError(f"{LABEL_MAP_FILE}: {item!r} is not a taxonomy label")
        labels.append(item)
    return tuple(labels)


def load_bundle(directory: Path, *, quantized: bool = True) -> BertBundle:
    """Load and cross-check one bundle directory.

    Args:
        directory: where the training script wrote the bundle.
        quantized: load the INT8 graph, which is what the ship condition is
            defined on. False loads the FP32 graph, which is what the parity
            check compares against.

    Raises:
        ModelLoadError: anything that would make the bundle unsafe to run.
    """
    model_name = MODEL_INT8_FILE if quantized else MODEL_FP32_FILE
    required = (model_name, TOKENIZER_FILE, LABEL_MAP_FILE, CALIBRATION_FILE, CONFIG_FILE)
    missing = [name for name in required if not (directory / name).is_file()]
    if missing:
        raise ModelLoadError(f"{directory}: the bundle is missing {', '.join(missing)}")

    config = _mapping(_read_json(directory / CONFIG_FILE), CONFIG_FILE)
    version = config.get("schema_version")
    if version != CONFIG_SCHEMA_VERSION:
        raise ModelLoadError(
            f"{CONFIG_FILE}: this build reads schema version {CONFIG_SCHEMA_VERSION}, "
            f"found {version!r}"
        )
    max_length = config.get("max_length")
    if isinstance(max_length, bool) or not isinstance(max_length, int) or max_length < 1:
        raise ModelLoadError(f"{CONFIG_FILE}: max_length must be a positive integer")

    labels = _load_labels(directory / LABEL_MAP_FILE)
    calibration = Calibration.from_json(
        _mapping(_read_json(directory / CALIBRATION_FILE), CALIBRATION_FILE)
    )
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

    return BertBundle(
        directory=directory,
        model_path=directory / model_name,
        tokenizer_path=directory / TOKENIZER_FILE,
        labels=labels,
        calibration=calibration,
        max_length=max_length,
        base_model=str(config.get("base_model", "unrecorded")),
        quantization=str(config.get("quantization", "unrecorded")) if quantized else "none-fp32",
        shas={name: _sha256(directory / name) for name in required},
    )


def open_tokenizer(path: Path, max_length: int) -> Any:
    """Open the runtime tokenizer with truncation and padding set in code.

    Set here rather than read off the file, because the two are the whole of the
    train and serve contract for tokenisation and a contract that lives in a
    serialised default is a contract nobody can read. ``scripts/train_bert.py``
    asserts that this path and the training-time tokenizer produce identical ids
    over the entire dev split.
    """
    try:
        from tokenizers import Tokenizer
    except ImportError as error:
        raise ModelLoadError(
            "the bert engine needs the tokenizers wheel, which is in the optional "
            "bert-train extra and is never installed by CI"
        ) from error

    tokenizer = Tokenizer.from_file(str(path))
    tokenizer.enable_truncation(max_length=max_length)
    tokenizer.enable_padding(pad_id=_pad_id(tokenizer), pad_token="[PAD]")
    return tokenizer


def _pad_id(tokenizer: Any) -> int:
    """The padding token's id, or the failure that says the file is wrong."""
    resolved = tokenizer.token_to_id("[PAD]")
    if resolved is None:
        raise ModelLoadError(f"{TOKENIZER_FILE}: carries no [PAD] token")
    return int(resolved)


def _open_session(path: Path) -> Any:
    """Open the CPU session with threads pinned, exactly as P4's session is.

    Spec section 10.5: a per-field classification is far too small to benefit
    from threading, and a benchmark whose threads moved between engines would be
    measuring the thread pool.
    """
    try:
        import onnxruntime
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


# ---------------------------------------------------------------------------
# The engine.
# ---------------------------------------------------------------------------


class BertClassifier:
    """The fine-tuned encoder behind the ``Classifier`` protocol.

    Construction opens the session and the tokenizer, which is the expensive
    part and happens once per process. ``predict`` encodes a whole page in one
    call and runs one batch through the session, for the reason P4 gives: a page
    of sixty fields as sixty single-row calls would measure the call overhead
    rather than the model.
    """

    name: str = ENGINE_NAME

    def __init__(self, bundle: BertBundle) -> None:
        self._bundle = bundle
        self._session = _open_session(bundle.model_path)
        self._tokenizer = open_tokenizer(bundle.tokenizer_path, bundle.max_length)
        self._inputs = [str(item.name) for item in self._session.get_inputs()]
        self._output = str(self._session.get_outputs()[0].name)

    @property
    def bundle(self) -> BertBundle:
        """The loaded artefacts, for a caller that wants their identity."""
        return self._bundle

    def encode(self, texts: Sequence[str]) -> dict[str, Any]:
        """Tokenise a batch to the session's input arrays."""
        encoded = self._tokenizer.encode_batch(list(texts))
        ids = np.asarray([item.ids for item in encoded], dtype=np.int64)
        mask = np.asarray([item.attention_mask for item in encoded], dtype=np.int64)
        return {"input_ids": ids, "attention_mask": mask}

    def logits(self, fields: Sequence[FieldDescriptor]) -> Any:
        """Return the session's own output for a batch of descriptors.

        Exposed because the parity check and the training script both need the
        raw matrix, and because a comparison that ran the session a second way
        would be comparing two implementations rather than one.
        """
        return self.logits_for_texts(field_texts(fields))

    def logits_for_texts(self, texts: Sequence[str]) -> Any:
        """Return the session's own output for already rendered strings."""
        batch = self.encode(texts)
        feed = {name: batch[name] for name in self._inputs if name in batch}
        outputs = self._session.run([self._output], feed)
        return np.asarray(outputs[0], dtype=np.float64)

    def predict(self, fields: Sequence[FieldDescriptor]) -> list[Prediction]:
        """Return one prediction per descriptor, in the order given."""
        if not fields:
            return []
        started = time.perf_counter()
        classifiable = [item for item in fields if item.undetectable_reason is None]
        rendered = field_texts(classifiable)
        calibrated = (
            self._bundle.calibration.apply(softmax(self.logits_for_texts(rendered)))
            if classifiable
            else None
        )
        per_field = ((time.perf_counter() - started) * 1e6) / len(fields)

        predictions: list[Prediction] = []
        row = 0
        for descriptor in fields:
            if descriptor.undetectable_reason is not None:
                predictions.append(_undetectable_prediction(descriptor, per_field))
                continue
            if calibrated is None:  # pragma: no cover - unreachable
                raise ModelLoadError("the classifiable batch went missing between two lines")
            predictions.append(
                self._prediction(descriptor, calibrated[row], rendered[row], per_field)
            )
            row += 1
        return predictions

    def _prediction(
        self,
        descriptor: FieldDescriptor,
        row: Any,
        rendered: str,
        latency_us: float,
    ) -> Prediction:
        """Assemble one prediction, with its input segments and its runner-up."""
        order = np.argsort(-row)
        best = self._bundle.labels[int(order[0])]
        runner_up: tuple[str, float] | None = None
        if len(order) > 1:
            runner_up = (self._bundle.labels[int(order[1])], float(row[int(order[1])]))

        signals = (_ATTRIBUTION_SIGNAL, *presence_signals(rendered))[:MAX_SIGNALS]
        confidence = float(row[int(order[0])])
        if best == Label.UNKNOWN.value:
            # The explicit abstention branch, as the n-gram engine has.
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

    def describe(self) -> dict[str, str]:
        """Return the engine identity the run log and the report copy verbatim.

        ``confidence_kind`` is ``calibrated-probability``, the same word the
        n-gram engine reports, and that is deliberate rather than a shortcut.
        P7's handoff expected a fourth word in the run log's total mapping. A
        fourth word would assert that these numbers are on a different scale
        from the n-gram engine's, and they are not: they are one-vs-rest
        calibrated probabilities fitted on the dev split by the identical
        procedure in ``scripts/train.py::fit_calibration``. The point of the key
        is that nothing downstream pools a regex tier with a probability, and
        inventing a distinction that does not exist would work against it.
        """
        identity = {
            "engine": ENGINE_NAME,
            "tool_version": __version__,
            "model_dir": str(self._bundle.directory),
            "providers": ",".join(str(name) for name in self._session.get_providers()),
            "intra_op_threads": "1",
            "calibration_fitted_on": self._bundle.calibration.fitted_on,
            "tokenizer": _tokenizers_version(),
            "evidence_note": (
                "this engine cannot name the features behind a decision. The signals on "
                "each prediction name the input segments the field carried, which is what "
                "the model was shown and not a decomposition of what it did."
            ),
            CONFIDENCE_KIND_KEY: CONFIDENCE_KIND_PROBABILITY,
        }
        identity.update(self._bundle.identity())
        return identity


def _tokenizers_version() -> str:
    """The resolved tokenizers version, or that it is absent."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("tokenizers")
    except PackageNotFoundError:  # pragma: no cover - the engine cannot load without it
        return "absent"


def _undetectable_prediction(descriptor: FieldDescriptor, latency_us: float) -> Prediction:
    """The answer for a descriptor that names a blind spot rather than a control.

    Short-circuited before serialisation for the reason the other two engines
    short-circuit it: a synthetic descriptor has no text and no identifiers, so
    it would produce a confident-looking answer with nothing behind it.
    """
    return Prediction(
        selector=descriptor.selector,
        label=Label.UNKNOWN.value,
        confidence=0.0,
        engine=ENGINE_NAME,
        signals=(f"undetectable:{descriptor.undetectable_reason}",),
        latency_us=latency_us,
    )


def find_bundle_dir(explicit: Path | None = None) -> Path | None:
    """Return the bundle directory, or None when there is not one."""
    if explicit is not None:
        return explicit if (explicit / CONFIG_FILE).is_file() else None
    override = os.environ.get(BERT_MODEL_DIR_ENV)
    if override:
        candidate = Path(override)
        return candidate if (candidate / CONFIG_FILE).is_file() else None
    candidate = Path.cwd() / "models" / "bert"
    return candidate if (candidate / CONFIG_FILE).is_file() else None


def load_bert_engine(directory: Path | None = None, *, quantized: bool = True) -> BertClassifier:
    """Load the engine, or explain in one sentence why it cannot run.

    Raises:
        ModelLoadError: no bundle was found, or the one found is unusable.
    """
    resolved = find_bundle_dir(directory)
    if resolved is None:
        raise ModelLoadError(
            "no fine-tuned encoder bundle was found. Train one with "
            f"scripts/train_bert.py, or point {BERT_MODEL_DIR_ENV} at a directory "
            f"holding {CONFIG_FILE}"
        )
    return BertClassifier(load_bundle(resolved, quantized=quantized))
