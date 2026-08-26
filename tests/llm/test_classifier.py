"""The LLM-backed ``Classifier``: chunking, latency, and the contracts downstream.

The classifier's job is the mapping between a page and a sequence of calls, plus
satisfying the three contracts that make an engine interchangeable with the other
two: the ``Classifier`` protocol, the run log's ``confidence_kind`` vocabulary,
and the renderer's confidence formatting.
"""

from __future__ import annotations

import json

import pytest

from autofill_audit.audit.engine import AuditOptions
from autofill_audit.audit.engine import audit as run_audit
from autofill_audit.audit.thresholds import load_thresholds
from autofill_audit.classify import EngineChoice, UnavailableEngineError, load_engine
from autofill_audit.classify.base import CONFIDENCE_KIND_KEY, Classifier
from autofill_audit.classify.llm import ENGINE_NAME, LLMClassifier
from autofill_audit.evaluate import runlog
from autofill_audit.llm import prompts
from autofill_audit.llm.client import LLMConfig, OllamaClient, RecordedTransport
from autofill_audit.taxonomy import Label
from builders import make_descriptor, make_result
from conftest import client_for, descriptors_for, load_transcript


def classifier_for(name: str, *, batch: int = 40) -> tuple[LLMClassifier, list]:
    """A classifier wired to one committed transcript."""
    client, fields, _ = client_for(name)
    return LLMClassifier(client, batch=batch), fields


# ---------------------------------------------------------------------------
# The protocol and the identity contracts.
# ---------------------------------------------------------------------------


def test_the_engine_satisfies_the_classifier_protocol() -> None:
    engine, _ = classifier_for("compliant")
    assert isinstance(engine, Classifier)
    assert engine.name == ENGINE_NAME


def test_the_engine_name_is_llm_and_the_model_tag_lives_in_describe() -> None:
    """P5's handoff settled this: the tag in the engine name would make every
    model tag a new engine in the headline grid."""
    engine, _ = classifier_for("compliant")
    described = engine.describe()

    assert described["engine"] == "llm"
    assert described["model_tag"] == "mistral-nemo:12b-instruct-2407-q4_K_M"
    assert described["quantization"] == "q4_K_M"


def test_the_confidence_kind_maps_onto_the_run_log_vocabulary() -> None:
    """``runlog._DESCRIBE_TO_KIND`` is a total function that raises on an unknown
    word. This engine's word has to be in it, and it is, deliberately, since
    P5."""
    engine, _ = classifier_for("compliant")
    assert runlog.confidence_kind_for(engine.describe()) == "self_reported"


def test_describe_says_the_confidence_is_not_calibrated_and_the_latency_is_amortised() -> None:
    engine, _ = classifier_for("compliant")
    described = engine.describe()

    assert described[CONFIDENCE_KIND_KEY] == "self-reported"
    assert "never feeds the threshold policy" in described["confidence_note"]
    assert "amortises the round trip" in described["latency_note"]


def test_the_prompt_version_reaches_a_run_log_row() -> None:
    """Spec section 13.1's ``prompt_version`` was null for both P5 engines. It is
    this engine's equivalent of a model sha and a row without it could not say
    which prompt produced it."""
    engine, fields = classifier_for("compliant")
    engine.predict(fields)

    row = runlog.RunLogRow(
        run_id="r",
        engine=ENGINE_NAME,
        engine_describe=engine.describe(),
        corpus_manifest_sha="sha",
        split="test",
        form_id="f",
        form_family="checkout",
        locale="en-US",
        tier="clean",
        template_id="checkout_t01",
        selector="#a",
        true_label=Label.EMAIL.value,
        pred_label=Label.EMAIL.value,
        confidence=0.9,
        confidence_kind="self_reported",
        prompt_version=engine.describe()["prompt_version"],
    )
    assert row.to_json()["prompt_version"] == prompts.PROMPT_VERSION


# ---------------------------------------------------------------------------
# Prediction, chunking, and latency.
# ---------------------------------------------------------------------------


def test_one_prediction_per_descriptor_in_the_order_given() -> None:
    engine, fields = classifier_for("compliant")
    predictions = engine.predict(fields)

    assert len(predictions) == len(fields)
    assert [item.selector for item in predictions] == [field.selector for field in fields]
    assert all(item.engine == ENGINE_NAME for item in predictions)


def test_a_page_under_the_cap_is_one_request() -> None:
    """Spec section 12.3 point 6 prefers one request per page, since page-level
    context is part of what the model is being given credit for."""
    document = load_transcript("compliant")
    transport = RecordedTransport(list(document["responses"]))
    engine = LLMClassifier(OllamaClient(LLMConfig(), transport), batch=40)
    engine.predict(descriptors_for(document["selectors"]))

    assert len(transport.requests) == 1


def test_a_page_over_the_cap_is_split_into_consecutive_chunks() -> None:
    document = load_transcript("compliant")
    selectors = document["selectors"]
    fields = descriptors_for(selectors)

    def one(selector: str, label: str) -> dict:
        content = json.dumps(
            {"fields": [{"selector": selector, "label": label, "confidence": 0.8}]}
        )
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}

    transport = RecordedTransport(
        [
            one(selectors[0], Label.GIVEN_NAME.value),
            one(selectors[1], Label.POSTAL_CODE.value),
            one(selectors[2], Label.NOT_AUTOFILLABLE.value),
        ]
    )
    engine = LLMClassifier(OllamaClient(LLMConfig(batch=1), transport), batch=1)
    predictions = engine.predict(fields)

    assert len(transport.requests) == 3, "one request per chunk"
    assert len(predictions) == 3
    assert engine.accounting.batch_sizes == [1, 1, 1]


