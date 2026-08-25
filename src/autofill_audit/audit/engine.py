"""The ordered decision procedure that turns predictions into findings.

Spec section 11.2, implemented in the order it is written. Compares declared
against inferred labels, and in corpus mode against the answer key. It never
re-derives a signal: everything it reads is on the descriptor the extractor
produced or on the prediction the classifier produced.

The shape of the procedure
--------------------------

Each control gets **at most one primary finding**, chosen by the first matching
branch of the ordered chain, and any number of **secondary findings**, which are
evaluated independently and describe how the control is built rather than what it
means. A control can be both wrongly declared and unlabeled, and a report that
mentioned only the first would leave half the work undone.

The asymmetry in the middle of the chain is the important part and it is
deliberate. **A declaration is authoritative unless the tool is confident it is
wrong.** A developer stated an intent in the markup; a mid-confidence classifier
disagreeing with a stated intent is not evidence, it is noise, and a tool that
emitted it would be loudest on the pages that are most nearly correct.

The corollary is the modifier rule of spec section 7.1: a declared
``shipping postal-code`` against an inferred ``postal-code`` is a **match**. The
comparison is made against ``DeclaredAutocomplete.token``, which the extractor has
already separated from the modifiers, so the two agree exactly and no equivalence
lookup is involved. Getting this wrong produces a flood of false criticals on
well-built checkout pages, and there is a test named for it.

Three readings of the specification, written down
-------------------------------------------------

**``COMPOSITE_FIELD`` is placed in the undeclared branch.** Spec section 11.2's
pseudocode does not mention it and spec section 11.1 gives its trigger as
"inferred ``COMPOSITE_UNSPLIT``". Taken literally that fires a ``WARNING`` on
every correctly declared ``MM/YY`` input, and spec section 8.4 makes any finding
above ``INFO`` on a clean-tier form a defect. Both can only hold if the finding
is about the *absence* of the declaration, so it fires where
``MISSING_AUTOCOMPLETE`` would fire and carries the composite's own fix instead.
A composite that declares ``cc-exp`` or ``street-address`` is correctly declared
and the equivalence set says so.

**``AUTOCOMPLETE_OFF`` stops the primary chain when it fires.** The pseudocode
writes "; stop primary" on two branches and not on this one, but the prose
immediately above it says first match wins, and ``autocomplete="off"`` parses to
a null token, so without the stop a field would collect both
``AUTOCOMPLETE_OFF`` and ``MISSING_AUTOCOMPLETE``: two primary findings with two
contradictory fixes. When the inference is not personal data the branch does not
match at all and the chain continues, which is the correct behaviour for
``autocomplete="off"`` on a search box.

**An empty ``autocomplete=""`` is reported as off specification.** The pseudocode
guards on ``field.declared.raw`` being truthy, which an empty string is not, and
spec section 11.1's trigger says "present, non-empty". But spec section 15
requires an empty ``autocomplete`` to produce a diagnostic rather than silence,
and the extractor already records it as off specification (spec section 9.4). The
guard is therefore on the attribute being *present*, and the fix quotes what the
developer actually wrote, which is nothing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from autofill_audit.audit.findings import (
    CLASSIFICATION_DRIVEN,
    FINDING_SPECS,
    PLACEHOLDER_ID,
    SEVERITY_ORDER,
    SIGNAL_FOR,
    STRUCTURAL_CONFIDENCE,
    UNDETECTABLE_FIX_OVERRIDES,
    UNDETECTABLE_REASON_TEXT,
    UNKNOWN_TOKEN_ADVICE,
    Finding,
    FindingCode,
    Severity,
    at_or_above,
    equivalent,
    is_personal_data,
    severity_rank,
)
from autofill_audit.audit.thresholds import Thresholds
from autofill_audit.classify.base import (
    CONFIDENCE_KIND_KEY,
    CONFIDENCE_KIND_TIER,
    Classifier,
    tier_for_confidence,
)
from autofill_audit.descriptors import (
    CanvasRegion,
    ExtractionResult,
    ExtractionWarningCode,
    FieldDescriptor,
    GroupRole,
    Prediction,
)
from autofill_audit.taxonomy import Label, declaration_for

__all__ = [
    "EXIT_FINDINGS",
    "EXIT_OK",
    "AuditOptions",
    "AuditReport",
    "Suppression",
    "audit",
]

EXIT_OK: Final[int] = 0
"""Spec section 11.5: completed, nothing at or above the failure threshold."""

EXIT_FINDINGS: Final[int] = 1
"""Spec section 11.5: completed, at least one finding at or above it."""

_PAGE_LEVEL_INDEX: Final[int] = -1
"""The sort key page-level findings carry, so they precede every control."""

_GENERIC_IDENTIFIERS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^input\d+$"),
    re.compile(r"^field[_-]?\d+$"),
    re.compile(r"^txt\d+$"),
    re.compile(r"^ctl\d+"),
    re.compile(r"ctl\d+\$"),
    re.compile(r"^[0-9a-f]{8,}$"),
)
"""Spec section 11.1's generic pattern set, as regexes over a raw identifier.

