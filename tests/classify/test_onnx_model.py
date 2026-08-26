"""The ONNX engine: calibration, the bundle it loads, and the answers it gives.

Split into three, because the three fail for different reasons and a reader
chasing one of them should not have to read the other two.

The calibration tests are pure arithmetic over hand-built calibrators. They need
no model and no browser, and they are where the one-vs-rest renormalisation of
spec section 10.4 is pinned down.

The bundle tests are about refusing a broken artefact by name. A vocabulary from
one training run beside a calibration from another would produce confident
nonsense with nothing to notice it, so every cross-check gets a case.

The engine tests are about what a report ends up carrying: a calibrated
confidence, named evidence, a runner-up, and an abstention that stays below any
threshold.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from tests.builders import make_descriptor

from autofill_audit.audit.thresholds import load_thresholds
from autofill_audit.classify.base import (
    CONFIDENCE_KIND_KEY,
    CONFIDENCE_KIND_PROBABILITY,
    Classifier,
)
from autofill_audit.classify.onnx_model import (
    CALIBRATION_FILE,
    EVIDENCE_FILE,
    LABEL_MAP_FILE,
    MODEL_DIR_ENV,
    MODEL_FILE,
    VOCAB_FILE,
    Calibration,
    ClassCalibration,
    ModelBundle,
    ModelLoadError,
    NgramClassifier,
    find_model_dir,
    load_bundle,
    load_ngram_engine,
)
from autofill_audit.descriptors import FieldDescriptor
from autofill_audit.taxonomy import Label

# ---------------------------------------------------------------------------
# Calibration.
# ---------------------------------------------------------------------------


def _calibration(*classes: ClassCalibration) -> Calibration:
    return Calibration(classes=classes, switchover_count=100, fitted_on="dev")


def test_the_identity_calibrator_passes_the_raw_probability_through() -> None:
    """A class with too few dev positives is uncalibrated, and honestly so."""
    item = ClassCalibration(label="a", method="identity", dev_positives=1)
    assert item.apply(np.array([0.25, 0.75])).tolist() == [0.25, 0.75]


def test_the_identity_calibrator_still_clips() -> None:
    """Uncalibrated is not the same as unbounded."""
    item = ClassCalibration(label="a", method="identity", dev_positives=0)
    assert item.apply(np.array([-0.5, 1.5])).tolist() == [0.0, 1.0]


def test_the_sigmoid_calibrator_is_monotone_and_bounded() -> None:
    """Platt scaling reorders nothing; it moves the numbers, not the ranking."""
    item = ClassCalibration(label="a", method="sigmoid", dev_positives=8, slope=0.5, intercept=-1.0)
    values = item.apply(np.array([0.01, 0.2, 0.5, 0.8, 0.99]))
    assert list(values) == sorted(values)
    assert all(0.0 <= value <= 1.0 for value in values)


def test_the_sigmoid_calibrator_survives_a_probability_of_zero_and_one() -> None:
    """The logit of an endpoint is the obvious way to divide by zero here."""
    item = ClassCalibration(label="a", method="sigmoid", dev_positives=8, slope=1.0)
    values = item.apply(np.array([0.0, 1.0]))
    assert np.isfinite(values).all()


def test_the_isotonic_calibrator_interpolates_and_clips() -> None:
    """The committed thresholds are the fitted step function, applied by numpy."""
    item = ClassCalibration(
        label="a",
        method="isotonic",
        dev_positives=120,
        thresholds=(0.0, 0.5, 1.0),
        values=(0.0, 0.2, 0.9),
    )
    values = item.apply(np.array([-1.0, 0.25, 0.5, 0.75, 2.0]))
    assert values[0] == pytest.approx(0.0)
    assert values[1] == pytest.approx(0.1)
    assert values[2] == pytest.approx(0.2)
    assert values[4] == pytest.approx(0.9)


def test_an_isotonic_calibrator_with_no_thresholds_falls_back_to_the_identity() -> None:
    """A fitted step function with no steps is not a calibrator."""
    item = ClassCalibration(label="a", method="isotonic", dev_positives=120)
    assert item.apply(np.array([0.3])).tolist() == [0.3]


def test_applying_the_calibration_renormalises_each_row() -> None:
    """Independently calibrated classes do not sum to one, and a confidence must."""
    calibration = _calibration(
        ClassCalibration(label="a", method="identity", dev_positives=5),
        ClassCalibration(label="b", method="identity", dev_positives=5),
    )
    calibrated = calibration.apply(np.array([[0.4, 0.4], [0.1, 0.3]]))
    assert calibrated.sum(axis=1).tolist() == pytest.approx([1.0, 1.0])
    assert calibrated[1].tolist() == pytest.approx([0.25, 0.75])


def test_a_row_calibrated_to_nothing_keeps_its_raw_distribution() -> None:
    """The alternative is a division by zero or an invented uniform row."""
    calibration = _calibration(
        ClassCalibration(
            label="a",
            method="isotonic",
            dev_positives=200,
            thresholds=(0.0, 1.0),
            values=(0.0, 0.0),
        ),
        ClassCalibration(
            label="b",
            method="isotonic",
            dev_positives=200,
            thresholds=(0.0, 1.0),
            values=(0.0, 0.0),
        ),
    )
    raw = np.array([[0.3, 0.7]])
    assert calibration.apply(raw)[0].tolist() == pytest.approx([0.3, 0.7])


def test_a_calibration_of_the_wrong_width_is_refused() -> None:
    """A calibration from another run beside this model is caught, not applied."""
    calibration = _calibration(ClassCalibration(label="a", method="identity", dev_positives=1))
    with pytest.raises(ModelLoadError, match="classes"):
        calibration.apply(np.array([[0.5, 0.5]]))


def test_the_calibration_round_trips_through_json() -> None:
    """Every method's parameters survive the file they are committed in."""
    calibration = _calibration(
        ClassCalibration(label="a", method="identity", dev_positives=0),
        ClassCalibration(label="b", method="sigmoid", dev_positives=9, slope=0.5, intercept=0.25),
        ClassCalibration(
            label="c",
            method="isotonic",
            dev_positives=300,
            thresholds=(0.0, 1.0),
            values=(0.0, 1.0),
        ),
    )
    rebuilt = Calibration.from_json(json.loads(json.dumps(calibration.to_json())))
    assert rebuilt == calibration
    assert rebuilt.methods() == {"a": "identity", "b": "sigmoid", "c": "isotonic"}


