"""Target resolution and content sniffing, with no browser.

The loader's refusals are the extractor's half of the malformed-input list in
spec section 15. Each one raises a typed exception the CLI maps to an exit code
at P3, so each one is tested here as a type and a sentence rather than as a
traceback somebody reads in the wild.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autofill_audit.loader import (
    SUPPORTED_SCHEMES,
    LoadBudget,
    LoaderError,
    NotHtmlError,
    TargetNotFoundError,
    UnsupportedSchemeError,
    looks_like_html,
    target_url,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "extract" / "pages"


class TestFileTargets:
    """``--file`` reaches a local file through ``file://`` and nothing else."""

    def test_an_html_file_becomes_a_file_uri(self) -> None:
        """The only navigation the tool ever performs on a local target."""
        url = target_url(str(FIXTURES / "clean_labeled.html"), as_file=True)
        assert url.startswith("file://")
        assert url.endswith("clean_labeled.html")

    def test_a_relative_path_is_resolved(self) -> None:
        """A URI needs an absolute path, and a user types a relative one."""
        url = target_url(str(FIXTURES / ".." / "pages" / "clean_labeled.html"), as_file=True)
        assert "/.." not in url

    def test_a_missing_file(self) -> None:
        """A typo, which is the most common failure of them all."""
        with pytest.raises(TargetNotFoundError, match="no such file"):
            target_url(str(FIXTURES / "nope.html"), as_file=True)

    def test_a_directory_is_not_a_file(self) -> None:
        """Pointing at a corpus directory instead of a form is easy to do."""
        with pytest.raises(TargetNotFoundError):
            target_url(str(FIXTURES), as_file=True)

    def test_a_file_that_is_not_html(self) -> None:
        """From the malformed-input list of spec section 15."""
        with pytest.raises(NotHtmlError, match="does not look like HTML"):
            target_url(str(FIXTURES / "not_html.txt"), as_file=True)


class TestUrlTargets:
    """A URL is opened only when its scheme is one the tool serves."""

    @pytest.mark.parametrize("scheme", sorted(SUPPORTED_SCHEMES))
    def test_supported_schemes_pass_through_unchanged(self, scheme: str) -> None:
        """Unchanged, so what the user typed is what gets opened."""
        target = f"{scheme}://example.invalid/checkout"
        assert target_url(target, as_file=False) == target

    def test_an_unsupported_scheme(self) -> None:
        """From the malformed-input list of spec section 15."""
        with pytest.raises(UnsupportedSchemeError, match="ftp"):
            target_url("ftp://example.invalid/form.html", as_file=False)

    def test_a_javascript_url_is_refused(self) -> None:
        """The one refusal that is a safety property rather than a convenience."""
        with pytest.raises(UnsupportedSchemeError):
            target_url("javascript:alert(1)", as_file=False)

    def test_a_bare_path_with_no_scheme_says_what_to_do(self) -> None:
        """The likeliest mistake deserves the most useful message."""
        with pytest.raises(UnsupportedSchemeError, match="--file"):
            target_url("./page.html", as_file=False)

    def test_every_loader_error_shares_one_base(self) -> None:
        """So a caller that only cares that loading failed catches one class."""
        for error in (UnsupportedSchemeError, TargetNotFoundError, NotHtmlError):
            assert issubclass(error, LoaderError)


class TestContentSniffing:
    """Suffixes lie; the first few kilobytes do not."""

    def test_a_real_page_sniffs_as_html(self) -> None:
        """Every committed fixture, so the sniff cannot be too strict."""
        for page in sorted(FIXTURES.glob("*.html")):
            assert looks_like_html(page), page.name

    def test_prose_does_not(self) -> None:
        """The committed non-HTML fixture."""
        assert looks_like_html(FIXTURES / "not_html.txt") is False

    def test_a_saved_dom_with_the_wrong_suffix_still_sniffs_as_html(self, tmp_path: Path) -> None:
        """Spec section 9.6 exists so a developer can save their own rendered
        DOM and audit it offline, and they will not always name it .html."""
        saved = tmp_path / "dom-dump.txt"
        saved.write_text("<div class='field'><input name='email'></div>", encoding="utf-8")
        assert looks_like_html(saved) is True

    def test_binary_content_does_not(self, tmp_path: Path) -> None:
        """A renamed image, which is the other half of the same mistake."""
        image = tmp_path / "screenshot.html"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4)
        assert looks_like_html(image) is False

    def test_an_unreadable_path_is_not_html(self, tmp_path: Path) -> None:
        """A path that cannot be opened is not HTML, and is not an exception."""
        assert looks_like_html(tmp_path / "absent") is False


class TestBudget:
    """The waiting policy, as a value rather than as four arguments."""

    def test_the_defaults_are_the_documented_ones(self) -> None:
        """So a run can record what it used (spec section 18)."""
        budget = LoadBudget()
        assert budget.load_timeout_ms > budget.network_idle_ms > budget.quiet_ms
        assert budget.settle_budget_ms > budget.quiet_ms

    def test_a_test_can_shrink_the_whole_policy_at_once(self) -> None:
        """Which is the reason it is one value."""
        budget = LoadBudget(load_timeout_ms=1, network_idle_ms=1, quiet_ms=1, settle_budget_ms=1)
        assert budget.settle_budget_ms == 1
