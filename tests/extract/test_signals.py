"""Signal collection and derivation, from raw records, with no browser.

Spec section 9.2's two load-bearing rules are asserted here rather than only
through a page: missing is ``None`` and never the empty string, and ``data-*``
contributes keys and never values. Both are the kind of rule that a refactor
breaks silently, because the result still looks like a plausible descriptor.
"""

from __future__ import annotations

import pytest

from autofill_audit.descriptors import TextSignals
from autofill_audit.extract.signals import (
    LABEL_SOURCE_ORDER,
    MAX_OPTIONS,
    RawControl,
    is_honeypot,
    normalized_signals_for,
    raw_control_from_json,
    text_signals_of,
)


class TestAbsentVersusEmpty:
    """Spec section 9.2's first rule, which is a signal in its own right."""

    def test_an_absent_placeholder_is_none(self) -> None:
        """Nobody wrote one."""
        assert text_signals_of(RawControl()).placeholder is None

    def test_an_empty_placeholder_is_the_empty_string(self) -> None:
        """Somebody wrote one and left it blank, which says something else."""
        assert text_signals_of(RawControl(placeholder="")).placeholder == ""

    def test_the_two_are_distinguishable_downstream(self) -> None:
        """Stated as an inequality so a coercion cannot collapse them."""
        assert text_signals_of(RawControl(placeholder="")) != text_signals_of(RawControl())

    def test_an_empty_label_still_wins_its_place_in_the_order(self) -> None:
        """A field labelled with nothing is labelled, and badly.

        Reporting it as unlabelled would hide the difference between a page that
        forgot a label and a page that shipped an empty one.
        """
        signals = normalized_signals_for(RawControl(), TextSignals(label_for="", placeholder="Zip"))
        assert signals.label_source == "label_for"
        assert signals.label_tokens == ()


class TestLabelSourcePreference:
    """Which signal becomes ``label_tokens``, and why the order is that order."""

    def test_the_documented_order(self) -> None:
        """Stated as a test so reordering it is a deliberate change."""
        assert LABEL_SOURCE_ORDER == (
            "label_for",
            "label_ancestor",
            "aria_label",
            "aria_labelledby_text",
            "title",
            "placeholder",
        )

    def test_an_explicit_label_beats_everything(self) -> None:
        """The strongest signal a page can give."""
        signals = normalized_signals_for(
            RawControl(),
            TextSignals(label_for="Postcode", aria_label="ARIA", placeholder="SW1A 1AA"),
        )
        assert signals.label_source == "label_for"
        assert signals.label_tokens == ("postcode",)

    def test_aria_beats_a_placeholder(self) -> None:
        """ARIA is a repair; a placeholder is not a label at all."""
        signals = normalized_signals_for(
            RawControl(), TextSignals(aria_label="Postcode", placeholder="SW1A 1AA")
        )
        assert signals.label_source == "aria_label"

    def test_a_placeholder_is_the_source_of_last_resort(self) -> None:
        """And saying so is what lets P3 raise PLACEHOLDER_AS_LABEL without
        re-deriving anything."""
        signals = normalized_signals_for(RawControl(), TextSignals(placeholder="Postcode"))
        assert signals.label_source == "placeholder"
        assert signals.label_tokens == ("postcode",)

    def test_no_label_at_all(self) -> None:
        """None, not the empty string, so "absent" stays readable."""
        assert normalized_signals_for(RawControl(), TextSignals()).label_source is None

    def test_a_description_is_context_not_a_label(self) -> None:
        """``aria-describedby`` names help text, not the field."""
        signals = normalized_signals_for(
            RawControl(), TextSignals(aria_describedby_text="We never share this")
        )
        assert signals.label_source is None
        assert "share" in signals.context_tokens


class TestIdentifierStream:
    """What goes into ``identifier_tokens``, and what must not."""

    def test_name_and_id_and_classes(self) -> None:
        """Everything the page called the field."""
        signals = normalized_signals_for(
            RawControl(
                name="shippingPostcode", element_id="ship-zip", css_classes=("form-control",)
            ),
            TextSignals(),
        )
        assert signals.identifier_tokens == (
            "shipping",
            "postcode",
            "ship",
            "zip",
            "control",
        )

    def test_data_attribute_keys_only(self) -> None:
        """Spec section 9.2's second rule.

        A generated corpus that embedded truth in a data attribute would leak
        into training. Keys carry real hints on real pages; values are where a
        leak would live, so values never reach a descriptor at all.
        """
        signals = normalized_signals_for(RawControl(data_keys=("postcode",)), TextSignals())
        assert signals.identifier_tokens == ("postcode",)

    def test_framework_attribute_values_do_contribute(self) -> None:
        """And the difference from data attributes is deliberate.

        ``formcontrolname="postalCode"`` is an identifier in exactly the way
        ``name="postalCode"`` is. It is not a data attribute, and no generator
        emits one, so the leak the other rule prevents cannot happen here.
        """
        signals = normalized_signals_for(
            RawControl(framework_attrs=(("formcontrolname", "postalCode"),)), TextSignals()
        )
        assert signals.identifier_tokens == ("postal", "code")

    def test_framework_noise_is_dropped_from_identifiers(self) -> None:
        """Step 5 of spec section 9.7, applied where it belongs."""
        signals = normalized_signals_for(RawControl(name="ctl00$txtZip"), TextSignals())
        assert "ctl00" not in signals.identifier_tokens
        assert "zip" in signals.identifier_tokens

    def test_framework_noise_is_kept_in_labels(self) -> None:
        """A label that literally reads Field is information about the page."""
        signals = normalized_signals_for(RawControl(), TextSignals(label_for="Field"))
        assert signals.label_tokens == ("field",)

    def test_duplicates_are_kept(self) -> None:
        """An id and a name saying the same thing say it twice.

        Removing one would make a strongly identified control indistinguishable
        from a weakly identified one in the feature space.
        """
        signals = normalized_signals_for(
            RawControl(name="postcode", element_id="postcode"), TextSignals()
        )
        assert signals.identifier_tokens == ("postcode", "postcode")


