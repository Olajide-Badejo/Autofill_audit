"""The ``autocomplete`` grammar of spec sections 7.1 and 9.4.

This parse is load bearing twice over. The audit engine compares an inferred
label against ``token`` to decide whether a page is right or wrong about its own
field, and it compares ``modifiers`` to decide whether ``shipping postal-code``
against an inferred postal code is a match rather than a mismatch. Spec section
7.1 is explicit about what getting the second one wrong costs: a flood of false
findings on exactly the well-built checkout pages that need them least.
"""

from __future__ import annotations

import pytest

from autofill_audit.extract.signals import WHATWG_FIELD_NAMES, parse_autocomplete
from autofill_audit.taxonomy import SPEC_TOKENS, Label


class TestAbsentAndEmpty:
    """Absent is not empty, and both are different from declaring nothing."""

    def test_absent_attribute(self) -> None:
        """No attribute at all: nothing declared, nothing to report."""
        declared = parse_autocomplete(None)
        assert declared.raw is None
        assert declared.token is None
        assert declared.modifiers == ()
        assert declared.section is None
        assert declared.is_off is False
        assert declared.is_off_spec is False

    def test_empty_attribute_is_off_spec(self) -> None:
        """From the malformed-input list of spec section 15.

        Somebody wrote the attribute and left it blank. No browser can act on
        it, so it is off specification, and the empty raw value keeps it
        distinguishable from an attribute that was never written.
        """
        declared = parse_autocomplete("")
        assert declared.raw == ""
        assert declared.token is None
        assert declared.is_off_spec is True

    def test_whitespace_only_attribute_is_off_spec(self) -> None:
        """Same case with a space in it, which is the same case."""
        assert parse_autocomplete("   ").is_off_spec is True


class TestPlainTokens:
    """One field-name token, which is the overwhelmingly common shape."""

    def test_taxonomy_token(self) -> None:
        """The value is kept verbatim and the token is parsed out of it."""
        declared = parse_autocomplete(Label.POSTAL_CODE.value)
        assert declared.token == Label.POSTAL_CODE.value
        assert declared.is_off_spec is False

    def test_case_is_folded(self) -> None:
        """HTML attribute values are case insensitive here and pages know it."""
        assert parse_autocomplete("GIVEN-NAME").token == Label.GIVEN_NAME.value

    def test_surrounding_whitespace_is_ignored(self) -> None:
        """A value with a stray newline in it still means what it says."""
        assert parse_autocomplete("  email\n").token == Label.EMAIL.value

    @pytest.mark.parametrize("token", sorted(label.value for label in SPEC_TOKENS))
    def test_every_taxonomy_token_parses_as_itself(self, token: str) -> None:
        """All thirty seven, so none can silently become off specification."""
        declared = parse_autocomplete(token)
        assert declared.token == token
        assert declared.is_off_spec is False


class TestModifiersAndSections:
    """The qualifiers that are not labels (spec section 7.1)."""

    def test_address_modifier(self) -> None:
        """The case a wrong parse floods with false findings."""
        declared = parse_autocomplete(f"shipping {Label.POSTAL_CODE.value}")
        assert declared.token == Label.POSTAL_CODE.value
        assert declared.modifiers == ("shipping",)
        assert declared.is_off_spec is False

    def test_contact_modifier(self) -> None:
        """A mobile telephone number is a telephone number."""
        declared = parse_autocomplete(f"mobile {Label.TEL.value}")
        assert declared.token == Label.TEL.value
        assert declared.modifiers == ("mobile",)

    def test_both_modifier_kinds_keep_their_order(self) -> None:
        """The order they were written in, so a report can quote it back."""
        declared = parse_autocomplete(f"billing home {Label.TEL.value}")
        assert declared.modifiers == ("billing", "home")

    def test_section_token(self) -> None:
        """A section-* token names a group of fields, not a field."""
        declared = parse_autocomplete(f"section-blue shipping {Label.STREET_ADDRESS.value}")
        assert declared.section == "section-blue"
        assert declared.modifiers == ("shipping",)
        assert declared.token == Label.STREET_ADDRESS.value
        assert declared.is_off_spec is False

    def test_webauthn_is_a_modifier(self) -> None:
        """A trailing token, and not a field name."""
        declared = parse_autocomplete(f"{Label.ONE_TIME_CODE.value} webauthn")
        assert declared.token == Label.ONE_TIME_CODE.value
        assert declared.modifiers == ("webauthn",)

    def test_modifiers_only_is_off_spec(self) -> None:
        """From the malformed-input list of spec section 15.

        ``shipping`` on its own is not a value any browser can act on. It is
        parsed for what it says, and flagged for what it does not.
        """
        declared = parse_autocomplete("shipping")
        assert declared.modifiers == ("shipping",)
        assert declared.token is None
        assert declared.is_off_spec is True

    def test_out_of_order_tokens_still_parse(self) -> None:
        """Order is deliberately not enforced.

        Real pages get the order wrong and still meant something, and refusing
        to read a value because its tokens are in the wrong sequence turns a
        reportable mistake into an invisible one.
        """
        declared = parse_autocomplete(f"{Label.POSTAL_CODE.value} shipping")
        assert declared.token == Label.POSTAL_CODE.value
        assert declared.modifiers == ("shipping",)
        assert declared.is_off_spec is False


