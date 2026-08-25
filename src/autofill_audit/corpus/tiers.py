"""Markup-quality tiers and the transforms that produce them (spec section 8.4).

Every fraction and count in this module is a *generator constant* with a name,
not a number typed into a branch. Spec section 8.4 asks for the wrong-declaration
fraction of the partial tier to be stated; stating it in a docstring while the
code uses a literal would leave two copies to disagree, so the constant is the
only copy and the documentation quotes it by name.

The four tiers, and what each is for:

- ``clean`` is the false-positive test. Every control carries a correct label, a
  semantic identifier, the right input type, and the right declaration. Spec
  section 8.4 makes any finding above INFO on a clean form a defect, and P3's
  gate asserts that over the whole clean slice.
- ``partial`` is where the tool earns its keep, because a wrong declaration is
  invisible to a developer reading their own template.
- ``hostile`` is where the classifier is tested: no labels, generic identifiers,
  shadow roots, ungrouped split fields, a field that does not exist at load, and
  one control a human could not label either.
- ``mixed`` is what real pages look like once one team has rewritten checkout
  and another has not: sections drawn from different tiers within one form.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

import numpy as np

from autofill_audit.taxonomy import Label

__all__ = [
    "HOSTILE_PLACEHOLDER_FRACTION",
    "INJECTED_FIELD_DELAY_MS",
    "MIXED_TIERS",
    "PARTIAL_CORRECT_DECLARATION_FRACTION",
    "PARTIAL_WRONG_DECLARATION_FRACTION",
    "Declaration",
    "Delivery",
    "IdentifierStyle",
    "Tier",
    "partial_declaration",
    "wrong_declaration_value",
]


class Tier(StrEnum):
    """The four markup-quality tiers."""

    CLEAN = "clean"
    PARTIAL = "partial"
    HOSTILE = "hostile"
    MIXED = "mixed"


MIXED_TIERS: Final[tuple[Tier, ...]] = (Tier.CLEAN, Tier.PARTIAL, Tier.HOSTILE)
"""The tiers a mixed form draws its sections from. ``MIXED`` itself is not among
them, because a mixed section would just be a form within a form."""

PARTIAL_WRONG_DECLARATION_FRACTION: Final[float] = 0.20
"""The stated fraction of spec section 8.4: on a partial-tier form, this share of
the controls that could carry a declaration carry a wrong one instead."""

PARTIAL_CORRECT_DECLARATION_FRACTION: Final[float] = 0.50
"""The share that carry a correct declaration. The remainder, one minus the two
fractions above, carry none at all."""

HOSTILE_PLACEHOLDER_FRACTION: Final[float] = 0.5
"""The share of hostile-tier controls that carry the label text as a placeholder
instead of a real label. The rest carry no text signal at all. This is the
placeholder-as-label antipattern, and the split is what makes the hostile tier
graded rather than uniformly impossible."""

INJECTED_FIELD_DELAY_MS: Final[int] = 300
"""How long after load the injected control appears. Matched to the fixture spec
section 15 layer 2 asks for, so P2 exercises one settle policy rather than two."""


class Declaration(StrEnum):
    """What a partial-tier control does about its autocomplete attribute."""

    CORRECT = "correct"
    WRONG = "wrong"
    ABSENT = "absent"


class IdentifierStyle(StrEnum):
    """How a control's ``name`` and ``id`` are formed.

    The last four exist only in the hostile tier, and between them they force
    every branch of the selector preference order of spec section 9.3 to be
    exercised by the corpus rather than only by unit tests.
    """

    SEMANTIC = "semantic"
    """``shipping-postcode``: an authored, meaningful identifier."""
    NUMBERED = "numbered"
    """``input1``: generic but usable as an id selector."""
    UNDERSCORED = "underscored"
    """``field_7``: generic, with a matching name attribute."""
    LEGACY_NAME = "legacy_name"
    """``ctl00$txt3`` as a name with no id, forcing the name-scoped selector."""
    HEX_ID = "hex_id"
    """An id carrying a hexadecimal run, which ``looks_generated`` rejects, so
    the selector falls back even though an id is present."""
    BARE = "bare"
    """Neither id nor name, forcing the positional path."""


class Delivery(StrEnum):
    """How a control reaches the DOM."""

    STATIC = "static"
    SHADOW = "shadow"
    """Inside an open shadow root attached by a custom element."""
    INJECTED = "injected"
    """Appended by an inline script after load."""


_OFF_SPEC_TOKENS: Final[tuple[str, ...]] = (
    "address",
    "fname",
    "lname",
    "zipcode",
    "cardnum",
    "fullname",
    "on",
)
"""Values that appear in real templates and are not autofill field-name tokens.
They produce the OFF_SPEC_TOKEN finding of spec section 11.1 rather than a
mismatch, which is a different finding with a different fix."""

_CONFUSABLE: Final[dict[Label, Label]] = {
    Label.GIVEN_NAME: Label.NAME,
    Label.FAMILY_NAME: Label.NAME,
    Label.ADDRESS_LINE1: Label.STREET_ADDRESS,
    Label.ADDRESS_LINE2: Label.ADDRESS_LINE1,
    Label.ADDRESS_LINE3: Label.ADDRESS_LINE2,
    Label.ADDRESS_LEVEL2: Label.ADDRESS_LEVEL1,
    Label.ADDRESS_LEVEL1: Label.ADDRESS_LEVEL2,
    Label.POSTAL_CODE: Label.ADDRESS_LEVEL2,
    Label.ORGANIZATION: Label.NAME,
    Label.CC_EXP_MONTH: Label.CC_EXP,
    Label.CC_EXP_YEAR: Label.CC_EXP,
    Label.CC_CSC: Label.CC_NUMBER,
    Label.CC_NAME: Label.NAME,
    Label.NEW_PASSWORD: Label.CURRENT_PASSWORD,
    Label.CURRENT_PASSWORD: Label.NEW_PASSWORD,
    Label.USERNAME: Label.EMAIL,
    Label.EMAIL: Label.USERNAME,
    Label.TEL_NATIONAL: Label.TEL_COUNTRY_CODE,
    Label.TEL_COUNTRY_CODE: Label.TEL_NATIONAL,
    Label.COUNTRY_NAME: Label.ADDRESS_LEVEL1,
    Label.BDAY: Label.SEX,
}
"""Wrong declarations that are still valid tokens, chosen to be the mistakes
real templates actually make. Deliberately excludes every pair in the
equivalence set of spec section 11.1: declaring ``tel`` on a national number is
not an error, so it would be a useless thing for the corpus to assert is one."""


def partial_declaration(rng: np.random.Generator) -> Declaration:
    """Draw what one partial-tier control does about its declaration."""
    draw = float(rng.random())
    if draw < PARTIAL_WRONG_DECLARATION_FRACTION:
        return Declaration.WRONG
    if draw < PARTIAL_WRONG_DECLARATION_FRACTION + PARTIAL_CORRECT_DECLARATION_FRACTION:
        return Declaration.CORRECT
    return Declaration.ABSENT


def wrong_declaration_value(rng: np.random.Generator, correct: Label | None) -> str:
    """Return a wrong but plausible raw autocomplete value.

    Half the time, where a confusable token exists, the wrong value is a real
    token that means something else, which is the case the audit engine can be
    most confident about because both a declaration and an inference exist. The
    other half is an off-spec string, which is a different finding.
    """
    confusable = _CONFUSABLE.get(correct) if correct is not None else None
    if confusable is not None and bool(rng.random() < 0.5):
        return confusable.value
    index = int(rng.integers(0, len(_OFF_SPEC_TOKENS)))
    return _OFF_SPEC_TOKENS[index]


assert 0.0 < PARTIAL_WRONG_DECLARATION_FRACTION < 1.0
assert 0.0 < PARTIAL_CORRECT_DECLARATION_FRACTION < 1.0
assert PARTIAL_WRONG_DECLARATION_FRACTION + PARTIAL_CORRECT_DECLARATION_FRACTION < 1.0, (
    "some partial-tier controls must carry no declaration at all"
)
