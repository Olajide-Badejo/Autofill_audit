"""The finding catalogue: severities, fix templates, and the equivalence sets.

Spec section 15's layer one asks for "fix-template formatting for every finding
code", and that is what the parametrised test here does: every template is
formatted with the full context the audit engine can supply, so a template that
names a field nobody provides fails here rather than on the one page in the world
that triggers it.
"""

from __future__ import annotations

import string

import pytest

from autofill_audit.audit.findings import (
    CLASSIFICATION_DRIVEN,
    EQUIVALENCE_SETS,
    FINDING_SPECS,
    SEVERITY_ORDER,
    SIGNAL_FOR,
    UNDETECTABLE_FIX_OVERRIDES,
    UNDETECTABLE_REASON_TEXT,
    Finding,
    FindingCode,
    Severity,
    at_or_above,
    equivalent,
    is_personal_data,
    severity_rank,
)
from autofill_audit.descriptors import UndetectableReason
from autofill_audit.taxonomy import ALL_LABELS, Label

FULL_CONTEXT = {
    "attribute": "type",
    "confidence": "rule tier HIGH",
    "declared": "zipcode",
    "engine": "rules",
    "expected": "email",
    "id": "field-id",
    "label": "postal-code",
    "month_token": "cc-exp-month",
    "reason": "the control is inside a closed shadow root",
    "selector": "#postcode",
    "year_token": "cc-exp-year",
}


def test_the_catalogue_holds_exactly_the_fifteen_codes() -> None:
    assert len(FindingCode) == 15
    assert set(FINDING_SPECS) == set(FindingCode)


@pytest.mark.parametrize("code", list(FindingCode), ids=lambda code: code.value)
def test_every_fix_template_formats_with_the_documented_context(code: FindingCode) -> None:
    """A template that named an undocumented field would raise in front of a user."""
    text = FINDING_SPECS[code].fix.format(**FULL_CONTEXT)
    assert text
    assert "{" not in text


@pytest.mark.parametrize("code", list(FindingCode), ids=lambda code: code.value)
def test_every_code_has_a_trigger_written_for_a_person(code: FindingCode) -> None:
    trigger = FINDING_SPECS[code].trigger
    assert trigger and trigger[0].islower()


@pytest.mark.parametrize("code", list(FindingCode), ids=lambda code: code.value)
def test_every_code_carries_its_own_evidence_entry(code: FindingCode) -> None:
    """Law 1: an unattributed finding is a bug, not a low-quality finding."""
    assert SIGNAL_FOR[code]
    assert ":" in SIGNAL_FOR[code]


def test_every_override_formats_too() -> None:
    for template in UNDETECTABLE_FIX_OVERRIDES.values():
        assert "{" not in template.format(**FULL_CONTEXT)


def test_every_undetectable_reason_has_text_written_for_a_person() -> None:
    """The enum is exhaustible, so the report can never print a bare enum value."""
    for reason in UndetectableReason:
        assert UNDETECTABLE_REASON_TEXT[reason.value]


def test_the_cross_origin_frame_text_does_not_imply_a_defect() -> None:
    """Spec section 9.6 is explicit, and spec section 11.1's template is not."""
    override = UNDETECTABLE_FIX_OVERRIDES["cross-origin-frame"]
    assert "not necessarily a defect" in override
    assert "on purpose" in UNDETECTABLE_REASON_TEXT["cross-origin-frame"]


# ---------------------------------------------------------------------------
# Severities.
# ---------------------------------------------------------------------------


def test_the_severity_order_runs_from_most_to_least_severe() -> None:
    assert SEVERITY_ORDER == (
        Severity.CRITICAL,
        Severity.WARNING,
        Severity.INFO,
        Severity.NOTE,
    )
    assert severity_rank(Severity.CRITICAL) < severity_rank(Severity.NOTE)


@pytest.mark.parametrize(
    ("severity", "threshold", "expected"),
    [
        (Severity.CRITICAL, Severity.CRITICAL, True),
        (Severity.WARNING, Severity.CRITICAL, False),
        (Severity.WARNING, Severity.WARNING, True),
        (Severity.NOTE, Severity.INFO, False),
        (Severity.INFO, Severity.NOTE, True),
    ],
)
def test_at_or_above_is_the_whole_of_the_failure_threshold(
    severity: Severity, threshold: Severity, expected: bool
) -> None:
    assert at_or_above(severity, threshold) is expected


def test_the_severities_of_the_catalogue_match_the_specification_table() -> None:
    expected = {
        FindingCode.MISSING_AUTOCOMPLETE: Severity.CRITICAL,
        FindingCode.WRONG_AUTOCOMPLETE: Severity.CRITICAL,
        FindingCode.OFF_SPEC_TOKEN: Severity.CRITICAL,
        FindingCode.AUTOCOMPLETE_OFF: Severity.WARNING,
        FindingCode.UNLABELED_FIELD: Severity.WARNING,
        FindingCode.PLACEHOLDER_AS_LABEL: Severity.WARNING,
        FindingCode.SPLIT_FIELD: Severity.WARNING,
        FindingCode.COMPOSITE_FIELD: Severity.WARNING,
        FindingCode.GENERIC_IDENTIFIER: Severity.INFO,
        FindingCode.WRONG_INPUT_TYPE: Severity.INFO,
        FindingCode.MISSING_NAME_ATTR: Severity.INFO,
        FindingCode.LOW_CONFIDENCE: Severity.NOTE,
        FindingCode.UNDETECTABLE_FIELD: Severity.WARNING,
        FindingCode.EXTRACTION_INCOMPLETE: Severity.INFO,
        FindingCode.KEY_MISMATCH: Severity.NOTE,
    }
    assert {code: FINDING_SPECS[code].severity for code in FindingCode} == expected


