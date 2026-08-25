#!/usr/bin/env python3
"""Law 3 enforcement: no number in prose unless it traces to a result file.

Scans the README, everything under ``docs/``, and (once they exist) the LaTeX
sources under ``report/``, ``report_debug/``, and ``report_for_me/``, looking for
numeric literals that read as measurements. A match is a violation unless the
line names the result file it came from.

Being pragmatic beats being complete here, because a check that flags a year, a
section number, or a pinned dependency version is a check somebody switches off
within a week. So the rule is stated positively: a number is a violation when it
is shaped like a measurement, not merely when it is a number. Three shapes
count.

1. A percentage: any number immediately followed by a percent sign, or by the
   word "percent".
2. A probability-shaped decimal: one decimal point, a leading 0 or 1, which is
   the shape every accuracy, precision, recall, F1, and calibration figure in
   this project takes.
3. A number sharing a line with a measurement word: accuracy, latency, F1, the
   percentiles, and the counting nouns that describe run outputs.

Deliberately never flagged, because none of them are measurements: anything
inside a fenced code block or an inline code span, anything inside a URL,
version strings of three or more components, four-digit years, ISO dates,
bracketed reference numbers, markdown list markers and heading levels, and table
rule rows.

Two things clear a line that would otherwise be a violation:

- a result reference, meaning a path under ``experiments/results/`` or a
  ``results:`` key naming a file, on the same line; or
- an explicit annotation ``<!-- traceability: reason -->`` on the same line or
  the line above, for numbers that are configuration rather than measurement.
  The reason is required, so waving the check through leaves a written trace.

Usage:
    check_traceability.py [--root DIR] [PATH ...]

Exit status is 0 when clean and 1 when any violation is found.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

MEASUREMENT_WORDS: frozenset[str] = frozenset(
    {
        "accuracy",
        "auc",
        "calibration",
        "ece",
        "errors",
        "examples",
        "f1",
        "failures",
        "findings",
        "forms",
        "faster",
        "latency",
        "macro",
        "micro",
        "milliseconds",
        "misclassifications",
        "p50",
        "p95",
        "p99",
        "percentile",
        "precision",
        "recall",
        "roc",
        "runs",
        "slower",
        "speedup",
        "throughput",
    }
)

DEFAULT_GLOBS: tuple[tuple[str, str], ...] = (
    ("", "README.md"),
    ("docs", "**/*.md"),
    ("report", "**/*.tex"),
    ("report_debug", "**/*.tex"),
    ("report_for_me", "**/*.tex"),
)

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_URL_RE = re.compile(r"https?://\S+|\S+@\S+\.\S+")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_VERSION_RE = re.compile(r"\bv?\d+(?:\.\d+){2,}\b")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_REFERENCE_RE = re.compile(r"\[\d+\]")
_LIST_MARKER_RE = re.compile(r"^\s{0,8}(?:[-*+]\s|\d{1,3}[.)]\s|#{1,6}\s)")
_TABLE_RULE_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")

_RESULT_REFERENCE_RE = re.compile(r"experiments/results/|\bresults:\s*\S+")
_ANNOTATION_RE = re.compile(r"<!--\s*traceability:\s*\S[^>]*-->")

_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|percent\b)")
_PROBABILITY_RE = re.compile(r"(?<![\w.])[01]\.\d+(?![\w.])")
_ANY_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")


@dataclass(frozen=True, slots=True)
class Violation:
    """One untraceable number at one position in one file."""

    path: str
    line: int
    excerpt: str
    reason: str

    def render(self) -> str:
        """Format as the ``file:line: reason`` line the CI log shows."""
        return f"{self.path}:{self.line}: {self.reason}: {self.excerpt!r}"


def _strip_uncheckable(line: str) -> str:
    """Blank out the parts of a line that are never measurements."""
    for pattern in (
        _INLINE_CODE_RE,
        _URL_RE,
        _ISO_DATE_RE,
        _VERSION_RE,
        _YEAR_RE,
        _REFERENCE_RE,
    ):
        line = pattern.sub(" ", line)
    return _LIST_MARKER_RE.sub(" ", line)


def _classify(line: str) -> str | None:
    """Return the reason ``line`` is a violation, or None when it is clean."""
    if _PERCENT_RE.search(line):
        return "percentage in prose with no result-file reference"
    if _PROBABILITY_RE.search(line):
        return "probability-shaped number with no result-file reference"
    if _ANY_NUMBER_RE.search(line):
        words = {word.casefold() for word in _WORD_RE.findall(line)}
        shared = sorted(words & MEASUREMENT_WORDS)
        if shared:
            return f"number beside measurement word {shared[0]!r} with no result-file reference"
    return None


def scan_text(text: str, *, display_path: str) -> list[Violation]:
    """Find every untraceable measurement-shaped number in already decoded text."""
    violations: list[Violation] = []
    in_fence = False
    previous_annotated = False
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            previous_annotated = False
            continue
        annotated = bool(_ANNOTATION_RE.search(raw))
        if in_fence or _TABLE_RULE_RE.match(raw):
            previous_annotated = annotated
            continue
        if annotated or previous_annotated or _RESULT_REFERENCE_RE.search(raw):
            previous_annotated = annotated
            continue
        reason = _classify(_strip_uncheckable(raw))
        if reason is not None:
            violations.append(
                Violation(
                    path=display_path,
                    line=line_number,
                    excerpt=raw.strip()[:120],
                    reason=reason,
                )
            )
        previous_annotated = annotated
    return violations


def scan_file(path: Path, *, display_path: str | None = None) -> list[Violation]:
    """Scan one prose file."""
    shown = display_path if display_path is not None else str(path)
    return scan_text(path.read_text(encoding="utf-8"), display_path=shown)


def default_targets(root: Path) -> list[Path]:
    """Return every prose file the check covers, as paths relative to ``root``."""
    targets: list[Path] = []
    for subdirectory, pattern in DEFAULT_GLOBS:
        base = root / subdirectory if subdirectory else root
        if not base.is_dir():
            continue
        targets.extend(sorted(path.relative_to(root) for path in base.glob(pattern)))
    return targets


def scan_paths(paths: Iterable[Path], *, root: Path) -> list[Violation]:
    """Scan a set of paths interpreted relative to ``root``."""
    violations: list[Violation] = []
    for relative in paths:
        absolute = relative if relative.is_absolute() else root / relative
        violations.extend(scan_file(absolute, display_path=str(relative)))
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check and return the process exit status."""
    parser = argparse.ArgumentParser(description="Enforce number traceability (law 3).")
    parser.add_argument(
        "paths", nargs="*", type=Path, help="files to scan; default is the docs set"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    args = parser.parse_args(argv)

    root: Path = args.root
    targets: list[Path] = list(args.paths) if args.paths else default_targets(root)
    violations = scan_paths(targets, root=root)

    for violation in violations:
        print(violation.render())

    if violations:
        count = len(violations)
        noun = "number" if count == 1 else "numbers"
        print(f"check_traceability: {count} untraceable {noun} found", file=sys.stderr)
        return 1

    print(f"check_traceability: clean, {len(targets)} files scanned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