def test_latency_is_the_batch_elapsed_time_divided_by_the_field_count() -> None:
    """The convention the n-gram engine already uses, and the sentence that has
    to travel with it."""
    engine, fields = classifier_for("compliant")
    predictions = engine.predict(fields)

    assert all(item.latency_us is not None for item in predictions)
    assert len({item.latency_us for item in predictions}) == 1, (
        "every field of one batch carries the same per-field share, which is what "
        "makes it a share rather than a measurement"
    )


def test_there_is_no_runner_up_because_the_schema_returns_one_label() -> None:
    engine, fields = classifier_for("compliant")
    predictions = engine.predict(fields)

    assert all(item.runner_up is None for item in predictions)


def test_every_prediction_is_marked_as_carrying_a_self_reported_number() -> None:
    engine, fields = classifier_for("compliant")
    predictions = engine.predict(fields)

    assert all("llm:self-reported-confidence" in item.signals for item in predictions)


def test_the_models_own_reason_is_prefixed_as_a_claim_rather_than_as_evidence() -> None:
    """A finding's signals are evidence. A sentence the model wrote about its own
    answer is a claim, and the prefix is what keeps the two distinguishable."""
    engine, fields = classifier_for("compliant")
    predictions = engine.predict(fields)

    reasons = [
        signal
        for item in predictions
        for signal in item.signals
        if signal.startswith("llm:model-stated-reason:")
    ]
    assert reasons


# ---------------------------------------------------------------------------
# The failure path, end to end through the classifier.
# ---------------------------------------------------------------------------


def test_a_field_the_model_never_answered_is_predicted_unknown_and_kept() -> None:
    """Spec section 12.3 point 4 at the engine boundary. The field reaches the
    run log, stays in the denominator, and is marked so the results table can
    say how often it happened."""
    engine, fields = classifier_for("not_json_twice")
    predictions = engine.predict(fields)

    assert len(predictions) == len(fields), "nothing dropped"
    assert all(item.label == Label.UNKNOWN.value for item in predictions)
    assert all(item.confidence == 0.0 for item in predictions)
    assert all("llm:schema-failure-scored-unknown" in item.signals for item in predictions)


def test_a_partial_failure_marks_only_the_field_it_cost() -> None:
    engine, fields = classifier_for("missing_selector_twice")
    predictions = engine.predict(fields)

    marked = [item for item in predictions if "llm:schema-failure-scored-unknown" in item.signals]
    assert len(marked) == 1
    assert marked[0].selector == fields[2].selector
    assert predictions[0].label == Label.GIVEN_NAME.value


def test_a_batch_below_one_is_refused() -> None:
    client, _, _ = client_for("compliant")
    with pytest.raises(ValueError, match="at least one field"):
        LLMClassifier(client, batch=0)


# ---------------------------------------------------------------------------
# The threshold block and the renderer arm.
# ---------------------------------------------------------------------------


def test_the_llm_threshold_block_exists_and_gates_nothing() -> None:
    """Spec section 12.1: a self-reported confidence never feeds the threshold
    policy. The block exists because the decision procedure needs two floats and
    it is zero and zero so that the number decides nothing.

    Pre-registered in experiments/predictions/p6-llm-comparison.md before the
    engine classified a field.
    """
    thresholds = load_thresholds("llm")

    assert thresholds.tau_high == 0.0
    assert thresholds.tau_low == 0.0
    assert thresholds.measured is False
    assert "decides nothing" in thresholds.basis


def test_a_self_reported_confidence_is_rendered_with_its_marker() -> None:
    """Spec section 12.1 forbids rendering it as a bare percentage beside a
    calibrated one without a marker distinguishing them. This is the marker, and
    ``audit/engine.py::_confidence_display`` is the one place it happens."""
    result = make_result(
        make_descriptor(selector="#a", label="First name", name="fname", element_id="a")
    )

    document = json.dumps(
        {"fields": [{"selector": "#a", "label": "given-name", "confidence": 0.93}]}
    )
    transport = RecordedTransport(
        [{"choices": [{"message": {"role": "assistant", "content": document}}]}]
    )
    engine = LLMClassifier(OllamaClient(LLMConfig(), transport), batch=40)

    report = run_audit(result, engine, AuditOptions(thresholds=load_thresholds("llm")))
    displays = [finding.confidence_display for finding in report.findings if finding.confidence]

    assert displays, "the page declares nothing, so it should be accused"
    assert all("self-reported" in display for display in displays)
    assert all("not calibrated" in display for display in displays)


def test_naming_the_llm_engine_without_a_server_fails_by_name_rather_than_silently() -> None:
    """Spec section 14's fail-fast. An engine that silently became a different
    one would make a three-engine benchmark report two under three names."""
    config = LLMConfig(endpoint="http://127.0.0.1:1/v1")

    with pytest.raises(UnavailableEngineError, match="no server answered"):
        load_engine(EngineChoice.LLM, llm_config=config)


def test_a_wrong_configuration_type_is_refused_by_name() -> None:
    with pytest.raises(UnavailableEngineError, match="must be an LLMConfig"):
        load_engine(EngineChoice.LLM, llm_config="http://localhost")
