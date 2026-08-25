"""Law 2 clause (d): every taxonomy label is asserted by at least one test.

Spec section 7.3 clause 4 asks for an **end-to-end finding** that depends on the
label, not merely a classification. So each case here builds a control, runs the
whole decision procedure over it, and asserts the finding the label produces:

- a specification token with no declaration produces ``MISSING_AUTOCOMPLETE``
  whose fix names that exact token, which is the claim the label is *for*;
- a split-expiry label produces the same finding naming the specification's
  month or year token, because the extra label carries structure rather than a
  different declaration (spec section 7.2);
- ``COMPOSITE_UNSPLIT`` produces ``COMPOSITE_FIELD``;
- ``NOT_AUTOFILLABLE`` produces no missing-declaration finding at all, which is
  the whole reason it exists: without it the engine would tell a developer to
  put ``autocomplete`` on their search box;
- ``UNKNOWN`` produces ``UNLABELED_FIELD`` and never a confident claim, which is
  law 1's escape hatch working.

``scripts/check_reachability.py`` collects the ``label`` markers below and fails
the build on any taxonomy label that no test carries. The marker is therefore
load bearing: adding a case without it, or adding a label without a case, is a
red build rather than a gap nobody notices.
"""

from __future__ import annotations

import pytest

from autofill_audit.audit.engine import AuditOptions, audit
from autofill_audit.audit.findings import FindingCode
from autofill_audit.audit.thresholds import load_thresholds
from autofill_audit.classify.rules import RuleClassifier
from autofill_audit.descriptors import FieldDescriptor, GroupRole
from autofill_audit.taxonomy import ALL_LABELS, Label, declaration_for
from builders import make_descriptor, make_result

MONTHS = tuple(f"{number:02d}" for number in range(1, 13))
YEARS = tuple(str(year) for year in range(2026, 2037))


def _case(label: Label, descriptor: FieldDescriptor) -> pytest.param:  # type: ignore[valid-type]
    """One label case, tagged with the label it is the evidence for."""
    return pytest.param(label, descriptor, id=label.value, marks=pytest.mark.label(label.value))


CASES = [
    _case(Label.NAME, make_descriptor(label="Full name")),
    _case(Label.GIVEN_NAME, make_descriptor(label="First name")),
    _case(Label.ADDITIONAL_NAME, make_descriptor(label="Middle name")),
    _case(Label.FAMILY_NAME, make_descriptor(label="Surname")),
    _case(Label.HONORIFIC_PREFIX, make_descriptor(label="Title")),
    _case(Label.HONORIFIC_SUFFIX, make_descriptor(label="Suffix")),
    _case(Label.NICKNAME, make_descriptor(label="Display name")),
    _case(Label.EMAIL, make_descriptor(label="Email address", input_type="email")),
    _case(Label.TEL, make_descriptor(label="Phone number", input_type="tel", inputmode="tel")),
    _case(Label.TEL_COUNTRY_CODE, make_descriptor(label="Country code")),
    _case(Label.TEL_NATIONAL, make_descriptor(label="Rufnummer")),
    _case(Label.TEL_EXTENSION, make_descriptor(label="Extension")),
    _case(Label.URL, make_descriptor(label="Website", input_type="url")),
    _case(Label.STREET_ADDRESS, make_descriptor(label="Address")),
    _case(Label.ADDRESS_LINE1, make_descriptor(label="Address line 1")),
    _case(Label.ADDRESS_LINE2, make_descriptor(label="Apartment, suite, unit")),
    _case(Label.ADDRESS_LINE3, make_descriptor(label="Address line 3")),
    _case(Label.ADDRESS_LEVEL2, make_descriptor(label="Town or city")),
    _case(Label.ADDRESS_LEVEL1, make_descriptor(label="County")),
    _case(Label.POSTAL_CODE, make_descriptor(label="Postcode")),
    _case(Label.COUNTRY, make_descriptor(label="Country")),
    _case(Label.COUNTRY_NAME, make_descriptor(label="Country name")),
    _case(Label.ORGANIZATION, make_descriptor(label="Company")),
    _case(Label.CC_NAME, make_descriptor(label="Name on card")),
    _case(
        Label.CC_NUMBER,
        make_descriptor(label="Card number", inputmode="numeric", maxlength=19),
    ),
    _case(Label.CC_EXP, make_descriptor(label="Expiry date", input_type="month")),
    _case(Label.CC_EXP_MONTH, make_descriptor(label="Expiry month", inputmode="numeric")),
    _case(Label.CC_EXP_YEAR, make_descriptor(label="Expiry year", inputmode="numeric")),
    _case(Label.CC_CSC, make_descriptor(label="Security code", inputmode="numeric")),
    _case(Label.CC_TYPE, make_descriptor(label="Card type", tag="select", input_type=None)),
    _case(Label.TRANSACTION_AMOUNT, make_descriptor(label="Amount", input_type="number")),
    _case(Label.USERNAME, make_descriptor(label="Username")),
    _case(Label.NEW_PASSWORD, make_descriptor(label="Confirm password", input_type="password")),
    _case(
        Label.CURRENT_PASSWORD,
        make_descriptor(label="Current password", input_type="password"),
    ),
    _case(
        Label.ONE_TIME_CODE,
        make_descriptor(label="Verification code", inputmode="numeric"),
    ),
    _case(Label.BDAY, make_descriptor(label="Date of birth", input_type="date")),
    _case(Label.SEX, make_descriptor(label="Gender", tag="select", input_type=None)),
    _case(
        Label.CC_EXP_SPLIT_MONTH,
        make_descriptor(
            label="Month",
            tag="select",
            input_type=None,
            option_labels=MONTHS,
            option_values=MONTHS,
            group_role=GroupRole.CC_EXP_MONTH,
            group_id="expiry-1",
        ),
    ),
    _case(
        Label.CC_EXP_SPLIT_YEAR,
        make_descriptor(
            label="Year",
            tag="select",
            input_type=None,
            option_labels=YEARS,
            option_values=YEARS,
            group_role=GroupRole.CC_EXP_YEAR,
            group_id="expiry-1",
        ),
    ),
    _case(
        Label.COMPOSITE_UNSPLIT,
        make_descriptor(label="Expiry (MM/YY)", maxlength=5),
    ),
    _case(Label.NOT_AUTOFILLABLE, make_descriptor(label="Search", input_type="search")),
    _case(Label.UNKNOWN, make_descriptor(name="q7")),
]


