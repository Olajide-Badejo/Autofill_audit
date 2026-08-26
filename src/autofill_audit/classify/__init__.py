"""The classifier ladder: rules, n-gram ONNX, LLM, and later a transformer.

Every engine behind this package sees a field descriptor and nothing else: never
the DOM, never the answer key (spec section 5.1).

``load_engine`` is the ladder's one entry point and the place the fallback of
spec section 10.1 lives. ``auto`` means the strongest engine that actually loads,
and when a stronger one does not load the caller is told **in one clear line**
and the run continues on the rule baseline. A tool that refuses to run because a
model file is absent is worse than a tool that runs with a weaker classifier and
says so.

At P6 the ladder has three rungs and every name in ``EngineChoice`` loads
something. The language-model rung is the only one whose prerequisites live
outside this repository, so it is the only one that can fail for a reason a user
can fix by starting a service, and ``check_llm_prerequisites`` exists so that the
three ways it can be missing get three different sentences rather than one
"unavailable".

**Naming an engine explicitly never falls back.** ``--engine ngram`` with no
model is an error and exit code 2, because an engine that silently became a
different one would make a three-way benchmark report two engines under three
names, which is the failure spec section 14 has ``bench`` fail fast about.
``auto`` is the only choice that substitutes, and it says which engine it ended
up with and why.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from autofill_audit.classify.base import Classifier
from autofill_audit.classify.onnx_model import (
    ENGINE_NAME as NGRAM_ENGINE_NAME,
)
from autofill_audit.classify.onnx_model import (
    ModelLoadError,
    load_ngram_engine,
)
from autofill_audit.classify.rules import ENGINE_NAME, RuleClassifier

__all__ = [
    "EngineChoice",
    "EngineLoad",
    "UnavailableEngineError",
    "check_llm_prerequisites",
    "load_engine",
]


class EngineChoice(StrEnum):
    """The values ``--engine`` accepts (spec section 14)."""

    AUTO = "auto"
    RULES = ENGINE_NAME
    NGRAM = NGRAM_ENGINE_NAME
    LLM = "llm"


class UnavailableEngineError(RuntimeError):
    """An engine was asked for by name and cannot run.

    Distinct from a fallback. ``auto`` falls back and says so; naming an engine
    explicitly and having it silently become a different one would make a
    benchmark comparing three engines report two under three names, which is the
    failure spec section 14 has ``bench`` fail fast about.
    """


_PENDING: Final[dict[EngineChoice, str]] = {}
"""Engines that have a name and no implementation yet, each naming its phase.

Empty since P6. It is kept rather than deleted because the assertion at the foot
of this module reads it, and that assertion is what makes adding a name to
``EngineChoice`` without implementing it a build failure rather than a
``KeyError`` in front of a user."""

_AUTO_NOTICE: Final[str] = (
    "the n-gram model did not load, so this run used the rule baseline. "
    "That is the documented fallback, not an error."
)
"""The one line ``auto`` prints when it falls back (spec section 10.1).

