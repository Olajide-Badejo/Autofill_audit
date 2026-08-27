#!/usr/bin/env python3
"""Derive the two decision thresholds on the dev split (spec section 11.3).

The optimisation is not invented here. It was pre-registered before the model
existed, in `experiments/predictions/p4-threshold-derivation.md`, and that file's
commit is an ancestor of the commit this script's output lands in, which is what
makes law 4 more than an intention. This script implements it and nothing else.

**tau_high** is the smallest calibrated confidence at which dev-split precision
for `MISSING_AUTOCOMPLETE`-eligible predictions reaches the pre-registered
target.

**tau_low** is the greatest confidence at which the band from it up to tau_high
still captures at least the pre-registered fraction of the recall tau_high gives
up. The prediction file records why "greatest" rather than "smallest": captured
recall only falls as the low threshold rises, so every value below a qualifying
one also qualifies and the smallest qualifying value is always zero, which is a
threshold that says nothing.

What eligible means
-------------------

The audit engine's primary chain, run on a dev field, would reach the
`MISSING_AUTOCOMPLETE` branch if the confidence were high enough. That is read
off the decision procedure in `audit/engine.py` rather than invented beside it:
the control is not a blind spot, the page declares nothing on it, and the
inferred label is one a correct page would declare something for.

What correct means
------------------

The token the tool would tell the developer to add is the token the answer key
says the field should carry, or is equivalent to it under the documented
equivalence sets. Equivalence is used because a page that declares `name` where
this tool reads `given-name` fills correctly from a stored profile, and calling
that a false accusation would measure something other than what a user
experiences.

Usage:
    derive_thresholds.py --corpus corpus --model models [--write]

Without `--write` it computes and prints and changes nothing, which is the mode
to run first. Exit status is 0 when a threshold meeting the target was found.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import train  # noqa: E402
from autofill_audit.audit.findings import equivalent  # noqa: E402
from autofill_audit.classify.onnx_model import ENGINE_NAME, load_ngram_engine  # noqa: E402
from autofill_audit.descriptors import FieldDescriptor, Prediction  # noqa: E402
from autofill_audit.taxonomy import Label, declaration_for  # noqa: E402

TARGET_PRECISION = 0.98
"""Pre-registered before the model existed. A false CRITICAL tells somebody to
edit production markup and costs this project the credibility that makes the next
finding worth reading; a missed one costs a field that would not have autofilled
anyway. The target sits where that asymmetry says to put it."""

RECALL_BAND_FRACTION = 0.50
"""How much of the recall tau_high gives up the near-miss band must capture."""

THRESHOLDS_PATH = Path("src") / "autofill_audit" / "audit" / "thresholds.json"

_NOT_A_CLAIM = frozenset({Label.UNKNOWN, Label.NOT_AUTOFILLABLE, Label.COMPOSITE_UNSPLIT})
"""Labels the primary chain answers before it reaches the missing-declaration
branch, so a prediction of one of them is never an accusation."""


@dataclass(frozen=True, slots=True)
class Row:
    """One dev field, as the threshold derivation sees it."""

    selector: str
    truth: str
    predicted: str
    confidence: float
    eligible: bool
    needs_accusation: bool
    correct: bool


def _undeclared(descriptor: FieldDescriptor) -> bool:
    """Whether the page declares nothing usable on this control.

    The three ways a declaration takes the primary chain somewhere else, in the
    order `audit/engine.py` applies them: an explicit off, a token the
    specification does not define, and a valid token to compare against.
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


def build_rows(examples: Sequence[train.Example], predictions: Sequence[Prediction]) -> list[Row]:
    """Pair every dev field with what the tool would have said about it."""
    rows: list[Row] = []
    for example, prediction in zip(examples, predictions, strict=True):
        descriptor = example.descriptor
        truth = _label(example.label)
        inferred = _label(prediction.label)
        undeclared = _undeclared(descriptor)

        needs = (
            descriptor.undetectable_reason is None
            and undeclared
            and truth is not None
            and declaration_for(truth) is not None
        )
        eligible = (
            descriptor.undetectable_reason is None
            and undeclared
            and inferred is not None
            and inferred not in _NOT_A_CLAIM
            and declaration_for(inferred) is not None
        )
        correct = False
        if eligible and truth is not None and inferred is not None:
            advice = declaration_for(inferred)
            correct = advice is not None and equivalent(advice, truth)
        rows.append(
            Row(
                selector=descriptor.selector,
                truth=example.label,
                predicted=prediction.label,
                confidence=prediction.confidence,
                eligible=eligible,
                needs_accusation=needs,
                correct=correct,
            )
        )
    return rows


