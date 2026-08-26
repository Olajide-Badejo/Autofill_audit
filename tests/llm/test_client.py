"""The validation, retry, and failure accounting of spec section 12.3.

Every test here replays a committed transcript through the real client. Nothing
is mocked at the client level, so what is under test is the code the benchmark
ran rather than a second implementation of it, and nothing touches a network.
"""

from __future__ import annotations

import json

import pytest

from autofill_audit.llm import prompts
from autofill_audit.llm.client import (
    MAX_ATTEMPTS,
    CloudClient,
    LLMConfig,
    LLMError,
    OllamaClient,
    RecordedTransport,
    quantization_of,
)
from autofill_audit.taxonomy import Label
from conftest import client_for, descriptors_for

# ---------------------------------------------------------------------------
# The happy path, and what the request carried.
# ---------------------------------------------------------------------------


def test_a_compliant_response_takes_one_attempt_and_answers_every_selector(compliant) -> None:
    client, fields, _ = compliant
    response = client.classify(fields, batch=40)

    assert response.attempts == 1
    assert response.failure_reason is None
    assert response.unresolved == ()
    assert response.compliant
    assert set(response.labels) == {field.selector for field in fields}
    assert response.labels[fields[0].selector] == Label.GIVEN_NAME.value
    assert response.labels[fields[1].selector] == Label.POSTAL_CODE.value


def test_the_request_carries_the_schema_with_the_taxonomy_injected(compliant) -> None:
    client, fields, transport = compliant
    client.classify(fields, batch=40)

    sent = transport.requests[0]
    schema = sent["response_format"]["json_schema"]
    assert sent["response_format"]["type"] == "json_schema"
    assert schema["name"] == prompts.SCHEMA_NAME

    enum = schema["schema"]["properties"]["fields"]["items"]["properties"]["label"]["enum"]
    assert set(enum) == {label.value for label in Label}, (
        "ground rule 6: the enum is injected from taxonomy.py, so it is the taxonomy "
        "and not a copy of it that drifted"
    )


def test_temperature_and_seed_travel_with_the_request(compliant) -> None:
    client, fields, transport = compliant
    client.classify(fields, batch=40)

    sent = transport.requests[0]
    assert sent["temperature"] == 0.0
    assert sent["seed"] == 20260825


def test_an_unset_seed_is_omitted_rather_than_sent_as_null() -> None:
    client, fields, transport = client_for("compliant", config=LLMConfig(seed=None))
    client.classify(fields, batch=40)

    assert "seed" not in transport.requests[0]


def test_the_declared_autocomplete_never_reaches_the_request() -> None:
    """Spec section 12.2's one required drop, checked on the wire.

    The descriptors here declare the answer. If the declaration reached the
    request, every clean-tier number in the headline table would be a measure of
    copying.
    """
    from builders import make_descriptor

    fields = [
        make_descriptor(selector="#a", label="First name", name="fname", declared="given-name"),
        make_descriptor(selector="#b", label="Postal code", name="plz", declared="postal-code"),
    ]
    document = json.loads(
        json.dumps(
            {
                "fields": [
                    {"selector": "#a", "label": "given-name", "confidence": 0.9},
                    {"selector": "#b", "label": "postal-code", "confidence": 0.9},
                ]
            }
        )
    )
    envelope = {
        "choices": [{"message": {"role": "assistant", "content": json.dumps(document)}}],
    }
    transport = RecordedTransport([envelope])
    OllamaClient(LLMConfig(), transport).classify(fields, batch=40)

    body = json.dumps(transport.requests[0])
    assert "autocomplete" not in body
    assert '"declared"' not in body


def test_a_leaked_declaration_is_an_error_rather_than_a_quiet_advantage() -> None:
    """``assert_no_declaration_leaks`` is the check, so it has to be able to fail."""
    from builders import make_descriptor

    field = make_descriptor(selector="#a", label="First name", declared="given-name")
    leaked = [{**prompts.prune(field), "autocomplete": "given-name"}]

    with pytest.raises(ValueError, match="changed the pruned payload"):
        prompts.assert_no_declaration_leaks(leaked, [field])


# ---------------------------------------------------------------------------
# Parse failure and the parse retry (spec section 12.3 points 1 and 4).
# ---------------------------------------------------------------------------


def test_prose_is_retried_once_with_the_error_text_and_then_succeeds() -> None:
    client, fields, transport = client_for("not_json_then_valid")
    response = client.classify(fields, batch=40)

    assert response.attempts == 2
    assert response.failure_reason is None
    assert response.unresolved == ()
    assert len(response.labels) == len(fields)

    retry = transport.requests[1]["messages"][-1]["content"]
    assert "could not be parsed as JSON" in retry
    assert "Return only the JSON document" in retry