@pytest.mark.parametrize(
    "payload",
    [
        {
            "schema_version": 99,
            "fitted_on": "dev",
            "classes": [{"label": "a", "method": "identity"}],
        },
        {"schema_version": 1, "fitted_on": "dev", "classes": []},
        {"schema_version": 1, "fitted_on": "", "classes": [{"label": "a", "method": "identity"}]},
        {"schema_version": 1, "fitted_on": "dev", "switchover_count": "many", "classes": [{}]},
        {"schema_version": 1, "fitted_on": "dev", "classes": [{"label": 1, "method": "identity"}]},
        {
            "schema_version": 1,
            "fitted_on": "dev",
            "classes": [{"label": "a", "method": "identity", "dev_positives": "some"}],
        },
        {
            "schema_version": 1,
            "fitted_on": "dev",
            "classes": [{"label": "a", "method": "isotonic", "thresholds": "no"}],
        },
        {
            "schema_version": 1,
            "fitted_on": "dev",
            "classes": [{"label": "a", "method": "sigmoid", "slope": "steep"}],
        },
    ],
)
def test_a_broken_calibration_document_is_refused_by_name(payload: dict[str, object]) -> None:
    """Every malformed shape raises rather than loading a half-built calibrator."""
    with pytest.raises(ModelLoadError):
        Calibration.from_json(payload)


# ---------------------------------------------------------------------------
# The bundle.
# ---------------------------------------------------------------------------


def _copy_bundle(model_dir: Path, destination: Path) -> Path:
    """Copy the committed bundle so a test can break one file of it."""
    destination.mkdir(parents=True, exist_ok=True)
    for name in (MODEL_FILE, VOCAB_FILE, CALIBRATION_FILE, LABEL_MAP_FILE, EVIDENCE_FILE):
        source = model_dir / name
        if source.is_file():
            shutil.copy(source, destination / name)
    return destination


def test_the_committed_bundle_loads_and_cross_checks(bundle: ModelBundle) -> None:
    """The four files are one artefact and are checked against each other."""
    assert bundle.labels
    assert len(bundle.calibration.classes) == len(bundle.labels)
    assert bundle.space.width > 0
    identity = bundle.identity()
    assert len(identity["model_sha256"]) == 64
    assert identity["class_count"] == str(len(bundle.labels))


def test_a_bundle_missing_a_file_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(ModelLoadError, match="missing"):
        load_bundle(tmp_path)


def test_a_label_map_holding_a_string_that_is_not_a_label_is_refused(
    model_dir: Path, tmp_path: Path
) -> None:
    """Ground rule 6 from the other end: the taxonomy is the only definition."""
    broken = _copy_bundle(model_dir, tmp_path / "broken")
    (broken / LABEL_MAP_FILE).write_text(
        json.dumps({"schema_version": 1, "labels": ["not-a-real-token"]}), encoding="utf-8"
    )
    with pytest.raises(ModelLoadError, match="taxonomy label"):
        load_bundle(broken)


