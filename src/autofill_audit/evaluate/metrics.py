"""Precision, recall, F1 per label, per locale, per tier, and latency percentiles.

Spec section 13.2, computed from the committed run log and from nothing else, so
that every number in a result file can be recomputed by a reader who has only
that file. The one exception is the finding-level block, and it is an exception
on purpose: see ``FindingObservation`` below.

What macro-F1 averages over, stated once
----------------------------------------

The union of the labels appearing in truth or in prediction. That is the honest
denominator, and it is the one P4's training script already used, so the two
agree. A label the model predicts and the answer key never carries is a class
the model is wrong about, and averaging it away would hide exactly that. A
label present in neither contributes nothing, because a class that did not occur
and was not guessed has no F1 to average: giving it a zero would let the
denominator be set by the size of the taxonomy rather than by the data.

Why this module does not import scikit-learn
--------------------------------------------

It is inside the shipped package, and scikit-learn is a development dependency.
An installed tool that could not compute its own metrics without the training
stack would be carrying the training stack. The arithmetic here is a dozen lines
and `tests/unit/test_metrics.py` checks it against scikit-learn on random data,
which is the right direction for that dependency to point.

The insufficient-data rule
--------------------------

``MIN_FIELDS_PER_REPORTED_CELL`` is enforced in code, not in a caveat in prose,
because a caveat in prose gets dropped when a table is copied into a report. A
cell below it reports its count and ``None`` for every metric plus an
``insufficient_data`` flag, and a renderer prints ``INSUFFICIENT_DATA``.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from autofill_audit.evaluate.runlog import RunLogRow
from autofill_audit.taxonomy import Label

__all__ = [
    "INSUFFICIENT_DATA",
    "MIN_FIELDS_PER_REPORTED_CELL",
    "PERCENTILES",
    "FindingObservation",
    "LabelMetrics",
    "PhaseTiming",
    "SliceCell",
    "abstention",
    "accuracy",
    "accuracy_columns",
    "calibration_report",
    "confusion_matrix",
    "confusion_pairs",
    "encode",
    "finding_metrics",
    "finding_precision_columns",
    "finding_recall_columns",
    "grid_json",
    "headline",
    "is_reportable",
    "label_report",
    "label_report_json",
    "latency_percentiles",
    "macro_f1",
    "macro_f1_columns",
    "micro_f1",
    "pair_count",
    "pair_grid",
    "slice_grid",
    "subset",
    "suppressed_cells",
]

MIN_FIELDS_PER_REPORTED_CELL: Final[int] = 30
"""A locale by tier cell needs at least this many fields before its accuracy is
reported as a percentage (spec section 8.5, recorded in ``docs/report.md``).

Spec section 8.5 states the reason plainly: a three-field cell showing "100%
accuracy" is a lie that formats correctly. The threshold is a policy decision
fixed at P1 and enforced by code from P5, rather than a judgement left to
whoever is writing the table.

