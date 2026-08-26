"""The ``corpus`` command group."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from autofill_audit.cli import cli
from autofill_audit.corpus.families import TEMPLATES_PER_FAMILY


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


SMALL = ["--families", "login", "--locales", "en-US", "--base-year", "2026"]


def test_generate_writes_a_corpus(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "corpus"
    result = runner.invoke(
        cli, ["corpus", "generate", "--seed", "20260825", "--out", str(out), *SMALL]
    )
    assert result.exit_code == 0, result.output
    assert (out / "manifest.json").is_file()
    assert (out / "split.json").is_file()
    assert list((out / "forms").glob("*.html"))
    assert list((out / "answer_keys").glob("*.json"))
    assert "manifest sha256" in result.output


def test_generate_refuses_a_non_empty_directory(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "corpus"
    out.mkdir()
    (out / "something.txt").write_text("keep me", encoding="utf-8")
    result = runner.invoke(cli, ["corpus", "generate", "--seed", "1", "--out", str(out), *SMALL])
    assert result.exit_code == 2
    assert "Pass --force" in result.output
    assert (out / "something.txt").is_file()


def test_generate_overwrites_with_force(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "corpus"
    out.mkdir()
    (out / "stale.txt").write_text("x", encoding="utf-8")
    result = runner.invoke(
        cli, ["corpus", "generate", "--seed", "1", "--out", str(out), "--force", *SMALL]
    )
    assert result.exit_code == 0, result.output


def test_generate_writes_into_an_empty_directory(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "corpus"
    out.mkdir()
    result = runner.invoke(cli, ["corpus", "generate", "--seed", "1", "--out", str(out), *SMALL])
    assert result.exit_code == 0, result.output


def test_generate_rejects_an_unknown_locale(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        cli,
        [
            "corpus",
            "generate",
            "--seed",
            "1",
            "--out",
            str(tmp_path / "corpus"),
            "--locales",
            "xx-XX",
        ],
    )
    assert result.exit_code == 2
    assert "unknown locale" in result.output


def test_generate_accepts_several_axes(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "corpus"
    result = runner.invoke(
        cli,
        [
            "corpus",
            "generate",
            "--seed",
            "1",
            "--out",
            str(out),
            "--families",
            "login,payment",
            "--locales",
            "en-US, de-DE",
            "--tiers",
            "clean",
            "--variants",
            "2",
            "--base-year",
            "2026",
        ],
    )
    assert result.exit_code == 0, result.output
    families, locales, tiers, variants = 2, 2, 1, 2
    expected = TEMPLATES_PER_FAMILY * families * locales * tiers * variants
    assert len(list((out / "forms").glob("*.html"))) == expected


def test_validate_is_green_on_a_full_corpus(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "corpus"
    generated = runner.invoke(
        cli,
        [
            "corpus",
            "generate",
            "--seed",
            "20260825",
            "--out",
            str(out),
            "--locales",
            "en-US",
            "--base-year",
            "2026",
        ],
    )
    assert generated.exit_code == 0, generated.output
    result = runner.invoke(cli, ["corpus", "validate", "--corpus-dir", str(out)])
    assert result.exit_code == 0, result.output
    assert "corpus validate: green" in result.output
    assert "labels emitted: 42 of 42" in result.output


def test_validate_prints_the_coverage_table(runner: CliRunner, sample_corpus: Path) -> None:
    result = runner.invoke(cli, ["corpus", "validate", "--corpus-dir", str(sample_corpus)])
    assert result.exit_code == 0, result.output
    for group in ("identity", "contact", "address", "payment", "credentials", "extra"):
        assert group in result.output


def test_validate_quiet_skips_the_table(runner: CliRunner, sample_corpus: Path) -> None:
    result = runner.invoke(
        cli, ["corpus", "validate", "--corpus-dir", str(sample_corpus), "--quiet"]
    )
    assert result.exit_code == 0, result.output
    assert "identity" not in result.output
    assert "corpus validate: green" in result.output


def test_validate_fails_on_a_broken_corpus(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "corpus"
    runner.invoke(
        cli,
        ["corpus", "generate", "--seed", "1", "--out", str(out), *SMALL],
    )
    (out / "manifest.json").unlink()
    result = runner.invoke(cli, ["corpus", "validate", "--corpus-dir", str(out)])
    assert result.exit_code == 2
    assert "problem" in result.output


def test_validate_reports_missing_labels(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "corpus"
    runner.invoke(cli, ["corpus", "generate", "--seed", "1", "--out", str(out), *SMALL])
    result = runner.invoke(cli, ["corpus", "validate", "--corpus-dir", str(out)])
    assert "missing:" in result.output


def test_corpus_help_lists_both_commands(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["corpus", "--help"])
    assert result.exit_code == 0
    assert "generate" in result.output
    assert "validate" in result.output


def test_generate_help_names_every_flag(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["corpus", "generate", "--help"])
    assert result.exit_code == 0
    for flag in ("--seed", "--out", "--families", "--locales", "--tiers", "--variants", "--force"):
        assert flag in result.output
