#!/usr/bin/env python3
"""Evaluate one engine on one split, writing a run log and its manifest.

Spec sections 13.1, 13.2, 14 and 18. This is the command that produces the first
citable numbers in the project, so everything it does is arranged around one
question a reader will ask later: where did this number come from.

Why this is its own script and arms no guard
--------------------------------------------

`scripts/train.py` installs a `sys.addaudithook` that raises on any open of a
test-partition path, and `sys.addaudithook` cannot be removed for the life of
the process. A runner that imported `train.main` would inherit the guard and
then fail, from inside whatever library happened to open the file, on the one
run it exists to perform. So this script imports `train`'s loaders and never its
entry point, and gets its friction from `--i-am-measuring` instead, which is
what spec section 14 asks for: a small deliberate act rather than an accident.

What "classify latency" means here
----------------------------------

Two passes run over every form, and they measure different things.

The first calls `predict` once per form over that form's detectable controls,
which is how the audit engine uses an engine on a real page, and it is the pass
the per-field latency on each row comes from. The n-gram engine divides one
batch's elapsed time by the field count, so the figure is a per-field share of a
batched call rather than a per-field measurement, and batching amortises the
session call. That is stated on the row's own terms in the model card and
restated here because a benchmark that compared this number against a per-call
measurement would be comparing two different quantities.

The second runs the whole decision procedure through `audit.engine.audit`, which
is what produces the finding codes on each row and the finding-level metrics.
It is not timed into the classify column, because it is the audit engine's work
rather than the classifier's.
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

import train  # noqa: E402
from autofill_audit.audit.engine import AuditOptions  # noqa: E402
from autofill_audit.audit.engine import _declared_label as declared_label  # noqa: E402
from autofill_audit.audit.engine import audit as run_audit  # noqa: E402
from autofill_audit.audit.findings import FindingCode, equivalent  # noqa: E402
from autofill_audit.audit.thresholds import Thresholds, load_thresholds  # noqa: E402
from autofill_audit.classify import EngineChoice, load_engine  # noqa: E402
from autofill_audit.classify.onnx_model import (  # noqa: E402
    CALIBRATION_FILE,
    LABEL_MAP_FILE,
    MODEL_FILE,
    VOCAB_FILE,
)
from autofill_audit.descriptors import ExtractionResult, FieldDescriptor  # noqa: E402
from autofill_audit.evaluate import metrics, runlog  # noqa: E402
from autofill_audit.taxonomy import Label, declaration_for  # noqa: E402

# `_declared_label` is imported rather than reimplemented for the reason P4's
# handoff gives about eligibility generally: the audit engine's decision
# procedure is the definition, and a metrics module that invented its own would
# produce a second answer to the same question. It is private to signal that it
# is not part of the tool's outward contract, not to keep this repository out.

RESULTS_ROOT = Path("experiments") / "results"

DEPENDENCIES = (
    "numpy",
    "onnxruntime",
    "playwright",
    "click",
    "rich",
    "jinja2",
    "ml-experiment-triage",
)

_NOT_A_CLAIM = frozenset({Label.UNKNOWN, Label.NOT_AUTOFILLABLE, Label.COMPOSITE_UNSPLIT})
"""Labels the primary chain answers before it reaches an accusation branch.