def test_a_second_parse_failure_scores_every_field_unknown_and_keeps_them_all() -> None:
    """The P6 gate: retried once, then UNKNOWN, and never dropped.

    Spec section 12.3 point 4 in one assertion set. The denominator is the thing
    being protected: a benchmark that quietly excluded the fields a model failed
    to answer would be reporting the model's accuracy on the subset it happened
    to handle.
    """
    client, fields, transport = client_for("not_json_twice")
    response = client.classify(fields, batch=40)

    assert response.attempts == MAX_ATTEMPTS
    assert len(transport.requests) == MAX_ATTEMPTS, "no third attempt"
    assert response.failure_reason is not None
    assert "not valid JSON" in response.failure_reason

    assert len(response.labels) == len(fields), "every field is still in the denominator"
    assert set(response.unresolved) == {field.selector for field in fields}
    assert all(label == Label.UNKNOWN.value for label in response.labels.values())
    assert all(confidence == 0.0 for confidence in response.confidences.values())
    assert not response.compliant


def test_a_json_array_is_a_parse_failure_because_nothing_in_it_is_an_answer() -> None:
    client, fields, _ = client_for("not_an_object")
    response = client.classify(fields, batch=40)

    assert response.attempts == 2
    assert response.compliant, "the retry recovered it"


def test_a_code_fence_is_unwrapped_without_spending_an_attempt() -> None:
    client, fields, transport = client_for("fenced_json")
    response = client.classify(fields, batch=40)

    assert response.attempts == 1
    assert len(transport.requests) == 1
    assert response.compliant


# ---------------------------------------------------------------------------
# Semantic failure and the semantic retry (spec section 12.3 points 2 to 4).
# ---------------------------------------------------------------------------


def test_a_missing_selector_is_retried_with_that_selector_named() -> None:
    client, fields, transport = client_for("missing_selector_then_valid")
    response = client.classify(fields, batch=40)

    assert response.attempts == 2
    assert response.compliant

    retry = transport.requests[1]["messages"][-1]["content"]
    assert "You omitted 1 selector" in retry
    assert fields[2].selector in retry, "the retry names the specific selector, not just a count"


def test_a_selector_missing_twice_costs_that_field_and_no_other() -> None:
    client, fields, _ = client_for("missing_selector_twice")
    response = client.classify(fields, batch=40)

    assert response.attempts == MAX_ATTEMPTS
    assert response.unresolved == (fields[2].selector,)
    assert response.labels[fields[2].selector] == Label.UNKNOWN.value
    assert response.labels[fields[0].selector] == Label.GIVEN_NAME.value
    assert response.labels[fields[1].selector] == Label.POSTAL_CODE.value
    assert len(response.labels) == len(fields)


def test_an_invented_selector_is_dropped_and_named_in_the_retry() -> None:
    client, fields, transport = client_for("invented_selector")
    response = client.classify(fields, batch=40)

    assert response.attempts == 2
    assert response.compliant
    assert set(response.labels) == {field.selector for field in fields}

    retry = transport.requests[1]["messages"][-1]["content"]
    assert "You invented 1 selector" in retry
    assert "#f9" in retry


def test_a_label_outside_the_taxonomy_leaves_the_field_unanswered() -> None:
    """Ground rule 6 at the boundary: a server that ignores the enum does not
    get to extend the taxonomy."""
    client, fields, transport = client_for("label_outside_taxonomy")
    response = client.classify(fields, batch=40)

    assert response.attempts == 2
    assert response.compliant
    assert "shipping-address-line-1" not in response.labels.values()

    retry = transport.requests[1]["messages"][-1]["content"]
    assert fields[2].selector in retry


def test_a_duplicated_selector_keeps_the_first_answer_and_names_the_repeat() -> None:
    client, fields, transport = client_for("duplicate_selector")
    response = client.classify(fields, batch=40)

    assert response.labels[fields[0].selector] == Label.GIVEN_NAME.value
    retry = transport.requests[1]["messages"][-1]["content"]
    assert "invented" in retry


# ---------------------------------------------------------------------------
# Confidence, tokens, and cost.
# ---------------------------------------------------------------------------


def test_confidences_are_clamped_and_a_missing_one_defaults_without_losing_the_label() -> None:
    client, fields, _ = client_for("confidence_out_of_range")
    response = client.classify(fields, batch=40)

    assert response.compliant, "a self-reported number that decides nothing cannot cost a label"
    assert response.confidences[fields[0].selector] == 1.0
    assert response.confidences[fields[1].selector] == 0.0
    assert response.confidences[fields[2].selector] == 0.0


def test_absent_token_counts_are_recorded_as_absent_rather_than_as_zero() -> None:
    client, fields, _ = client_for("no_usage_block")
    response = client.classify(fields, batch=40)

    assert response.prompt_tokens is None
    assert response.completion_tokens is None


def test_a_local_call_records_no_cost_rather_than_a_cost_of_zero(compliant) -> None:
    """Spec section 12.4: zero is a measurement and the electricity was not free."""
    client, fields, _ = compliant
    response = client.classify(fields, batch=40)

    assert response.estimated_cost_usd_list_price is None
    assert client.accounting.estimated_cost_usd_list_price is None
    assert client.accounting.to_json()["estimated_cost_usd_list_price"] is None


