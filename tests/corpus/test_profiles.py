"""Locale profiles: the structural claims, not the spellings.

Spec section 8.1 says a generator that only swaps label strings across locales
produces a corpus that tests translation rather than localisation. These tests
are the mechanical version of that sentence: they assert the profiles differ in
*shape*, and would fail if somebody replaced the tables with six translations of
one layout.
"""

from __future__ import annotations

import pytest

from autofill_audit.corpus.profiles import LOCALE_IDS, load_profile, profiles
from autofill_audit.corpus.roles import ROLE_SPECS, SlotRole


@pytest.mark.parametrize("locale", LOCALE_IDS)
def test_every_role_has_a_label(locale: str) -> None:
    profile = load_profile(locale)
    missing = [role.value for role in SlotRole if role not in profile.labels]
    assert missing == []


@pytest.mark.parametrize("locale", LOCALE_IDS)
def test_labels_are_non_empty(locale: str) -> None:
    profile = load_profile(locale)
    blank = [role.value for role, text in profile.labels.items() if not text.strip()]
    assert blank == []


@pytest.mark.parametrize("locale", LOCALE_IDS)
def test_every_block_style_exists(locale: str) -> None:
    profile = load_profile(locale)
    assert set(profile.name_blocks) == {"full", "split", "split_middle", "honorific"}
    assert set(profile.address_blocks) == {"lines", "lines3", "street", "composite"}


@pytest.mark.parametrize("locale", LOCALE_IDS)
def test_option_tables_are_present(locale: str) -> None:
    profile = load_profile(locale)
    assert len(profile.options["months"]) == 12
    for key in ("titles", "sex_options", "card_types", "admin_areas"):
        assert profile.options[key], key
    for key in ("countries", "phone_country_codes"):
        assert profile.option_pairs[key], key


def test_unknown_locale_raises() -> None:
    with pytest.raises(KeyError, match="unknown locale"):
        load_profile("xx-XX")


def test_address_order_is_genuinely_structural() -> None:
    """The six locales must not all compose an address the same way."""
    orders = {profile.locale: profile.address_blocks["lines"] for profile in profiles()}
    assert len(set(orders.values())) > 1


def test_german_and_french_put_the_postal_code_before_the_town() -> None:
    for locale in ("de-DE", "fr-FR"):
        order = load_profile(locale).address_blocks["lines"]
        assert order.index(SlotRole.POSTAL_CODE) < order.index(SlotRole.CITY)


def test_american_and_british_put_the_postal_code_last() -> None:
    for locale in ("en-US", "en-GB"):
        order = load_profile(locale).address_blocks["lines"]
        assert order[-1] is SlotRole.POSTAL_CODE


def test_japanese_puts_the_postal_code_first_and_splits_the_name_into_kana() -> None:
    profile = load_profile("ja-JP")
    assert profile.address_blocks["lines"][0] is SlotRole.POSTAL_CODE
    split = profile.name_blocks["split"]
    assert SlotRole.FAMILY_NAME_KANA in split
    assert SlotRole.GIVEN_NAME_KANA in split
    # Family name before given name, which is the convention that makes a
    # Japanese form structurally different rather than merely translated.
    assert split.index(SlotRole.FAMILY_NAME) < split.index(SlotRole.GIVEN_NAME)


def test_only_japanese_carries_kana_name_fields() -> None:
    for profile in profiles():
        has_kana = SlotRole.FAMILY_NAME_KANA in profile.name_blocks["split"]
        assert has_kana == (profile.locale == "ja-JP")


def test_german_and_french_address_blocks_carry_no_administrative_area() -> None:
    """A real German address form has no state field. Emitting one would make
    the corpus assert a convention that does not exist."""
    for locale in ("de-DE", "fr-FR"):
        assert SlotRole.ADMIN_AREA not in load_profile(locale).address_blocks["lines"]


def test_nigerian_postal_code_is_frequently_absent() -> None:
    """Spec section 8.1 names this one specifically."""
    profile = load_profile("en-NG")
    assert 0.0 < profile.presence_of(SlotRole.POSTAL_CODE) < 1.0
    assert profile.presence_of(SlotRole.CITY) == 1.0


def test_postal_code_identifiers_differ_across_english_locales() -> None:
    """The cross-locale claim rests on identifiers as much as on labels, because
    the hostile tier removes the labels and leaves the identifiers."""
    stems = {
        locale: load_profile(locale).identifier_for(
            SlotRole.POSTAL_CODE, ROLE_SPECS[SlotRole.POSTAL_CODE].identifier
        )
        for locale in ("en-US", "en-GB", "de-DE", "fr-FR")
    }
    assert stems["en-US"] != stems["en-GB"]
    assert stems["de-DE"] != stems["en-US"]
    assert len(set(stems.values())) == 4


def test_identifier_falls_back_to_the_role_stem() -> None:
    profile = load_profile("en-US")
    assert profile.identifier_for(SlotRole.NICKNAME, "displayname") == "displayname"


def test_placeholder_is_optional() -> None:
    profile = load_profile("en-US")
    assert profile.placeholder_for(SlotRole.EMAIL) is not None
    assert profile.placeholder_for(SlotRole.UNDETERMINABLE) is None


def test_section_headings_and_page_titles_resolve() -> None:
    profile = load_profile("de-DE")
    assert profile.section_heading("shipping")
    assert profile.page_title("checkout")


def test_profiles_are_cached() -> None:
    assert load_profile("en-US") is load_profile("en-US")


def test_profiles_returns_every_locale() -> None:
    assert tuple(profile.locale for profile in profiles()) == LOCALE_IDS
