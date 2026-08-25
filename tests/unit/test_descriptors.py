"""The descriptor schema of spec section 9.4 and its lossless round trip.

Spec section 15 layer 4 requires the round trip to be a property, not an
example: it is what lets the LLM mode, the offline evaluator, and the golden
tests all work without a browser, so a member that quietly fails to survive
serialisation would be a member that quietly disappears from every offline run.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autofill_audit.descriptors import (
    CanvasRegion,
    DeclaredAutocomplete,
    DescriptorFormatError,
    ExtractionResult,
    ExtractionWarning,
    ExtractionWarningCode,
    FieldDescriptor,
    GroupRole,
    NormalizedSignals,
    Prediction,
    SettleReport,
    TextSignals,
)

_TEXT = st.text(max_size=12)
_OPT_TEXT = st.none() | _TEXT
_TOKENS = st.tuples() | st.lists(_TEXT, max_size=4).map(tuple)


def _text_signals() -> st.SearchStrategy[TextSignals]:
    """Generate a ``TextSignals``, absent and empty members included."""
    return st.builds(
        TextSignals,
        label_for=_OPT_TEXT,
        label_ancestor=_OPT_TEXT,
        aria_label=_OPT_TEXT,
        aria_labelledby_text=_OPT_TEXT,
        aria_describedby_text=_OPT_TEXT,
        title=_OPT_TEXT,
        placeholder=_OPT_TEXT,
        preceding_text=_OPT_TEXT,
        legend=_OPT_TEXT,
        section_heading=_OPT_TEXT,
        form_accessible_name=_OPT_TEXT,
    )


def _descriptors() -> st.SearchStrategy[FieldDescriptor]:
    """Generate a ``FieldDescriptor`` covering every member."""
    return st.builds(
        FieldDescriptor,
        selector=_TEXT,
        frame_path=_TOKENS,
        shadow_path=_TOKENS,
        document_index=st.integers(min_value=0, max_value=999),
        tag=_TEXT,
        input_type=_OPT_TEXT,
        inputmode=_OPT_TEXT,
        pattern=_OPT_TEXT,
        maxlength=st.none() | st.integers(min_value=0, max_value=9999),
        required=st.booleans(),
        readonly=st.booleans(),
        disabled=st.booleans(),
        option_labels=_TOKENS,
        option_values=_TOKENS,
        name=_OPT_TEXT,
        element_id=_OPT_TEXT,
        css_classes=_TOKENS,
        data_keys=_TOKENS,
        framework_attrs=st.lists(st.tuples(_TEXT, _TEXT), max_size=3).map(tuple),
        declared=st.builds(
            DeclaredAutocomplete,
            raw=_OPT_TEXT,
            token=_OPT_TEXT,
            modifiers=_TOKENS,
            section=_OPT_TEXT,
            is_off_spec=st.booleans(),
            is_off=st.booleans(),
        ),
        text=_text_signals(),
        norm=st.builds(
            NormalizedSignals,
            label_tokens=_TOKENS,
            label_source=_OPT_TEXT,
            identifier_tokens=_TOKENS,
            context_tokens=_TOKENS,
            all_tokens=_TOKENS,
            text_blob=_TEXT,
        ),
        form_index=st.none() | st.integers(min_value=0, max_value=99),
        fieldset_index=st.none() | st.integers(min_value=0, max_value=99),
        sibling_control_count=st.integers(min_value=0, max_value=99),
        group_role=st.sampled_from(list(GroupRole)),
        group_id=_OPT_TEXT,
        is_visible=st.booleans(),
        bbox=st.none()
        | st.tuples(*[st.floats(allow_nan=False, allow_infinity=False, width=32)] * 4),
        undetectable_reason=_OPT_TEXT,
    )


@given(_descriptors())
@settings(max_examples=200)
def test_descriptor_round_trip_is_lossless(descriptor: FieldDescriptor) -> None:
    """Spec section 15 layer 4, and the whole reason offline evaluation works."""
    assert FieldDescriptor.from_json(descriptor.to_json()) == descriptor


@given(_descriptors())
@settings(max_examples=100)
def test_descriptor_round_trips_through_real_json(descriptor: FieldDescriptor) -> None:
    """Through ``json.dumps`` too, because that is the path a run log takes."""
    encoded = json.dumps(descriptor.to_json(), ensure_ascii=False)
    assert FieldDescriptor.from_json(json.loads(encoded)) == descriptor


class TestFrozenAndSlotted:
    """Spec section 9.4 requires both, and says why."""

    @pytest.mark.parametrize(
        "cls",
        [
            TextSignals,
            NormalizedSignals,
            DeclaredAutocomplete,
            FieldDescriptor,
            Prediction,
            SettleReport,
            CanvasRegion,
            ExtractionWarning,
            ExtractionResult,
        ],
    )
    def test_every_dataclass_is_frozen_and_slotted(self, cls: type) -> None:
        """Frozen so three classifiers in a row cannot mutate one; slotted so a
        page with several hundred controls does not allocate several hundred
        dictionaries."""
        assert dataclasses.is_dataclass(cls)
        assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]
        assert hasattr(cls, "__slots__")

    def test_mutation_raises(self) -> None:
        """Stated once, as behaviour rather than as a decorator argument."""
        descriptor = FieldDescriptor(selector="#a")
        with pytest.raises(dataclasses.FrozenInstanceError):
            descriptor.selector = "#b"  # type: ignore[misc]

    def test_with_group_returns_a_copy(self) -> None:
        """The one pass that writes back onto a finished descriptor."""
        descriptor = FieldDescriptor(selector="#a")
        grouped = descriptor.with_group(GroupRole.CC_EXP_MONTH, "expiry-1")
        assert descriptor.group_role is GroupRole.NONE
        assert grouped.group_role is GroupRole.CC_EXP_MONTH
        assert grouped.group_id == "expiry-1"
        assert grouped.selector == "#a"


class TestDefaults:
    """The defaults spec section 9.4 fixes."""

    def test_missing_text_signals_are_none_not_empty(self) -> None:
        """Spec section 9.2's rule, stated as a test on the type itself."""
        signals = TextSignals()
        for member in dataclasses.fields(signals):
            assert getattr(signals, member.name) is None

    def test_a_bare_descriptor_needs_only_a_selector(self) -> None:
        """Everything else has a default, so a synthetic descriptor is cheap."""
        descriptor = FieldDescriptor(selector="#only")
        assert descriptor.tag == "input"
        assert descriptor.group_role is GroupRole.NONE
        assert descriptor.is_visible is True
        assert descriptor.undetectable_reason is None