def test_a_calibration_of_a_different_length_is_refused(model_dir: Path, tmp_path: Path) -> None:
    broken = _copy_bundle(model_dir, tmp_path / "short")
    document = json.loads((broken / CALIBRATION_FILE).read_text(encoding="utf-8"))
    document["classes"] = document["classes"][:1]
    (broken / CALIBRATION_FILE).write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ModelLoadError, match="carries"):
        load_bundle(broken)


def test_a_calibration_in_a_different_class_order_is_refused(
    model_dir: Path, tmp_path: Path
) -> None:
    """Order is the whole contract between the map and the model's columns."""
    broken = _copy_bundle(model_dir, tmp_path / "shuffled")
    document = json.loads((broken / CALIBRATION_FILE).read_text(encoding="utf-8"))
    document["classes"] = list(reversed(document["classes"]))
    (broken / CALIBRATION_FILE).write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ModelLoadError, match="class 0"):
        load_bundle(broken)


def test_unreadable_json_is_refused_by_name(model_dir: Path, tmp_path: Path) -> None:
    broken = _copy_bundle(model_dir, tmp_path / "corrupt")
    (broken / VOCAB_FILE).write_text("{not json", encoding="utf-8")
    with pytest.raises(ModelLoadError, match="not valid JSON"):
        load_bundle(broken)


def test_a_broken_evidence_file_is_refused(model_dir: Path, tmp_path: Path) -> None:
    broken = _copy_bundle(model_dir, tmp_path / "evidence")
    (broken / EVIDENCE_FILE).write_text(
        json.dumps({"schema_version": 1, "classes": {"email": ["not a pair"]}}), encoding="utf-8"
    )
    with pytest.raises(ModelLoadError, match="name and weight"):
        load_bundle(broken)


def test_a_bundle_with_no_evidence_file_still_loads(model_dir: Path, tmp_path: Path) -> None:
    """Evidence is a convenience of the vocabulary route, not a load requirement."""
    trimmed = _copy_bundle(model_dir, tmp_path / "no-evidence")
    (trimmed / EVIDENCE_FILE).unlink(missing_ok=True)
    assert load_bundle(trimmed).evidence == {}


def test_a_broken_onnx_file_is_refused_when_the_session_opens(
    model_dir: Path, tmp_path: Path
) -> None:
    broken = _copy_bundle(model_dir, tmp_path / "not-a-graph")
    (broken / MODEL_FILE).write_bytes(b"this is not a protobuf")
    with pytest.raises(ModelLoadError, match="refused it"):
        NgramClassifier(load_bundle(broken))


# ---------------------------------------------------------------------------
# Finding the bundle.
# ---------------------------------------------------------------------------


def test_the_environment_override_wins(model_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MODEL_DIR_ENV, str(model_dir))
    assert find_model_dir() == model_dir


