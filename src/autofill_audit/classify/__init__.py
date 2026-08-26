"""The classifier ladder: rules, n-gram ONNX, LLM, and later a transformer.

Every engine behind this package sees a field descriptor and nothing else: never
the DOM, never the answer key (spec section 5.1).

``load_engine`` is the ladder's one entry point and the place the fallback of
spec section 10.1 lives. ``auto`` means the strongest engine that actually loads,
and when a stronger one does not load the caller is told **in one clear line**
and the run continues on the rule baseline. A tool that refuses to run because a
model file is absent is worse than a tool that runs with a weaker classifier and
says so.

At P4 the ladder has two rungs. The remaining name is accepted and refused with
the phase that will implement it, rather than rejected as an unknown value,
because a user who typed ``--engine llm`` has asked a reasonable question and
deserves an answer rather than a usage error.

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


_PENDING: Final[dict[EngineChoice, str]] = {
    EngineChoice.LLM: (
        "the local language model engine arrives at phase P6; it is a research "
        "comparison and is never required for an audit"
    ),
}
"""Engines that have a name and no implementation yet, each naming its phase."""

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


def load_engine(choice: EngineChoice, *, model_dir: Path | None = None) -> EngineLoad:
    """Return the engine for ``choice``, with any notice the user must see.

    ``model_dir`` is for a caller that knows where the bundle is, which in
    practice is a test. Left alone, the search of
    ``classify.onnx_model.find_model_dir`` applies.

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
    if choice is EngineChoice.AUTO:
        try:
            return EngineLoad(classifier=load_ngram_engine(model_dir))
        except ModelLoadError as error:
            return EngineLoad(classifier=RuleClassifier(), notice=f"{_AUTO_NOTICE} {error}")
    raise UnavailableEngineError(f"--engine {choice.value}: {_PENDING[choice]}")


assert set(_PENDING) | {
    EngineChoice.AUTO,
    EngineChoice.RULES,
    EngineChoice.NGRAM,
} == set(EngineChoice), "every engine choice must either load or say which phase implements it"
