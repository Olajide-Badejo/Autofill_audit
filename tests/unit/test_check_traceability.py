"""Behaviour of the traceability check.

The important test in this file is that the check is capable of failing. A law-3
gate that has only ever been observed green is indistinguishable from a gate
that always returns green, and this is the unit-level half of that argument; the
CI-level half is the red scratch run recorded in ``docs/ci-proof.md``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import check_traceability


def scan(line: str) -> list[check_traceability.Violation]:
    return check_traceability.scan_text(line + "\n", display_path="probe.md")


@pytest.mark.parametrize(
    "line",
    [
        "The tool reports 87% accuracy on the test split.",
        "It is 12 percent faster than the baseline.",
        "Macro F1 reached 0.91 on the held out locale.",
        "Median latency was 3 milliseconds per field.",
        "The run produced 240 findings across the corpus.",
    ],
)
def test_measurement_shaped_numbers_are_flagged(line: str) -> None:
    violations = scan(line)
    assert len(violations) == 1
    assert violations[0].line == 1
    assert violations[0].path == "probe.md"
    assert violations[0].render().startswith("probe.md:1: ")


@pytest.mark.parametrize(
    "line",
    [
        "Retrieved on 2026-08-25 and still resolving.",
        "Benjamini and Hochberg (1995) describe the procedure.",
        "The resolved interpreter is CPython 3.14.4 on this machine.",
        "See the reference list at [12] for the full citation.",
        "1. The first item of an ordered list.",
        "## A heading",
        "| column | column |",
        "| --- | --- |",
        "A link to https://example.invalid/path/2024/99 is not a measurement.",
        "The gate value lives in `--cov-fail-under=90` in pyproject.toml.",
        "Nothing numeric here at all.",
    ],
)
def test_non_measurements_are_not_flagged(line: str) -> None:
    assert scan(line) == []


def test_fenced_code_blocks_are_skipped() -> None:
    text = "```\naccuracy was 99%\n```\nclean prose\n"
    assert check_traceability.scan_text(text, display_path="probe.md") == []


def test_a_result_reference_clears_the_line() -> None:
    assert scan("Macro F1 is 0.91 (results: experiments/results/run-0001/metrics.json)") == []


def test_a_results_key_clears_the_line() -> None:
    assert scan("Accuracy 88% results: run-0001") == []


def test_an_annotation_clears_the_line() -> None:
    line = "The coverage gate is 90 findings wide. <!-- traceability: configured threshold -->"
    assert scan(line) == []


def test_an_annotation_clears_the_following_line() -> None:
    text = (
        "<!-- traceability: configured threshold, not a measurement -->\n"
        "The gate requires 90 percent.\n"
    )
    assert check_traceability.scan_text(text, display_path="probe.md") == []


def test_an_annotation_does_not_clear_two_lines_later() -> None:
    text = (
        "<!-- traceability: configured threshold -->\n"
        "The gate requires 90 percent.\n"
        "Accuracy was 91%.\n"
    )
    violations = check_traceability.scan_text(text, display_path="probe.md")
    assert len(violations) == 1
    assert violations[0].line == 3


def test_default_targets_covers_the_readme_and_docs(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("clean\n", encoding="utf-8")
    docs = tmp_path / "docs" / "adr"
    docs.mkdir(parents=True)
    (docs / "0001-x.md").write_text("clean\n", encoding="utf-8")
    targets = check_traceability.default_targets(tmp_path)
    assert Path("README.md") in targets
    assert Path("docs/adr/0001-x.md") in targets


def test_main_is_clean_on_prose_without_measurements(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "README.md").write_text("A tool that audits forms.\n", encoding="utf-8")
    assert check_traceability.main(["--root", str(tmp_path)]) == 0
    assert "clean" in capsys.readouterr().out


def test_main_fails_on_a_bare_percentage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "README.md").write_text("It is 99% accurate.\n", encoding="utf-8")
    assert check_traceability.main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "README.md:1" in captured.out
    assert "1 untraceable number found" in captured.err


def test_main_accepts_explicit_paths(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("It is 99% accurate.\n", encoding="utf-8")
    assert check_traceability.main(["--root", str(tmp_path), "notes.md"]) == 1


# ---------------------------------------------------------------------------
# Resolving the chain (P5), which is what turns a citation into a check.
# ---------------------------------------------------------------------------


def _repo_with_result(tmp_path: Path, *, dirty: bool = False) -> tuple[Path, str]:
    """A git repository holding one result directory with a manifest."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    results = tmp_path / "experiments" / "results" / "test" / "run-one"
    results.mkdir(parents=True)
    (results / "run.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "seed.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-q",
            "-m",
            "a run",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (results / "manifest.json").write_text(
        json.dumps({"git": {"commit": commit, "dirty": dirty}}), encoding="utf-8"
    )
    return tmp_path, commit


def test_references_are_found_wherever_they_appear() -> None:
    text = "macro-F1 was 0.77 (experiments/results/test/run-one/metrics.json)\n"
    assert check_traceability.references_in(text) == [
        "experiments/results/test/run-one/metrics.json"
    ]


def test_a_citation_that_resolves_passes(tmp_path: Path) -> None:
    root, _ = _repo_with_result(tmp_path)
    (root / "README.md").write_text(
        "macro-F1 was 0.77 (experiments/results/test/run-one/run.jsonl)\n", encoding="utf-8"
    )
    assert check_traceability.main(["--root", str(root), "--resolve", "README.md"]) == 0


def test_a_citation_of_a_file_that_does_not_exist_fails(tmp_path: Path) -> None:
    """The failure the shape-only check could not catch."""
    root, _ = _repo_with_result(tmp_path)
    (root / "README.md").write_text(
        "macro-F1 was 0.77 (experiments/results/test/imaginary/run.jsonl)\n", encoding="utf-8"
    )
    assert check_traceability.main(["--root", str(root), "--resolve", "README.md"]) == 1


def test_a_citation_of_a_dirty_run_fails(tmp_path: Path) -> None:
    """Spec section 18: a result from a dirty tree is not citable."""
    root, _ = _repo_with_result(tmp_path, dirty=True)
    (root / "README.md").write_text(
        "macro-F1 was 0.77 (experiments/results/test/run-one/run.jsonl)\n", encoding="utf-8"
    )
    assert check_traceability.main(["--root", str(root), "--resolve", "README.md"]) == 1


def test_a_manifest_naming_a_commit_that_does_not_resolve_fails(tmp_path: Path) -> None:
    root, _ = _repo_with_result(tmp_path)
    manifest = root / "experiments" / "results" / "test" / "run-one" / "manifest.json"
    manifest.write_text(json.dumps({"git": {"commit": "0" * 40, "dirty": False}}), encoding="utf-8")
    (root / "README.md").write_text(
        "macro-F1 was 0.77 (experiments/results/test/run-one/run.jsonl)\n", encoding="utf-8"
    )
    assert check_traceability.main(["--root", str(root), "--resolve", "README.md"]) == 1


def test_a_result_with_no_manifest_beside_it_fails(tmp_path: Path) -> None:
    root, _ = _repo_with_result(tmp_path)
    (root / "experiments" / "results" / "test" / "run-one" / "manifest.json").unlink()
    (root / "README.md").write_text(
        "macro-F1 was 0.77 (experiments/results/test/run-one/run.jsonl)\n", encoding="utf-8"
    )
    assert check_traceability.main(["--root", str(root), "--resolve", "README.md"]) == 1


def test_a_citation_of_a_directory_of_runs_resolves_every_run_under_it(tmp_path: Path) -> None:
    """A link to a directory points a reader at all of it, so all of it must resolve."""
    root, commit = _repo_with_result(tmp_path)
    second = root / "experiments" / "results" / "test" / "run-two"
    second.mkdir()
    (second / "manifest.json").write_text(
        json.dumps({"git": {"commit": commit, "dirty": False}}), encoding="utf-8"
    )
    (root / "README.md").write_text(
        "the runs live under experiments/results/test\n", encoding="utf-8"
    )
    assert check_traceability.main(["--root", str(root), "--resolve", "README.md"]) == 0

    (second / "manifest.json").write_text(
        json.dumps({"git": {"commit": commit, "dirty": True}}), encoding="utf-8"
    )
    assert check_traceability.main(["--root", str(root), "--resolve", "README.md"]) == 1
