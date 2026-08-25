"""Seeded sample values (spec section 8.1 step 5, spec section 8.2).

Sample values are page content, never answer-key content and never classifier
input. They appear in three places: the order-summary block a checkout or
address page shows, the example values some placeholders carry, and the option
lists of a few selects. A form with no values in it reads like a grid of empty
boxes, and a corpus that reads like that is a corpus whose hostile tier is
easier than the real thing.

**Where Faker is used and where it is not.** Faker supplies names, streets,
cities, administrative areas, and company names, per spec section 8.2, seeded
from the same per-form value the numpy generator is seeded from. It does *not*
supply phone numbers or postal codes. Faker's phone providers emit numbers that
look dialable, and ground rule 10 asks for values a reviewer can see are
invented, so those come from a hand-authored per-locale pattern instead. Card
numbers come from the published test-card set and from nowhere else, so that no
generator path can emit a Luhn-valid live BIN.
"""

from __future__ import annotations

import string
from functools import cache
from typing import Final

import numpy as np
from faker import Faker

from autofill_audit.corpus.profiles import LocaleProfile
from autofill_audit.corpus.roles import ValueKind

__all__ = ["TEST_CARD_NUMBERS", "ValueProvider"]

TEST_CARD_NUMBERS: Final[tuple[str, ...]] = (
    "4242 4242 4242 4242",
    "5555 5555 5555 4444",
    "3782 822463 10005",
    "6011 1111 1111 1117",
)
"""The published payment-processor test numbers. Ground rule 10 names the first
of them; the rest are its siblings from the same published set."""

_DIGITS: Final[str] = "0123456789"
_UPPER: Final[str] = string.ascii_uppercase


@cache
def _faker_for(faker_locale: str) -> Faker:
    """Return a cached Faker for a locale.

    Cached because constructing a Faker loads its whole provider set, and the
    generator builds six hundred forms. Reseeding per form with
    ``seed_instance`` is what keeps that safe: the sequence of draws inside one
    form is fixed, so a cached instance reseeded at the top of each form gives
    the same values a fresh instance would.
    """
    return Faker(faker_locale)


class ValueProvider:
    """Seeded sample values for one form.

    One instance per generated form. Constructing it reseeds the shared Faker,
    so every draw made through it belongs to that form and to no other.
    """

    __slots__ = ("_faker", "_profile", "_rng")

    def __init__(self, profile: LocaleProfile, seed: int) -> None:
        self._profile = profile
        self._faker = _faker_for(profile.faker_locale)
        self._faker.seed_instance(seed)
        self._rng = np.random.default_rng(seed)

    def pattern(self, template: str) -> str:
        """Expand a hand-authored value pattern.

        ``#`` becomes a digit and ``@`` becomes an uppercase letter. Every other
        character is a literal, which is what carries the locale's shape: the
        spaces in a British postcode and the hyphen in a Japanese postal code
        are part of what the field looks like.
        """
        out: list[str] = []
        for character in template:
            if character == "#":
                out.append(_DIGITS[int(self._rng.integers(0, len(_DIGITS)))])
            elif character == "@":
                out.append(_UPPER[int(self._rng.integers(0, len(_UPPER)))])
            else:
                out.append(character)
        return "".join(out)

    def choice(self, options: tuple[str, ...]) -> str:
        """Pick one option, seeded."""
        return options[int(self._rng.integers(0, len(options)))]

    def card_number(self) -> str:
        """Return one of the published test card numbers."""
        return self.choice(TEST_CARD_NUMBERS)

    def value_for(self, kind: ValueKind) -> str | None:
        """Return a sample value for a role's value kind, or None when it has none."""
        faker = self._faker
        profile = self._profile
        match kind:
            case ValueKind.NONE:
                return None
            case ValueKind.GIVEN_NAME:
                return str(faker.first_name())
            case ValueKind.FAMILY_NAME:
                return str(faker.last_name())
            case ValueKind.MIDDLE_INITIAL:
                return str(faker.first_name())[:1]
            case ValueKind.FULL_NAME:
                return f"{faker.first_name()} {faker.last_name()}"
            case ValueKind.KANA_GIVEN:
                return str(faker.first_kana_name())
            case ValueKind.KANA_FAMILY:
                return str(faker.last_kana_name())
            case ValueKind.HONORIFIC:
                return self.choice(profile.options["titles"])
            case ValueKind.SUFFIX:
                return str(faker.suffix())
            case ValueKind.NICKNAME:
                return str(faker.user_name())
            case ValueKind.EMAIL:
                return f"{faker.user_name()}@example.com"
            case ValueKind.PHONE | ValueKind.PHONE_NATIONAL:
                return self.pattern(profile.phone_pattern)
            case ValueKind.EXTENSION:
                return self.pattern("####")
            case ValueKind.WEBSITE:
                return "https://example.com"
            case ValueKind.ORGANIZATION:
                return str(faker.company())
            case ValueKind.STREET:
                return str(faker.street_address()).replace("\n", ", ")
            case ValueKind.SECONDARY:
                return self.pattern("Unit ##")
            case ValueKind.BUILDING:
                return self.pattern("Block @")
            case ValueKind.CITY:
                return str(faker.city())
            case ValueKind.ADMIN_AREA:
                return self.choice(profile.options["admin_areas"])
            case ValueKind.POSTAL_CODE:
                return self.pattern(profile.postal_pattern)
            case ValueKind.COUNTRY:
                return profile.country_name
            case ValueKind.FULL_ADDRESS:
                street = str(faker.street_address()).replace("\n", ", ")
                return f"{street}, {faker.city()}, {self.pattern(profile.postal_pattern)}"
            case ValueKind.CARD_NUMBER:
                return self.card_number()
            case ValueKind.CARD_EXPIRY:
                return self.pattern("##/##")
            case ValueKind.CARD_MONTH:
                return self.pattern("##")
            case ValueKind.CARD_YEAR:
                return self.pattern("20##")
            case ValueKind.CARD_SECURITY_CODE:
                return self.pattern("###")
            case ValueKind.AMOUNT:
                return self.pattern("##.00")
            case ValueKind.USERNAME:
                return str(faker.user_name())
            case ValueKind.PASSWORD:
                return None
            case ValueKind.OTP:
                return self.pattern("######")
            case ValueKind.BIRTH_DATE:
                return self.pattern("19##-0#-1#")
            case ValueKind.FREE_TEXT:
                return None
        raise AssertionError(f"unhandled value kind {kind!r}")

    def summary(self) -> dict[str, str]:
        """Return the synthetic recipient block a checkout or address page shows.

        This is the only place a whole invented person appears, and it exists
        because spec section 9.2 lists preceding text and section headings as
        signals. A page whose only text is its labels would make the context
        signal untestable.
        """
        profile = self._profile
        street = str(self._faker.street_address()).replace("\n", ", ")
        return {
            "name": f"{self._faker.first_name()} {self._faker.last_name()}",
            "street": street,
            "city": str(self._faker.city()),
            "postal_code": self.pattern(profile.postal_pattern),
            "phone": self.pattern(profile.phone_pattern),
            "country": profile.country_name,
        }