class TestOffAndOn:
    """``off`` and ``on`` are valid values that name no field."""

    def test_off(self) -> None:
        """The one a page writes when it means to suppress autofill."""
        declared = parse_autocomplete("off")
        assert declared.is_off is True
        assert declared.token is None
        assert declared.is_off_spec is False

    def test_off_is_case_folded(self) -> None:
        """Pages shout it as often as not."""
        assert parse_autocomplete("OFF").is_off is True

    def test_on(self) -> None:
        """Valid, names no field, and is not off specification."""
        declared = parse_autocomplete("on")
        assert declared.is_off is False
        assert declared.token is None
        assert declared.is_off_spec is False

    def test_off_beside_a_field_name_is_off_spec(self) -> None:
        """Declaring both is declaring something no browser can act on."""
        declared = parse_autocomplete(f"off {Label.EMAIL.value}")
        assert declared.is_off is True
        assert declared.is_off_spec is True


class TestOffSpecDetection:
    """What ``is_off_spec`` means, stated case by case."""

    def test_invented_token(self) -> None:
        """The case P3's OFF_SPEC_TOKEN finding exists for."""
        declared = parse_autocomplete("zipcode")
        assert declared.token == "zipcode"
        assert declared.is_off_spec is True

    def test_two_field_names_at_once(self) -> None:
        """Two names is no name."""
        declared = parse_autocomplete(f"{Label.GIVEN_NAME.value} {Label.FAMILY_NAME.value}")
        assert declared.is_off_spec is True

    def test_a_whatwg_token_outside_this_taxonomy_is_not_off_spec(self) -> None:
        """The distinction this project has to keep straight.

        Spec section 7.1 leaves several WHATWG tokens out of the *label* set
        because law 2's reachability rule cannot be satisfied for them. That is
        a statement about what the classifier may predict, not about what HTML
        permits. A page declaring one of them has declared something valid, and
        reporting it as off specification would be the tool being wrong about
        the specification it is named after.
        """
        declared = parse_autocomplete("address-level3")
        assert declared.token == "address-level3"
        assert declared.is_off_spec is False
        assert "address-level3" not in {label.value for label in SPEC_TOKENS}

    def test_the_whatwg_set_contains_the_taxonomy(self) -> None:
        """Every label this project can predict is a value HTML accepts."""
        assert {label.value for label in SPEC_TOKENS} <= WHATWG_FIELD_NAMES

    def test_the_whatwg_set_is_larger_than_the_taxonomy(self) -> None:
        """Stated so the two sets cannot quietly collapse into one."""
        assert len(WHATWG_FIELD_NAMES) > len(SPEC_TOKENS)


class TestRawIsKeptVerbatim:
    """A report quotes what the developer wrote, not a tidied version."""

    def test_raw_preserves_case_and_spacing(self) -> None:
        """So the fix text can say "you wrote X" and be telling the truth."""
        declared = parse_autocomplete("  Shipping   POSTAL-CODE ")
        assert declared.raw == "  Shipping   POSTAL-CODE "
        assert declared.token == Label.POSTAL_CODE.value
        assert declared.modifiers == ("shipping",)
