"""The reconciliation rules the P2 gate's corpus sweep is stated in.

Defined once so that the fast sample-corpus sweep in the test suite and the full
six-hundred-form sweep in ``scripts/corpus_sweep.py`` report the same numbers by
the same rules. Tested here without a browser, against hand-built results, so
that the rules themselves are pinned rather than only their outcome on one
corpus.
"""

from __future__ import annotations

from typing import Any

from autofill_audit.descriptors import (
    CanvasRegion,
    ExtractionResult,
    ExtractionWarning,
    ExtractionWarningCode,
    FieldDescriptor,
)
from autofill_audit.extract.reconcile import SweepTotals, reconcile


def _key(*selectors: str, **notes: list[str]) -> dict[str, Any]:
    """A minimal answer key in the committed shape."""
    return {
        "form_id": "example-01-en-US-clean-v0",
        "fields": [{"selector": selector} for selector in selectors],
        "page_notes": {
            "canvas_pseudo_fields": notes.get("canvas", []),
            "injected_selectors": notes.get("injected", []),
            "shadow_hosts": notes.get("shadow", []),
        },
    }


def _result(*selectors: str, **extra: Any) -> ExtractionResult:
    """A minimal extraction result."""
    return ExtractionResult(
        fields=tuple(
            FieldDescriptor(
                selector=selector,
                shadow_path=(selector.split(" >>> ")[0],) if " >>> " in selector else (),
            )
            for selector in selectors
        ),
        honeypots=tuple(
            FieldDescriptor(selector=item, is_visible=False) for item in extra.get("honeypots", [])
        ),
        canvas_regions=tuple(
            CanvasRegion(selector=item, width=320.0, height=120.0)
            for item in extra.get("canvas", [])
        ),
        warnings=tuple(extra.get("warnings", ())),
    )


class TestBalancing:
    """What "reconciles" means."""

    def test_an_exact_match(self) -> None:
        """Every selector accounted for, nothing invented."""
        item = reconcile(_result("#a", "#b"), _key("#a", "#b"))
        assert item.ok is True
        assert item.found == item.expected == 2
        assert item.missing == ()
        assert item.unexpected == ()

    def test_a_missing_control(self) -> None:
        """A key entry the walk did not find, named so it can be chased."""
        item = reconcile(_result("#a"), _key("#a", "#b"))
        assert item.ok is False
        assert item.missing == ("#b",)

    def test_an_invented_control(self) -> None:
        """The failure that would otherwise hide behind a matching count."""
        item = reconcile(_result("#a", "#c"), _key("#a"))
        assert item.ok is False
        assert item.unexpected == ("#c",)

    def test_a_count_that_matches_while_the_selectors_do_not(self) -> None:
        """Two wrongs looking like a right is exactly what set comparison
        catches and a count comparison does not."""
        item = reconcile(_result("#a", "#c"), _key("#a", "#b"))
        assert item.found == item.expected
        assert item.ok is False


class TestOrder:
    """Order is reported, and is not a failure."""

    def test_a_reordered_result_still_reconciles(self) -> None:
        """An answer key lists slot order; the extractor returns document order.

        On the mixed markup tier those legitimately differ, because a hostile
        block sits in the middle of a form whose extra controls belong to that
        block and render in the middle while the key lists them last. The
        selectors are the contract; the order of the list is not.
        """
        item = reconcile(_result("#b", "#a"), _key("#a", "#b"))
        assert item.ok is True
        assert item.order_differs is True

    def test_a_matching_order_says_so(self) -> None:
        """The common case, which is most of the corpus."""
        assert reconcile(_result("#a", "#b"), _key("#a", "#b")).order_differs is False


