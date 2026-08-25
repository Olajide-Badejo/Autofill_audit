"""The rule baseline, and the permanent fallback when no model is present.

Spec section 10.1. The table lives in ``rules_table``; this module owns the
precedence between its tiers and owns no vocabulary of its own, so adding a
language never touches this file and changing precedence never touches that one.

The procedure, in full
----------------------

For each descriptor, walk ``TIER_PRECEDENCE`` in order. At each tier, match the
rules against that tier's stream and collect, per candidate label, the highest
weight of any of its rules that matched. If exactly one label holds the maximum
weight, that tier has decided and the walk stops. Otherwise the tier has tied and
the walk continues. If every tier ties or matches nothing, the answer is
``UNKNOWN`` at confidence zero.

**The default branch can never become a confident answer** (law 1). ``UNKNOWN``
is emitted at ``ConfidenceTier.NONE``, which is below both thresholds, so the
decision procedure of spec section 11.2 treats it as "the tool has nothing to
say" rather than as a claim about the page. There is no branch here that reaches
a confident answer without a rule having matched, and the tests assert that.

Which stream belongs to which tier
----------------------------------

Five of the six read the descriptor directly. The placeholder tier is the one
that needs explaining.

``NormalizedSignals`` has no placeholder stream. The extractor puts the strongest
available label source into ``label_tokens`` and names it in ``label_source``
(spec section 9.4), so a placeholder contributes tokens exactly when it is the
strongest thing labelling the control, and contributes none at all when a real
label exists. This module therefore reads ``label_tokens`` at the ``LABEL`` tier
when ``label_source`` names a real label, and at the ``PLACEHOLDER`` tier when it
names the placeholder. That is the whole difference, and it is what keeps a
placeholder pressed into service as a label at ``MEDIUM`` where spec section 10.1
puts it, instead of at the ``HIGH`` a real label earns.

The option stream is the one thing this module derives rather than reads. Spec
section 9.4's descriptor carries the option labels and values raw and no
normalised form of them, so any consumer that wants to match words against them
has to normalise them, and it does so through the same ``extract.normalize``
function every other stream went through. That is a normalisation, not a
re-derivation of a signal the extractor already made.

Evidence
--------

``Prediction.signals`` carries every rule that fired, as ``tier:signal_name``, in
the order the tiers were evaluated. Every rule, not only the winner's: when a
tier ties and the walk falls through, the losing candidate's signals are the
explanation for why it fell through, and dropping them would leave a report
saying ``UNKNOWN`` with no account of what it saw. Tiers after the deciding one
are never evaluated, so the list is bounded by the tier that answered.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from autofill_audit import __version__
from autofill_audit.classify.base import (
    CONFIDENCE_KIND_KEY,
    CONFIDENCE_KIND_TIER,
    TIER_CONFIDENCE,
    ConfidenceTier,
)
from autofill_audit.classify.rules_table import (
    INTRINSIC_RULES,
    OPTION_RULES,
    RULE_TABLE_VERSION,
    TIER_PRECEDENCE,
    TIER_TO_CONFIDENCE,
    VOCABULARY,
    IntrinsicField,
    Rule,
    SignalTier,
)
from autofill_audit.descriptors import FieldDescriptor, Prediction
from autofill_audit.extract.normalize import normalize_tokens
from autofill_audit.taxonomy import Label

__all__ = ["ENGINE_NAME", "RuleClassifier", "TierVerdict", "classify_one"]

ENGINE_NAME: Final[str] = "rules"
"""What lands in ``Prediction.engine``. Also the value ``--engine rules`` takes,
so the flag, the prediction, and the run log all say the same word."""

_UNDETECTABLE_SIGNAL: Final[str] = "undetectable"
"""The evidence recorded when a descriptor names a blind spot rather than a
control. It is not a tier and not a rule: no rule ran, because there was nothing
to run one against."""


@dataclass(frozen=True, slots=True)
class TierVerdict:
    """What one tier concluded about one control.

    ``label`` is None when the tier tied or matched nothing, which are two
    different situations that behave identically here and are told apart by
    whether ``signals`` is empty.
    """

    label: Label | None
    signals: tuple[str, ...]
    runner_up: Label | None = None


_PLACEHOLDER_SOURCE: Final[str] = "placeholder"
"""The ``label_source`` value that means no real label exists. It is the last
member of the extractor's ``LABEL_SOURCE_ORDER`` and the derived fact spec
section 11.1's ``PLACEHOLDER_AS_LABEL`` trigger is stated in."""