Matched against ``name`` and ``element_id`` casefolded and nothing else. The set
is deliberately narrow, for the same reason the selector rules of spec section
9.3 are: a wider test flags ordinary short identifiers, and a check that cries
wolf is a check somebody disables."""

_ACCESSIBLE_LABEL_SOURCES: Final[frozenset[str]] = frozenset(
    {"label_for", "label_ancestor", "aria_label", "aria_labelledby_text"}
)
"""The four sources spec section 11.1's ``UNLABELED_FIELD`` trigger names.

``title`` is not among them. A title attribute is a tooltip: it is announced
inconsistently, it is invisible on touch, and the specification's own trigger
lists the four above and stops. A control whose only text is a title is
unlabeled, and saying so is the honest reading."""

_PLACEHOLDER_SOURCE: Final[str] = "placeholder"

_TYPE_ATTRIBUTE: Final[str] = "type"
_INPUTMODE_ATTRIBUTE: Final[str] = "inputmode"

_EXPECTED_INPUT: Final[dict[Label, tuple[str, str]]] = {
    Label.EMAIL: (_TYPE_ATTRIBUTE, "email"),
    Label.URL: (_TYPE_ATTRIBUTE, "url"),
    Label.TEL: (_INPUTMODE_ATTRIBUTE, "tel"),
    Label.TEL_NATIONAL: (_INPUTMODE_ATTRIBUTE, "tel"),
    Label.CC_NUMBER: (_INPUTMODE_ATTRIBUTE, "numeric"),
    Label.CC_CSC: (_INPUTMODE_ATTRIBUTE, "numeric"),
    Label.ONE_TIME_CODE: (_INPUTMODE_ATTRIBUTE, "numeric"),
}
"""Spec section 11.1's ``WRONG_INPUT_TYPE`` table, for the labels where the
answer does not depend on anything the descriptor cannot see.

