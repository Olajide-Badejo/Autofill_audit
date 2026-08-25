"""The malformed-input list of spec section 15, for the extractor-scoped half.

Each case must produce a diagnostic and a documented outcome, never a traceback
and never a wrong answer. The URL and exit-code cases belong to P3's CLI; what
lives here is what the extractor and the loader owe it, which is a typed
exception or a correct descriptor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from autofill_audit.extract.signals import MAX_OPTIONS
from autofill_audit.loader import (
    LoadBudget,
    NavigationFailedError,
    NavigationTimeoutError,
    NotHtmlError,
    load_page,
)

pytestmark = pytest.mark.e2e


class TestUnclosedTags:
    """The parser repairs them and the walk sees the repaired tree."""

    def test_the_page_still_extracts(self, extract_page: Any) -> None:
        """Four controls, in order, from markup that does not close its tags."""
        result = extract_page("malformed_markup.html")
        assert [item.selector for item in result.fields] == [
            "#broken-empty",
            "#broken-modifier",
            "#broken-token",
            "#broken-control",
        ]

    def test_the_repaired_label_still_labels_its_control(self, extract_page: Any) -> None:
        """The unclosed label swallows the input, so it labels it twice over:
        once by ``for`` and once by containing it. Both are collected."""
        result = extract_page("malformed_markup.html")
        first = result.fields[0]
        assert first.text.label_for == "Empty declaration"
        assert first.text.label_ancestor == "Empty declaration"


class TestDeclarationCases:
    """The three ``autocomplete`` shapes on the malformed-input list."""

    def test_empty_declaration(self, extract_page: Any) -> None:
        """Present, blank, and off specification. Not the same as absent."""
        declared = extract_page("malformed_markup.html").fields[0].declared
        assert declared.raw == ""
        assert declared.token is None
        assert declared.is_off_spec is True

    def test_modifier_only_declaration(self, extract_page: Any) -> None:
        """``shipping`` alone is not a value any browser can act on."""
        declared = extract_page("malformed_markup.html").fields[1].declared
        assert declared.modifiers == ("shipping",)
        assert declared.token is None
        assert declared.is_off_spec is True

    def test_invented_token(self, extract_page: Any) -> None:
        """The modifier is still parsed, and the token is still flagged."""
        declared = extract_page("malformed_markup.html").fields[2].declared
        assert declared.modifiers == ("shipping",)
        assert declared.token == "zipcode"
        assert declared.is_off_spec is True


class TestHostileText:
    """Labels that are too long or full of characters nobody meant to type."""

    def test_control_characters_are_collapsed_away(self, extract_page: Any) -> None:
        """A tab, a vertical tab, and a zero-width space, from one real label."""
        control = extract_page("malformed_markup.html").fields[3]
        assert control.norm.label_tokens == ("post", "code", "here")

    def test_a_ten_thousand_character_label_is_collected_whole(self, extract_page: Any) -> None:
        """Not truncated, and not allowed to raise.

        Truncating a signal without saying so is how an extractor produces a
        confident wrong answer, so the choice here is to carry it.
        """
        result = extract_page("long_label.html")
        label = result.fields[0].text.label_for
        assert label is not None
        assert len(label) > 10_000
        assert result.fields[0].norm.label_tokens[:3] == ("street", "address", "line")

    def test_the_control_beside_it_is_unaffected(self, extract_page: Any) -> None:
        """One hostile control must not cost the rest of the page."""
        result = extract_page("long_label.html")
        assert result.fields[1].selector == "#verbose-postcode"


class TestManyOptions:
    """A select with five thousand options."""

    def test_the_option_list_is_truncated(self, extract_page: Any) -> None:
        """Bounded, at the documented constant."""
        select = extract_page("many_options.html").fields[0]
        assert len(select.option_values) == MAX_OPTIONS
        assert len(select.option_labels) == MAX_OPTIONS

    def test_the_truncated_list_is_not_mistaken_for_a_month_list(self, extract_page: Any) -> None:
        """The whole reason the constant is larger than twelve."""
        select = extract_page("many_options.html").fields[0]
        assert select.group_role == "none"
        assert len(select.option_values) != 12

    def test_the_control_beside_it_is_unaffected(self, extract_page: Any) -> None:
        """Again: one hostile control, one hostile control's worth of cost."""
        result = extract_page("many_options.html")
        assert result.fields[1].selector == "#branch-postcode"


class TestDuplicateIds:
    """Invalid HTML, and entirely ordinary on real pages."""

    def test_neither_control_uses_the_duplicated_id(self, extract_page: Any) -> None:
        """``#email`` would resolve to the first of two and name the wrong one."""
        result = extract_page("duplicate_ids.html")
        assert not any(item.selector == "#email" for item in result.fields)

    def test_each_falls_through_to_a_different_preference(self, extract_page: Any) -> None:
        """The first has a name; the second has nothing but its position."""
        result = extract_page("duplicate_ids.html")
        assert result.fields[0].selector == 'form[name="signup"] [name="signup_email"]'
        assert result.fields[1].selector.startswith('form[name="signup"] >')

    def test_the_label_attaches_to_the_first_only(self, extract_page: Any) -> None:
        """Which is what ``getElementById`` does, and what the browser does."""
        result = extract_page("duplicate_ids.html")
        assert result.fields[0].text.label_for == "Email address"
        assert result.fields[1].text.label_for is None

    def test_a_unique_id_on_the_same_page_still_works(self, extract_page: Any) -> None:
        """One duplicate does not poison the document."""
        result = extract_page("duplicate_ids.html")
        assert result.fields[2].selector == "#signup-postcode"


class TestLoaderRefusals:
    """Typed exceptions the CLI maps to exit codes at P3."""

    def test_a_file_that_is_not_html(self, browser: Any, pages_dir: Path) -> None:
        """Refused before a browser is ever pointed at it."""
        with (
            pytest.raises(NotHtmlError),
            load_page(str(pages_dir / "not_html.txt"), as_file=True, browser=browser),
        ):
            pass

    def test_a_url_that_never_answers(self, browser: Any) -> None:
        """No network in this suite, so an unroutable host is the honest test.

        Whichever way Chromium reports it, a bounded wait and a typed exception
        are what the CLI needs, and an unbounded hang is what it must never get.
        """
        with (
            pytest.raises((NavigationTimeoutError, NavigationFailedError)),
            load_page(
                "http://127.0.0.1:9/never",
                browser=browser,
                budget=LoadBudget(load_timeout_ms=2000),
            ),
        ):
            pass

    def test_a_page_that_loads_slowly_still_loads(self, browser: Any, pages_dir: Path) -> None:
        """The bound is a bound, not a hair trigger."""
        with load_page(
            str(pages_dir / "injected_field.html"),
            as_file=True,
            browser=browser,
            budget=LoadBudget(load_timeout_ms=15_000),
        ) as loaded:
            assert loaded.url.endswith("injected_field.html")
