"""``Finding``, the finding code enum, severities, fix templates, equivalences.

Spec section 11.1, and the one place any of it is written down. Every finding
carries named evidence and a stated confidence or documented tier, or it is not
emitted at all (law 1).

**Fix text is data, not f-strings scattered through the renderers.** The
templates live here, beside the enum, and all three renderers format the same
template with the same fields, so they agree by construction rather than by
three people remembering to make the same edit. A renderer that wants different
wording is a renderer that has to change this file, which is exactly the friction
the golden snapshots of spec section 15 exist to make visible.

Severities are ordered, and the order is the whole of the exit-code contract.
``CRITICAL`` is "autofill will certainly fail on a field a user must fill",
``WARNING`` is "will probably fail or fill wrongly", ``INFO`` is "works, but is
fragile", ``NOTE`` is "informational, no action implied". The clean-tier property
of spec section 8.4 is stated against this order: nothing above ``INFO`` may fire
on a correctly built form, which is to say no ``WARNING`` and no ``CRITICAL``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from autofill_audit.taxonomy import Label, declaration_for

__all__ = [
    "CLASSIFICATION_DRIVEN",
    "EQUIVALENCE_SETS",
    "FINDING_SPECS",
    "PLACEHOLDER_ID",
    "SEVERITY_ORDER",
    "SIGNAL_FOR",
    "STRUCTURAL_CONFIDENCE",
    "UNDETECTABLE_FIX_OVERRIDES",
    "UNDETECTABLE_REASON_TEXT",
    "UNKNOWN_TOKEN_ADVICE",
    "Finding",
    "FindingCode",
    "FindingSpec",
    "Severity",
    "at_or_above",
    "equivalent",
    "is_personal_data",
    "severity_rank",
]


class Severity(StrEnum):
    """How much a finding is claiming (spec section 11.1)."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    NOTE = "note"


SEVERITY_ORDER: Final[tuple[Severity, ...]] = (
    Severity.CRITICAL,
    Severity.WARNING,
    Severity.INFO,
    Severity.NOTE,
)
"""Most severe first. Fixed here so that a report's group order, a summary's row
order, and the ``--fail-on`` comparison all read the same list."""

_SEVERITY_RANK: Final[dict[Severity, int]] = {
    severity: index for index, severity in enumerate(SEVERITY_ORDER)
}


def severity_rank(severity: Severity) -> int:
    """Return a sortable rank, zero being the most severe."""
    return _SEVERITY_RANK[severity]


def at_or_above(severity: Severity, threshold: Severity) -> bool:
    """Whether ``severity`` is as severe as ``threshold`` or more so."""
    return severity_rank(severity) <= severity_rank(threshold)


class FindingCode(StrEnum):
    """The fifteen codes of spec section 11.1, and no sixteenth.

    The catalogue is closed at P3 on purpose. A code is a promise to a reader
    that a class of problem has a defined trigger, a defined severity, and a
    defined fix, and adding one without all three is how a finding list turns
    into a list of opinions.
    """

    MISSING_AUTOCOMPLETE = "MISSING_AUTOCOMPLETE"
    WRONG_AUTOCOMPLETE = "WRONG_AUTOCOMPLETE"
    OFF_SPEC_TOKEN = "OFF_SPEC_TOKEN"
    AUTOCOMPLETE_OFF = "AUTOCOMPLETE_OFF"
    UNLABELED_FIELD = "UNLABELED_FIELD"
    PLACEHOLDER_AS_LABEL = "PLACEHOLDER_AS_LABEL"
    SPLIT_FIELD = "SPLIT_FIELD"
    COMPOSITE_FIELD = "COMPOSITE_FIELD"
    GENERIC_IDENTIFIER = "GENERIC_IDENTIFIER"
    WRONG_INPUT_TYPE = "WRONG_INPUT_TYPE"
    MISSING_NAME_ATTR = "MISSING_NAME_ATTR"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    UNDETECTABLE_FIELD = "UNDETECTABLE_FIELD"
    EXTRACTION_INCOMPLETE = "EXTRACTION_INCOMPLETE"
    KEY_MISMATCH = "KEY_MISMATCH"


