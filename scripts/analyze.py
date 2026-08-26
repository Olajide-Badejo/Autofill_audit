#!/usr/bin/env python3
"""Compare two engines' run logs through the external evaluation harness.

Spec section 13.3, end to end: a paired permutation test clustered by template,
Benjamini Hochberg across the comparison family, and a three way outcome in
which the middle category is reported rather than quietly promoted.

The run logs are read exactly as they were written. Nothing is rewritten, no
reshaped copy is made, and the first thing this script records is what the
harness's own log parser makes of an unmodified run log, because that answer is
the finding this phase exists to produce.

The two clusterings, and why both are here
------------------------------------------

The **primary** analysis clusters by template, which is what spec section 13.3
requires and what the policy file pre-registered. The test split holds ten
templates, two per family, because P1's leakage rule assigns whole templates to
partitions and P5R widened the grid to eight per family for exactly this reason.
Ten clusters give a paired sign-flip space of one thousand and twenty-four
arrangements, so the test is exact rather than sampled and its smallest
attainable two sided p value is two orders of magnitude below the pre-registered
alpha.

It was not always so, and the reason the number matters is worth keeping here.
At one test template per family the space held thirty-two arrangements and its
floor sat above alpha, so no comparison in the primary analysis could reach
significance at any effect size, and the correct report of every one of them was
"the design cannot reach alpha" rather than "no significant difference". Those
two sentences mean different things, the verdict vocabulary still carries both,
and the underpowered verdict remains reachable: a slice thin enough to lose
clusters can still hit it.

The **secondary** analysis clusters by form. It is reported because an effect
that is invisible at ten clusters and obvious at two hundred and forty is worth
seeing, and it is labelled everywhere it appears, because clustering by form
asserts that two locales of one template are independent, which is a stronger
assumption than spec section 13.3 makes and is therefore anticonservative
relative to the pre-registered test. It is not the headline and nothing in the
README cites it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import eval as evaluate  # noqa: E402
from autofill_audit.audit.findings import FindingCode  # noqa: E402
from autofill_audit.evaluate import metrics, runlog, triage_bridge  # noqa: E402

ANALYSIS_FILENAME = "analysis.json"

TIERS = ("clean", "partial", "mixed", "hostile")

FINDING_CODES = (
    FindingCode.MISSING_AUTOCOMPLETE.value,
    FindingCode.WRONG_AUTOCOMPLETE.value,
)


@dataclass(frozen=True, slots=True)
class Run:
    """One engine's committed run directory, read back."""

    directory: Path
    rows: list[runlog.RunLogRow]
    findings: list[dict[str, Any]]
    manifest: dict[str, Any]

    @property
    def engine(self) -> str:
        """The engine that produced it, from its own manifest."""
        return str(self.manifest["engine"])

    @property
    def run_id(self) -> str:
        """The run id, from its own manifest."""
        return str(self.manifest["run_id"])


