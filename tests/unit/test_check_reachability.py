"""Behaviour of the reachability check.

Two things are asserted: that the check passes on the real tree, and that each
check is capable of failing. The second matters more. Law 2 is only worth
anything if the thing enforcing it can say no.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pytest

import check_reachability

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_every_active_check_passes_on_the_real_tree() -> None:
    results = check_reachability.run_all(REPO_ROOT)
    assert results
    failed = [result.name for result in results if not result.passed]
    assert failed == []


def test_main_exits_zero_on_the_real_tree(capsys: pytest.CaptureFixture[str]) -> None:
    assert check_reachability.main(["--root", str(REPO_ROOT)]) == 0
    output = capsys.readouterr().out
    assert "all active checks passed" in output
    assert "[WAIT]" in output


def test_pending_clauses_name_the_phase_that_activates_them() -> None:
    """The count is deliberately not asserted. It shrinks by one every time a
    phase makes a clause enforceable, and a test that pinned the number would
    have to be edited in the same commit that did the real work, which teaches
    the next person to edit the number rather than to check the property."""
    assert check_reachability.PENDING
    for pending in check_reachability.PENDING:
        assert "activates at P" in pending


def test_result_renders_pass_and_fail() -> None:
    passed = check_reachability.CheckResult("a", True, "fine")
    failed = check_reachability.CheckResult("b", False, "broken")
    assert passed.render() == "  [PASS] a: fine"
    assert failed.render() == "  [FAIL] b: broken"


def test_duplicate_label_values_are_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    class Aliased(StrEnum):
        FIRST = "one"
        SECOND = "two"
        SHADOW = "one"

    monkeypatch.setattr(check_reachability, "Label", Aliased)
    result = check_reachability.check_no_duplicate_label_values(REPO_ROOT)
    assert not result.passed
    assert "SHADOW aliases FIRST" in result.detail


def test_an_empty_taxonomy_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_reachability, "ALL_LABELS", frozenset())
    result = check_reachability.check_taxonomy_populated(REPO_ROOT)
    assert not result.passed
    assert "empty" in result.detail


def test_a_label_in_no_group_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    trimmed = {
        name: members for name, members in check_reachability.GROUPS.items() if name != "payment"
    }
    monkeypatch.setattr(check_reachability, "GROUPS", trimmed)
    result = check_reachability.check_groups_partition(REPO_ROOT)
    assert not result.passed
    assert "labels in no group" in result.detail
    assert "cc-number" in result.detail


def test_a_label_in_two_groups_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = dict(check_reachability.GROUPS)
    groups["shadow"] = groups["payment"]
    monkeypatch.setattr(check_reachability, "GROUPS", groups)
    result = check_reachability.check_groups_partition(REPO_ROOT)
    assert not result.passed
    assert "more than one group" in result.detail


def _fake_tree(root: Path, module_body: str) -> None:
    package = root / "src" / "autofill_audit"
    package.mkdir(parents=True)
    (package / "taxonomy.py").write_text('POSTAL = "postal-code"\n', encoding="utf-8")
    (package / "rules.py").write_text(module_body, encoding="utf-8")
    (root / "scripts").mkdir()


def test_a_stray_label_literal_is_detected(tmp_path: Path) -> None:
    _fake_tree(tmp_path, 'TABLE = {"plz": "postal-code"}\n')
    result = check_reachability.check_no_stray_label_literals(tmp_path)
    assert not result.passed
    assert "rules.py:1" in result.detail
    assert "postal-code" in result.detail


def test_a_docstring_mentioning_a_label_is_not_a_stray_literal(tmp_path: Path) -> None:
    _fake_tree(tmp_path, '"""This module predicts postal-code fields."""\n')
    result = check_reachability.check_no_stray_label_literals(tmp_path)
    assert result.passed


def test_the_taxonomy_module_itself_is_exempt(tmp_path: Path) -> None:
    _fake_tree(tmp_path, "VALUE = 1\n")
    result = check_reachability.check_no_stray_label_literals(tmp_path)
    assert result.passed


def test_pending_no_longer_lists_the_corpus_clause() -> None:
    """P1 moved clause (b) out of PENDING and into CHECKS. Leaving it in both
    would misrepresent a green run as enforcing less than it does, and leaving
    it only in PENDING would misrepresent it as enforcing more."""
    joined = " ".join(check_reachability.PENDING)
    assert "corpus reachability" not in joined
    assert check_reachability.check_corpus_reachability in check_reachability.CHECKS


def test_corpus_reachability_passes_on_the_real_tree() -> None:
    result = check_reachability.check_corpus_reachability(REPO_ROOT)
    assert result.passed, result.detail
    assert "all 42 labels emitted" in result.detail


def test_corpus_reachability_fails_when_a_label_is_emitted_by_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check has to be able to say no, or it is decoration."""

    class Extra(StrEnum):
        GHOST = "GHOST_LABEL"

    monkeypatch.setattr(
        check_reachability,
        "ALL_LABELS",
        frozenset(check_reachability.ALL_LABELS | {Extra.GHOST}),
    )
    result = check_reachability.check_corpus_reachability(REPO_ROOT)
    assert not result.passed
    assert "GHOST_LABEL" in result.detail


def test_corpus_reachability_fails_without_a_sample_corpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = check_reachability.check_corpus_reachability(tmp_path)
    assert not result.passed
    assert "no answer keys" in result.detail
