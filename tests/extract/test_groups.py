"""Structural group detection (spec section 9.5), with no browser and a frozen clock.

Two failures matter here and they are not symmetric. A group the extractor
misses becomes two independent confusing predictions; a group it invents becomes
one wrong finding. Both are tested, and the invented-group cases are the ones
with the most tests, because a detector that fires too readily is the one that
looks like it works.

The expiry year window is relative to a year the caller passes in. Spec section
9.5 says so in as many words, and every test here freezes that year rather than
reading the clock, so nothing in this file expires.
"""

from __future__ import annotations

import pytest

from autofill_audit.descriptors import FieldDescriptor, GroupRole, NormalizedSignals
from autofill_audit.extract.groups import (
    YEAR_WINDOW_BACK,
    YEAR_WINDOW_FORWARD,
    detect_groups,
    is_month_options,
    is_year_options,
)
from autofill_audit.extract.signals import RawControl

FROZEN_YEAR = 2026

MONTH_VALUES = tuple(f"{month:02d}" for month in range(1, 13))
GERMAN_MONTHS = (
    "Januar",
    "Februar",
    "Maerz",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)
JAPANESE_MONTHS = tuple(f"{month}月" for month in range(1, 13))
YEAR_VALUES = tuple(str(year) for year in range(FROZEN_YEAR, FROZEN_YEAR + 11))


def _control(
    selector: str,
    *,
    tag: str = "input",
    input_type: str | None = "text",
    name: str | None = None,
    option_values: tuple[str, ...] = (),
    option_labels: tuple[str, ...] = (),
    label_tokens: tuple[str, ...] = (),
    identifier_tokens: tuple[str, ...] = (),
    declared_token: str | None = None,
) -> FieldDescriptor:
    """Build one finished descriptor, without going near a page."""
    from autofill_audit.descriptors import DeclaredAutocomplete

    return FieldDescriptor(
        selector=selector,
        tag=tag,
        input_type=input_type,
        name=name,
        option_values=option_values,
        option_labels=option_labels,
        declared=DeclaredAutocomplete(raw=declared_token, token=declared_token),
        norm=NormalizedSignals(label_tokens=label_tokens, identifier_tokens=identifier_tokens),
    )


def _raw(
    *,
    parent: str = "cell",
    fieldset: str | None = None,
    form: str | None = "form1",
    multiple: bool = False,
) -> RawControl:
    """Build the structural half of one record."""
    return RawControl(parent_key=parent, fieldset_key=fieldset, form_key=form, multiple=multiple)


class TestMonthOptionShape:
    """Twelve options, and how they are recognised across six locales."""

    def test_padded_values(self) -> None:
        """The values every locale in the corpus emits."""
        assert is_month_options(MONTH_VALUES, MONTH_VALUES) is True

    def test_unpadded_values(self) -> None:
        """Spec section 9.5 names both spellings."""
        assert is_month_options(tuple(str(m) for m in range(1, 13)), ()) is True

    def test_german_month_names_are_recognised_by_their_values(self) -> None:
        """A detector keyed on display text alone fails on two locales of six.

        The corpus renders month names in German and in Japanese while keeping
        the values 01 to 12 everywhere, which is exactly why the values are
        checked first.
        """
        assert is_month_options(MONTH_VALUES, GERMAN_MONTHS) is True

    def test_japanese_month_labels_are_recognised_by_their_digits(self) -> None:
        """1月 through 12月, with no month-name table anywhere."""
        assert is_month_options((), JAPANESE_MONTHS) is True

    def test_a_blank_first_option_disqualifies(self) -> None:
        """The corpus makes this discriminating on purpose.

        Country, card type, title, sex, and administrative area selects all
        carry a blank first option; only month and year selects do not.
        """
        assert is_month_options(("", *MONTH_VALUES[:11]), ()) is False

    def test_eleven_options_are_not_twelve_months(self) -> None:
        """Off by one is the failure mode this rule exists to avoid."""
        assert is_month_options(MONTH_VALUES[:11], ()) is False

    def test_out_of_order_values_are_not_months(self) -> None:
        """Twelve numbers is not twelve months."""
        shuffled = ("12", *MONTH_VALUES[:11])
        assert is_month_options(shuffled, ()) is False

    def test_a_multi_select_is_never_a_month(self) -> None:
        """Twelve options a user may pick several of is not a month picker."""
        assert is_month_options(MONTH_VALUES, MONTH_VALUES, multiple=True) is False