def load_run(directory: Path) -> Run:
    """Read a run directory back: the log, the finding judgements, the manifest."""
    rows = runlog.read_rows(directory / runlog.RUNLOG_FILENAME)
    findings_path = directory / evaluate.FINDINGS_FILENAME
    findings = [
        json.loads(line)
        for line in findings_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = runlog.read_manifest(directory / runlog.MANIFEST_FILENAME)
    return Run(directory=directory, rows=rows, findings=findings, manifest=manifest)


def align(baseline: Run, candidate: Run) -> None:
    """Refuse to compare two runs that did not see the same fields.

    Pairing is the whole reason the test has any power at all, and pairing rows
    that are not the same field would be worse than not pairing: it would give a
    variance reduction that the data does not support. Both runs come from the
    same corpus through the same extraction, so the sequences agree; checking is
    cheap and the failure it catches would be silent.
    """
    left = [(row.form_id, row.selector) for row in baseline.rows]
    right = [(row.form_id, row.selector) for row in candidate.rows]
    if left != right:
        raise SystemExit(
            f"{baseline.run_id} and {candidate.run_id} did not classify the same fields "
            f"in the same order: {len(left)} against {len(right)}. A paired test needs "
            "the identical field set."
        )
    if baseline.manifest["split"] != candidate.manifest["split"]:
        raise SystemExit("the two runs are on different splits")
    if baseline.manifest["corpus_manifest_sha"] != candidate.manifest["corpus_manifest_sha"]:
        raise SystemExit("the two runs are against different corpora")


# ---------------------------------------------------------------------------
# Building the comparison family.
# ---------------------------------------------------------------------------


def _label_columns(
    rows: Sequence[runlog.RunLogRow], other: Sequence[runlog.RunLogRow]
) -> tuple[np.ndarray, np.ndarray]:
    """Encode both engines' truth and prediction against one shared vocabulary."""
    vocabulary = sorted(
        {row.true_label for row in rows}
        | {row.pred_label for row in rows}
        | {row.pred_label for row in other}
    )
    first = np.column_stack(
        [
            metrics.encode([row.true_label for row in rows], vocabulary),
            metrics.encode([row.pred_label for row in rows], vocabulary),
        ]
    )
    second = np.column_stack(
        [
            metrics.encode([row.true_label for row in other], vocabulary),
            metrics.encode([row.pred_label for row in other], vocabulary),
        ]
    )
    return first, second


def _finding_columns(records: Sequence[Mapping[str, Any]]) -> np.ndarray:
    """Encode the finding judgements as the three integer columns."""
    return np.array(
        [[int(item["needed"]), int(item["emitted"]), int(item["correct"])] for item in records],
        dtype=np.int64,
    ).reshape(-1, 3)


def label_comparisons(
    baseline: Run,
    candidate: Run,
    unseen_forms: frozenset[str],
    cluster_key: str,
) -> list[triage_bridge.PairedComparison]:
    """Macro-F1 on the whole split, on both locale slices, and per tier."""
    slices: list[tuple[str, Callable[[runlog.RunLogRow], bool]]] = [
        ("all", lambda row: True),
        ("seen_locales", lambda row: row.form_id not in unseen_forms),
        ("unseen_locale", lambda row: row.form_id in unseen_forms),
    ]
    slices.extend((f"tier:{tier}", (lambda t: lambda row: row.tier == t)(tier)) for tier in TIERS)

    comparisons: list[triage_bridge.PairedComparison] = []
    for name, keep in slices:
        indices = [index for index, row in enumerate(baseline.rows) if keep(row)]
        if not indices:
            continue
        left = [baseline.rows[index] for index in indices]
        right = [candidate.rows[index] for index in indices]
        first, second = _label_columns(left, right)
        comparisons.append(
            triage_bridge.PairedComparison(
                name=f"macro_f1/{name}",
                metric="macro_f1",
                slice_name=name,
                baseline_name=baseline.engine,
                candidate_name=candidate.engine,
                clusters=tuple(str(getattr(row, cluster_key)) for row in left),
                baseline=first,
                candidate=second,
                statistic=metrics.macro_f1_columns,
            )
        )
    return comparisons


def finding_comparisons(
    baseline: Run, candidate: Run, cluster_key: str
) -> list[triage_bridge.PairedComparison]:
    """Finding-level precision and recall, per accusation code.

    Read the write-up sentence that has to accompany every one of these: a
    finding-level comparison between these two engines is **not** a comparison of
    two classifiers. It is a comparison of a classifier plus a pre-registered
    precision target against a rule table plus a documented tier mapping, and the
    two engines' confidences are on scales that were never the same quantity. The
    number is still the one a user experiences, which is why it is here, but a
    table that put the two recalls side by side without that sentence would be
    reporting the answers to two different questions as if they answered one.
    """
    comparisons: list[triage_bridge.PairedComparison] = []
    for code in FINDING_CODES:
        left = [item for item in baseline.findings if item["code"] == code]
        right = [item for item in candidate.findings if item["code"] == code]
        if not left or len(left) != len(right):
            continue
        first = _finding_columns(left)
        second = _finding_columns(right)
        clusters = tuple(
            str(item["template_id"] if cluster_key == "template_id" else item["form_id"])
            for item in left
        )
        for metric, statistic in (
            ("precision", metrics.finding_precision_columns),
            ("recall", metrics.finding_recall_columns),
        ):
            comparisons.append(
                triage_bridge.PairedComparison(
                    name=f"{code}/{metric}",
                    metric=f"finding_{metric}",
                    slice_name=code,
                    baseline_name=baseline.engine,
                    candidate_name=candidate.engine,
                    clusters=clusters,
                    baseline=first,
                    candidate=second,
                    statistic=statistic,
                )
            )
    return comparisons


def analyse(
    baseline: Run,
    candidate: Run,
    unseen_forms: frozenset[str],
    policy: triage_bridge.StatisticalPolicy,
    cluster_key: str,
) -> list[triage_bridge.ClusteredPairedResult]:
    """Run the whole family at one clustering and correct across it."""
    family = [
        *label_comparisons(baseline, candidate, unseen_forms, cluster_key),
        *finding_comparisons(baseline, candidate, cluster_key),
    ]
    results = [triage_bridge.run_comparison(item, policy) for item in family]
    return triage_bridge.adjust_family(results, policy)


def _git(*arguments: str) -> str:
    """Run one git command in the repository, or return the empty string."""
    try:
        completed = subprocess.run(
            ["git", *arguments], cwd=_REPO_ROOT, capture_output=True, text=True, check=False
        )
    except OSError:  # pragma: no cover - git is present on the build machine
        return ""
    return completed.stdout.strip()


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(description="Compare two run logs through the harness.")
    parser.add_argument("--baseline", type=Path, required=True, help="a run directory")
    parser.add_argument("--candidate", type=Path, required=True, help="a run directory")
    parser.add_argument("--split-file", type=Path, default=Path("corpus") / "split.json")
    parser.add_argument("--out", type=Path, default=evaluate.RESULTS_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--policy", type=Path, default=None, help="the pre-registered policy file")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--fdr", type=float, default=0.05)
    parser.add_argument("--practical-threshold", type=float, default=0.02)
    parser.add_argument("--resamples", type=int, default=triage_bridge.DEFAULT_RESAMPLES)
    parser.add_argument("--seed", type=int, default=20260825)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Compare, correct, classify, and write the analysis result file."""
    args = _arguments(argv)
    baseline = load_run(args.baseline)
    candidate = load_run(args.candidate)
    align(baseline, candidate)

    split = json.loads(args.split_file.read_text(encoding="utf-8"))
    unseen = frozenset(split.get("slices", {}).get("unseen_locale", []))

    policy = triage_bridge.StatisticalPolicy(
        alpha=args.alpha,
        false_discovery_rate=args.fdr,
        practical_threshold=args.practical_threshold,
        resamples=args.resamples,
        seed=args.seed,
    )

    print("analyze.py: handing the harness an unmodified run log")
    native = triage_bridge.probe_native_ingestion(baseline.directory / runlog.RUNLOG_FILENAME)
    print(f"  parser              {native.parser}")
    print(f"  claimed the file    {native.claimed}")
    print(f"  parsed the file     {native.parsed}")
    print(f"  detail              {native.detail}")

    print()
    print(f"analyze.py: {policy.describe()}")
    started = time.perf_counter()
    primary = analyse(baseline, candidate, unseen, policy, "template_id")
    secondary = analyse(baseline, candidate, unseen, policy, "form_id")
    elapsed = time.perf_counter() - started
    cross_check = triage_bridge.harness_native_verdicts(primary, policy)

    print()
    print(f"analyze.py: primary family, clustered by template ({len(primary)} comparisons)")
    _print_family(primary)
    print()
    print(
        f"analyze.py: secondary family, clustered by form ({len(secondary)} comparisons). "
        "Anticonservative relative to the pre-registered test; not cited anywhere."
    )
    _print_family(secondary)

    commit = _git("rev-parse", "HEAD")
    run_id = args.run_id or runlog.make_run_id("analysis", commit)
    destination = args.out / "analysis" / run_id
    if destination.exists():
        print(f"analyze.py: {destination} exists; result files are append-only", file=sys.stderr)
        return 2
    destination.mkdir(parents=True, exist_ok=True)

    document = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "harness": {
            "distribution": triage_bridge.TRIAGE_DISTRIBUTION,
            "version": triage_bridge.harness_version(),
            "used_for": [
                "permutation_p_value: the two sided p value from a caller supplied null",
                "benjamini_hochberg: the step up adjustment across the comparison family",
                "classify with RegressionConfig: the harness's own verdicts, as a cross check",
            ],
            "not_used_for": [
                "clustered resampling: no public entry point accepts a cluster assignment, "
                "so the null distribution is built here at the template level and handed to "
                "the harness's p value estimator. Filed in docs/cross-repo-tasks.md.",
                "ingestion: the harness's JSONL parser cannot read a spec section 13.1 run "
                "log, which has no step field because it has no time axis. Filed.",
            ],
        },
        "native_ingestion": native.to_json(),
        "policy": policy.to_json(),
        "inputs": {
            "baseline": {
                "run_id": baseline.run_id,
                "engine": baseline.engine,
                "directory": str(args.baseline),
                "git_commit": baseline.manifest["git"]["commit"],
                "rows": len(baseline.rows),
            },
            "candidate": {
                "run_id": candidate.run_id,
                "engine": candidate.engine,
                "directory": str(args.candidate),
                "git_commit": candidate.manifest["git"]["commit"],
                "rows": len(candidate.rows),
            },
            "split": baseline.manifest["split"],
            "corpus_manifest_sha": baseline.manifest["corpus_manifest_sha"],
        },
        "primary": {
            "cluster_unit": "template_id",
            "label": "the pre-registered test of spec section 13.3",
            "family_size": len(primary),
            "outcome_counts": _counts(primary),
            "at_design_floor": [item.name for item in primary if item.at_design_floor],
            "comparisons": [item.to_json() for item in primary],
        },
        "secondary": {
            "cluster_unit": "form_id",
            "label": (
                "interim, clustered at the form rather than the template. It asserts that "
                "two locales of one template are independent, which is a stronger "
                "assumption than spec section 13.3 makes, so it is anticonservative "
                "relative to the pre-registered test. Reported for visibility, cited "
                "nowhere."
            ),
            "family_size": len(secondary),
            "outcome_counts": _counts(secondary),
            "comparisons": [item.to_json() for item in secondary],
        },
        "harness_cross_check": {
            "label": (
                "the harness's own end to end verdict machinery over the primary results. "
                "Its statistical and underpowered gates are the ones used above; its "
                "practical gate reads a relative percentage where this project "
                "pre-registered an absolute difference, so a disagreement between the two "
                "verdict columns is that gap and nothing else."
            ),
            "comparisons": cross_check,
            "disagreements": [item["name"] for item in cross_check if not item["agrees"]],
        },
        "elapsed_s": elapsed,
    }
    (destination / ANALYSIS_FILENAME).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    manifest = runlog.Manifest(
        run_id=run_id,
        command_line=" ".join([Path(sys.argv[0]).name, *sys.argv[1:]]),
        split=str(baseline.manifest["split"]),
        engine=f"{baseline.engine} against {candidate.engine}",
        engine_describe={
            "analysis": "paired permutation clustered by template, Benjamini Hochberg",
            "harness": f"{triage_bridge.TRIAGE_DISTRIBUTION} {triage_bridge.harness_version()}",
            "clustering": "built here; the harness has no public clustered resampling",
        },
        threshold_describe={
            "alpha": repr(policy.alpha),
            "false_discovery_rate": repr(policy.false_discovery_rate),
            "practical_threshold_absolute": repr(policy.practical_threshold),
        },
        artefact_sha256={
            "baseline_run.jsonl": runlog.sha256_of(args.baseline / runlog.RUNLOG_FILENAME),
            "candidate_run.jsonl": runlog.sha256_of(args.candidate / runlog.RUNLOG_FILENAME),
        },
        corpus_manifest_sha=str(baseline.manifest["corpus_manifest_sha"]),
        split_file_sha=runlog.sha256_of(args.split_file),
        seed=args.seed,
        git_commit=commit,
        git_dirty=evaluate._dirty(args.out),
        dependency_versions=runlog.resolved_versions(evaluate.DEPENDENCIES),
        machine=runlog.machine_descriptor(),
        started_at=runlog.utc_now(),
        finished_at=runlog.utc_now(),
        row_count=len(primary),
        form_count=len({row.form_id for row in baseline.rows}),
        notes=(
            "the clustered resampling is built in evaluate/triage_bridge.py because the "
            "harness has no public entry point that accepts a cluster assignment; the p "
            "value and the Benjamini Hochberg adjustment are the harness's own",
            f"the policy file is {args.policy}" if args.policy else "no policy file named",
        ),
    )
    runlog.write_manifest(destination / runlog.MANIFEST_FILENAME, manifest)
    print()
    print(f"analyze.py: wrote {destination}")
    return 0


def _counts(results: Sequence[triage_bridge.ClusteredPairedResult]) -> dict[str, int]:
    """How many comparisons landed in each outcome.

    Every verdict the vocabulary has, including the ones with a count of zero.
    Spec section 13.3 point 4 says the middle category must not be dropped, and
    a summary that listed only the categories that occurred would drop it by
    omission on exactly the runs where nothing landed in it.
    """
    counts = dict.fromkeys(triage_bridge.VERDICTS, 0)
    for item in results:
        if item.verdict is not None:
            counts[item.verdict] += 1
    return counts


def _print_family(results: Sequence[triage_bridge.ClusteredPairedResult]) -> None:
    """Print one family as the gate output shows it."""
    header = (
        f"  {'comparison':<34} {'baseline':>9} {'candidate':>9} {'effect':>8} "
        f"{'p':>8} {'adj p':>8}  verdict"
    )
    print(header)
    for item in results:
        floor = " (at the design floor)" if item.at_design_floor else ""
        print(
            f"  {item.name:<34} {item.baseline_statistic:>9.4f} "
            f"{item.candidate_statistic:>9.4f} {item.effect:>+8.4f} "
            f"{item.p_value:>8.4f} {item.adjusted_p or 0.0:>8.4f}  {item.verdict}{floor}"
        )
    if results:
        first = results[0]
        print(
            f"  clusters {first.n_clusters}, arrangements {first.n_arrangements}, "
            f"exact {first.exact}, smallest attainable p {first.min_attainable_p:.4f}"
        )
        counts: dict[str, int] = {}
        for item in results:
            counts[item.verdict or "undecided"] = counts.get(item.verdict or "undecided", 0) + 1
        for verdict in triage_bridge.VERDICTS:
            print(f"  {counts.get(verdict, 0):>3}  {verdict}")


if __name__ == "__main__":
    raise SystemExit(main())