**``postal-code`` is deliberately absent, and this is a deviation worth stating.**
Spec section 11.1 writes its expected inputmode as "per locale", and it is right
to: a German or American postal code is digits and wants ``inputmode="numeric"``,
while a British, Irish, Canadian, or Dutch one contains letters and would be made
harder to type by a numeric keypad. Nothing on a ``FieldDescriptor`` names the
country the form is for. Emitting the wrong keypad advice on half the world's
checkout pages would be worse than emitting none, so this table stops where the
evidence stops."""


@dataclass(frozen=True, slots=True)
class Suppression:
    """One configured suppression, and why (spec section 14).

    ``selector`` is None for a whole-code suppression, which is what
    ``ignore = ["GENERIC_IDENTIFIER"]`` in the config file produces. A suppressed
    finding is retained and reported under ``suppressed`` with this reason
    attached, never dropped.
    """

    code: FindingCode
    selector: str | None = None
    reason: str = "suppressed by configuration"

    def matches(self, finding: Finding) -> bool:
        """Whether this rule suppresses ``finding``."""
        if finding.code is not self.code:
            return False
        return self.selector is None or self.selector == finding.selector


@dataclass(frozen=True, slots=True)
class AuditOptions:
    """Everything the decision procedure needs that is not the page itself."""

    thresholds: Thresholds
    suppressions: tuple[Suppression, ...] = ()
    include_hidden: bool = False
    """Audit the controls a user cannot see instead of setting them aside."""
    answer_key: Mapping[str, str] | None = None
    """Corpus mode only: selector to true label. It **never** changes a
    user-facing finding (spec section 11.2). It produces ``KEY_MISMATCH`` records
    on a separate list, and keeping it out of the finding path is what makes the
    corpus a test rather than an oracle the product depends on."""


@dataclass(frozen=True, slots=True)
class AuditReport:
    """One page, audited.

    ``findings`` is what a reader acts on. ``suppressed`` is what configuration
    hid, with reasons. ``evaluation`` is the corpus-mode record and is never
    shown to a user.
    """

    url: str
    findings: tuple[Finding, ...] = ()
    suppressed: tuple[Finding, ...] = ()
    evaluation: tuple[Finding, ...] = ()
    fields: tuple[FieldDescriptor, ...] = ()
    honeypots: tuple[FieldDescriptor, ...] = ()
    predictions: tuple[Prediction, ...] = ()
    engine: Mapping[str, str] = field(default_factory=dict)
    thresholds: Thresholds | None = None
    page_notes: tuple[str, ...] = ()
    """Page-level facts that are not findings: a truncated walk, an unreadable
    frame, a canvas beside real controls. The finding catalogue is closed at
    fifteen codes (spec section 11.1), so a fact with no code is reported as a
    fact rather than given an invented one."""
    canvas_regions: tuple[CanvasRegion, ...] = ()
    frame_count: int = 1
    controls_seen: int = 0
    truncated: bool = False
    timing_ms: Mapping[str, float] = field(default_factory=dict)
    """The one part of a report that is not a pure function of the page.

    Everything else here is deterministic, so two runs over one page produce
    byte-identical JSON and a diff in CI means something changed. The golden
    snapshots of spec section 15 pin fixed values into this key for exactly that
    reason."""

    def counts(self) -> dict[Severity, int]:
        """Findings per severity, every severity present, most severe first.

        Every severity present including the zeroes: a summary that omitted the
        empty rows would make "no criticals" and "criticals not checked"
        indistinguishable.
        """
        tally = dict.fromkeys(SEVERITY_ORDER, 0)
        for finding in self.findings:
            tally[finding.severity] += 1
        return tally

    def worst(self) -> Severity | None:
        """The most severe finding's severity, or None when there are none."""
        if not self.findings:
            return None
        return min((finding.severity for finding in self.findings), key=severity_rank)

    def readiness(self) -> tuple[int, int]:
        """Controls carrying a usable declaration, and controls audited.

        **A count, never a score** (spec section 11.4). No letter grade, no index
        out of a hundred, no weighting of one finding against another. A composite
        score would be a number with no reproducible definition, which is a law 3
        problem wearing a friendly hat, and the first thing anybody would do with
        one is quote it without the report it came from.

        Blind spots are excluded from both halves. A cross-origin frame is not a
        control that failed to declare anything; it is a control this tool cannot
        see, and counting it as a failure would make a correctly built hosted
        payment form look worse than a broken one.
        """
        real = [item for item in self.fields if item.undetectable_reason is None]
        declared = sum(
            1 for item in real if item.declared.token is not None and not item.declared.is_off_spec
        )
        return declared, len(real)

    def exit_code(self, fail_on: Severity | None) -> int:
        """Spec section 11.5's codes 0 and 1.

        ``fail_on`` of None is ``--fail-on never``: the audit always reports
        success, which is what a reporting-only CI step wants. The loader and
        usage failures own codes 2, 3, and 4 and are decided in the CLI, because
        they happen before there is a report to ask.
        """
        if fail_on is None:
            return EXIT_OK
        for finding in self.findings:
            if at_or_above(finding.severity, fail_on):
                return EXIT_FINDINGS
        return EXIT_OK