@dataclass(frozen=True, slots=True)
class FindingSpec:
    """Everything fixed about one code: severity, trigger, fix template.

    ``fix`` is a ``str.format`` template. Its placeholders are the keys the audit
    engine puts in ``Finding.context``, and the module-level assertion at the
    bottom checks that every placeholder a template names is a key the engine
    documents, so a renaming cannot leave a template that raises at render time
    on the one page that triggers it.
    """

    code: FindingCode
    severity: Severity
    trigger: str
    fix: str
    user_facing: bool = True
    """False only for ``KEY_MISMATCH``, which exists to drive evaluation and
    never reaches a user's report (spec section 11.2)."""


_MISSING_AUTOCOMPLETE_FIX: Final[str] = 'add autocomplete="{label}" to {selector}'
_WRONG_AUTOCOMPLETE_FIX: Final[str] = (
    '{selector} declares autocomplete="{declared}" but looks like {label}; '
    'change to autocomplete="{label}"'
)
_OFF_SPEC_TOKEN_FIX: Final[str] = (
    'autocomplete="{declared}" is not a valid autofill token; use "{label}"'
)
_AUTOCOMPLETE_OFF_FIX: Final[str] = (
    'remove autocomplete="off" from {selector}; browsers may ignore it and users lose autofill'
)
_UNLABELED_FIELD_FIX: Final[str] = 'add a <label for="{id}">...</label> to {selector}'
_PLACEHOLDER_AS_LABEL_FIX: Final[str] = (
    "{selector} uses a placeholder as its label; add a real <label>"
)
_SPLIT_FIELD_FIX: Final[str] = (
    '{selector} is one half of a split expiry; set autocomplete="{month_token}" and '
    '"{year_token}" on the pair'
)
_COMPOSITE_FIELD_FIX: Final[str] = (
    '{selector} collects several values in one control; declare autocomplete="{label}" or split it'
)
_GENERIC_IDENTIFIER_FIX: Final[str] = (
    "give {selector} a meaningful name/id, or declare autocomplete"
)
_WRONG_INPUT_TYPE_FIX: Final[str] = 'set {attribute}="{expected}" on {selector}'
_MISSING_NAME_ATTR_FIX: Final[str] = "add a name attribute to {selector}"
_LOW_CONFIDENCE_FIX: Final[str] = (
    "{selector} may be {label} ({confidence}); declare autocomplete explicitly"
)
_UNDETECTABLE_FIELD_FIX: Final[str] = (
    "{reason}: autofill cannot see this field; expose it in light DOM or declare "
    "autocomplete on the host"
)
_EXTRACTION_INCOMPLETE_FIX: Final[str] = (
    "the page was still adding fields when auditing stopped; re-run with a longer --settle"
)
_KEY_MISMATCH_FIX: Final[str] = (
    "answer key says {expected}, {engine} predicted {label} ({confidence})"
)


