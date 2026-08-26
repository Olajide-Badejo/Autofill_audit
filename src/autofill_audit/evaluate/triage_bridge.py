"""The only module permitted to import the external evaluation harness.

Public API only: no monkey-patching, no subclassing around a limitation, no
reaching into internals. Insufficiency of the public API is a cross-repo task
recorded in ``docs/cross-repo-tasks.md``, never a local workaround (spec section
0.5). `tests/unit/test_triage_bridge.py` scans every module in the package and
in `scripts/` and fails if a second importer appears, because "only this module
imports it" is a claim about the whole repository and cannot be checked from
inside one file.

What the harness does and does not do for this project
------------------------------------------------------

The harness was built to compare training runs: its unit of analysis is a run,
its data model is a tagged step series, and its permutation test shuffles a
condition label across runs. This project's unit of analysis is a form field,
its outcome is categorical, its fields are clustered inside templates, and its
two engines see the identical field set, which makes the comparison paired. The
overlap between those two shapes is smaller than either repository's
documentation implied, and finding out exactly where it ends is the deliverable
of this phase rather than an obstacle to it.

Three pieces of the harness fit this project exactly and are used unchanged:

``permutation_p_value``
    Turns an observed effect and a null distribution into a two sided p value,
    with the add-one correction that keeps a sampled p value from being reported
    as zero. It takes the null as an argument, which is precisely the seam a
    caller with its own resampling scheme needs.
``benjamini_hochberg``
    Step up adjusted p values across a family of comparisons. Spec section 13.3
    asks for exactly this and the harness implements exactly this.
``classify`` and the ``VERDICT_*`` vocabulary
    The three way outcome spec section 13.3 point 4 demands, plus a fourth for a
    design that cannot reach alpha, which turned out to be the category this
    project's test split lands in.

One piece does not fit and is built here, under protest recorded in the ledger:

**the clustered paired resampling itself.** Nothing in the harness's public API
accepts a cluster assignment, and spec section 13.3 calls clustering
non-negotiable rather than a nicety, because unclustered resampling on this
corpus produces intervals that are too narrow and therefore claimed significance
that is not there. So the null distribution is built here, at the template
level, and handed to the harness's p value estimator. That arrangement is
labelled in every result file it produces and is filed as a cross-repo task with
a concrete API proposal. It is not a silent degradation to unclustered
resampling, which is the one thing that was forbidden outright.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
from triage.analysis.comparison import (
    ComparisonResult,
    permutation_p_value,
)
from triage.analysis.regression import (
    VERDICT_BELOW_THRESHOLD,
    VERDICT_IMPROVEMENT,
    VERDICT_NO_CHANGE,
    VERDICT_REGRESSION,
    VERDICT_UNDERPOWERED,
    RegressionConfig,
    benjamini_hochberg,
    classify,
)
from triage.parsers import JsonlParser, ParseError

__all__ = [
    "DEFAULT_RESAMPLES",
    "EXHAUSTIVE_LIMIT",
    "TRIAGE_DISTRIBUTION",
    "VERDICTS",
    "ClusteredPairedResult",
    "NativeIngestion",
    "PairedComparison",
    "StatisticalPolicy",
    "adjust_family",
    "benjamini_hochberg",
    "harness_native_verdicts",
    "harness_version",
    "probe_native_ingestion",
    "run_comparison",
]

TRIAGE_DISTRIBUTION: Final[str] = "ml-experiment-triage"
"""The distribution name, for the manifest's resolved dependency block."""

DEFAULT_RESAMPLES: Final[int] = 10000
"""Resamples when the sign-flip space is too large to enumerate.

Ten thousand is the pre-registered figure and it is also the harness's own
default, so the two agree and neither had to be bent to the other."""

EXHAUSTIVE_LIMIT: Final[int] = 50000
"""Enumerate every sign vector when there are no more than this many.

The same limit the harness uses for its own label permutations. With five test
templates the space is thirty-two vectors, so the primary analysis in this
project is exact rather than sampled, and the p values it reports are the exact
permutation p values rather than Monte Carlo estimates of them."""

VERDICTS: Final[tuple[str, ...]] = (
    VERDICT_IMPROVEMENT,
    VERDICT_REGRESSION,
    VERDICT_BELOW_THRESHOLD,
    VERDICT_NO_CHANGE,
    VERDICT_UNDERPOWERED,
)
"""The harness's verdict vocabulary, re-exported so that nothing downstream
invents a fifth word for a result. Spec section 13.3 names three categories and
insists the middle one is not dropped; the harness supplies those three under
``IMPROVEMENT`` or ``REGRESSION``, ``BELOW_THRESHOLD``, and ``NO_CHANGE``, and
adds ``UNDERPOWERED`` for a design whose smallest attainable p value is already
above alpha."""


