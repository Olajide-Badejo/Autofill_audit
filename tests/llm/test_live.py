"""Live-server tests. Marked, and skipped unless the env var and a server agree.

Spec section 15: "Live-server tests exist, are marked, and are skipped unless the
env var and a reachable Ollama are both present." Spec section 16: CI "does not
call any network service other than the package index and the Playwright download
host" and does not run LLM tests.

**Both conditions, not either.** The environment variable alone is an intention;
a reachable server alone would make a developer who happens to run Ollama for
something else start paying for these tests without asking. Requiring both means
the default everywhere, including CI, is that this file contributes skips and
nothing else, and the pytest summary says so rather than saying nothing.

Run them deliberately:

    AUTOFILL_AUDIT_LLM_TESTS=1 pytest tests/llm/test_live.py -m llm

These assert on the **contract**, never on the content. A test that asserted the
model labels a field ``postal-code`` would be a test of a 12-billion-parameter
model's opinion on a Tuesday, and it would fail on a model upgrade for a reason
that is not a defect. What is asserted is what the code depends on: that the
server honours the structured-output schema, that the selectors come back
matched, and that the retry ladder is never needed for a well-formed request.
"""

from __future__ import annotations

import os

import pytest

from autofill_audit.classify import UnavailableEngineError, check_llm_prerequisites
from autofill_audit.classify.llm import LLMClassifier
from autofill_audit.llm.client import LLMConfig, OllamaClient
from autofill_audit.taxonomy import ALL_LABELS
from conftest import descriptors_for

LIVE_ENV = "AUTOFILL_AUDIT_LLM_TESTS"

pytestmark = pytest.mark.llm


def _reachable(config: LLMConfig) -> bool:
    """Whether a server is up and carries the tag, without raising."""
    try:
        check_llm_prerequisites(config)
    except UnavailableEngineError:
        return False
    return True


def _skip_reason() -> str | None:
    """Why these are being skipped, or None when they should run."""
    if os.environ.get(LIVE_ENV) != "1":
        return f"{LIVE_ENV} is not 1, so the live server is not being called"
    if not _reachable(LLMConfig()):
        return "no reachable Ollama carrying the configured tag"
    return None


live = pytest.mark.skipif(_skip_reason() is not None, reason=_skip_reason() or "")


@live
def test_the_server_honours_the_structured_output_schema() -> None:
    """The one thing the client cannot verify offline: that the server actually
    constrains its output to the schema passed with the request."""
    fields = descriptors_for(["#given", "#postal", "#search"])
    client = OllamaClient(LLMConfig())
    response = client.classify(fields, batch=40)

    assert set(response.labels) == {field.selector for field in fields}
    assert all(label in {item.value for item in ALL_LABELS} for label in response.labels.values())
    assert all(0.0 <= value <= 1.0 for value in response.confidences.values())


@live
def test_a_well_formed_request_needs_no_retry() -> None:
    """Not a guarantee, an observation, and the reason it is worth making: if a
    live run needs a retry on a three-field page, the prompt is wrong rather than
    the model being bad, and that is a defect to fix before a benchmark rather
    than a number to report."""
    fields = descriptors_for(["#given", "#postal", "#search"])
    client = OllamaClient(LLMConfig())
    response = client.classify(fields, batch=40)

    assert response.attempts == 1
    assert response.unresolved == ()


@live
def test_the_server_reports_token_counts() -> None:
    """Spec section 12.4 logs prompt and completion tokens "as reported". If the
    server reports none, the run records null and the report says the counts were
    unavailable, so this asserts which of those two worlds the benchmark ran in."""
    fields = descriptors_for(["#given"])
    client = OllamaClient(LLMConfig())
    response = client.classify(fields, batch=40)

    assert response.prompt_tokens is not None
    assert response.completion_tokens is not None


@live
def test_the_engine_predicts_one_label_per_field_through_the_classifier() -> None:
    fields = descriptors_for(["#given", "#postal"])
    engine = LLMClassifier(OllamaClient(LLMConfig()), batch=40)
    predictions = engine.predict(fields)

    assert len(predictions) == len(fields)
    assert [item.selector for item in predictions] == [field.selector for field in fields]
    assert all(item.latency_us is not None and item.latency_us > 0 for item in predictions)


@live
def test_a_local_call_has_no_cost() -> None:
    fields = descriptors_for(["#given"])
    client = OllamaClient(LLMConfig())
    client.classify(fields, batch=40)

    assert client.accounting.estimated_cost_usd_list_price is None