Thirty is defensible and it is not measured. It is kept at P5 rather than
retuned, and the reason it is kept is worth one sentence: it was fixed before
any number existed, and moving it now, with the grid on screen, would be
choosing a reporting threshold in the knowledge of which cells it suppresses,
which is the decision law 4 exists to prevent."""

INSUFFICIENT_DATA: Final[str] = "insufficient data"
"""What a cell below the threshold renders as. A string rather than a blank,
because a blank cell reads as an oversight and this one is a decision."""

PERCENTILES: Final[tuple[int, ...]] = (50, 95, 99)
"""The latency percentiles spec section 13.2 asks for."""

_UNKNOWN: Final[str] = Label.UNKNOWN.value

RELIABILITY_BINS: Final[int] = 10
"""Equal-width bins over the winning class's probability. Ten, matching
``scripts/train.py``, so the dev curve and the test curve are the same shape and
a reader can put them side by side."""


def is_reportable(field_count: int) -> bool:
    """Return True when a cell holds enough fields to report as a percentage."""
    return field_count >= MIN_FIELDS_PER_REPORTED_CELL


# ---------------------------------------------------------------------------
# Label-level metrics.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LabelMetrics:
    """Precision, recall, F1 and both counts for one label.

    ``support`` is the number of rows whose truth is this label and ``predicted``
    the number of rows guessed as it. Both are carried because a precision of one
    over three predictions and a precision of one over three hundred are the same
    number and are not the same claim.
    """

    label: str
    precision: float
    recall: float
    f1: float
    support: int
    predicted: int

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "support": self.support,
            "predicted": self.predicted,
        }


def _divide(numerator: float, denominator: float) -> float:
    """Zero when the denominator is zero, matching ``zero_division=0``.

    An undefined ratio is reported as zero rather than as ``None`` here because
    the per-label table always shows its two counts beside the number, so a zero
    with a support of zero cannot be misread. The slice grid has no such column,
    which is why the insufficient-data rule exists there and not here.
    """
    return numerator / denominator if denominator else 0.0


def label_report(truth: Sequence[str], predicted: Sequence[str]) -> dict[str, LabelMetrics]:
    """Per-label precision, recall, F1 and both counts, over the observed union."""
    if len(truth) != len(predicted):
        raise ValueError(f"{len(truth)} truths against {len(predicted)} predictions")
    names = sorted(set(truth) | set(predicted))
    true_positive: Counter[str] = Counter()
    for actual, guess in zip(truth, predicted, strict=True):
        if actual == guess:
            true_positive[actual] += 1
    support = Counter(truth)
    guessed = Counter(predicted)
    report: dict[str, LabelMetrics] = {}
    for name in names:
        hits = true_positive[name]
        precision = _divide(hits, guessed[name])
        recall = _divide(hits, support[name])
        report[name] = LabelMetrics(
            label=name,
            precision=precision,
            recall=recall,
            f1=_divide(2 * precision * recall, precision + recall),
            support=support[name],
            predicted=guessed[name],
        )
    return report


def macro_f1(truth: Sequence[str], predicted: Sequence[str]) -> float:
    """Unweighted mean F1 over the labels appearing in truth or in prediction."""
    report = label_report(truth, predicted)
    if not report:
        return 0.0
    return sum(item.f1 for item in report.values()) / len(report)


def micro_f1(truth: Sequence[str], predicted: Sequence[str]) -> float:
    """Micro-averaged F1, which for single-label classification is accuracy.

    Reported alongside macro-F1 because spec section 13.2 asks for it and because
    it reflects what a user of a typical page experiences, where the common
    labels are most of the page. Stated here rather than left implicit: with one
    prediction per field and no abstention from the denominator, micro precision,
    micro recall, micro F1 and accuracy are the same number, and printing it four
    times under four names would suggest four measurements.
    """
    if not truth:
        return 0.0
    hits = sum(1 for actual, guess in zip(truth, predicted, strict=True) if actual == guess)
    return hits / len(truth)


def accuracy(truth: Sequence[str], predicted: Sequence[str]) -> float:
    """Fraction of rows whose prediction equals the answer key."""
    return micro_f1(truth, predicted)


# ---------------------------------------------------------------------------
# Slices, with the insufficient-data rule enforced.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SliceCell:
    """One cell of a per-locale, per-tier, or per-family grid.

    ``accuracy`` and ``macro_f1`` are ``None`` exactly when ``insufficient_data``
    is true. Two representations of one fact, kept together deliberately: the
    flag is what a renderer branches on and the null is what stops a consumer
    that ignored the flag from formatting a number that is not there.
    """

    name: str
    count: int
    accuracy: float | None
    macro_f1: float | None
    insufficient_data: bool

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "count": self.count,
            "accuracy": self.accuracy,
            "macro_f1": self.macro_f1,
            "insufficient_data": self.insufficient_data,
        }

    def render(self) -> str:
        """The cell as a table would print it, rule enforced."""
        if self.insufficient_data or self.macro_f1 is None:
            return f"{INSUFFICIENT_DATA} (n={self.count})"
        return f"{self.macro_f1:.4f} (n={self.count})"


def _cell(name: str, pairs: Sequence[tuple[str, str]]) -> SliceCell:
    """Build one grid cell, applying the reporting minimum."""
    enough = is_reportable(len(pairs))
    truth = [pair[0] for pair in pairs]
    guesses = [pair[1] for pair in pairs]
    return SliceCell(
        name=name,
        count=len(pairs),
        accuracy=accuracy(truth, guesses) if enough else None,
        macro_f1=macro_f1(truth, guesses) if enough else None,
        insufficient_data=not enough,
    )


def slice_grid(rows: Sequence[RunLogRow], key: str) -> dict[str, SliceCell]:
    """Group rows by one row attribute and report each group as a cell."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        groups.setdefault(str(getattr(row, key)), []).append((row.true_label, row.pred_label))
    return {name: _cell(name, pairs) for name, pairs in sorted(groups.items())}


