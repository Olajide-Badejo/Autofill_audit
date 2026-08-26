"""Law 4's mechanism: a prediction is committed before what it predicts.

Every test here builds a real git repository in a temporary directory and makes
real commits, because the property under test is a property of a commit graph
and a mock of git would only be testing the mock.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_prediction_ancestry import (
    parse_front_matter,
    run,
)

AUTHOR = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid"]


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", *AUTHOR, *arguments], cwd=root, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """An initialised repository with the predictions directory in place."""
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "experiments" / "predictions").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    return tmp_path


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


PREDICTION = """---
predicts:
  - src/thresholds.json
---

# A prediction

The number will be larger than the other number.
"""


def test_front_matter_reads_the_paths_and_the_amendment() -> None:
    matter = parse_front_matter(
        "---\npredicts:\n  - a/b.json\n  - c/\namended: 2026-08-26, reason\n---\nbody\n"
    )
    assert matter.present is True
    assert matter.predicts == ("a/b.json", "c/")
    assert matter.amended == "2026-08-26, reason"


def test_a_file_with_no_front_matter_is_reported_as_having_none() -> None:
    assert parse_front_matter("# just a heading\n").present is False


def test_an_unclosed_block_is_not_front_matter() -> None:
    assert parse_front_matter("---\npredicts:\n  - a\n").present is False


def test_a_prediction_before_its_artefact_passes(repo: Path) -> None:
    (repo / "experiments" / "predictions" / "p.md").write_text(PREDICTION, encoding="utf-8")
    _commit(repo, "pre register the prediction")
    (repo / "src" / "thresholds.json").write_text("{}\n", encoding="utf-8")
    _commit(repo, "derive the thresholds")

    report = run(repo, Path("experiments") / "predictions")
    assert report.ok
    assert len(report.checked) == 1


def test_a_prediction_after_its_artefact_fails(repo: Path) -> None:
    """The whole point. A prediction written once the number is known is not one."""
    (repo / "src" / "thresholds.json").write_text("{}\n", encoding="utf-8")
    _commit(repo, "derive the thresholds")
    (repo / "experiments" / "predictions" / "p.md").write_text(PREDICTION, encoding="utf-8")
    _commit(repo, "pre register the prediction, allegedly")

    report = run(repo, Path("experiments") / "predictions")
    assert not report.ok
    assert "not an ancestor" in report.violations[0]


def test_an_edited_prediction_must_declare_the_edit(repo: Path) -> None:
    (repo / "experiments" / "predictions" / "p.md").write_text(PREDICTION, encoding="utf-8")
    _commit(repo, "pre register the prediction")
    (repo / "src" / "thresholds.json").write_text("{}\n", encoding="utf-8")
    _commit(repo, "derive the thresholds")
    (repo / "experiments" / "predictions" / "p.md").write_text(
        PREDICTION + "\nAnd it was, obviously.\n", encoding="utf-8"
    )
    _commit(repo, "tidy the prediction")

    report = run(repo, Path("experiments") / "predictions")
    assert not report.ok
    assert "amended" in report.violations[0]


def test_a_declared_amendment_is_accepted(repo: Path) -> None:
    (repo / "experiments" / "predictions" / "p.md").write_text(PREDICTION, encoding="utf-8")
    _commit(repo, "pre register the prediction")
    (repo / "src" / "thresholds.json").write_text("{}\n", encoding="utf-8")
    _commit(repo, "derive the thresholds")
    (repo / "experiments" / "predictions" / "p.md").write_text(
        PREDICTION.replace("---\n\n# A", "amended: 2026-08-26, a typo\n---\n\n# A"),
        encoding="utf-8",
    )
    _commit(repo, "fix a typo in the prediction")

    report = run(repo, Path("experiments") / "predictions")
    assert report.ok


def test_a_prediction_with_no_front_matter_is_a_violation(repo: Path) -> None:
    (repo / "experiments" / "predictions" / "p.md").write_text("# nothing\n", encoding="utf-8")
    _commit(repo, "add a prediction with no mapping")

    report = run(repo, Path("experiments") / "predictions")
    assert not report.ok
    assert "no front matter" in report.violations[0]


def test_it_passes_trivially_when_nothing_is_committed_yet(repo: Path) -> None:
    """The property CI needs: green on a change that touched no results."""
    (repo / "experiments" / "predictions" / "p.md").write_text(PREDICTION, encoding="utf-8")
    _commit(repo, "pre register the prediction")

    report = run(repo, Path("experiments") / "predictions")
    assert report.ok
    assert report.checked == []
    assert any("nothing committed under it yet" in line for line in report.skipped)


def test_a_directory_covers_everything_under_it(repo: Path) -> None:
    (repo / "experiments" / "predictions" / "p.md").write_text(
        "---\npredicts:\n  - experiments/results/test/\n---\n\n# A prediction\n",
        encoding="utf-8",
    )
    _commit(repo, "pre register")
    results = repo / "experiments" / "results" / "test" / "run-one"
    results.mkdir(parents=True)
    (results / "run.jsonl").write_text("{}\n", encoding="utf-8")
    (results / "manifest.json").write_text("{}\n", encoding="utf-8")
    _commit(repo, "the first run")

    report = run(repo, Path("experiments") / "predictions")
    assert report.ok
    assert len(report.checked) == 2


def test_an_absent_predictions_directory_is_not_a_failure(tmp_path: Path) -> None:
    assert run(tmp_path, Path("experiments") / "predictions").ok