FINDING_SPECS: Final[dict[FindingCode, FindingSpec]] = {
    FindingCode.MISSING_AUTOCOMPLETE: FindingSpec(
        code=FindingCode.MISSING_AUTOCOMPLETE,
        severity=Severity.CRITICAL,
        trigger=(
            "no autocomplete declared, and the inferred label is an autofillable token "
            "at or above the high-confidence threshold"
        ),
        fix=_MISSING_AUTOCOMPLETE_FIX,
    ),
    FindingCode.WRONG_AUTOCOMPLETE: FindingSpec(
        code=FindingCode.WRONG_AUTOCOMPLETE,
        severity=Severity.CRITICAL,
        trigger=(
            "the declared token differs from the inferred label, the inference is at or "
            "above the high-confidence threshold, and the two are not equivalent"
        ),
        fix=_WRONG_AUTOCOMPLETE_FIX,
    ),
    FindingCode.OFF_SPEC_TOKEN: FindingSpec(
        code=FindingCode.OFF_SPEC_TOKEN,
        severity=Severity.CRITICAL,
        trigger=(
            "an autocomplete value is present and does not name exactly one field-name "
            "token the HTML specification defines"
        ),
        fix=_OFF_SPEC_TOKEN_FIX,
    ),
    FindingCode.AUTOCOMPLETE_OFF: FindingSpec(
        code=FindingCode.AUTOCOMPLETE_OFF,
        severity=Severity.WARNING,
        trigger='autocomplete="off" on a field inferred to be a personal-data field',
        fix=_AUTOCOMPLETE_OFF_FIX,
    ),
    FindingCode.UNLABELED_FIELD: FindingSpec(
        code=FindingCode.UNLABELED_FIELD,
        severity=Severity.WARNING,
        trigger="no label for, no ancestor label, no aria-label, and no aria-labelledby",
        fix=_UNLABELED_FIELD_FIX,
    ),
    FindingCode.PLACEHOLDER_AS_LABEL: FindingSpec(
        code=FindingCode.PLACEHOLDER_AS_LABEL,
        severity=Severity.WARNING,
        trigger="a placeholder is present and is the only text signal",
        fix=_PLACEHOLDER_AS_LABEL_FIX,
    ),
    FindingCode.SPLIT_FIELD: FindingSpec(
        code=FindingCode.SPLIT_FIELD,
        severity=Severity.WARNING,
        trigger=("a detected split expiry pair where either member lacks the matching declaration"),
        fix=_SPLIT_FIELD_FIX,
    ),
    FindingCode.COMPOSITE_FIELD: FindingSpec(
        code=FindingCode.COMPOSITE_FIELD,
        severity=Severity.WARNING,
        trigger=(
            "the inferred label is the composite extra and no declaration names the "
            "token the composite should carry"
        ),
        fix=_COMPOSITE_FIELD_FIX,
    ),
    FindingCode.GENERIC_IDENTIFIER: FindingSpec(
        code=FindingCode.GENERIC_IDENTIFIER,
        severity=Severity.INFO,
        trigger="the name or id matches the generic pattern set and no label exists",
        fix=_GENERIC_IDENTIFIER_FIX,
    ),
    FindingCode.WRONG_INPUT_TYPE: FindingSpec(
        code=FindingCode.WRONG_INPUT_TYPE,
        severity=Severity.INFO,
        trigger="the inferred label implies a type or inputmode the control lacks",
        fix=_WRONG_INPUT_TYPE_FIX,
    ),
    FindingCode.MISSING_NAME_ATTR: FindingSpec(
        code=FindingCode.MISSING_NAME_ATTR,
        severity=Severity.INFO,
        trigger="a control inside a form carries no name attribute",
        fix=_MISSING_NAME_ATTR_FIX,
    ),
    FindingCode.LOW_CONFIDENCE: FindingSpec(
        code=FindingCode.LOW_CONFIDENCE,
        severity=Severity.NOTE,
        trigger=("nothing is declared and the inference sits between the low and high thresholds"),
        fix=_LOW_CONFIDENCE_FIX,
    ),
    FindingCode.UNDETECTABLE_FIELD: FindingSpec(
        code=FindingCode.UNDETECTABLE_FIELD,
        severity=Severity.WARNING,
        trigger="the descriptor names a blind spot: a closed shadow root, a cross-origin "
        "frame, or a page whose only form-like element is a canvas",
        fix=_UNDETECTABLE_FIELD_FIX,
    ),
    FindingCode.EXTRACTION_INCOMPLETE: FindingSpec(
        code=FindingCode.EXTRACTION_INCOMPLETE,
        severity=Severity.INFO,
        trigger="the extraction budget expired with the DOM still mutating",
        fix=_EXTRACTION_INCOMPLETE_FIX,
    ),
    FindingCode.KEY_MISMATCH: FindingSpec(
        code=FindingCode.KEY_MISMATCH,
        severity=Severity.NOTE,
        trigger="corpus mode only: the prediction differs from the answer key",
        fix=_KEY_MISMATCH_FIX,
        user_facing=False,
    ),
}
"""Every code, its severity, its trigger, and its fix template.

``docs/findings.md`` carries the same table with a worked example per code, and
the golden snapshot tests pin the exact rendered text of each."""