class TestYearOptionShape:
    """A run of consecutive years, in a window relative to the clock."""

    def test_four_digit_run(self) -> None:
        """The shape the corpus emits: eleven years from the base year."""
        assert is_year_options(YEAR_VALUES, (), now_year=FROZEN_YEAR) is True

    def test_two_digit_run(self) -> None:
        """Spec section 9.5 names both widths."""
        two_digit = tuple(str(year % 100) for year in range(FROZEN_YEAR, FROZEN_YEAR + 6))
        assert is_year_options(two_digit, (), now_year=FROZEN_YEAR) is True

    def test_a_gap_disqualifies(self) -> None:
        """Consecutive means consecutive."""
        assert is_year_options(("2026", "2028", "2029"), (), now_year=FROZEN_YEAR) is False

    def test_descending_disqualifies(self) -> None:
        """A list counting down is a list of something else."""
        assert is_year_options(("2029", "2028", "2027"), (), now_year=FROZEN_YEAR) is False

    def test_two_is_not_a_run(self) -> None:
        """Any pair of adjacent numbers is a run of two."""
        assert is_year_options(("2026", "2027"), (), now_year=FROZEN_YEAR) is False

    def test_a_run_far_in_the_past_is_not_an_expiry_list(self) -> None:
        """Birth years are a run of consecutive years and are not this."""
        old = tuple(str(year) for year in range(1970, 1980))
        assert is_year_options(old, (), now_year=FROZEN_YEAR) is False

    def test_the_window_moves_with_the_clock(self) -> None:
        """The property spec section 9.5 asks for, asserted directly.

        The same option list is inside the window for one year and outside it
        for another, and nothing in the detector had to be edited in between.
        """
        values = tuple(str(year) for year in range(2060, 2066))
        assert is_year_options(values, (), now_year=2026) is False
        assert is_year_options(values, (), now_year=2058) is True

    def test_the_window_bounds_are_relative(self) -> None:
        """Stated so a literal window cannot creep back in."""
        just_inside = tuple(
            str(year)
            for year in range(FROZEN_YEAR - YEAR_WINDOW_BACK, FROZEN_YEAR - YEAR_WINDOW_BACK + 4)
        )
        just_outside = tuple(
            str(year)
            for year in range(
                FROZEN_YEAR + YEAR_WINDOW_FORWARD + 1, FROZEN_YEAR + YEAR_WINDOW_FORWARD + 5
            )
        )
        assert is_year_options(just_inside, (), now_year=FROZEN_YEAR) is True
        assert is_year_options(just_outside, (), now_year=FROZEN_YEAR) is False

    def test_non_numeric_options_are_not_years(self) -> None:
        """A country list is not an expiry list."""
        assert is_year_options(("GB", "IE", "FR"), (), now_year=FROZEN_YEAR) is False


