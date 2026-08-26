"""The boundary with the external evaluation harness (spec section 0.5).

Two kinds of test live here. The first checks the boundary itself: exactly one
module imports the harness, and that claim is about the whole repository so it is
checked by walking the repository rather than by reading one file. The second
checks the clustered paired permutation the bridge had to build because the
harness's public API has no entry point that accepts a cluster assignment.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pytest

from autofill_audit.evaluate import triage_bridge
from autofill_audit.evaluate.metrics import accuracy_columns, macro_f1_columns
from autofill_audit.evaluate.runlog import RunLogRow

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLE_IMPORTER = _REPO_ROOT / "src" / "autofill_audit" / "evaluate" / "triage_bridge.py"
_HARNESS_ROOTS = frozenset({"triage", "ml_experiment_triage"})


def _imported_roots(source: str) -> set[str]:
    """Every top-level package name a module imports."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _python_files() -> list[Path]:
    """Every Python file this repository owns, tests included."""
    files: list[Path] = []
    for directory in ("src", "scripts", "tests"):
        files.extend(sorted((_REPO_ROOT / directory).rglob("*.py")))
    return files


def test_exactly_one_module_imports_the_harness() -> None:
    """Spec section 0.5: `triage_bridge.py` is the only importer.

    Walked rather than asserted, because "only this module imports it" is a claim
    about every file in the repository and cannot be checked from inside one of
    them. This test file itself imports the bridge, never the harness.
    """
    importers = [
        path
        for path in _python_files()
        if _imported_roots(path.read_text(encoding="utf-8")) & _HARNESS_ROOTS
    ]
    assert importers == [_SOLE_IMPORTER], [str(path) for path in importers]


def test_the_bridge_does_not_reach_into_private_names() -> None:
    """Public API only: no `triage._x` anywhere in the one module that may import."""
    source = _SOLE_IMPORTER.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in (
            _HARNESS_ROOTS
        ):
            for alias in node.names:
                assert not alias.name.startswith("_"), alias.name


# ---------------------------------------------------------------------------
# What the harness makes of a spec section 13.1 run log.
# ---------------------------------------------------------------------------


def _row(**overrides: object) -> RunLogRow:
    fields: dict[str, object] = {
        "run_id": "r",
        "engine": "ngram",
        "engine_describe": {"engine": "ngram"},
        "corpus_manifest_sha": "a" * 64,
        "split": "test",
        "form_id": "f",
        "form_family": "checkout",
        "locale": "de-DE",
        "tier": "hostile",
        "template_id": "checkout-02",
        "selector": "#x",
        "true_label": "postal-code",
        "pred_label": "postal-code",
        "confidence": 0.9,
        "confidence_kind": "calibrated",
    }
    fields.update(overrides)
    return RunLogRow(**fields)  # type: ignore[arg-type]


def test_the_harness_claims_the_run_log_and_cannot_read_it(tmp_path: Path) -> None:
    """The friction this phase exists to find, pinned so it cannot go unnoticed.

    If a future harness release parses a spec section 13.1 run log, this test
    fails, and the correct response is to delete the local resampling scaffolding
    and close the ledger entry rather than to relax the assertion.
    """
    path = tmp_path / "run.jsonl"
    path.write_text(json.dumps(_row().to_json()) + "\n", encoding="utf-8")
    probe = triage_bridge.probe_native_ingestion(path)
    assert probe.claimed is True
    assert probe.parsed is False
    assert "step" in probe.detail


def test_a_file_the_harness_does_not_claim_is_reported_as_such(tmp_path: Path) -> None:
    path = tmp_path / "run.txt"
    path.write_text("not a log\n", encoding="utf-8")
    probe = triage_bridge.probe_native_ingestion(path)
    assert probe.claimed is False
    assert probe.parsed is False


# ---------------------------------------------------------------------------
# The clustered paired permutation.
# ---------------------------------------------------------------------------

POLICY = triage_bridge.StatisticalPolicy(resamples=200, seed=7)


def _comparison(
    clusters: tuple[str, ...], baseline: np.ndarray, candidate: np.ndarray
) -> triage_bridge.PairedComparison:
    return triage_bridge.PairedComparison(
        name="macro_f1/all",
        metric="macro_f1",
        slice_name="all",
        baseline_name="rules",
        candidate_name="ngram",
        clusters=clusters,
        baseline=baseline,
        candidate=candidate,
        statistic=macro_f1_columns,
    )


