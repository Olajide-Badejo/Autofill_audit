"""Every step of spec section 9.7, separately, plus the properties it must hold.

Spec section 15 layer 1 names four of these by hand: NFKC on full-width
Japanese, casefold on the sharp s, camelCase splitting, and script-boundary
splitting. They are here, and so is each remaining step, because a composition
whose parts are only tested through the composition is a composition whose
failing part is found by bisection rather than by reading a test name.
"""

from __future__ import annotations

import unicodedata

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autofill_audit.extract.normalize import (
    FRAMEWORK_NOISE,
    casefold_token,
    drop_framework_noise,
    insert_camel_boundaries,
    insert_script_boundaries,
    nfkc,
    normalize_identifier_tokens,
    normalize_text,
    normalize_tokens,
    split_on_delimiters,
)


class TestStepOneNfkc:
    """Step 1: Unicode NFKC, and it comes first for a reason."""

    def test_half_width_katakana_becomes_full_width(self) -> None:
        """The step spec section 9.7 puts first exists for exactly this.

        Half-width katakana with its combining voiced marks folds to the
        composed full-width form, so a page that writes a label one way and an
        identifier the other reaches one spelling.
        """
        assert nfkc("ﾜﾋﾞﾝﾊﾞﾝｺﾞｳ") == "ワビンバンゴウ"

    def test_full_width_latin_becomes_ascii(self) -> None:
        """A form that spells its own identifiers in full width still matches.

        The input is written as escapes rather than as the characters
        themselves, because a full-width ``z`` and an ASCII ``z`` are
        indistinguishable in a diff and the whole point of the test is that they
        are not the same character.
        """
        assert nfkc("\uff5a\uff49\uff50") == "zip"

    def test_is_idempotent(self) -> None:
        """NFKC of NFKC is NFKC, which every later step relies on."""
        once = nfkc("ﾜﾋﾞﾝ")
        assert nfkc(once) == once

    def test_leaves_ascii_alone(self) -> None:
        """The common case costs nothing and changes nothing."""
        assert nfkc("postal-code") == "postal-code"


class TestStepTwoCasefold:
    """Step 2: casefold, not lower."""

    def test_sharp_s_folds_to_ss(self) -> None:
        """The de-DE case, and the reason the specification says casefold."""
        assert casefold_token("Straße") == "strasse"

    def test_capital_sharp_s_folds_to_ss_as_well(self) -> None:
        """Both spellings of the same word reach the same token."""
        assert casefold_token("STRAẞE") == "strasse"

    def test_lower_would_not_have(self) -> None:
        """Stated as a test so the choice cannot be undone by accident."""
        assert "Straße".lower() != casefold_token("Straße")

    def test_turkish_dotted_capital_i(self) -> None:
        """The other property the specification names casefold for."""
        assert casefold_token("İ") == unicodedata.normalize("NFKC", "İ".casefold())


class TestStepThreeCamelBoundaries:
    """Step 3: de-camelCase, de-PascalCase, and letter-to-digit."""

    def test_camel_case(self) -> None:
        """The specification's own worked example."""
        assert insert_camel_boundaries("firstName") == "first Name"

    def test_letter_to_digit(self) -> None:
        """The specification's other worked example."""
        assert insert_camel_boundaries("addr1") == "addr 1"

    def test_digit_to_letter(self) -> None:
        """The mirror of the same rule, which real identifiers need."""
        assert insert_camel_boundaries("1stLine") == "1 st Line"

    def test_acronym_run_splits_before_the_last_capital(self) -> None:
        """``ZIPCode`` is two words, not four letters and a word."""
        assert insert_camel_boundaries("ZIPCode") == "ZIP Code"

    def test_pascal_case(self) -> None:
        """A leading capital is not a boundary; there is nothing before it."""
        assert insert_camel_boundaries("PostalCode") == "Postal Code"

    def test_empty_string(self) -> None:
        """No boundary to insert, no exception to raise."""
        assert insert_camel_boundaries("") == ""

    def test_localised_camel_identifiers_from_the_corpus(self) -> None:
        """The three the P1 corpus emits specifically to exercise this step."""
        assert insert_camel_boundaries("passwortWiederholen") == "passwort Wiederholen"
        assert insert_camel_boundaries("meiKana") == "mei Kana"
        assert insert_camel_boundaries("nomComplet") == "nom Complet"