# ``benjamini_hochberg`` is named in ``__all__`` above. It is the harness's own
# function, imported and not wrapped, re-exported so that a caller who needs it
# does not have to import the harness itself and break the sole-importer rule.
# Keeping the boundary one module wide is the point of that rule, and a second
# importer added "just for a test" is how such a boundary stops being one.


def harness_version() -> str:
    """The installed harness version, for the manifest."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(TRIAGE_DISTRIBUTION)
    except PackageNotFoundError:  # pragma: no cover - the lock file installs it
        return "absent"


# ---------------------------------------------------------------------------
# What the harness makes of a spec section 13.1 run log, unmodified.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NativeIngestion:
    """What the harness's own log parser did with an unmodified run log.

    Recorded in every analysis result file rather than described in prose,
    because "the schemas disagree" is the finding this phase exists to produce
    and a finding that lives only in a paragraph is a finding nobody can check.
    """

    path: str
    parser: str
    claimed: bool
    parsed: bool
    detail: str

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "path": self.path,
            "parser": self.parser,
            "claimed_the_file": self.claimed,
            "parsed_the_file": self.parsed,
            "detail": self.detail,
        }


def probe_native_ingestion(path: Path) -> NativeIngestion:
    """Hand the harness's own parser an unmodified run log and record the result.

    The run log is passed exactly as it was written. Nothing is rewritten, no
    temporary reshaped copy is made, and no key is added to make the parse
    succeed: spec section 0.5 forbids post-processing a run log into a
    harness-specific shape, and adding a step counter to a file that has no time
    axis would be inventing a number to satisfy a parser.
    """
    parser = JsonlParser()
    name = type(parser).__name__
    claimed = parser.can_parse(path)
    if not claimed:
        return NativeIngestion(
            path=str(path),
            parser=name,
            claimed=False,
            parsed=False,
            detail="the parser did not recognise the file",
        )
    try:
        experiment = parser.parse(path)
    except (ParseError, ValueError) as error:
        return NativeIngestion(
            path=str(path), parser=name, claimed=True, parsed=False, detail=str(error)
        )
    return NativeIngestion(
        path=str(path), parser=name, claimed=True, parsed=True, detail=experiment.summary()
    )


# ---------------------------------------------------------------------------
# The statistical policy, fixed before any measurement.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatisticalPolicy:
    """Every knob of the procedure, in one object so a result file can print it.

    ``practical_threshold`` is an **absolute** difference in the metric, not a
    relative percentage. That is what was pre-registered, and it is the one place
    the harness's own gate could not be used: its practical gate reads
    ``relative_effect_pct``, so expressing an absolute macro-F1 difference of two
    hundredths through it would mean writing a relative number into a field whose
    name says it is relative and whose value would not be. The gap is in the
    ledger with a proposed API.
    """

    alpha: float = 0.05
    false_discovery_rate: float = 0.05
    practical_threshold: float = 0.02
    resamples: int = DEFAULT_RESAMPLES
    exhaustive_limit: int = EXHAUSTIVE_LIMIT
    seed: int = 20260825
    cluster_unit: str = "template_id"

    def describe(self) -> str:
        """One line naming the whole procedure, for a result file's header."""
        return (
            f"paired permutation clustered by {self.cluster_unit}, sign flips at the "
            f"cluster level, exhaustive when the space is at most "
            f"{self.exhaustive_limit} vectors and {self.resamples} resamples otherwise; "
            f"Benjamini Hochberg across the comparison family at a false discovery rate "
            f"of {self.false_discovery_rate:g}; a difference counts as practical at an "
            f"absolute {self.practical_threshold:g} in the metric"
        )

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "alpha": self.alpha,
            "false_discovery_rate": self.false_discovery_rate,
            "practical_threshold_absolute": self.practical_threshold,
            "resamples": self.resamples,
            "exhaustive_limit": self.exhaustive_limit,
            "seed": self.seed,
            "cluster_unit": self.cluster_unit,
            "description": self.describe(),
        }


