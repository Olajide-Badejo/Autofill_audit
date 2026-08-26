"""The ``LLMClient`` interface, a local Ollama client, and a config-swap cloud client.

Spec section 12.1. One interface in front of every backend, so that changing
model or host is configuration rather than a refactor.

The transport seam, and what it buys
------------------------------------

``OllamaClient`` does not call the network. It calls a ``Transport``, which is a
one-method object that takes a request document and returns a response document.
``HttpxTransport`` is the real one; ``RecordedTransport`` replays committed
transcripts.

That seam is the reason spec section 15's coverage carve-out ("excluding only the
LLM client's network path") stays as small as one method. Every line of the
validation, retry and failure accounting of spec section 12.3 runs in the test
suite against recorded responses, including the deliberately malformed ones,
with no server and no network. What is uncovered is the socket call itself,
which no fake can exercise and no test should.

Attempts, and the accounting that must not flatter
--------------------------------------------------

Spec section 12.3 allows exactly two attempts per request: the first, and one
retry whose corrective message depends on how the first failed. If the second
also fails, the affected fields are scored ``UNKNOWN``, they stay in the
denominator, and the failure is recorded.

The rule for which response is used is written down here because it is a real
choice and every alternative is worse. **The response used is the last attempt
that parsed into a schema-shaped document.** Requested selectors it did not
resolve become ``UNKNOWN``; selectors it invented are dropped and named in the
failure reason. Merging a partial first attempt with a partial second would be
generous to the model in a way nothing could justify, and discarding a good first
attempt because a retry came back as prose would punish it for the same reason.

Cost, and why local is null
---------------------------

Spec section 12.4: local calls log ``None``, never ``0.0``. Zero is a
measurement and the electricity was not free; null is the absence of one. Only
the cloud client computes a number, it is a **list-price estimate** from a table
in ``docs/`` with a retrieval date, and the field is named
``estimated_cost_usd_list_price`` so that no renderer can print it as spend.
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final, Protocol

from autofill_audit.descriptors import FieldDescriptor
from autofill_audit.llm import prompts
from autofill_audit.taxonomy import ALL_LABELS, Label

__all__ = [
    "CLOUD_PRICE_TABLE",
    "DEFAULT_BATCH",
    "DEFAULT_ENDPOINT",
    "DEFAULT_MODEL_TAG",
    "MAX_ATTEMPTS",
    "AnthropicClient",
    "CallAccounting",
    "CloudClient",
    "HttpxTransport",
    "LLMClient",
    "LLMConfig",
    "LLMError",
    "LLMResponse",
    "LLMUnavailableError",
    "OllamaClient",
    "RecordedTransport",
    "Transport",
    "quantization_of",
]

DEFAULT_ENDPOINT: Final[str] = "http://127.0.0.1:11434/v1"
"""Ollama's OpenAI-compatible base, on the loopback address it binds by default."""

DEFAULT_MODEL_TAG: Final[str] = "mistral-nemo:12b-instruct-2407-q4_K_M"
"""The model ADR 0007 resolved: 12B class, 4-bit, which is what spec section 0.3
pins. The tag travels in ``describe()`` and therefore into every run manifest, so
a reader of the headline table can see which model produced which row."""

DEFAULT_BATCH: Final[int] = 40
"""Fields per request. Spec section 12.3 point 6 prefers one request per page
where it fits and asks for the value to be recorded; this is the cap above which
a page is split, and the realised distribution goes in the run manifest."""

DEFAULT_TIMEOUT_S: Final[float] = 600.0
"""Per-request budget. Generous because a cold model load from a mounted store is
tens of seconds and a timeout that fired during it would report a server problem
that is really a warm-up."""

DEFAULT_SEED: Final[int] = 20260825
"""The project seed, passed where the server honours it. Spec section 12.3 point
7 requires it to be recorded and requires the report to say that determinism is
not guaranteed even so."""