# ---------------------------------------------------------------------------
# Predicates over one descriptor. Each reads the descriptor and nothing else.
# ---------------------------------------------------------------------------


def _has_accessible_label(descriptor: FieldDescriptor) -> bool:
    """Whether any of the four sources of spec section 11.1 named the control."""
    text = descriptor.text
    return any(getattr(text, source) is not None for source in sorted(_ACCESSIBLE_LABEL_SOURCES))


def _is_generic_identifier(descriptor: FieldDescriptor) -> bool:
    """Whether the name or id matches the generic pattern set."""
    for raw in (descriptor.name, descriptor.element_id):
        if raw is None:
            continue
        folded = raw.casefold()
        if any(pattern.search(folded) for pattern in _GENERIC_IDENTIFIERS):
            return True
    return False


def _declared_label(descriptor: FieldDescriptor) -> Label | None:
    """The declared token as a taxonomy label, when it is one.

    None covers two different situations and the caller has to know which. Either
    nothing was declared, or the declaration names a WHATWG token this project's
    taxonomy leaves out (spec section 7.1 excludes seventeen of them). In the
    second case the tool cannot adjudicate the declaration at all: it has no label
    to compare against, so it says nothing rather than guessing that a valid token
    it does not model is wrong. That is law 1 applied to the declaration side.
    """
    token = descriptor.declared.token
    if token is None:
        return None
    try:
        return Label(token)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Assembly of one finding.
# ---------------------------------------------------------------------------


def _confidence_display(prediction: Prediction, engine: Mapping[str, str]) -> str:
    """Format a confidence for a person (spec sections 10.1 and 11.4).

    For a tiered engine this is the tier name and never a percentage. Printing
    "83%" from a regex table would assert a frequency nothing has observed, which
    is a law 1 and a law 4 violation in a single number.
    """
    if engine.get(CONFIDENCE_KIND_KEY) == CONFIDENCE_KIND_TIER:
        return f"rule tier {tier_for_confidence(prediction.confidence).value}"
    return f"confidence {prediction.confidence:.2f}"


def _make(
    code: FindingCode,
    *,
    selector: str,
    context: dict[str, str],
    prediction: Prediction | None = None,
    engine: Mapping[str, str],
    label: str | None = None,
    declared: str | None = None,
    group_id: str | None = None,
    template: str | None = None,
) -> Finding:
    """Build one finding from the catalogue, formatting its fix template.

    The template comes from ``FINDING_SPECS`` unless the caller passes a
    documented override, and the context is the only thing a caller supplies.
    That is what makes all three renderers agree by construction.

    Evidence is assembled here so that no caller can forget it. Every finding
    carries the code's own evidence entry from ``SIGNAL_FOR``; a
    classification-driven code additionally carries the rule signals that
    produced the prediction and that prediction's confidence, while a structural
    code carries neither, because there was no classification to be confident
    about (law 1).
    """
    spec = FINDING_SPECS[code]
    resolved = template if template is not None else spec.fix
    signals: list[str] = [SIGNAL_FOR[code]]
    confidence: float | None = None
    display = STRUCTURAL_CONFIDENCE
    if code in CLASSIFICATION_DRIVEN and prediction is not None:
        signals.extend(signal for signal in prediction.signals if signal not in signals)
        confidence = prediction.confidence
        display = _confidence_display(prediction, engine)
    return Finding(
        code=code,
        severity=spec.severity,
        selector=selector,
        fix=resolved.format(**context),
        signals=tuple(signals),
        confidence=confidence,
        confidence_display=display,
        label=label,
        declared=declared,
        group_id=group_id,
    )


# ---------------------------------------------------------------------------
# The primary chain (spec section 11.2).
# ---------------------------------------------------------------------------


