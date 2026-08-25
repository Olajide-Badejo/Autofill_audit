"""The CLI against real fixtures through a real browser, offline (spec 15 layer 5).

These drive the whole path: the process entry point, click, the loader, Chromium,
the extractor, the rule engine, the decision procedure, and all three renderers.
They must run in CI, because a tool whose browser path is only tested by hand is
a tool that breaks on the first Playwright upgrade.

**They run the tool in a subprocess**, and that is not ceremony. Playwright's
synchronous API allows one live session per thread, the audit suite holds one
open for the whole run, and the CLI opens one of its own on every invocation. In
one process those two collide and the failure reads like an async/sync mistake
rather than like the resource conflict it is. A subprocess also happens to be the
more faithful end-to-end test: it exercises the real exit codes as a shell sees
them rather than as a test runner reports them.

Every target is a local file opened through ``file://``. Nothing here touches the
network, and the frame fixture reaches an opaque origin through a ``data:`` URL
rather than through a second server.

The malformed-input list of spec section 15 is covered between this module,
``tests/unit/test_cli_audit.py`` (which raises the loader's typed errors at the
seam, because a 404 and a page that never fires load both need a server CI is
forbidden from calling), and ``test_loader_targets.py``. Each case produces a
diagnostic and a documented exit code, never a traceback.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

HOSTILE = "checkout_hostile.html"
MODIFIERS = "checkout_modifiers.html"

_ENTRY = [sys.executable, "-m", "autofill_audit.cli"]


def _run(*arguments: str, cwd: Path | None = None) -> tuple[int, str]:
    """Run the installed command surface in a subprocess.

    Standard output and standard error are joined, because a reader looking at a
    terminal sees them joined and every assertion here is about what that reader
    sees.
    """
    completed = subprocess.run(
        [*_ENTRY, *arguments],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    return completed.returncode, completed.stdout + completed.stderr


@pytest.fixture(scope="module")
def runner() -> None:
    """Retained so the signatures below read the same; the runner is a process."""
    return None


def _audit(runner: None, target: Path, *flags: str) -> tuple[int, str]:
    """Run the audit command against a real file."""
    del runner
    return _run("audit", str(target), *flags)


# ---------------------------------------------------------------------------
# The gate command.
# ---------------------------------------------------------------------------


def test_the_hostile_fixture_exits_one_at_the_default_threshold(
    runner: None, fixtures_dir: Path
) -> None:
    """The phase gate's own command, asserted as a test."""
    code, output = _audit(runner, fixtures_dir / HOSTILE, "--fail-on", "critical")
    assert code == 1
    assert "MISSING_AUTOCOMPLETE" in output
    assert "Traceback" not in output


def test_the_hostile_fixture_exits_zero_when_nothing_may_fail(
    runner: None, fixtures_dir: Path
) -> None:
    """``--fail-on never`` is a reporting-only pipeline step."""
    code, _ = _audit(runner, fixtures_dir / HOSTILE, "--fail-on", "never")
    assert code == 0


def test_the_failure_threshold_moves_the_exit_code(runner: None, fixtures_dir: Path) -> None:
    """The modifier fixture has nothing at any severity, so it passes them all."""
    for level in ("critical", "warning", "info"):
        code, _ = _audit(runner, fixtures_dir / MODIFIERS, "--fail-on", level)
        assert code == 0, level


@pytest.mark.label("postal-code")
def test_the_modifier_fixture_raises_no_wrong_autocomplete(
    runner: None, fixtures_dir: Path, tmp_path: Path
) -> None:
    """Spec section 7.1's named test, at the level a user experiences it.

    A page whose every declaration carries a section modifier is a correctly
    built page. If this ever fails, the tool has become loudest on the pages that
    are most nearly right, which is the fastest way to get an auditing tool
    uninstalled.
    """
    out = tmp_path / "report.json"
    code, _ = _audit(runner, fixtures_dir / MODIFIERS, "--format", "json", "--out", str(out))
    assert code == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["findings"] == []
    assert document["summary"]["counts"]["critical"] == 0
    assert document["summary"]["counts"]["warning"] == 0


# ---------------------------------------------------------------------------
# Output.
# ---------------------------------------------------------------------------