def pair_grid(rows: Sequence[RunLogRow], first: str, second: str) -> dict[str, SliceCell]:
    """The locale by tier grid of spec section 13.4, keyed ``locale/tier``.

    This is the grid the insufficient-data rule was written for. The test split
    is the same size as the development split, but this grid is roughly
    twenty-four times finer than the one-dimensional slices, so cells here fall
    below the minimum where the single-axis cells do not.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        name = f"{getattr(row, first)}/{getattr(row, second)}"
        groups.setdefault(name, []).append((row.true_label, row.pred_label))
    return {name: _cell(name, pairs) for name, pairs in sorted(groups.items())}


def subset(rows: Sequence[RunLogRow], predicate: Callable[[RunLogRow], bool]) -> list[RunLogRow]:
    """The rows a predicate keeps, in order. A named helper so callers read."""
    return [row for row in rows if predicate(row)]


# ---------------------------------------------------------------------------
# Abstention.
# ---------------------------------------------------------------------------


def abstention(rows: Sequence[RunLogRow]) -> dict[str, Any]:
    """The rate of ``UNKNOWN`` and the accuracy on what was not abstained.

    Read off the label, never off the confidence. The n-gram engine reports an
    abstention at confidence exactly zero rather than at its calibrated
    probability, so a rule that tested the number would count a genuine
    low-confidence answer as an abstention and would miss nothing else.
    """
    committed = [row for row in rows if row.pred_label != _UNKNOWN]
    total = len(rows)
    return {
        "rows": total,
        "unknown": total - len(committed),
        "unknown_rate": _divide(total - len(committed), total),
        "committed": len(committed),
        "accuracy_when_committed": _divide(
            sum(1 for row in committed if row.correct), len(committed)
        ),
    }


# ---------------------------------------------------------------------------
# Confusion.
# ---------------------------------------------------------------------------


def confusion_matrix(rows: Sequence[RunLogRow]) -> dict[str, Any]:
    """The full matrix, as a labelled sparse mapping plus the label order.

    Sparse because the taxonomy has forty-two labels and a dense forty-two by
    forty-two grid of mostly zeros is larger than the run log that produced it
    and harder to read than the pairs. The label order is carried so a renderer
    can build the dense form without inventing an order of its own.
    """
    labels = sorted({row.true_label for row in rows} | {row.pred_label for row in rows})
    counts: Counter[tuple[str, str]] = Counter((row.true_label, row.pred_label) for row in rows)
    cells: dict[str, dict[str, int]] = {}
    for (actual, guess), count in sorted(counts.items()):
        cells.setdefault(actual, {})[guess] = count
    return {"labels": labels, "rows": len(rows), "cells": cells}


def confusion_pairs(rows: Sequence[RunLogRow], limit: int = 20) -> list[dict[str, Any]]:
    """The most frequent wrong pairs, which is what a write-up calls out."""
    counts: Counter[tuple[str, str]] = Counter(
        (row.true_label, row.pred_label) for row in rows if not row.correct
    )
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"truth": pair[0], "predicted": pair[1], "count": count} for pair, count in ordered[:limit]
    ]


def pair_count(rows: Sequence[RunLogRow], truth: str, predicted: str) -> int:
    """How often one specific confusion happened, in either direction's one sense."""
    return sum(1 for row in rows if row.true_label == truth and row.pred_label == predicted)


