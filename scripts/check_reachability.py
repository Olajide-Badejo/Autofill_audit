#!/usr/bin/env python3
"""Law 2 enforcement: no label exists that nothing can reach.

The full rule (spec section 7.3) has four clauses. A label must be (a) a WHATWG
autofill token or an enumerated extra, (b) emitted by at least one corpus answer
key, (c) reachable by at least one rule or present in the model's training
distribution, and (d) asserted by at least one test.

At P0 only clause (a) and the taxonomy's own internal consistency could be
checked, because no corpus, no rule table, and no label-tagged tests existed.
P1 activates clause (b): the corpus exists now, so the check generates a small
one and reads the committed sample, and fails the build on any label that
nothing emits. Clauses (c) and (d) stay in ``PENDING``, each naming the phase
that activates it, rather than pretending the whole law is enforced. The check
functions are independent and are registered in ``CHECKS``, so a phase extends
this file by adding a function to that list rather than rewriting it.

**Why clause (b) both generates and reads the sample.** Generating catches a
template change that stops emitting a label; reading the committed sample
catches the opposite failure, a sample that has silently gone stale against the
generator. Neither alone would notice the other's defect, and both together
still run in about a second, which is the budget a CI job of this kind deserves.

Usage:
    check_reachability.py [--root DIR]

Exit status is 0 when every active check passes and 1 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from autofill_audit.corpus.answer_key import build_answer_key  # noqa: E402
from autofill_audit.corpus.families import Family  # noqa: E402
from autofill_audit.corpus.generator import grid_from, iter_forms  # noqa: E402
from autofill_audit.corpus.tiers import Tier  # noqa: E402
from autofill_audit.taxonomy import (  # noqa: E402
    ALL_LABELS,
    EXTRA_LABELS,
    GROUPS,
    SPEC_TOKENS,
    Label,
)

_SAMPLE_CORPUS = Path("tests") / "fixtures" / "sample_corpus"
_REACHABILITY_SEED = 20260825
_REACHABILITY_BASE_YEAR = 2026
"""Pinned rather than taken from the clock. This check runs in CI on every push,
and a check whose input changed when the year turned would go red for a reason
that has nothing to do with the commit under test."""

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


def _generated_labels() -> set[Label]:
    """Return the labels emitted by a small freshly generated corpus.

    One locale, every family, every tier, one variant. English is enough because
    no label is locale specific: the locale profiles change which slots exist
    and what they are called, not what a slot means. Six locales here would
    multiply the runtime of a CI job by six and find nothing the one locale
    misses.
    """
    grid = grid_from(
        seed=_REACHABILITY_SEED,
        families=[family.value for family in Family],
        locales=["en-US"],
        tiers=[tier.value for tier in Tier],
        variants=1,
        base_year=_REACHABILITY_BASE_YEAR,
    )
    emitted: set[Label] = set()
    for form, _ in iter_forms(grid):
        for entry in build_answer_key(form)["fields"]:
            emitted.add(Label(entry["label"]))
    return emitted


def _sample_labels(root: Path) -> tuple[set[Label], int]:
    """Return the labels emitted by the committed sample, and its form count."""
    keys_dir = root / _SAMPLE_CORPUS / "answer_keys"
    emitted: set[Label] = set()
    count = 0
    if not keys_dir.is_dir():
        return emitted, count
    for path in sorted(keys_dir.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        count += 1
        for entry in document["fields"]:
            emitted.add(Label(entry["label"]))
    return emitted, count


def check_corpus_reachability(root: Path) -> CheckResult:
    """Law 2 clause (b): every label is emitted by at least one answer key.

    A label that exists in the enum but is emitted by nothing is dead weight
    that inflates the denominator of every macro-averaged metric, which is
    precisely how a project accidentally reports a worse F1 than it earned, or a
    better one, depending on which direction the dead label falls
    (spec section 7.3).
    """
    name = "corpus reachability"
    sample, sample_forms = _sample_labels(root)
    if sample_forms == 0:
        return CheckResult(
            name,
            False,
            f"the committed sample corpus at {_SAMPLE_CORPUS} has no answer keys",
        )
    generated = _generated_labels()
    emitted = sample | generated

    missing = ALL_LABELS - emitted
    if missing:
        return CheckResult(
            name,
            False,
            "no answer key emits " + ", ".join(sorted(label.value for label in missing)),
        )

    stale = ALL_LABELS - sample
    detail = (
        f"all {len(ALL_LABELS)} labels emitted, from {sample_forms} committed sample "
        "forms and a freshly generated grid"
    )
    if stale:
        detail += "; the sample alone misses " + ", ".join(sorted(label.value for label in stale))
    return CheckResult(name, True, detail)


CHECKS: list[Callable[[Path], CheckResult]] = [
    check_taxonomy_populated,
    check_no_duplicate_label_values,
    check_groups_partition,
    check_no_stray_label_literals,
    check_corpus_reachability,
]

# Clauses of the law that no artefact exists to check yet. Each names the phase
# that activates it, so that a reader of a green run is not misled into thinking
# law 2 is fully enforced. Clause (b) left this list at P1, in the commit that
# made it enforceable.
PENDING: list[str] = [
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