class TestValidation:
    """``from_json`` refuses what it cannot rebuild, by name."""

    def test_a_missing_selector_is_refused(self) -> None:
        """A descriptor with no selector cannot be reported or fixed."""
        with pytest.raises(DescriptorFormatError, match="selector is required"):
            FieldDescriptor.from_json({})

    def test_a_non_object_payload_is_refused(self) -> None:
        """A list where an object belongs is a corrupt file, not a descriptor."""
        with pytest.raises(DescriptorFormatError, match="expected an object"):
            FieldDescriptor.from_json([])  # type: ignore[arg-type]

    def test_a_wrong_typed_member_names_itself(self) -> None:
        """The message says which member, so the file can be fixed."""
        with pytest.raises(DescriptorFormatError, match="maxlength"):
            FieldDescriptor.from_json({"selector": "#a", "maxlength": "nineteen"})

    def test_a_boolean_is_not_an_integer_here(self) -> None:
        """Python says it is; a maxlength of True is a corrupt file."""
        with pytest.raises(DescriptorFormatError, match="maxlength"):
            FieldDescriptor.from_json({"selector": "#a", "maxlength": True})

    def test_an_unknown_group_role_is_refused(self) -> None:
        """A role nobody defines would silently become NONE otherwise."""
        with pytest.raises(DescriptorFormatError, match="unknown role"):
            FieldDescriptor.from_json({"selector": "#a", "group_role": "cc_exp_century"})

    def test_a_ragged_bounding_box_is_refused(self) -> None:
        """Three numbers is not a box."""
        with pytest.raises(DescriptorFormatError, match="bbox"):
            FieldDescriptor.from_json({"selector": "#a", "bbox": [1, 2, 3]})

    def test_a_string_where_a_list_belongs_is_refused(self) -> None:
        """A string is a sequence, so this needs saying explicitly."""
        with pytest.raises(DescriptorFormatError, match="css_classes"):
            FieldDescriptor.from_json({"selector": "#a", "css_classes": "field"})

    def test_a_ragged_framework_attribute_pair_is_refused(self) -> None:
        """An attribute with no value is not an attribute pair."""
        with pytest.raises(DescriptorFormatError, match="framework_attrs"):
            FieldDescriptor.from_json({"selector": "#a", "framework_attrs": [["only"]]})

    def test_an_unknown_warning_code_is_refused(self) -> None:
        """Warning codes are a closed set the audit engine exhausts."""
        with pytest.raises(DescriptorFormatError, match="unknown warning code"):
            ExtractionWarning.from_json({"code": "went-a-bit-wrong", "detail": ""})

    def test_a_future_schema_version_is_refused(self) -> None:
        """Reading a file this build does not understand is worse than failing."""
        with pytest.raises(DescriptorFormatError, match="schema_version"):
            ExtractionResult.from_json({"schema_version": 99})