The wording changed at P4, from "no trained model is installed" to this. A model
that is present and unreadable is a different fact from a model that is absent,
and the old sentence would have been false in exactly the case a user most needs
to be told the truth about. The reason follows this line, so the user gets both
the consequence and the cause."""


@dataclass(frozen=True, slots=True)
class EngineLoad:
    """A loaded engine and whatever the caller has to be told about it."""

    classifier: Classifier
    notice: str | None = None


def load_engine(
    choice: EngineChoice,
    *,
    model_dir: Path | None = None,
    llm_config: object | None = None,
) -> EngineLoad:
    """Return the engine for ``choice``, with any notice the user must see.

    ``model_dir`` is for a caller that knows where the bundle is, which in
    practice is a test. Left alone, the search of
    ``classify.onnx_model.find_model_dir`` applies.

    ``llm_config`` is an ``autofill_audit.llm.client.LLMConfig`` and is typed as
    ``object`` here on purpose. This module is imported by the audit path, which
    ground rule 11 forbids from requiring the research layer, and an annotation
    naming that type would make the import unconditional at module scope. It is
    checked at the point of use, where the module is already being imported.

    Raises:
        UnavailableEngineError: the engine was named explicitly and cannot run.
    """
    if choice is EngineChoice.RULES:
        return EngineLoad(classifier=RuleClassifier())
    if choice is EngineChoice.NGRAM:
        try:
            return EngineLoad(classifier=load_ngram_engine(model_dir))
        except ModelLoadError as error:
            raise UnavailableEngineError(f"--engine {choice.value}: {error}") from error
    if choice is EngineChoice.LLM:
        return EngineLoad(classifier=_load_llm_engine(llm_config))
    if choice is EngineChoice.AUTO:
        try:
            return EngineLoad(classifier=load_ngram_engine(model_dir))
        except ModelLoadError as error:
            return EngineLoad(classifier=RuleClassifier(), notice=f"{_AUTO_NOTICE} {error}")
    raise UnavailableEngineError(f"--engine {choice.value}: {_PENDING[choice]}")


def _load_llm_engine(llm_config: object | None) -> Classifier:
    """Build the language-model engine, failing fast on a missing prerequisite.

    Spec section 14 requires ``bench`` to fail fast with a clear message when an
    engine's prerequisite is missing, "rather than silently benchmarking three
    engines and reporting two". For this engine the prerequisites are three, and
    each gets its own sentence because the fixes are different: the optional
    dependency, a reachable server, and the model tag being present on it.

    The imports are function-local because ground rule 11 forbids the audit path
    from requiring the research layer, and a module-scope import here would put
    the LLM modules in the import graph of every ``autofill-audit audit`` run.
    """
    from autofill_audit.classify.llm import LLMClassifier
    from autofill_audit.llm.client import LLMConfig, OllamaClient

    if llm_config is None:
        config = LLMConfig()
    elif isinstance(llm_config, LLMConfig):
        config = llm_config
    else:
        raise UnavailableEngineError(
            f"--engine llm: the configuration must be an LLMConfig, got {type(llm_config).__name__}"
        )

    check_llm_prerequisites(config)
    return LLMClassifier(OllamaClient(config), batch=config.batch)


def check_llm_prerequisites(config: object) -> None:
    """Raise ``UnavailableEngineError`` unless the server is up and has the model.

    Separate from the loader so that ``bench`` can check every engine's
    prerequisites **before the first page loads**, which is what "fails fast"
    has to mean for a command whose first engine may run for an hour before the
    third one discovers it cannot start.
    """
    from autofill_audit.llm.client import LLMConfig

    if not isinstance(config, LLMConfig):  # pragma: no cover - guarded by the caller
        raise UnavailableEngineError("the llm configuration must be an LLMConfig")

    try:
        import httpx
    except ImportError as error:
        raise UnavailableEngineError(
            "--engine llm needs httpx, which is in the optional 'llm' extra. Install it "
            "with: pip install 'autofill-audit[llm]'. The audit path never needs it."
        ) from error

    base = config.endpoint.rstrip("/").removesuffix("/v1")
    try:
        tags = httpx.get(f"{base}/api/tags", timeout=10.0)
    except httpx.HTTPError as error:
        raise UnavailableEngineError(
            f"--engine llm: no server answered at {config.endpoint} ({error}). Start one "
            "with: ollama serve. The language model is a research comparison and is never "
            "required for an audit."
        ) from error
    if tags.status_code != 200:
        raise UnavailableEngineError(
            f"--engine llm: {base}/api/tags returned {tags.status_code}, so the server is "
            "answering but is not an Ollama the model list can be read from."
        )

    payload = tags.json()
    models = payload.get("models", []) if isinstance(payload, dict) else []
    available = sorted(str(entry.get("name", "")) for entry in models if isinstance(entry, dict))
    if config.model_tag not in available:
        listed = ", ".join(available) or "nothing"
        raise UnavailableEngineError(
            f"--engine llm: {config.model_tag} is not on the server at {config.endpoint}. "
            f"It has: {listed}. Pull it with: ollama pull {config.model_tag}."
        )


assert set(_PENDING) | {
    EngineChoice.AUTO,
    EngineChoice.RULES,
    EngineChoice.NGRAM,
    EngineChoice.LLM,
} == set(EngineChoice), "every engine choice must either load or say which phase implements it"