The same set `scripts/derive_thresholds.py` uses, for the same reason: a
prediction of one of these is never an accusation, so it can neither be a
correct accusation nor a false one."""

MEASURING_FLAG = "--i-am-measuring"

_TEST_REFUSAL = (
    "refusing --split test without " + MEASURING_FLAG + ". The test split is spent "
    "the first time it is looked at, and every look after that is a decision made "
    "with knowledge of it. Passing the flag is the small deliberate act spec "
    "section 14 asks for; it is not a formality, and every run that passed it is "
    "recorded in the manifest."
)


@dataclass(frozen=True, slots=True)
class FormRun:
    """One form, extracted, classified, and audited."""

    form_id: str
    key: Mapping[str, Any]
    result: ExtractionResult
    examples: list[train.Example]
    predictions: list[Any]
    codes_by_selector: Mapping[str, tuple[str, ...]]


def _undeclared(descriptor: FieldDescriptor) -> bool:
    """Whether the page declares nothing usable on this control.

    The three ways a declaration takes the primary chain somewhere else, in the
    order `audit/engine.py` applies them: an explicit off, a token the
    specification does not define, and a valid token to compare against. Kept
    identical to `scripts/derive_thresholds.py`, which derived the thresholds
    this run then measures against.
    """
    declared = descriptor.declared
    if declared.is_off:
        return False
    if declared.raw is not None and declared.is_off_spec:
        return False
    return declared.token is None


def _label(value: str) -> Label | None:
    """Turn an answer-key or prediction string into a label, or None."""
    try:
        return Label(value)
    except ValueError:
        return None


def observations_for(
    example: train.Example, predicted: str, codes: Sequence[str]
) -> list[metrics.FindingObservation]:
    """Judge one field at the finding level, for both accusation codes.

    Eligibility and correctness are read off the decision procedure in
    `audit/engine.py::_primary` rather than invented beside it. ``emitted`` comes
    from what the audit engine actually raised on this selector, so the emitted
    count in the metrics and the ``finding_codes`` on the run-log row are the
    same fact rather than two computations of it.
    """
    descriptor = example.descriptor
    truth = _label(example.label)
    inferred = _label(predicted)
    if descriptor.undetectable_reason is not None or truth is None:
        return []

    advice = None if inferred is None or inferred in _NOT_A_CLAIM else declaration_for(inferred)
    correct = advice is not None and equivalent(advice, truth)

    observations: list[metrics.FindingObservation] = []

    # MISSING_AUTOCOMPLETE: the page declares nothing and a correct page would.
    observations.append(
        metrics.FindingObservation(
            code=FindingCode.MISSING_AUTOCOMPLETE.value,
            template_id=example.template_id,
            needed=_undeclared(descriptor) and declaration_for(truth) is not None,
            emitted=FindingCode.MISSING_AUTOCOMPLETE.value in codes,
            correct=correct,
        )
    )

    # WRONG_AUTOCOMPLETE: the page declares a token this taxonomy models and the
    # answer key disagrees with it. A declared token outside the taxonomy is not
    # counted as needing a finding, because the tool has no label to adjudicate
    # it with and says nothing about it on purpose.
    declared = declared_label(descriptor)
    observations.append(
        metrics.FindingObservation(
            code=FindingCode.WRONG_AUTOCOMPLETE.value,
            template_id=example.template_id,
            needed=declared is not None and not equivalent(declared, truth),
            emitted=FindingCode.WRONG_AUTOCOMPLETE.value in codes,
            correct=correct,
        )
    )
    return observations


def run_forms(
    corpus_dir: Path,
    split: Mapping[str, Any],
    partition: str,
    engine: Any,
    thresholds: Thresholds,
    cache: Path | None,
    base_year: int,
    timings: dict[str, float],
) -> list[FormRun]:
    """Extract, classify and audit every form of one partition."""
    guard = train.TestPartitionGuard(frozenset())
    form_ids = train._forms_in(split, partition)
    options = AuditOptions(thresholds=thresholds)
    runs: list[FormRun] = []
    classify_s = 0.0
    audit_s = 0.0

    for form_id, result, key in train.extract_forms(
        corpus_dir, form_ids, guard, cache, base_year, timings
    ):
        examples, _, _ = train.examples_for_form(form_id, result, key)
        descriptors = [item.descriptor for item in examples]

        started = time.perf_counter()
        predictions = engine.predict(descriptors) if descriptors else []
        classify_s += time.perf_counter() - started

        started = time.perf_counter()
        report = run_audit(result, engine, options)
        audit_s += time.perf_counter() - started

        codes: dict[str, list[str]] = {}
        for finding in (*report.findings, *report.suppressed):
            codes.setdefault(finding.selector, []).append(finding.code.value)

        runs.append(
            FormRun(
                form_id=form_id,
                key=key,
                result=result,
                examples=examples,
                predictions=predictions,
                codes_by_selector={
                    selector: tuple(sorted(set(values))) for selector, values in codes.items()
                },
            )
        )

    timings["classify_s"] = classify_s
    timings["audit_s"] = audit_s
    return runs


def rows_for(
    runs: Sequence[FormRun],
    *,
    run_id: str,
    engine_name: str,
    describe: Mapping[str, str],
    corpus_manifest_sha: str,
    split_name: str,
    prompt_version: str | None = None,
) -> tuple[list[runlog.RunLogRow], list[metrics.FindingObservation], list[dict[str, Any]]]:
    """Turn the classified forms into run-log rows and finding observations.

    The third return value is the per-field finding-level judgement, carrying
    the slice keys of the row it belongs to so that `findings.jsonl` can be cut
    the same ways the run log can without a join.

    ``prompt_version`` is null for every engine that has no prompt and is the
    `PROMPT_VERSION` of spec section 12.2 for the one that does. It goes on every
    row rather than only in the manifest because a prompt change is the language
    model's equivalent of a model sha, and a row separated from its manifest still
    has to say what produced it, which is the same reason `engine_describe` is
    repeated (spec section 13.1).
    """
    kind = runlog.confidence_kind_for(describe)
    rows: list[runlog.RunLogRow] = []
    observations: list[metrics.FindingObservation] = []
    records: list[dict[str, Any]] = []
    for form in runs:
        warnings = tuple(sorted({item.code.value for item in form.result.warnings}))
        for example, prediction in zip(form.examples, form.predictions, strict=True):
            codes = form.codes_by_selector.get(example.descriptor.selector, ())
            rows.append(
                runlog.RunLogRow(
                    run_id=run_id,
                    engine=engine_name,
                    engine_describe=describe,
                    corpus_manifest_sha=corpus_manifest_sha,
                    split=split_name,
                    form_id=form.form_id,
                    form_family=str(form.key["family"]),
                    locale=example.locale,
                    tier=example.tier,
                    template_id=example.template_id,
                    selector=example.descriptor.selector,
                    true_label=example.label,
                    pred_label=prediction.label,
                    confidence=prediction.confidence,
                    confidence_kind=kind,
                    signals=tuple(prediction.signals),
                    runner_up_label=(
                        None if prediction.runner_up is None else prediction.runner_up[0]
                    ),
                    runner_up_confidence=(
                        None if prediction.runner_up is None else prediction.runner_up[1]
                    ),
                    latency_us=prediction.latency_us,
                    declared_token=example.descriptor.declared.token,
                    finding_codes=codes,
                    extraction_warnings=warnings,
                    prompt_version=prompt_version,
                )
            )
            row = rows[-1]
            for observation in observations_for(example, prediction.label, codes):
                observations.append(observation)
                records.append(
                    {
                        "code": observation.code,
                        "form_id": row.form_id,
                        "selector": row.selector,
                        "template_id": observation.template_id,
                        "locale": row.locale,
                        "tier": row.tier,
                        "form_family": row.form_family,
                        "needed": observation.needed,
                        "emitted": observation.emitted,
                        "correct": observation.correct,
                    }
                )
    return rows, observations, records


def uncalibrated_labels(model_dir: Path | None) -> frozenset[str]:
    """The classes whose calibrator is the identity, from the model bundle.

    A class with no development positives gets an identity calibrator, so its
    reported probability is a raw softmax output. Pooling those into one
    reliability curve with the calibrated classes would be averaging over two
    different things and calling the average calibration, so the calibration
    block is reported both ways and this is where the exclusion list comes from.
    """
    if model_dir is None:
        return frozenset()
    path = model_dir / CALIBRATION_FILE
    if not path.is_file():
        return frozenset()
    document = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(
        str(entry["label"])
        for entry in document.get("classes", [])
        if entry.get("method") == "identity"
    )


def compute_metrics(
    rows: Sequence[runlog.RunLogRow],
    observations: Sequence[metrics.FindingObservation],
    *,
    unseen_locale_forms: frozenset[str],
    uncalibrated: frozenset[str],
    timing: metrics.PhaseTiming,
    calibrated: bool,
) -> dict[str, Any]:
    """Every metric spec section 13.2 asks for, computed from the run log."""
    seen = metrics.subset(rows, lambda row: row.form_id not in unseen_locale_forms)
    unseen = metrics.subset(rows, lambda row: row.form_id in unseen_locale_forms)

    locale_grid = metrics.slice_grid(rows, "locale")
    tier_grid = metrics.slice_grid(rows, "tier")
    family_grid = metrics.slice_grid(rows, "form_family")
    locale_tier = metrics.pair_grid(rows, "locale", "tier")

    latencies = [row.latency_us for row in rows if row.latency_us is not None]

    document: dict[str, Any] = {
        "headline": metrics.headline(rows),
        "slices": {
            "seen_locales": metrics.headline(seen),
            "unseen_locale": metrics.headline(unseen),
        },
        "per_label": metrics.label_report_json(rows),
        "grids": {
            "locale": metrics.grid_json(locale_grid),
            "tier": metrics.grid_json(tier_grid),
            "family": metrics.grid_json(family_grid),
            "locale_by_tier": metrics.grid_json(locale_tier),
        },
        "insufficient_data": {
            "minimum": metrics.MIN_FIELDS_PER_REPORTED_CELL,
            "locale": metrics.suppressed_cells(locale_grid.values()),
            "tier": metrics.suppressed_cells(tier_grid.values()),
            "family": metrics.suppressed_cells(family_grid.values()),
            "locale_by_tier": metrics.suppressed_cells(locale_tier.values()),
        },
        "abstention": metrics.abstention(rows),
        "findings": {
            code: metrics.finding_metrics(observations, code)
            for code in (
                FindingCode.MISSING_AUTOCOMPLETE.value,
                FindingCode.WRONG_AUTOCOMPLETE.value,
            )
        },
        "latency_us_per_field": metrics.latency_percentiles(latencies),
        "wall_time": timing.to_json(),
        "confusions": metrics.confusion_pairs(rows),
        "predicted_confusion_pairs": {
            f"{truth} as {guess}": metrics.pair_count(rows, truth, guess)
            for truth, guess in PREDICTED_CONFUSIONS
        },
    }
    if calibrated:
        document["calibration"] = {
            "all_classes": metrics.calibration_report(rows),
            "calibrated_classes_only": metrics.calibration_report(
                rows, exclude_labels=uncalibrated
            ),
        }
    else:
        document["calibration"] = None
    return document


_PREDICTED_PAIRS: tuple[tuple[Label, Label], ...] = (
    (Label.USERNAME, Label.EMAIL),
    (Label.ADDRESS_LEVEL1, Label.ADDRESS_LEVEL2),
    (Label.TEL, Label.TEL_NATIONAL),
    (Label.CC_EXP, Label.CC_EXP_MONTH),
)
"""The four pairs spec section 13.2 predicts will be confused, as labels.