def _primary(
    descriptor: FieldDescriptor,
    prediction: Prediction,
    inferred: Label,
    options: AuditOptions,
    engine: Mapping[str, str],
    *,
    unlabeled: bool,
) -> Finding | None:
    """Return the one primary finding for a control, or None.

    Ordered exactly as spec section 11.2 writes it. ``unlabeled`` is passed in
    rather than recomputed so that the ``UNKNOWN`` branch and the secondary pass
    agree about the same control, and so that ``UNLABELED_FIELD`` is emitted once
    when both would raise it.
    """
    thresholds = options.thresholds
    declared = descriptor.declared
    selector = descriptor.selector

    if descriptor.undetectable_reason is not None:
        reason = UNDETECTABLE_REASON_TEXT.get(
            descriptor.undetectable_reason, descriptor.undetectable_reason
        )
        return _make(
            FindingCode.UNDETECTABLE_FIELD,
            selector=selector,
            context={"reason": reason},
            prediction=prediction,
            engine=engine,
            template=UNDETECTABLE_FIX_OVERRIDES.get(descriptor.undetectable_reason),
        )

    if declared.is_off and is_personal_data(inferred):
        return _make(
            FindingCode.AUTOCOMPLETE_OFF,
            selector=selector,
            context={"selector": selector},
            prediction=prediction,
            engine=engine,
            label=inferred.value,
            declared=declared.raw,
        )

    if declared.raw is not None and declared.is_off_spec:
        suggestion = declaration_for(inferred)
        advice = (
            suggestion.value
            if suggestion is not None and prediction.confidence >= thresholds.tau_high
            else UNKNOWN_TOKEN_ADVICE
        )
        return _make(
            FindingCode.OFF_SPEC_TOKEN,
            selector=selector,
            context={"declared": declared.raw, "label": advice},
            prediction=prediction,
            engine=engine,
            label=inferred.value,
            declared=declared.raw,
        )

    if declared.token is not None:
        declared_label = _declared_label(descriptor)
        if declared_label is None:
            # A valid WHATWG token outside this taxonomy. Nothing to compare.
            return None
        if equivalent(declared_label, inferred):
            return None
        if prediction.confidence >= thresholds.tau_high:
            suggestion = declaration_for(inferred)
            if suggestion is None:
                return None
            return _make(
                FindingCode.WRONG_AUTOCOMPLETE,
                selector=selector,
                context={
                    "selector": selector,
                    "declared": declared_label.value,
                    "label": suggestion.value,
                },
                prediction=prediction,
                engine=engine,
                label=inferred.value,
                declared=declared.raw,
            )
        # The declaration is authoritative unless we are confident it is wrong.
        return None

    if inferred is Label.NOT_AUTOFILLABLE:
        return None

    if inferred is Label.UNKNOWN:
        if unlabeled:
            return _make(
                FindingCode.UNLABELED_FIELD,
                selector=selector,
                context={
                    "selector": selector,
                    "id": descriptor.element_id or descriptor.name or PLACEHOLDER_ID,
                },
                prediction=prediction,
                engine=engine,
                label=inferred.value,
            )
        return None

    if inferred is Label.COMPOSITE_UNSPLIT:
        if prediction.confidence < thresholds.tau_high:
            return None
        return _make(
            FindingCode.COMPOSITE_FIELD,
            selector=selector,
            context={"selector": selector, "label": _composite_token(descriptor).value},
            prediction=prediction,
            engine=engine,
            label=inferred.value,
        )

    suggestion = declaration_for(inferred)
    if suggestion is None:
        return None
    if prediction.confidence >= thresholds.tau_high:
        return _make(
            FindingCode.MISSING_AUTOCOMPLETE,
            selector=selector,
            context={"selector": selector, "label": suggestion.value},
            prediction=prediction,
            engine=engine,
            label=inferred.value,
        )
    if prediction.confidence >= thresholds.tau_low:
        return _make(
            FindingCode.LOW_CONFIDENCE,
            selector=selector,
            context={
                "selector": selector,
                "label": suggestion.value,
                "confidence": _confidence_display(prediction, engine),
            },
            prediction=prediction,
            engine=engine,
            label=inferred.value,
        )
    return None