def precision_recall(rows: Sequence[Row], tau: float) -> tuple[int, int, float, float]:
    """Return accusations, correct accusations, precision, and recall at ``tau``."""
    needs = sum(1 for row in rows if row.needs_accusation)
    accusations = [row for row in rows if row.eligible and row.confidence >= tau]
    correct = sum(1 for row in accusations if row.correct)
    precision = correct / len(accusations) if accusations else 1.0
    recall = correct / needs if needs else 0.0
    return len(accusations), correct, precision, recall


def candidates(rows: Sequence[Row]) -> list[float]:
    """The thresholds worth trying: the observed confidences, plus the ends.

    Observed values rather than a fixed grid, so the chosen threshold is always
    achievable and never falls in a gap no dev field occupies.
    """
    observed = {row.confidence for row in rows if row.eligible}
    return sorted(observed | {0.0, 1.0})


def choose_tau_high(rows: Sequence[Row], target: float) -> tuple[float, bool]:
    """The smallest confidence at which precision reaches ``target``.

    Returns the threshold and whether the target was actually met. If nothing
    reaches it, the smallest threshold that maximises precision is returned and
    the shortfall is recorded rather than hidden by lowering the target.
    """
    best_value = 1.0
    best_precision = -1.0
    for tau in candidates(rows):
        accusations, _, precision, _ = precision_recall(rows, tau)
        if accusations == 0:
            continue
        if precision >= target:
            return tau, True
        if precision > best_precision:
            best_value, best_precision = tau, precision
    return best_value, False


def choose_tau_low(rows: Sequence[Row], tau_high: float, fraction: float) -> float:
    """The greatest confidence whose band still captures ``fraction`` of the loss.

    If tau_high gives up no recall at all, the band has nothing to capture and
    the low threshold is set equal to the high one, which empties the near-miss
    band honestly rather than putting an arbitrary number there.
    """
    needs = sum(1 for row in rows if row.needs_accusation)
    if not needs:
        return tau_high
    _, _, _, recall_all = precision_recall(rows, 0.0)
    _, _, _, recall_high = precision_recall(rows, tau_high)
    given_up = recall_all - recall_high
    if given_up <= 0.0:
        return tau_high
    wanted = fraction * given_up

    best = 0.0
    for tau in candidates(rows):
        if tau >= tau_high:
            continue
        captured = (
            sum(
                1
                for row in rows
                if row.eligible and row.correct and tau <= row.confidence < tau_high
            )
            / needs
        )
        if captured >= wanted:
            best = max(best, tau)
    return best