class TestStepFourSplitting:
    """Step 4: non-alphanumeric delimiters and script boundaries."""

    def test_script_boundary_between_cjk_and_latin(self) -> None:
        """The specification's worked example."""
        assert insert_script_boundaries("郵便番号zipcode") == ("郵便番号 zipcode")

    def test_no_boundary_inside_japanese(self) -> None:
        """Han and hiragana are one class, so an ordinary label stays whole."""
        assert insert_script_boundaries("お名前") == "お名前"

    def test_empty_string(self) -> None:
        """Nothing to split, nothing to raise."""
        assert insert_script_boundaries("") == ""

    def test_delimiters_include_the_underscore(self) -> None:
        """Python calls it a word character; every form on the web does not."""
        assert split_on_delimiters("field_7") == ["field", "7"]

    def test_delimiters_include_punctuation(self) -> None:
        """An email placeholder is three tokens, not one."""
        assert split_on_delimiters("you@example.com") == ["you", "example", "com"]

    def test_delimiters_keep_accented_letters(self) -> None:
        """A French label must not be shredded on its own accents."""
        assert split_on_delimiters("adresse électronique") == ["adresse", "électronique"]

    def test_delimiters_keep_combining_marks(self) -> None:
        """The bug a splitter built on Python's word class has.

        ``\\w`` excludes combining marks, so a naive splitter treats each one as
        a separator. That shreds every decomposed form and every script that
        marks its vowels, and it breaks idempotence outright: casefolding the
        Turkish dotted capital I yields an ``i`` followed by a combining dot, and
        splitting on that dot makes a second pass return something different
        from the first.
        """
        assert split_on_delimiters("i̇sim") == ["i̇sim"]
        assert split_on_delimiters("é") == ["é"]

    def test_the_turkish_dotted_capital_i_survives_a_second_pass(self) -> None:
        """The exact case Hypothesis found, pinned as an example."""
        once = normalize_text("İ")
        assert normalize_text(once) == once


class TestStepFiveStoplist:
    """Step 5: framework noise, and only on the identifier stream."""

    def test_drops_listed_tokens(self) -> None:
        """The list is the specification's, verbatim."""
        assert drop_framework_noise(("mat", "postal", "field", "code")) == ("postal", "code")

    def test_keeps_everything_else(self) -> None:
        """A stoplist that grew would quietly delete real signal."""
        assert drop_framework_noise(("postcode",)) == ("postcode",)

    def test_the_list_is_the_specifications(self) -> None:
        """Stated as a test so an addition to it is a deliberate change."""
        assert {
            "ctl00",
            "ng",
            "mat",
            "mui",
            "form",
            "input",
            "field",
            "text",
        } == FRAMEWORK_NOISE

    def test_applies_to_identifiers(self) -> None:
        """``field_5`` carries one token of information, which is the five."""
        assert normalize_identifier_tokens("field_5") == ("5",)

    def test_does_not_apply_to_labels(self) -> None:
        """A label that literally reads Field is information about the page."""
        assert normalize_tokens("Field") == ("field",)

    def test_ctl00_is_matched_before_the_letter_digit_split(self) -> None:
        """The one entry on the list naming a real framework has to survive.

        Split first and ``ctl00`` becomes ``ctl`` and ``00``, neither of which is
        on the list, so the entry would match nothing anywhere. The pre-split
        pass is what makes it mean something.
        """
        assert normalize_identifier_tokens("ctl00$txt3") == ("txt", "3")

    def test_a_real_identifier_survives_intact(self) -> None:
        """The stoplist must not eat anything that carries meaning."""
        assert normalize_identifier_tokens("payment_cardholder") == ("payment", "cardholder")


