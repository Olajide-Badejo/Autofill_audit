"""Behaviour of the dash check.

The forbidden characters are built with ``chr()`` here for the same reason the
check itself does it: this file is scanned by the check it is testing, so a
literal would make the test suite fail its own gate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import check_dashes

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def test_clean_text_produces_no_violations() -> None:
    text = "A plain sentence, with a comma: and a hyphenated-word.\n"
    assert check_dashes.scan_text(text, display_path="clean.md", is_tex=False) == []


def test_em_dash_is_reported_with_line_and_column() -> None:
    text = f"first line\nsecond {EM_DASH} line\n"
    violations = check_dashes.scan_text(text, display_path="planted.md", is_tex=False)
    assert len(violations) == 1
    violation = violations[0]
    assert violation.line == 2
    assert violation.column == 8
    assert "U+2014" in violation.reason
    assert violation.render().startswith("planted.md:2:8: ")


def test_en_dash_is_reported() -> None:
    violations = check_dashes.scan_text(
        f"range 1{EN_DASH}9\n", display_path="planted.md", is_tex=False
    )
    assert len(violations) == 1
    assert "U+2013" in violations[0].reason


def test_hyphens_are_fine_in_markdown() -> None:
    text = "a plain hyphen - and a range 1-9 and an option --root\n"
    assert check_dashes.scan_text(text, display_path="fine.md", is_tex=False) == []


def test_tex_ligatures_are_rejected() -> None:
    text = "pages 12--15 and a break --- here\n"
    violations = check_dashes.scan_text(text, display_path="report.tex", is_tex=True)
    assert len(violations) == 2
    assert all("ligature" in violation.reason for violation in violations)


def test_single_hyphen_is_allowed_in_tex() -> None:
    assert check_dashes.scan_text("well-formed\n", display_path="a.tex", is_tex=True) == []


def test_binary_extensions_are_skipped(tmp_path: Path) -> None:
    binary = tmp_path / "logo.png"
    binary.write_bytes(EM_DASH.encode("utf-8"))
    assert not check_dashes.is_scannable(binary)
    assert check_dashes.scan_file(binary) == []


def test_undecodable_file_is_skipped_with_a_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.md"
    broken.write_bytes(b"\xff\xfe not utf eight")
    assert check_dashes.scan_file(broken) == []
    assert "not valid UTF-8" in capsys.readouterr().err


def test_missing_file_is_skipped_with_a_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check_dashes.scan_file(tmp_path / "absent.md") == []
    assert "skipped" in capsys.readouterr().err


def test_scan_file_detects_tex_by_suffix(tmp_path: Path) -> None:
    source = tmp_path / "main.tex"
    source.write_text("pages 1--2\n", encoding="utf-8")
    violations = check_dashes.scan_file(source)
    assert len(violations) == 1


def test_main_returns_zero_on_clean_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "clean.md").write_text("nothing to see here\n", encoding="utf-8")
    exit_code = check_dashes.main(["--root", str(tmp_path), "clean.md"])
    assert exit_code == 0
    assert "clean, 1 files scanned" in capsys.readouterr().out


def test_main_returns_one_on_a_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "dirty.md").write_text(f"a {EM_DASH} b\n", encoding="utf-8")
    exit_code = check_dashes.main(["--root", str(tmp_path), "dirty.md"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "dirty.md:1:3" in captured.out
    assert "1 violation found" in captured.err


def test_main_walks_git_ls_files_when_given_no_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-b", "main", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.md").write_text(f"bad {EM_DASH} line\n", encoding="utf-8")
    (tmp_path / "untracked.md").write_text(f"also bad {EM_DASH}\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.md"], cwd=tmp_path, check=True)

    assert check_dashes.tracked_files(tmp_path) == [Path("tracked.md")]

    exit_code = check_dashes.main(["--root", str(tmp_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "tracked.md:1:5" in captured.out
    assert "untracked.md" not in captured.out
