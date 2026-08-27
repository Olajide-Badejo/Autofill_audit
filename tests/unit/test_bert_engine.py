"""The P8 encoder's serialiser and bundle loader (spec section 10.7).

The session and the engine are not exercised here. Running them needs the
``bert-train`` extra, which is deliberately absent from ``requirements.lock`` and
therefore absent from CI (`docs/adr/0008-transformer-stretch.md`), and a test
that skipped itself on the build machine as well would be a test that never ran.
What is testable everywhere is the part that decides what the model reads and
the part that refuses to load a bundle that does not hang together, and both of
those are pure Python over records.

The one that matters most is the declaration-independence property. A leak there
would not crash anything, would not look wrong in a diff, and would turn every
clean-tier number in the headline table into a measurement of copying.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import bert_engine
from autofill_audit.classify.onnx_model import (
    CALIBRATION_FILE,
    LABEL_MAP_FILE,
    LABEL_MAP_SCHEMA_VERSION,
    Calibration,
    ClassCalibration,
    ModelLoadError,
)
from autofill_audit.descriptors import DeclaredAutocomplete, GroupRole
from autofill_audit.taxonomy import Label
from builders import make_descriptor

# ---------------------------------------------------------------------------
# Serialisation.
# ---------------------------------------------------------------------------


def test_the_rendered_field_carries_the_signals_the_model_is_meant_to_read() -> None:
    descriptor = make_descriptor(
        "#plz",
        label="Postleitzahl",
        placeholder="10115",
        name="addr_plz",
        element_id="plz",
        input_type="text",
        inputmode="numeric",
    )
    rendered = bert_engine.field_text(descriptor)
    assert "tag input type text inputmode numeric" in rendered
    assert "label Postleitzahl" in rendered
    assert "placeholder 10115" in rendered
    assert "name addr_plz" in rendered
    assert "id plz" in rendered


def test_the_rendering_is_deterministic_and_depends_on_no_neighbour() -> None:
    """Two identical descriptors render identically, whatever is beside them."""
    first = make_descriptor("#a", label="E-Mail", name="usr_email")
    second = make_descriptor("#b", label="E-Mail", name="usr_email")
    assert bert_engine.field_text(first) == bert_engine.field_text(second)
    batch = bert_engine.field_texts([first, second])
    assert batch == [bert_engine.field_text(first), bert_engine.field_text(second)]


def test_a_declared_autocomplete_value_never_reaches_the_string() -> None:
    """The one drop that has to be checked rather than trusted."""
    plain = make_descriptor("#email", label="Email", name="usr_email")
    declaring = make_descriptor("#email", label="Email", name="usr_email", declared="email")
    assert declaring.declared.token == Label.EMAIL.value
    assert bert_engine.field_text(declaring) == bert_engine.field_text(plain)
    bert_engine.assert_no_declaration_leaks([declaring, plain])


def test_a_leak_is_an_error_and_not_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check fails when the rendering stops being independent of the token."""
    original = bert_engine.field_text

    def leaking(descriptor: object) -> str:
        rendered = original(descriptor)  # type: ignore[arg-type]
        token = getattr(descriptor, "declared", DeclaredAutocomplete()).token
        return f"{rendered} | autocomplete {token}" if token else rendered

    monkeypatch.setattr(bert_engine, "field_text", leaking)
    declaring = make_descriptor("#email", label="Email", declared="email")
    with pytest.raises(ValueError, match="changed the string the encoder reads"):
        bert_engine.assert_no_declaration_leaks([declaring])


def test_an_enormous_option_list_is_truncated_and_its_count_survives() -> None:
    """Spec section 15's hostile select: a diagnostic rather than a wrong answer."""
    labels = tuple(f"option-{index}" for index in range(5000))
    descriptor = make_descriptor("#country", label="Land", option_labels=labels)
    rendered = bert_engine.field_text(descriptor)
    assert "options 5000:" in rendered
    assert rendered.count("option-") == bert_engine.OPTION_LABEL_LIMIT


def test_a_ten_thousand_character_label_is_cut_at_the_limit() -> None:
    descriptor = make_descriptor("#x", label="a" * 10000)
    rendered = bert_engine.field_text(descriptor)
    segment = next(
        part for part in rendered.split(bert_engine.SEGMENT_SEPARATOR) if part[:5] == "label"
    )
    assert len(segment) == len("label ") + bert_engine.TEXT_MAX_CHARS


