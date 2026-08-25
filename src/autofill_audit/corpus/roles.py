"""Slot roles: the semantic vocabulary the generator composes forms out of.

A *role* is what a slot means on a page. A *label* is the ground truth an answer
key records for the control that role produces. The two are not the same thing
and collapsing them would lose information the corpus exists to carry.

Three cases make the distinction load bearing.

- Several roles share one label. A card expiry month rendered as one half of a
  two-select pair and a card expiry month rendered as a lone text input are
  different page facts with different fixes, and the taxonomy separates them
  (``CC_EXP_SPLIT_MONTH`` against the specification's month token). A given name
  written in kanji and the same given name written in kana are two controls on
  one Japanese form, both of which a browser fills from the same token.
- One label covers many unrelated roles. Every search box, quantity spinner,
  coupon field, comment area, and consent checkbox is ``NOT_AUTOFILLABLE``, and
  a generator that could not tell them apart would emit five copies of one form
  control and call it variety.
- The label a correct page *declares* is not always the label the answer key
  records. A single MM/YY input is a ``COMPOSITE_UNSPLIT`` control whose correct
  declaration is the combined expiry token. The role knows both.

Every role's ground-truth label comes from ``taxonomy.Label`` and nothing here
spells a label out as a string, so the one-definition rule of ground rule 6
holds through this layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from autofill_audit.taxonomy import Label, declaration_for

__all__ = [
    "ROLE_SPECS",
    "Control",
    "OptionKind",
    "RoleSpec",
    "SlotRole",
    "ValueKind",
    "spec_for",
]


class Control(StrEnum):
    """The HTML control a role renders as."""

    INPUT = "input"
    SELECT = "select"
    TEXTAREA = "textarea"


class OptionKind(StrEnum):
    """The shape of a ``<select>`` element's option list.

    The extractor collects option labels and values as a signal (spec 9.2), so
    the option list is part of what a role means, not decoration on top of it.
    """

    NONE = "none"
    MONTHS = "months"
    YEARS = "years"
    COUNTRIES = "countries"
    CARD_TYPES = "card_types"
    TITLES = "titles"
    SEX_OPTIONS = "sex_options"
    PHONE_COUNTRY_CODES = "phone_country_codes"
    ADMIN_AREAS = "admin_areas"


class ValueKind(StrEnum):
    """Which seeded provider supplies a plausible sample value for a role.

    Sample values never reach a classifier: they appear in placeholder text and
    in the page's order-summary context block, both of which are page content
    rather than answer-key content. They exist so that a generated form reads
    like a form rather than like a grid of empty boxes.
    """

    NONE = "none"
    GIVEN_NAME = "given_name"
    FAMILY_NAME = "family_name"
    MIDDLE_INITIAL = "middle_initial"
    FULL_NAME = "full_name"
    KANA_GIVEN = "kana_given"
    KANA_FAMILY = "kana_family"
    HONORIFIC = "honorific"
    SUFFIX = "suffix"
    NICKNAME = "nickname"
    EMAIL = "email"
    PHONE = "phone"
    PHONE_NATIONAL = "phone_national"
    EXTENSION = "extension"
    WEBSITE = "website"
    ORGANIZATION = "organization"
    STREET = "street"
    SECONDARY = "secondary"
    BUILDING = "building"
    CITY = "city"
    ADMIN_AREA = "admin_area"
    POSTAL_CODE = "postal_code"
    COUNTRY = "country"
    FULL_ADDRESS = "full_address"
    CARD_NUMBER = "card_number"
    CARD_EXPIRY = "card_expiry"
    CARD_MONTH = "card_month"
    CARD_YEAR = "card_year"
    CARD_SECURITY_CODE = "card_security_code"
    AMOUNT = "amount"
    USERNAME = "username"
    PASSWORD = "password"
    OTP = "otp"
    BIRTH_DATE = "birth_date"
    FREE_TEXT = "free_text"


class SlotRole(StrEnum):
    """Every semantic role a template may ask for.

    Values are snake_case so that no role value can collide with a WHATWG
    autofill token, which is hyphenated. That is not cosmetic: the reachability
    check fails the build on a label string written outside the taxonomy, and a
    role vocabulary that reused the token spellings would either trip that check
    or force it to be weakened.
    """

    HONORIFIC_PREFIX = "honorific_prefix"
    HONORIFIC_SUFFIX = "honorific_suffix"
    GIVEN_NAME = "given_name"
    ADDITIONAL_NAME = "additional_name"
    FAMILY_NAME = "family_name"
    GIVEN_NAME_KANA = "given_name_kana"
    FAMILY_NAME_KANA = "family_name_kana"
    FULL_NAME = "full_name"
    NICKNAME = "nickname"

    EMAIL = "email_address"
    PHONE = "phone"
    PHONE_COUNTRY_CODE = "phone_country_code"
    PHONE_NATIONAL = "phone_national"
    PHONE_EXTENSION = "phone_extension"
    WEBSITE = "website"

    STREET_ADDRESS = "street_address"
    ADDRESS_LINE_1 = "address_line_1"
    ADDRESS_LINE_2 = "address_line_2"
    ADDRESS_LINE_3 = "address_line_3"
    CITY = "city"
    ADMIN_AREA = "admin_area"
    POSTAL_CODE = "postal_code"
    COUNTRY_SELECT = "country_select"
    COUNTRY_TEXT = "country_text"
    ORGANIZATION = "organization"
    FULL_ADDRESS_COMPOSITE = "full_address_composite"

    CARD_HOLDER = "card_holder"
    CARD_NUMBER = "card_number"
    CARD_EXPIRY = "card_expiry"
    CARD_EXPIRY_MONTH = "card_expiry_month"
    CARD_EXPIRY_YEAR = "card_expiry_year"
    CARD_EXPIRY_SPLIT_MONTH = "card_expiry_split_month"
    CARD_EXPIRY_SPLIT_YEAR = "card_expiry_split_year"
    CARD_EXPIRY_COMPOSITE = "card_expiry_composite"
    CARD_SECURITY_CODE = "card_security_code"
    CARD_TYPE = "card_type"
    AMOUNT = "amount"

    USERNAME = "username"
    NEW_PASSWORD = "new_password"
    NEW_PASSWORD_CONFIRM = "new_password_confirm"
    CURRENT_PASSWORD = "current_password"
    ONE_TIME_CODE = "one_time_code"
    BIRTH_DATE = "birth_date"
    SEX = "sex"

    SEARCH = "search"
    QUANTITY = "quantity"
    COUPON = "coupon"
    COMMENTS = "comments"
    CONSENT = "consent"
    MARKETING_OPT_IN = "marketing_opt_in"

    UNDETERMINABLE = "undeterminable"


@dataclass(frozen=True, slots=True)
class RoleSpec:
    """Everything the renderer and the answer key need about one role."""

    role: SlotRole
    label: Label
    control: Control
    input_type: str | None = None
    inputmode: str | None = None
    option_kind: OptionKind = OptionKind.NONE
    value_kind: ValueKind = ValueKind.NONE
    identifier: str = ""
    """The locale-agnostic identifier stem used for ``name`` and ``id`` when the
    locale profile has no localised stem of its own."""
    maxlength: int | None = None
    autocomplete_expected: bool = True
    """False for roles a correct page declares nothing on. Kept separate from
    ``declaration`` being None so that ``COMPOSITE_UNSPLIT``, which does expect a
    declaration, is not confused with a search box, which does not."""
    declaration_override: Label | None = None
    """Set only where the label alone does not settle what a correct page
    declares, which is exactly the two composite roles."""

    @property
    def declaration(self) -> Label | None:
        """The token a correct page declares on this role's control."""
        if self.declaration_override is not None:
            return self.declaration_override
        return declaration_for(self.label)