def _composite_token(descriptor: FieldDescriptor) -> Label:
    """Which token a composite control should declare (spec section 7.2).

    ``COMPOSITE_UNSPLIT`` deliberately has no single correct declaration: a
    ``MM/YY`` input takes the combined expiry token and a full-address textarea
    takes the street-address token, and the label alone cannot say which. The
    control can: a textarea collects an address, and so does a control long
    enough to hold one, while a short input beside a card number collects an
    expiry.
    """
    if descriptor.tag == "textarea":
        return Label.STREET_ADDRESS
    if descriptor.maxlength is not None and descriptor.maxlength <= _EXPIRY_MAX_LENGTH:
        return Label.CC_EXP
    return Label.STREET_ADDRESS


_EXPIRY_MAX_LENGTH: Final[int] = 7
"""The longest a ``MM/YY`` or ``MM/YYYY`` control's maxlength can be and still be
an expiry. Above it, a single control collecting several values is collecting an
address, which is the only other composite this taxonomy names."""


# ---------------------------------------------------------------------------
# The secondary findings (spec section 11.2), evaluated independently.
# ---------------------------------------------------------------------------


def _secondary(
    descriptor: FieldDescriptor,
    prediction: Prediction,
    inferred: Label,
    engine: Mapping[str, str],
    *,
    unlabeled: bool,
    primary: Finding | None,
) -> list[Finding]:
    """Return every secondary finding for one control.

    ``primary`` is passed in so that ``UNLABELED_FIELD`` is not emitted twice
    when the ``UNKNOWN`` branch of the primary chain already raised it. The two
    are the same claim about the same control, and a report that made it twice
    would be a report whose counts nobody could reconcile.
    """
    selector = descriptor.selector
    found: list[Finding] = []

    already_unlabeled = primary is not None and primary.code is FindingCode.UNLABELED_FIELD
    if unlabeled and not already_unlabeled:
        if descriptor.norm.label_source == _PLACEHOLDER_SOURCE:
            found.append(
                _make(
                    FindingCode.PLACEHOLDER_AS_LABEL,
                    selector=selector,
                    context={"selector": selector},
                    prediction=prediction,
                    engine=engine,
                    label=inferred.value,
                )
            )
        else:
            found.append(
                _make(
                    FindingCode.UNLABELED_FIELD,
                    selector=selector,
                    context={
                        "selector": selector,
                        "id": descriptor.element_id or descriptor.name or PLACEHOLDER_ID,
                    },
                    prediction=prediction,
                    engine=engine,
                    label=inferred.value,
                )
            )

    if unlabeled and _is_generic_identifier(descriptor):
        found.append(
            _make(
                FindingCode.GENERIC_IDENTIFIER,
                selector=selector,
                context={"selector": selector},
                prediction=prediction,
                engine=engine,
                label=inferred.value,
            )
        )

    expected = _EXPECTED_INPUT.get(inferred)
    if expected is not None:
        attribute, wanted = expected
        satisfied = descriptor.input_type == wanted or descriptor.inputmode == wanted
        if not satisfied:
            found.append(
                _make(
                    FindingCode.WRONG_INPUT_TYPE,
                    selector=selector,
                    context={
                        "selector": selector,
                        "attribute": attribute,
                        "expected": wanted,
                    },
                    prediction=prediction,
                    engine=engine,
                    label=inferred.value,
                )
            )

    if descriptor.form_index is not None and descriptor.name is None:
        found.append(
            _make(
                FindingCode.MISSING_NAME_ATTR,
                selector=selector,
                context={"selector": selector},
                prediction=prediction,
                engine=engine,
                label=inferred.value,
            )
        )

    return found


