"""The hard cases of spec section 9.6, each shown on its own.

The P2 gate asks for the closed shadow root, the cross-origin frame, the canvas,
and the injected field to each produce their specified outcome, individually.
This module is that, in a real browser, against the hand-authored pages, with
one test per outcome so that a failure names the case rather than a fixture
diff.

The injected-field tests assert on the **mechanism**, never on a duration. Spec
section 15's flake policy is explicit: a timing-dependent extractor test waits on
a condition, and a run that merely took long enough proves nothing.
"""

from __future__ import annotations

from typing import Any

import pytest

from autofill_audit.descriptors import ExtractionWarningCode, UndetectableReason
from autofill_audit.extract.walker import ExtractOptions
from autofill_audit.loader import LoadBudget

pytestmark = pytest.mark.e2e


class TestClosedShadowRoot:
    """Cannot be accessed, and so is named rather than passed over."""

    def test_it_yields_one_undetectable_descriptor(self, extract_page: Any) -> None:
        """Spec section 9.6's specified outcome, exactly."""
        result = extract_page("closed_shadow_root.html")
        closed = [
            item
            for item in result.fields
            if item.undetectable_reason == UndetectableReason.CLOSED_SHADOW_ROOT.value
        ]
        assert len(closed) == 1
        assert closed[0].selector == "#ce-2"
        assert closed[0].tag == "vault-field"

    def test_the_walk_continues_past_it(self, extract_page: Any) -> None:
        """A blind spot costs one control, not the rest of the page."""
        result = extract_page("closed_shadow_root.html")
        assert [item.selector for item in result.fields] == ["#pay-name", "#ce-2", "#pay-csc"]

    def test_a_decorative_custom_element_produces_nothing(self, extract_page: Any) -> None:
        """The discriminator that keeps the rule from firing on every icon.

        ``vault-icon`` is upgraded and has no shadow root and no light DOM
        controls, exactly like ``vault-field``. What it does not have is
        anything that presents it as a control, and that is what separates them.
        """
        result = extract_page("closed_shadow_root.html")
        assert all("deco-1" not in item.selector for item in result.fields)

    def test_an_open_shadow_root_is_walked_instead_of_reported(self, extract_page: Any) -> None:
        """The contrast that makes the closed case mean something."""
        result = extract_page("open_shadow_root.html")
        assert all(item.undetectable_reason is None for item in result.fields)
        assert result.fields[1].selector == "#ce-1 >>> input:nth-of-type(1)"
        assert result.fields[1].shadow_path == ("#ce-1",)

    def test_the_shadow_control_is_walked_in_place(self, extract_page: Any) -> None:
        """Spec section 9.1's ordering rule, which the context signals depend on.

        The shadowed password field sits between the username above it and the
        one-time code below it, in the page and in the output.
        """
        result = extract_page("open_shadow_root.html")
        assert [item.selector for item in result.fields] == [
            "#login-user",
            "#ce-1 >>> input:nth-of-type(1)",
            "#login-code",
        ]

    def test_shadow_context_comes_from_the_host(self, extract_page: Any) -> None:
        """There is no form and no heading inside the root, and both are real
        facts about where the control sits."""
        result = extract_page("open_shadow_root.html")
        assert result.fields[1].text.section_heading == "Sign in"


class TestCrossOriginFrame:
    """Common and correct on real checkouts, and still a blind spot."""

    def test_it_yields_one_undetectable_descriptor(self, extract_page: Any) -> None:
        """Spec section 9.6's specified outcome, exactly."""
        result = extract_page("cross_origin_iframe.html")
        unreadable = [
            item
            for item in result.fields
            if item.undetectable_reason == UndetectableReason.CROSS_ORIGIN_FRAME.value
        ]
        assert len(unreadable) == 1
        assert unreadable[0].selector == "frame[#hosted-card]"

    def test_the_page_level_warning_names_the_frame(self, extract_page: Any) -> None:
        """So a report can say which one, on a page with several."""
        result = extract_page("cross_origin_iframe.html")
        warning = result.warning(ExtractionWarningCode.FRAME_UNREADABLE)
        assert warning is not None
        assert "frame[#hosted-card]" in warning.detail

    def test_the_control_after_the_frame_is_still_collected(self, extract_page: Any) -> None:
        """One unreadable frame costs exactly that frame, which is the whole
        reason spec section 9.1 treats frames as roots."""
        result = extract_page("cross_origin_iframe.html")
        assert [item.selector for item in result.fields] == [
            "#outer-name",
            "frame[#hosted-card]",
            "#outer-postcode",
        ]

    def test_a_same_origin_frame_is_walked_instead(self, extract_page: Any) -> None:
        """The contrast, and the frame separator in use."""
        result = extract_page("same_origin_iframe.html")
        assert all(item.undetectable_reason is None for item in result.fields)
        assert result.fields[1].selector == "frame[#card-frame] >> #pan"
        assert result.fields[1].frame_path == ("frame[#card-frame]",)
        assert result.frame_count == 2

    def test_the_main_frame_is_walked_first(self, extract_page: Any) -> None:
        """Spec section 9.1 step 2: roots in turn, not interleaved."""
        result = extract_page("same_origin_iframe.html")
        assert result.fields[0].frame_path == ()


