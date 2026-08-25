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
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from autofill_audit.classify.rules_table import labels_with_rules  # noqa: E402
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

_TAXONOMY_DOC = Path("docs") / "taxonomy.md"
_EXEMPTION_HEADING = "### Rule reachability exemptions"
_EXEMPTION_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*$")
_MIN_REASON_LENGTH = 40
"""How much prose an exemption has to carry to count as one.

Not a style rule. An exemption is a written argument that a label cannot be
reached by a rule, and one word is not an argument. Forty characters is roughly
one clause of English, which is the shortest thing that can be disagreed with."""


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


def _documented_exemptions(root: Path) -> tuple[set[Label], list[str]]:
    """Read the rule-reachability exemption table out of ``docs/taxonomy.md``.

    Clause (c) allows a label to have no rule when the taxonomy document says
    why. Reading the exemptions from the document rather than from a constant in
    this file is what makes the written reason load bearing: an exemption with no
    prose beside it does not exist, and deleting the prose deletes the exemption.

    Returns the exempt labels and any problems with the table itself.
    """
    document = root / _TAXONOMY_DOC
    problems: list[str] = []
    if not document.is_file():
        return set(), [f"{_TAXONOMY_DOC} is missing, so no exemption can be documented"]

    lines = document.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index(_EXEMPTION_HEADING)
    except ValueError:
        return set(), [f"{_TAXONOMY_DOC} has no {_EXEMPTION_HEADING!r} section"]

    exempt: set[Label] = set()
    for line in lines[start + 1 :]:
        if line.startswith("## ") or (line.startswith("### ") and line != _EXEMPTION_HEADING):
            break
        match = _EXEMPTION_ROW.match(line)
        if match is None:
            continue
        name, reason = match.group(1), match.group(2).strip()
        try:
            label = Label(name)
        except ValueError:
            problems.append(f"{_TAXONOMY_DOC} exempts {name!r}, which is not a label")
            continue
        if len(reason) < _MIN_REASON_LENGTH:
            problems.append(f"{_TAXONOMY_DOC}: the exemption for {name} states no real reason")
            continue
        exempt.add(label)
    return exempt, problems


def check_rule_reachability(root: Path) -> CheckResult:
    """Law 2 clause (c): every label is produced by a rule, or is documented.

    The reachable set is read from the rule tables themselves rather than from a
    list kept beside them, so the check cannot drift from the code it checks. A
    label that is both exempt and reachable is reported too: a stale exemption
    quietly weakens the law for whichever label acquires a rule next.
    """
    name = "rule reachability"
    reachable = labels_with_rules()
    exempt, problems = _documented_exemptions(root)

    missing = ALL_LABELS - reachable - exempt
    if missing:
        problems.append(
            "no rule produces, and nothing documents, "
            + ", ".join(sorted(label.value for label in missing))
        )
    stale = exempt & reachable
    if stale:
        problems.append(
            "documented as unreachable but reachable by a rule: "
            + ", ".join(sorted(label.value for label in stale))
        )
    if problems:
        return CheckResult(name, False, "; ".join(problems))
    detail = f"{len(reachable)} of {len(ALL_LABELS)} labels reachable by at least one rule"
    if exempt:
        detail += "; documented as unreachable: " + ", ".join(
            sorted(label.value for label in exempt)
        )
    return CheckResult(name, True, detail)


_COLLECTOR_PLUGIN = '''
"""Collect the label markers of a pytest run into a JSON file."""
import json
import os


def pytest_collection_modifyitems(session, config, items):
    seen = set()
    for item in items:
        for marker in item.iter_markers("label"):
            seen.update(str(argument) for argument in marker.args)
    with open(os.environ["AUTOFILL_AUDIT_LABEL_OUT"], "w", encoding="utf-8") as handle:
        json.dump(sorted(seen), handle)
'''


def collect_label_markers(root: Path) -> tuple[set[str], str | None]:
    """Return every label named by a ``label`` marker in the test suite.

    A real pytest collection, in a subprocess, rather than a parse of the test
    sources. Spec section 7.3 asks for a "pytest collection of label-tagged
    tests" and the difference is not pedantry: the table that covers all forty
    two labels tags its cases from a loop, so the marker's argument is a
    computed value that no static reader could resolve. Collection resolves it
    because collection is the thing that builds the parameters.

    A subprocess because this check is itself exercised by the test suite, and
    calling ``pytest.main`` from inside a pytest run is asking for trouble.
    """
    with tempfile.TemporaryDirectory() as work:
        workdir = Path(work)
        (workdir / "_label_collector.py").write_text(_COLLECTOR_PLUGIN, encoding="utf-8")
        out = workdir / "labels.json"
        environment = dict(os.environ)
        environment["AUTOFILL_AUDIT_LABEL_OUT"] = str(out)
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(workdir), environment.get("PYTHONPATH", "")]
        ).strip(os.pathsep)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "--no-cov",
                "-p",
                "no:cacheprovider",
                "-p",
                "_label_collector",
                str(root / "tests"),
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if not out.is_file():
            tail = (completed.stderr or completed.stdout).strip().splitlines()[-5:]
            return set(), "pytest collection produced nothing: " + " | ".join(tail)
        return set(json.loads(out.read_text(encoding="utf-8"))), None


def check_test_reachability(root: Path) -> CheckResult:
    """Law 2 clause (d): every label is asserted by at least one test."""
    name = "test reachability"
    tagged, error = collect_label_markers(root)
    if error is not None:
        return CheckResult(name, False, error)

    unknown = tagged - {label.value for label in ALL_LABELS}
    if unknown:
        return CheckResult(
            name,
            False,
            "tests are tagged with labels that do not exist: " + ", ".join(sorted(unknown)),
        )
    missing = {label.value for label in ALL_LABELS} - tagged
    if missing:
        return CheckResult(name, False, "no test asserts " + ", ".join(sorted(missing)))
    return CheckResult(name, True, f"all {len(ALL_LABELS)} labels carry a label-tagged test")


CHECKS: list[Callable[[Path], CheckResult]] = [
    check_taxonomy_populated,
    check_no_duplicate_label_values,
    check_groups_partition,
    check_no_stray_label_literals,
    check_corpus_reachability,
    check_rule_reachability,
    check_test_reachability,
]

# Clauses of the law that no artefact exists to check yet. Empty since P3, which
# activated the last two. It stays in the file rather than being deleted: a later
# phase that adds a clause it cannot yet enforce puts it here and says which
# phase will, instead of quietly enforcing three quarters of a law.
PENDING: list[str] = []


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

    if PENDING:
        print("check_reachability: checks not yet active")
        for pending in PENDING:
            print(f"  [WAIT] {pending}")
    else:
        print("check_reachability: all four clauses of law 2 are enforced")

    failed = [result for result in results if not result.passed]
    if failed:
        print(f"check_reachability: {len(failed)} check(s) failed", file=sys.stderr)
        return 1
    print("check_reachability: all active checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