def test_an_override_pointing_at_nothing_finds_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An override is an instruction, not a starting point for a search."""
    monkeypatch.setenv(MODEL_DIR_ENV, str(tmp_path))
    assert find_model_dir() is None


def test_loading_with_no_model_says_how_to_get_one() -> None:
    """The suite runs with the search pointed at an empty directory."""
    with pytest.raises(ModelLoadError, match="autofill-audit train"):
        load_ngram_engine()


# ---------------------------------------------------------------------------
# The engine.
# ---------------------------------------------------------------------------


def test_the_engine_satisfies_the_protocol(engine: NgramClassifier) -> None:
    """The same structural assertion P3 makes about the rule engine."""
    assert isinstance(engine, Classifier)
    assert engine.name == "ngram"


def test_describe_reports_calibrated_probabilities_and_the_artefact_shas(
    engine: NgramClassifier,
) -> None:
    """The load-bearing key, and the identity law 3 needs (P3's handoff)."""
    described = engine.describe()
    assert described[CONFIDENCE_KIND_KEY] == CONFIDENCE_KIND_PROBABILITY
    assert described["providers"] == "CPUExecutionProvider"
    assert described["intra_op_threads"] == "1"
    assert len(described["model_sha256"]) == 64
    assert len(described["calibration_sha256"]) == 64
    assert described["onnx_opset"].isdigit()
    assert all(isinstance(value, str) for value in described.values())


def test_an_empty_page_is_an_empty_answer(engine: NgramClassifier) -> None:
    assert engine.predict([]) == []


def test_every_prediction_carries_a_confidence_a_runner_up_and_a_latency(
    engine: NgramClassifier,
) -> None:
    fields = [
        make_descriptor("#a", label="Postcode", name="postcode"),
        make_descriptor("#b", label="Email address", input_type="email", name="email"),
    ]
    predictions = engine.predict(fields)
    assert [item.selector for item in predictions] == ["#a", "#b"]
    for prediction in predictions:
        assert prediction.engine == "ngram"
        assert 0.0 <= prediction.confidence <= 1.0
        assert prediction.runner_up is not None
        assert prediction.latency_us is not None and prediction.latency_us > 0
        assert len(prediction.signals) <= 8


def test_the_evidence_names_features_and_never_a_taxonomy_label(
    engine: NgramClassifier,
) -> None:
    """Law 1's named evidence, in the vocabulary P3 established for evidence."""
    prediction = engine.predict([make_descriptor("#a", label="Postcode", name="postcode")])[0]
    values = {label.value for label in Label}
    for signal in prediction.signals:
        assert signal.startswith("ngram:")
        assert signal not in values


def test_an_undetectable_descriptor_is_answered_without_featurising(
    engine: NgramClassifier,
) -> None:
    """A blind spot has no text, so a confident answer about it would be invented."""
    blind = make_descriptor("#gone", undetectable_reason="closed-shadow-root")
    prediction = engine.predict([blind])[0]
    assert prediction.label == Label.UNKNOWN.value
    assert prediction.confidence == 0.0
    assert prediction.signals == ("undetectable:closed-shadow-root",)


def test_an_undetectable_descriptor_beside_a_real_one_keeps_the_order(
    engine: NgramClassifier,
) -> None:
    """The short-circuit must not renumber the rows the session did answer."""
    fields = [
        make_descriptor("#gone", undetectable_reason="cross-origin-frame"),
        make_descriptor("#a", label="Postcode", name="postcode"),
        make_descriptor("#gone2", undetectable_reason="canvas-region"),
        make_descriptor("#b", label="Email", input_type="email"),
    ]
    predictions = engine.predict(fields)
    assert [item.selector for item in predictions] == ["#gone", "#a", "#gone2", "#b"]
    assert predictions[0].confidence == 0.0
    assert predictions[2].confidence == 0.0


def test_an_unknown_prediction_reports_zero_and_says_it_abstained(
    engine: NgramClassifier, bundle: ModelBundle
) -> None:
    """The explicit branch P3's handoff asked for.

    Driven directly with a probability row rather than hunting for a control the
    committed model happens to abstain on, because the invariant is about the
    branch and not about any particular page. A test that searched for a probe
    would pass by luck and skip when the luck ran out.
    """
    unknown = bundle.labels.index(Label.UNKNOWN.value)
    row = np.full(len(bundle.labels), 0.01)
    row[unknown] = 0.9
    runner_up_column = (unknown + 1) % len(bundle.labels)
    row[runner_up_column] = 0.05

    prediction = engine._prediction(make_descriptor("#x"), row, [], 12.0)
    assert prediction.label == Label.UNKNOWN.value
    assert prediction.confidence == 0.0
    assert prediction.signals[0] == "ngram:abstain:unknown-class"
    assert prediction.runner_up == (bundle.labels[runner_up_column], 0.05)
    assert prediction.latency_us == 12.0


def test_an_abstention_stays_below_every_committed_threshold(
    engine: NgramClassifier, sample_dev_slice: list[tuple[FieldDescriptor, str]]
) -> None:
    """The invariant the decision procedure depends on, over a real slice.

    UNKNOWN must stay below the low threshold or the audit engine would ask
    whether to raise a finding for the label UNKNOWN, reach the right answer
    through declaration_for returning nothing, and be right by accident.
    """
    thresholds = load_thresholds(engine.name)
    for prediction in engine.predict([descriptor for descriptor, _ in sample_dev_slice]):
        if prediction.label == Label.UNKNOWN.value:
            assert prediction.confidence < thresholds.tau_low


def test_the_batch_and_the_single_field_agree(engine: NgramClassifier) -> None:
    """One call per page and one call per field must give the same answer.

    ``predict`` batches a whole page through one session call, which is the only
    way the latency numbers mean anything. A batch that changed an answer would
    make a benchmark and an audit disagree about the same page.
    """
    fields = [
        make_descriptor("#a", label="Postcode", name="postcode"),
        make_descriptor("#b", label="Email address", input_type="email"),
        make_descriptor("#c", label="Card number", name="cardnumber", maxlength=19),
    ]
    batched = engine.predict(fields)
    singles = [engine.predict([field])[0] for field in fields]
    for one, many in zip(singles, batched, strict=True):
        assert one.label == many.label
        assert one.confidence == pytest.approx(many.confidence)
        assert one.signals == many.signals


def test_the_calibrated_confidences_are_a_distribution(
    engine: NgramClassifier, sample_dev_slice: list[tuple[FieldDescriptor, str]]
) -> None:
    """Over a real slice, every reported confidence is a probability."""
    descriptors = [descriptor for descriptor, _ in sample_dev_slice]
    assert descriptors
    for prediction in engine.predict(descriptors):
        assert 0.0 <= prediction.confidence <= 1.0
        if prediction.runner_up is not None:
            assert 0.0 <= prediction.runner_up[1] <= 1.0
            if prediction.label != Label.UNKNOWN.value:
                assert prediction.confidence >= prediction.runner_up[1]
