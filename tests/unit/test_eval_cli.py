"""The ``eval`` command's contract (spec section 14).

The friction on the test split is the point of this file. Spec section 14 makes
looking at the test split a deliberate act rather than an accident, and a
refusal that is not tested is a refusal that will be removed by the first person
who finds it inconvenient.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from autofill_audit.cli import cli, find_script

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import eval as evaluate


def test_the_test_split_is_refused_without_the_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = evaluate.main(["--split", "test", "--engine", "rules", "--corpus", str(tmp_path)])
    assert status == 2
    assert "i-am-measuring" in capsys.readouterr().err


def test_the_refusal_explains_itself_rather_than_naming_the_flag() -> None:
    """A refusal a reader cannot argue with is a refusal they will route around."""
    assert "spent" in evaluate._TEST_REFUSAL
    assert "deliberate" in evaluate._TEST_REFUSAL


def test_the_dev_split_needs_no_flag(tmp_path: Path) -> None:
    """The friction is on the test split and nowhere else.

    A missing corpus is the failure here, which is the point: the command got
    past the refusal and reached its real work, and it did so without the flag.
    """
    with pytest.raises((FileNotFoundError, OSError)):
        evaluate.main(["--split", "dev", "--engine", "rules", "--corpus", str(tmp_path)])


def test_the_cli_offers_the_flag_and_both_splits() -> None:
    result = CliRunner().invoke(cli, ["eval", "--help"])
    assert result.exit_code == 0
    assert "--i-am-measuring" in result.output
    assert "dev|test" in result.output.replace(" ", "")


def test_the_cli_refuses_an_engine_that_would_not_say_what_ran() -> None:
    """``auto`` is right for a person auditing a page and wrong for a measurement."""
    result = CliRunner().invoke(
        cli, ["eval", "--split", "dev", "--engine", "auto", "--corpus", "corpus"]
    )
    assert result.exit_code == 2
    assert "auto" in result.output


def test_the_cli_finds_the_script_it_wraps() -> None:
    assert find_script(Path.cwd(), "eval.py") is not None
    assert find_script(Path.cwd(), "not-a-script.py") is None


def test_runs_are_filed_under_the_split_they_measured() -> None:
    """Not tidiness: the ancestry check depends on it.

    The pre-registered policy predicts about `experiments/results/test/`, and
    development runs precede that policy. Filing both in one directory would make
    law 4's check fail on a run that was correctly taken before the prediction.
    """
    source = Path(evaluate.__file__).read_text(encoding="utf-8")
    assert "args.out / args.split / run_id" in source


def test_the_predicted_confusion_pairs_are_carried_in_both_directions() -> None:
    """Spec section 13.2 names four pairs. Confusion is not symmetric."""
    pairs = set(evaluate.PREDICTED_CONFUSIONS)
    for first, second in (
        ("username", "email"),
        ("address-level1", "address-level2"),
        ("tel", "tel-national"),
        ("cc-exp", "cc-exp-month"),
    ):
        assert (first, second) in pairs
        assert (second, first) in pairs