# ---------------------------------------------------------------------------
# The clustered paired permutation this project needs and the harness has not.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PairedComparison:
    """One comparison: two engines, the same units, one statistic, one slice.

    Attributes:
        name: how the comparison is named in the result file and in the family.
        metric: the statistic's name, for the result file.
        slice_name: which slice of the split these units are, ``all`` for none.
        baseline_name, candidate_name: the two engines, in that order.
        clusters: one cluster label per unit, the resampling unit.
        baseline, candidate: an ``(n, w)`` integer array per engine. The columns
            are whatever ``statistic`` reads; they are swapped between the two
            engines wholesale, so a column that is a property of the field rather
            than of the engine (the answer key's label, for instance) is
            identical in both and swapping it is a no-op.
        statistic: maps one ``(n, w)`` array to the metric.
        higher_is_better: which direction of the effect counts as the candidate
            winning.
    """

    name: str
    metric: str
    slice_name: str
    baseline_name: str
    candidate_name: str
    clusters: tuple[str, ...]
    baseline: np.ndarray
    candidate: np.ndarray
    statistic: Callable[[np.ndarray], float]
    higher_is_better: bool = True

    def __post_init__(self) -> None:
        if self.baseline.shape != self.candidate.shape:
            raise ValueError(
                f"{self.name}: the two engines must be scored on the same units; "
                f"got {self.baseline.shape} against {self.candidate.shape}"
            )
        if len(self.clusters) != self.baseline.shape[0]:
            raise ValueError(
                f"{self.name}: {len(self.clusters)} cluster labels for "
                f"{self.baseline.shape[0]} units"
            )