class TestTextBlob:
    """The single string the model is fed (spec section 9.7)."""

    def test_source_prefixes(self) -> None:
        """Without them the strongest and weakest signals are indistinguishable
        in the feature space, which costs nothing to prevent."""
        signals = normalized_signals_for(
            RawControl(name="zip"), TextSignals(label_for="Postcode", legend="Delivery")
        )
        assert signals.text_blob == "L:postcode I:zip C:delivery"

    def test_order_is_label_then_identifier_then_context(self) -> None:
        """Fixed by spec section 9.7, so a featurizer can rely on it."""
        signals = normalized_signals_for(
            RawControl(name="b"), TextSignals(label_for="a", legend="c")
        )
        assert signals.text_blob.split() == ["L:a", "I:b", "C:c"]

    def test_all_tokens_is_the_same_three_streams_unprefixed(self) -> None:
        """One is for a model, the other for a human reading a debug report."""
        signals = normalized_signals_for(
            RawControl(name="b"), TextSignals(label_for="a", legend="c")
        )
        assert signals.all_tokens == ("a", "b", "c")

    def test_an_empty_control_yields_an_empty_blob(self) -> None:
        """The deliberately undeterminable control of the hostile tier."""
        assert normalized_signals_for(RawControl(), TextSignals()).text_blob == ""


class TestHoneypotRule:
    """Spec section 9.6's three shapes, and the one shape it is not."""

    def test_style_hidden(self) -> None:
        """display:none, visibility:hidden, or an opacity of zero."""
        assert is_honeypot(RawControl(style_hidden=True)) is True

    def test_zero_size(self) -> None:
        """A box with no area cannot be typed into."""
        assert is_honeypot(RawControl(zero_size=True)) is True

    def test_offscreen(self) -> None:
        """``position:absolute; left:-9999px``, the classic."""
        assert is_honeypot(RawControl(offscreen=True)) is True

    def test_an_ordinary_control_is_not_one(self) -> None:
        """The default has to be visible or every page is a page of traps."""
        assert is_honeypot(RawControl(bbox=(10.0, 20.0, 200.0, 30.0))) is False

    def test_below_the_fold_is_not_hidden(self) -> None:
        """A long form is not a page full of honeypots.

        The comparison is against the document origin, never against the
        viewport, and a rule that got this wrong would exclude the second half
        of every checkout on the web.
        """
        assert is_honeypot(RawControl(bbox=(10.0, 4000.0, 200.0, 30.0))) is False


class TestRecordDecoding:
    """The typed boundary between what the page said and what was concluded."""

    def test_a_full_record(self) -> None:
        """The shape the traversal script actually returns."""
        raw = raw_control_from_json(
            {
                "tag": "select",
                "inputType": None,
                "maxlength": 19,
                "required": True,
                "multiple": False,
                "name": "card_expmonth",
                "elementId": "card-expmonth",
                "cssClasses": ["field"],
                "dataKeys": ["testid"],
                "frameworkAttrs": [["ng-model", "expMonth"]],
                "optionValues": ["01", "02"],
                "optionCount": 12,
                "chain": [{"tag": "form", "nth": 1, "formName": "pay", "idUnique": False}],
                "bbox": [1, 2, 3, 4],
            }
        )
        assert raw.tag == "select"
        assert raw.maxlength == 19
        assert raw.required is True
        assert raw.data_keys == ("testid",)
        assert raw.framework_attrs == (("ng-model", "expMonth"),)
        assert raw.option_count == 12
        assert raw.chain[0].form_name == "pay"
        assert raw.bbox == (1.0, 2.0, 3.0, 4.0)

    def test_an_empty_record_is_all_defaults(self) -> None:
        """A page is allowed to be strange, and a walk must not abort over it."""
        raw = raw_control_from_json({})
        assert raw.tag == "input"
        assert raw.name is None
        assert raw.chain == ()
        assert raw.bbox is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"maxlength": "nineteen"},
            {"cssClasses": "field"},
            {"frameworkAttrs": [["only"]]},
            {"bbox": [1, 2, 3]},
            {"chain": "form"},
            {"chain": [{"tag": "form"}]},
        ],
    )
    def test_unreadable_members_fall_back_rather_than_raising(
        self, payload: dict[str, object]
    ) -> None:
        """The script and this decoder ship together, so a mismatch is a bug in
        one of them; an extractor that aborted a whole walk over one odd
        attribute would be useless on the pages that most need auditing."""
        raw = raw_control_from_json(payload)
        assert isinstance(raw, RawControl)


def test_the_option_limit_is_wider_than_a_month_list() -> None:
    """The reason the constant is what it is.

    Spec section 9.4 gives the descriptor no field for the total option count,
    so the only way a consumer can tell a complete list of twelve months from
    the first twelve of five thousand branches is for the cut to fall somewhere
    a meaningful list never reaches.
    """
    assert MAX_OPTIONS > 12