def test_the_json_report_validates_against_its_own_schema_keys(
    runner: None, fixtures_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "report.json"
    _audit(runner, fixtures_dir / HOSTILE, "--format", "json", "--out", str(out))
    document = json.loads(out.read_text(encoding="utf-8"))
    for key in ("schema_version", "tool", "target", "engine", "summary", "findings"):
        assert key in document
    assert all("bbox" not in item for item in document["descriptors"])
    assert document["timing_ms"]["load_ms"] >= 0


def test_several_formats_write_beside_one_another(
    runner: None, fixtures_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "report"
    code, _ = _audit(
        runner,
        fixtures_dir / HOSTILE,
        "--format",
        "json",
        "--format",
        "html",
        "--out",
        str(out),
    )
    assert code == 1
    assert (tmp_path / "report.json").is_file()
    assert (tmp_path / "report.html").is_file()


def test_the_html_report_needs_nothing_from_the_network(
    runner: None, fixtures_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "report.html"
    _audit(runner, fixtures_dir / HOSTILE, "--format", "html", "--out", str(out))
    document = out.read_text(encoding="utf-8")
    assert "<script" not in document.lower()
    assert "http" not in document


def test_the_fallback_notice_is_printed_once_and_is_not_an_error(
    runner: None, fixtures_dir: Path
) -> None:
    """Spec section 10.1: one clear line, and the run continues."""
    _, output = _audit(runner, fixtures_dir / MODIFIERS)
    assert output.count("no trained model is installed") == 1
    assert "not an error" in output


def test_a_non_default_threshold_is_announced(runner: None, fixtures_dir: Path) -> None:
    _, output = _audit(runner, fixtures_dir / MODIFIERS, "--min-confidence", "0.1")
    assert "non-default low threshold" in output


def test_a_configured_suppression_appears_in_the_json_under_suppressed(
    runner: None, fixtures_dir: Path, tmp_path: Path
) -> None:
    """A finding that vanished without trace is how a config file lies to CI."""
    config = tmp_path / "autofill-audit.toml"
    config.write_text("ignore = ['GENERIC_IDENTIFIER']\n", encoding="utf-8")
    out = tmp_path / "report.json"
    _audit(
        runner,
        fixtures_dir / HOSTILE,
        "--config",
        str(config),
        "--format",
        "json",
        "--out",
        str(out),
    )
    document = json.loads(out.read_text(encoding="utf-8"))
    codes = {item["code"] for item in document["findings"]}
    hidden = document["suppressed"]
    assert "GENERIC_IDENTIFIER" not in codes
    assert [item["code"] for item in hidden] == ["GENERIC_IDENTIFIER"]
    assert hidden[0]["suppressed_by"] == "ignore = GENERIC_IDENTIFIER"


# ---------------------------------------------------------------------------
# Malformed input (spec section 15).
# ---------------------------------------------------------------------------


def test_a_file_that_is_not_html_is_a_usage_error(runner: None, fixtures_dir: Path) -> None:
    code, output = _audit(runner, fixtures_dir / "extract" / "pages" / "not_html.txt")
    assert code == 2
    assert "does not look like HTML" in output
    assert "Traceback" not in output


def test_a_target_that_does_not_exist_is_a_usage_error(runner: None, tmp_path: Path) -> None:
    code, output = _audit(runner, tmp_path / "nothing-here.html")
    assert code == 2
    assert "no such file" in output
    assert "Traceback" not in output


def test_an_unsupported_scheme_is_a_usage_error() -> None:
    code, output = _run("audit", "ftp://example.test/page.html")
    assert code == 2
    assert "is not one of" in output
    assert "Traceback" not in output


def test_a_boundary_flag_is_answered_by_the_real_entry_point() -> None:
    """The interception happens before click parses, so it holds for the process."""
    code, output = _run("audit", "page.html", "--fill")
    assert code == 2
    assert "auditor, not a form filler" in output


def test_the_version_command_runs_from_a_clean_process() -> None:
    code, output = _run("version")
    assert code == 0
    assert "rule_table_version" in output


def test_a_malformed_page_still_produces_a_report(runner: None, fixtures_dir: Path) -> None:
    """Unclosed tags, duplicate ids: the browser repairs them and the audit runs."""
    code, output = _audit(
        runner, fixtures_dir / "extract" / "pages" / "malformed_markup.html", "--fail-on", "never"
    )
    assert code == 0
    assert "Traceback" not in output


def test_a_page_with_five_thousand_options_does_not_hang_or_crash(
    runner: None, fixtures_dir: Path
) -> None:
    """The option list is truncated by the extractor and the audit is unbothered."""
    code, output = _audit(
        runner, fixtures_dir / "extract" / "pages" / "many_options.html", "--fail-on", "never"
    )
    assert code == 0
    assert "Traceback" not in output


def test_a_ten_thousand_character_label_does_not_break_a_renderer(
    runner: None, fixtures_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "long.html"
    code, _ = _audit(
        runner,
        fixtures_dir / "extract" / "pages" / "long_label.html",
        "--fail-on",
        "never",
        "--format",
        "html",
        "--out",
        str(out),
    )
    assert code == 0
    assert out.is_file()


def test_a_page_whose_only_form_like_thing_is_a_canvas_says_so(
    runner: None, fixtures_dir: Path
) -> None:
    code, output = _audit(
        runner, fixtures_dir / "extract" / "pages" / "canvas_only.html", "--fail-on", "critical"
    )
    assert code == 0
    assert "UNDETECTABLE_FIELD" in output
    assert "canvas" in output
