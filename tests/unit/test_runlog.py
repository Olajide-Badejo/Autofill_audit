"""The run-log schema of spec section 13.1 and the manifest of spec section 18."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autofill_audit.evaluate.runlog import (
    CONFIDENCE_KINDS,
    Manifest,
    RunLogError,
    RunLogRow,
    confidence_kind_for,
    machine_descriptor,
    make_run_id,
    read_manifest,
    read_rows,
    resolved_versions,
    write_manifest,
    write_rows,
)


def _row(**overrides: object) -> RunLogRow:
    """A row with every required field filled, for a test to vary one of."""
    fields: dict[str, object] = {
        "run_id": "2026-08-26T00-00-00Z_ngram_abcdefg",
        "engine": "ngram",
        "engine_describe": {"engine": "ngram", "confidence_kind": "calibrated-probability"},
        "corpus_manifest_sha": "a" * 64,
        "split": "test",
        "form_id": "checkout-02-de-DE-hostile-v0",
        "form_family": "checkout",
        "locale": "de-DE",
        "tier": "hostile",
        "template_id": "checkout-02",
        "selector": "#plz",
        "true_label": "postal-code",
        "pred_label": "postal-code",
        "confidence": 0.91,
        "confidence_kind": "calibrated",
    }
    fields.update(overrides)
    return RunLogRow(**fields)  # type: ignore[arg-type]


def test_a_row_carries_every_key_spec_thirteen_one_names() -> None:
    payload = _row().to_json()
    expected = {
        "schema_version",
        "run_id",
        "engine",
        "engine_describe",
        "prompt_version",
        "corpus_manifest_sha",
        "split",
        "form_id",
        "form_family",
        "locale",
        "tier",
        "template_id",
        "selector",
        "true_label",
        "pred_label",
        "correct",
        "confidence",
        "confidence_kind",
        "runner_up_label",
        "runner_up_confidence",
        "signals",
        "latency_us",
        "declared_token",
        "finding_codes",
        "extraction_warnings",
    }
    assert set(payload) == expected


def test_correct_is_derived_and_never_stored() -> None:
    """The row cannot disagree with itself about whether it was right."""
    assert _row().correct is True
    assert _row(pred_label="address-level2").correct is False


def test_a_row_without_a_template_id_is_refused() -> None:
    """Spec section 13.3 clusters by template, so a row without one is unusable."""
    with pytest.raises(RunLogError, match="template_id"):
        _row(template_id="")


def test_the_confidence_kind_vocabulary_is_closed() -> None:
    assert {"calibrated", "rule_tier", "self_reported"} == CONFIDENCE_KINDS
    with pytest.raises(RunLogError, match="not one of"):
        _row(confidence_kind="pretty sure")


def test_the_engines_own_words_map_onto_the_schemas_three() -> None:
    assert confidence_kind_for({"confidence_kind": "calibrated-probability"}) == "calibrated"
    assert confidence_kind_for({"confidence_kind": "tier"}) == "rule_tier"


def test_an_unmapped_confidence_kind_is_an_error_and_not_a_default() -> None:
    """P6's engine has to add its word deliberately. That is the whole point."""
    with pytest.raises(RunLogError, match="no word for"):
        confidence_kind_for({"confidence_kind": "vibes"})
    with pytest.raises(RunLogError, match="carries no confidence_kind"):
        confidence_kind_for({})


def test_a_row_round_trips(tmp_path: Path) -> None:
    rows = [_row(), _row(selector="#city", true_label="address-level2", pred_label="UNKNOWN")]
    path = tmp_path / "run.jsonl"
    assert write_rows(path, rows) == 2
    assert read_rows(path) == rows


def test_a_run_log_is_never_overwritten(tmp_path: Path) -> None:
    """Result files are append-only history (spec section 18)."""
    path = tmp_path / "run.jsonl"
    write_rows(path, [_row()])
    with pytest.raises(RunLogError, match="append-only"):
        write_rows(path, [_row()])


def test_a_schema_version_this_build_cannot_read_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    payload = _row().to_json()
    payload["schema_version"] = "2.0.0"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(RunLogError, match="schema"):
        read_rows(path)


def _manifest(**overrides: object) -> Manifest:
    fields: dict[str, object] = {
        "run_id": "r",
        "command_line": "eval.py --split test",
        "split": "test",
        "engine": "ngram",
        "engine_describe": {"engine": "ngram"},
        "threshold_describe": {"tau_high": "0.9"},
        "artefact_sha256": {"model.onnx": "b" * 64},
        "corpus_manifest_sha": "a" * 64,
        "split_file_sha": "c" * 64,
        "seed": 20260825,
        "git_commit": "d" * 40,
        "git_dirty": False,
        "dependency_versions": {"python": "3.14.4"},
        "machine": {"os": "Linux"},
        "started_at": "2026-08-26T00:00:00Z",
        "finished_at": "2026-08-26T00:01:00Z",
        "row_count": 1,
        "form_count": 1,
    }
    fields.update(overrides)
    return Manifest(**fields)  # type: ignore[arg-type]


def test_a_manifest_carries_everything_spec_eighteen_requires(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    write_manifest(path, _manifest())
    document = read_manifest(path)
    for key in (
        "schema_version",
        "git",
        "dependency_versions",
        "corpus_manifest_sha",
        "split_file_sha",
        "seed",
        "engine_describe",
        "command_line",
        "machine",
        "started_at",
        "finished_at",
        "artefact_sha256",
    ):
        assert key in document, key
    assert document["git"] == {"commit": "d" * 40, "dirty": False}


def test_a_dirty_run_is_not_citable() -> None:
    """Spec section 18: a result from a dirty tree is marked and is not citable."""
    assert _manifest().citable is True
    assert _manifest(git_dirty=True).citable is False
    assert _manifest(git_commit="").citable is False


def test_a_manifest_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    write_manifest(path, _manifest())
    with pytest.raises(RunLogError, match="append-only"):
        write_manifest(path, _manifest())


def test_the_run_id_names_the_engine_and_the_commit() -> None:
    run_id = make_run_id("ngram", "abcdef1234567890")
    assert run_id.endswith("_ngram_abcdef1")
    assert make_run_id("rules", "").endswith("_rules_unknown")


def test_the_machine_descriptor_answers_every_question_spec_eighteen_asks() -> None:
    descriptor = machine_descriptor()
    for key in ("os", "machine", "python", "cpu_model", "cpu_count", "gpu_present"):
        assert descriptor[key]


def test_an_absent_dependency_is_recorded_as_absent_rather_than_omitted() -> None:
    resolved = resolved_versions(["numpy", "a-package-nobody-published"])
    assert resolved["a-package-nobody-published"] == "absent"
    assert resolved["numpy"] != "absent"
    assert "python" in resolved