@dataclass(frozen=True, slots=True)
class ClusteredPairedResult:
    """One comparison, tested. Everything needed to justify the number is here."""

    name: str
    metric: str
    slice_name: str
    baseline_name: str
    candidate_name: str
    baseline_statistic: float
    candidate_statistic: float
    effect: float
    relative_effect_pct: float
    p_value: float
    adjusted_p: float | None
    min_attainable_p: float
    n_units: int
    n_clusters: int
    n_arrangements: int
    exact: bool
    cluster_unit: str
    higher_is_better: bool
    verdict: str | None = None
    passes_statistical_gate: bool | None = None
    passes_practical_gate: bool | None = None

    @property
    def improved(self) -> bool:
        """True when the candidate moved the metric in the good direction."""
        return self.effect > 0 if self.higher_is_better else self.effect < 0

    @property
    def at_design_floor(self) -> bool:
        """Whether the p value is the smallest this design could have produced.

        Worth its own field because of what it means when the design cannot
        reach alpha. A p value equal to the floor says the observed difference
        was more extreme than every other arrangement the clustered permutation
        permits: it is the strongest evidence the design can produce, and it is
        still not significance. Reporting the p value alone would let a reader
        read 0.0625 as a near miss that more of the same data would fix, and it
        is not: it is the floor of this split's template count.
        """
        return self.p_value <= self.min_attainable_p + 1e-12

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form."""
        return {
            "name": self.name,
            "metric": self.metric,
            "slice": self.slice_name,
            "baseline": self.baseline_name,
            "candidate": self.candidate_name,
            "baseline_statistic": self.baseline_statistic,
            "candidate_statistic": self.candidate_statistic,
            "effect": self.effect,
            "relative_effect_pct": self.relative_effect_pct,
            "p_value": self.p_value,
            "adjusted_p": self.adjusted_p,
            "min_attainable_p": self.min_attainable_p,
            "units": self.n_units,
            "clusters": self.n_clusters,
            "arrangements": self.n_arrangements,
            "exact": self.exact,
            "at_design_floor": self.at_design_floor,
            "cluster_unit": self.cluster_unit,
            "higher_is_better": self.higher_is_better,
            "improved": self.improved,
            "verdict": self.verdict,
            "passes_statistical_gate": self.passes_statistical_gate,
            "passes_practical_gate": self.passes_practical_gate,
        }


def _cluster_masks(
    clusters: Sequence[str], policy: StatisticalPolicy
) -> tuple[np.ndarray, bool, int]:
    """Row-level swap masks, one per sign vector over the clusters.

    Returns the ``(arrangements, n_units)`` boolean matrix, whether the
    enumeration was exhaustive, and the size of the full sign-flip space.

    The exchangeability being asserted is the one spec section 13.3 states: under
    the null, the two engines' outcomes are exchangeable *within a template*, and
    a whole template flips together because fields inside it share an author and
    are not independent. Flipping fields individually would be the unclustered
    test, which on this corpus produces intervals too narrow to believe.
    """
    names = sorted(set(clusters))
    index = {name: position for position, name in enumerate(names)}
    membership = np.array([index[name] for name in clusters], dtype=np.int64)
    count = len(names)
    space = 2**count

    if space <= policy.exhaustive_limit:
        vectors = np.array(list(itertools.product([False, True], repeat=count)), dtype=bool)
        return vectors[:, membership], True, space

    rng = np.random.default_rng(policy.seed)
    vectors = rng.random((policy.resamples, count)) < 0.5
    return vectors[:, membership], False, space


def run_comparison(
    comparison: PairedComparison, policy: StatisticalPolicy
) -> ClusteredPairedResult:
    """Test one comparison by a template-clustered paired permutation.

    The null distribution is built here because no public entry point of the
    harness accepts a cluster assignment. The p value is computed *by the
    harness*, from that null, through ``permutation_p_value``, so the estimator
    with its add-one correction is the harness's and not a second implementation
    of it living in this repository.
    """
    masks, exact, space = _cluster_masks(comparison.clusters, policy)
    baseline, candidate = comparison.baseline, comparison.candidate

    observed_baseline = float(comparison.statistic(baseline))
    observed_candidate = float(comparison.statistic(candidate))
    observed = observed_candidate - observed_baseline

    null = np.empty(masks.shape[0], dtype=np.float64)
    for position in range(masks.shape[0]):
        swap = masks[position][:, None]
        pseudo_baseline = np.where(swap, candidate, baseline)
        pseudo_candidate = np.where(swap, baseline, candidate)
        null[position] = comparison.statistic(pseudo_candidate) - comparison.statistic(
            pseudo_baseline
        )

    p_value = permutation_p_value(observed, null, exact)
    min_attainable = 2.0 / space if exact else 1.0 / (1 + policy.resamples)

    return ClusteredPairedResult(
        name=comparison.name,
        metric=comparison.metric,
        slice_name=comparison.slice_name,
        baseline_name=comparison.baseline_name,
        candidate_name=comparison.candidate_name,
        baseline_statistic=observed_baseline,
        candidate_statistic=observed_candidate,
        effect=observed,
        relative_effect_pct=(100.0 * observed / observed_baseline if observed_baseline else 0.0),
        p_value=float(p_value),
        adjusted_p=None,
        min_attainable_p=float(min_attainable),
        n_units=int(baseline.shape[0]),
        n_clusters=len(set(comparison.clusters)),
        n_arrangements=int(masks.shape[0]),
        exact=exact,
        cluster_unit=policy.cluster_unit,
        higher_is_better=comparison.higher_is_better,
    )


def adjust_family(
    results: Sequence[ClusteredPairedResult], policy: StatisticalPolicy
) -> list[ClusteredPairedResult]:
    """Apply the harness's Benjamini Hochberg correction across the family.

    The family is every comparison passed in one call, which is exactly the set
    spec section 13.3 names: engine pairs by metrics by slices. Correcting inside
    a smaller family and calling it the family would be the standard way to
    manufacture a significant result, so the caller passes the whole thing and
    the result file records how many comparisons were in it.

    The three way classification is applied here rather than by the harness's own
    ``classify``. The statistical gate and the underpowered gate are identical to
    the harness's; the practical gate is not, because the harness compares a
    relative percentage against a relative threshold and this project
    pre-registered an absolute one. ``harness_native_verdicts`` runs the harness's
    own gate over the same results so the difference is visible rather than
    asserted.
    """
    if not results:
        return []
    adjusted = benjamini_hochberg([item.p_value for item in results], policy.false_discovery_rate)
    decided: list[ClusteredPairedResult] = []
    for item, adjusted_p in zip(results, adjusted, strict=True):
        statistical = bool(adjusted_p < policy.alpha)
        practical = bool(abs(item.effect) >= policy.practical_threshold)
        if item.min_attainable_p > policy.alpha:
            verdict = VERDICT_UNDERPOWERED
        elif statistical and practical:
            verdict = VERDICT_IMPROVEMENT if item.improved else VERDICT_REGRESSION
        elif statistical:
            verdict = VERDICT_BELOW_THRESHOLD
        else:
            verdict = VERDICT_NO_CHANGE
        decided.append(
            ClusteredPairedResult(
                name=item.name,
                metric=item.metric,
                slice_name=item.slice_name,
                baseline_name=item.baseline_name,
                candidate_name=item.candidate_name,
                baseline_statistic=item.baseline_statistic,
                candidate_statistic=item.candidate_statistic,
                effect=item.effect,
                relative_effect_pct=item.relative_effect_pct,
                p_value=item.p_value,
                adjusted_p=float(adjusted_p),
                min_attainable_p=item.min_attainable_p,
                n_units=item.n_units,
                n_clusters=item.n_clusters,
                n_arrangements=item.n_arrangements,
                exact=item.exact,
                cluster_unit=item.cluster_unit,
                higher_is_better=item.higher_is_better,
                verdict=verdict,
                passes_statistical_gate=statistical,
                passes_practical_gate=practical,
            )
        )
    return decided


_HARNESS_MODE: Final[str] = "template_clustered_paired"
"""The mode string written onto a harness ``ComparisonResult``.