class TestCanvas:
    """Out of scope to solve, in scope to name."""

    def test_a_canvas_only_page_yields_one_page_level_descriptor(self, extract_page: Any) -> None:
        """Spec section 9.6's specified outcome: zero controls, one canvas."""
        result = extract_page("canvas_only.html")
        assert len(result.fields) == 1
        assert result.fields[0].undetectable_reason == UndetectableReason.CANVAS_REGION.value
        assert result.fields[0].selector == "#canvas-card"

    def test_the_small_canvas_is_ignored(self, extract_page: Any) -> None:
        """A sparkline is not a hidden form, and reporting it as one would
        teach a reader to skip the finding."""
        result = extract_page("canvas_only.html")
        assert [region.selector for region in result.canvas_regions] == ["#canvas-card"]

    def test_a_canvas_beside_real_controls_is_recorded_only(self, extract_page: Any) -> None:
        """What the corpus actually contains, and the counting rule the gate
        reconciliation depends on: the canvas is a region, never a field."""
        result = extract_page("clean_labeled.html")
        assert result.canvas_regions == ()
        assert all(item.undetectable_reason is None for item in result.fields)


class TestInjectedField:
    """The bounded wait, asserted on its mechanism."""

    def test_the_injected_control_is_found(self, extract_page: Any) -> None:
        """A walk at the load event would have missed it."""
        result = extract_page("injected_field.html")
        assert [item.selector for item in result.fields] == ["#basket-email", "#input2"]

    def test_the_settle_observed_the_control_arrive(self, extract_page: Any) -> None:
        """The mechanism assertion spec section 15's flake policy asks for.

        This is the difference between a wait that worked and a wait that was
        merely long: the mutation observer counted a control being added after
        the load event, so the extraction can say it saw the page change rather
        than that it slept for a while and hoped.
        """
        result = extract_page("injected_field.html")
        assert result.settle.controls_added_after_load >= 1
        assert result.settle.reached_quiet is True
        assert result.warning(ExtractionWarningCode.INCOMPLETE) is None

    def test_without_the_wait_the_control_is_missing(self, extract_page: Any) -> None:
        """The other half of the same mechanism.

        With the quiet period and the settle budget both taken away, the walk
        runs at the load event and finds the empty slot and no control in it,
        which is exactly the short list the wait exists to prevent.
        """
        result = extract_page(
            "injected_field.html",
            budget=LoadBudget(network_idle_ms=0, quiet_ms=0, settle_budget_ms=0),
        )
        assert [item.selector for item in result.fields] == ["#basket-email"]

    def test_a_page_that_never_settles_is_bounded_and_says_so(self, extract_page: Any) -> None:
        """Spec section 9.6: extract what exists, warn, never wait unbounded.

        The page appends a control every fifty milliseconds forever, so the
        quiet period is unreachable and the budget is the thing that ends the
        wait. What matters is that the wait ends, that the result says the page
        was still moving, and that what did exist was still extracted.
        """
        result = extract_page(
            "settle_budget_expiry.html",
            budget=LoadBudget(network_idle_ms=200, quiet_ms=250, settle_budget_ms=600),
        )
        assert result.settle.reached_quiet is False
        warning = result.warning(ExtractionWarningCode.INCOMPLETE)
        assert warning is not None
        assert "still changing" in warning.detail
        assert any(item.selector == "#live-email" for item in result.fields)

    def test_a_static_page_reaches_quiet_and_warns_about_nothing(self, extract_page: Any) -> None:
        """The common case has to be silent for the warning to mean anything."""
        result = extract_page("clean_labeled.html")
        assert result.settle.reached_quiet is True
        assert result.settle.controls_added_after_load == 0
        assert result.warnings == ()


class TestHoneypots:
    """Excluded from the audit, retained on the record."""

    def test_the_three_hidden_controls_are_excluded(self, extract_page: Any) -> None:
        """Offscreen, zero size, and display none: the shapes spec 9.6 names."""
        result = extract_page("honeypot.html")
        assert [item.selector for item in result.fields] == [
            "#contact-email",
            "#contact-message",
        ]

    def test_they_are_retained_rather_than_dropped(self, extract_page: Any) -> None:
        """A report whose field count disagrees with the developer's own markup
        is a report they stop trusting."""
        result = extract_page("honeypot.html")
        assert [item.selector for item in result.honeypots] == [
            "#contact-website",
            "#contact-fax",
            "#contact-alias",
        ]
        assert all(item.is_visible is False for item in result.honeypots)

    def test_a_control_below_the_fold_is_not_a_honeypot(self, extract_page: Any) -> None:
        """The message box sits below two thousand four hundred pixels of
        spacer and is an ordinary field."""
        result = extract_page("honeypot.html")
        message = result.fields[-1]
        assert message.selector == "#contact-message"
        assert message.is_visible is True
        assert message.bbox is not None
        assert message.bbox[1] > 2000


class TestTruncation:
    """The bound of spec section 9.6 on a very large page."""

    def test_a_page_above_the_limit_is_truncated_and_reported(self, extract_page: Any) -> None:
        """Stopping is fine; stopping quietly is not.

        The limit is lowered for the test rather than the page being made
        enormous, because the behaviour under test is the bound, not the number.
        """
        result = extract_page(
            "radio_checkbox_groups.html", options=ExtractOptions(now_year=2026, max_controls=3)
        )
        assert result.truncated is True
        assert len(result.fields) == 3
        warning = result.warning(ExtractionWarningCode.TRUNCATED)
        assert warning is not None
        assert "3 controls" in warning.detail