def _write_block(path: Path, block: dict[str, Any], engine: str = ENGINE_NAME) -> None:
    """Insert one engine's block into the committed thresholds document.

    Every other block is left exactly as it is. A phase that retuned the rule
    boundary while adding an engine would churn every golden snapshot and every
    reported finding for a reason that had nothing to do with the rules, and the
    same argument applies in the other direction when P8 adds a fourth.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    document["engines"][engine] = block
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


BERT_ENGINE_NAME = "bert"
"""The P8 engine's name, a string for the reason `scripts/eval.py` gives beside
its own copy: the transformer joins the package's engine list only if the
pre-registered ship condition is met, and until then it is measurable from here
and absent from the tool."""


def _load_engine(engine: str, model_dir: Path) -> Any:
    """Return the engine whose confidences the boundary will be derived on."""
    if engine == BERT_ENGINE_NAME:
        import bert_engine

        return bert_engine.load_bert_engine(model_dir)
    return load_ngram_engine(model_dir)


_BASIS = {
    ENGINE_NAME: "dev split of the seed 20260825 corpus, calibrated n-gram engine",
    BERT_ENGINE_NAME: (
        "dev split of the seed 20260825 corpus, calibrated INT8 encoder. Derived under "
        "the identical policy of experiments/predictions/p4-threshold-derivation.md, "
        "before the test-split run and before the ship condition of spec section 10.7 "
        "was evaluated"
    ),
}
"""What each block says about where its two numbers came from. Required by the
loader and never a default: a threshold that cannot say what produced it is
folklore with a JSON key."""


def main(argv: Sequence[str] | None = None) -> int:
    """Derive, print, and optionally write the thresholds."""
    parser = argparse.ArgumentParser(description="Derive the decision thresholds on dev.")
    parser.add_argument("--corpus", type=Path, default=Path("corpus"))
    parser.add_argument("--split-file", type=Path, default=None)
    parser.add_argument("--model", type=Path, default=Path("models"))
    parser.add_argument(
        "--engine",
        choices=(ENGINE_NAME, BERT_ENGINE_NAME),
        default=ENGINE_NAME,
        help="whose confidences the boundary is derived on, and which block it is written to",
    )
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--target-precision", type=float, default=TARGET_PRECISION)
    parser.add_argument("--band-fraction", type=float, default=RECALL_BAND_FRACTION)
    parser.add_argument("--write", action="store_true", help="update the committed file")
    args = parser.parse_args(argv)

    corpus_dir: Path = args.corpus
    split_path: Path = args.split_file if args.split_file else corpus_dir / "split.json"
    split = train._load_split(split_path)
    guard = train.TestPartitionGuard(frozenset(train._forms_in(split, train.TEST)))
    guard.arm()
    print(f"derive_thresholds: guarding {len(guard.forbidden)} test-partition forms")

    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    base_year = int(manifest.get("base_year", time.gmtime().tm_year))
    train.bind_cache(args.cache, train._corpus_manifest_sha(corpus_dir))
    dev = train.build_dataset(corpus_dir, split, train.DEV, guard, args.cache, base_year)
    print(f"derive_thresholds: {dev.forms} dev forms, {len(dev.examples)} rows")

    engine = _load_engine(args.engine, args.model)
    predictions = engine.predict(dev.descriptors)
    rows = build_rows(dev.examples, predictions)

    needs = sum(1 for row in rows if row.needs_accusation)
    eligible = sum(1 for row in rows if row.eligible)
    print(f"derive_thresholds: {needs} fields need an accusation, {eligible} would receive one")

    print("  tau    accusations   correct   precision   recall")
    for tau in [value / 20 for value in range(0, 21)]:
        accusations, correct, precision, recall = precision_recall(rows, tau)
        print(f"  {tau:<6.2f} {accusations:>11} {correct:>9} {precision:>11.4f} {recall:>8.4f}")

    tau_high, met = choose_tau_high(rows, args.target_precision)
    tau_low = choose_tau_low(rows, tau_high, args.band_fraction)
    accusations, correct, precision, recall = precision_recall(rows, tau_high)
    _, _, _, recall_all = precision_recall(rows, 0.0)
    band = (
        sum(
            1
            for row in rows
            if row.eligible and row.correct and tau_low <= row.confidence < tau_high
        )
        / needs
        if needs
        else 0.0
    )

    print()
    print(f"derive_thresholds: target precision {args.target_precision}")
    print(f"  tau_high            {tau_high!r}")
    print(f"  tau_low             {tau_low!r}")
    print(f"  target met          {met}")
    print(f"  accusations         {accusations}")
    print(f"  correct             {correct}")
    print(f"  dev precision       {precision:.4f}")
    print(f"  dev recall          {recall:.4f}")
    print(f"  recall at any conf  {recall_all:.4f}")
    print(f"  recall given up     {recall_all - recall:.4f}")
    print(f"  band captures       {band:.4f}")
    print(f"  band fraction       {band / (recall_all - recall) if recall_all > recall else 0:.4f}")

    block = {
        "basis": _BASIS[args.engine],
        "tau_high": tau_high,
        "tau_low": tau_low,
        "target_precision": args.target_precision,
        "dev_precision": precision,
        "dev_recall": recall,
        # The denominators, so that the file carries the sample size beside the
        # rate. A precision of one over fifteen accusations and a precision of one
        # over fifteen hundred are the same number and are not the same claim, and
        # a reader of this file should not have to go and find out which it is.
        "dev_accusations": accusations,
        "dev_fields_needing_accusation": needs,
        "dev_recall_at_any_confidence": recall_all,
        "band_fraction_target": args.band_fraction,
        "band_recall_captured": band,
        "corpus_manifest_sha": train._corpus_manifest_sha(corpus_dir),
        "derived_on": datetime.now(UTC).date().isoformat(),
    }
    print()
    print(json.dumps(block, indent=2))

    if args.write:
        _write_block(_REPO_ROOT / THRESHOLDS_PATH, block, args.engine)
        print(f"derive_thresholds: wrote the {args.engine} block to {THRESHOLDS_PATH}")
    else:
        print("derive_thresholds: nothing written; pass --write to update the committed file")
    return 0 if met else 1


if __name__ == "__main__":
    raise SystemExit(main())
