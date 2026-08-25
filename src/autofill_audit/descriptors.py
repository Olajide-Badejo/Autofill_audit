"""``FieldDescriptor``, ``Prediction``, and their serialisation (spec section 9.4).

This module is the only interface between the extractor and everything
downstream. A classifier sees a ``FieldDescriptor`` and nothing else: not the
page, not the answer key (spec section 5.1). That boundary is what makes the
rule baseline, the ONNX model, and the LLM genuinely interchangeable, and it is
what lets the offline evaluator and the golden tests run without a browser.

Every dataclass here is frozen and slotted. Frozen because a descriptor is
handed to three classifiers in turn and any of them mutating it would produce
order-dependent results that are miserable to debug. Slotted because a page with
several hundred controls should not allocate several hundred dictionaries.

**Serialisation is lossless in both directions.** ``to_json`` emits plain JSON
types and ``from_json`` rebuilds the exact object, tuples included; a property
test asserts the round trip over generated descriptors. ``from_json`` validates
as it goes and raises ``DescriptorFormatError`` on anything it cannot rebuild,
because a silently coerced field is a wrong answer that survives to a report.

Two shapes here are not in spec section 9.4 and are called out so a reader does
not go looking for them in the specification:

``ExtractionResult`` and its parts (``SettleReport``, ``CanvasRegion``,
``ExtractionWarning``) are the page-level surface spec section 9.6 requires. The
specification describes the behaviour (a page-level warning when the settle
budget expires, honeypots retained under a separate key, canvas regions named
rather than guessed at) without naming a type to carry it. It lives here rather
than in the extractor package so that a downstream consumer imports one module
for the whole contract.

``ExtractionWarningCode`` is deliberately *not* the audit engine's finding code
enum. The extractor is forbidden from emitting findings (spec section 5.1), so
it reports facts and the audit engine maps them to findings at P3.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Final, Self

__all__ = [
    "SCHEMA_VERSION",
    "CanvasRegion",
    "DeclaredAutocomplete",
    "DescriptorFormatError",
    "ExtractionResult",
    "ExtractionWarning",
    "ExtractionWarningCode",
    "FieldDescriptor",
    "GroupRole",
    "NormalizedSignals",
    "Prediction",
    "SettleReport",
    "TextSignals",
    "UndetectableReason",
]

SCHEMA_VERSION: Final[int] = 1
"""Bumped when a serialised descriptor stops being readable by the previous
reader. Adding an optional field with a default does not bump it; removing a
field or changing what one means does."""


class DescriptorFormatError(ValueError):
    """A serialised descriptor could not be rebuilt.

    Raised by every ``from_json``. It is a ``ValueError`` so that a caller which
    only wants to know that the payload was bad does not have to import this
    module to catch it.
    """


# ---------------------------------------------------------------------------
# Coercion helpers.
#
# ``from_json`` reads JSON, which is to say it reads whatever was in the file.
# Each helper accepts exactly the JSON shape the corresponding field emits and
# refuses everything else by name, so a malformed payload produces a sentence
# rather than an AttributeError several frames later.
# ---------------------------------------------------------------------------


def _require_mapping(value: object, *, where: str) -> Mapping[str, Any]:
    """Return ``value`` as a mapping, or raise."""
    if not isinstance(value, Mapping):
        raise DescriptorFormatError(f"{where}: expected an object, found {type(value).__name__}")
    return value


def _opt_str(payload: Mapping[str, Any], key: str) -> str | None:
    """Read an optional string. Absent and null both mean None."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DescriptorFormatError(f"{key}: expected a string or null, found {value!r}")
    return value


def _req_str(payload: Mapping[str, Any], key: str, default: str) -> str:
    """Read a string that must not be null."""
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise DescriptorFormatError(f"{key}: expected a string, found {value!r}")
    return value


def _opt_int(payload: Mapping[str, Any], key: str) -> int | None:
    """Read an optional integer. ``bool`` is refused; it is not an integer here."""
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise DescriptorFormatError(f"{key}: expected an integer or null, found {value!r}")
    return value


def _req_int(payload: Mapping[str, Any], key: str, default: int) -> int:
    """Read an integer that must not be null."""
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise DescriptorFormatError(f"{key}: expected an integer, found {value!r}")
    return value


