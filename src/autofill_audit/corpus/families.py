"""The template set: five families, eight structurally distinct templates each.

Spec section 8.6 makes the template the atom of the train/dev/test split, which
means a "template" has to be a real structural skeleton and not a relabelling of
its siblings. Two templates in the same family differ in which sections exist,
which slots those sections carry, and how the composite and split cases are
rendered. If two of them differed only in field order, splitting on templates
would leak, because the split's whole purpose is to keep a test-set form from
sharing its author's conventions with a training form.

**Why eight rather than five.** The count is a statistical requirement rather
than a target for variety. The template is the clustering unit of spec section
13.3, so the number of test-partition templates is the number of clusters the
paired sign-flip permutation gets, and five clusters give thirty-two
arrangements and a smallest attainable two sided p value above the
pre-registered alpha. P5 measured on that design and could certify nothing, at
any effect size. Eight per family at a five, one, two split puts ten templates
in the test partition, which is one thousand and twenty-four arrangements. The
reasoning is in ``experiments/predictions/p5r-power-repair.md`` and in the
engineering log, both committed before these templates were written.

**The last three of each family carry the starved labels on purpose.** A label
with no training rows is a class the model can only get wrong, and three labels
had exactly that: ``country-name``, ``one-time-code`` and ``street-address``.
Templates 06 to 08 are built around them rather than leaving them to turn up by
luck, which is why several of them carry a country field as free text, an
address as a single street line, and a verification code.
``check_reachability.py`` enforces the minimum, so a later template change that
stopped emitting one of them fails the build instead of quietly starving a class
again.

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
    "TEMPLATES_PER_FAMILY",
    "Family",
    "ItemKind",
    "Section",
    "SectionItem",
    "Template",
    "templates_for",
]

TEMPLATES_PER_FAMILY: Final[int] = 8
"""How many structurally distinct templates each family carries.