def _stream(tokens: Sequence[str]) -> str:
    """Join a token stream for matching.

    Space separated, which is what the ``\\b`` boundaries and the whole-token
    patterns in the table are written against. An empty stream is the empty
    string and matches nothing, including patterns anchored with ``^``, because
    every anchored pattern in the table requires a character after the anchor.
    """
    return " ".join(tokens)


def _label_stream(descriptor: FieldDescriptor) -> str:
    """The real-label stream: empty when the only label is a placeholder."""
    source = descriptor.norm.label_source
    if source is None or source == _PLACEHOLDER_SOURCE:
        return ""
    return _stream(descriptor.norm.label_tokens)


def _placeholder_stream(descriptor: FieldDescriptor) -> str:
    """The placeholder stream: the label tokens, when they came from one."""
    if descriptor.norm.label_source != _PLACEHOLDER_SOURCE:
        return ""
    return _stream(descriptor.norm.label_tokens)


def _option_stream(descriptor: FieldDescriptor) -> str:
    """The option stream: labels then values, normalised and joined."""
    if not descriptor.option_labels and not descriptor.option_values:
        return ""
    tokens: list[str] = []
    for raw in (*descriptor.option_labels, *descriptor.option_values):
        tokens.extend(normalize_tokens(raw))
    return _stream(tokens)


def _resolve(scores: dict[Label, int]) -> tuple[Label | None, Label | None]:
    """Return the unique top-weighted label and its runner-up.

    A tier decides only when exactly one label holds the maximum weight. Two
    labels at the top is a tie, and a tie falls through: it is the table saying
    that this stream does not distinguish them, which is a fact about the page's
    wording rather than a defect in the table.
    """
    if not scores:
        return None, None
    best = max(scores.values())
    leaders = [label for label, weight in scores.items() if weight == best]
    if len(leaders) != 1:
        return None, None
    runners = [label for label, weight in scores.items() if weight != best]
    runner_up = max(runners, key=lambda label: scores[label]) if runners else None
    return leaders[0], runner_up


def _intrinsic_verdict(descriptor: FieldDescriptor) -> TierVerdict:
    """Match the intrinsic tier against the descriptor's own declarations."""
    values: dict[IntrinsicField, str | None] = {
        IntrinsicField.INPUT_TYPE: descriptor.input_type,
        IntrinsicField.INPUTMODE: descriptor.inputmode,
        IntrinsicField.TAG: descriptor.tag,
        IntrinsicField.GROUP_ROLE: descriptor.group_role.value,
    }
    scores: dict[Label, int] = {}
    signals: list[str] = []
    for rule in INTRINSIC_RULES:
        if values.get(rule.field) != rule.value:
            continue
        signals.append(rule.evidence())
        scores[rule.label] = max(scores.get(rule.label, 0), rule.weight)
    label, runner_up = _resolve(scores)
    return TierVerdict(label=label, signals=tuple(signals), runner_up=runner_up)


def _pattern_verdict(stream: str, rules: Sequence[Rule], tier: SignalTier) -> TierVerdict:
    """Match one vocabulary against one stream."""
    if not stream:
        return TierVerdict(label=None, signals=())
    scores: dict[Label, int] = {}
    signals: list[str] = []
    for rule in rules:
        if rule.pattern.search(stream) is None:
            continue
        evidence = rule.evidence(tier)
        if evidence not in signals:
            signals.append(evidence)
        scores[rule.label] = max(scores.get(rule.label, 0), rule.weight)
    label, runner_up = _resolve(scores)
    return TierVerdict(label=label, signals=tuple(signals), runner_up=runner_up)