def _perfect_and_wrong(clusters: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    """One engine right on every row, the other wrong on every row."""
    size = len(clusters)
    truth = np.zeros(size, dtype=np.int64)
    right = np.column_stack([truth, truth])
    wrong = np.column_stack([truth, np.ones(size, dtype=np.int64)])
    return right, wrong


def test_the_space_is_two_to_the_cluster_count_and_the_test_is_exact() -> None:
    clusters = tuple(f"t{index // 4}" for index in range(20))
    baseline, candidate = _perfect_and_wrong(clusters)
    result = triage_bridge.run_comparison(_comparison(clusters, baseline, candidate), POLICY)
    assert result.n_clusters == 5
    assert result.exact is True
    assert result.n_arrangements == 32
    assert result.min_attainable_p == pytest.approx(2 / 32)


def test_five_clusters_cannot_reach_an_alpha_of_five_percent() -> None:
    """The property that decides every verdict in this project's primary family.

    Not an accident of the data: with five templates the sign-flip space holds
    thirty-two arrangements, so the smallest two sided p value the design can
    produce is 0.0625. That is above alpha, so no comparison clustered by
    template on this split can be significant, whatever the effect turns out to
    be, and the honest report of every one of them is that the design cannot
    reach alpha rather than that there is no difference.
    """
    clusters = tuple(f"t{index // 4}" for index in range(20))
    baseline, candidate = _perfect_and_wrong(clusters)
    decided = triage_bridge.adjust_family(
        [triage_bridge.run_comparison(_comparison(clusters, baseline, candidate), POLICY)],
        POLICY,
    )
    assert decided[0].min_attainable_p > POLICY.alpha
    assert decided[0].verdict == "inconclusive: the design cannot reach alpha"
    assert decided[0].at_design_floor is True


def test_many_clusters_reach_significance_on_the_same_effect() -> None:
    """The same difference, resampled at a finer clustering, is significant.

    Both halves of this pair matter. It shows the machinery can fire, so a green
    underpowered verdict elsewhere is not the test being broken, and it shows
    exactly what the clustering choice costs, which is why the choice is
    pre-registered rather than made after seeing the p value.
    """
    clusters = tuple(f"t{index}" for index in range(60))
    baseline, candidate = _perfect_and_wrong(clusters)
    result = triage_bridge.run_comparison(_comparison(clusters, baseline, candidate), POLICY)
    assert result.exact is False
    assert result.n_arrangements == POLICY.resamples
    decided = triage_bridge.adjust_family([result], POLICY)
    assert decided[0].p_value < POLICY.alpha
    assert decided[0].verdict == "regression"


def test_no_difference_gives_no_effect_and_the_largest_p() -> None:
    clusters = tuple(f"t{index // 4}" for index in range(20))
    baseline, _ = _perfect_and_wrong(clusters)
    result = triage_bridge.run_comparison(_comparison(clusters, baseline, baseline), POLICY)
    assert result.effect == pytest.approx(0.0)
    assert result.p_value == pytest.approx(1.0)


def test_the_family_correction_is_the_harnesss_own() -> None:
    """Benjamini Hochberg comes from the harness, not from a copy of it here.

    Reached through the bridge's re-export rather than by importing the harness,
    because this file is inside the scope of the sole-importer test above and
    reaching around the boundary to check the boundary would be self-defeating.
    """
    benjamini_hochberg = triage_bridge.benjamini_hochberg

    clusters = tuple(f"t{index // 4}" for index in range(20))
    baseline, candidate = _perfect_and_wrong(clusters)
    results = [
        triage_bridge.run_comparison(_comparison(clusters, baseline, candidate), POLICY),
        triage_bridge.run_comparison(_comparison(clusters, baseline, baseline), POLICY),
    ]
    decided = triage_bridge.adjust_family(results, POLICY)
    expected = benjamini_hochberg([item.p_value for item in results], POLICY.false_discovery_rate)
    assert [item.adjusted_p for item in decided] == pytest.approx(list(expected))


def test_the_practical_gate_is_absolute_and_not_relative() -> None:
    """The one gate the harness could not supply, checked on its own terms.

    An effect of one hundredth of a point of macro-F1 against a pre-registered
    absolute threshold of two hundredths fails the practical gate, whatever its
    size relative to the baseline, which for a small baseline can be enormous.
    """
    policy = triage_bridge.StatisticalPolicy(practical_threshold=0.02, resamples=200, seed=7)
    clusters = tuple(f"t{index % 60}" for index in range(1000))
    truth = np.zeros(len(clusters), dtype=np.int64)
    baseline = np.column_stack([truth, truth])
    candidate = baseline.copy()
    candidate[0, 1] = 1
    comparison = triage_bridge.PairedComparison(
        name="accuracy/all",
        metric="accuracy",
        slice_name="all",
        baseline_name="rules",
        candidate_name="ngram",
        clusters=clusters,
        baseline=baseline,
        candidate=candidate,
        statistic=accuracy_columns,
    )
    result = triage_bridge.run_comparison(comparison, policy)
    decided = triage_bridge.adjust_family([result], policy)[0]
    assert abs(decided.effect) == pytest.approx(0.001)
    assert abs(decided.relative_effect_pct) < 1.0
    assert decided.passes_practical_gate is False


def test_the_two_engines_must_be_scored_on_the_same_units() -> None:
    clusters = ("t0", "t0", "t1")
    baseline, _ = _perfect_and_wrong(clusters)
    with pytest.raises(ValueError, match="same units"):
        _comparison(clusters, baseline, baseline[:2])


def test_the_verdict_vocabulary_is_the_harnesss_own() -> None:
    """Nothing downstream invents a fifth word for an outcome."""
    assert len(set(triage_bridge.VERDICTS)) == 5
    assert "significant but below the practical threshold" in triage_bridge.VERDICTS


def test_the_harness_cross_check_rejoins_its_reordered_output() -> None:
    """`classify` returns severity order, so a positional zip would mislabel.

    The harness ranks its findings before returning them, and the tag this
    project passes is not unique across slices, so the only key that rejoins a
    finding to its comparison is the identity of the result object. This test
    fails if that rejoin is ever replaced by a positional one.
    """
    clusters = tuple(f"t{index}" for index in range(60))
    baseline, candidate = _perfect_and_wrong(clusters)
    results = triage_bridge.adjust_family(
        [
            triage_bridge.run_comparison(_comparison(clusters, baseline, baseline), POLICY),
            triage_bridge.run_comparison(_comparison(clusters, baseline, candidate), POLICY),
        ],
        POLICY,
    )
    cross = triage_bridge.harness_native_verdicts(results, POLICY)
    assert [item["harness_verdict"] for item in cross] == [
        "no significant change",
        "regression",
    ]
