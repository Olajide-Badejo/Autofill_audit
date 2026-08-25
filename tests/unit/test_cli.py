"""CLI smoke tests.

These are deliberately thin. The command surface is almost entirely unbuilt at
P0, and the only claims worth asserting are that the entry point exists, that
``version`` prints the version, and that ``audit`` refuses loudly rather than
emitting an empty report that reads like a clean bill of health.
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


def test_version_command_prints_the_version(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"autofill-audit {__version__}"


def test_version_flag_prints_the_version(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_the_commands(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "audit" in result.output
    assert "version" in result.output


def test_audit_refuses_with_the_reserved_exit_code(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["audit", "some/page.html"])
    assert result.exit_code == 2
    assert "some/page.html" in result.output
    assert "P3" in result.output


def test_audit_help_works_before_audit_does(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["audit", "--help"])
    assert result.exit_code == 0
    assert "URL_OR_PATH" in result.output


def test_unknown_command_is_a_usage_error(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["crawl", "https://example.invalid"])
    assert result.exit_code != 0


def test_main_is_the_console_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["autofill-audit", "version"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"autofill-audit {__version__}"