def test_the_structural_segment_is_always_present() -> None:
    descriptor = make_descriptor("#x", document_index=7)
    assert "position 7 siblings 0" in bert_engine.field_text(descriptor)


def test_a_group_role_is_named_only_when_there_is_one() -> None:
    plain = make_descriptor("#x")
    grouped = make_descriptor("#y", group_role=GroupRole.ADDRESS_LINE_MEMBER, group_id="g1")
    assert "group " not in bert_engine.field_text(plain)
    assert f"group {GroupRole.ADDRESS_LINE_MEMBER.value}" in bert_engine.field_text(grouped)


def test_an_undetectable_descriptor_says_so_in_its_string() -> None:
    descriptor = make_descriptor("#canvas", undetectable_reason="canvas-region")
    assert "undetectable canvas-region" in bert_engine.field_text(descriptor)


# ---------------------------------------------------------------------------
# The evidence this engine can and cannot give.
# ---------------------------------------------------------------------------


def test_presence_signals_name_the_segments_that_were_actually_there() -> None:
    descriptor = make_descriptor(
        "#plz", label="Postleitzahl", name="addr_plz", context="Lieferadresse"
    )
    signals = bert_engine.presence_signals(bert_engine.field_text(descriptor))
    assert "bert:input:label" in signals
    assert "bert:input:identifier" in signals
    assert "bert:input:context" in signals
    assert "bert:input:options" not in signals


def test_presence_signals_are_deduplicated_and_ordered() -> None:
    """Two identifier segments name the identifier input once."""
    descriptor = make_descriptor("#x", name="a", element_id="b")
    signals = bert_engine.presence_signals(bert_engine.field_text(descriptor))
    assert signals.count("bert:input:identifier") == 1
    assert list(signals) == sorted(signals, key=list(signals).index)


# ---------------------------------------------------------------------------
# Numerics.
# ---------------------------------------------------------------------------


def test_softmax_rows_sum_to_one_and_survive_large_logits() -> None:
    import numpy as np

    probabilities = bert_engine.softmax(np.array([[1000.0, 999.0], [0.0, 0.0]]))
    assert probabilities.shape == (2, 2)
    assert np.allclose(probabilities.sum(axis=1), 1.0)
    assert np.isfinite(probabilities).all()
    assert probabilities[1, 0] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# The bundle loader.
# ---------------------------------------------------------------------------


