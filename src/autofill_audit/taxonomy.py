"""The one definition of the label taxonomy (ground rule 6).

Every rule table, training script, report renderer, and test imports the label
set from this module. A label string literal appearing anywhere else is a defect
that ``scripts/check_reachability.py`` is allowed to fail the build on.

The label space is the WHATWG HTML autofill field-name token set (spec section
7.1, 37 tokens) plus the five enumerated extra labels of spec section 7.2. Spec
tokens carry their specification spelling as their value, lowercase and
hyphenated, because the label is the fix string: predicting ``postal-code``
yields the advice ``add autocomplete="postal-code"`` with no translation step.

Autofill modifiers (``shipping``, ``billing``, ``home``, ``work``, ``mobile``,
``fax``, ``pager``, ``section-*``, ``webauthn``) are not labels. They are
qualifiers within an ``autocomplete`` value, they are recorded on the field
descriptor by the extractor, and the classifier never predicts them.

The taxonomy may only grow under the rule of spec section 7.3.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "ALL_LABELS",
    "EXTRA_LABELS",
    "GROUPS",
    "GROUP_ORDER",
    "SPEC_TOKENS",
    "Label",
    "declaration_for",
    "group_of",
    "is_spec_token",
]


class Label(StrEnum):
    """The complete label space: 37 specification tokens plus 5 extras.

    Members whose value is lowercase and hyphenated are WHATWG autofill
    field-name tokens. Members whose value equals their own uppercase member
    name are the extra labels of spec section 7.2, which have no specification
    token and are deliberately spelled so that no extra label can ever be
    mistaken for something a browser would accept in an ``autocomplete``
    attribute.
    """

    # Identity (7)
    NAME = "name"
    GIVEN_NAME = "given-name"
    ADDITIONAL_NAME = "additional-name"
    FAMILY_NAME = "family-name"
    HONORIFIC_PREFIX = "honorific-prefix"
    HONORIFIC_SUFFIX = "honorific-suffix"
    NICKNAME = "nickname"

    # Contact (6)
    EMAIL = "email"
    TEL = "tel"
    TEL_COUNTRY_CODE = "tel-country-code"
    TEL_NATIONAL = "tel-national"
    TEL_EXTENSION = "tel-extension"
    URL = "url"

    # Address (10)
    STREET_ADDRESS = "street-address"
    ADDRESS_LINE1 = "address-line1"
    ADDRESS_LINE2 = "address-line2"
    ADDRESS_LINE3 = "address-line3"
    ADDRESS_LEVEL2 = "address-level2"
    ADDRESS_LEVEL1 = "address-level1"
    POSTAL_CODE = "postal-code"
    COUNTRY = "country"
    COUNTRY_NAME = "country-name"
    ORGANIZATION = "organization"

    # Payment (8)
    CC_NAME = "cc-name"
    CC_NUMBER = "cc-number"
    CC_EXP = "cc-exp"
    CC_EXP_MONTH = "cc-exp-month"
    CC_EXP_YEAR = "cc-exp-year"
    CC_CSC = "cc-csc"
    CC_TYPE = "cc-type"
    TRANSACTION_AMOUNT = "transaction-amount"

    # Credentials and other (6)
    USERNAME = "username"
    NEW_PASSWORD = "new-password"
    CURRENT_PASSWORD = "current-password"
    ONE_TIME_CODE = "one-time-code"
    BDAY = "bday"
    SEX = "sex"

    # Extra labels (5), spec section 7.2
    UNKNOWN = "UNKNOWN"
    NOT_AUTOFILLABLE = "NOT_AUTOFILLABLE"
    CC_EXP_SPLIT_MONTH = "CC_EXP_SPLIT_MONTH"
    CC_EXP_SPLIT_YEAR = "CC_EXP_SPLIT_YEAR"
    COMPOSITE_UNSPLIT = "COMPOSITE_UNSPLIT"


IDENTITY: Final[frozenset[Label]] = frozenset(
    {
        Label.NAME,
        Label.GIVEN_NAME,
        Label.ADDITIONAL_NAME,
        Label.FAMILY_NAME,
        Label.HONORIFIC_PREFIX,
        Label.HONORIFIC_SUFFIX,
        Label.NICKNAME,
    }
)

CONTACT: Final[frozenset[Label]] = frozenset(
    {
        Label.EMAIL,
        Label.TEL,
        Label.TEL_COUNTRY_CODE,
        Label.TEL_NATIONAL,
        Label.TEL_EXTENSION,
        Label.URL,
    }
)

ADDRESS: Final[frozenset[Label]] = frozenset(
    {
        Label.STREET_ADDRESS,
        Label.ADDRESS_LINE1,
        Label.ADDRESS_LINE2,
        Label.ADDRESS_LINE3,
        Label.ADDRESS_LEVEL2,
        Label.ADDRESS_LEVEL1,
        Label.POSTAL_CODE,
        Label.COUNTRY,
        Label.COUNTRY_NAME,
        Label.ORGANIZATION,
    }
)

PAYMENT: Final[frozenset[Label]] = frozenset(
    {
        Label.CC_NAME,
        Label.CC_NUMBER,
        Label.CC_EXP,
        Label.CC_EXP_MONTH,
        Label.CC_EXP_YEAR,
        Label.CC_CSC,
        Label.CC_TYPE,
        Label.TRANSACTION_AMOUNT,
    }
)

CREDENTIALS: Final[frozenset[Label]] = frozenset(
    {
        Label.USERNAME,
        Label.NEW_PASSWORD,
        Label.CURRENT_PASSWORD,
        Label.ONE_TIME_CODE,
        Label.BDAY,
        Label.SEX,
    }
)

EXTRA: Final[frozenset[Label]] = frozenset(
    {
        Label.UNKNOWN,
        Label.NOT_AUTOFILLABLE,
        Label.CC_EXP_SPLIT_MONTH,
        Label.CC_EXP_SPLIT_YEAR,
        Label.COMPOSITE_UNSPLIT,
    }
)

GROUPS: Final[dict[str, frozenset[Label]]] = {
    "identity": IDENTITY,
    "contact": CONTACT,
    "address": ADDRESS,
    "payment": PAYMENT,
    "credentials": CREDENTIALS,
    "extra": EXTRA,
}
"""Human-comprehension grouping. The five non-extra groups partition the 37
specification tokens exactly; the extra group holds the five section 7.2 labels."""

EXTRA_LABELS: Final[frozenset[Label]] = EXTRA
"""The five extra labels of spec section 7.2."""

SPEC_TOKENS: Final[frozenset[Label]] = IDENTITY | CONTACT | ADDRESS | PAYMENT | CREDENTIALS
"""The 37 WHATWG autofill field-name tokens adopted as labels."""

ALL_LABELS: Final[frozenset[Label]] = SPEC_TOKENS | EXTRA_LABELS
"""Every label in the taxonomy."""

GROUP_ORDER: Final[tuple[str, ...]] = (
    "identity",
    "contact",
    "address",
    "payment",
    "credentials",
    "extra",
)
"""Stable iteration order for the groups, so that a coverage table, a report
row order, and a manifest key order never depend on set iteration."""

_GROUP_OF: Final[dict[Label, str]] = {
    label: group for group, members in GROUPS.items() for label in members
}

_EXTRA_DECLARATION: Final[dict[Label, Label | None]] = {
    Label.UNKNOWN: None,
    Label.NOT_AUTOFILLABLE: None,
    Label.CC_EXP_SPLIT_MONTH: Label.CC_EXP_MONTH,
    Label.CC_EXP_SPLIT_YEAR: Label.CC_EXP_YEAR,
    Label.COMPOSITE_UNSPLIT: None,
}
"""What a correctly built page declares for each extra label, where the label
alone settles it.

