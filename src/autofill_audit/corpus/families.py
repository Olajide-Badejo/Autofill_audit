"""The template set: five families, five structurally distinct templates each.

Spec section 8.6 makes the template the atom of the train/dev/test split, which
means a "template" has to be a real structural skeleton and not a relabelling of
its siblings. Two templates in the same family differ in which sections exist,
which slots those sections carry, and how the composite and split cases are
rendered. If two of them differed only in field order, splitting on templates
would leak, because the split's whole purpose is to keep a test-set form from
sharing its author's conventions with a training form.

A template does not know what a locale looks like. It asks for a name block or
an address block by *style*, and the locale profile decides which slots that
style expands to and in what order (``locales.py``). A template that listed
address-line-1 and address-line-2 directly would silently assert that every
locale composes an address the same way, which is the failure spec section 8.1
calls out by name.

Sections carry the autofill *modifiers* of spec section 7.1: a shipping section
declares ``shipping``, a billing section declares ``billing``, and the answer
key records that as ``expected_modifiers`` so P3 can tell a correct
``shipping postal-code`` declaration from a mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from autofill_audit.corpus.roles import SlotRole

__all__ = [
    "ADDRESS_STYLES",
    "NAME_STYLES",
    "TEMPLATES",
    "Family",
    "ItemKind",
    "Section",
    "SectionItem",
    "Template",
    "templates_for",
]


class Family(StrEnum):
    """The five form families of spec section 8.3."""

    CHECKOUT = "checkout"
    SIGNUP = "signup"
    ADDRESS = "address"
    PAYMENT = "payment"
    LOGIN = "login"


class ItemKind(StrEnum):
    """What a section item asks the locale profile for."""

    FIELD = "field"
    NAME_BLOCK = "name_block"
    ADDRESS_BLOCK = "address_block"


NAME_STYLES: Final[tuple[str, ...]] = ("full", "split", "split_middle", "honorific")
ADDRESS_STYLES: Final[tuple[str, ...]] = ("lines", "lines3", "street", "composite")


@dataclass(frozen=True, slots=True)
class SectionItem:
    """One request within a section: a concrete slot, or a block to expand."""

    kind: ItemKind
    role: SlotRole | None = None
    style: str = ""

    def __post_init__(self) -> None:
        if self.kind is ItemKind.FIELD and self.role is None:
            raise ValueError("a field item must name a role")
        if self.kind is not ItemKind.FIELD and not self.style:
            raise ValueError("a block item must name a style")


def f(role: SlotRole) -> SectionItem:
    """A concrete field."""
    return SectionItem(kind=ItemKind.FIELD, role=role)


def name_block(style: str) -> SectionItem:
    """A name block, expanded by the locale profile."""
    return SectionItem(kind=ItemKind.NAME_BLOCK, style=style)


def address_block(style: str) -> SectionItem:
    """An address block, expanded by the locale profile."""
    return SectionItem(kind=ItemKind.ADDRESS_BLOCK, style=style)


@dataclass(frozen=True, slots=True)
class Section:
    """One titled group of items."""

    key: str
    """Selects the heading text from the locale profile's section table."""
    items: tuple[SectionItem, ...]
    modifiers: tuple[str, ...] = ()
    """Autofill modifiers every field in this section inherits."""