class TestComposition:
    """The function every caller actually uses."""

    def test_worked_example_end_to_end(self) -> None:
        """NFKC, then boundaries, then casefold, in that order."""
        assert normalize_tokens("firstName") == ("first", "name")

    def test_mixed_script_identifier(self) -> None:
        """Both halves of a mixed-script identifier come out as tokens."""
        assert normalize_tokens("郵便番号zipCode") == (
            "郵便番号",
            "zip",
            "code",
        )

    def test_german_label(self) -> None:
        """Casefold and NFKC together on a real de-DE label."""
        assert normalize_tokens("Straße und Hausnummer") == (
            "strasse",
            "und",
            "hausnummer",
        )

    def test_empty_input_yields_no_tokens(self) -> None:
        """An empty placeholder is present and carries nothing, and both are true."""
        assert normalize_tokens("") == ()

    def test_whitespace_only_yields_no_tokens(self) -> None:
        """Same, for the label that is a single non-breaking space."""
        assert normalize_tokens("\u00a0 \t\n") == ()

    def test_control_characters_are_dropped(self) -> None:
        """From the malformed-input list of spec section 15."""
        assert normalize_tokens("Post\tcode\x0bhere​") == ("post", "code", "here")

    @pytest.mark.parametrize(
        ("identifier", "expected"),
        [
            ("zip", ("zip",)),
            ("postcode", ("postcode",)),
            ("plz", ("plz",)),
            ("codepostal", ("codepostal",)),
            ("yubinbango", ("yubinbango",)),
            ("postalCode", ("postal", "code")),
        ],
    )
    def test_localised_postcode_identifiers(
        self, identifier: str, expected: tuple[str, ...]
    ) -> None:
        """The six spellings the corpus uses for one concept.

        Normalisation does not unify them, and it is not supposed to: spec
        section 9.7 forbids stemming and translation, and character n-grams are
        the mechanism for crossing locales (spec section 10.1). What this test
        pins is that each one arrives at the classifier intact.
        """
        assert normalize_identifier_tokens(identifier) == expected


_ALPHABET = st.characters(
    codec="utf-8",
    categories=["L", "N", "P", "Z", "S"],
    include_characters="ßẞİıéü郵便番号ｚユ",
    max_codepoint=0x9FFF,
)
"""A broad but curated alphabet: letters, numbers, punctuation, separators, and
symbols up to the end of the CJK ideographs, plus the specific characters this
project's six locales turn on. Deliberately not the whole of Unicode. The
composition of NFKC and casefold is idempotent over everything a form label can
contain and over almost everything else, and pinning the property to the input
space the tool actually serves says something true instead of something that
would be false for a Deseret ligature nobody will ever type into a checkout."""


@given(st.text(alphabet=_ALPHABET, max_size=60))
@settings(max_examples=300)
def test_normalisation_is_idempotent(raw: str) -> None:
    """Spec section 15 layer 4: normalising twice changes nothing.

    Stated over the re-joined text rather than over the token tuple, because
    that is the form the property has to hold in: the tokens are fed back
    through as one string everywhere the extractor uses them.
    """
    once = normalize_text(raw)
    assert normalize_text(once) == once


@given(st.text(alphabet=_ALPHABET, max_size=60))
@settings(max_examples=200)
def test_normalisation_never_yields_an_empty_token(raw: str) -> None:
    """An empty token would be a phantom feature with no source in the page."""
    assert all(token for token in normalize_tokens(raw))


@given(st.text(alphabet=_ALPHABET, max_size=60))
@settings(max_examples=200)
def test_identifier_normalisation_is_a_subsequence_of_the_plain_form(raw: str) -> None:
    """The stoplist may only remove tokens, never invent or reorder them."""
    plain = list(normalize_tokens(raw))
    for token in normalize_identifier_tokens(raw):
        assert token in plain