MAX_ATTEMPTS: Final[int] = 2
"""The first attempt and one retry. Spec section 12.3 point 4: do not retry a
third time. A third attempt would turn a schema-compliance measurement into a
measurement of how many tries the harness was willing to spend."""

_LABEL_VALUES: Final[frozenset[str]] = frozenset(label.value for label in ALL_LABELS)


class LLMError(RuntimeError):
    """A language-model call failed in a way the caller has to know about."""


class LLMUnavailableError(LLMError):
    """The backend is not reachable, or the model is not present on it.

    Separate from ``LLMError`` because spec section 14 requires ``bench`` to fail
    fast with a clear message when an engine's prerequisite is missing, and
    "there is no server" is a different sentence from "the server said no".
    """


def quantization_of(model_tag: str) -> str:
    """Read the quantization out of a model tag, or say it is unstated.

    Ollama tags carry it by convention (``...-q4_K_M``) rather than by rule, so
    this is a best effort over a convention and it says so when the convention
    was not followed. Spec section 3.4 requires the headline table to name the
    quantization in every row, and a row reading ``unstated in the tag`` is a
    true statement where a guess would not be.
    """
    _, _, suffix = model_tag.partition(":")
    for part in reversed(suffix.split("-")):
        lowered = part.lower()
        if lowered.startswith("q") and any(character.isdigit() for character in lowered):
            return part
        if lowered in {"fp16", "f16", "bf16", "fp32", "f32"}:
            return part
    return "unstated in the tag"


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Endpoint, model, and decoding parameters (spec section 14's config block)."""

    endpoint: str = DEFAULT_ENDPOINT
    model_tag: str = DEFAULT_MODEL_TAG
    batch: int = DEFAULT_BATCH
    timeout_s: float = DEFAULT_TIMEOUT_S
    temperature: float = 0.0
    seed: int | None = DEFAULT_SEED

    def __post_init__(self) -> None:
        if self.batch < 1:
            raise LLMError(f"batch must be at least one field per request, got {self.batch}")

    @property
    def quantization(self) -> str:
        """The quantization named in the model tag."""
        return quantization_of(self.model_tag)

    def describe(self) -> dict[str, str]:
        """The identity spec section 12.1 requires ``describe()`` to return."""
        return {
            "model_tag": self.model_tag,
            "quantization": self.quantization,
            "endpoint": self.endpoint,
            "batch": str(self.batch),
            "temperature": repr(self.temperature),
            "seed": "unset" if self.seed is None else str(self.seed),
            "determinism": (
                "not guaranteed: the server may ignore the seed and batched reductions "
                "are not order stable (spec section 12.3 point 7)"
            ),
        }


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """One call's result, at the shape of spec section 12.1.

    ``confidences`` is the model's **self-reported** number and the name says so.
    Spec section 12.1: a language model asked how sure it is produces a number
    that correlates with nothing in particular. It is logged because comparing it
    against a calibrated probability is interesting; it never feeds the threshold
    policy of spec section 11.3 and it is never rendered as a bare percentage.

    Three fields are not in the specification's sketch and each is required by
    the paragraph after it. ``failure_reason`` and ``unresolved`` carry what spec
    section 12.3 point 5 requires be logged per call; a response that recorded
    ``attempts=2`` without saying what failed would log the count of a thing it
    could not name. ``estimated_cost_usd_list_price`` is spec section 12.4's
    field, spelled as that section spells it.
    """

    labels: Mapping[str, str]
    confidences: Mapping[str, float]
    raw_text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: float
    model_tag: str
    attempts: int
    reasons: Mapping[str, str] = field(default_factory=dict)
    failure_reason: str | None = None
    unresolved: tuple[str, ...] = ()
    estimated_cost_usd_list_price: float | None = None

    @property
    def compliant(self) -> bool:
        """Whether the call ended with every requested selector answered."""
        return self.failure_reason is None and not self.unresolved


@dataclass(slots=True)
class CallAccounting:
    """What every call did, totalled for the run manifest (spec section 12.4).

    Mutable and owned by the client, because it is a running total over a run
    rather than a value passed between modules. It is read once, at the end, and
    copied into the manifest.
    """

    calls: int = 0
    attempts: int = 0
    retried_calls: int = 0
    failed_calls: int = 0
    unresolved_fields: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    batch_sizes: list[int] = field(default_factory=list)
    failure_reasons: list[str] = field(default_factory=list)
    estimated_cost_usd_list_price: float | None = None

    def record(self, response: LLMResponse, batch_size: int) -> None:
        """Fold one call into the totals."""
        self.calls += 1
        self.attempts += response.attempts
        self.batch_sizes.append(batch_size)
        if response.attempts > 1:
            self.retried_calls += 1
        if response.failure_reason is not None:
            self.failed_calls += 1
            self.failure_reasons.append(response.failure_reason)
        self.unresolved_fields += len(response.unresolved)
        self.prompt_tokens += response.prompt_tokens or 0
        self.completion_tokens += response.completion_tokens or 0
        if response.estimated_cost_usd_list_price is not None:
            self.estimated_cost_usd_list_price = (
                self.estimated_cost_usd_list_price or 0.0
            ) + response.estimated_cost_usd_list_price

    def to_json(self) -> dict[str, Any]:
        """The block the run manifest carries.

        ``retry_rate`` and ``failure_rate`` are emitted even when they are zero.
        Spec section 12.3 point 4 is explicit that quietly excluding a model's
        schema failures is how an LLM benchmark flatters its subject, and a
        block that appeared only when something went wrong would make a clean run
        and an unmeasured one look identical.
        """
        sizes = sorted(self.batch_sizes)
        return {
            "calls": self.calls,
            "attempts": self.attempts,
            "retried_calls": self.retried_calls,
            "retry_rate": (self.retried_calls / self.calls) if self.calls else None,
            "failed_calls": self.failed_calls,
            "failure_rate": (self.failed_calls / self.calls) if self.calls else None,
            "unresolved_fields_scored_unknown": self.unresolved_fields,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "batch_size_min": sizes[0] if sizes else None,
            "batch_size_max": sizes[-1] if sizes else None,
            "batch_size_median": sizes[len(sizes) // 2] if sizes else None,
            "fields_per_request_cap": None,
            "estimated_cost_usd_list_price": self.estimated_cost_usd_list_price,
            "cost_note": (
                "null for a local engine. Spec section 12.4: zero is a measurement and "
                "the electricity was not free, so the absence of a monetary cost is "
                "recorded as the absence of one."
            ),
            "failure_reasons": list(self.failure_reasons),
        }


class LLMClient(ABC):
    """One interface in front of every backend (spec section 12.1)."""

    @abstractmethod
    def classify(self, fields: Sequence[FieldDescriptor], *, batch: int) -> LLMResponse:
        """Classify one batch of descriptors, retrying per spec section 12.3."""

    @abstractmethod
    def describe(self) -> dict[str, str]:
        """Model tag, quantization, endpoint, and decoding parameters."""

    @property
    @abstractmethod
    def accounting(self) -> CallAccounting:
        """The running totals for the run manifest."""


# ---------------------------------------------------------------------------
# The transport seam.
# ---------------------------------------------------------------------------


class Transport(Protocol):
    """Takes a chat-completions request document, returns the response document."""

    def send(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Perform one request. Raises ``LLMError`` on a transport failure."""
        ...

    def describe(self) -> dict[str, str]:
        """How this transport reached the server, for the manifest."""
        ...


class HttpxTransport:
    """The real network path. The one thing spec section 15 does not cover."""

    def __init__(self, endpoint: str, timeout_s: float, api_key: str | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._timeout_s = timeout_s
        self._api_key = api_key

    def send(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:  # pragma: no cover
        """POST to ``/chat/completions`` and return the parsed response.

        Not covered by the test suite, deliberately and by the one carve-out spec
        section 15 grants. Everything it would exercise is exercised through
        ``RecordedTransport``; what is left is a socket, and a test that mocked
        the socket would be asserting that ``httpx`` works.
        """
        try:
            import httpx
        except ImportError as error:
            raise LLMUnavailableError(
                "the llm engine needs httpx, which is in the optional 'llm' extra. "
                "Install it with: pip install 'autofill-audit[llm]'. The audit path "
                "never needs it (ground rule 11)."
            ) from error

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            response = httpx.post(
                f"{self._endpoint}/chat/completions",
                json=dict(payload),
                headers=headers,
                timeout=self._timeout_s,
            )
        except httpx.HTTPError as error:
            raise LLMUnavailableError(f"{self._endpoint} could not be reached: {error}") from error
        if response.status_code != 200:
            raise LLMError(
                f"{self._endpoint} returned {response.status_code}: {response.text[:400]}"
            )
        parsed: Any = response.json()
        if not isinstance(parsed, Mapping):
            raise LLMError(f"{self._endpoint} returned a non-object response document")
        return parsed

    def describe(self) -> dict[str, str]:
        """Say that this was a live server."""
        return {"transport": "httpx", "endpoint": self._endpoint}


class RecordedTransport:
    """Replays committed transcripts, in order, with no network.

    This is what spec section 15's "fake client replaying recorded responses"
    means in practice, and it sits at the transport rather than at the client so
    that the retry and failure accounting under test is the real one rather than
    a second implementation of it.
    """

    def __init__(self, responses: Sequence[Mapping[str, Any] | Exception]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.requests: list[Mapping[str, Any]] = []

    def send(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return the next recorded response, or raise the next recorded error."""
        self.requests.append(payload)
        if self._index >= len(self._responses):
            raise LLMError(
                f"the transcript holds {len(self._responses)} response(s) and the client "
                f"asked for number {self._index + 1}. Spec section 12.3 allows at most "
                f"{MAX_ATTEMPTS} attempts per call, so a client asking for more is the "
                "defect this fake exists to catch."
            )
        recorded = self._responses[self._index]
        self._index += 1
        if isinstance(recorded, Exception):
            raise recorded
        return recorded

    def describe(self) -> dict[str, str]:
        """Say plainly that no server was involved."""
        return {"transport": "recorded transcript", "endpoint": "none, replayed offline"}


# ---------------------------------------------------------------------------
# Validation (spec section 12.3 points 1 to 4).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Parsed:
    """One attempt's response, after parsing and semantic validation."""

    labels: dict[str, str]
    confidences: dict[str, float]
    reasons: dict[str, str]
    missing: tuple[str, ...]
    extra: tuple[str, ...]
    raw_text: str

    @property
    def ok(self) -> bool:
        """Whether every requested selector was answered and none was invented."""
        return not self.missing and not self.extra


def _content_of(document: Mapping[str, Any]) -> str:
    """Pull the assistant message out of a chat-completions response."""
    choices = document.get("choices")
    if not isinstance(choices, Sequence) or not choices:
        raise LLMError("the response document carries no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise LLMError("the first choice is not an object")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise LLMError("the first choice carries no message object")
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMError("the message content is not a string")
    return content


def _usage_of(document: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """Prompt and completion token counts as reported, or None when absent."""
    usage = document.get("usage")
    if not isinstance(usage, Mapping):
        return None, None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    return (
        prompt if isinstance(prompt, int) else None,
        completion if isinstance(completion, int) else None,
    )


def _parse(content: str, requested: Sequence[str]) -> _Parsed:
    """Parse and semantically validate one attempt (spec section 12.3 points 1 and 2).

    Raises:
        LLMError: the content is not JSON, or not the shape the schema describes.
            That is the parse failure of point 1 and it takes the parse retry.
            Everything the schema does describe but the answer gets wrong is a
            semantic failure, reported on the returned object rather than raised,
            because point 3 gives it a different retry message.
    """
    stripped = content.strip()
    if stripped.startswith("```"):
        # A fenced block is a parse failure in the strict sense and a very common
        # one. Unwrapping it here rather than spending an attempt on it means the
        # retry budget is spent on answers that are wrong rather than on answers
        # that are right and wearing a code fence.
        stripped = stripped.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        document: Any = json.loads(stripped)
    except json.JSONDecodeError as error:
        raise LLMError(f"not valid JSON: {error}") from error
    if not isinstance(document, Mapping):
        raise LLMError(f"the top level must be an object, found {type(document).__name__}")
    entries = document.get("fields")
    if not isinstance(entries, Sequence) or isinstance(entries, str):
        raise LLMError("the object must carry a 'fields' array")

    wanted = list(requested)
    labels: dict[str, str] = {}
    confidences: dict[str, float] = {}
    reasons: dict[str, str] = {}
    extra: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise LLMError("every entry of 'fields' must be an object")
        selector = entry.get("selector")
        label = entry.get("label")
        if not isinstance(selector, str) or not isinstance(label, str):
            raise LLMError("every entry needs a string 'selector' and a string 'label'")
        if selector not in wanted:
            extra.append(selector)
            continue
        if selector in labels:
            # A duplicate is an extra answer, not a correction. Keeping the first
            # and naming the selector as extra is what makes the retry message
            # say something the model can act on.
            extra.append(selector)
            continue
        if label not in _LABEL_VALUES:
            # A label outside the taxonomy is a semantic failure for this field
            # rather than a parse failure for the document. Leaving the selector
            # unanswered puts it in `missing`, which is what the retry names.
            continue
        labels[selector] = label
        confidences[selector] = _confidence_of(entry)
        reason = entry.get("reason")
        if isinstance(reason, str) and reason.strip():
            reasons[selector] = reason.strip()[:120]

    missing = tuple(selector for selector in wanted if selector not in labels)
    return _Parsed(
        labels=labels,
        confidences=confidences,
        reasons=reasons,
        missing=missing,
        extra=tuple(dict.fromkeys(extra)),
        raw_text=content,
    )


def _confidence_of(entry: Mapping[str, Any]) -> float:
    """Read the self-reported confidence, clamped, defaulting to zero.

    Clamped rather than rejected: a model that answers 1.5 has still answered,
    and the number is self-reported anyway, so refusing the field over its
    confidence would discard a label because a quantity that decides nothing was
    out of range. Absent becomes 0.0 and the schema makes it required, so this is
    the branch for a server that ignored the schema.
    """
    value = entry.get("confidence")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return max(0.0, min(1.0, float(value)))


# ---------------------------------------------------------------------------
# The Ollama client.
# ---------------------------------------------------------------------------


class OllamaClient(LLMClient):
    """Ollama's OpenAI-compatible /v1 endpoint, with structured output enforced.

    The JSON schema of spec section 12.2 travels with every request, so validity
    is the server's job. The client validates anyway, because spec section 12.3
    requires it and because a server that ignores the schema is a case to survive
    rather than to assume away.
    """

    def __init__(self, config: LLMConfig | None = None, transport: Transport | None = None) -> None:
        self._config = config or LLMConfig()
        self._transport = transport or HttpxTransport(self._config.endpoint, self._config.timeout_s)
        self._accounting = CallAccounting()

    @property
    def config(self) -> LLMConfig:
        """The resolved configuration, for a caller assembling a manifest."""
        return self._config

    @property
    def accounting(self) -> CallAccounting:
        """The running totals over every call this client has made."""
        return self._accounting

    def describe(self) -> dict[str, str]:
        """Model tag, quantization, endpoint, params (spec section 12.1)."""
        described = self._config.describe()
        described.update(self._transport.describe())
        described["prompt_version"] = prompts.PROMPT_VERSION
        described["prompt_fingerprint"] = prompts.prompt_fingerprint()
        described["structured_output"] = "json_schema passed with every request"
        return described

    def _request(self, messages: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        """Assemble one chat-completions request with the schema attached."""
        payload: dict[str, Any] = {
            "model": self._config.model_tag,
            "messages": list(messages),
            "temperature": self._config.temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": prompts.SCHEMA_NAME,
                    "strict": True,
                    "schema": prompts.response_schema(),
                },
            },
        }
        if self._config.seed is not None:
            payload["seed"] = self._config.seed
        return payload

    def classify(self, fields: Sequence[FieldDescriptor], *, batch: int) -> LLMResponse:
        """Classify one batch, with the retry ladder of spec section 12.3.

        ``batch`` is the cap the caller chunked to; it is accepted so that the
        signature matches spec section 12.1 and so that the realised size reaches
        the accounting, which is what spec section 12.3 point 6 asks be recorded.
        """
        if not fields:
            raise LLMError("classify was given no fields")
        if len(fields) > batch:
            raise LLMError(
                f"classify was given {len(fields)} fields with a batch cap of {batch}. "
                "Chunking is the caller's job, so this is a defect rather than a "
                "condition to paper over."
            )

        pruned = prompts.prune_all(fields)
        prompts.assert_no_declaration_leaks(pruned, fields)
        requested = [descriptor.selector for descriptor in fields]

        messages: list[Mapping[str, str]] = [
            {"role": "system", "content": prompts.system_prompt()},
            {"role": "user", "content": prompts.user_message(pruned)},
        ]

        started = time.perf_counter()
        best: _Parsed | None = None
        failure: str | None = None
        prompt_tokens = 0
        completion_tokens = 0
        saw_usage = False
        raw_text = ""
        attempts = 0

        for attempt in range(1, MAX_ATTEMPTS + 1):
            attempts = attempt
            document = self._transport.send(self._request(messages))
            counted_prompt, counted_completion = _usage_of(document)
            if counted_prompt is not None or counted_completion is not None:
                saw_usage = True
                prompt_tokens += counted_prompt or 0
                completion_tokens += counted_completion or 0
            content = _content_of(document)
            raw_text = content

            try:
                parsed = _parse(content, requested)
            except LLMError as error:
                failure = f"attempt {attempt}: {error}"
                if attempt == MAX_ATTEMPTS:
                    break
                messages = [
                    *messages[:2],
                    {"role": "user", "content": prompts.parse_retry_message(str(error))},
                ]
                continue

            best = parsed
            if parsed.ok:
                failure = None
                break

            failure = (
                f"attempt {attempt}: {len(parsed.missing)} selector(s) missing, "
                f"{len(parsed.extra)} invented"
            )
            if attempt == MAX_ATTEMPTS:
                break
            messages = [
                *messages[:2],
                {
                    "role": "user",
                    "content": prompts.semantic_retry_message(parsed.missing, parsed.extra),
                },
            ]

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        labels = dict(best.labels) if best else {}
        confidences = dict(best.confidences) if best else {}
        reasons = dict(best.reasons) if best else {}

        # Spec section 12.3 point 4. Every requested selector the model did not
        # resolve is scored UNKNOWN. It is not dropped, it is not excluded from
        # the denominator, and it is counted here so the results table can say
        # how often it happened.
        unresolved = tuple(selector for selector in requested if selector not in labels)
        for selector in unresolved:
            labels[selector] = Label.UNKNOWN.value
            confidences[selector] = 0.0

        response = LLMResponse(
            labels=labels,
            confidences=confidences,
            raw_text=raw_text,
            prompt_tokens=prompt_tokens if saw_usage else None,
            completion_tokens=completion_tokens if saw_usage else None,
            latency_ms=elapsed_ms,
            model_tag=self._config.model_tag,
            attempts=attempts,
            reasons=reasons,
            failure_reason=failure if unresolved or failure else None,
            unresolved=unresolved,
            estimated_cost_usd_list_price=None,
        )
        self._accounting.record(response, len(fields))
        return response


# ---------------------------------------------------------------------------
# The config-swap cloud client (spec sections 3.4 and 12.1).
# ---------------------------------------------------------------------------

CLOUD_PRICE_TABLE: Final[str] = "docs/llm-price-table.md"
"""Where the list prices come from, with the retrieval date spec section 12.4
requires. A price is a fact about a vendor's web page on a day, so the table
records the day and the report says "estimated" every time it prints one."""


class CloudClient(OllamaClient):
    """A hosted API behind the same interface. Never used in CI, never required.

    Spec sections 3.4 and 12.1 require that swapping the local model for a hosted
    one be a configuration change and a different concrete class rather than a
    refactor. This is that class, and the vendor-specific subclass below it is
    six lines of configuration, which is the whole point being demonstrated.

    **Nothing here is run by the test suite against a live service, by CI, or by
    the headline benchmark.** Every row of that table is local and its cost
    column is null. What this contributes to the phase is that the seam is real
    and exercised: the tests drive this class through a recorded transport, so
    the cost arithmetic and the price labelling are covered by the same
    network-free suite as everything else.

    It extends the local client because the request shape is the same
    OpenAI-compatible one, and the only differences are the base URL, the key,
    and the price table. A second copy of the retry ladder is exactly what spec
    section 12.1's "one interface" exists to prevent.
    """

    API_KEY_ENV: str = ""
    """The environment variable the key is read from. Never a literal key, never
    a file, never a prompt: spec section 12.1 says "key from env or not at all"."""

    API_ENDPOINT: str = ""
    """The default base URL for this vendor's OpenAI-compatible surface."""

    def __init__(
        self,
        config: LLMConfig | None = None,
        transport: Transport | None = None,
        *,
        price_per_million_input: float | None = None,
        price_per_million_output: float | None = None,
    ) -> None:
        resolved = config or LLMConfig(endpoint=self.API_ENDPOINT)
        key = os.environ.get(self.API_KEY_ENV) if self.API_KEY_ENV else None
        super().__init__(
            resolved,
            transport or HttpxTransport(resolved.endpoint, resolved.timeout_s, api_key=key),
        )
        self._price_in = price_per_million_input
        self._price_out = price_per_million_output

    def describe(self) -> dict[str, str]:
        """The identity, plus where the price estimate's numbers came from."""
        described = super().describe()
        described["price_table"] = CLOUD_PRICE_TABLE
        described["cost_basis"] = "estimated list price, never observed spend"
        described["api_key_source"] = self.API_KEY_ENV or "none configured"
        return described

    def classify(self, fields: Sequence[FieldDescriptor], *, batch: int) -> LLMResponse:
        """Classify, and attach a list-price estimate when a price table was given.

        The estimate is a **list price** from a published table with a retrieval
        date, and the field it lands in is named
        ``estimated_cost_usd_list_price`` so that nothing downstream can render
        it as money that was spent. Law 4, and spec section 12.4 in as many
        words. With no prices configured the field stays ``None``, which is the
        same absence the local path records.
        """
        response = super().classify(fields, batch=batch)
        if self._price_in is None or self._price_out is None:
            return response
        prompt_tokens = response.prompt_tokens or 0
        completion_tokens = response.completion_tokens or 0
        estimate = (prompt_tokens * self._price_in + completion_tokens * self._price_out) / 1e6
        priced = replace(response, estimated_cost_usd_list_price=estimate)
        # `super().classify` already folded the unpriced response into the
        # accounting, so the estimate is added here rather than double counting
        # the call by recording the priced copy again.
        self.accounting.estimated_cost_usd_list_price = (
            self.accounting.estimated_cost_usd_list_price or 0.0
        ) + estimate
        return priced


class AnthropicClient(CloudClient):  # pragma: no cover
    """The config swap spec sections 3.4 and 12.1 name, as configuration only.

    Six lines, because that is what the seam above reduces a vendor to. It is
    never instantiated by the test suite, by CI, or by the benchmark, so it is
    excluded from coverage rather than exercised: every line of behaviour it
    would run lives in ``CloudClient`` and is covered there against recorded
    transcripts. What is here is two strings.
    """

    API_KEY_ENV = "ANTHROPIC_API_KEY"
    API_ENDPOINT = "https://api.anthropic.com/v1"
