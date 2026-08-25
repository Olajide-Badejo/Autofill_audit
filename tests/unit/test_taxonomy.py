"""Taxonomy invariants.

The token lists below are transcribed from spec section 7.1 rather than derived
from the enum, on purpose. A test that reads the values out of the code under
test proves only that the code agrees with itself; these lists are the
independent statement of what the WHATWG token set contains, so a typo in
``taxonomy.py`` fails here instead of propagating into every fix string the tool
ever prints.
"""

from __future__ import annotations

import pytest

from autofill_audit.taxonomy import (
    ALL_LABELS,
    EXTRA_LABELS,
    GROUPS,
    SPEC_TOKENS,
    Label,
    group_of,
    is_spec_token,
)

IDENTITY_TOKENS = [
    "name",
    "given-name",
    "additional-name",
    "family-name",
    "honorific-prefix",
    "honorific-suffix",
    "nickname",
]
CONTACT_TOKENS = [
    "email",
    "tel",
    "tel-country-code",
    "tel-national",
    "tel-extension",
    "url",
]
ADDRESS_TOKENS = [
    "street-address",
    "address-line1",
    "address-line2",
    "address-line3",
    "address-level2",
    "address-level1",
    "postal-code",
    "country",
    "country-name",
    "organization",
]
PAYMENT_TOKENS = [
    "cc-name",
    "cc-number",
    "cc-exp",
    "cc-exp-month",
    "cc-exp-year",
    "cc-csc",
    "cc-type",
    "transaction-amount",
]
CREDENTIAL_TOKENS = [
    "username",
    "new-password",
    "current-password",
    "one-time-code",
    "bday",
    "sex",
]

EXTRA_NAMES = [
    "UNKNOWN",
    "NOT_AUTOFILLABLE",
    "CC_EXP_SPLIT_MONTH",
    "CC_EXP_SPLIT_YEAR",
    "COMPOSITE_UNSPLIT",
]

GROUP_EXPECTATIONS = {
    "identity": IDENTITY_TOKENS,
    "contact": CONTACT_TOKENS,
    "address": ADDRESS_TOKENS,
    "payment": PAYMENT_TOKENS,
    "credentials": CREDENTIAL_TOKENS,
    "extra": EXTRA_NAMES,
}

ALL_SPEC_TOKEN_STRINGS = (
    IDENTITY_TOKENS + CONTACT_TOKENS + ADDRESS_TOKENS + PAYMENT_TOKENS + CREDENTIAL_TOKENS
)


def test_spec_token_count_is_thirty_seven() -> None:
    assert len(ALL_SPEC_TOKEN_STRINGS) == 37
    assert len(SPEC_TOKENS) == 37


def test_spec_token_values_match_the_specification_strings() -> None:
    assert {label.value for label in SPEC_TOKENS} == set(ALL_SPEC_TOKEN_STRINGS)


@pytest.mark.parametrize("token", ALL_SPEC_TOKEN_STRINGS)
def test_every_spec_token_is_a_label(token: str) -> None:
    assert Label(token) in SPEC_TOKENS


def test_spec_tokens_are_lowercase_and_hyphenated() -> None:
    for label in SPEC_TOKENS:
        assert label.value == label.value.lower()
        assert " " not in label.value
        assert "_" not in label.value


def test_the_five_extras_are_present_and_spelled_as_their_own_names() -> None:
    assert len(EXTRA_LABELS) == 5
    assert {label.value for label in EXTRA_LABELS} == set(EXTRA_NAMES)
    for label in EXTRA_LABELS:
        assert label.name == label.value


def test_extras_are_not_spec_tokens() -> None:
    for label in EXTRA_LABELS:
        assert not is_spec_token(label)
    for label in SPEC_TOKENS:
        assert is_spec_token(label)


def test_all_labels_is_the_union() -> None:
    assert ALL_LABELS == SPEC_TOKENS | EXTRA_LABELS
    assert len(ALL_LABELS) == 42


def test_no_duplicate_values_and_no_hidden_aliases() -> None:
    assert len({label.value for label in Label}) == len(Label)
    assert len(Label.__members__) == len(list(Label))


def test_groups_partition_the_taxonomy() -> None:
    assert set(GROUPS) == set(GROUP_EXPECTATIONS)
    union: set[Label] = set()
    for group, members in GROUPS.items():
        assert {label.value for label in members} == set(GROUP_EXPECTATIONS[group])
        assert union.isdisjoint(members), f"{group} overlaps an earlier group"
        union |= members
    assert union == ALL_LABELS


def test_the_five_spec_groups_partition_the_spec_tokens() -> None:
    spec_groups = [name for name in GROUPS if name != "extra"]
    union: set[Label] = set()
    for name in spec_groups:
        union |= GROUPS[name]
    assert union == SPEC_TOKENS


@pytest.mark.parametrize("group", sorted(GROUP_EXPECTATIONS))
def test_group_of_agrees_with_the_group_mapping(group: str) -> None:
    for label in GROUPS[group]:
        assert group_of(label) == group


def test_label_is_a_string_enum_so_the_label_is_the_fix_string() -> None:
    assert Label.POSTAL_CODE == "postal-code"
    assert f'autocomplete="{Label.POSTAL_CODE}"' == 'autocomplete="postal-code"'
