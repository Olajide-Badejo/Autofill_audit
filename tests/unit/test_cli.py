"""CLI smoke tests: the entry point, the command surface, and the exit codes.

These cover the wiring. What the ``audit`` command does with its arguments lives
in ``test_cli_audit.py``, and what it does against a real page lives in
``tests/e2e/test_cli_e2e.py``.
"""

from __future__ import annotations

import sys

import pytest
from click.testing import CliRunner

from autofill_audit import __version__
from autofill_audit.cli import cli, main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_version_command_prints_the_version_and_the_engine_identities(
    runner: CliRunner,
) -> None:
    """``describe()`` output, verbatim, so a bug report can name what ran."""
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert lines[0] == f"autofill-audit {__version__}"
    assert any(line.strip().startswith("engine: rules") for line in lines)


def test_version_flag_prints_the_version(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_the_commands(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "audit" in result.output
    assert "version" in result.output
    assert "corpus" in result.output


def test_audit_help_names_its_argument(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["audit", "--help"])
    assert result.exit_code == 0
    assert "URL_OR_PATH" in result.output
    assert "--fail-on" in result.output
    assert "--json-schema" in result.output


def test_audit_help_does_not_advertise_a_flag_that_does_not_exist(
    runner: CliRunner,
) -> None:
    """The boundaries of spec section 0.4 are answered, never offered."""
    result = runner.invoke(cli, ["audit", "--help"])
    for flag in ("--crawl", "--depth", "--fill", "--write"):
        assert flag not in result.output


def test_unknown_command_is_a_usage_error(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["scrape", "https://example.invalid"])
    assert result.exit_code != 0


def test_main_is_the_console_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["autofill-audit", "version"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith(f"autofill-audit {__version__}")


def test_main_answers_a_boundary_flag_before_click_ever_sees_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not "no such option", which reads like an oversight."""
    monkeypatch.setattr(sys, "argv", ["autofill-audit", "audit", "page.html", "--crawl"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2
    assert "no crawl mode" in capsys.readouterr().err


def test_main_maps_a_usage_error_to_exit_code_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["autofill-audit", "scrape"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2
    assert capsys.readouterr().err


def test_main_maps_an_unexpected_failure_to_exit_code_four(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Code 4 is a bug in this program, and it says so and prints a traceback.

    The alternative is exiting 0 or 1 on an internal error, which would tell a
    pipeline that the page was audited when it was not.
    """
    import autofill_audit.cli as module

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("a bug, not a page problem")

    monkeypatch.setattr(module.cli, "main", explode)
    monkeypatch.setattr(sys, "argv", ["autofill-audit", "version"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 4
    captured = capsys.readouterr()
    assert "Traceback" in captured.err
    assert "bug in autofill-audit" in captured.err
    assert "issues" in captured.err