def _split_field_findings(
    descriptors: Sequence[FieldDescriptor],
    predictions: Mapping[str, Prediction],
    engine: Mapping[str, str],
) -> list[Finding]:
    """One ``SPLIT_FIELD`` per incomplete expiry group, never one per member.

    Spec section 11.2 is explicit about the once-per-group rule, and the reason
    is the fix: both halves have to be changed together, so telling a reader
    twice is telling them to do the job twice.
    """
    groups: dict[str, list[FieldDescriptor]] = {}
    for descriptor in descriptors:
        if descriptor.group_role not in {GroupRole.CC_EXP_MONTH, GroupRole.CC_EXP_YEAR}:
            continue
        if descriptor.group_id is None:
            continue
        groups.setdefault(descriptor.group_id, []).append(descriptor)

    wanted = {
        GroupRole.CC_EXP_MONTH: Label.CC_EXP_MONTH,
        GroupRole.CC_EXP_YEAR: Label.CC_EXP_YEAR,
    }
    found: list[Finding] = []
    for group_id, members in groups.items():
        complete = all(
            _declared_label(member) is wanted[GroupRole(member.group_role)] for member in members
        )
        if complete:
            continue
        anchor = members[0]
        found.append(
            _make(
                FindingCode.SPLIT_FIELD,
                selector=anchor.selector,
                context={
                    "selector": anchor.selector,
                    "month_token": Label.CC_EXP_MONTH.value,
                    "year_token": Label.CC_EXP_YEAR.value,
                },
                prediction=predictions.get(anchor.selector),
                engine=engine,
                group_id=group_id,
            )
        )
    return found


# ---------------------------------------------------------------------------
# Page-level findings and notes.
# ---------------------------------------------------------------------------


def _page_findings(
    result: ExtractionResult,
    engine: Mapping[str, str],
    seen_selectors: set[str],
) -> tuple[list[Finding], list[str]]:
    """Findings and notes that belong to the page rather than to a control."""
    found: list[Finding] = []
    notes: list[str] = []

    incomplete = result.warning(ExtractionWarningCode.INCOMPLETE)
    if incomplete is not None:
        found.append(
            _make(
                FindingCode.EXTRACTION_INCOMPLETE,
                selector=result.url,
                context={},
                engine=engine,
            )
        )
        notes.append(incomplete.detail)

    for code in (ExtractionWarningCode.TRUNCATED, ExtractionWarningCode.FRAME_UNREADABLE):
        warning = result.warning(code)
        if warning is not None:
            notes.append(warning.detail)

    for region in result.canvas_regions:
        if region.selector in seen_selectors:
            continue
        found.append(
            _make(
                FindingCode.UNDETECTABLE_FIELD,
                selector=region.selector,
                context={"reason": UNDETECTABLE_REASON_TEXT["canvas-region"]},
                engine=engine,
            )
        )

    return found, notes


# ---------------------------------------------------------------------------
# Corpus mode.
# ---------------------------------------------------------------------------


def _key_mismatches(
    descriptors: Sequence[FieldDescriptor],
    predictions: Mapping[str, Prediction],
    answer_key: Mapping[str, str],
    engine: Mapping[str, str],
) -> list[Finding]:
    """Compare predictions against the answer key, for evaluation only.

    These never reach a user-facing report. Keeping the answer key out of the
    finding path is what makes the corpus a test rather than an oracle the
    product depends on (spec section 11.2).
    """
    records: list[Finding] = []
    engine_name = engine.get("engine", "")
    for descriptor in descriptors:
        expected = answer_key.get(descriptor.selector)
        if expected is None:
            continue
        prediction = predictions.get(descriptor.selector)
        if prediction is None or prediction.label == expected:
            continue
        records.append(
            _make(
                FindingCode.KEY_MISMATCH,
                selector=descriptor.selector,
                context={
                    "expected": expected,
                    "engine": engine_name,
                    "label": prediction.label,
                    "confidence": _confidence_display(prediction, engine),
                },
                prediction=prediction,
                engine=engine,
                label=prediction.label,
            )
        )
    return records


# ---------------------------------------------------------------------------
# The entry point.
# ---------------------------------------------------------------------------


