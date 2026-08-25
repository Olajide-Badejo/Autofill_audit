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
    assert len(check_reachability.PENDING) == 3
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
