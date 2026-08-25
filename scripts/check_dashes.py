#!/usr/bin/env python3
"""Ground rule 13, the mechanical half: no em dash, no en dash, anywhere.

Walks every tracked text file as reported by ``git ls-files`` and fails with a
``file:line:column`` report on any occurrence of U+2014 (em dash) or U+2013 (en
dash). In ``.tex`` sources it additionally rejects the ligature forms ``--`` and
``---``, because LaTeX typesets those to exactly the two forbidden characters,
so allowing them in source would let the rule be evaded at the last step.

The check is deliberately dumb and fast: two codepoints, one pass over each
file, no configuration surface and nothing to argue with.

Usage:
    check_dashes.py                     scan every tracked file under the repo
    check_dashes.py PATH [PATH ...]     scan exactly these files
    check_dashes.py --root DIR          run git ls-files in DIR instead of cwd

Exit status is 0 when clean and 1 when any violation is found.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

# Extensions whose contents are not text and are therefore not scanned. Kept
# short on purpose: anything not listed here is read and decoded, and a file
# that fails to decode as UTF-8 is reported as skipped rather than ignored
# silently, so the list cannot quietly grow into a way to hide a violation.
BINARY_SUFFIXES: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".pdf",
        ".onnx",
        ".npy",
        ".npz",
        ".gz",
        ".zip",
        ".whl",
        ".so",
        ".wasm",
        ".mp4",
        ".webm",
    }
)

# Built from codepoints on purpose: this file is itself scanned by this check,
# so the two forbidden characters must never appear literally in it.
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

_DASH_RE = re.compile(f"[{EN_DASH}{EM_DASH}]")
_TEX_LIGATURE_RE = re.compile(r"-{2,}")

_DASH_NAMES = {EM_DASH: "U+2014 em dash", EN_DASH: "U+2013 en dash"}


@dataclass(frozen=True, slots=True)
class Violation:
    """One forbidden sequence at one position in one file."""

    path: str
    line: int
    column: int
    reason: str

    def render(self) -> str:
        """Format as the ``file:line:column: reason`` line the CI log shows."""
        return f"{self.path}:{self.line}:{self.column}: {self.reason}"


def is_scannable(path: Path) -> bool:
    """Return True when the file's extension is not on the binary skip list."""
    return path.suffix.lower() not in BINARY_SUFFIXES


def scan_text(text: str, *, display_path: str, is_tex: bool) -> list[Violation]:
    """Find every forbidden sequence in already decoded text.

    Args:
        text: the full file contents.
        display_path: the path to print in the report.
        is_tex: when True, also reject the LaTeX ligature forms ``--`` and ``---``.

    Returns:
        Every violation found, in file order.
    """
    violations: list[Violation] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in _DASH_RE.finditer(line):
            character = match.group()
            violations.append(
                Violation(
                    path=display_path,
                    line=line_number,
                    column=match.start() + 1,
                    reason=f"forbidden {_DASH_NAMES[character]}",
                )
            )
        if is_tex:
            for match in _TEX_LIGATURE_RE.finditer(line):
                run = match.group()
                violations.append(
                    Violation(
                        path=display_path,
                        line=line_number,
                        column=match.start() + 1,
                        reason=(
                            f"forbidden LaTeX ligature {run!r}, which typesets to a "
                            "dash this project does not use"
                        ),
                    )
                )
    return violations


def scan_file(path: Path, *, display_path: str | None = None) -> list[Violation]:
    """Scan one file, skipping it when it is binary or not decodable as UTF-8."""
    shown = display_path if display_path is not None else str(path)
    if not is_scannable(path):
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"check_dashes: skipped {shown}: not valid UTF-8 text", file=sys.stderr)
        return []
    except OSError as error:
        print(f"check_dashes: skipped {shown}: {error}", file=sys.stderr)
        return []
    return scan_text(text, display_path=shown, is_tex=path.suffix.lower() == ".tex")


def tracked_files(root: Path) -> list[Path]:
    """Return every file git tracks under ``root``, as paths relative to it."""
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(entry) for entry in completed.stdout.split("\0") if entry]


def scan_paths(paths: Iterable[Path], *, root: Path) -> list[Violation]:
    """Scan a set of paths interpreted relative to ``root``."""
    violations: list[Violation] = []
    for relative in paths:
        absolute = relative if relative.is_absolute() else root / relative
        violations.extend(scan_file(absolute, display_path=str(relative)))
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check and return the process exit status."""
    parser = argparse.ArgumentParser(description="Reject em dashes and en dashes.")
    parser.add_argument("paths", nargs="*", type=Path, help="files to scan; default is all tracked")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    args = parser.parse_args(argv)

    root: Path = args.root
    targets: list[Path] = list(args.paths) if args.paths else tracked_files(root)
    violations = scan_paths(targets, root=root)

    for violation in violations:
        print(violation.render())

    if violations:
        count = len(violations)
        noun = "violation" if count == 1 else "violations"
        print(f"check_dashes: {count} {noun} found", file=sys.stderr)
        return 1

    print(f"check_dashes: clean, {len(targets)} files scanned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