def audit(
    result: ExtractionResult,
    classifier: Classifier,
    options: AuditOptions,
) -> AuditReport:
    """Run the decision procedure over one extraction.

    Args:
        result: what the extractor produced, page level included.
        classifier: any engine satisfying the protocol. The audit engine never
            knows which one ran except through ``describe()``.
        options: thresholds, suppressions, and the corpus-mode answer key.

    Returns:
        The report, with findings ordered by document position, then by severity,
        then by code, so that two runs over one page produce byte-identical
        output and a golden snapshot means something.
    """
    engine = classifier.describe()

    audited: list[FieldDescriptor] = list(result.fields)
    honeypots: list[FieldDescriptor] = list(result.honeypots)
    if options.include_hidden:
        audited.extend(honeypots)
        honeypots = []
    audited.sort(key=lambda item: item.document_index)

    predictions = classifier.predict(audited)
    by_selector = {
        descriptor.selector: prediction
        for descriptor, prediction in zip(audited, predictions, strict=True)
    }
    order = {descriptor.selector: descriptor.document_index for descriptor in audited}

    raised: list[Finding] = []
    for descriptor, prediction in zip(audited, predictions, strict=True):
        inferred = Label(prediction.label)
        unlabeled = not _has_accessible_label(descriptor)
        primary = _primary(
            descriptor,
            prediction,
            inferred,
            options,
            engine,
            unlabeled=unlabeled,
        )
        if primary is not None:
            raised.append(primary)
        if descriptor.undetectable_reason is not None:
            # A synthetic descriptor names a blind spot, not a control. It has no
            # label, no identifier, and no form, so every secondary finding would
            # fire on it and every one of them would be about a control nobody
            # can see. The blind spot is the finding.
            continue
        raised.extend(
            _secondary(
                descriptor,
                prediction,
                inferred,
                engine,
                unlabeled=unlabeled,
                primary=primary,
            )
        )

    raised.extend(_split_field_findings(audited, by_selector, engine))

    page, notes = _page_findings(result, engine, {descriptor.selector for descriptor in audited})
    raised.extend(page)

    raised.sort(
        key=lambda finding: (
            order.get(finding.selector, _PAGE_LEVEL_INDEX),
            severity_rank(finding.severity),
            finding.code.value,
            finding.fix,
        )
    )

    kept: list[Finding] = []
    hidden: list[Finding] = []
    for finding in raised:
        rule = next((item for item in options.suppressions if item.matches(finding)), None)
        if rule is None:
            kept.append(finding)
            continue
        hidden.append(
            Finding(
                code=finding.code,
                severity=finding.severity,
                selector=finding.selector,
                fix=finding.fix,
                signals=finding.signals,
                confidence=finding.confidence,
                confidence_display=finding.confidence_display,
                label=finding.label,
                declared=finding.declared,
                group_id=finding.group_id,
                suppressed_by=rule.reason,
            )
        )

    evaluation: tuple[Finding, ...] = ()
    if options.answer_key is not None:
        evaluation = tuple(_key_mismatches(audited, by_selector, options.answer_key, engine))

    report = AuditReport(
        url=result.url,
        findings=tuple(kept),
        suppressed=tuple(hidden),
        evaluation=evaluation,
        fields=tuple(audited),
        honeypots=tuple(honeypots),
        predictions=tuple(predictions),
        engine=engine,
        thresholds=options.thresholds,
        page_notes=tuple(notes),
        canvas_regions=result.canvas_regions,
        frame_count=result.frame_count,
        controls_seen=result.controls_seen,
        truncated=result.truncated,
    )
    _assert_law_one(report)
    return report


def _assert_law_one(report: AuditReport) -> None:
    """Every emitted finding carries named evidence and a stated confidence.

    Law 1, checked rather than remembered, over the findings a reader sees and
    the ones configuration hid. There are no exemptions: a structural finding
    carries its structural evidence and the word ``structural`` where a
    confidence would go, and a classification-driven one carries the rule signals
    and the tier. A finding with neither is a bug, not a low-quality finding.
    """
    for finding in (*report.findings, *report.suppressed):
        if not finding.signals or not finding.confidence_display:
            raise AssertionError(
                f"{finding.code.value} on {finding.selector} carries no evidence; "
                "law 1 forbids emitting it"
            )
        if finding.code in CLASSIFICATION_DRIVEN and finding.confidence is None:
            raise AssertionError(
                f"{finding.code.value} on {finding.selector} acts on a classification "
                "and must carry its confidence"
            )