class TestSplitExpiry:
    """Pairing the two halves, and refusing to pair anything else."""

    def test_two_selects_in_one_fieldset(self) -> None:
        """The grouped shape: a fieldset, a legend, and two cells."""
        descriptors = [
            _control("#m", tag="select", input_type=None, option_values=MONTH_VALUES),
            _control("#y", tag="select", input_type=None, option_values=YEAR_VALUES),
        ]
        raws = [_raw(parent="cell1", fieldset="fs1"), _raw(parent="cell2", fieldset="fs1")]
        grouped = detect_groups(descriptors, raws, now_year=FROZEN_YEAR)
        assert grouped[0].group_role is GroupRole.CC_EXP_MONTH
        assert grouped[1].group_role is GroupRole.CC_EXP_YEAR
        assert grouped[0].group_id == grouped[1].group_id

    def test_two_selects_sharing_one_parent_with_no_fieldset(self) -> None:
        """The ungrouped shape the hostile tier renders: one div, no legend."""
        descriptors = [
            _control("#m", tag="select", input_type=None, option_values=MONTH_VALUES),
            _control("#y", tag="select", input_type=None, option_values=YEAR_VALUES),
        ]
        raws = [_raw(parent="cell1"), _raw(parent="cell1")]
        grouped = detect_groups(descriptors, raws, now_year=FROZEN_YEAR)
        assert grouped[0].group_role is GroupRole.CC_EXP_MONTH
        assert grouped[1].group_role is GroupRole.CC_EXP_YEAR

    def test_a_select_and_a_text_input(self) -> None:
        """Spec section 9.5 names this shape explicitly.

        The year half has no option list, so it is recognised from its tokens.
        ``expyear`` is why the match is on a substring: no stemmer turns that
        into ``year``.
        """
        descriptors = [
            _control("#m", tag="select", input_type=None, option_values=MONTH_VALUES),
            _control("#y", identifier_tokens=("card", "expyear")),
        ]
        raws = [_raw(parent="cell1"), _raw(parent="cell1")]
        grouped = detect_groups(descriptors, raws, now_year=FROZEN_YEAR)
        assert grouped[1].group_role is GroupRole.CC_EXP_YEAR

    def test_year_before_month_is_still_a_pair(self) -> None:
        """Some pages put the year first, and it is the same pair."""
        descriptors = [
            _control("#y", tag="select", input_type=None, option_values=YEAR_VALUES),
            _control("#m", tag="select", input_type=None, option_values=MONTH_VALUES),
        ]
        raws = [_raw(parent="cell1"), _raw(parent="cell1")]
        grouped = detect_groups(descriptors, raws, now_year=FROZEN_YEAR)
        assert grouped[0].group_role is GroupRole.CC_EXP_YEAR
        assert grouped[1].group_role is GroupRole.CC_EXP_MONTH

    def test_two_unlabelled_text_inputs_are_not_paired(self) -> None:
        """The hostile-tier case, and the one where guessing invents a group.

        Two bare text inputs side by side say nothing about being an expiry.
        Spec section 9.5 requires at least one half to be a select, and this is
        the case that requirement exists for.
        """
        descriptors = [_control("#a"), _control("#b")]
        raws = [_raw(parent="cell1"), _raw(parent="cell1")]
        grouped = detect_groups(descriptors, raws, now_year=FROZEN_YEAR)
        assert all(item.group_role is GroupRole.NONE for item in grouped)

    def test_controls_in_different_cells_and_fieldsets_are_not_paired(self) -> None:
        """Adjacent in the list is not adjacent in the document."""
        descriptors = [
            _control("#m", tag="select", input_type=None, option_values=MONTH_VALUES),
            _control("#y", tag="select", input_type=None, option_values=YEAR_VALUES),
        ]
        raws = [_raw(parent="cellA", fieldset="fsA"), _raw(parent="cellB", fieldset="fsB")]
        grouped = detect_groups(descriptors, raws, now_year=FROZEN_YEAR)
        assert all(item.group_role is GroupRole.NONE for item in grouped)

    def test_a_country_select_beside_a_month_select_is_not_a_pair(self) -> None:
        """The invented-group case a careless option check would produce."""
        descriptors = [
            _control("#m", tag="select", input_type=None, option_values=MONTH_VALUES),
            _control("#c", tag="select", input_type=None, option_values=("", "GB", "IE")),
        ]
        raws = [_raw(parent="cell1"), _raw(parent="cell1")]
        grouped = detect_groups(descriptors, raws, now_year=FROZEN_YEAR)
        assert all(item.group_role is GroupRole.NONE for item in grouped)

    def test_a_single_composite_control_is_not_a_group(self) -> None:
        """One MM/YY input has nothing to pair with, and inventing one would be
        a wrong finding rather than a missing one."""
        descriptors = [_control("#e", label_tokens=("expiry",), identifier_tokens=("expiry",))]
        grouped = detect_groups(descriptors, [_raw()], now_year=FROZEN_YEAR)
        assert grouped[0].group_role is GroupRole.NONE

    def test_two_pairs_on_one_page_get_different_ids(self) -> None:
        """A page with two cards is rare and must not merge them."""
        descriptors = [
            _control("#m1", tag="select", input_type=None, option_values=MONTH_VALUES),
            _control("#y1", tag="select", input_type=None, option_values=YEAR_VALUES),
            _control("#m2", tag="select", input_type=None, option_values=MONTH_VALUES),
            _control("#y2", tag="select", input_type=None, option_values=YEAR_VALUES),
        ]
        raws = [
            _raw(parent="cell1"),
            _raw(parent="cell1"),
            _raw(parent="cell2"),
            _raw(parent="cell2"),
        ]
        grouped = detect_groups(descriptors, raws, now_year=FROZEN_YEAR)
        assert grouped[0].group_id != grouped[2].group_id