class TestPrediction:
    """Shaped at P2, filled by the engines at P3 and P4."""

    def test_round_trip(self) -> None:
        """Including the runner up, which is the member with a shape of its own."""
        prediction = Prediction(
            selector="#a",
            label="postal-code",
            confidence=0.91,
            engine="rules",
            signals=("label says postcode",),
            runner_up=("address-level1", 0.04),
            latency_us=12.5,
        )
        assert Prediction.from_json(prediction.to_json()) == prediction

    def test_round_trip_without_a_runner_up(self) -> None:
        """A rule that fired with no second candidate has none to report."""
        prediction = Prediction(selector="#a", label="email", confidence=0.9, engine="rules")
        assert Prediction.from_json(prediction.to_json()) == prediction

    def test_a_ragged_runner_up_is_refused(self) -> None:
        """A label with no score is not a runner up."""
        with pytest.raises(DescriptorFormatError, match="runner_up"):
            Prediction.from_json({"selector": "#a", "runner_up": ["email"]})


class TestExtractionResult:
    """The page-level surface P3's audit engine and renderers consume."""

    def _result(self) -> ExtractionResult:
        """A result with something in every member."""
        return ExtractionResult(
            fields=(
                FieldDescriptor(selector="#a"),
                FieldDescriptor(
                    selector="frame[#pay]",
                    undetectable_reason="cross-origin-frame",
                ),
            ),
            honeypots=(FieldDescriptor(selector="#trap", is_visible=False),),
            canvas_regions=(CanvasRegion(selector="#c", width=320.0, height=120.0),),
            warnings=(ExtractionWarning(ExtractionWarningCode.INCOMPLETE, "still moving"),),
            settle=SettleReport(reached_quiet=False, waited_ms=3000.0, controls_added_after_load=2),
            controls_seen=3,
            truncated=False,
            frame_count=2,
            url="file:///tmp/page.html",
        )

    def test_round_trip(self) -> None:
        """The whole surface survives a file."""
        result = self._result()
        assert ExtractionResult.from_json(result.to_json()) == result

    def test_undetectable_is_a_view_over_the_fields(self) -> None:
        """P3 reads it without filtering the list itself."""
        result = self._result()
        assert [item.selector for item in result.undetectable] == ["frame[#pay]"]

    def test_warning_lookup(self) -> None:
        """A consumer asks for a code rather than scanning a tuple."""
        result = self._result()
        found = result.warning(ExtractionWarningCode.INCOMPLETE)
        assert found is not None
        assert found.detail == "still moving"
        assert result.warning(ExtractionWarningCode.TRUNCATED) is None

    def test_canvas_area(self) -> None:
        """The comparison the large-canvas rule is stated in."""
        assert CanvasRegion(selector="#c", width=320.0, height=120.0).area == pytest.approx(38400.0)

    def test_an_empty_result_round_trips(self) -> None:
        """A page with no controls is a legitimate result, not a failure."""
        empty = ExtractionResult()
        assert ExtractionResult.from_json(empty.to_json()) == empty


def test_json_payloads_are_plain_types() -> None:
    """Nothing in a serialised descriptor needs a custom encoder.

    Asserted by encoding one with the standard library and no help, because a
    payload that needed help would be one every downstream consumer had to be
    taught about.
    """
    descriptor = FieldDescriptor(
        selector="#a", group_role=GroupRole.RADIO_MEMBER, framework_attrs=(("ng-model", "x"),)
    )
    encoded: Any = json.loads(json.dumps(descriptor.to_json()))
    assert encoded["group_role"] == "radio_member"
    assert encoded["framework_attrs"] == [["ng-model", "x"]]
