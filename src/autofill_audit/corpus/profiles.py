"""Locale profiles: the structural half of localisation, not the lexical half.

Spec section 8.1 is explicit that a generator which only swaps label strings
across locales produces a corpus that tests translation rather than
localisation, and that the multilingual claim of spec section 5.3 would be
untestable on such a corpus. So a profile here carries four kinds of fact, and
only the first is vocabulary:

1. **Label, placeholder, and identifier strings.** German forms say *PLZ* and
   name the field ``plz``; British forms say *Postcode*; American forms say *ZIP
   code* and name the field ``zip``. Identifier stems matter as much as visible
   labels, because the hostile tier removes the labels and leaves the
   identifiers.
2. **Which slots exist.** German and French address blocks carry no
   administrative-area field at all. Nigerian addresses frequently carry no
   postal code, which the profile expresses as a presence probability rather
   than as an absence, because "frequently" is the honest shape of that fact.
3. **What order they appear in.** Japanese addresses run postal code, then
   prefecture, then municipality, then the street line. German addresses put the
   postal code before the town. American addresses put the postal code last.
4. **How names decompose.** Japanese forms split a name into family and given
   in that order and then repeat the pair as kana fields, which is a structural
   convention with no equivalent in the other five locales.

Profiles are committed JSON under ``locales/`` so that a reviewer can read what
a locale claims without reading Python, and so that adding a seventh locale is a
data change rather than a code change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Final

from autofill_audit.corpus.roles import SlotRole

__all__ = [
    "LOCALE_IDS",
    "LocaleProfile",
    "load_profile",
    "profiles",
]

LOCALE_IDS: Final[tuple[str, ...]] = (
    "en-US",
    "en-GB",
    "de-DE",
    "fr-FR",
    "ja-JP",
    "en-NG",
)
"""The six locales of the realised grid, in a fixed order.

``fr-FR`` is the held-out locale (``docs/adr/0005-held-out-locale.md``). It is
listed here like any other because the generator emits it like any other; the
split, not the generator, is what holds it out."""

_PACKAGE = "autofill_audit.corpus"
_TABLE_DIRECTORY = "locales"
"""The tables live in a data directory beside this module rather than in a
subpackage. It is named ``locales`` because spec section 6 names it that, which
is also why this module is ``profiles.py``: a module named ``locales.py`` would
shadow the directory on import and silently resolve package data one level too
high."""


@dataclass(frozen=True, slots=True)
class LocaleProfile:
    """One locale's structural and lexical conventions."""

    locale: str
    html_lang: str
    faker_locale: str
    country_code: str
    country_name: str
    phone_country_code: str
    phone_pattern: str
    """A hand-authored fictional phone shape. ``#`` is replaced by a seeded
    digit. Hand-authored rather than taken from Faker because Faker's phone
    providers emit dialable-looking numbers and ground rule 10 wants values a
    reviewer can see are invented."""
    postal_pattern: str
    """Same convention as ``phone_pattern``, with ``@`` for an uppercase letter,
    which the British and Canadian postal formats need."""
    name_blocks: dict[str, tuple[SlotRole, ...]]
    address_blocks: dict[str, tuple[SlotRole, ...]]
    row_groups: tuple[tuple[SlotRole, ...], ...]
    """Roles that this locale renders side by side on one row. German puts the
    postal code and the town on one line; American forms put city, state, and
    ZIP on one line. This changes the DOM shape, and therefore the selector
    paths, which is why it is a profile fact and not a stylesheet fact."""
    optional_roles: dict[SlotRole, float]
    labels: dict[SlotRole, str]
    placeholders: dict[SlotRole, str]
    identifiers: dict[SlotRole, str]
    sections: dict[str, str]
    page_titles: dict[str, str]
    summary: dict[str, str]
    options: dict[str, tuple[str, ...]]
    option_pairs: dict[str, tuple[tuple[str, str], ...]]

    def label_for(self, role: SlotRole) -> str:
        """Return this locale's visible label text for ``role``."""
        return self.labels[role]

    def placeholder_for(self, role: SlotRole) -> str | None:
        """Return this locale's placeholder text for ``role``, if it has one."""
        return self.placeholders.get(role)

    def identifier_for(self, role: SlotRole, fallback: str) -> str:
        """Return this locale's identifier stem for ``role``.

        ``fallback`` is the role specification's locale-agnostic stem, used
        wherever the locale has no word of its own worth carrying.
        """
        return self.identifiers.get(role, fallback)

    def presence_of(self, role: SlotRole) -> float:
        """Return the probability that ``role`` is present in an expanded block."""
        return self.optional_roles.get(role, 1.0)

    def section_heading(self, key: str) -> str:
        """Return this locale's heading text for a section key."""
        return self.sections[key]

    def page_title(self, family: str) -> str:
        """Return this locale's page title for a form family."""
        return self.page_titles[family]


def _roles(values: list[str]) -> tuple[SlotRole, ...]:
    return tuple(SlotRole(value) for value in values)


def _role_map(raw: dict[str, str]) -> dict[SlotRole, str]:
    return {SlotRole(key): value for key, value in raw.items()}


def _parse(raw: dict[str, Any]) -> LocaleProfile:
    """Build a profile from its committed JSON document."""
    blocks: dict[str, Any] = raw["blocks"]
    text: dict[str, Any] = raw["text"]
    return LocaleProfile(
        locale=raw["locale"],
        html_lang=raw["html_lang"],
        faker_locale=raw["faker_locale"],
        country_code=raw["country_code"],
        country_name=raw["country_name"],
        phone_country_code=raw["phone_country_code"],
        phone_pattern=raw["phone_pattern"],
        postal_pattern=raw["postal_pattern"],
        name_blocks={name: _roles(value) for name, value in blocks["name"].items()},
        address_blocks={name: _roles(value) for name, value in blocks["address"].items()},
        row_groups=tuple(_roles(group) for group in blocks["rows"]),
        optional_roles={SlotRole(key): float(value) for key, value in blocks["optional"].items()},
        labels=_role_map(text["labels"]),
        placeholders=_role_map(text["placeholders"]),
        identifiers=_role_map(text["identifiers"]),
        sections=dict(text["sections"]),
        page_titles=dict(text["page_titles"]),
        summary=dict(text["summary"]),
        options={name: tuple(value) for name, value in raw["options"].items()},
        option_pairs={
            name: tuple((pair[0], pair[1]) for pair in value)
            for name, value in raw["option_pairs"].items()
        },
    )


@cache
def load_profile(locale: str) -> LocaleProfile:
    """Load and cache one locale profile by its identifier.

    Raises:
        KeyError: when ``locale`` is not one of ``LOCALE_IDS``.
    """
    if locale not in LOCALE_IDS:
        raise KeyError(f"unknown locale {locale!r}; known locales are {', '.join(LOCALE_IDS)}")
    table = resources.files(_PACKAGE).joinpath(_TABLE_DIRECTORY, f"{locale}.json")
    document = table.read_text(encoding="utf-8")
    parsed: dict[str, Any] = json.loads(document)
    return _parse(parsed)


def profiles() -> tuple[LocaleProfile, ...]:
    """Return every locale profile, in ``LOCALE_IDS`` order."""
    return tuple(load_profile(locale) for locale in LOCALE_IDS)