def _write_bundle(directory: Path, labels: tuple[str, ...]) -> None:
    """Write a bundle whose only unreal part is the graph itself."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / bert_engine.MODEL_INT8_FILE).write_bytes(b"not a real graph")
    (directory / bert_engine.TOKENIZER_FILE).write_text("{}", encoding="utf-8")
    (directory / LABEL_MAP_FILE).write_text(
        json.dumps({"schema_version": LABEL_MAP_SCHEMA_VERSION, "labels": list(labels)}),
        encoding="utf-8",
    )
    calibration = Calibration(
        classes=tuple(
            ClassCalibration(label=name, method="identity", dev_positives=1) for name in labels
        ),
        switchover_count=100,
        fitted_on="dev",
    )
    (directory / CALIBRATION_FILE).write_text(json.dumps(calibration.to_json()), encoding="utf-8")
    (directory / bert_engine.CONFIG_FILE).write_text(
        json.dumps(
            {
                "schema_version": bert_engine.CONFIG_SCHEMA_VERSION,
                "base_model": "distilbert-base-multilingual-cased",
                "max_length": 64,
                "quantization": "int8-dynamic",
            }
        ),
        encoding="utf-8",
    )


def test_a_complete_bundle_loads_and_reports_its_identity(tmp_path: Path) -> None:
    labels = (Label.EMAIL.value, Label.UNKNOWN.value)
    _write_bundle(tmp_path, labels)
    bundle = bert_engine.load_bundle(tmp_path)
    assert bundle.labels == labels
    assert bundle.max_length == 64
    identity = bundle.identity()
    assert identity["quantization"] == "int8-dynamic"
    assert identity["class_count"] == "2"
    assert len(identity["model_sha256"]) == 64


def test_a_bundle_missing_a_file_names_what_is_missing(tmp_path: Path) -> None:
    _write_bundle(tmp_path, (Label.EMAIL.value,))
    (tmp_path / bert_engine.TOKENIZER_FILE).unlink()
    with pytest.raises(ModelLoadError, match=bert_engine.TOKENIZER_FILE):
        bert_engine.load_bundle(tmp_path)


def test_a_calibration_that_names_other_classes_is_refused(tmp_path: Path) -> None:
    """A vocabulary from one run beside a calibration from another is nonsense."""
    _write_bundle(tmp_path, (Label.EMAIL.value, Label.UNKNOWN.value))
    (tmp_path / LABEL_MAP_FILE).write_text(
        json.dumps(
            {
                "schema_version": LABEL_MAP_SCHEMA_VERSION,
                "labels": [Label.UNKNOWN.value, Label.EMAIL.value],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ModelLoadError, match="class 0"):
        bert_engine.load_bundle(tmp_path)


def test_a_config_at_the_wrong_schema_version_is_refused(tmp_path: Path) -> None:
    _write_bundle(tmp_path, (Label.EMAIL.value,))
    (tmp_path / bert_engine.CONFIG_FILE).write_text(
        json.dumps({"schema_version": 99, "max_length": 64}), encoding="utf-8"
    )
    with pytest.raises(ModelLoadError, match="schema version"):
        bert_engine.load_bundle(tmp_path)


def test_a_label_outside_the_taxonomy_is_refused(tmp_path: Path) -> None:
    """Law 2: the taxonomy has one definition and a bundle may not widen it."""
    _write_bundle(tmp_path, (Label.EMAIL.value,))
    (tmp_path / LABEL_MAP_FILE).write_text(
        json.dumps({"schema_version": LABEL_MAP_SCHEMA_VERSION, "labels": ["tarot-card"]}),
        encoding="utf-8",
    )
    with pytest.raises(ModelLoadError, match="not a taxonomy label"):
        bert_engine.load_bundle(tmp_path)


def test_the_search_finds_nothing_when_there_is_nothing(tmp_path: Path) -> None:
    assert bert_engine.find_bundle_dir(tmp_path) is None
    with pytest.raises(ModelLoadError, match="no fine-tuned encoder bundle"):
        bert_engine.load_bert_engine(tmp_path)


def test_the_environment_override_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_bundle(tmp_path, (Label.EMAIL.value,))
    monkeypatch.setenv(bert_engine.BERT_MODEL_DIR_ENV, str(tmp_path))
    assert bert_engine.find_bundle_dir() == tmp_path


def test_the_fp32_graph_can_be_asked_for_by_name(tmp_path: Path) -> None:
    """The parity check loads the unquantized graph through the same loader."""
    _write_bundle(tmp_path, (Label.EMAIL.value,))
    (tmp_path / bert_engine.MODEL_FP32_FILE).write_bytes(b"not a real graph either")
    bundle = bert_engine.load_bundle(tmp_path, quantized=False)
    assert bundle.model_path.name == bert_engine.MODEL_FP32_FILE
    assert bundle.quantization == "none-fp32"


# ---------------------------------------------------------------------------
# The runtime tokenizer, when the optional wheel is present.
# ---------------------------------------------------------------------------


def test_the_runtime_tokenizer_needs_a_pad_token(tmp_path: Path) -> None:
    pytest.importorskip("tokenizers", reason="the bert-train extra is not installed")
    from tokenizers import Tokenizer, models

    path = tmp_path / bert_engine.TOKENIZER_FILE
    Tokenizer(models.WordPiece(vocab={"[UNK]": 0}, unk_token="[UNK]")).save(str(path))
    with pytest.raises(ModelLoadError, match=r"\[PAD\]"):
        bert_engine.open_tokenizer(path, 32)


def test_the_declaration_check_skips_a_field_that_declares_nothing() -> None:
    """The loop's cheap exit, which is most fields on a hostile page."""
    descriptor = replace(make_descriptor("#x"), declared=DeclaredAutocomplete())
    bert_engine.assert_no_declaration_leaks([descriptor])
