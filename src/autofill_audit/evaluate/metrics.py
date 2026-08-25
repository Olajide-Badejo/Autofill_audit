"""Precision, recall, F1 per label, per locale, per tier, and latency percentiles.

Filled at P5 (spec section 13.2). What lands here at P1 is the one policy
constant P1 was asked to fix, because the constant has to exist before the code
that enforces it does: fixing it later, once the first numbers are on screen,
would mean choosing a reporting threshold with knowledge of which cells it would
suppress, which is the kind of decision law 4 exists to prevent.
"""

from __future__ import annotations

from typing import Final

__all__ = ["INSUFFICIENT_DATA", "MIN_FIELDS_PER_REPORTED_CELL", "is_reportable"]

MIN_FIELDS_PER_REPORTED_CELL: Final[int] = 30
"""A locale by tier cell needs at least this many fields before its accuracy is
reported as a percentage (spec section 8.5, recorded in ``docs/report.md``).

Spec section 8.5 states the reason plainly: a three-field cell showing "100%
accuracy" is a lie that formats correctly. The threshold is a policy decision
fixed at P1 and enforced by code from P5, rather than a judgement left to
whoever is writing the table."""

INSUFFICIENT_DATA: Final[str] = "insufficient data"
"""What a cell below the threshold renders as. A string rather than a blank,
because a blank cell reads as an oversight and this one is a decision."""


def is_reportable(field_count: int) -> bool:
    """Return True when a cell holds enough fields to report as a percentage."""
    return field_count >= MIN_FIELDS_PER_REPORTED_CELL
