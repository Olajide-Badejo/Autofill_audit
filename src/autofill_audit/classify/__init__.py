"""The classifier ladder: rules, n-gram ONNX, LLM, and later a transformer.

Every engine behind this package sees a field descriptor and nothing else: never
the DOM, never the answer key (spec section 5.1).

``load_engine`` is the ladder's one entry point and the place the fallback of
spec section 10.1 lives. ``auto`` means the strongest engine that actually loads,
and when a stronger one does not load the caller is told **in one clear line**
and the run continues on the rule baseline. A tool that refuses to run because a
model file is absent is worse than a tool that runs with a weaker classifier and
says so.

At P3 the ladder has one rung. The other three names are accepted and refused
with the phase that will implement them, rather than rejected as unknown values,
because a user who typed ``--engine ngram`` has asked a reasonable question and
deserves an answer rather than a usage error.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from autofill_audit.classify.base import Classifier
from autofill_audit.classify.rules import ENGINE_NAME, RuleClassifier

__all__ = ["EngineChoice", "EngineLoad", "UnavailableEngineError", "load_engine"]


class EngineChoice(StrEnum):
    """The values ``--engine`` accepts (spec section 14)."""

    AUTO = "auto"
    RULES = ENGINE_NAME
    NGRAM = "ngram"
    LLM = "llm"


class UnavailableEngineError(RuntimeError):
    """An engine was asked for by name and cannot run.

    Distinct from a fallback. ``auto`` falls back and says so; naming an engine
    explicitly and having it silently become a different one would make a
    benchmark comparing three engines report two under three names, which is the
    failure spec section 14 has ``bench`` fail fast about.
    """


_PENDING: Final[dict[EngineChoice, str]] = {
    EngineChoice.NGRAM: (
        "the n-gram engine arrives at phase P4, together with its calibration and its ONNX export"
    ),
    EngineChoice.LLM: (
        "the local language model engine arrives at phase P6; it is a research "
        "comparison and is never required for an audit"
    ),
}
"""Engines that have a name and no implementation yet, each naming its phase."""

_AUTO_NOTICE: Final[str] = (
    "no trained model is installed, so this run used the rule baseline. "
    "That is the documented fallback, not an error."
)
"""The one line ``auto`` prints when it falls back (spec section 10.1)."""


@dataclass(frozen=True, slots=True)
class EngineLoad:
    """A loaded engine and whatever the caller has to be told about it."""

    classifier: Classifier
    notice: str | None = None


def load_engine(choice: EngineChoice) -> EngineLoad:
    """Return the engine for ``choice``, with any notice the user must see.

    Raises:
        UnavailableEngineError: the engine was named explicitly and cannot run.
    """
    if choice is EngineChoice.RULES:
        return EngineLoad(classifier=RuleClassifier())
    if choice is EngineChoice.AUTO:
        return EngineLoad(classifier=RuleClassifier(), notice=_AUTO_NOTICE)
    raise UnavailableEngineError(f"--engine {choice.value}: {_PENDING[choice]}")


assert set(_PENDING) | {EngineChoice.AUTO, EngineChoice.RULES} == set(EngineChoice), (
    "every engine choice must either load or say which phase implements it"
)