# ---------------------------------------------------------------------------
# Calibration.
# ---------------------------------------------------------------------------


def calibration_report(
    rows: Sequence[RunLogRow],
    *,
    exclude_labels: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Reliability curve and expected calibration error on the winning class.

    ``exclude_labels`` names classes whose calibrator was the identity, which is
    what a class with no development positives gets. Their probability is a raw
    softmax output, so a curve that pooled them with the rest would be averaging
    over two different things and calling the average calibration. P5 reports the
    number both ways and says which is which rather than choosing one.

    Abstentions are excluded from the curve in both variants. The n-gram engine
    reports them at confidence exactly zero by construction, so including them
    would put a spike of certain-to-be-wrong mass in the lowest bin that
    describes the abstention branch rather than the calibrator.
    """
    scored = [
        row for row in rows if row.pred_label != _UNKNOWN and row.pred_label not in exclude_labels
    ]
    total = len(scored)
    bins: list[dict[str, Any]] = []
    error = 0.0
    edges = [index / RELIABILITY_BINS for index in range(RELIABILITY_BINS + 1)]
    for position in range(RELIABILITY_BINS):
        low, high = edges[position], edges[position + 1]
        inside = [
            row
            for row in scored
            if (low < row.confidence <= high) or (position == 0 and row.confidence <= high)
        ]
        if not inside:
            bins.append({"low": low, "high": high, "count": 0})
            continue
        mean_predicted = sum(row.confidence for row in inside) / len(inside)
        mean_observed = sum(1 for row in inside if row.correct) / len(inside)
        bins.append(
            {
                "low": low,
                "high": high,
                "count": len(inside),
                "mean_predicted": mean_predicted,
                "mean_observed": mean_observed,
            }
        )
        error += (len(inside) / total) * abs(mean_predicted - mean_observed) if total else 0.0
    return {
        "scored_rows": total,
        "excluded_labels": sorted(exclude_labels),
        "excluded_rows": len(rows) - total,
        "bins": bins,
        "expected_calibration_error": error,
    }


# ---------------------------------------------------------------------------
# Latency.
# ---------------------------------------------------------------------------


def latency_percentiles(values: Sequence[float]) -> dict[str, float | None]:
    """p50, p95 and p99 of a latency sample, by linear interpolation.

    Linear interpolation between the two nearest order statistics, which is
    numpy's default and the one most readers assume. Named here because a p99
    over a sample of one hundred is entirely determined by which convention was
    used, and the two conventions disagree by the whole gap between the two
    largest values.
    """
    if not values:
        return {f"p{percentile}": None for percentile in PERCENTILES}
    ordered = sorted(values)
    result: dict[str, float | None] = {}
    for percentile in PERCENTILES:
        position = (percentile / 100) * (len(ordered) - 1)
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            result[f"p{percentile}"] = ordered[lower]
        else:
            weight = position - lower
            result[f"p{percentile}"] = ordered[lower] * (1 - weight) + ordered[upper] * weight
    return result


@dataclass(frozen=True, slots=True)
class PhaseTiming:
    """Whole-run wall time, split as spec section 13.2 asks.

    The split matters because if the browser's page load dominates then a
    difference in classifier latency is real and irrelevant to the user, and the
    report should say so rather than celebrate microseconds. ``render`` is the
    time spent emitting the run log and the metrics, which is this command's
    analogue of a report render; a run that emitted no report has to say what it
    put in that column rather than leave a zero that reads as a measurement.
    """

    load_s: float
    extract_s: float
    classify_s: float
    render_s: float
    total_s: float
    forms: int
    fields: int
    extraction_source: str

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "load_s": self.load_s,
            "extract_s": self.extract_s,
            "classify_s": self.classify_s,
            "render_s": self.render_s,
            "total_s": self.total_s,
            "forms": self.forms,
            "fields": self.fields,
            "extraction_source": self.extraction_source,
            "load_and_extract_share": _divide(self.load_s + self.extract_s, self.total_s),
        }


# ---------------------------------------------------------------------------
# Finding-level metrics.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FindingObservation:
    """One field, judged at the finding level rather than the label level.

    This is the one block in this module that is not computed from the run log
    alone, and the reason is worth stating rather than hiding. Whether a page
    *needed* an accusation depends on the difference between "declares nothing",
    "declares off", and "declares a token outside the specification", and spec
    section 13.1's row carries only ``declared_token``, which is null in all
    three cases. So the evaluation runner, which holds the descriptor, decides
    eligibility by calling the audit engine's own decision procedure, and hands
    the verdict here. The run log still records which codes actually fired, so
    the emitted counts remain checkable from the committed log by itself.

    Attributes:
        code: the finding code this observation is about.
        needed: the answer key says a correct page would declare something here.
        emitted: the engine, through its own thresholds, actually raised it.
        correct: the token the tool advised is equivalent to the key's label.
    """

    code: str
    template_id: str
    needed: bool
    emitted: bool
    correct: bool


def finding_metrics(observations: Sequence[FindingObservation], code: str) -> dict[str, Any]:
    """Precision and recall of one finding code, with both denominators.

    Precision is correct accusations over accusations. Recall is correct
    accusations over the fields that needed one.

    **The reporting minimum applies here too**, which is a decision P5 made and
    P4's handoff asked P5 to make. Each rate is suppressed independently, against
    its own denominator, because they have different ones and suppressing both on
    the smaller would hide a rate that is perfectly well supported.

    The reason is the one the constant was written for. The two engines in this
    comparison raise wildly different numbers of accusations, by construction:
    one has a pre-registered precision target and one has a tier mapping. A
    precision of 1.0 over fifteen accusations and a precision of 1.0 over fifteen
    hundred are the same number and are not the same claim, and the first of
    those is exactly what the rule exists to stop a table from printing as though
    it were the second. The counts are reported either way, so nothing is hidden;
    what is withheld is the invitation to read a rate off a denominator that
    cannot support one.
    """
    relevant = [item for item in observations if item.code == code]
    accusations = [item for item in relevant if item.emitted]
    correct = [item for item in accusations if item.correct]
    needed = [item for item in relevant if item.needed]
    precision = _divide(len(correct), len(accusations))
    recall = _divide(len(correct), len(needed))
    enough_accusations = is_reportable(len(accusations))
    enough_needed = is_reportable(len(needed))
    return {
        "code": code,
        "accusations": len(accusations),
        "correct_accusations": len(correct),
        "fields_needing_one": len(needed),
        "precision": precision if enough_accusations else None,
        "recall": recall if enough_needed else None,
        "f1": (
            _divide(2 * precision * recall, precision + recall)
            if enough_accusations and enough_needed
            else None
        ),
        "precision_insufficient_data": not enough_accusations,
        "recall_insufficient_data": not enough_needed,
        "minimum": MIN_FIELDS_PER_REPORTED_CELL,
    }


# ---------------------------------------------------------------------------
# The headline block.
# ---------------------------------------------------------------------------


def headline(rows: Sequence[RunLogRow]) -> dict[str, Any]:
    """Macro-F1, micro-F1, accuracy and the counts they were computed over."""
    truth = [row.true_label for row in rows]
    predicted = [row.pred_label for row in rows]
    return {
        "rows": len(rows),
        "forms": len({row.form_id for row in rows}),
        "templates": len({row.template_id for row in rows}),
        "labels_observed": len(set(truth) | set(predicted)),
        "macro_f1": macro_f1(truth, predicted),
        "micro_f1": micro_f1(truth, predicted),
        "accuracy": accuracy(truth, predicted),
    }


def label_report_json(rows: Sequence[RunLogRow]) -> dict[str, dict[str, Any]]:
    """The per-label table, ready to serialise."""
    report = label_report([row.true_label for row in rows], [row.pred_label for row in rows])
    return {name: item.to_json() for name, item in sorted(report.items())}


def grid_json(cells: Mapping[str, SliceCell]) -> dict[str, dict[str, Any]]:
    """Serialise a grid of cells."""
    return {name: cell.to_json() for name, cell in cells.items()}


def suppressed_cells(cells: Iterable[SliceCell]) -> list[str]:
    """The names of the cells the reporting minimum suppressed.

    Emitted into the result file so that a reader can see the rule fired without
    having to scan the grid for nulls, and so that a test can assert on it.
    """
    return sorted(cell.name for cell in cells if cell.insufficient_data)


# ---------------------------------------------------------------------------
# The same statistics, as array functions, for the permutation test.
# ---------------------------------------------------------------------------
#
# The significance test recomputes its statistic once per resampled arrangement,
# which is one thousand and twenty-four times for the exact test on this split
# and ten thousand times for the sampled one, so the loop above is the wrong
# shape for it. These are the same definitions over integer columns.
#
# There must be exactly one answer to "what is the macro-F1 of this run", so
# `tests/unit/test_metrics.py` asserts these agree with the functions above on
# the same data. Two implementations that are not checked against each other are
# two numbers waiting to disagree in a table.


def encode(values: Sequence[str], vocabulary: Sequence[str]) -> np.ndarray:
    """Map label strings onto their index in ``vocabulary``."""
    index = {name: position for position, name in enumerate(vocabulary)}
    return np.array([index[value] for value in values], dtype=np.int64)


def macro_f1_columns(columns: np.ndarray) -> float:
    """Macro-F1 from an ``(n, 2)`` array of ``[truth, prediction]`` label codes.

    Averaged over the codes present in truth or in prediction *in this array*,
    which is the same denominator ``macro_f1`` uses. It has to be recomputed per
    arrangement rather than fixed once, because a resampled arrangement can
    predict a label the observed one did not.
    """
    truth = columns[:, 0]
    predicted = columns[:, 1]
    width = int(max(truth.max(initial=-1), predicted.max(initial=-1))) + 1
    if width <= 0:
        return 0.0
    support = np.bincount(truth, minlength=width).astype(np.float64)
    guessed = np.bincount(predicted, minlength=width).astype(np.float64)
    hits = np.bincount(truth[truth == predicted], minlength=width).astype(np.float64)
    present = (support > 0) | (guessed > 0)
    if not present.any():
        return 0.0
    precision = np.divide(hits, guessed, out=np.zeros(width), where=guessed > 0)
    recall = np.divide(hits, support, out=np.zeros(width), where=support > 0)
    denominator = precision + recall
    f1 = np.divide(2 * precision * recall, denominator, out=np.zeros(width), where=denominator > 0)
    return float(f1[present].mean())


def accuracy_columns(columns: np.ndarray) -> float:
    """Accuracy from the same ``(n, 2)`` array."""
    if columns.shape[0] == 0:
        return 0.0
    return float((columns[:, 0] == columns[:, 1]).mean())


#: Column order of the finding-level array: needed, emitted, correct.
FINDING_NEEDED: Final[int] = 0
FINDING_EMITTED: Final[int] = 1
FINDING_CORRECT: Final[int] = 2


def finding_precision_columns(columns: np.ndarray) -> float:
    """Correct accusations over accusations, zero when nothing was accused."""
    emitted = columns[:, FINDING_EMITTED].astype(bool)
    if not emitted.any():
        return 0.0
    correct = columns[:, FINDING_CORRECT].astype(bool)
    return float((emitted & correct).sum() / emitted.sum())


def finding_recall_columns(columns: np.ndarray) -> float:
    """Correct accusations over the fields that needed one.

    The ``needed`` column is a property of the answer key rather than of the
    engine, so it is identical in both engines' arrays and the permutation's
    swap leaves it alone. That is why it can travel in the swapped array at all.
    """
    needed = columns[:, FINDING_NEEDED].astype(bool)
    if not needed.any():
        return 0.0
    emitted = columns[:, FINDING_EMITTED].astype(bool)
    correct = columns[:, FINDING_CORRECT].astype(bool)
    return float((emitted & correct).sum() / needed.sum())