def _audit(descriptor: FieldDescriptor) -> list[FindingCode]:
    """Run the whole decision procedure over one control."""
    report = audit(
        make_result(descriptor),
        RuleClassifier(),
        AuditOptions(thresholds=load_thresholds()),
    )
    return [finding.code for finding in report.findings]


@pytest.mark.parametrize(("label", "descriptor"), CASES)
def test_every_label_drives_an_end_to_end_finding(
    label: Label, descriptor: FieldDescriptor
) -> None:
    """The finding a label produces is the claim the label exists to make."""
    report = audit(
        make_result(descriptor),
        RuleClassifier(),
        AuditOptions(thresholds=load_thresholds()),
    )
    predicted = report.predictions[0]
    codes = [finding.code for finding in report.findings]

    if label is Label.UNKNOWN:
        assert predicted.label == Label.UNKNOWN.value
        assert predicted.confidence == 0.0, "law 1: the default branch is never confident"
        assert FindingCode.UNLABELED_FIELD in codes
        assert FindingCode.MISSING_AUTOCOMPLETE not in codes
        return

    assert predicted.label == label.value, f"expected {label.value}, got {predicted.label}"

    if label is Label.NOT_AUTOFILLABLE:
        assert FindingCode.MISSING_AUTOCOMPLETE not in codes
        assert FindingCode.LOW_CONFIDENCE not in codes
        return

    if label is Label.COMPOSITE_UNSPLIT:
        assert FindingCode.COMPOSITE_FIELD in codes
        return

    token = declaration_for(label)
    assert token is not None
    assert FindingCode.MISSING_AUTOCOMPLETE in codes
    fix = next(
        finding.fix
        for finding in report.findings
        if finding.code is FindingCode.MISSING_AUTOCOMPLETE
    )
    assert f'autocomplete="{token.value}"' in fix


def test_the_case_table_covers_the_whole_taxonomy() -> None:
    """A label added to the taxonomy without a case here fails immediately.

    ``check_reachability.py`` enforces the same thing across the whole suite, in
    CI. This is the same claim asserted locally, so that adding a label and
    running the tests tells you at once rather than after a push.
    """
    covered = {case.values[0] for case in CASES}
    assert covered == ALL_LABELS, sorted(
        label.value for label in ALL_LABELS.symmetric_difference(covered)
    )


def test_a_declared_field_produces_no_missing_autocomplete() -> None:
    """The other half of every case above: a correct declaration is silent."""
    descriptor = make_descriptor(label="Postcode", name="postcode", declared="postal-code")
    assert _audit(descriptor) == []