The two split-expiry labels do settle it: the pair is still declared with the
specification's month and year tokens, and the extra label exists only to carry
the structural fact that the two controls must be fixed together (spec 7.2).

``UNKNOWN`` and ``NOT_AUTOFILLABLE`` declare nothing, which is the correct
markup for a search box or a consent checkbox rather than an omission.

``COMPOSITE_UNSPLIT`` is deliberately ``None`` even though a correct page does
declare something for it, because what it declares depends on what the control
composites: a single MM/YY input takes the combined expiry token and a single
full-address textarea takes the street-address token. The caller that knows
which composite it built supplies the token; the label on its own cannot."""


def is_spec_token(label: Label) -> bool:
    """Return True when ``label`` is a WHATWG token usable as an autocomplete value."""
    return label in SPEC_TOKENS


def declaration_for(label: Label) -> Label | None:
    """Return the token a correct page declares for ``label``, or None.

    None means one of two different things, and the caller must know which:
    either the label is one a correct page declares nothing for, or it is
    ``COMPOSITE_UNSPLIT``, whose declaration depends on the composite. See
    ``_EXTRA_DECLARATION``.
    """
    if label in SPEC_TOKENS:
        return label
    return _EXTRA_DECLARATION[label]


def group_of(label: Label) -> str:
    """Return the group name a label belongs to.

    Raises:
        KeyError: if the label is somehow not covered by ``GROUPS``, which the
            module-level consistency assertion below makes unreachable.
    """
    return _GROUP_OF[label]


# Consistency invariants, asserted at import so a mistake in this file cannot
# reach a rule table, a training run, or a report. The test suite asserts the
# same properties independently, against the specification counts.
assert len(Label) == 42, "taxonomy must hold exactly 37 spec tokens plus 5 extras"
assert len(SPEC_TOKENS) == 37, "spec token count fixed by spec section 7.1"
assert len(EXTRA_LABELS) == 5, "extra label count fixed by spec section 7.2"
assert len(_GROUP_OF) == len(Label), "groups must cover every label exactly once"
assert len({label.value for label in Label}) == len(Label), "label values must be unique"
assert set(GROUP_ORDER) == set(GROUPS), "the group order must name every group exactly once"
assert len(GROUP_ORDER) == len(GROUPS), "the group order must not repeat a group"
assert set(_EXTRA_DECLARATION) == EXTRA_LABELS, "every extra label needs a declaration entry"