def _verdict_for(descriptor: FieldDescriptor, tier: SignalTier) -> TierVerdict:
    """Run one tier against one descriptor."""
    match tier:
        case SignalTier.INTRINSIC:
            return _intrinsic_verdict(descriptor)
        case SignalTier.LABEL:
            return _pattern_verdict(_label_stream(descriptor), VOCABULARY, tier)
        case SignalTier.IDENTIFIER:
            return _pattern_verdict(_stream(descriptor.norm.identifier_tokens), VOCABULARY, tier)
        case SignalTier.PLACEHOLDER:
            return _pattern_verdict(_placeholder_stream(descriptor), VOCABULARY, tier)
        case SignalTier.CONTEXT:
            return _pattern_verdict(_stream(descriptor.norm.context_tokens), VOCABULARY, tier)
        case SignalTier.OPTIONS:
            return _pattern_verdict(_option_stream(descriptor), OPTION_RULES, tier)
    raise AssertionError(f"unhandled tier {tier!r}")


def classify_one(descriptor: FieldDescriptor) -> Prediction:
    """Classify one control, with timing.

    Exposed rather than private because the evaluator, the benchmark, and the
    tests all want one control's answer without assembling a page around it.
    """
    started = time.perf_counter()

    if descriptor.undetectable_reason is not None:
        # Check this first and short-circuit (spec section 9.6). A synthetic
        # descriptor names a blind spot: it has no text, no identifiers, and no
        # normalised tokens, so handing it to the tiers would produce a
        # confident-looking UNKNOWN whose evidence list was empty, and the audit
        # engine would lose the one fact that matters about it.
        return Prediction(
            selector=descriptor.selector,
            label=Label.UNKNOWN.value,
            confidence=TIER_CONFIDENCE[ConfidenceTier.NONE],
            engine=ENGINE_NAME,
            signals=(f"{_UNDETECTABLE_SIGNAL}:{descriptor.undetectable_reason}",),
            latency_us=(time.perf_counter() - started) * 1e6,
        )

    signals: list[str] = []
    for tier in TIER_PRECEDENCE:
        verdict = _verdict_for(descriptor, tier)
        for signal in verdict.signals:
            if signal not in signals:
                signals.append(signal)
        if verdict.label is None:
            continue
        confidence_tier = TIER_TO_CONFIDENCE[tier]
        runner_up: tuple[str, float] | None = None
        if verdict.runner_up is not None:
            runner_up = (verdict.runner_up.value, TIER_CONFIDENCE[confidence_tier])
        return Prediction(
            selector=descriptor.selector,
            label=verdict.label.value,
            confidence=TIER_CONFIDENCE[confidence_tier],
            engine=ENGINE_NAME,
            signals=tuple(signals),
            runner_up=runner_up,
            latency_us=(time.perf_counter() - started) * 1e6,
        )

    return Prediction(
        selector=descriptor.selector,
        label=Label.UNKNOWN.value,
        confidence=TIER_CONFIDENCE[ConfidenceTier.NONE],
        engine=ENGINE_NAME,
        signals=tuple(signals),
        latency_us=(time.perf_counter() - started) * 1e6,
    )


class RuleClassifier:
    """The rule engine, and the fallback every other engine falls back to.

    Stateless and cheap to construct. It holds no compiled state of its own
    because the table compiles its patterns once at import, which is also what
    makes a second instance free.

    Spec section 10.1: if the ONNX model file is missing, corrupt, or fails to
    load, the CLI falls back to this, prints one clear line saying so, and
    continues. A tool that refuses to run because a model file is absent is worse
    than a tool that runs with a weaker classifier and says so.
    """

    name: str = ENGINE_NAME

    def predict(self, fields: Sequence[FieldDescriptor]) -> list[Prediction]:
        """Return one prediction per descriptor, in the order given."""
        return [classify_one(descriptor) for descriptor in fields]

    def describe(self) -> dict[str, str]:
        """Return the engine identity the run log and the report copy verbatim.

        ``confidence_kind`` is the load-bearing key. It is what tells a renderer
        that the floats in these predictions are ordered tiers and must be shown
        by name, never as a percentage (spec section 10.1).
        """
        return {
            "engine": ENGINE_NAME,
            "tool_version": __version__,
            "rule_table_version": RULE_TABLE_VERSION,
            "vocabulary_rules": str(len(VOCABULARY)),
            "option_rules": str(len(OPTION_RULES)),
            "intrinsic_rules": str(len(INTRINSIC_RULES)),
            CONFIDENCE_KIND_KEY: CONFIDENCE_KIND_TIER,
        }