def _req_bool(payload: Mapping[str, Any], key: str, default: bool) -> bool:
    """Read a boolean."""
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise DescriptorFormatError(f"{key}: expected a boolean, found {value!r}")
    return value


def _req_float(payload: Mapping[str, Any], key: str, default: float) -> float:
    """Read a number, accepting the integers JSON writes for whole values."""
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DescriptorFormatError(f"{key}: expected a number, found {value!r}")
    return float(value)


def _opt_float(payload: Mapping[str, Any], key: str) -> float | None:
    """Read an optional number."""
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DescriptorFormatError(f"{key}: expected a number or null, found {value!r}")
    return float(value)


def _str_tuple(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """Read a list of strings as a tuple. Absent means empty."""
    value = payload.get(key, ())
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise DescriptorFormatError(f"{key}: expected a list of strings, found {value!r}")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise DescriptorFormatError(f"{key}: expected a list of strings, found {item!r}")
        items.append(item)
    return tuple(items)


def _pair_tuple(payload: Mapping[str, Any], key: str) -> tuple[tuple[str, str], ...]:
    """Read a list of two-string lists as a tuple of pairs."""
    value = payload.get(key, ())
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise DescriptorFormatError(f"{key}: expected a list of pairs, found {value!r}")
    pairs: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, str) or not isinstance(item, Sequence) or len(item) != 2:
            raise DescriptorFormatError(f"{key}: expected a two element list, found {item!r}")
        first, second = item[0], item[1]
        if not isinstance(first, str) or not isinstance(second, str):
            raise DescriptorFormatError(f"{key}: expected a pair of strings, found {item!r}")
        pairs.append((first, second))
    return tuple(pairs)


def _bbox(payload: Mapping[str, Any], key: str) -> tuple[float, float, float, float] | None:
    """Read a bounding box as four numbers, or None."""
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Sequence) or len(value) != 4:
        raise DescriptorFormatError(f"{key}: expected four numbers or null, found {value!r}")
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise DescriptorFormatError(f"{key}: expected four numbers, found {item!r}")
        numbers.append(float(item))
    return (numbers[0], numbers[1], numbers[2], numbers[3])


# ---------------------------------------------------------------------------
# The descriptor parts.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextSignals:
    """Raw text, exactly as found. Normalisation is a separate, derived layer.

    Every member is ``None`` when the signal is absent and a string when it is
    present, **including the empty string** (spec section 9.2). The distinction
    is itself a signal: ``placeholder=""`` means somebody wrote a placeholder
    attribute and left it blank, which says something about the page that a
    missing attribute does not.
    """

    label_for: str | None = None
    label_ancestor: str | None = None
    aria_label: str | None = None
    aria_labelledby_text: str | None = None
    aria_describedby_text: str | None = None
    title: str | None = None
    placeholder: str | None = None
    preceding_text: str | None = None
    legend: str | None = None
    section_heading: str | None = None
    form_accessible_name: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "label_for": self.label_for,
            "label_ancestor": self.label_ancestor,
            "aria_label": self.aria_label,
            "aria_labelledby_text": self.aria_labelledby_text,
            "aria_describedby_text": self.aria_describedby_text,
            "title": self.title,
            "placeholder": self.placeholder,
            "preceding_text": self.preceding_text,
            "legend": self.legend,
            "section_heading": self.section_heading,
            "form_accessible_name": self.form_accessible_name,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the plain JSON form."""
        data = _require_mapping(payload, where="text")
        return cls(
            label_for=_opt_str(data, "label_for"),
            label_ancestor=_opt_str(data, "label_ancestor"),
            aria_label=_opt_str(data, "aria_label"),
            aria_labelledby_text=_opt_str(data, "aria_labelledby_text"),
            aria_describedby_text=_opt_str(data, "aria_describedby_text"),
            title=_opt_str(data, "title"),
            placeholder=_opt_str(data, "placeholder"),
            preceding_text=_opt_str(data, "preceding_text"),
            legend=_opt_str(data, "legend"),
            section_heading=_opt_str(data, "section_heading"),
            form_accessible_name=_opt_str(data, "form_accessible_name"),
        )


@dataclass(frozen=True, slots=True)
class NormalizedSignals:
    """Derived from ``TextSignals`` plus identifiers by ``normalize``. Pure.

    ``label_source`` names the ``TextSignals`` member ``label_tokens`` came
    from, which is how a consumer tells a real ``<label>`` from a placeholder
    pressed into service as one without re-deriving anything.
    """

    label_tokens: tuple[str, ...] = ()
    label_source: str | None = None
    identifier_tokens: tuple[str, ...] = ()
    context_tokens: tuple[str, ...] = ()
    all_tokens: tuple[str, ...] = ()
    text_blob: str = ""

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "label_tokens": list(self.label_tokens),
            "label_source": self.label_source,
            "identifier_tokens": list(self.identifier_tokens),
            "context_tokens": list(self.context_tokens),
            "all_tokens": list(self.all_tokens),
            "text_blob": self.text_blob,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the plain JSON form."""
        data = _require_mapping(payload, where="norm")
        return cls(
            label_tokens=_str_tuple(data, "label_tokens"),
            label_source=_opt_str(data, "label_source"),
            identifier_tokens=_str_tuple(data, "identifier_tokens"),
            context_tokens=_str_tuple(data, "context_tokens"),
            all_tokens=_str_tuple(data, "all_tokens"),
            text_blob=_req_str(data, "text_blob", ""),
        )