# ---------------------------------------------------------------------------
# Equivalence sets (spec section 11.1).
#
# Some declared/inferred disagreements are not errors. Omitting these would make
# the tool loudest on the pages that are most nearly correct, which is the
# fastest way to get an auditing tool uninstalled.
#
# Four sets, and the fourth is not in this table because it is not a pair.
# ---------------------------------------------------------------------------

EQUIVALENCE_SETS: Final[tuple[frozenset[Label], ...]] = (
    # A page that declares `name` on a control this tool reads as one half of a
    # split name has made a defensible choice, and so has a page that does the
    # reverse. Both fill correctly from a stored profile.
    frozenset({Label.NAME, Label.GIVEN_NAME, Label.FAMILY_NAME}),
    # `tel` is the whole number and `tel-national` is the number without its
    # dialling code. On a form with one telephone field they are the same field.
    frozenset({Label.TEL, Label.TEL_NATIONAL}),
    # `country` takes the code and `country-name` takes the name. Which one a
    # given select wants is a fact about its option values, not about the field.
    frozenset({Label.COUNTRY, Label.COUNTRY_NAME}),
    # The composite extra against either token a composite can correctly carry.
    # A single MM/YY input declaring `cc-exp` is correctly declared, and so is a
    # single full-address textarea declaring `street-address`; the extra label
    # exists to carry the structural fact, not to contradict the declaration
    # (spec section 7.2).
    frozenset({Label.COMPOSITE_UNSPLIT, Label.CC_EXP, Label.STREET_ADDRESS}),
)
"""The documented mapping consulted before ``WRONG_AUTOCOMPLETE`` fires.

The fourth equivalence spec section 11.1 names, "any declaration whose modifiers
differ but whose token matches", is not a pair of labels and so is not in this
table. It is handled by the audit engine comparing ``DeclaredAutocomplete.token``
rather than ``DeclaredAutocomplete.raw``: a declared ``shipping postal-code``
carries the token ``postal-code`` and the modifier ``shipping`` separately, so an
inferred ``postal-code`` matches it exactly and no equivalence lookup is needed.
Spec section 7.1 is emphatic that getting this wrong produces a flood of false
findings on precisely the well-built checkout pages that need them least, so
there is a test named for it."""

_EQUIVALENT_TO: Final[dict[Label, frozenset[Label]]] = {}
for _members in EQUIVALENCE_SETS:
    for _member in _members:
        _EQUIVALENT_TO[_member] = _EQUIVALENT_TO.get(_member, frozenset()) | _members


def equivalent(declared: Label, inferred: Label) -> bool:
    """Whether a declared token and an inferred label are the same claim.

    Three ways they can be. They are the same label. The inferred label is an
    extra whose correct declaration is the declared token, which is how the two
    split-expiry labels relate to the specification's month and year tokens
    (spec section 7.2). Or they share an equivalence set above.
    """
    if declared is inferred:
        return True
    if declaration_for(inferred) is declared:
        return True
    return inferred in _EQUIVALENT_TO.get(declared, frozenset())


def is_personal_data(label: Label) -> bool:
    """Whether a label names a field holding a person's own data.

    True for every specification token and for the three structural extras that
    stand in for one. False for ``UNKNOWN``, because the tool does not know, and
    false for ``NOT_AUTOFILLABLE``, because a search box is not personal data and
    ``autocomplete="off"`` on one is correct markup rather than a finding.
    """
    return label not in {Label.UNKNOWN, Label.NOT_AUTOFILLABLE}