@dataclass(frozen=True, slots=True)
class Template:
    """A structural skeleton, and the atom of the split."""

    template_id: str
    family: Family
    sections: tuple[Section, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if len(self.sections) < 2:
            raise ValueError(
                f"{self.template_id}: a template needs at least two sections, because the "
                "mixed tier draws a tier per section and a one-section form cannot mix"
            )


_SHIPPING: Final[tuple[str, ...]] = ("shipping",)
_BILLING: Final[tuple[str, ...]] = ("billing",)


_TEMPLATES: Final[tuple[Template, ...]] = (
    # Checkout. The broadest family: it is where the shipping and billing
    # modifiers live and where NOT_AUTOFILLABLE has the most natural homes.
    Template(
        "checkout-01",
        Family.CHECKOUT,
        (
            Section("contact", (f(SlotRole.EMAIL), f(SlotRole.PHONE))),
            Section(
                "shipping",
                (f(SlotRole.ORGANIZATION), address_block("lines"), f(SlotRole.COUNTRY_SELECT)),
                _SHIPPING,
            ),
            Section("billing", (address_block("lines"), f(SlotRole.COUNTRY_SELECT)), _BILLING),
            Section(
                "payment",
                (
                    f(SlotRole.CARD_HOLDER),
                    f(SlotRole.CARD_NUMBER),
                    f(SlotRole.CARD_EXPIRY_COMPOSITE),
                    f(SlotRole.CARD_SECURITY_CODE),
                ),
            ),
            Section("extras", (f(SlotRole.COMMENTS), f(SlotRole.CONSENT))),
        ),
    ),
    Template(
        "checkout-02",
        Family.CHECKOUT,
        (
            Section("contact", (f(SlotRole.EMAIL),)),
            Section("shipping", (address_block("street"), f(SlotRole.COUNTRY_SELECT)), _SHIPPING),
            Section(
                "payment",
                (
                    f(SlotRole.CARD_TYPE),
                    f(SlotRole.CARD_HOLDER),
                    f(SlotRole.CARD_NUMBER),
                    f(SlotRole.CARD_EXPIRY_SPLIT_MONTH),
                    f(SlotRole.CARD_EXPIRY_SPLIT_YEAR),
                    f(SlotRole.CARD_SECURITY_CODE),
                ),
            ),
            Section("order", (f(SlotRole.QUANTITY), f(SlotRole.COUPON))),
        ),
    ),
    Template(
        "checkout-03",
        Family.CHECKOUT,
        (
            Section("extras", (f(SlotRole.SEARCH),)),
            Section(
                "identity",
                (name_block("split_middle"), f(SlotRole.EMAIL), f(SlotRole.WEBSITE)),
            ),
            Section(
                "shipping",
                (f(SlotRole.ORGANIZATION), address_block("lines3"), f(SlotRole.COUNTRY_SELECT)),
                _SHIPPING,
            ),
            Section(
                "payment",
                (
                    f(SlotRole.CARD_NUMBER),
                    f(SlotRole.CARD_EXPIRY_MONTH),
                    f(SlotRole.CARD_EXPIRY_YEAR),
                    f(SlotRole.CARD_SECURITY_CODE),
                ),
            ),
        ),
    ),
    Template(
        "checkout-04",
        Family.CHECKOUT,
        (
            Section(
                "contact",
                (
                    name_block("full"),
                    f(SlotRole.EMAIL),
                    f(SlotRole.PHONE_COUNTRY_CODE),
                    f(SlotRole.PHONE_NATIONAL),
                    f(SlotRole.PHONE_EXTENSION),
                ),
            ),
            Section("shipping", (address_block("lines"), f(SlotRole.COUNTRY_SELECT)), _SHIPPING),
            Section(
                "payment",
                (
                    f(SlotRole.CARD_HOLDER),
                    f(SlotRole.CARD_NUMBER),
                    f(SlotRole.CARD_EXPIRY),
                    f(SlotRole.CARD_SECURITY_CODE),
                ),
            ),
            Section("extras", (f(SlotRole.CONSENT),)),
        ),
    ),
    Template(
        "checkout-05",
        Family.CHECKOUT,
        (
            Section("identity", (name_block("honorific"), f(SlotRole.EMAIL))),
            Section("shipping", (address_block("lines"), f(SlotRole.COUNTRY_TEXT)), _SHIPPING),
            Section("billing", (address_block("composite"),), _BILLING),
            Section(
                "payment",
                (
                    f(SlotRole.CARD_NUMBER),
                    f(SlotRole.CARD_EXPIRY_COMPOSITE),
                    f(SlotRole.CARD_SECURITY_CODE),
                    f(SlotRole.AMOUNT),
                ),
            ),
            Section("extras", (f(SlotRole.COMMENTS),)),
        ),
    ),
    # Signup. Where the rare identity labels live, because a registration form
    # is the only place a real page asks for an honorific or a nickname.
    Template(
        "signup-01",
        Family.SIGNUP,
        (
            Section("identity", (name_block("split"), f(SlotRole.EMAIL))),
            Section(
                "account",
                (
                    f(SlotRole.USERNAME),
                    f(SlotRole.NEW_PASSWORD),
                    f(SlotRole.NEW_PASSWORD_CONFIRM),
                ),
            ),
            Section("extras", (f(SlotRole.CONSENT),)),
        ),
    ),
    Template(
        "signup-02",
        Family.SIGNUP,
        (
            Section(
                "identity",
                (
                    name_block("honorific"),
                    f(SlotRole.ADDITIONAL_NAME),
                    f(SlotRole.NICKNAME),
                    f(SlotRole.EMAIL),
                ),
            ),
            Section("account", (f(SlotRole.NEW_PASSWORD),)),
            Section("extras", (f(SlotRole.MARKETING_OPT_IN),)),
        ),
    ),
    Template(
        "signup-03",
        Family.SIGNUP,
        (
            Section(
                "identity",
                (
                    name_block("full"),
                    f(SlotRole.NICKNAME),
                    f(SlotRole.EMAIL),
                    f(SlotRole.BIRTH_DATE),
                    f(SlotRole.SEX),
                    f(SlotRole.PHONE),
                    f(SlotRole.WEBSITE),
                ),
            ),
            Section("account", (f(SlotRole.NEW_PASSWORD),)),
        ),
    ),
    Template(
        "signup-04",
        Family.SIGNUP,
        (
            Section("identity", (f(SlotRole.ORGANIZATION), f(SlotRole.WEBSITE))),
            Section(
                "contact",
                (
                    name_block("split"),
                    f(SlotRole.EMAIL),
                    f(SlotRole.PHONE_COUNTRY_CODE),
                    f(SlotRole.PHONE_NATIONAL),
                ),
            ),
            Section("address", (address_block("street"), f(SlotRole.COUNTRY_SELECT))),
            Section("account", (f(SlotRole.NEW_PASSWORD),)),
        ),
    ),
    Template(
        "signup-05",
        Family.SIGNUP,
        (
            Section("extras", (f(SlotRole.SEARCH),)),
            Section(
                "identity",
                (
                    f(SlotRole.USERNAME),
                    f(SlotRole.EMAIL),
                    f(SlotRole.BIRTH_DATE),
                    f(SlotRole.SEX),
                ),
            ),
            Section("security", (f(SlotRole.NEW_PASSWORD), f(SlotRole.NEW_PASSWORD_CONFIRM))),
            Section("order", (f(SlotRole.CONSENT),)),
        ),
    ),
    # Address. One address block per template, so the locale differences of
    # spec section 8.1 are the only thing varying across the six locales.
    Template(
        "address-01",
        Family.ADDRESS,
        (
            Section("identity", (name_block("split"),)),
            Section("address", (address_block("lines"), f(SlotRole.COUNTRY_SELECT))),
            Section("contact", (f(SlotRole.PHONE),)),
        ),
    ),
    Template(
        "address-02",
        Family.ADDRESS,
        (
            Section("identity", (f(SlotRole.ORGANIZATION),)),
            Section("address", (address_block("lines3"), f(SlotRole.COUNTRY_SELECT))),
        ),
    ),
    Template(
        "address-03",
        Family.ADDRESS,
        (
            Section("identity", (name_block("full"),)),
            Section("address", (address_block("street"), f(SlotRole.COUNTRY_TEXT))),
        ),
    ),
    Template(
        "address-04",
        Family.ADDRESS,
        (
            Section("identity", (name_block("full"),)),
            Section("address", (address_block("composite"), f(SlotRole.COUNTRY_SELECT))),
            Section("contact", (f(SlotRole.PHONE),)),
        ),
    ),
    Template(
        "address-05",
        Family.ADDRESS,
        (
            Section("address", (address_block("lines"),)),
            Section(
                "contact",
                (
                    f(SlotRole.PHONE_COUNTRY_CODE),
                    f(SlotRole.PHONE_NATIONAL),
                    f(SlotRole.PHONE_EXTENSION),
                ),
            ),
            Section("extras", (f(SlotRole.COMMENTS),)),
        ),
    ),
    # Payment. Both split-expiry renderings, both composites, and the two
    # specification expiry tokens as plain inputs, so that all four expiry
    # labels are reachable and distinguishable.
    Template(
        "payment-01",
        Family.PAYMENT,
        (
            Section("payment", (f(SlotRole.CARD_HOLDER), f(SlotRole.CARD_NUMBER))),
            Section(
                "security",
                (
                    f(SlotRole.CARD_EXPIRY_SPLIT_MONTH),
                    f(SlotRole.CARD_EXPIRY_SPLIT_YEAR),
                    f(SlotRole.CARD_SECURITY_CODE),
                ),
            ),
        ),
    ),
    Template(
        "payment-02",
        Family.PAYMENT,
        (
            Section(
                "payment",
                (f(SlotRole.CARD_TYPE), f(SlotRole.CARD_HOLDER), f(SlotRole.CARD_NUMBER)),
            ),
            Section(
                "security",
                (f(SlotRole.CARD_EXPIRY_COMPOSITE), f(SlotRole.CARD_SECURITY_CODE)),
            ),
        ),
    ),
    Template(
        "payment-03",
        Family.PAYMENT,
        (
            Section("order", (f(SlotRole.AMOUNT), f(SlotRole.EMAIL))),
            Section(
                "payment",
                (
                    f(SlotRole.CARD_HOLDER),
                    f(SlotRole.CARD_NUMBER),
                    f(SlotRole.CARD_EXPIRY),
                    f(SlotRole.CARD_SECURITY_CODE),
                ),
            ),
            Section("extras", (f(SlotRole.COMMENTS),)),
        ),
    ),
    Template(
        "payment-04",
        Family.PAYMENT,
        (
            Section("payment", (f(SlotRole.CARD_TYPE), f(SlotRole.CARD_NUMBER))),
            Section(
                "security",
                (
                    f(SlotRole.CARD_EXPIRY_MONTH),
                    f(SlotRole.CARD_EXPIRY_YEAR),
                    f(SlotRole.CARD_SECURITY_CODE),
                ),
            ),
            Section("billing", (f(SlotRole.POSTAL_CODE),), _BILLING),
        ),
    ),
    Template(
        "payment-05",
        Family.PAYMENT,
        (
            Section("order", (f(SlotRole.COUPON), f(SlotRole.QUANTITY))),
            Section(
                "payment",
                (
                    f(SlotRole.CARD_HOLDER),
                    f(SlotRole.CARD_NUMBER),
                    f(SlotRole.CARD_EXPIRY_SPLIT_MONTH),
                    f(SlotRole.CARD_EXPIRY_SPLIT_YEAR),
                    f(SlotRole.CARD_SECURITY_CODE),
                ),
            ),
            Section("extras", (f(SlotRole.CONSENT),)),
        ),
    ),
    # Login. Small forms, and the home of the username-against-email ambiguity
    # spec section 8.3 names.
    Template(
        "login-01",
        Family.LOGIN,
        (
            Section("account", (f(SlotRole.USERNAME),)),
            Section("security", (f(SlotRole.CURRENT_PASSWORD),)),
        ),
    ),
    Template(
        "login-02",
        Family.LOGIN,
        (
            Section("account", (f(SlotRole.EMAIL), f(SlotRole.CURRENT_PASSWORD))),
            Section("extras", (f(SlotRole.CONSENT),)),
        ),
    ),
    Template(
        "login-03",
        Family.LOGIN,
        (
            Section("account", (f(SlotRole.USERNAME), f(SlotRole.CURRENT_PASSWORD))),
            Section("security", (f(SlotRole.ONE_TIME_CODE),)),
        ),
    ),
    Template(
        "login-04",
        Family.LOGIN,
        (
            Section("account", (f(SlotRole.EMAIL),)),
            Section("security", (f(SlotRole.ONE_TIME_CODE),)),
        ),
    ),
    Template(
        "login-05",
        Family.LOGIN,
        (
            Section("extras", (f(SlotRole.SEARCH),)),
            Section("account", (f(SlotRole.USERNAME), f(SlotRole.CURRENT_PASSWORD))),
        ),
    ),
)

TEMPLATES: Final[dict[str, Template]] = {template.template_id: template for template in _TEMPLATES}


def templates_for(family: Family) -> tuple[Template, ...]:
    """Return the templates of one family, in declaration order."""
    return tuple(template for template in _TEMPLATES if template.family is family)


assert len(TEMPLATES) == len(_TEMPLATES), "template identifiers must be unique"
for _family in Family:
    assert len(templates_for(_family)) == 5, f"{_family} must carry five templates"