def _spec(
    role: SlotRole,
    label: Label,
    identifier: str,
    *,
    control: Control = Control.INPUT,
    input_type: str | None = "text",
    inputmode: str | None = None,
    option_kind: OptionKind = OptionKind.NONE,
    value_kind: ValueKind = ValueKind.NONE,
    maxlength: int | None = None,
    autocomplete_expected: bool = True,
    declaration_override: Label | None = None,
) -> RoleSpec:
    """Build one role specification. Keyword heavy on purpose: a positional
    argument list this long is unreadable at the call site."""
    return RoleSpec(
        role=role,
        label=label,
        control=control,
        input_type=input_type,
        inputmode=inputmode,
        option_kind=option_kind,
        value_kind=value_kind,
        identifier=identifier,
        maxlength=maxlength,
        autocomplete_expected=autocomplete_expected,
        declaration_override=declaration_override,
    )


_SPECS: Final[tuple[RoleSpec, ...]] = (
    _spec(
        SlotRole.HONORIFIC_PREFIX,
        Label.HONORIFIC_PREFIX,
        "title",
        control=Control.SELECT,
        input_type=None,
        option_kind=OptionKind.TITLES,
        value_kind=ValueKind.HONORIFIC,
    ),
    _spec(
        SlotRole.HONORIFIC_SUFFIX,
        Label.HONORIFIC_SUFFIX,
        "suffix",
        value_kind=ValueKind.SUFFIX,
        maxlength=12,
    ),
    _spec(SlotRole.GIVEN_NAME, Label.GIVEN_NAME, "firstname", value_kind=ValueKind.GIVEN_NAME),
    _spec(
        SlotRole.ADDITIONAL_NAME,
        Label.ADDITIONAL_NAME,
        "middlename",
        value_kind=ValueKind.MIDDLE_INITIAL,
    ),
    _spec(SlotRole.FAMILY_NAME, Label.FAMILY_NAME, "lastname", value_kind=ValueKind.FAMILY_NAME),
    _spec(
        SlotRole.GIVEN_NAME_KANA,
        Label.GIVEN_NAME,
        "firstnamekana",
        value_kind=ValueKind.KANA_GIVEN,
    ),
    _spec(
        SlotRole.FAMILY_NAME_KANA,
        Label.FAMILY_NAME,
        "lastnamekana",
        value_kind=ValueKind.KANA_FAMILY,
    ),
    _spec(SlotRole.FULL_NAME, Label.NAME, "fullname", value_kind=ValueKind.FULL_NAME),
    _spec(SlotRole.NICKNAME, Label.NICKNAME, "displayname", value_kind=ValueKind.NICKNAME),
    _spec(
        SlotRole.EMAIL,
        Label.EMAIL,
        "email",
        input_type="email",
        inputmode="email",
        value_kind=ValueKind.EMAIL,
    ),
    _spec(
        SlotRole.PHONE,
        Label.TEL,
        "phone",
        input_type="tel",
        inputmode="tel",
        value_kind=ValueKind.PHONE,
    ),
    _spec(
        SlotRole.PHONE_COUNTRY_CODE,
        Label.TEL_COUNTRY_CODE,
        "phonecc",
        control=Control.SELECT,
        input_type=None,
        option_kind=OptionKind.PHONE_COUNTRY_CODES,
    ),
    _spec(
        SlotRole.PHONE_NATIONAL,
        Label.TEL_NATIONAL,
        "phonenumber",
        input_type="tel",
        inputmode="tel",
        value_kind=ValueKind.PHONE_NATIONAL,
    ),
    _spec(
        SlotRole.PHONE_EXTENSION,
        Label.TEL_EXTENSION,
        "phoneext",
        inputmode="numeric",
        value_kind=ValueKind.EXTENSION,
        maxlength=6,
    ),
    _spec(
        SlotRole.WEBSITE,
        Label.URL,
        "website",
        input_type="url",
        inputmode="url",
        value_kind=ValueKind.WEBSITE,
    ),
    _spec(
        SlotRole.STREET_ADDRESS,
        Label.STREET_ADDRESS,
        "street",
        value_kind=ValueKind.STREET,
    ),
    _spec(SlotRole.ADDRESS_LINE_1, Label.ADDRESS_LINE1, "address1", value_kind=ValueKind.STREET),
    _spec(
        SlotRole.ADDRESS_LINE_2,
        Label.ADDRESS_LINE2,
        "address2",
        value_kind=ValueKind.SECONDARY,
    ),
    _spec(
        SlotRole.ADDRESS_LINE_3,
        Label.ADDRESS_LINE3,
        "address3",
        value_kind=ValueKind.BUILDING,
    ),
    _spec(SlotRole.CITY, Label.ADDRESS_LEVEL2, "city", value_kind=ValueKind.CITY),
    _spec(
        SlotRole.ADMIN_AREA,
        Label.ADDRESS_LEVEL1,
        "region",
        control=Control.SELECT,
        input_type=None,
        option_kind=OptionKind.ADMIN_AREAS,
        value_kind=ValueKind.ADMIN_AREA,
    ),
    _spec(
        SlotRole.POSTAL_CODE,
        Label.POSTAL_CODE,
        "postcode",
        inputmode="numeric",
        value_kind=ValueKind.POSTAL_CODE,
        maxlength=10,
    ),
    _spec(
        SlotRole.COUNTRY_SELECT,
        Label.COUNTRY,
        "country",
        control=Control.SELECT,
        input_type=None,
        option_kind=OptionKind.COUNTRIES,
        value_kind=ValueKind.COUNTRY,
    ),
    _spec(
        SlotRole.COUNTRY_TEXT,
        Label.COUNTRY_NAME,
        "countryname",
        value_kind=ValueKind.COUNTRY,
    ),
    _spec(
        SlotRole.ORGANIZATION,
        Label.ORGANIZATION,
        "company",
        value_kind=ValueKind.ORGANIZATION,
    ),
    _spec(
        SlotRole.FULL_ADDRESS_COMPOSITE,
        Label.COMPOSITE_UNSPLIT,
        "fulladdress",
        control=Control.TEXTAREA,
        input_type=None,
        value_kind=ValueKind.FULL_ADDRESS,
        declaration_override=Label.STREET_ADDRESS,
    ),
    _spec(SlotRole.CARD_HOLDER, Label.CC_NAME, "cardholder", value_kind=ValueKind.FULL_NAME),
    _spec(
        SlotRole.CARD_NUMBER,
        Label.CC_NUMBER,
        "cardnumber",
        inputmode="numeric",
        value_kind=ValueKind.CARD_NUMBER,
        maxlength=19,
    ),
    _spec(
        SlotRole.CARD_EXPIRY,
        Label.CC_EXP,
        "cardexpiry",
        input_type="month",
        value_kind=ValueKind.CARD_EXPIRY,
    ),
    _spec(
        SlotRole.CARD_EXPIRY_MONTH,
        Label.CC_EXP_MONTH,
        "cardexpmonth",
        inputmode="numeric",
        value_kind=ValueKind.CARD_MONTH,
        maxlength=2,
    ),
    _spec(
        SlotRole.CARD_EXPIRY_YEAR,
        Label.CC_EXP_YEAR,
        "cardexpyear",
        inputmode="numeric",
        value_kind=ValueKind.CARD_YEAR,
        maxlength=4,
    ),
    _spec(
        SlotRole.CARD_EXPIRY_SPLIT_MONTH,
        Label.CC_EXP_SPLIT_MONTH,
        "expmonth",
        control=Control.SELECT,
        input_type=None,
        option_kind=OptionKind.MONTHS,
    ),
    _spec(
        SlotRole.CARD_EXPIRY_SPLIT_YEAR,
        Label.CC_EXP_SPLIT_YEAR,
        "expyear",
        control=Control.SELECT,
        input_type=None,
        option_kind=OptionKind.YEARS,
    ),
    _spec(
        SlotRole.CARD_EXPIRY_COMPOSITE,
        Label.COMPOSITE_UNSPLIT,
        "expdate",
        inputmode="numeric",
        value_kind=ValueKind.CARD_EXPIRY,
        maxlength=5,
        declaration_override=Label.CC_EXP,
    ),
    _spec(
        SlotRole.CARD_SECURITY_CODE,
        Label.CC_CSC,
        "securitycode",
        inputmode="numeric",
        value_kind=ValueKind.CARD_SECURITY_CODE,
        maxlength=4,
    ),
    _spec(
        SlotRole.CARD_TYPE,
        Label.CC_TYPE,
        "cardtype",
        control=Control.SELECT,
        input_type=None,
        option_kind=OptionKind.CARD_TYPES,
    ),
    _spec(
        SlotRole.AMOUNT,
        Label.TRANSACTION_AMOUNT,
        "amount",
        input_type="number",
        inputmode="decimal",
        value_kind=ValueKind.AMOUNT,
    ),
    _spec(SlotRole.USERNAME, Label.USERNAME, "username", value_kind=ValueKind.USERNAME),
    _spec(
        SlotRole.NEW_PASSWORD,
        Label.NEW_PASSWORD,
        "newpassword",
        input_type="password",
        value_kind=ValueKind.PASSWORD,
    ),
    _spec(
        SlotRole.NEW_PASSWORD_CONFIRM,
        Label.NEW_PASSWORD,
        "confirmpassword",
        input_type="password",
        value_kind=ValueKind.PASSWORD,
    ),
    _spec(
        SlotRole.CURRENT_PASSWORD,
        Label.CURRENT_PASSWORD,
        "password",
        input_type="password",
        value_kind=ValueKind.PASSWORD,
    ),
    _spec(
        SlotRole.ONE_TIME_CODE,
        Label.ONE_TIME_CODE,
        "verificationcode",
        inputmode="numeric",
        value_kind=ValueKind.OTP,
        maxlength=6,
    ),
    _spec(
        SlotRole.BIRTH_DATE,
        Label.BDAY,
        "birthdate",
        input_type="date",
        value_kind=ValueKind.BIRTH_DATE,
    ),
    _spec(
        SlotRole.SEX,
        Label.SEX,
        "gender",
        control=Control.SELECT,
        input_type=None,
        option_kind=OptionKind.SEX_OPTIONS,
    ),
    _spec(
        SlotRole.SEARCH,
        Label.NOT_AUTOFILLABLE,
        "sitesearch",
        input_type="search",
        inputmode="search",
        value_kind=ValueKind.FREE_TEXT,
        autocomplete_expected=False,
    ),
    _spec(
        SlotRole.QUANTITY,
        Label.NOT_AUTOFILLABLE,
        "quantity",
        input_type="number",
        inputmode="numeric",
        option_kind=OptionKind.NONE,
        autocomplete_expected=False,
    ),
    _spec(
        SlotRole.COUPON,
        Label.NOT_AUTOFILLABLE,
        "promocode",
        value_kind=ValueKind.FREE_TEXT,
        maxlength=16,
        autocomplete_expected=False,
    ),
    _spec(
        SlotRole.COMMENTS,
        Label.NOT_AUTOFILLABLE,
        "ordernotes",
        control=Control.TEXTAREA,
        input_type=None,
        value_kind=ValueKind.FREE_TEXT,
        autocomplete_expected=False,
    ),
    _spec(
        SlotRole.CONSENT,
        Label.NOT_AUTOFILLABLE,
        "termsaccepted",
        input_type="checkbox",
        autocomplete_expected=False,
    ),
    _spec(
        SlotRole.MARKETING_OPT_IN,
        Label.NOT_AUTOFILLABLE,
        "newsletter",
        input_type="checkbox",
        autocomplete_expected=False,
    ),
    _spec(
        SlotRole.UNDETERMINABLE,
        Label.UNKNOWN,
        "value",
        autocomplete_expected=False,
    ),
)

ROLE_SPECS: Final[dict[SlotRole, RoleSpec]] = {spec.role: spec for spec in _SPECS}


def spec_for(role: SlotRole) -> RoleSpec:
    """Return the specification for ``role``."""
    return ROLE_SPECS[role]


assert len(ROLE_SPECS) == len(SlotRole), "every role needs exactly one specification"