@dataclass(frozen=True, slots=True)
class Finding:
    """One claim about one page, with the evidence that supports it.

    ``signals`` and ``confidence_display`` are not optional decoration. Law 1
    forbids emitting a finding without named evidence and a stated confidence or
    documented tier, so a finding that carries neither is a bug rather than a
    low-quality finding, and the audit engine asserts it before returning.

    ``confidence_display`` is a string rather than the raw float on purpose. For
    the rule engine it reads as a tier name, and printing the float behind a tier
    as a percentage would assert a frequency nothing has measured (spec section
    10.1). The float is kept in ``confidence`` for the run log, which is a
    machine's audience rather than a person's.
    """

    code: FindingCode
    severity: Severity
    selector: str
    fix: str
    signals: tuple[str, ...] = ()
    confidence: float | None = None
    confidence_display: str = ""
    label: str | None = None
    declared: str | None = None
    group_id: str | None = None
    context: Mapping[str, str] = field(default_factory=dict)
    suppressed_by: str | None = None
    """The configuration rule that suppressed this finding, when one did. A
    suppressed finding is retained and reported under its own key rather than
    dropped: a finding that vanishes without trace is how a config file becomes
    a way to lie to your own CI (spec section 14)."""

    @property
    def spec(self) -> FindingSpec:
        """The catalogue entry this finding instantiates."""
        return FINDING_SPECS[self.code]

    def to_json(self) -> dict[str, Any]:
        """Emit the plain JSON form used by the report and the run log."""
        payload: dict[str, Any] = {
            "code": self.code.value,
            "severity": self.severity.value,
            "selector": self.selector,
            "fix": self.fix,
            "signals": list(self.signals),
            "confidence": self.confidence,
            "confidence_display": self.confidence_display,
            "label": self.label,
            "declared": self.declared,
            "group_id": self.group_id,
        }
        if self.suppressed_by is not None:
            payload["suppressed_by"] = self.suppressed_by
        return payload


STRUCTURAL_CONFIDENCE: Final[str] = "structural"
"""What a finding displays instead of a confidence when it is not a claim about
what a control *means*.

Law 1 requires every finding to carry a confidence or a documented tier. For
``UNLABELED_FIELD`` and its kind there is no classification to be confident
about: the control has no label, and that is either true or false. Printing a
tier there would imply the tool was unsure about something it can see directly,
and printing nothing would leave the field blank in a report whose whole point is
that no field is ever blank. So it says what it is."""

CLASSIFICATION_DRIVEN: Final[frozenset[FindingCode]] = frozenset(
    {
        FindingCode.MISSING_AUTOCOMPLETE,
        FindingCode.WRONG_AUTOCOMPLETE,
        FindingCode.OFF_SPEC_TOKEN,
        FindingCode.AUTOCOMPLETE_OFF,
        FindingCode.COMPOSITE_FIELD,
        FindingCode.WRONG_INPUT_TYPE,
        FindingCode.LOW_CONFIDENCE,
        FindingCode.KEY_MISMATCH,
    }
)
"""The codes whose trigger depends on what the classifier concluded.

These carry the prediction's confidence and the rule signals that produced it.
The other seven depend only on how the control is built, and carry the structural
evidence below instead. The split is what lets law 1 be enforced as one rule
rather than as seven exceptions."""

SIGNAL_FOR: Final[dict[FindingCode, str]] = {
    FindingCode.MISSING_AUTOCOMPLETE: "declaration:absent",
    FindingCode.WRONG_AUTOCOMPLETE: "declaration:token-mismatch",
    FindingCode.OFF_SPEC_TOKEN: "declaration:off-spec",
    FindingCode.AUTOCOMPLETE_OFF: "declaration:off",
    FindingCode.UNLABELED_FIELD: "structure:no-accessible-label",
    FindingCode.PLACEHOLDER_AS_LABEL: "structure:placeholder-is-the-only-label",
    FindingCode.SPLIT_FIELD: "structure:split-expiry-group",
    FindingCode.COMPOSITE_FIELD: "declaration:absent",
    FindingCode.GENERIC_IDENTIFIER: "structure:generic-identifier",
    FindingCode.WRONG_INPUT_TYPE: "structure:input-attribute-mismatch",
    FindingCode.MISSING_NAME_ATTR: "structure:no-name-attribute",
    FindingCode.LOW_CONFIDENCE: "declaration:absent",
    FindingCode.UNDETECTABLE_FIELD: "structure:undetectable",
    FindingCode.EXTRACTION_INCOMPLETE: "extraction:settle-budget-expired",
    FindingCode.KEY_MISMATCH: "corpus:answer-key",
}
"""The evidence entry every finding of a code carries, whatever else it carries.

Without this a finding could be emitted with an empty ``signals`` list whenever
the classifier happened to match nothing, which is exactly the situation an
``UNLABELED_FIELD`` on a bare input is. Law 1 says an unattributed finding is a
bug, so the attribution is part of the catalogue rather than something the engine
hopes it has."""

