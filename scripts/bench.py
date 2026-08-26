#!/usr/bin/env python3
"""The multi-engine headline benchmark of spec sections 13.4 and 14.

Runs `eval` once per engine into one output root, runs `analyze.py` over the
whole set as a single comparison family, and assembles the section 13.4 grid
from the committed metrics documents.

Why this calls `eval` rather than reimplementing it
---------------------------------------------------

Everything a benchmark needs is what `eval` already writes: the run log, the
manifest, the metrics, the finding judgements. A second path that produced a
second kind of result file would give two answers to every question, and the
first time they disagreed nobody would know which was the measurement. So this
script is a driver: it decides what to run, in what order, with what
prerequisites checked, and it reads back what `eval` committed. Every cell of the
headline table traces to a result file by construction rather than by discipline.

Fail fast, and what "fast" has to mean here
-------------------------------------------

Spec section 14: `bench` "fails fast with a clear message if an engine's
prerequisite is missing rather than silently benchmarking three engines and
reporting two". For this command that has to mean **before the first page
loads**, because the language-model engine runs for the better part of an hour
and discovering at the end of it that the third engine has no model bundle would
waste the run and, worse, would tempt whoever is watching to report the two that
worked.

So `check_prerequisites` runs every engine's check up front: the threshold block
for each named engine, the model bundle for `ngram`, and for `llm` the optional
dependency, a reachable server, and the tag being present on it.

`--repeats` and `--warmup` are latency flags and only latency flags
-------------------------------------------------------------------

P5's handoff settled this and the reasoning is worth keeping beside the code.
Repeating a deterministic classifier changes nothing but the timing. Repeating a
language model at a nonzero temperature would change the answers, which would
make one run log carry several different predictions for one field under one run
id, and no statistic in this project knows what to do with that.

So repeats time the classifier and never touch the committed predictions: the
measured run is the first one, `--warmup` passes are discarded before it, and any
`--repeats` above one times the classifier again over the already-extracted
descriptors and records the timing spread in the benchmark document. The run log
is written once. The manifest says which it was.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import eval as evaluate  # noqa: E402
from autofill_audit.audit.thresholds import ThresholdsError, load_thresholds  # noqa: E402
from autofill_audit.classify import (  # noqa: E402
    EngineChoice,
    UnavailableEngineError,
    check_llm_prerequisites,
)
from autofill_audit.classify.onnx_model import ModelLoadError, load_ngram_engine  # noqa: E402
from autofill_audit.evaluate import runlog  # noqa: E402

BENCH_FILENAME = "benchmark.json"

DEFAULT_ENGINES = ("rules", "ngram", "llm")

ABSENT_ENGINES: Mapping[str, str] = {
    "bert-onnx-int8": (
        "absent: the transformer of spec section 10.7 is phase P8 and has not been built. "
        "Spec section 13.4 requires the row to say absent rather than be left blank, "
        "because a blank cell reads as a measurement of zero."
    )
}
"""Engines the headline table of spec section 13.4 names and this build does not
have. Reported by name with a reason, never omitted."""


@dataclass(frozen=True, slots=True)
class EngineRun:
    """One engine's completed run, located by the directory `eval` wrote."""

    engine: str
    directory: Path
    metrics: Mapping[str, Any]
    manifest: Mapping[str, Any]


def check_prerequisites(engines: Sequence[str], llm_options: Mapping[str, Any]) -> list[str]:
    """Return one message per engine that cannot run. Empty means every one can.

    Checked before anything loads a page. Every engine is checked even after the
    first failure, because a person who has to start a service and train a model
    would rather be told both now than one after fixing the other.
    """
    problems: list[str] = []
    for name in engines:
        try:
            load_thresholds(name)
        except ThresholdsError as error:
            problems.append(f"{name}: {error}")
            continue

        if name == EngineChoice.NGRAM.value:
            try:
                load_ngram_engine(llm_options.get("model_dir"))
            except ModelLoadError as error:
                problems.append(f"{name}: {error}")
        elif name == EngineChoice.LLM.value:
            from autofill_audit.llm.client import LLMConfig

            defaults = LLMConfig()
            config = LLMConfig(
                endpoint=llm_options.get("endpoint") or defaults.endpoint,
                model_tag=llm_options.get("model_tag") or defaults.model_tag,
                batch=llm_options.get("batch") or defaults.batch,
            )
            try:
                check_llm_prerequisites(config)
            except UnavailableEngineError as error:
                problems.append(str(error))
    return problems


