"""The LLM-backed classifier used in research mode.

Wraps an ``LLMClient`` and is never required to run the tool, the test suite, or
CI (ground rule 11). Spec section 12.

What this module adds on top of the client
------------------------------------------

The client owns one call: prompt, schema, retry ladder, failure accounting. This
module owns the mapping between a page and a sequence of calls, which is three
decisions the client cannot make because it does not see the page.

**Chunking.** Spec section 12.3 point 6 prefers one request per page and caps a
request at a configured number of fields. A page under the cap is one request; a
page over it is split into consecutive chunks in document order, so a split page
still gives each chunk its neighbours rather than a random sample of the form.

**Latency.** ``Prediction.latency_us`` is per field, and for a batching engine it
is the batch's elapsed time divided by the field count rather than a per-field
measurement. That is the convention ``classify/onnx_model.py`` already uses and
the sentence has to travel with the number: batching amortises the round trip, so
a per-field figure derived from a batch is not comparable against one derived
from per-call timing. The model card says it and the report says it.

**Confidence.** ``describe()`` reports ``self-reported``, which
``evaluate/runlog.py`` maps to the schema's ``self_reported`` and which
``audit/engine.py`` formats with its own arm rather than as a bare percentage.
Spec section 12.1 is explicit that the number correlates with nothing in
particular; it is logged because comparing it against a calibrated probability is
interesting, and it decides nothing.

Why every field gets a prediction, including the ones the model lost
--------------------------------------------------------------------

Spec section 12.3 point 4 forbids dropping a field the model failed to answer.
The client has already turned those into ``UNKNOWN`` and named them; this module
carries them through as predictions with a signal saying so, so that they reach
the run log, stay in the denominator, and appear in the abstention rate as what
they are. Quietly excluding them is named in the specification as the single most
common way an LLM benchmark flatters its subject.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from autofill_audit import __version__
from autofill_audit.classify.base import CONFIDENCE_KIND_KEY, CONFIDENCE_KIND_SELF_REPORTED
from autofill_audit.descriptors import FieldDescriptor, Prediction
from autofill_audit.llm import prompts
from autofill_audit.llm.client import DEFAULT_BATCH, CallAccounting, LLMClient
from autofill_audit.taxonomy import Label

__all__ = [
    "ENGINE_NAME",
    "LLMClassifier",
]

ENGINE_NAME: Final[str] = "llm"
"""What this engine calls itself, and what lands in the run log's ``engine``
column.

The model tag does **not** go here. P5's handoff settled it: the engine's own
name is what the column carries, and putting the tag in the name would make every
model tag a new engine in the headline grid. The tag lives in
``engine_describe``, where spec section 13.1 puts an engine's identity, and the
headline table reads it from there so a row can still say which model ran."""

_SELF_REPORTED_SIGNAL: Final[str] = "llm:self-reported-confidence"
"""On every prediction. A renderer that dropped the ``confidence_kind`` key would
still have this on the row, and a reader of a run log sees on the field itself
that the number beside it is the model's own claim."""

_SCHEMA_FAILURE_SIGNAL: Final[str] = "llm:schema-failure-scored-unknown"
"""On a field the model never validly answered (spec section 12.3 point 4)."""

_MODEL_REASON_PREFIX: Final[str] = "llm:model-stated-reason:"
"""Prefix for the model's own one-line justification.

Prefixed rather than bare because a finding's ``signals`` are evidence, and a
sentence the model wrote about its own answer is not evidence, it is a claim.
The prefix is what keeps the two distinguishable in a report that shows both."""


class LLMClassifier:
    """A ``Classifier`` backed by an ``LLMClient`` (spec sections 10 and 12).

    Satisfies the ``Classifier`` protocol structurally rather than by
    inheritance, like every other engine in this package: nothing downstream
    imports an engine, and nothing downstream knows which one ran except through
    ``Prediction.engine`` and ``describe()``.
    """

    name: str = ENGINE_NAME

    def __init__(self, client: LLMClient, *, batch: int = DEFAULT_BATCH) -> None:
        if batch < 1:
            raise ValueError(f"batch must be at least one field per request, got {batch}")
        self._client = client
        self._batch = batch

    @property
    def accounting(self) -> CallAccounting:
        """The client's running totals, for the run manifest."""
        return self._client.accounting

    @property
    def batch(self) -> int:
        """The configured cap on fields per request."""
        return self._batch

    def describe(self) -> dict[str, str]:
        """The engine identity the run log and the report copy verbatim.

        ``confidence_kind`` is the load-bearing key, as it is for every engine.
        Here it tells the renderer that the float beside a finding is a number
        the model made up about itself, and ``audit/engine.py`` has an arm that
        prints it as such rather than as a percentage.
        """
        described: dict[str, str] = {
            "engine": ENGINE_NAME,
            "tool_version": __version__,
            "prompt_version": prompts.PROMPT_VERSION,
            "batch_cap": str(self._batch),
            CONFIDENCE_KIND_KEY: CONFIDENCE_KIND_SELF_REPORTED,
            "confidence_note": (
                "self-reported by the model and not calibrated against anything. Spec "
                "section 12.1: it never feeds the threshold policy of spec section 11.3."
            ),
            "latency_note": (
                "latency_us per field is a batch's elapsed time divided by its field "
                "count, not a per-field measurement. Batching amortises the round trip."
            ),
        }
        described.update(self._client.describe())
        described["engine"] = ENGINE_NAME
        return described

    def predict(self, fields: Sequence[FieldDescriptor]) -> list[Prediction]:
        """Return one prediction per descriptor, in the order given.

        One request per chunk of at most ``batch`` descriptors, in document
        order. Every descriptor gets a prediction, including one the model failed
        to answer after its retry: that becomes ``UNKNOWN`` with the
        schema-failure signal on it, which is what keeps it in the denominator.
        """
        predictions: list[Prediction] = []
        for start in range(0, len(fields), self._batch):
            chunk = list(fields[start : start + self._batch])
            response = self._client.classify(chunk, batch=self._batch)
            per_field_us = (response.latency_ms * 1000.0) / len(chunk)
            for descriptor in chunk:
                selector = descriptor.selector
                label = response.labels.get(selector, Label.UNKNOWN.value)
                confidence = response.confidences.get(selector, 0.0)
                signals = [_SELF_REPORTED_SIGNAL, f"llm:attempts={response.attempts}"]
                if selector in response.unresolved:
                    signals.append(_SCHEMA_FAILURE_SIGNAL)
                reason = response.reasons.get(selector)
                if reason:
                    signals.append(f"{_MODEL_REASON_PREFIX}{reason}")
                predictions.append(
                    Prediction(
                        selector=selector,
                        label=label,
                        confidence=confidence,
                        engine=ENGINE_NAME,
                        signals=tuple(signals),
                        # No runner up. The schema of spec section 12.2 asks for
                        # one label per field, so there is no second choice to
                        # report, and inventing one from the confidence would be
                        # inventing a number.
                        runner_up=None,
                        latency_us=per_field_us,
                    )
                )
        return predictions