UNKNOWN_TOKEN_ADVICE: Final[str] = "a token from the WHATWG autofill list"
"""What ``{label}`` renders as when a fix has to be given and the engine has no
confident label to suggest. It is text, so it lives here with the templates
rather than being assembled in a renderer."""

PLACEHOLDER_ID: Final[str] = "field-id"
"""What ``{id}`` renders as in the unlabeled-field fix when the control has no id
and no name. The advice is still actionable: the reader has to invent an id
anyway before they can point a label at it."""

UNDETECTABLE_REASON_TEXT: Final[dict[str, str]] = {
    "closed-shadow-root": "the control is inside a closed shadow root",
    "cross-origin-frame": (
        "the control is inside a cross-origin frame, which is how hosted payment "
        "fields are built on purpose"
    ),
    "canvas-region": "the only form-like element on this page is a canvas",
    "detached": "the control was removed from the document before it could be read",
    "timeout": "the control could not be read within the extraction budget",
}
"""One sentence per ``UndetectableReason``, written for a person.

Kept as data beside the templates for the same reason the templates are: three
renderers must agree, and the only way to guarantee that is for there to be one
copy of the words."""

UNDETECTABLE_FIX_OVERRIDES: Final[dict[str, str]] = {
    "cross-origin-frame": (
        "{reason}; this is not necessarily a defect. Autofill still works inside the "
        "frame, and the frame's own document is where its autocomplete attributes "
        "belong. Audit that document separately"
    ),
}
"""Where spec section 11.1's single fix template is wrong for one reason.

Spec section 9.6 is explicit that a hosted payment field behind a cross-origin
frame is common and correct and that the finding text must say so rather than
implying a defect. Spec section 11.1's template says "expose it in light DOM or
declare autocomplete on the host", which is sound advice for a closed shadow root
and nonsense for a frame the page does not own. The two sections conflict, the
more specific one wins, and the override is written down here rather than
improvised in a renderer."""

_TEMPLATE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "attribute",
        "confidence",
        "declared",
        "engine",
        "expected",
        "id",
        "label",
        "month_token",
        "reason",
        "selector",
        "year_token",
    }
)
"""Every placeholder any fix template may name.

The audit engine builds a context holding exactly these keys, so a template that
named a twelfth would raise on the first page that triggered it, in front of a
user, rather than at import. The assertion below moves that failure to import."""


def _placeholders(template: str) -> set[str]:
    """Return the ``{name}`` placeholders a template names."""
    import string

    return {
        name for _, name, _, _ in string.Formatter().parse(template) if name is not None and name
    }


assert len(FindingCode) == 15, "spec section 11.1 fixes the catalogue at fifteen codes"
assert set(FINDING_SPECS) == set(FindingCode), "every code needs a catalogue entry"
assert all(code is entry.code for code, entry in FINDING_SPECS.items()), (
    "a catalogue entry must be filed under its own code"
)
assert set(SEVERITY_ORDER) == set(Severity), "the severity order must name every severity"
assert all(_placeholders(entry.fix) <= _TEMPLATE_FIELDS for entry in FINDING_SPECS.values()), (
    "a fix template may only name a documented context field"
)
assert sum(1 for entry in FINDING_SPECS.values() if not entry.user_facing) == 1, (
    "KEY_MISMATCH is the only non user-facing code (spec section 11.2)"
)
assert all(
    _placeholders(override) <= _TEMPLATE_FIELDS for override in UNDETECTABLE_FIX_OVERRIDES.values()
), "an override may only name a documented context field"
assert set(UNDETECTABLE_FIX_OVERRIDES) <= set(UNDETECTABLE_REASON_TEXT), (
    "an override must be for a reason that has text"
)
assert set(SIGNAL_FOR) == set(FindingCode), "every code needs its own evidence entry"
assert set(FindingCode) >= CLASSIFICATION_DRIVEN, "only real codes may be classification driven"