def run_engine(
    engine: str,
    args: argparse.Namespace,
    run_id: str | None,
) -> int:
    """Run `eval` for one engine as a subprocess, returning its exit status.

    A subprocess rather than a function call, for the reason `eval` itself gives
    about `train`: process-level isolation is what keeps one engine's import
    graph, audit hooks and ONNX thread pinning out of the next engine's
    measurement. A benchmark whose second engine ran in a process warmed by the
    first would be measuring the order the engines were named in.
    """
    command = [
        sys.executable,
        str(_REPO_ROOT / "scripts" / "eval.py"),
        "--corpus",
        str(args.corpus),
        "--split",
        args.split,
        "--engine",
        engine,
        "--out",
        str(args.out),
        "--seed",
        str(args.seed),
    ]
    if args.split_file is not None:
        command.extend(["--split-file", str(args.split_file)])
    if run_id is not None:
        command.extend(["--run-id", run_id])
    if args.model is not None and engine == EngineChoice.NGRAM.value:
        command.extend(["--model", str(args.model)])
    if args.measuring:
        command.append(evaluate.MEASURING_FLAG)
    if engine == EngineChoice.LLM.value:
        if args.llm_endpoint:
            command.extend(["--llm-endpoint", args.llm_endpoint])
        if args.llm_model:
            command.extend(["--llm-model", args.llm_model])
        if args.llm_batch:
            command.extend(["--llm-batch", str(args.llm_batch)])
    command.extend(["--note", f"one engine of the spec section 13.4 benchmark {args.bench_id}"])
    for note in args.note:
        command.extend(["--note", note])

    print(f"bench.py: {engine}")
    print(f"  {' '.join(command[1:])}")
    return subprocess.call(command)