def test_the_cloud_client_labels_its_cost_as_an_estimated_list_price() -> None:
    document = json.loads(
        (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "fixtures"
            / "llm"
            / "compliant.json"
        ).read_text(encoding="utf-8")
    )
    transport = RecordedTransport(list(document["responses"]))
    client = CloudClient(
        LLMConfig(endpoint="https://example.invalid/v1"),
        transport,
        price_per_million_input=3.0,
        price_per_million_output=15.0,
    )
    response = client.classify(descriptors_for(document["selectors"]), batch=40)

    # 640 prompt tokens at 3.00 and 96 completion tokens at 15.00 per million.
    assert response.estimated_cost_usd_list_price == pytest.approx((640 * 3.0 + 96 * 15.0) / 1e6)
    assert client.describe()["cost_basis"] == "estimated list price, never observed spend"
    assert client.describe()["price_table"].endswith("llm-price-table.md")


def test_the_cloud_client_records_no_cost_when_no_price_table_is_configured() -> None:
    document = json.loads(
        (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "fixtures"
            / "llm"
            / "compliant.json"
        ).read_text(encoding="utf-8")
    )
    transport = RecordedTransport(list(document["responses"]))
    client = CloudClient(LLMConfig(endpoint="https://example.invalid/v1"), transport)
    response = client.classify(descriptors_for(document["selectors"]), batch=40)

    assert response.estimated_cost_usd_list_price is None


# ---------------------------------------------------------------------------
# The accounting that goes in the manifest.
# ---------------------------------------------------------------------------


def test_the_accounting_counts_retries_and_failures_even_when_they_are_zero(compliant) -> None:
    client, fields, _ = compliant
    client.classify(fields, batch=40)

    block = client.accounting.to_json()
    assert block["calls"] == 1
    assert block["attempts"] == 1
    assert block["retried_calls"] == 0
    assert block["failed_calls"] == 0
    assert block["retry_rate"] == 0.0, "reported as zero rather than omitted"
    assert block["failure_rate"] == 0.0
    assert block["unresolved_fields_scored_unknown"] == 0
    assert block["prompt_tokens"] == 640
    assert block["completion_tokens"] == 96


def test_the_accounting_counts_a_failed_call_and_the_fields_it_cost() -> None:
    client, fields, _ = client_for("not_json_twice")
    client.classify(fields, batch=40)

    block = client.accounting.to_json()
    assert block["calls"] == 1
    assert block["attempts"] == 2
    assert block["retried_calls"] == 1
    assert block["failed_calls"] == 1
    assert block["failure_rate"] == 1.0
    assert block["unresolved_fields_scored_unknown"] == len(fields)
    assert block["failure_reasons"], "the reason is logged, not just the count"


def test_the_accounting_records_the_batch_sizes_spec_12_3_asks_be_recorded(compliant) -> None:
    client, fields, _ = compliant
    client.classify(fields, batch=40)

    block = client.accounting.to_json()
    assert block["batch_size_min"] == len(fields)
    assert block["batch_size_max"] == len(fields)


# ---------------------------------------------------------------------------
# Guards.
# ---------------------------------------------------------------------------


def test_classify_refuses_an_empty_batch(compliant) -> None:
    client, _, _ = compliant
    with pytest.raises(LLMError, match="no fields"):
        client.classify([], batch=40)


def test_classify_refuses_more_fields_than_the_cap_because_chunking_is_the_callers_job(
    compliant,
) -> None:
    client, fields, _ = compliant
    with pytest.raises(LLMError, match="batch cap"):
        client.classify(fields, batch=1)


def test_a_batch_below_one_is_refused() -> None:
    with pytest.raises(LLMError, match="at least one field"):
        LLMConfig(batch=0)


def test_the_transcript_refuses_a_third_attempt() -> None:
    """The fake is the guard: a client that retried twice would ask for a fourth
    response and the transcript would say so by name."""
    transport = RecordedTransport([])
    client = OllamaClient(LLMConfig(), transport)
    with pytest.raises(LLMError, match="at most 2 attempts"):
        client.classify(descriptors_for(["#a"]), batch=40)


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("mistral-nemo:12b-instruct-2407-q4_K_M", "q4_K_M"),
        ("gemma3:12b-it-q4_0", "q4_0"),
        ("something:12b-fp16", "fp16"),
        ("plain", "unstated in the tag"),
        ("model:latest", "unstated in the tag"),
    ],
)
def test_the_quantization_is_read_from_the_tag_or_said_to_be_unstated(
    tag: str, expected: str
) -> None:
    assert quantization_of(tag) == expected


def test_describe_names_the_model_the_endpoint_and_the_determinism_caveat(compliant) -> None:
    client, _, _ = compliant
    described = client.describe()

    assert described["model_tag"] == "mistral-nemo:12b-instruct-2407-q4_K_M"
    assert described["quantization"] == "q4_K_M"
    assert described["prompt_version"] == prompts.PROMPT_VERSION
    assert "not guaranteed" in described["determinism"]
    assert described["transport"] == "recorded transcript"
