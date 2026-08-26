"""The metrics of spec section 13.2, and the reporting policy fixed at P1.

Two things here are worth naming before the tests.

The parity block checks this module's arithmetic against scikit-learn's on
random data. The direction of that dependency is deliberate: scikit-learn is a
development dependency and this module is inside the shipped package, so the
package cannot import it, and an unchecked reimplementation of macro-F1 is a
second answer to a question that must have one.

The insufficient-data block checks that the rule fires. A reporting rule that has
only ever been observed not to fire is indistinguishable from a rule that cannot.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from autofill_audit.evaluate.metrics import (
    INSUFFICIENT_DATA,
    MIN_FIELDS_PER_REPORTED_CELL,
    FindingObservation,
    PhaseTiming,
    abstention,
    accuracy,
    accuracy_columns,
    calibration_report,
    confusion_matrix,
    confusion_pairs,
    encode,
    finding_metrics,
    headline,
    is_reportable,
    label_report,
    latency_percentiles,
    macro_f1,
    macro_f1_columns,
    micro_f1,
    pair_count,
    pair_grid,
    slice_grid,
    suppressed_cells,
)
from autofill_audit.evaluate.runlog import RunLogRow

LABELS = ("email", "username", "postal-code", "address-level2", "tel", "UNKNOWN")


def _row(**overrides: object) -> RunLogRow:
    fields: dict[str, object] = {
        "run_id": "r",
        "engine": "ngram",
        "engine_describe": {"engine": "ngram"},
        "corpus_manifest_sha": "a" * 64,
        "split": "test",
        "form_id": "checkout-02-de-DE-clean-v0",
        "form_family": "checkout",
        "locale": "de-DE",
        "tier": "clean",
        "template_id": "checkout-02",
        "selector": "#x",
        "true_label": "email",
        "pred_label": "email",
        "confidence": 0.9,
        "confidence_kind": "calibrated",
    }
    fields.update(overrides)
    return RunLogRow(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The policy fixed at P1.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Parity with scikit-learn, which this module may not import.
# ---------------------------------------------------------------------------


def _random_pairs(count: int, seed: int) -> tuple[list[str], list[str]]:
    rng = random.Random(seed)
    truth = [rng.choice(LABELS) for _ in range(count)]
    predicted = [actual if rng.random() < 0.6 else rng.choice(LABELS) for actual in truth]
    return truth, predicted


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_macro_f1_agrees_with_scikit_learn(seed: int) -> None:
    from sklearn.metrics import f1_score

    truth, predicted = _random_pairs(400, seed)
    expected = f1_score(truth, predicted, average="macro", zero_division=0)
    assert macro_f1(truth, predicted) == pytest.approx(float(expected))


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_per_label_metrics_agree_with_scikit_learn(seed: int) -> None:
    from sklearn.metrics import precision_recall_fscore_support

    truth, predicted = _random_pairs(400, seed)
    names = sorted(set(truth) | set(predicted))
    precision, recall, f1, support = precision_recall_fscore_support(
        truth, predicted, labels=names, zero_division=0
    )
    report = label_report(truth, predicted)
    for position, name in enumerate(names):
        assert report[name].precision == pytest.approx(float(precision[position]))
        assert report[name].recall == pytest.approx(float(recall[position]))
        assert report[name].f1 == pytest.approx(float(f1[position]))
        assert report[name].support == int(support[position])


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_micro_f1_agrees_with_scikit_learn(seed: int) -> None:
    from sklearn.metrics import f1_score

    truth, predicted = _random_pairs(400, seed)
    expected = f1_score(truth, predicted, average="micro", zero_division=0)
    assert micro_f1(truth, predicted) == pytest.approx(float(expected))
    assert accuracy(truth, predicted) == pytest.approx(float(expected))


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_the_array_statistic_is_the_same_statistic(seed: int) -> None:
    """The permutation test must not compute a different macro-F1 from the table."""
    truth, predicted = _random_pairs(300, seed)
    vocabulary = sorted(set(truth) | set(predicted))
    columns = np.column_stack([encode(truth, vocabulary), encode(predicted, vocabulary)])
    assert macro_f1_columns(columns) == pytest.approx(macro_f1(truth, predicted))
    assert accuracy_columns(columns) == pytest.approx(accuracy(truth, predicted))


def test_an_empty_array_statistic_is_zero_rather_than_an_error() -> None:
    empty = np.zeros((0, 2), dtype=np.int64)
    assert macro_f1_columns(empty) == 0.0
    assert accuracy_columns(empty) == 0.0


def test_macro_f1_averages_over_the_observed_union() -> None:
    """A label the model predicts and truth never carries is counted, not hidden."""
    truth = ["email", "email"]
    predicted = ["email", "tel"]
    report = label_report(truth, predicted)
    assert set(report) == {"email", "tel"}
    assert report["tel"].f1 == 0.0
    assert macro_f1(truth, predicted) == pytest.approx((report["email"].f1 + 0.0) / 2)


def test_the_two_lengths_must_agree() -> None:
    with pytest.raises(ValueError, match="against"):
        label_report(["email"], ["email", "tel"])


# ---------------------------------------------------------------------------
# The insufficient-data rule, shown firing.
# ---------------------------------------------------------------------------


def test_a_thin_grid_cell_reports_its_count_and_no_metric() -> None:
    rows = [_row(locale="fr-FR") for _ in range(MIN_FIELDS_PER_REPORTED_CELL - 1)]
    grid = slice_grid(rows, "locale")
    cell = grid["fr-FR"]
    assert cell.count == MIN_FIELDS_PER_REPORTED_CELL - 1
    assert cell.accuracy is None
    assert cell.macro_f1 is None
    assert cell.insufficient_data is True
    assert INSUFFICIENT_DATA in cell.render()
    assert suppressed_cells(grid.values()) == ["fr-FR"]


def test_a_thick_grid_cell_reports_a_number() -> None:
    rows = [_row(locale="de-DE") for _ in range(MIN_FIELDS_PER_REPORTED_CELL)]
    cell = slice_grid(rows, "locale")["de-DE"]
    assert cell.insufficient_data is False
    assert cell.macro_f1 == pytest.approx(1.0)
    assert INSUFFICIENT_DATA not in cell.render()


def test_the_pair_grid_suppresses_the_thin_cells_and_keeps_the_thick_ones() -> None:
    """The locale by tier grid is the one the rule was written for."""
    rows = [_row(locale="de-DE", tier="clean") for _ in range(MIN_FIELDS_PER_REPORTED_CELL)]
    rows += [_row(locale="ja-JP", tier="hostile") for _ in range(3)]
    grid = pair_grid(rows, "locale", "tier")
    assert grid["de-DE/clean"].insufficient_data is False
    assert grid["ja-JP/hostile"].insufficient_data is True
    assert suppressed_cells(grid.values()) == ["ja-JP/hostile"]


def test_a_finding_rate_over_a_thin_denominator_is_suppressed() -> None:
    """P4 applied the rule to slices only. P5 applies it to finding rates too.

    A precision of 1.0 over three accusations is exactly the number the rule
    exists to keep out of a table, and the counts are still reported, so
    suppressing the rate hides nothing that was measured.
    """
    observations = [
        FindingObservation(
            code="MISSING_AUTOCOMPLETE", template_id="t", needed=True, emitted=True, correct=True
        )
        for _ in range(3)
    ]
    block = finding_metrics(observations, "MISSING_AUTOCOMPLETE")
    assert block["accusations"] == 3
    assert block["correct_accusations"] == 3
    assert block["precision"] is None
    assert block["precision_insufficient_data"] is True


def test_the_two_finding_denominators_are_judged_separately() -> None:
    """Recall's denominator is large and precision's is small. Only one is hidden."""
    observations = [
        FindingObservation(
            code="MISSING_AUTOCOMPLETE",
            template_id="t",
            needed=True,
            emitted=index < 3,
            correct=index < 3,
        )
        for index in range(100)
    ]
    block = finding_metrics(observations, "MISSING_AUTOCOMPLETE")
    assert block["precision"] is None
    assert block["precision_insufficient_data"] is True
    assert block["recall"] == pytest.approx(0.03)
    assert block["recall_insufficient_data"] is False
    assert block["f1"] is None


def test_a_well_supported_finding_rate_is_reported() -> None:
    observations = [
        FindingObservation(
            code="MISSING_AUTOCOMPLETE",
            template_id="t",
            needed=True,
            emitted=True,
            correct=index % 2 == 0,
        )
        for index in range(100)
    ]
    block = finding_metrics(observations, "MISSING_AUTOCOMPLETE")
    assert block["precision"] == pytest.approx(0.5)
    assert block["recall"] == pytest.approx(0.5)
    assert block["f1"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Abstention, confusion, calibration, latency.
# ---------------------------------------------------------------------------


def test_abstention_reads_the_label_and_never_the_confidence() -> None:
    """The n-gram engine reports an abstention at confidence exactly zero."""
    rows = [
        _row(pred_label="UNKNOWN", confidence=0.0),
        _row(pred_label="email", confidence=0.0),
        _row(pred_label="tel", true_label="tel", confidence=0.99),
    ]
    block = abstention(rows)
    assert block["unknown"] == 1
    assert block["unknown_rate"] == pytest.approx(1 / 3)
    assert block["committed"] == 2
    assert block["accuracy_when_committed"] == pytest.approx(1.0)


def test_the_confusion_matrix_carries_its_label_order() -> None:
    rows = [
        _row(true_label="username", pred_label="email"),
        _row(true_label="username", pred_label="email"),
        _row(true_label="email", pred_label="email"),
    ]
    matrix = confusion_matrix(rows)
    assert matrix["labels"] == ["email", "username"]
    assert matrix["cells"]["username"]["email"] == 2
    assert confusion_pairs(rows)[0] == {"truth": "username", "predicted": "email", "count": 2}
    assert pair_count(rows, "username", "email") == 2
    assert pair_count(rows, "email", "username") == 0


def test_calibration_excludes_the_classes_whose_calibrator_is_the_identity() -> None:
    rows = [_row(pred_label="email", confidence=0.9) for _ in range(10)]
    rows += [_row(pred_label="username", true_label="email", confidence=0.9) for _ in range(10)]
    everything = calibration_report(rows)
    calibrated = calibration_report(rows, exclude_labels=frozenset({"username"}))
    assert everything["scored_rows"] == 20
    assert calibrated["scored_rows"] == 10
    assert calibrated["excluded_labels"] == ["username"]
    assert everything["expected_calibration_error"] > calibrated["expected_calibration_error"]


def test_calibration_leaves_abstentions_out_of_the_curve() -> None:
    rows = [_row(pred_label="UNKNOWN", confidence=0.0) for _ in range(5)]
    assert calibration_report(rows)["scored_rows"] == 0


def test_latency_percentiles_interpolate_the_way_numpy_does() -> None:
    values = [float(index) for index in range(1, 101)]
    result = latency_percentiles(values)
    for percentile in (50, 95, 99):
        expected = float(np.percentile(values, percentile))
        assert result[f"p{percentile}"] == pytest.approx(expected)


def test_latency_percentiles_of_nothing_are_null_rather_than_zero() -> None:
    assert latency_percentiles([]) == {"p50": None, "p95": None, "p99": None}


def test_the_wall_time_split_says_where_the_extraction_came_from() -> None:
    timing = PhaseTiming(
        load_s=10.0,
        extract_s=5.0,
        classify_s=1.0,
        render_s=0.5,
        total_s=20.0,
        forms=10,
        fields=100,
        extraction_source="browser",
    )
    payload = timing.to_json()
    assert payload["extraction_source"] == "browser"
    assert payload["load_and_extract_share"] == pytest.approx(0.75)


def test_the_headline_counts_the_templates_the_statistics_will_cluster_on() -> None:
    rows = [_row(template_id="a"), _row(template_id="a"), _row(template_id="b")]
    block = headline(rows)
    assert block["templates"] == 2
    assert block["rows"] == 3
    assert block["macro_f1"] == pytest.approx(1.0)