class TestAddressLineRuns:
    """Runs of two or three consecutive lines of one address."""

    def test_two_english_lines(self) -> None:
        """The common shape."""
        descriptors = [
            _control("#a1", label_tokens=("address", "line", "1")),
            _control("#a2", label_tokens=("address", "line", "2")),
        ]
        grouped = detect_groups(descriptors, [_raw(), _raw()], now_year=FROZEN_YEAR)
        assert all(item.group_role is GroupRole.ADDRESS_LINE_MEMBER for item in grouped)
        assert grouped[0].group_id == grouped[1].group_id

    def test_a_declared_address_line_counts_even_with_no_ordinal_in_the_label(self) -> None:
        """A page that declares its intent is believed about its structure."""
        descriptors = [
            _control("#a1", declared_token="address-line1"),
            _control("#a2", declared_token="address-line2"),
        ]
        grouped = detect_groups(descriptors, [_raw(), _raw()], now_year=FROZEN_YEAR)
        assert all(item.group_role is GroupRole.ADDRESS_LINE_MEMBER for item in grouped)

    def test_a_run_stops_at_three(self) -> None:
        """Spec section 9.5 says two or three, and four lines is two runs."""
        descriptors = [
            _control(f"#a{index}", label_tokens=("address", "line", str(index)))
            for index in (1, 2, 3, 1)
        ]
        grouped = detect_groups(descriptors, [_raw()] * 4, now_year=FROZEN_YEAR)
        assert grouped[0].group_id == grouped[2].group_id
        assert grouped[3].group_role is GroupRole.NONE

    def test_a_lone_address_line_is_not_a_run(self) -> None:
        """One line is a street address, which is a label, not a group."""
        descriptors = [
            _control("#a1", label_tokens=("address", "line", "1")),
            _control("#city", label_tokens=("town",)),
        ]
        grouped = detect_groups(descriptors, [_raw(), _raw()], now_year=FROZEN_YEAR)
        assert all(item.group_role is GroupRole.NONE for item in grouped)

    def test_a_run_does_not_cross_a_form_boundary(self) -> None:
        """Two forms on one page are two addresses."""
        descriptors = [
            _control("#a1", label_tokens=("address", "line", "1")),
            _control("#b1", label_tokens=("address", "line", "1")),
        ]
        raws = [_raw(form="form1"), _raw(form="form2")]
        grouped = detect_groups(descriptors, raws, now_year=FROZEN_YEAR)
        assert all(item.group_role is GroupRole.NONE for item in grouped)

    def test_a_select_is_never_an_address_line(self) -> None:
        """A country select is part of an address and is not a line of one."""
        descriptors = [
            _control("#a1", label_tokens=("address", "line", "1")),
            _control("#a2", tag="select", input_type=None, label_tokens=("address", "line", "2")),
        ]
        grouped = detect_groups(descriptors, [_raw(), _raw()], now_year=FROZEN_YEAR)
        assert all(item.group_role is GroupRole.NONE for item in grouped)


