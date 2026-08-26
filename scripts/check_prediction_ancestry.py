#!/usr/bin/env python3
"""Law 4 enforcement: a prediction is committed before the thing it predicts.

Spec section 18 states the mechanism in one sentence: `experiments/predictions/`
holds a file saying what a run is expected to show and why, it is committed
before the run, and this script verifies that the prediction commit is an
ancestor of the result commit. Without it, law 4 is an intention, and an
intention is exactly what it is trying to replace.

The mapping problem, and how it is solved
-----------------------------------------

The obvious design, "every result directory has a prediction file beside it",
does not survive contact with the first real case. P4's prediction file
predicted the values of `src/autofill_audit/audit/thresholds.json`, a runtime
configuration file that lives nowhere near `experiments/results/`, so a check
that only looked at result directories would have found nothing to verify on the
one case that already existed.

So the mapping is declared rather than inferred. Each prediction file carries a
front matter block naming the paths it predicts about, and the ancestry is
checked against the commit that last touched each of them. A prediction that
names nothing, or names paths nothing has committed yet, passes: it has made no
claim that can yet be violated, which is also why this check passes trivially in
a pull request that touched no results.

Front matter, in full
---------------------

A block delimited by lines of three hyphens, at the very top of the file:

    ---
    predicts:
      - experiments/results/
      - src/autofill_audit/audit/thresholds.json
    amended: 2026-08-26, front matter added; no prediction text changed
    ---

`predicts` is a list of repository-relative paths. A path ending in a separator,
or naming a directory, covers every tracked file under it.

`amended` is required exactly when the prediction file has commits after the one
that added it. A prediction that was edited after the fact is the failure mode
this whole mechanism exists to prevent, so the edit cannot be invisible: either
it happened before every artefact it predicts, in which case the ancestry check
covers it, or it is declared here in one line saying when and why.

Usage:
    check_prediction_ancestry.py [--root DIR] [--predictions DIR]

Exit status is 0 when every prediction precedes what it predicts, and 1 when any
does not.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

PREDICTIONS_DIR = Path("experiments") / "predictions"
FRONT_MATTER_FENCE = "---"


class GitError(RuntimeError):
    """A git command this check depends on could not be run."""


@dataclass(frozen=True, slots=True)
class FrontMatter:
    """The machine-readable header of one prediction file."""

    predicts: tuple[str, ...] = ()
    amended: str | None = None
    present: bool = False


@dataclass(slots=True)
class Report:
    """What the check found, so a caller can print it and a test can assert it."""

    checked: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether every prediction preceded what it predicts."""
        return not self.violations


