"""Reconciling an extraction against a committed answer key.

The P2 gate asks for a count of controls found versus answer-key entries, with
any discrepancy explained. This module is where that comparison is defined once,
so that the fast sample-corpus test in the suite and the full six-hundred-form
sweep report the same numbers by the same rules rather than by two similar
looking implementations.

Two rules are worth stating before the code.

**Comparison is by selector set, not by position.** An answer key lists its
fields in the generator's slot order, which appends a tier's extra controls at
the end of the list. The extractor returns document order (spec section 9.1 step
7). On the mixed markup tier, where a hostile block sits in the middle of a form
whose extras belong to it, those two orders legitimately differ. The selectors
are the contract; the order of the list is not.

**A canvas is not a field.** Spec section 0.4 puts canvas-rendered widgets out
of scope and spec section 9.6 says to name them at page level, so a corpus form
with a canvas has one canvas region and no extra descriptor. The counting rule
that falls out of that is the one P1's handoff states:

    controls found  ==  len(answer_key["fields"])
    canvas regions  ==  len(page_notes["canvas_pseudo_fields"])
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from autofill_audit.descriptors import ExtractionResult

__all__ = ["Reconciliation", "SweepTotals", "reconcile"]


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """How one extraction compared to one answer key."""

    form_id: str
    found: int
    expected: int
    missing: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    canvas_found: int = 0
    canvas_expected: int = 0
    injected_found: int = 0
    injected_expected: int = 0
    shadow_found: int = 0
    shadow_expected: int = 0
    order_differs: bool = False
    honeypots: int = 0
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether the extraction accounts for every entry in the key."""
        return (
            not self.missing and not self.unexpected and self.canvas_found == self.canvas_expected
        )

    def render(self) -> str:
        """One line for a sweep log."""
        mark = "ok  " if self.ok else "BAD "
        return (
            f"{mark}{self.form_id}: found {self.found} of {self.expected}, "
            f"canvas {self.canvas_found}/{self.canvas_expected}, "
            f"injected {self.injected_found}/{self.injected_expected}, "
            f"shadow {self.shadow_found}/{self.shadow_expected}"
        )


@dataclass(slots=True)
class SweepTotals:
    """Running totals over a whole corpus sweep."""

    forms: int = 0
    found: int = 0
    expected: int = 0
    canvas_found: int = 0
    canvas_expected: int = 0
    injected_found: int = 0
    injected_expected: int = 0
    shadow_found: int = 0
    shadow_expected: int = 0
    honeypots: int = 0
    order_differs: int = 0
    failures: list[Reconciliation] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    def add(self, item: Reconciliation) -> None:
        """Fold one form's reconciliation into the totals."""
        self.forms += 1
        self.found += item.found
        self.expected += item.expected
        self.canvas_found += item.canvas_found
        self.canvas_expected += item.canvas_expected
        self.injected_found += item.injected_found
        self.injected_expected += item.injected_expected
        self.shadow_found += item.shadow_found
        self.shadow_expected += item.shadow_expected
        self.honeypots += item.honeypots
        self.order_differs += int(item.order_differs)
        if not item.ok:
            self.failures.append(item)

    @property
    def ok(self) -> bool:
        """Whether the whole sweep balanced and nothing raised."""
        return not self.failures and not self.errors


def _page_notes(key: Mapping[str, Any], name: str) -> tuple[str, ...]:
    """Read one list out of an answer key's page notes."""
    notes = key.get("page_notes")
    if not isinstance(notes, Mapping):
        return ()
    values = notes.get(name)
    if not isinstance(values, Sequence) or isinstance(values, str):
        return ()
    return tuple(item for item in values if isinstance(item, str))


def reconcile(result: ExtractionResult, key: Mapping[str, Any]) -> Reconciliation:
    """Compare one extraction against one committed answer key."""
    entries = key.get("fields")
    expected_entries: list[Mapping[str, Any]] = (
        [item for item in entries if isinstance(item, Mapping)]
        if isinstance(entries, Sequence) and not isinstance(entries, str)
        else []
    )
    expected = [str(item["selector"]) for item in expected_entries if "selector" in item]
    found = [descriptor.selector for descriptor in result.fields]

    canvas_expected = _page_notes(key, "canvas_pseudo_fields")
    injected_expected = _page_notes(key, "injected_selectors")
    shadow_expected = _page_notes(key, "shadow_hosts")
    found_set = set(found)

    return Reconciliation(
        form_id=str(key.get("form_id", "")),
        found=len(found),
        expected=len(expected),
        missing=tuple(sorted(set(expected) - found_set)),
        unexpected=tuple(sorted(found_set - set(expected))),
        canvas_found=len(result.canvas_regions),
        canvas_expected=len(canvas_expected),
        injected_found=sum(1 for selector in injected_expected if selector in found_set),
        injected_expected=len(injected_expected),
        shadow_found=sum(
            1
            for descriptor in result.fields
            if descriptor.shadow_path and descriptor.shadow_path[0] in shadow_expected
        ),
        shadow_expected=len(shadow_expected),
        order_differs=found != expected,
        honeypots=len(result.honeypots),
        warnings=tuple(warning.code.value for warning in result.warnings),
    )
