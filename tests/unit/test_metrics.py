"""The reporting-minimum policy fixed at P1 (spec section 8.5)."""

from __future__ import annotations

from autofill_audit.evaluate.metrics import (
    INSUFFICIENT_DATA,
    MIN_FIELDS_PER_REPORTED_CELL,
    is_reportable,
)


def test_the_threshold_is_the_recorded_policy() -> None:
    assert MIN_FIELDS_PER_REPORTED_CELL == 30


def test_a_thin_cell_is_not_reportable() -> None:
    assert not is_reportable(0)
    assert not is_reportable(MIN_FIELDS_PER_REPORTED_CELL - 1)


def test_a_thick_cell_is_reportable() -> None:
    assert is_reportable(MIN_FIELDS_PER_REPORTED_CELL)
    assert is_reportable(MIN_FIELDS_PER_REPORTED_CELL + 1)


def test_the_insufficient_data_marker_is_a_visible_string() -> None:
    """A blank cell reads as an oversight. This one is a decision."""
    assert INSUFFICIENT_DATA.strip()