class TestPageNotes:
    """Canvases, injected controls, and shadow hosts."""

    def test_a_canvas_is_counted_as_a_region_not_a_field(self) -> None:
        """P1's counting rule, and what keeps the two totals comparable."""
        item = reconcile(
            _result("#a", canvas=["#canvas-order"]), _key("#a", canvas=["#canvas-order"])
        )
        assert item.canvas_found == item.canvas_expected == 1
        assert item.found == 1
        assert item.ok is True

    def test_a_missing_canvas_fails_the_reconciliation(self) -> None:
        """A canvas nobody noticed is a blind spot nobody reported."""
        item = reconcile(_result("#a"), _key("#a", canvas=["#canvas-order"]))
        assert item.ok is False

    def test_an_injected_control_is_counted_when_it_was_found(self) -> None:
        """The settle either caught it or it did not, and the number says so."""
        item = reconcile(_result("#a", "#input20"), _key("#a", "#input20", injected=["#input20"]))
        assert item.injected_found == item.injected_expected == 1

    def test_an_injected_control_that_was_missed_is_counted_as_missing(self) -> None:
        """Which is the discrepancy a walk with no bounded wait produces."""
        item = reconcile(_result("#a"), _key("#a", "#input20", injected=["#input20"]))
        assert item.injected_found == 0
        assert item.injected_expected == 1
        assert item.missing == ("#input20",)

    def test_a_shadow_hosted_control_is_matched_by_its_host(self) -> None:
        """The host is what the page notes list, and the descriptor carries it."""
        item = reconcile(
            _result("#a", "#ce-1 >>> input:nth-of-type(1)"),
            _key("#a", "#ce-1 >>> input:nth-of-type(1)", shadow=["#ce-1"]),
        )
        assert item.shadow_found == item.shadow_expected == 1

    def test_a_key_with_no_page_notes_at_all(self) -> None:
        """An older key, or a hand-written one, must not raise."""
        item = reconcile(_result("#a"), {"form_id": "x", "fields": [{"selector": "#a"}]})
        assert item.ok is True
        assert item.canvas_expected == 0

    def test_a_key_whose_page_notes_are_the_wrong_shape(self) -> None:
        """A corrupt key is reported as a mismatch, never as a crash."""
        item = reconcile(
            _result("#a"),
            {"form_id": "x", "fields": [{"selector": "#a"}], "page_notes": "none"},
        )
        assert item.canvas_expected == 0

    def test_a_key_whose_fields_are_the_wrong_shape(self) -> None:
        """Same, one level down."""
        item = reconcile(_result(), {"form_id": "x", "fields": "none"})
        assert item.expected == 0


class TestRendering:
    """One line per form, for a sweep log."""

    def test_a_passing_line(self) -> None:
        """Readable at a glance across six hundred of them."""
        line = reconcile(_result("#a"), _key("#a")).render()
        assert line.startswith("ok  ")
        assert "found 1 of 1" in line

    def test_a_failing_line(self) -> None:
        """Distinguishable from a passing one without reading the numbers."""
        assert reconcile(_result(), _key("#a")).render().startswith("BAD ")


class TestTotals:
    """The summary the gate reports."""

    def test_totals_add_up(self) -> None:
        """Sums, and a list of the forms that did not balance."""
        totals = SweepTotals()
        totals.add(reconcile(_result("#a"), _key("#a")))
        totals.add(reconcile(_result("#b", "#c"), _key("#b", "#c")))
        assert totals.forms == 2
        assert totals.found == totals.expected == 3
        assert totals.ok is True

    def test_a_failure_is_kept_for_the_report(self) -> None:
        """A sweep that failed has to say which form and why."""
        totals = SweepTotals()
        totals.add(reconcile(_result(), _key("#a")))
        assert totals.ok is False
        assert len(totals.failures) == 1

    def test_an_exception_makes_the_sweep_fail_even_with_no_mismatch(self) -> None:
        """The gate's wording is zero unhandled exceptions, so one is fatal to
        the run even though it produced no reconciliation to fail."""
        totals = SweepTotals()
        totals.add(reconcile(_result("#a"), _key("#a")))
        totals.errors.append(("form-04", "TimeoutError: never loaded"))
        assert totals.ok is False

    def test_warnings_are_carried_onto_the_reconciliation(self) -> None:
        """So a sweep log can say which forms were still moving when time ran
        out, which is the one discrepancy that is expected rather than a bug."""
        item = reconcile(
            _result(
                "#a",
                warnings=[ExtractionWarning(ExtractionWarningCode.INCOMPLETE, "still moving")],
            ),
            _key("#a"),
        )
        assert item.warnings == ("incomplete",)

    def test_honeypots_are_counted(self) -> None:
        """A corpus form has none, so a non-zero count is a visibility bug."""
        item = reconcile(_result("#a", honeypots=["#trap"]), _key("#a"))
        assert item.honeypots == 1
