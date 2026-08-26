"""The audit command's argument handling, configuration, and exit codes.

Everything here runs without a browser. The paths that need one are in
``tests/e2e/test_cli_e2e.py``, marked ``e2e``, and they assert the same exit-code
contract from the other side.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from autofill_audit import cli as cli_module
from autofill_audit.audit.findings import FindingCode
from autofill_audit.audit.thresholds import ThresholdsError
from autofill_audit.cli import (
    BOUNDARY_FLAGS,
    ConfigError,
    _configured_formats,
    _thresholds,
    check_boundaries,
    cli,
    find_config,
    load_config,
)
from autofill_audit.loader import (
    NavigationFailedError,
    NavigationTimeoutError,
    NotHtmlError,
    TargetNotFoundError,
    UnsupportedSchemeError,
)


@pytest.fixture
def runner() -> CliRunner:
    """A click runner that keeps standard error separate from standard output."""
    return CliRunner()


# ---------------------------------------------------------------------------
# The boundaries of spec section 0.4.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flag", sorted(BOUNDARY_FLAGS))
def test_each_absent_flag_names_its_boundary(flag: str) -> None:
    """Not "no such option". The reader has just asked a reasonable question."""
    message = check_boundaries(["audit", "page.html", flag])
    assert message is not None
    assert flag in message
    assert "on purpose" in message


@pytest.mark.parametrize("flag", sorted(BOUNDARY_FLAGS))
def test_an_absent_flag_is_caught_with_a_value_attached(flag: str) -> None:
    assert check_boundaries([f"{flag}=3"]) is not None


def test_an_ordinary_argument_containing_a_boundary_word_is_left_alone() -> None:
    """``--fix`` is a boundary; a file called ``fix.html`` is not."""
    assert check_boundaries(["audit", "fix.html", "--format", "json"]) is None
    assert check_boundaries(["audit", "--out", "crawl.json"]) is None


def test_the_boundary_list_is_exactly_the_five_of_the_specification() -> None:
    assert set(BOUNDARY_FLAGS) == {"--crawl", "--depth", "--fill", "--fix", "--write"}


# ---------------------------------------------------------------------------
# Usage.
# ---------------------------------------------------------------------------


def test_the_json_schema_flag_prints_a_schema_and_exits(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["audit", "--json-schema"])
    assert result.exit_code == 0
    schema = json.loads(result.output)
    assert schema["properties"]["schema_version"]["const"] == 1
    codes = schema["$defs"]["findingCodes"]
    assert set(codes) == {code.value for code in FindingCode}


def test_a_missing_target_is_a_usage_error(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["audit"])
    assert result.exit_code == 2
    assert "URL or a path" in result.output


def test_an_engine_that_does_not_exist_yet_names_its_phase(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["audit", "page.html", "--engine", "llm"])
    assert result.exit_code == 2
    assert "phase P6" in result.output


def test_the_ngram_engine_with_no_model_is_a_usage_error_and_not_a_fallback(
    runner: CliRunner,
) -> None:
    """Exit code 2 and a sentence, never a quiet substitution of the baseline."""
    result = runner.invoke(cli, ["audit", "page.html", "--engine", "ngram"])
    assert result.exit_code == 2
    assert "no trained model was found" in result.output
    assert "rule baseline" not in result.output


def test_an_unknown_engine_is_refused_by_the_choice(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["audit", "page.html", "--engine", "tarot"])
    assert result.exit_code != 0


def test_html_without_an_output_path_is_a_usage_error(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["audit", "page.html", "--format", "html"])
    assert result.exit_code == 2
    assert "--out is required" in result.output


def test_several_formats_without_an_output_path_is_a_usage_error(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["audit", "page.html", "--format", "json", "--format", "terminal"])
    assert result.exit_code == 2
    assert "--out is required" in result.output


def test_the_version_command_names_the_engine_and_the_thresholds(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert "rule_table_version" in result.output
    assert "threshold basis: rule-tier-band-mapping" in result.output
    assert "threshold measured: false" in result.output


# ---------------------------------------------------------------------------
# The config file (spec section 14).
# ---------------------------------------------------------------------------


def test_a_missing_config_file_is_not_an_error() -> None:
    assert load_config(None).suppressions == ()


def test_the_config_is_discovered_upward_from_the_working_directory(tmp_path: Path) -> None:
    (tmp_path / "autofill-audit.toml").write_text("format = 'json'\n", encoding="utf-8")
    nested = tmp_path / "packages" / "web"
    nested.mkdir(parents=True)
    found = find_config(nested)
    assert found == tmp_path / "autofill-audit.toml"


def test_a_config_that_is_nowhere_above_the_directory_is_not_found(tmp_path: Path) -> None:
    assert find_config(tmp_path) is None


def test_ignore_becomes_a_whole_code_suppression(tmp_path: Path) -> None:
    path = tmp_path / "autofill-audit.toml"
    path.write_text("ignore = ['GENERIC_IDENTIFIER']\n", encoding="utf-8")
    config = load_config(path)
    assert len(config.suppressions) == 1
    assert config.suppressions[0].code is FindingCode.GENERIC_IDENTIFIER
    assert config.suppressions[0].selector is None


def test_a_per_selector_suppression_needs_a_reason(tmp_path: Path) -> None:
    """A suppression with no stated reason is one nobody can review."""
    path = tmp_path / "autofill-audit.toml"
    path.write_text("[[suppress]]\ncode = 'UNLABELED_FIELD'\nselector = '#x'\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="needs a reason"):
        load_config(path)


def test_a_per_selector_suppression_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "autofill-audit.toml"
    path.write_text(
        "[[suppress]]\ncode = 'UNLABELED_FIELD'\nselector = '#x'\nreason = 'vendor widget'\n",
        encoding="utf-8",
    )
    rule = load_config(path).suppressions[0]
    assert rule.selector == "#x"
    assert rule.reason == "vendor widget"


def test_an_unknown_finding_code_in_the_config_lists_the_known_ones(tmp_path: Path) -> None:
    path = tmp_path / "autofill-audit.toml"
    path.write_text("ignore = ['NOT_A_CODE']\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Known codes"):
        load_config(path)


def test_unparseable_toml_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "autofill-audit.toml"
    path.write_text("this is not = = toml\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_a_config_format_may_be_a_string_or_a_list(tmp_path: Path) -> None:
    single = tmp_path / "one.toml"
    single.write_text("format = 'json'\n", encoding="utf-8")
    several = tmp_path / "two.toml"
    several.write_text("format = ['json', 'html']\n", encoding="utf-8")
    assert _configured_formats(load_config(single)) == ("json",)
    assert _configured_formats(load_config(several)) == ("json", "html")
    assert _configured_formats(load_config(None)) == ("terminal",)


def test_an_unparseable_config_is_exit_code_two(runner: CliRunner, tmp_path: Path) -> None:
    path = tmp_path / "autofill-audit.toml"
    path.write_text("ignore = ['NOPE']\n", encoding="utf-8")
    result = runner.invoke(cli, ["audit", "page.html", "--config", str(path)])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Threshold overrides.
# ---------------------------------------------------------------------------


def test_min_confidence_lowers_the_low_threshold_and_says_so() -> None:
    thresholds = _thresholds(0.2)
    assert thresholds.tau_low == 0.2
    assert "overridden on the command line" in thresholds.basis


def test_min_confidence_above_the_high_threshold_is_refused() -> None:
    """It would empty the low-confidence band rather than widen it."""
    with pytest.raises(ThresholdsError, match="above the high threshold"):
        _thresholds(0.99)


def test_min_confidence_outside_the_unit_interval_is_refused() -> None:
    with pytest.raises(ThresholdsError):
        _thresholds(-0.5)


def test_a_min_confidence_override_is_a_usage_error_at_the_command_line(
    runner: CliRunner,
) -> None:
    result = runner.invoke(cli, ["audit", "page.html", "--min-confidence", "0.99"])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# The loader failures of spec section 15, mapped to the codes of section 11.5.
#
# A page that returns 404 and a page that never fires load both need a real
# server to reproduce, and CI is forbidden from calling one (spec section 16).
# The loader already turns both into typed errors and P2 tests that it does; what
# is left to check is the mapping, and the mapping is checked by raising the
# typed error at the seam.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected", "fragment"),
    [
        (NavigationFailedError("https://x.test/p: answered with HTTP 404"), 3, "HTTP 404"),
        (NavigationTimeoutError("https://x.test/p: did not reach the load state"), 3, "load state"),
        (
            NavigationFailedError("https://x.test/p: navigation failed (dns)"),
            3,
            "navigation failed",
        ),
        (NotHtmlError("p.txt: does not look like HTML"), 2, "does not look like HTML"),
        (TargetNotFoundError("p.html: no such file"), 2, "no such file"),
        (UnsupportedSchemeError("ftp://x: scheme ftp is not one of"), 2, "not one of"),
    ],
)
def test_a_loader_failure_maps_to_its_documented_exit_code(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected: int,
    fragment: str,
) -> None:
    """Code 3 is deliberately distinct from code 1.

    A pipeline has to be able to tell "your form has problems" from "the auditor
    could not reach the page", and collapsing them produces exactly the flaky red
    build that gets the check deleted.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(cli_module, "load_page", refuse)
    result = runner.invoke(cli, ["audit", "https://example.test/page.html"])
    assert result.exit_code == expected
    assert fragment in result.output
    assert "Traceback" not in result.output


def test_a_page_that_could_not_be_reached_is_not_reported_as_a_clean_page(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure mode the two codes exist to keep apart."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise NavigationFailedError("https://x.test/p: answered with HTTP 404")

    monkeypatch.setattr(cli_module, "load_page", refuse)
    result = runner.invoke(cli, ["audit", "https://example.test/p", "--fail-on", "never"])
    assert result.exit_code == 3