The harness's ``mode`` field is a plain string with no validation, and two of its
derived members, ``mode_label`` and ``to_dict``, look the value up in a private
table of the two training modes and raise ``KeyError`` on anything else. So the
truthful value is written, those two members are not called, and the gap is in
the ledger. Writing ``seed_replicate`` instead would make both members work and
would be a lie about which test ran."""


def harness_native_verdicts(
    results: Sequence[ClusteredPairedResult], policy: StatisticalPolicy
) -> list[dict[str, Any]]:
    """Run the harness's own end to end verdict machinery over the same results.

    This exists to make one specific gap concrete rather than argued. The harness
    computes the same Benjamini Hochberg adjustment and the same statistical and
    underpowered gates, so where its verdict differs from this project's, the
    difference is entirely its practical gate reading a relative percentage where
    this project pre-registered an absolute difference. The result file records
    both verdicts side by side and names which comparisons they disagree on.
    """
    if not results:
        return []
    native = [
        ComparisonResult(
            tag=item.metric,
            baseline=item.baseline_name,
            candidate=item.candidate_name,
            mode=_HARNESS_MODE,
            test_name="two sided paired permutation test, sign flips clustered by template",
            baseline_statistic=item.baseline_statistic,
            candidate_statistic=item.candidate_statistic,
            effect=item.effect,
            relative_effect_pct=item.relative_effect_pct,
            effect_size=0.0,
            effect_size_name="not computed: the outcome is categorical",
            ci_low=float("nan"),
            ci_high=float("nan"),
            ci_method="not computed: no interval is pre-registered",
            ci_level=0.0,
            p_value=item.p_value,
            n_permutations=item.n_arrangements,
            exact=item.exact,
            min_attainable_p=item.min_attainable_p,
            n_baseline=item.n_units,
            n_candidate=item.n_units,
            window_points=0,
            higher_is_better=item.higher_is_better,
            seed=policy.seed,
        )
        for item in results
    ]
    config = RegressionConfig(
        alpha=policy.alpha,
        # The harness's gate is relative. The pre-registered threshold is
        # absolute, so there is no faithful value to put here; the relative
        # equivalent of the pre-registered absolute threshold at this project's
        # baseline is recorded in the result file instead, and this run is
        # labelled as the harness's own gate rather than as the policy's.
        practical_threshold_pct=100.0 * policy.practical_threshold,
        false_discovery_rate=policy.false_discovery_rate,
    )
    # `classify` returns `rank(findings)`, so its output order is severity order
    # and not the order it was given. Its `tag` is this project's metric name,
    # which is not unique: macro-F1 is compared across seven slices, so seven
    # findings share a tag. The only key that rejoins a finding to the comparison
    # it came from is the identity of the `result` object the finding carries, so
    # that is what is used. Filed in the ledger with the obvious proposal, which
    # is that `classify` return in input order given that `rank` is already
    # public and a caller who wants severity order can call it.
    position = {id(item): index for index, item in enumerate(native)}
    findings = classify(native, config)
    rejoined = sorted(findings, key=lambda finding: position[id(finding.result)])
    return [
        {
            "name": item.name,
            "metric": finding.tag,
            "harness_verdict": finding.verdict,
            "harness_adjusted_p": finding.adjusted_p,
            "harness_practical_gate": finding.passes_practical_gate,
            "harness_statistical_gate": finding.passes_statistical_gate,
            "harness_explanation": finding.explain(),
            "project_verdict": item.verdict,
            "agrees": finding.verdict == item.verdict,
        }
        for item, finding in zip(results, rejoined, strict=True)
    ]