@dataclass(frozen=True, slots=True)
class DeclaredAutocomplete:
    """The page's own declaration, parsed (spec sections 7.1 and 9.4).

    ``raw`` is kept verbatim so that a report can quote what the developer
    actually wrote rather than a tidied version of it. Everything else is
    derived, and ``is_off_spec`` is the flag that separates "declared something
    the specification does not define" from "declared nothing".
    """

    raw: str | None = None
    token: str | None = None
    modifiers: tuple[str, ...] = ()
    section: str | None = None
    is_off_spec: bool = False
    is_off: bool = False

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "raw": self.raw,
            "token": self.token,
            "modifiers": list(self.modifiers),
            "section": self.section,
            "is_off_spec": self.is_off_spec,
            "is_off": self.is_off,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the plain JSON form."""
        data = _require_mapping(payload, where="declared")
        return cls(
            raw=_opt_str(data, "raw"),
            token=_opt_str(data, "token"),
            modifiers=_str_tuple(data, "modifiers"),
            section=_opt_str(data, "section"),
            is_off_spec=_req_bool(data, "is_off_spec", False),
            is_off=_req_bool(data, "is_off", False),
        )


class GroupRole(StrEnum):
    """The structural role a control plays in a detected group (spec 9.5).

    A ``StrEnum`` rather than ``str, Enum`` so that the value survives ``json``
    without a custom encoder and compares equal to its own string.
    """

    NONE = "none"
    CC_EXP_MONTH = "cc_exp_month"
    CC_EXP_YEAR = "cc_exp_year"
    RADIO_MEMBER = "radio_member"
    CHECKBOX_MEMBER = "checkbox_member"
    ADDRESS_LINE_MEMBER = "address_line_member"


class UndetectableReason(StrEnum):
    """Why a control could not be read, when the extractor knows one is there.

    Spec section 9.4 lists these as free strings on the descriptor and spec
    section 9.6 fixes their behaviour. They are enumerated here so that the
    audit engine can exhaust them and a typo cannot invent a sixth.

    ``CANVAS_REGION`` is emitted only for the zero-control case of spec section
    9.6. A page that has controls *and* a canvas records the canvas on
    ``ExtractionResult.canvas_regions`` and emits no synthetic descriptor, which
    is what keeps a descriptor count comparable to an answer-key field count.
    """

    CLOSED_SHADOW_ROOT = "closed-shadow-root"
    CROSS_ORIGIN_FRAME = "cross-origin-frame"
    CANVAS_REGION = "canvas-region"
    DETACHED = "detached"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class FieldDescriptor:
    """One form control, with every signal that could inform a classification.

    ``document_index`` counts over the whole emitted sequence for the page,
    honeypots and synthetic undetectable descriptors included, so that excluding
    a honeypot from the audit does not renumber the controls around it.
    """

    # identity
    selector: str
    frame_path: tuple[str, ...] = ()
    shadow_path: tuple[str, ...] = ()
    document_index: int = 0

    # intrinsic
    tag: str = "input"
    input_type: str | None = None
    inputmode: str | None = None
    pattern: str | None = None
    maxlength: int | None = None
    required: bool = False
    readonly: bool = False
    disabled: bool = False
    option_labels: tuple[str, ...] = ()
    option_values: tuple[str, ...] = ()

    # identifiers
    name: str | None = None
    element_id: str | None = None
    css_classes: tuple[str, ...] = ()
    data_keys: tuple[str, ...] = ()
    framework_attrs: tuple[tuple[str, str], ...] = ()

    # declared intent
    declared: DeclaredAutocomplete = field(default_factory=DeclaredAutocomplete)

    # text
    text: TextSignals = field(default_factory=TextSignals)
    norm: NormalizedSignals = field(default_factory=NormalizedSignals)

    # structure
    form_index: int | None = None
    fieldset_index: int | None = None
    sibling_control_count: int = 0
    group_role: GroupRole = GroupRole.NONE
    group_id: str | None = None

    # visibility and extraction health
    is_visible: bool = True
    bbox: tuple[float, float, float, float] | None = None
    undetectable_reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form. Round-trips losslessly through ``from_json``."""
        return {
            "selector": self.selector,
            "frame_path": list(self.frame_path),
            "shadow_path": list(self.shadow_path),
            "document_index": self.document_index,
            "tag": self.tag,
            "input_type": self.input_type,
            "inputmode": self.inputmode,
            "pattern": self.pattern,
            "maxlength": self.maxlength,
            "required": self.required,
            "readonly": self.readonly,
            "disabled": self.disabled,
            "option_labels": list(self.option_labels),
            "option_values": list(self.option_values),
            "name": self.name,
            "element_id": self.element_id,
            "css_classes": list(self.css_classes),
            "data_keys": list(self.data_keys),
            "framework_attrs": [list(pair) for pair in self.framework_attrs],
            "declared": self.declared.to_json(),
            "text": self.text.to_json(),
            "norm": self.norm.to_json(),
            "form_index": self.form_index,
            "fieldset_index": self.fieldset_index,
            "sibling_control_count": self.sibling_control_count,
            "group_role": self.group_role.value,
            "group_id": self.group_id,
            "is_visible": self.is_visible,
            "bbox": None if self.bbox is None else list(self.bbox),
            "undetectable_reason": self.undetectable_reason,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the plain JSON form."""
        data = _require_mapping(payload, where="descriptor")
        if "selector" not in data:
            raise DescriptorFormatError("descriptor: selector is required")
        role_value = _req_str(data, "group_role", GroupRole.NONE.value)
        try:
            role = GroupRole(role_value)
        except ValueError as error:
            raise DescriptorFormatError(f"group_role: unknown role {role_value!r}") from error
        return cls(
            selector=_req_str(data, "selector", ""),
            frame_path=_str_tuple(data, "frame_path"),
            shadow_path=_str_tuple(data, "shadow_path"),
            document_index=_req_int(data, "document_index", 0),
            tag=_req_str(data, "tag", "input"),
            input_type=_opt_str(data, "input_type"),
            inputmode=_opt_str(data, "inputmode"),
            pattern=_opt_str(data, "pattern"),
            maxlength=_opt_int(data, "maxlength"),
            required=_req_bool(data, "required", False),
            readonly=_req_bool(data, "readonly", False),
            disabled=_req_bool(data, "disabled", False),
            option_labels=_str_tuple(data, "option_labels"),
            option_values=_str_tuple(data, "option_values"),
            name=_opt_str(data, "name"),
            element_id=_opt_str(data, "element_id"),
            css_classes=_str_tuple(data, "css_classes"),
            data_keys=_str_tuple(data, "data_keys"),
            framework_attrs=_pair_tuple(data, "framework_attrs"),
            declared=DeclaredAutocomplete.from_json(data.get("declared", {})),
            text=TextSignals.from_json(data.get("text", {})),
            norm=NormalizedSignals.from_json(data.get("norm", {})),
            form_index=_opt_int(data, "form_index"),
            fieldset_index=_opt_int(data, "fieldset_index"),
            sibling_control_count=_req_int(data, "sibling_control_count", 0),
            group_role=role,
            group_id=_opt_str(data, "group_id"),
            is_visible=_req_bool(data, "is_visible", True),
            bbox=_bbox(data, "bbox"),
            undetectable_reason=_opt_str(data, "undetectable_reason"),
        )

    def with_group(self, role: GroupRole, group_id: str) -> FieldDescriptor:
        """Return a copy carrying a detected group membership.

        Frozen dataclasses are copied rather than mutated, and group detection
        is the one pass that needs to write back onto a finished descriptor.
        """
        return replace(self, group_role=role, group_id=group_id)


@dataclass(frozen=True, slots=True)
class Prediction:
    """One classifier's answer for one control.

    Shaped at P2 because it is part of spec section 9.4's contract; the engines
    that fill it arrive at P3 and P4. ``signals`` carries the human-readable
    evidence law 1 requires, so no consumer has to reconstruct why.
    """

    selector: str
    label: str
    confidence: float
    engine: str
    signals: tuple[str, ...] = ()
    runner_up: tuple[str, float] | None = None
    latency_us: float | None = None

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "selector": self.selector,
            "label": self.label,
            "confidence": self.confidence,
            "engine": self.engine,
            "signals": list(self.signals),
            "runner_up": None if self.runner_up is None else [self.runner_up[0], self.runner_up[1]],
            "latency_us": self.latency_us,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the plain JSON form."""
        data = _require_mapping(payload, where="prediction")
        runner_up_value = data.get("runner_up")
        runner_up: tuple[str, float] | None = None
        if runner_up_value is not None:
            if (
                isinstance(runner_up_value, str)
                or not isinstance(runner_up_value, Sequence)
                or len(runner_up_value) != 2
            ):
                raise DescriptorFormatError(
                    f"runner_up: expected a pair, found {runner_up_value!r}"
                )
            name, score = runner_up_value[0], runner_up_value[1]
            if (
                not isinstance(name, str)
                or isinstance(score, bool)
                or not isinstance(score, int | float)
            ):
                raise DescriptorFormatError(
                    f"runner_up: expected a label and a score, found {runner_up_value!r}"
                )
            runner_up = (name, float(score))
        return cls(
            selector=_req_str(data, "selector", ""),
            label=_req_str(data, "label", ""),
            confidence=_req_float(data, "confidence", 0.0),
            engine=_req_str(data, "engine", ""),
            signals=_str_tuple(data, "signals"),
            runner_up=runner_up,
            latency_us=_opt_float(data, "latency_us"),
        )


# ---------------------------------------------------------------------------
# The page-level extraction surface (spec section 9.6).
# ---------------------------------------------------------------------------


class ExtractionWarningCode(StrEnum):
    """What went wrong at page level, as a fact rather than as a finding.

    The audit engine maps these onto finding codes at P3. Keeping the two enums
    apart is what stops the extractor from quietly acquiring an opinion about
    severity, which spec section 5.1 forbids it from having.
    """

    INCOMPLETE = "incomplete"
    TRUNCATED = "truncated"
    FRAME_UNREADABLE = "frame-unreadable"


@dataclass(frozen=True, slots=True)
class ExtractionWarning:
    """One page-level problem, with enough detail to put in a report."""

    code: ExtractionWarningCode
    detail: str

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {"code": self.code.value, "detail": self.detail}

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the plain JSON form."""
        data = _require_mapping(payload, where="warning")
        raw = _req_str(data, "code", "")
        try:
            code = ExtractionWarningCode(raw)
        except ValueError as error:
            raise DescriptorFormatError(f"code: unknown warning code {raw!r}") from error
        return cls(code=code, detail=_req_str(data, "detail", ""))


@dataclass(frozen=True, slots=True)
class SettleReport:
    """What the bounded wait of spec section 9.6 observed.

    ``controls_added_after_load`` is the field that makes the settle policy
    assertable on its *mechanism* rather than on a duration, which is what the
    flake policy of spec section 15 demands: a run that saw a control appear
    after the load event proves the wait did something, where a run that merely
    took long enough proves nothing.
    """

    reached_quiet: bool = True
    waited_ms: float = 0.0
    mutations_after_load: int = 0
    controls_added_after_load: int = 0
    network_idle: bool = True

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "reached_quiet": self.reached_quiet,
            "waited_ms": self.waited_ms,
            "mutations_after_load": self.mutations_after_load,
            "controls_added_after_load": self.controls_added_after_load,
            "network_idle": self.network_idle,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the plain JSON form."""
        data = _require_mapping(payload, where="settle")
        return cls(
            reached_quiet=_req_bool(data, "reached_quiet", True),
            waited_ms=_req_float(data, "waited_ms", 0.0),
            mutations_after_load=_req_int(data, "mutations_after_load", 0),
            controls_added_after_load=_req_int(data, "controls_added_after_load", 0),
            network_idle=_req_bool(data, "network_idle", True),
        )


@dataclass(frozen=True, slots=True)
class CanvasRegion:
    """A canvas large enough to be hiding a form control (spec section 9.6).

    Recorded unconditionally, whether or not the page also has real controls,
    because naming the blind spot is in scope even though reading it is not
    (spec section 0.4).
    """

    selector: str
    width: float
    height: float
    frame_path: tuple[str, ...] = ()

    @property
    def area(self) -> float:
        """The rendered area in CSS pixels."""
        return self.width * self.height

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "selector": self.selector,
            "width": self.width,
            "height": self.height,
            "frame_path": list(self.frame_path),
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the plain JSON form."""
        data = _require_mapping(payload, where="canvas")
        return cls(
            selector=_req_str(data, "selector", ""),
            width=_req_float(data, "width", 0.0),
            height=_req_float(data, "height", 0.0),
            frame_path=_str_tuple(data, "frame_path"),
        )


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Everything one extraction produced, page level included.

    ``fields`` is what the classifier sees and what ``extract`` returns.
    ``honeypots`` holds the controls excluded from the audit because a user
    cannot see them: spec section 9.6 requires that they be retained rather than
    silently dropped, so that a field count in a report matches the count a
    developer sees in the page they wrote.
    """

    fields: tuple[FieldDescriptor, ...] = ()
    honeypots: tuple[FieldDescriptor, ...] = ()
    canvas_regions: tuple[CanvasRegion, ...] = ()
    warnings: tuple[ExtractionWarning, ...] = ()
    settle: SettleReport = field(default_factory=SettleReport)
    controls_seen: int = 0
    truncated: bool = False
    frame_count: int = 1
    url: str = ""

    @property
    def undetectable(self) -> tuple[FieldDescriptor, ...]:
        """The synthetic descriptors that name a blind spot rather than a control."""
        return tuple(item for item in self.fields if item.undetectable_reason is not None)

    def warning(self, code: ExtractionWarningCode) -> ExtractionWarning | None:
        """Return the warning carrying ``code``, or None."""
        for item in self.warnings:
            if item.code is code:
                return item
        return None

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "schema_version": SCHEMA_VERSION,
            "url": self.url,
            "fields": [item.to_json() for item in self.fields],
            "honeypots": [item.to_json() for item in self.honeypots],
            "canvas_regions": [item.to_json() for item in self.canvas_regions],
            "warnings": [item.to_json() for item in self.warnings],
            "settle": self.settle.to_json(),
            "controls_seen": self.controls_seen,
            "truncated": self.truncated,
            "frame_count": self.frame_count,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild from the plain JSON form."""
        data = _require_mapping(payload, where="result")
        version = _req_int(data, "schema_version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            raise DescriptorFormatError(
                f"schema_version: this build reads version {SCHEMA_VERSION}, found {version}"
            )
        return cls(
            fields=_descriptor_list(data, "fields"),
            honeypots=_descriptor_list(data, "honeypots"),
            canvas_regions=tuple(
                CanvasRegion.from_json(_require_mapping(item, where="canvas"))
                for item in _sequence(data, "canvas_regions")
            ),
            warnings=tuple(
                ExtractionWarning.from_json(_require_mapping(item, where="warning"))
                for item in _sequence(data, "warnings")
            ),
            settle=SettleReport.from_json(data.get("settle", {})),
            controls_seen=_req_int(data, "controls_seen", 0),
            truncated=_req_bool(data, "truncated", False),
            frame_count=_req_int(data, "frame_count", 1),
            url=_req_str(data, "url", ""),
        )


def _sequence(payload: Mapping[str, Any], key: str) -> Sequence[Any]:
    """Read a JSON list, treating an absent key as empty."""
    value = payload.get(key, ())
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise DescriptorFormatError(f"{key}: expected a list, found {value!r}")
    return value


def _descriptor_list(payload: Mapping[str, Any], key: str) -> tuple[FieldDescriptor, ...]:
    """Read a list of serialised descriptors."""
    return tuple(
        FieldDescriptor.from_json(_require_mapping(item, where=key))
        for item in _sequence(payload, key)
    )
