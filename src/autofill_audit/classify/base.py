"""The ``Classifier`` protocol, the one interface every engine implements.

Keeping this a protocol rather than a base class is what lets the rule table,
the ONNX session, and the LLM client be genuinely interchangeable: nothing
downstream imports an engine, and nothing downstream knows which one ran except
through ``Prediction.engine`` and ``describe()`` (spec section 10).

``describe()`` is not decoration. It returns the engine's identity, and the run
log and the JSON report copy it verbatim, because law 3 has to be able to answer
"which exact artefact produced this number" and asking the artefact is more
reliable than remembering.

Confidence tiers, and why they live here
----------------------------------------

The rule baseline has no probabilities. It has three ordered tiers (spec section
10.1): ``HIGH`` when an intrinsic or a label match fires, ``MEDIUM`` when only
identifier, placeholder, or option-shape tokens fire, ``LOW`` when only context
fires. The numeric values behind those tiers are ``TIER_CONFIDENCE`` below, and
they are stated once, here, with the plain warning attached that **they are not
probabilities and they are not calibrated**.

They are nonetheless floats in the unit interval rather than the ordinals 1, 2
and 3, and that choice is deliberate. ``Prediction.confidence`` is one field
shared by every engine, and P4 puts a calibrated probability in it. A rule engine
that wrote 3.0 into the same field would make the run log carry two incompatible
scales under one name, and every consumer would need to know which engine wrote
the row before it could read it. Floats in one range keep the schema honest; the
``confidence_kind`` key of ``describe()`` is what tells a renderer that these
particular floats must be shown as tiers and never as percentages.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

from autofill_audit.descriptors import FieldDescriptor, Prediction

__all__ = [
    "CONFIDENCE_KIND_KEY",
    "CONFIDENCE_KIND_PROBABILITY",
    "CONFIDENCE_KIND_TIER",
    "TIER_CONFIDENCE",
    "TIER_ORDER",
    "Classifier",
    "ConfidenceTier",
    "tier_for_confidence",
]


class ConfidenceTier(StrEnum):
    """The rule baseline's ordered confidence tiers (spec section 10.1).

    ``NONE`` is not one of the specification's three. It is the tier of the
    default branch, and it exists so that "the rule table had nothing to say" is
    a value rather than the absence of one. Law 1 forbids a default branch
    becoming a confident answer, and naming the tier is how that is enforced by
    construction instead of by remembering.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


TIER_ORDER: Final[tuple[ConfidenceTier, ...]] = (
    ConfidenceTier.HIGH,
    ConfidenceTier.MEDIUM,
    ConfidenceTier.LOW,
    ConfidenceTier.NONE,
)
"""Strongest first. Fixed so a report row order never depends on set iteration."""

TIER_CONFIDENCE: Final[dict[ConfidenceTier, float]] = {
    ConfidenceTier.HIGH: 0.90,
    ConfidenceTier.MEDIUM: 0.70,
    ConfidenceTier.LOW: 0.40,
    ConfidenceTier.NONE: 0.0,
}
"""The numbers behind the tiers, in one place, and the warning that goes with them.

**These are not probabilities. They are not calibrated. They are not measured.**
They are four ordered placeholders whose only meaningful property is their order,
and the only arithmetic anything may do with them is comparison against the two
thresholds of spec section 11.3. Printing one of them as a percentage would
assert a frequency nothing in this project has observed, which is a law 1 and a
law 4 violation in a single number, so the renderers show the tier name and
``describe()`` tells them to.

The gaps between the values carry no information either. They are wide enough
that a threshold can sit between two tiers without floating-point comparison
being interesting, and that is the whole of the reasoning."""

CONFIDENCE_KIND_KEY: Final[str] = "confidence_kind"
"""The ``describe()`` key a renderer reads before formatting a confidence."""

CONFIDENCE_KIND_TIER: Final[str] = "tier"
"""``describe()[CONFIDENCE_KIND_KEY]`` for an engine whose confidences are the
ordered tiers above and must be displayed by name."""

CONFIDENCE_KIND_PROBABILITY: Final[str] = "calibrated-probability"
"""What a P4 engine reports once its outputs have been calibrated on the dev
split. Named here rather than at P4 so that the renderer's branch has both arms
written down at the point the branch is introduced."""


def tier_for_confidence(confidence: float) -> ConfidenceTier:
    """Return the tier whose value ``confidence`` carries.

    The inverse of ``TIER_CONFIDENCE``, for a renderer holding a ``Prediction``
    that a tiered engine produced. A value that is not one of the four is
    reported as the highest tier it reaches, so an engine that later interpolated
    between tiers would degrade to an understatement rather than to a crash.
    """
    for tier in TIER_ORDER:
        if confidence >= TIER_CONFIDENCE[tier]:
            return tier
    return ConfidenceTier.NONE


@runtime_checkable
class Classifier(Protocol):
    """One engine's contract (spec section 10).

    ``runtime_checkable`` so that a test can assert an engine satisfies the
    protocol without instantiating the whole ladder. The check is structural and
    shallow, which is exactly what is wanted here: the point is to catch a
    renamed method, not to re-type-check the implementation.
    """

    name: str

    def predict(self, fields: Sequence[FieldDescriptor]) -> list[Prediction]:
        """Return one prediction per descriptor, in the order given."""
        ...

    def describe(self) -> dict[str, str]:
        """Return the engine's identity, copied verbatim into the run manifest."""
        ...


assert set(TIER_CONFIDENCE) == set(ConfidenceTier), "every tier needs a value"
assert set(TIER_ORDER) == set(ConfidenceTier), "the tier order must name every tier"
assert list(TIER_CONFIDENCE.values()) == sorted(TIER_CONFIDENCE.values(), reverse=True), (
    "TIER_ORDER and TIER_CONFIDENCE must agree that HIGH is the strongest tier"
)