def parse_front_matter(text: str) -> FrontMatter:
    """Read the front matter block, or report that there is none.

    A hand-written parser rather than a YAML dependency. The grammar is two keys
    and a list, the whole point of it is to be checkable by a script that runs in
    every pull request, and adding a parser dependency to a repository-hygiene
    check would be adding a way for the check to stop running.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_FENCE:
        return FrontMatter()
    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == FRONT_MATTER_FENCE
        )
    except StopIteration:
        return FrontMatter()

    predicts: list[str] = []
    amended: str | None = None
    key: str | None = None
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and key == "predicts":
            predicts.append(stripped[2:].strip().strip("'\""))
            continue
        if ":" in stripped:
            name, _, value = stripped.partition(":")
            key = name.strip()
            value = value.strip()
            if key == "amended" and value:
                amended = value
            elif key == "predicts" and value:
                predicts.extend(part.strip() for part in value.split(",") if part.strip())
    return FrontMatter(predicts=tuple(predicts), amended=amended, present=True)


def _git(root: Path, *arguments: str) -> str:
    """Run one git command, raising when git itself is unavailable."""
    try:
        completed = subprocess.run(
            ["git", *arguments], cwd=root, capture_output=True, text=True, check=False
        )
    except OSError as error:  # pragma: no cover - git is present on the build machine
        raise GitError(f"git could not be run: {error}") from error
    return completed.stdout.strip()


def _is_ancestor(root: Path, earlier: str, later: str) -> bool:
    """Whether ``earlier`` is an ancestor of ``later``, or is the same commit."""
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", earlier, later],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def commits_touching(root: Path, path: str) -> list[str]:
    """Every commit that touched ``path``, newest first."""
    output = _git(root, "log", "--format=%H", "--", path)
    return [line for line in output.splitlines() if line]


def adding_commit(root: Path, path: str) -> str | None:
    """The commit that first added ``path``, which is when the claim was made."""
    output = _git(root, "log", "--diff-filter=A", "--format=%H", "--", path)
    commits = [line for line in output.splitlines() if line]
    return commits[-1] if commits else None


def tracked_under(root: Path, target: str) -> list[str]:
    """Every tracked path at or under ``target``.

    A prediction may name a single file or a directory. A directory is the
    normal case for a run: a prediction about the test split predicts about
    every result directory written after it, and enumerating them one by one
    would mean editing the prediction file after the measurement, which is the
    thing this check exists to catch.
    """
    output = _git(root, "ls-files", "--", target)
    return [line for line in output.splitlines() if line]


def check_file(root: Path, prediction: Path, report: Report) -> None:
    """Verify one prediction file against everything it names."""
    relative = prediction.relative_to(root).as_posix()
    matter = parse_front_matter(prediction.read_text(encoding="utf-8"))

    if not matter.present:
        report.violations.append(
            f"{relative}: no front matter. A prediction file must name the paths it "
            "predicts about, or nothing can check that it came first."
        )
        return

    added = adding_commit(root, relative)
    if added is None:
        report.skipped.append(f"{relative}: not committed yet, so nothing to check")
        return

    touching = commits_touching(root, relative)
    later = [commit for commit in touching if commit != added]
    if later and not matter.amended:
        report.violations.append(
            f"{relative}: {len(later)} commit(s) after the one that added it, and no "
            "'amended:' line saying when and why. A prediction edited after the fact is "
            "the failure law 4 exists to prevent, so the edit has to be declared."
        )
        return

    if not matter.predicts:
        report.skipped.append(f"{relative}: predicts nothing yet")
        return

    for target in matter.predicts:
        paths = tracked_under(root, target)
        if not paths:
            report.skipped.append(f"{relative}: {target} has nothing committed under it yet")
            continue
        for path in paths:
            commits = commits_touching(root, path)
            if not commits:  # pragma: no cover - ls-files listed it, so it has a commit
                continue
            newest = commits[0]
            if _is_ancestor(root, added, newest):
                report.checked.append(f"{relative} ({added[:7]}) precedes {path} ({newest[:7]})")
                continue
            report.violations.append(
                f"{relative}: its commit {added[:7]} is not an ancestor of {path}, whose "
                f"newest commit is {newest[:7]}. The prediction did not come first."
            )


def run(root: Path, predictions: Path) -> Report:
    """Check every prediction file under ``predictions``."""
    report = Report()
    directory = root / predictions
    if not directory.is_dir():
        return report
    for prediction in sorted(directory.glob("*.md")):
        check_file(root, prediction, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check and return the process exit status."""
    parser = argparse.ArgumentParser(description="Enforce prediction ancestry (law 4).")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--predictions", type=Path, default=PREDICTIONS_DIR)
    args = parser.parse_args(argv)

    try:
        report = run(args.root.resolve(), args.predictions)
    except GitError as error:
        print(f"check_prediction_ancestry: {error}", file=sys.stderr)
        return 1

    for line in report.checked:
        print(f"  ok        {line}")
    for line in report.skipped:
        print(f"  skipped   {line}")
    for line in report.violations:
        print(f"  VIOLATION {line}", file=sys.stderr)

    if report.violations:
        count = len(report.violations)
        noun = "prediction" if count == 1 else "predictions"
        print(
            f"check_prediction_ancestry: {count} {noun} did not precede what they predict",
            file=sys.stderr,
        )
        return 1

    print(
        f"check_prediction_ancestry: clean, {len(report.checked)} ancestry relations "
        f"verified, {len(report.skipped)} nothing to check yet"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
