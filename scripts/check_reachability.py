#!/usr/bin/env python3
"""Law 2 enforcement: no label exists that nothing can reach.

The full rule (spec section 7.3) has four clauses. A label must be (a) a WHATWG
autofill token or an enumerated extra, (b) emitted by at least one corpus answer
key, (c) reachable by at least one rule or present in the model's training
distribution, and (d) asserted by at least one test.

At P0 only clause (a) and the taxonomy's own internal consistency can be
checked, because no corpus, no rule table, and no label-tagged tests exist yet.
This script therefore runs the checks that are possible now and prints the ones
that activate later, rather than pretending the whole law is enforced. The check
functions are independent and are registered in ``CHECKS``, so P1 and P3 extend
this file by adding functions to that list rather than rewriting it.

Usage:
    check_reachability.py [--root DIR]

Exit status is 0 when every active check passes and 1 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from autofill_audit.taxonomy import (  # noqa: E402
    ALL_LABELS,
    EXTRA_LABELS,
    GROUPS,
    SPEC_TOKENS,
    Label,
)

# The taxonomy module owns every label string. Any other module carrying one as
# a literal is the drift ground rule 6 forbids. At P0 the scan is restricted to
# tokens that cannot be confused with ordinary prose or ordinary identifiers:
# the hyphenated specification tokens and the uppercase extras. Single-word
# tokens such as "name", "email", and "url" are excluded because they are also
# ordinary words, and a check that cries wolf is a check that gets disabled.
_UNAMBIGUOUS_LITERALS: frozenset[str] = frozenset(
    {label.value for label in SPEC_TOKENS if "-" in label.value}
    | {label.value for label in EXTRA_LABELS}
)

_TAXONOMY_MODULE = Path("src") / "autofill_audit" / "taxonomy.py"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """The outcome of one reachability check."""

    name: str
    passed: bool
    detail: str

    def render(self) -> str:
        """Format as one aligned result line."""
        mark = "PASS" if self.passed else "FAIL"
        return f"  [{mark}] {self.name}: {self.detail}"


def check_taxonomy_populated(root: Path) -> CheckResult:
    """The label enum must exist and must not be empty."""
    del root
    count = len(ALL_LABELS)
    if count == 0:
        return CheckResult("taxonomy populated", False, "the label set is empty")
    return CheckResult(
        "taxonomy populated",
        True,
        f"{len(SPEC_TOKENS)} specification tokens plus {len(EXTRA_LABELS)} extras",
    )


def check_no_duplicate_label_values(root: Path) -> CheckResult:
    """No two enum members may carry the same string value.

    Two members sharing a value do not raise in Python: the second becomes an
    alias of the first, vanishes from iteration, and silently shrinks the label
    space while the member name still looks live at every call site. That is
    precisely the drift law 2 exists to prevent, so it is checked by comparing
    the declared member names against the canonical members.
    """
    del root
    declared = list(Label.__members__)
    canonical = {label.name for label in Label}
    aliases = [name for name in declared if name not in canonical]
    if aliases:
        detail = ", ".join(
            f"{name} aliases {Label[name].name} on value {Label[name].value!r}" for name in aliases
        )
        return CheckResult("no duplicate label values", False, detail)
    return CheckResult(
        "no duplicate label values",
        True,
        f"{len(declared)} member names, {len(canonical)} distinct labels",
    )


def check_groups_partition(root: Path) -> CheckResult:
    """The group mapping must cover every label exactly once."""
    del root
    seen: dict[Label, list[str]] = {}
    for group, members in GROUPS.items():
        for label in members:
            seen.setdefault(label, []).append(group)

    duplicated = {label: groups for label, groups in seen.items() if len(groups) > 1}
    missing = ALL_LABELS - set(seen)
    problems: list[str] = []
    if duplicated:
        problems.append(
            "labels in more than one group: "
            + ", ".join(
                f"{label.value} in {sorted(groups)}" for label, groups in duplicated.items()
            )
        )
    if missing:
        problems.append(
            "labels in no group: " + ", ".join(sorted(label.value for label in missing))
        )
    if problems:
        return CheckResult("groups partition the taxonomy", False, "; ".join(problems))
    return CheckResult(
        "groups partition the taxonomy",
        True,
        f"{len(GROUPS)} groups cover {len(ALL_LABELS)} labels exactly once",
    )


def _string_constants(tree: ast.AST) -> list[tuple[int, str]]:
    """Return every string constant in ``tree`` that is not a docstring."""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr):
                inner = body[0].value
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    docstrings.add(id(inner))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def check_no_stray_label_literals(root: Path) -> CheckResult:
    """No module other than the taxonomy may carry a label string as a literal.

    Ground rule 6: the taxonomy has exactly one definition in code. A rule
    table, a training script, or a renderer that spells a label out as a string
    can drift from the enum without any test noticing.
    """
    offences: list[str] = []
    scanned = 0
    for source in sorted((root / "src").rglob("*.py")) + sorted((root / "scripts").rglob("*.py")):
        relative = source.relative_to(root)
        if relative == _TAXONOMY_MODULE:
            continue
        scanned += 1
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(relative))
        for lineno, value in _string_constants(tree):
            if value in _UNAMBIGUOUS_LITERALS:
                offences.append(f"{relative}:{lineno}: label literal {value!r}")
    if offences:
        return CheckResult("no stray label literals", False, "; ".join(offences))
    return CheckResult(
        "no stray label literals",
        True,
        f"{scanned} modules scanned, taxonomy remains the only definition",
    )


CHECKS: list[Callable[[Path], CheckResult]] = [
    check_taxonomy_populated,
    check_no_duplicate_label_values,
    check_groups_partition,
    check_no_stray_label_literals,
]

# Clauses of the law that no artefact exists to check yet. Each names the phase
# that activates it, so that a reader of a green P0 run is not misled into
# thinking law 2 is fully enforced.
PENDING: list[str] = [
    "corpus reachability (every label emitted by at least one answer key): activates at P1",
    "rule reachability (every label produced by at least one rule): activates at P3",
    "test reachability (every label asserted by at least one test): activates at P3",
]


def run_all(root: Path) -> list[CheckResult]:
    """Run every active check and return the results in registration order."""
    return [check(root) for check in CHECKS]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check and return the process exit status."""
    parser = argparse.ArgumentParser(description="Enforce taxonomy reachability (law 2).")
    parser.add_argument("--root", type=Path, default=_REPO_ROOT, help="repository root")
    args = parser.parse_args(argv)

    results = run_all(args.root)
    print("check_reachability: active checks")
    for result in results:
        print(result.render())

    print("check_reachability: checks not yet active")
    for pending in PENDING:
        print(f"  [WAIT] {pending}")

    failed = [result for result in results if not result.passed]
    if failed:
        print(f"check_reachability: {len(failed)} check(s) failed", file=sys.stderr)
        return 1
    print("check_reachability: all active checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