class TestRadioAndCheckboxGroups:
    """A shared name inside one form, which is what makes them one control."""

    def test_three_radios_sharing_a_name(self) -> None:
        """The shape the corpus does not emit and spec section 9.5 requires."""
        descriptors = [
            _control(f"#r{index}", input_type="radio", name="contact_method") for index in range(3)
        ]
        grouped = detect_groups(descriptors, [_raw()] * 3, now_year=FROZEN_YEAR)
        assert all(item.group_role is GroupRole.RADIO_MEMBER for item in grouped)
        assert len({item.group_id for item in grouped}) == 1

    def test_checkboxes_get_their_own_role(self) -> None:
        """Different role, different id, same mechanism."""
        descriptors = [
            _control(f"#c{index}", input_type="checkbox", name="topics") for index in range(2)
        ]
        grouped = detect_groups(descriptors, [_raw()] * 2, now_year=FROZEN_YEAR)
        assert all(item.group_role is GroupRole.CHECKBOX_MEMBER for item in grouped)

    def test_a_lone_checkbox_is_not_a_group(self) -> None:
        """A consent checkbox has nobody to be grouped with.

        The corpus emits standalone consent and marketing checkboxes rather than
        named groups, so this is the case that actually occurs in it.
        """
        descriptors = [_control("#terms", input_type="checkbox", name="terms_accepted")]
        grouped = detect_groups(descriptors, [_raw()], now_year=FROZEN_YEAR)
        assert grouped[0].group_role is GroupRole.NONE

    def test_a_shared_name_across_two_forms_is_two_groups(self) -> None:
        """Names are scoped to a form and so are groups."""
        descriptors = [
            _control("#r1", input_type="radio", name="choice"),
            _control("#r2", input_type="radio", name="choice"),
            _control("#r3", input_type="radio", name="choice"),
            _control("#r4", input_type="radio", name="choice"),
        ]
        raws = [_raw(form="a"), _raw(form="a"), _raw(form="b"), _raw(form="b")]
        grouped = detect_groups(descriptors, raws, now_year=FROZEN_YEAR)
        assert grouped[0].group_id != grouped[2].group_id

    def test_radios_with_no_name_are_not_grouped(self) -> None:
        """A radio with no name is broken markup, not a group."""
        descriptors = [_control(f"#r{index}", input_type="radio") for index in range(2)]
        grouped = detect_groups(descriptors, [_raw()] * 2, now_year=FROZEN_YEAR)
        assert all(item.group_role is GroupRole.NONE for item in grouped)


class TestPrecedence:
    """The one case where two rules could both fire."""

    def test_expiry_beats_an_address_run(self) -> None:
        """Expiry is the more specific claim, so it wins."""
        descriptors = [
            _control(
                "#m",
                tag="select",
                input_type=None,
                option_values=MONTH_VALUES,
                label_tokens=("address", "line", "1"),
            ),
            _control(
                "#y",
                tag="select",
                input_type=None,
                option_values=YEAR_VALUES,
                label_tokens=("address", "line", "2"),
            ),
        ]
        raws = [_raw(parent="cell1"), _raw(parent="cell1")]
        grouped = detect_groups(descriptors, raws, now_year=FROZEN_YEAR)
        assert grouped[0].group_role is GroupRole.CC_EXP_MONTH


def test_mismatched_input_lengths_are_refused() -> None:
    """The walk and the assembly disagreeing about how many controls exist is a
    bug worth a loud failure rather than a quiet misalignment."""
    with pytest.raises(ValueError, match="one raw record per descriptor"):
        detect_groups([_control("#a")], [], now_year=FROZEN_YEAR)


def test_undetectable_descriptors_are_never_grouped() -> None:
    """A synthetic descriptor names a blind spot and has no structure to share."""
    descriptors = [
        FieldDescriptor(selector="frame[#pay]", undetectable_reason="cross-origin-frame"),
        _control("#r1", input_type="radio", name="choice"),
        _control("#r2", input_type="radio", name="choice"),
    ]
    grouped = detect_groups(descriptors, [_raw()] * 3, now_year=FROZEN_YEAR)
    assert grouped[0].group_role is GroupRole.NONE
    assert grouped[1].group_role is GroupRole.RADIO_MEMBER