Asserted at import rather than trusted, because the split's power is a function
of this number and a family that quietly lost a template would shrink the test
partition's cluster count without failing anything."""


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
    Template(
        "checkout-06",
        Family.CHECKOUT,
        (
            # The only checkout that opens an account on the way through, so the
            # credential pair sits above the shipping block rather than below it,
            # and the shipping address is the composite textarea while the
            # billing address is the three line form. One page carrying both
            # address renderings is a real pattern and it is the case a
            # classifier keyed on section position gets wrong. The expiry is the
            # native month input, which is the fourth of the four renderings.
            Section("account", (f(SlotRole.EMAIL), f(SlotRole.USERNAME), f(SlotRole.NEW_PASSWORD))),
            Section(
                "shipping",
                (name_block("split"), address_block("composite"), f(SlotRole.COUNTRY_SELECT)),
                _SHIPPING,
            ),
            Section("billing", (address_block("lines3"), f(SlotRole.COUNTRY_SELECT)), _BILLING),
            Section(
                "payment",
                (
                    f(SlotRole.CARD_TYPE),
                    f(SlotRole.CARD_NUMBER),
                    f(SlotRole.CARD_EXPIRY),
                    f(SlotRole.CARD_SECURITY_CODE),
                ),
            ),
            Section("extras", (f(SlotRole.MARKETING_OPT_IN),)),
        ),
    ),
    Template(
        "checkout-07",
        Family.CHECKOUT,
        (
            # Guest checkout: no account section at all, the name and the whole
            # telephone are collected together at the top, the shipping address
            # is one street line, and the country is typed rather than chosen.
            # The expiry is a pair of plain numeric inputs, which is the third of
            # the four expiry renderings.
            Section(
                "contact",
                (
                    name_block("split_middle"),
                    f(SlotRole.EMAIL),
                    f(SlotRole.PHONE_COUNTRY_CODE),
                    f(SlotRole.PHONE_NATIONAL),
                    f(SlotRole.PHONE_EXTENSION),
                ),
            ),
            Section(
                "shipping",
                (f(SlotRole.ORGANIZATION), address_block("street"), f(SlotRole.COUNTRY_TEXT)),
                _SHIPPING,
            ),
            Section(
                "payment",
                (
                    f(SlotRole.CARD_HOLDER),
                    f(SlotRole.CARD_NUMBER),
                    f(SlotRole.CARD_EXPIRY_MONTH),
                    f(SlotRole.CARD_EXPIRY_YEAR),
                    f(SlotRole.CARD_SECURITY_CODE),
                ),
            ),
            Section("extras", (f(SlotRole.COMMENTS), f(SlotRole.CONSENT))),
        ),
    ),
    Template(
        "checkout-08",
        Family.CHECKOUT,
        (
            # An invoiced order: an honorific identity block, a street shipping
            # address, a composite billing address, an explicit amount, and an
            # order section carrying two of the labels a page must not declare.
            # It is the training home of street-address and country-name.
            Section("identity", (name_block("honorific"), f(SlotRole.EMAIL))),
            Section("shipping", (address_block("street"), f(SlotRole.COUNTRY_SELECT)), _SHIPPING),
            Section("billing", (address_block("composite"), f(SlotRole.COUNTRY_TEXT)), _BILLING),
            Section(
                "payment",
                (
                    f(SlotRole.CARD_TYPE),
                    f(SlotRole.CARD_NUMBER),
                    f(SlotRole.CARD_EXPIRY_COMPOSITE),
                    f(SlotRole.CARD_SECURITY_CODE),
                    f(SlotRole.AMOUNT),
                ),
            ),
            Section("order", (f(SlotRole.QUANTITY), f(SlotRole.COUPON))),
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
    Template(
        "signup-06",
        Family.SIGNUP,
        (
            # A developer account: the credential pair comes first and the
            # identity is optional decoration afterwards, which is the inverse of
            # every other signup here. The verification code sits in its own
            # section because the page asks for it after the address is sent.
            Section(
                "account",
                (
                    f(SlotRole.USERNAME),
                    f(SlotRole.EMAIL),
                    f(SlotRole.NEW_PASSWORD),
                    f(SlotRole.NEW_PASSWORD_CONFIRM),
                ),
            ),
            Section(
                "identity",
                (
                    name_block("full"),
                    f(SlotRole.NICKNAME),
                    f(SlotRole.BIRTH_DATE),
                    f(SlotRole.SEX),
                    f(SlotRole.WEBSITE),
                    f(SlotRole.ORGANIZATION),
                ),
            ),
            Section("security", (f(SlotRole.ONE_TIME_CODE),)),
            Section("extras", (f(SlotRole.CONSENT),)),
        ),
    ),
    Template(
        "signup-07",
        Family.SIGNUP,
        (
            # Profile completion after an account already exists: the widest
            # identity block in the corpus, the full three part telephone, and a
            # security section that pairs a new password with a verification
            # code. It is the training home of one-time-code.
            Section(
                "identity",
                (
                    name_block("split_middle"),
                    f(SlotRole.NICKNAME),
                    f(SlotRole.BIRTH_DATE),
                    f(SlotRole.SEX),
                ),
            ),
            Section(
                "contact",
                (
                    f(SlotRole.EMAIL),
                    f(SlotRole.PHONE_COUNTRY_CODE),
                    f(SlotRole.PHONE_NATIONAL),
                    f(SlotRole.PHONE_EXTENSION),
                    f(SlotRole.WEBSITE),
                ),
            ),
            Section("security", (f(SlotRole.NEW_PASSWORD), f(SlotRole.ONE_TIME_CODE))),
            Section("extras", (f(SlotRole.MARKETING_OPT_IN),)),
        ),
    ),
    Template(
        "signup-08",
        Family.SIGNUP,
        (
            # An invitation flow: the code is entered before anything else, in
            # the account section rather than in a security section, which is the
            # structural difference from signup-07 and not a relabelling of it. A
            # street address and a typed country make it a second training home
            # for both starved address labels.
            Section(
                "account",
                (
                    f(SlotRole.EMAIL),
                    f(SlotRole.ONE_TIME_CODE),
                    f(SlotRole.NEW_PASSWORD),
                    f(SlotRole.NEW_PASSWORD_CONFIRM),
                ),
            ),
            Section("identity", (name_block("honorific"), f(SlotRole.NICKNAME))),
            Section("address", (address_block("street"), f(SlotRole.COUNTRY_TEXT))),
            Section("extras", (f(SlotRole.SEARCH), f(SlotRole.CONSENT))),
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
    Template(
        "address-06",
        Family.ADDRESS,
        (
            # The only address form with an honorific name block, a single street
            # line, a typed country, and a telephone split into a country code
            # and a national number. It is the training home of street-address.
            Section("identity", (name_block("honorific"),)),
            Section("address", (address_block("street"), f(SlotRole.COUNTRY_TEXT))),
            Section(
                "contact",
                (
                    f(SlotRole.EMAIL),
                    f(SlotRole.PHONE_COUNTRY_CODE),
                    f(SlotRole.PHONE_NATIONAL),
                ),
            ),
        ),
    ),
    Template(
        "address-07",
        Family.ADDRESS,
        (
            # An address book entry rather than a delivery address: it is titled
            # by a nickname and a company as well as by a person, which puts two
            # labels a name block never produces beside a full honorific block,
            # and it ends in free text that must not be declared.
            Section(
                "identity",
                (f(SlotRole.NICKNAME), name_block("honorific"), f(SlotRole.ORGANIZATION)),
            ),
            Section("address", (address_block("lines3"), f(SlotRole.COUNTRY_SELECT))),
            Section("contact", (f(SlotRole.PHONE),)),
            Section("extras", (f(SlotRole.COMMENTS), f(SlotRole.CONSENT))),
        ),
    ),
    Template(
        "address-08",
        Family.ADDRESS,
        (
            # A search box above the form, a split name, the whole address in one
            # composite textarea, and a typed country. The composite is the case
            # where the correct declaration is not the label the answer key
            # records, so a form built almost entirely out of one is worth having.
            Section("extras", (f(SlotRole.SEARCH),)),
            Section("identity", (name_block("split"),)),
            Section("address", (address_block("composite"), f(SlotRole.COUNTRY_TEXT))),
            Section("contact", (f(SlotRole.PHONE), f(SlotRole.EMAIL))),
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
    Template(
        "payment-06",
        Family.PAYMENT,
        (
            # A card payment that also collects who is paying and where they
            # live: the only payment form with a name block, and the only one
            # whose billing address is a composite textarea beside a typed
            # country. The expiry is the grouped pair of selects.
            Section("identity", (name_block("full"), f(SlotRole.EMAIL))),
            Section(
                "payment",
                (
                    f(SlotRole.CARD_HOLDER),
                    f(SlotRole.CARD_NUMBER),
                    f(SlotRole.CARD_EXPIRY_SPLIT_MONTH),
                    f(SlotRole.CARD_EXPIRY_SPLIT_YEAR),
                    f(SlotRole.CARD_SECURITY_CODE),
                    f(SlotRole.CARD_TYPE),
                ),
            ),
            Section("billing", (address_block("composite"), f(SlotRole.COUNTRY_TEXT)), _BILLING),
            Section("order", (f(SlotRole.AMOUNT),)),
        ),
    ),
    Template(
        "payment-07",
        Family.PAYMENT,
        (
            # A subscription: the amount and the coupon come first because the
            # page is selling a plan, the billing address is one composite
            # textarea rather than a set of lines, and the confirmation step is a
            # verification code in a section of its own.
            Section("order", (f(SlotRole.AMOUNT), f(SlotRole.COUPON))),
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
            Section("billing", (address_block("composite"), f(SlotRole.COUNTRY_SELECT)), _BILLING),
            Section("security", (f(SlotRole.ONE_TIME_CODE),)),
            Section("extras", (f(SlotRole.CONSENT),)),
        ),
    ),
    Template(
        "payment-08",
        Family.PAYMENT,
        (
            # The expiry as two plain numeric inputs rather than as two selects,
            # a full billing address block rather than a bare postal code, and a
            # verification code after it. Payment is the only family where a
            # whole address block is the exception rather than the rule.
            Section(
                "payment",
                (
                    f(SlotRole.CARD_HOLDER),
                    f(SlotRole.CARD_NUMBER),
                    f(SlotRole.CARD_EXPIRY_MONTH),
                    f(SlotRole.CARD_EXPIRY_YEAR),
                    f(SlotRole.CARD_SECURITY_CODE),
                ),
            ),
            Section("billing", (address_block("lines"), f(SlotRole.COUNTRY_SELECT)), _BILLING),
            Section("security", (f(SlotRole.ONE_TIME_CODE),)),
            Section("extras", (f(SlotRole.COMMENTS),)),
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
    Template(
        "login-06",
        Family.LOGIN,
        (
            # The ambiguity spec section 8.3 names, made explicit: this is the
            # only form in the corpus where a username field and an email field
            # sit side by side, so a classifier cannot resolve one by assuming
            # the other is absent. A verification code follows.
            Section(
                "account",
                (f(SlotRole.USERNAME), f(SlotRole.EMAIL), f(SlotRole.CURRENT_PASSWORD)),
            ),
            Section("security", (f(SlotRole.ONE_TIME_CODE),)),
        ),
    ),
    Template(
        "login-07",
        Family.LOGIN,
        (
            # A password change rather than a sign in: the current password and
            # the new pair are on one page, which is the only place in the corpus
            # where current-password and new-password have to be told apart from
            # each other rather than from everything else.
            Section("identity", (f(SlotRole.EMAIL),)),
            Section(
                "security",
                (
                    f(SlotRole.CURRENT_PASSWORD),
                    f(SlotRole.NEW_PASSWORD),
                    f(SlotRole.NEW_PASSWORD_CONFIRM),
                    f(SlotRole.ONE_TIME_CODE),
                ),
            ),
            Section("extras", (f(SlotRole.SEARCH),)),
        ),
    ),
    Template(
        "login-08",
        Family.LOGIN,
        (
            # A workspace sign in: the organization identifier is a real field
            # above the credentials, which is a login shape no other template
            # here carries and which puts an autofillable label in a family that
            # is otherwise credentials only.
            Section("identity", (f(SlotRole.ORGANIZATION), f(SlotRole.EMAIL))),
            Section("security", (f(SlotRole.CURRENT_PASSWORD), f(SlotRole.ONE_TIME_CODE))),
        ),
    ),
)

TEMPLATES: Final[dict[str, Template]] = {template.template_id: template for template in _TEMPLATES}


def templates_for(family: Family) -> tuple[Template, ...]:
    """Return the templates of one family, in declaration order."""
    return tuple(template for template in _TEMPLATES if template.family is family)


assert len(TEMPLATES) == len(_TEMPLATES), "template identifiers must be unique"
for _family in Family:
    assert len(templates_for(_family)) == TEMPLATES_PER_FAMILY, (
        f"{_family} must carry {TEMPLATES_PER_FAMILY} templates"
    )