def _newest_run(out: Path, split: str, engine: str, run_id: str | None, since: float) -> Path:
    """The run directory `eval` just wrote for this engine.

    Two cases, because `eval` names a run two different ways. When this script
    supplied a `--run-id`, the directory is exactly that name and looking for
    anything else would be guessing at a value we already know. When it did not,
    `eval` built the id from a timestamp, the engine, and the commit, so the
    engine name is the part of it this script can match on.

    Either way the directory has to be newer than the moment the child started,
    which is what keeps a rerun from picking up the previous run of the same
    engine. Located by name and time rather than by parsing the child's output,
    because a parser for the run id here would be a second definition of a
    convention `eval` already owns.
    """
    root = out / split
    if not root.is_dir():
        raise SystemExit(f"bench.py: {engine} reported success and wrote nothing under {root}")
    if run_id is not None:
        exact = root / run_id
        if exact.is_dir():
            return exact
        raise SystemExit(
            f"bench.py: {engine} reported success and wrote no directory named {run_id} "
            f"under {root}"
        )
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir() and path.stat().st_mtime >= since and f"_{engine}_" in path.name
    ]
    if not candidates:
        raise SystemExit(
            f"bench.py: {engine} reported success and wrote no run directory under {root}"
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_engine_run(engine: str, directory: Path) -> EngineRun:
    """Read back what `eval` committed for one engine."""
    metrics_document = json.loads((directory / runlog.METRICS_FILENAME).read_text(encoding="utf-8"))
    manifest = runlog.read_manifest(directory / runlog.MANIFEST_FILENAME)
    return EngineRun(
        engine=engine, directory=directory, metrics=metrics_document, manifest=manifest
    )


# ---------------------------------------------------------------------------
# The section 13.4 grid.
# ---------------------------------------------------------------------------


def _cell(metrics_document: Mapping[str, Any], grid: str, key: str) -> Any:
    """One cell of a committed grid, or None when it was suppressed."""
    return metrics_document.get("grids", {}).get(grid, {}).get(key)


def headline_grid(runs: Sequence[EngineRun]) -> dict[str, Any]:
    """Assemble the engine by locale by tier grid of spec section 13.4.

    Every number here is copied out of a committed `metrics.json`. Nothing is
    recomputed, because a benchmark table that recomputed its own numbers could
    disagree with the result files it cites and law 3's chain would end at a
    disagreement.
    """
    engines: dict[str, Any] = {}
    for run in runs:
        document = run.metrics
        findings = document.get("findings", {})
        engines[run.engine] = {
            "run_id": run.manifest["run_id"],
            "result_file": str(run.directory),
            "git_commit": run.manifest["git"]["commit"],
            "citable": not run.manifest["git"]["dirty"],
            "engine_describe": dict(run.manifest["engine_describe"]),
            "prompt_version": document.get("llm", {}).get("prompt_version")
            if document.get("llm")
            else None,
            "headline": document.get("headline"),
            "slices": document.get("slices"),
            "by_locale": document.get("grids", {}).get("locale"),
            "by_tier": document.get("grids", {}).get("tier"),
            "by_locale_and_tier": document.get("grids", {}).get("locale_by_tier"),
            "insufficient_data": document.get("insufficient_data"),
            "abstention": document.get("abstention"),
            "findings": findings,
            "latency_us_per_field": document.get("latency_us_per_field"),
            "wall_time": document.get("wall_time"),
            "cost": {
                "estimated_cost_usd_list_price": (
                    document.get("llm", {}).get("estimated_cost_usd_list_price")
                    if document.get("llm")
                    else None
                ),
                "note": (
                    "null for every engine in this table. The two classical engines have "
                    "no provider and the language model ran locally. Spec section 12.4: "
                    "zero is a measurement and the electricity was not free, so the "
                    "absence of a monetary cost is recorded as the absence of one."
                ),
            },
            "schema_compliance": document.get("llm"),
        }
    return {
        "engines": engines,
        "absent": dict(ABSENT_ENGINES),
        "averages_note": (
            "macro-F1 and micro-F1 are both reported for every engine and slice. They "
            "disagree about which engine wins, and both are correct: macro averaging is "
            "free about abstention and micro averaging is not. A table that reported one "
            "of them would be picking a winner by picking a denominator."
        ),
        "latency_note": (
            "latency_us_per_field for the language model is a batch's elapsed time "
            "divided by its field count, not a per-field measurement. Batching amortises "
            "the round trip, so it is not comparable against a per-call figure. The "
            "wall_time block is what a user experiences and it is reported beside it."
        ),
        "finding_level_note": (
            "a finding-level comparison between these engines is not a comparison of "
            "three classifiers. Each engine's accusations are gated by its own threshold "
            "block, and the three blocks are on scales that were never the same quantity: "
            "the n-gram engine's boundary was derived against a precision target, the "
            "rule engine's is a documented tier mapping, and the language model's is zero "
            "because spec section 12.1 forbids its self-reported confidence from gating "
            "anything."
        ),
    }


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line of spec section 14's `bench`."""
    parser = argparse.ArgumentParser(description="Run the spec section 13.4 headline benchmark.")
    parser.add_argument("--corpus", type=Path, default=Path("corpus"))
    parser.add_argument("--split-file", type=Path, default=None)
    parser.add_argument("--split", choices=("dev", "test"), default="test")
    parser.add_argument(
        "--engines",
        type=str,
        default=",".join(DEFAULT_ENGINES),
        help="comma separated; every one is checked before any of them runs",
    )
    parser.add_argument("--out", type=Path, default=evaluate.RESULTS_ROOT)
    parser.add_argument("--bench-id", type=str, default=None)
    parser.add_argument("--run-id-prefix", type=str, default=None)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="time the classifier this many times; the predictions are written once",
    )
    parser.add_argument(
        "--warmup", type=int, default=0, help="discarded timing passes before the measured one"
    )
    parser.add_argument("--llm-endpoint", type=str, default=None)
    parser.add_argument("--llm-model", type=str, default=None)
    parser.add_argument("--llm-batch", type=int, default=None)
    parser.add_argument(
        evaluate.MEASURING_FLAG,
        dest="measuring",
        action="store_true",
        help="required for --split test; the test split is spent once",
    )
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="write the grid without running the significance family",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Check, run every engine, assemble the grid, and run the family."""
    args = _arguments(argv)
    engines = [name.strip() for name in args.engines.split(",") if name.strip()]
    if not engines:
        print("bench.py: --engines named nothing", file=sys.stderr)
        return 2
    if args.split == "test" and not args.measuring:
        print(f"bench.py: {evaluate._TEST_REFUSAL}", file=sys.stderr)
        return 2
    if args.repeats < 1:
        print("bench.py: --repeats must be at least one", file=sys.stderr)
        return 2

    commit = evaluate._git("rev-parse", "HEAD")
    args.bench_id = args.bench_id or runlog.make_run_id("bench", commit)

    print(f"bench.py: {args.bench_id}")
    print(f"bench.py: engines {', '.join(engines)}, split {args.split}")
    for name, reason in ABSENT_ENGINES.items():
        print(f"bench.py: {name} {reason}")

    print()
    print("bench.py: checking every engine's prerequisites before any page loads")
    problems = check_prerequisites(
        engines,
        {
            "model_dir": args.model,
            "endpoint": args.llm_endpoint,
            "model_tag": args.llm_model,
            "batch": args.llm_batch,
        },
    )
    if problems:
        for problem in problems:
            print(f"bench.py: {problem}", file=sys.stderr)
        print(
            f"bench.py: {len(problems)} engine(s) cannot run. Spec section 14 has this "
            "command fail fast rather than benchmark three engines and report two.",
            file=sys.stderr,
        )
        return 2
    print(f"bench.py: all {len(engines)} engine(s) can run")

    started_at = runlog.utc_now()
    runs: list[EngineRun] = []
    for engine in engines:
        print()
        since = time.time()
        run_id = f"{args.run_id_prefix}-{engine}" if args.run_id_prefix else None
        status = run_engine(engine, args, run_id)
        if status != 0:
            print(f"bench.py: {engine} exited {status}", file=sys.stderr)
            return status
        directory = _newest_run(args.out, args.split, engine, run_id, since)
        runs.append(load_engine_run(engine, directory))

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "bench_id": args.bench_id,
        "command_line": " ".join([Path(sys.argv[0]).name, *sys.argv[1:]]),
        "split": args.split,
        "engines": engines,
        "started_at": started_at,
        "finished_at": runlog.utc_now(),
        "repeats": args.repeats,
        "warmup": args.warmup,
        "repeats_note": (
            "repeats and warmup are latency flags and only latency flags. The predictions "
            "are written once, by the measured pass. Repeating a language model at a "
            "nonzero temperature would change the answers, and a run log carrying several "
            "predictions for one field under one run id is not something any statistic in "
            "this project knows how to read."
        ),
        "grid": headline_grid(runs),
    }

    destination = args.out / "bench" / args.bench_id
    if destination.exists():
        print(f"bench.py: {destination} exists; result files are append-only", file=sys.stderr)
        return 2
    destination.mkdir(parents=True, exist_ok=True)
    (destination / BENCH_FILENAME).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    manifest = runlog.Manifest(
        run_id=args.bench_id,
        command_line=document["command_line"],
        split=args.split,
        engine=" against ".join(engines),
        engine_describe={
            run.engine: json.dumps(dict(run.manifest["engine_describe"]), sort_keys=True)
            for run in runs
        },
        threshold_describe={
            run.engine: json.dumps(dict(run.manifest["threshold_describe"])) for run in runs
        },
        artefact_sha256={
            f"{run.engine}/run.jsonl": runlog.sha256_of(run.directory / runlog.RUNLOG_FILENAME)
            for run in runs
        },
        corpus_manifest_sha=str(runs[0].manifest["corpus_manifest_sha"]),
        split_file_sha=str(runs[0].manifest["split_file_sha"]),
        seed=args.seed,
        git_commit=commit,
        git_dirty=evaluate._dirty(args.out),
        dependency_versions=runlog.resolved_versions(evaluate.DEPENDENCIES),
        machine=runlog.machine_descriptor(),
        started_at=started_at,
        finished_at=runlog.utc_now(),
        row_count=sum(int(run.manifest["row_count"]) for run in runs),
        form_count=int(runs[0].manifest["form_count"]),
        notes=(
            f"the spec section 13.4 headline benchmark over {len(engines)} engines",
            "every number in benchmark.json is copied from a committed metrics.json and "
            "none is recomputed here",
            *(f"{name} {reason}" for name, reason in ABSENT_ENGINES.items()),
        ),
    )
    runlog.write_manifest(destination / runlog.MANIFEST_FILENAME, manifest)

    print()
    _print_headline(runs)
    print()
    print(f"bench.py: wrote {destination}")

    if args.skip_analysis or len(runs) < 2:
        return 0

    print()
    print("bench.py: the significance family over every engine pair")
    analysis = [
        sys.executable,
        str(_REPO_ROOT / "scripts" / "analyze.py"),
        "--out",
        str(args.out),
        "--policy",
        "experiments/predictions/p6-llm-comparison.md",
    ]
    for run in runs:
        analysis.extend(["--run", str(run.directory)])
    if args.split_file is not None:
        analysis.extend(["--split-file", str(args.split_file)])
    if args.run_id_prefix:
        analysis.extend(["--run-id", f"{args.run_id_prefix}-analysis"])
    return subprocess.call(analysis)


def _print_headline(runs: Sequence[EngineRun]) -> None:
    """Print the section 13.4 table as the gate output shows it."""
    print(f"bench.py: the headline table, spec section 13.4 ({len(runs)} engines)")
    header = (
        f"  {'engine':<8} {'macroF1':>8} {'microF1':>8} {'seen':>8} {'unseen':>8} "
        f"{'abstain':>8} {'p95 us':>12} {'cost':>6}"
    )
    print(header)
    for run in runs:
        headline = run.metrics.get("headline", {})
        slices = run.metrics.get("slices", {})
        latency = run.metrics.get("latency_us_per_field", {})
        print(
            f"  {run.engine:<8} {headline.get('macro_f1', 0.0):>8.4f} "
            f"{headline.get('micro_f1', 0.0):>8.4f} "
            f"{slices.get('seen_locales', {}).get('macro_f1', 0.0):>8.4f} "
            f"{slices.get('unseen_locale', {}).get('macro_f1', 0.0):>8.4f} "
            f"{run.metrics.get('abstention', {}).get('unknown_rate', 0.0):>8.4f} "
            f"{latency.get('p95', 0.0):>12.1f} {'null':>6}"
        )
    for name, reason in ABSENT_ENGINES.items():
        print(f"  {name:<8} {reason.split(':')[0]}")


if __name__ == "__main__":
    raise SystemExit(main())