Labels rather than strings because ground rule 6 gives the taxonomy exactly one
definition in code, and `scripts/check_reachability.py` fails the build on a
label literal written anywhere else."""

PREDICTED_CONFUSIONS: tuple[tuple[str, str], ...] = tuple(
    pair
    for first, second in _PREDICTED_PAIRS
    for pair in ((first.value, second.value), (second.value, first.value))
)
"""Both directions of each predicted pair.

Both directions because "confused with" is not symmetric: a model that reads
every username field as an email is a different failure from one that reads
every email field as a username, and a table that reported one direction would
be reporting half the pair. The prediction file restates them for the test split
before this runs."""


FINDINGS_FILENAME = "findings.jsonl"
"""The per-field finding-level judgement, beside the run log.

A fourth artefact rather than four more keys on the run-log row, because spec
section 13.1's schema is fixed and has no key for whether a page *needed* an
accusation. That judgement depends on the difference between "declares
nothing", "declares off", and "declares a token outside the specification", and
the row carries only ``declared_token``, which is null in all three. Without
this file the finding-level significance test could not be reproduced from
committed artefacts, and a number nobody can recompute is a number law 3 will
not let into the README."""


def _write_findings(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    """Write one line per field per accusation code, with its slice keys."""
    if path.exists():
        raise runlog.RunLogError(f"{path} already exists; result files are append-only")
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")


def _git(*arguments: str) -> str:
    """Run one git command in the repository, or return the empty string."""
    try:
        completed = subprocess.run(
            ["git", *arguments], cwd=_REPO_ROOT, capture_output=True, text=True, check=False
        )
    except OSError:  # pragma: no cover - git is present on the build machine
        return ""
    return completed.stdout.strip()


def _dirty(out: Path) -> bool:
    """Whether the tree differs from HEAD, ignoring the output directory.

    The output directory is excluded and only it, for the reason
    `scripts/train.py` gives: on a first run the directory does not exist in
    HEAD, so counting it would mark every run dirty by construction and make the
    flag mean nothing. Everything else counts, untracked files included.
    """
    status = _git("status", "--porcelain")
    if not status:
        return False
    try:
        relative = out.resolve().relative_to(_REPO_ROOT)
    except ValueError:
        relative = out
    prefix = f"{relative}/"
    for line in status.splitlines():
        path = line[3:].strip().strip('"')
        if path == str(relative) or path.startswith(prefix):
            continue
        return True
    return False


def _artefact_shas(model_dir: Path | None) -> dict[str, str]:
    """The content addresses spec section 18 requires of every run.

    ``thresholds.json`` is included even though it is not part of the engine.
    The engine does not load it, the CLI resolves the engine and then asks for
    that engine's block, so the engine's own `describe()` cannot carry the sha
    and this is where it has to come from. A run whose thresholds moved is a run
    whose findings moved, and a manifest that could not say so would be missing
    the one artefact most likely to change between two otherwise identical runs.
    """
    shas: dict[str, str] = {}
    thresholds_path = _REPO_ROOT / "src" / "autofill_audit" / "audit" / "thresholds.json"
    if thresholds_path.is_file():
        shas["thresholds.json"] = runlog.sha256_of(thresholds_path)
    if model_dir is not None:
        for name in (MODEL_FILE, VOCAB_FILE, CALIBRATION_FILE, LABEL_MAP_FILE):
            path = model_dir / name
            if path.is_file():
                shas[name] = runlog.sha256_of(path)
    return shas


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line of spec section 14's ``eval``."""
    parser = argparse.ArgumentParser(description="Evaluate one engine on one split.")
    parser.add_argument("--corpus", type=Path, default=Path("corpus"))
    parser.add_argument("--split-file", type=Path, default=None)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--engine", choices=("rules", "ngram", "llm"), required=True)
    parser.add_argument(
        "--llm-endpoint",
        type=str,
        default=None,
        help="the OpenAI-compatible base URL; default is Ollama on loopback",
    )
    parser.add_argument(
        "--llm-model", type=str, default=None, help="the model tag, recorded in every row"
    )
    parser.add_argument(
        "--llm-batch",
        type=int,
        default=None,
        help="fields per request; a page under it is one request (spec section 12.3)",
    )
    parser.add_argument("--out", type=Path, default=RESULTS_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument(
        MEASURING_FLAG,
        dest="measuring",
        action="store_true",
        help="required for --split test; the test split is spent once",
    )
    parser.add_argument("--note", action="append", default=[], help="a note for the manifest")
    return parser.parse_args(argv)


def _llm_config(args: argparse.Namespace) -> Any:
    """Build the language-model configuration, or None for every other engine.

    Returns None rather than a default configuration when the engine is not
    ``llm``, so that a run of the rule baseline never imports the research layer
    and never touches the network to discover it did not need to (ground rule
    11).
    """
    if args.engine != "llm":
        return None
    from autofill_audit.llm.client import LLMConfig

    defaults = LLMConfig()
    return LLMConfig(
        endpoint=args.llm_endpoint or defaults.endpoint,
        model_tag=args.llm_model or defaults.model_tag,
        batch=args.llm_batch or defaults.batch,
    )


def _llm_block(engine: Any) -> dict[str, Any] | None:
    """The cost and schema-compliance accounting, or None for a local engine.

    Spec section 13.1's row schema is fixed and has no cost key, and P5's handoff
    settled where the missing quantity goes: cost is a property of the run and
    the provider rather than of the field, so it lives in the run manifest and
    the metrics document beside every other per-run quantity. Adding a column to
    the row would have bumped the run-log schema version for a value that is the
    same on all 2317 of them.
    """
    accounting = getattr(engine, "accounting", None)
    if accounting is None:
        return None
    block: dict[str, Any] = accounting.to_json()
    block["fields_per_request_cap"] = getattr(engine, "batch", None)
    block["prompt_version"] = engine.describe().get("prompt_version")
    return block


def main(argv: Sequence[str] | None = None) -> int:
    """Evaluate, write the run log, the manifest, the metrics and the matrix."""
    args = _arguments(argv)
    if args.split == train.TEST and not args.measuring:
        print(f"eval.py: {_TEST_REFUSAL}", file=sys.stderr)
        return 2

    corpus_dir: Path = args.corpus
    split_path: Path = args.split_file if args.split_file else corpus_dir / "split.json"
    split = train._load_split(split_path)
    manifest_document = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    base_year = int(manifest_document.get("base_year", time.gmtime().tm_year))
    corpus_manifest_sha = train._corpus_manifest_sha(corpus_dir)
    train.bind_cache(args.cache, corpus_manifest_sha)

    choice = EngineChoice(args.engine)
    load = load_engine(choice, model_dir=args.model, llm_config=_llm_config(args))
    if load.notice:
        print(f"eval.py: {load.notice}")
    engine = load.classifier
    describe = engine.describe()
    thresholds = load_thresholds(args.engine)

    commit = _git("rev-parse", "HEAD")
    run_id = args.run_id or runlog.make_run_id(args.engine, commit)
    # Runs are filed under the split they measured. That is not tidiness. The
    # pre-registered policy file names `experiments/results/test/` as the thing
    # it predicts about, and `scripts/check_prediction_ancestry.py` checks that
    # the policy commit precedes every commit under it. Development runs are
    # sanity checks that precede the policy and make no claim it covers, so
    # filing them in the same directory would make the ancestry check fail on a
    # run that was correctly taken before the prediction was written.
    destination = args.out / args.split / run_id
    if destination.exists():
        print(
            f"eval.py: {destination} exists. Result files are append-only history "
            "(spec section 18): a wrong result gets a new run id, never a regeneration.",
            file=sys.stderr,
        )
        return 2

    print(f"eval.py: run {run_id}")
    print(f"eval.py: engine {args.engine}, split {args.split}, corpus {corpus_manifest_sha[:12]}")
    if args.measuring:
        print("eval.py: measuring on the test split, deliberately")

    started_at = runlog.utc_now()
    wall_started = time.perf_counter()
    timings: dict[str, float] = {}
    runs = run_forms(
        corpus_dir, split, args.split, engine, thresholds, args.cache, base_year, timings
    )
    print(f"eval.py: {len(runs)} forms")

    rows, observations, finding_records = rows_for(
        runs,
        run_id=run_id,
        engine_name=args.engine,
        describe=describe,
        corpus_manifest_sha=corpus_manifest_sha,
        split_name=args.split,
        prompt_version=describe.get("prompt_version"),
    )
    print(f"eval.py: {len(rows)} classified fields")

    model_dir = _model_dir_of(describe, args.model)
    unseen = frozenset(split.get("slices", {}).get("unseen_locale", []))
    render_started = time.perf_counter()

    destination.mkdir(parents=True, exist_ok=True)
    written = runlog.write_rows(destination / runlog.RUNLOG_FILENAME, rows)
    render_s = time.perf_counter() - render_started
    total_s = time.perf_counter() - wall_started

    timing = metrics.PhaseTiming(
        load_s=timings.get("load_s", 0.0),
        extract_s=timings.get("extract_s", 0.0),
        classify_s=timings.get("classify_s", 0.0),
        render_s=render_s,
        total_s=total_s,
        forms=len(runs),
        fields=len(rows),
        extraction_source=("browser" if timings.get("load_s", 0.0) > 0 else "descriptor cache"),
    )
    document = compute_metrics(
        rows,
        observations,
        unseen_locale_forms=unseen,
        uncalibrated=uncalibrated_labels(model_dir),
        timing=timing,
        calibrated=describe.get("confidence_kind") == "calibrated-probability",
    )
    document["audit_s"] = timings.get("audit_s", 0.0)
    llm_block = _llm_block(engine)
    document["llm"] = llm_block
    (destination / runlog.METRICS_FILENAME).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (destination / runlog.CONFUSION_FILENAME).write_text(
        json.dumps(metrics.confusion_matrix(rows), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_findings(destination / FINDINGS_FILENAME, finding_records)

    notes = list(args.note)
    if args.measuring:
        notes.append("run with --i-am-measuring on the test split")
    if llm_block is not None:
        notes.append(
            f"{llm_block['calls']} language-model requests, {llm_block['attempts']} attempts, "
            f"{llm_block['retried_calls']} retried, {llm_block['failed_calls']} still failing "
            f"after the retry, {llm_block['unresolved_fields_scored_unknown']} fields scored "
            "UNKNOWN by that failure and kept in the denominator (spec section 12.3 point 4)"
        )
        notes.append(
            "cost is null rather than zero: the calls were local. Spec section 12.4, zero "
            "is a measurement and the electricity was not free"
        )
        notes.append(
            "latency_us per field is a batch's elapsed time divided by its field count, "
            "not a per-field measurement; batching amortises the round trip"
        )
    if timing.extraction_source == "descriptor cache":
        notes.append(
            "descriptors came from the cache, so the load and extract columns of "
            "wall_time are zero and the browser figures belong to the run that "
            "populated it"
        )

    manifest = runlog.Manifest(
        run_id=run_id,
        command_line=" ".join([Path(sys.argv[0]).name, *sys.argv[1:]]),
        split=args.split,
        engine=args.engine,
        engine_describe=describe,
        threshold_describe=thresholds.describe(),
        artefact_sha256=_artefact_shas(model_dir),
        corpus_manifest_sha=corpus_manifest_sha,
        split_file_sha=runlog.sha256_of(split_path),
        seed=args.seed,
        git_commit=commit,
        git_dirty=_dirty(args.out),
        dependency_versions=runlog.resolved_versions(DEPENDENCIES),
        machine=runlog.machine_descriptor(),
        started_at=started_at,
        finished_at=runlog.utc_now(),
        row_count=written,
        form_count=len(runs),
        notes=tuple(notes),
    )
    runlog.write_manifest(destination / runlog.MANIFEST_FILENAME, manifest)

    headline = document["headline"]
    print()
    print(f"eval.py: wrote {destination}")
    print(f"  rows                {headline['rows']}")
    print(f"  forms               {headline['forms']}")
    print(f"  templates           {headline['templates']}")
    print(f"  macro-F1            {headline['macro_f1']:.4f}")
    print(f"  micro-F1            {headline['micro_f1']:.4f}")
    print(f"  unseen locale F1    {document['slices']['unseen_locale']['macro_f1']:.4f}")
    print(f"  abstention          {document['abstention']['unknown_rate']:.4f}")
    for code, block in document["findings"].items():
        precision = block["precision"]
        recall = block["recall"]
        shown = metrics.INSUFFICIENT_DATA if precision is None else f"{precision:.4f}"
        recalled = metrics.INSUFFICIENT_DATA if recall is None else f"{recall:.4f}"
        print(
            f"  {code:<22} precision {shown} over {block['accusations']} accusations, "
            f"recall {recalled} of {block['fields_needing_one']}"
        )
    percentiles = document["latency_us_per_field"]
    print(
        f"  latency us          p50 {percentiles['p50']:.1f} p95 {percentiles['p95']:.1f} "
        f"p99 {percentiles['p99']:.1f}"
    )
    suppressed = document["insufficient_data"]["locale_by_tier"]
    print(f"  suppressed cells    {len(suppressed)} of {len(document['grids']['locale_by_tier'])}")
    if llm_block is not None:
        retry_rate = llm_block["retry_rate"]
        failure_rate = llm_block["failure_rate"]
        print(
            f"  llm requests        {llm_block['calls']} calls, "
            f"{llm_block['attempts']} attempts, retry rate "
            f"{'n/a' if retry_rate is None else f'{retry_rate:.4f}'}, failure rate "
            f"{'n/a' if failure_rate is None else f'{failure_rate:.4f}'}"
        )
        print(
            f"  llm unresolved      {llm_block['unresolved_fields_scored_unknown']} fields "
            "scored UNKNOWN and kept in the denominator"
        )
        print(
            f"  llm tokens          {llm_block['prompt_tokens']} prompt, "
            f"{llm_block['completion_tokens']} completion, cost null (local)"
        )
    if manifest.git_dirty:
        print("  WARNING: the tree was dirty, so this result is not citable (spec section 18)")
    return 0


def _model_dir_of(describe: Mapping[str, str], override: Path | None) -> Path | None:
    """Where the model bundle that ran actually lives, or None for the rules."""
    if override is not None:
        return override
    recorded = describe.get("model_dir")
    return Path(recorded) if recorded else None


if __name__ == "__main__":
    raise SystemExit(main())