def test_key_mismatch_is_the_only_code_that_never_reaches_a_user() -> None:
    hidden = [code for code, entry in FINDING_SPECS.items() if not entry.user_facing]
    assert hidden == [FindingCode.KEY_MISMATCH]


# ---------------------------------------------------------------------------
# Equivalence (spec section 11.1).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("declared", "inferred"),
    [
        (Label.NAME, Label.GIVEN_NAME),
        (Label.NAME, Label.FAMILY_NAME),
        (Label.GIVEN_NAME, Label.NAME),
        (Label.TEL, Label.TEL_NATIONAL),
        (Label.TEL_NATIONAL, Label.TEL),
        (Label.COUNTRY, Label.COUNTRY_NAME),
        (Label.COUNTRY_NAME, Label.COUNTRY),
        (Label.CC_EXP, Label.COMPOSITE_UNSPLIT),
        (Label.STREET_ADDRESS, Label.COMPOSITE_UNSPLIT),
        (Label.CC_EXP_MONTH, Label.CC_EXP_SPLIT_MONTH),
        (Label.CC_EXP_YEAR, Label.CC_EXP_SPLIT_YEAR),
    ],
)
def test_the_documented_equivalences_hold(declared: Label, inferred: Label) -> None:
    assert equivalent(declared, inferred)


@pytest.mark.parametrize(
    ("declared", "inferred"),
    [
        (Label.NAME, Label.CC_NAME),
        (Label.ADDRESS_LINE1, Label.STREET_ADDRESS),
        (Label.ADDRESS_LEVEL1, Label.ADDRESS_LEVEL2),
        (Label.CC_NUMBER, Label.CC_CSC),
        (Label.NEW_PASSWORD, Label.CURRENT_PASSWORD),
    ],
)
def test_the_mistakes_real_templates_make_are_not_equivalences(
    declared: Label, inferred: Label
) -> None:
    """The corpus asserts these are errors, so making them equivalent would make
    the assertion unfalsifiable."""
    assert not equivalent(declared, inferred)


def test_every_label_is_equivalent_to_itself() -> None:
    for label in ALL_LABELS:
        assert equivalent(label, label)


def test_the_equivalence_sets_are_symmetric() -> None:
    for members in EQUIVALENCE_SETS:
        for first in members:
            for second in members:
                assert equivalent(first, second), (first, second)


def test_unknown_and_not_autofillable_are_not_personal_data() -> None:
    assert not is_personal_data(Label.UNKNOWN)
    assert not is_personal_data(Label.NOT_AUTOFILLABLE)
    assert is_personal_data(Label.POSTAL_CODE)
    assert is_personal_data(Label.CC_EXP_SPLIT_MONTH)


# ---------------------------------------------------------------------------
# The finding object.
# ---------------------------------------------------------------------------


def test_a_finding_serialises_the_keys_a_consumer_reads() -> None:
    finding = Finding(
        code=FindingCode.MISSING_AUTOCOMPLETE,
        severity=Severity.CRITICAL,
        selector="#a",
        fix='add autocomplete="email" to #a',
        signals=("declaration:absent", "label:email-words"),
        confidence=0.9,
        confidence_display="rule tier HIGH",
        label="email",
    )
    payload = finding.to_json()
    assert payload["code"] == "MISSING_AUTOCOMPLETE"
    assert payload["signals"] == ["declaration:absent", "label:email-words"]
    assert "suppressed_by" not in payload
    assert finding.spec.severity is Severity.CRITICAL


def test_a_suppressed_finding_carries_its_reason_into_the_document() -> None:
    finding = Finding(
        code=FindingCode.GENERIC_IDENTIFIER,
        severity=Severity.INFO,
        selector="#a",
        fix="give #a a meaningful name/id, or declare autocomplete",
        signals=("structure:generic-identifier",),
        confidence_display="structural",
        suppressed_by="vendor widget",
    )
    assert finding.to_json()["suppressed_by"] == "vendor widget"


def test_classification_driven_and_structural_partition_the_catalogue() -> None:
    structural = set(FindingCode) - CLASSIFICATION_DRIVEN
    assert structural
    assert CLASSIFICATION_DRIVEN & structural == set()
    assert CLASSIFICATION_DRIVEN | structural == set(FindingCode)


def test_no_template_names_a_field_outside_the_documented_set() -> None:
    """The same invariant the module asserts at import, restated as a test."""
    formatter = string.Formatter()
    for entry in FINDING_SPECS.values():
        named = {name for _, name, _, _ in formatter.parse(entry.fix) if name}
        assert named <= set(FULL_CONTEXT), entry.code
