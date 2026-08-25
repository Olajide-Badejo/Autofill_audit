"""The decision procedure of spec section 11.2, branch by branch.

Every ordered branch of the primary chain gets a test, every secondary finding
gets a test, and the three places this implementation had to read the
specification rather than transcribe it get a test naming the reading.
"""

from __future__ import annotations

import pytest

from autofill_audit.audit.engine import AuditOptions, Suppression, audit
from autofill_audit.audit.findings import (
    CLASSIFICATION_DRIVEN,
    FindingCode,
    Severity,
    equivalent,
)
from autofill_audit.audit.thresholds import load_thresholds
from autofill_audit.classify.rules import RuleClassifier
from autofill_audit.descriptors import ExtractionResult, GroupRole
from autofill_audit.taxonomy import Label
from builders import make_descriptor, make_result

MONTHS = tuple(f"{number:02d}" for number in range(1, 13))
YEARS = tuple(str(year) for year in range(2026, 2037))


def run(result: ExtractionResult, **kwargs: object) -> object:
    """Audit one built result with the committed thresholds."""
    options = AuditOptions(thresholds=load_thresholds(), **kwargs)  # type: ignore[arg-type]
    return audit(result, RuleClassifier(), options)


def codes(result: ExtractionResult, **kwargs: object) -> list[FindingCode]:
    """The finding codes one built result produces, in report order."""
    report = run(result, **kwargs)
    return [finding.code for finding in report.findings]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The modifier rule (spec section 7.1). This is the test spec section 7.1 asks
# for by name, and it is the single most expensive thing to get wrong.
# ---------------------------------------------------------------------------


@pytest.mark.label("postal-code")
def test_a_shipping_modifier_on_a_correct_token_is_a_match_not_a_mismatch() -> None:
    """``shipping postal-code`` declared against ``postal-code`` inferred.

    Spec section 7.1: this is a **match**. A tool that compared the raw attribute
    value would raise a CRITICAL on every well-built checkout in the world.
    """
    descriptor = make_descriptor(
        selector="#shipping-postcode",
        label="Postcode",
        name="shipping_postcode",
        declared="shipping postal-code",
    )
    report = run(make_result(descriptor))
    assert report.predictions[0].label == Label.POSTAL_CODE.value  # type: ignore[attr-defined]
    assert descriptor.declared.modifiers == ("shipping",)
    assert descriptor.declared.token == Label.POSTAL_CODE.value
    assert codes(make_result(descriptor)) == []


@pytest.mark.parametrize(
    "raw",
    [
        "shipping postal-code",
        "billing postal-code",
        "section-blue shipping postal-code",
        "postal-code shipping",
    ],
)
def test_no_arrangement_of_modifiers_produces_a_wrong_autocomplete(raw: str) -> None:
    """Including the one the HTML grammar puts in the wrong order.

    Real pages get the token order wrong and still meant something. Refusing to
    read such a value would turn a reportable mistake into an invisible one, and
    reporting it as a mismatch would be worse.
    """
    descriptor = make_descriptor(label="Postcode", name="postcode", declared=raw)
    assert FindingCode.WRONG_AUTOCOMPLETE not in codes(make_result(descriptor))


# ---------------------------------------------------------------------------
# The primary chain, in the order spec section 11.2 writes it.
# ---------------------------------------------------------------------------


def test_an_undetectable_descriptor_short_circuits_the_chain() -> None:
    """A blind spot is the finding. Nothing else about it is reportable."""
    descriptor = make_descriptor(
        selector="frame[#hosted]",
        undetectable_reason="cross-origin-frame",
        input_type=None,
        form_index=None,
    )
    assert codes(make_result(descriptor)) == [FindingCode.UNDETECTABLE_FIELD]


def test_a_cross_origin_frame_is_not_reported_as_a_defect() -> None:
    """Spec section 9.6 requires the text to say so, and 11.1's template does not."""
    descriptor = make_descriptor(
        selector="frame[#hosted]", undetectable_reason="cross-origin-frame", form_index=None
    )
    report = run(make_result(descriptor))
    fix = report.findings[0].fix  # type: ignore[attr-defined]
    assert "not necessarily a defect" in fix
    assert "expose it in light DOM" not in fix


@pytest.mark.label("tel")
def test_autocomplete_off_on_a_personal_data_field() -> None:
    """And it stops the chain, so no second contradictory fix is emitted."""
    descriptor = make_descriptor(
        label="Phone number", name="phone", input_type="tel", inputmode="tel", declared="off"
    )
    found = codes(make_result(descriptor))
    assert FindingCode.AUTOCOMPLETE_OFF in found
    assert FindingCode.MISSING_AUTOCOMPLETE not in found


@pytest.mark.label("NOT_AUTOFILLABLE")
def test_autocomplete_off_on_a_search_box_is_correct_markup() -> None:
    """The branch does not match, and the chain continues to say nothing."""
    descriptor = make_descriptor(label="Search", name="q", input_type="search", declared="off")
    assert codes(make_result(descriptor)) == []


def test_an_off_spec_token_stops_the_chain_and_quotes_what_was_written() -> None:
    descriptor = make_descriptor(label="Postcode", name="zip", declared="zipcode")
    report = run(make_result(descriptor))
    finding = report.findings[0]  # type: ignore[attr-defined]
    assert finding.code is FindingCode.OFF_SPEC_TOKEN
    assert 'autocomplete="zipcode"' in finding.fix
    assert 'use "postal-code"' in finding.fix


def test_an_empty_autocomplete_is_reported_rather_than_ignored() -> None:
    """Spec section 15's malformed-input list requires a diagnostic for this."""
    descriptor = make_descriptor(label="Postcode", name="zip", declared="")
    assert FindingCode.OFF_SPEC_TOKEN in codes(make_result(descriptor))


def test_modifiers_with_no_field_name_are_off_spec() -> None:
    """``autocomplete="shipping"`` names no field and is not a valid value."""
    descriptor = make_descriptor(label="Postcode", name="zip", declared="shipping")
    assert FindingCode.OFF_SPEC_TOKEN in codes(make_result(descriptor))


def test_a_confident_disagreement_with_a_declaration_is_a_critical() -> None:
    descriptor = make_descriptor(label="Name on card", name="holder", declared="name")
    report = run(make_result(descriptor))
    finding = report.findings[0]  # type: ignore[attr-defined]
    assert finding.code is FindingCode.WRONG_AUTOCOMPLETE
    assert finding.severity is Severity.CRITICAL
    assert 'change to autocomplete="cc-name"' in finding.fix


def test_a_mid_confidence_disagreement_leaves_the_declaration_alone() -> None:
    """The asymmetry of spec section 11.2, stated as a test.

    The identifier says one thing, the declaration says another, and the
    identifier tier is below the high threshold. A developer stated an intent;
    a classifier that is not confident is not evidence against it.
    """
    descriptor = make_descriptor(
        name="company", declared="organization", title="Employer", input_type="text"
    )
    assert FindingCode.WRONG_AUTOCOMPLETE not in codes(make_result(descriptor))


def test_a_valid_token_outside_this_taxonomy_is_never_adjudicated() -> None:
    """``address-level3`` is valid HTML and is not a label this tool predicts.

    Reporting it as off specification would be the tool being wrong about the
    specification it is named after (P2's handoff is emphatic about this), and
    reporting it as a mismatch would be a claim the label space cannot support.
    """
    descriptor = make_descriptor(label="Town or city", name="city", declared="address-level3")
    assert descriptor.declared.is_off_spec is False
    assert codes(make_result(descriptor)) == []


@pytest.mark.label("COMPOSITE_UNSPLIT")
def test_a_composite_with_the_right_declaration_is_silent() -> None:
    """The reading of spec section 11.1 that makes the clean tier hold."""
    descriptor = make_descriptor(label="Expiry (MM/YY)", name="exp", maxlength=5, declared="cc-exp")
    assert codes(make_result(descriptor)) == []
    assert equivalent(Label.CC_EXP, Label.COMPOSITE_UNSPLIT)


def test_a_full_address_textarea_is_told_to_declare_street_address() -> None:
    descriptor = make_descriptor(label="Full address", name="addr", tag="textarea", input_type=None)
    report = run(make_result(descriptor))
    finding = next(
        item
        for item in report.findings
        if item.code is FindingCode.COMPOSITE_FIELD  # type: ignore[attr-defined]
    )
    assert 'autocomplete="street-address"' in finding.fix


def test_an_unknown_with_a_label_produces_no_primary_finding() -> None:
    """Nothing is claimed about a control the table could not name."""
    descriptor = make_descriptor(label="Reference", name="ref")
    found = codes(make_result(descriptor))
    assert FindingCode.MISSING_AUTOCOMPLETE not in found
    assert FindingCode.UNLABELED_FIELD not in found


def test_a_low_confidence_inference_becomes_a_note_not_a_critical() -> None:
    descriptor = make_descriptor(name="q1", context="Company")
    report = run(make_result(descriptor))
    note = next(
        item
        for item in report.findings
        if item.code is FindingCode.LOW_CONFIDENCE  # type: ignore[attr-defined]
    )
    assert note.severity is Severity.NOTE
    assert "organization" in note.fix


# ---------------------------------------------------------------------------
# Secondary findings.
# ---------------------------------------------------------------------------


def test_unlabeled_and_placeholder_as_label_are_mutually_exclusive() -> None:
    """Spec section 11.2's ``elif``. Two names for one problem is one too many."""
    bare = codes(make_result(make_descriptor(name="a1")))
    placeholder = codes(make_result(make_descriptor(name="a1", placeholder="Full name")))
    assert FindingCode.UNLABELED_FIELD in bare
    assert FindingCode.PLACEHOLDER_AS_LABEL not in bare
    assert FindingCode.PLACEHOLDER_AS_LABEL in placeholder
    assert FindingCode.UNLABELED_FIELD not in placeholder


def test_unlabeled_field_is_emitted_once_even_when_both_paths_reach_it() -> None:
    """The ``UNKNOWN`` branch and the secondary pass make the same claim."""
    found = codes(make_result(make_descriptor(name="q9")))
    assert found.count(FindingCode.UNLABELED_FIELD) == 1


def test_a_title_attribute_is_not_a_label() -> None:
    """Spec section 11.1 names four sources and ``title`` is not one of them."""
    descriptor = make_descriptor(name="a1", title="Full name")
    assert FindingCode.UNLABELED_FIELD in codes(make_result(descriptor))


def test_generic_identifier_needs_both_a_generic_name_and_no_label() -> None:
    labelled = make_descriptor(label="Full name", element_id="input7", name="input7")
    bare = make_descriptor(element_id="input7", name="input7")
    assert FindingCode.GENERIC_IDENTIFIER not in codes(make_result(labelled))
    assert FindingCode.GENERIC_IDENTIFIER in codes(make_result(bare))


@pytest.mark.label("email")
def test_wrong_input_type_fires_on_an_email_field_typed_as_text() -> None:
    descriptor = make_descriptor(label="Email address", name="email", input_type="text")
    report = run(make_result(descriptor))
    finding = next(
        item
        for item in report.findings
        if item.code is FindingCode.WRONG_INPUT_TYPE  # type: ignore[attr-defined]
    )
    assert finding.severity is Severity.INFO
    assert 'set type="email"' in finding.fix


def test_a_tel_field_typed_as_tel_satisfies_the_inputmode_expectation() -> None:
    """The advice is about the keypad, and ``type="tel"`` already produces it."""
    descriptor = make_descriptor(label="Phone number", name="phone", input_type="tel")
    assert FindingCode.WRONG_INPUT_TYPE not in codes(make_result(descriptor))


def test_missing_name_attr_only_fires_inside_a_form() -> None:
    inside = make_descriptor(label="Full name", form_index=0)
    outside = make_descriptor(label="Full name", form_index=None)
    assert FindingCode.MISSING_NAME_ATTR in codes(make_result(inside))
    assert FindingCode.MISSING_NAME_ATTR not in codes(make_result(outside))


@pytest.mark.label("CC_EXP_SPLIT_MONTH")
def test_split_field_fires_once_per_group_and_not_once_per_member() -> None:
    month = make_descriptor(
        selector="#mm",
        label="Month",
        name="mm",
        tag="select",
        input_type=None,
        option_labels=MONTHS,
        option_values=MONTHS,
        group_role=GroupRole.CC_EXP_MONTH,
        group_id="expiry-1",
        document_index=0,
    )
    year = make_descriptor(
        selector="#yy",
        label="Year",
        name="yy",
        tag="select",
        input_type=None,
        option_labels=YEARS,
        option_values=YEARS,
        group_role=GroupRole.CC_EXP_YEAR,
        group_id="expiry-1",
        document_index=1,
    )
    found = codes(make_result(month, year))
    assert found.count(FindingCode.SPLIT_FIELD) == 1


@pytest.mark.label("CC_EXP_SPLIT_YEAR")
def test_a_fully_declared_split_pair_produces_no_split_field() -> None:
    month = make_descriptor(
        selector="#mm",
        label="Month",
        name="mm",
        tag="select",
        input_type=None,
        option_labels=MONTHS,
        option_values=MONTHS,
        group_role=GroupRole.CC_EXP_MONTH,
        group_id="expiry-1",
        declared="cc-exp-month",
    )
    year = make_descriptor(
        selector="#yy",
        label="Year",
        name="yy",
        tag="select",
        input_type=None,
        option_labels=YEARS,
        option_values=YEARS,
        group_role=GroupRole.CC_EXP_YEAR,
        group_id="expiry-1",
        document_index=1,
        declared="cc-exp-year",
    )
    assert codes(make_result(month, year)) == []


# ---------------------------------------------------------------------------
# Report level.
# ---------------------------------------------------------------------------


def test_findings_are_ordered_by_document_position_then_severity() -> None:
    first = make_descriptor(selector="#a", name="a1", document_index=0)
    second = make_descriptor(
        selector="#b", label="Email address", name="b", input_type="text", document_index=1
    )
    report = run(make_result(first, second))
    order = [(finding.selector, finding.code) for finding in report.findings]  # type: ignore[attr-defined]
    assert [selector for selector, _ in order] == ["#a", "#b", "#b"]
    assert order[0][1] is FindingCode.UNLABELED_FIELD
    # Within one control, the more severe finding comes first.
    assert order[1][1] is FindingCode.MISSING_AUTOCOMPLETE
    assert order[2][1] is FindingCode.WRONG_INPUT_TYPE


def test_two_audits_of_one_page_produce_identical_findings() -> None:
    """The property the golden snapshots depend on."""
    page = make_result(
        make_descriptor(selector="#a", name="a1"),
        make_descriptor(selector="#b", label="Card number", name="b", document_index=1),
    )
    assert codes(page) == codes(page)


def test_suppression_hides_a_finding_and_keeps_the_reason() -> None:
    descriptor = make_descriptor(element_id="input7", name="input7")
    report = run(
        make_result(descriptor),
        suppressions=(
            Suppression(
                code=FindingCode.GENERIC_IDENTIFIER, reason="a third party widget we do not own"
            ),
        ),
    )
    assert FindingCode.GENERIC_IDENTIFIER not in [f.code for f in report.findings]  # type: ignore[attr-defined]
    hidden = report.suppressed  # type: ignore[attr-defined]
    assert [item.code for item in hidden] == [FindingCode.GENERIC_IDENTIFIER]
    assert hidden[0].suppressed_by == "a third party widget we do not own"


def test_a_selector_scoped_suppression_leaves_other_controls_alone() -> None:
    one = make_descriptor(selector="#input7", element_id="input7", name="input7")
    two = make_descriptor(selector="#input8", element_id="input8", name="input8", document_index=1)
    report = run(
        make_result(one, two),
        suppressions=(
            Suppression(
                code=FindingCode.GENERIC_IDENTIFIER, selector="#input7", reason="known widget"
            ),
        ),
    )
    remaining = [f.selector for f in report.findings if f.code is FindingCode.GENERIC_IDENTIFIER]  # type: ignore[attr-defined]
    assert remaining == ["#input8"]


def test_honeypots_are_set_aside_unless_asked_for() -> None:
    visible = make_descriptor(selector="#a", label="Email address", name="a", input_type="email")
    hidden = make_descriptor(selector="#hp", name="hp", is_visible=False, document_index=1)
    page = make_result(visible, honeypots=(hidden,))
    assert FindingCode.UNLABELED_FIELD not in codes(page)
    assert FindingCode.UNLABELED_FIELD in codes(page, include_hidden=True)


def test_the_readiness_line_is_a_count_and_excludes_blind_spots() -> None:
    declared = make_descriptor(selector="#a", label="Postcode", name="a", declared="postal-code")
    undeclared = make_descriptor(selector="#b", label="Town or city", name="b", document_index=1)
    blind = make_descriptor(
        selector="frame[#f]", undetectable_reason="cross-origin-frame", document_index=2
    )
    report = run(make_result(declared, undeclared, blind))
    assert report.readiness() == (1, 2)  # type: ignore[attr-defined]


def test_the_exit_code_moves_with_the_failure_threshold() -> None:
    descriptor = make_descriptor(name="a1")
    report = run(make_result(descriptor))
    assert report.exit_code(Severity.CRITICAL) == 0  # type: ignore[attr-defined]
    assert report.exit_code(Severity.WARNING) == 1  # type: ignore[attr-defined]
    assert report.exit_code(None) == 0  # type: ignore[attr-defined]


def test_every_finding_carries_evidence_and_a_stated_confidence() -> None:
    """Law 1, asserted over a page that reaches most of the catalogue."""
    page = make_result(
        make_descriptor(selector="#a", label="Email address", name="a", input_type="text"),
        make_descriptor(selector="#b", element_id="input7", document_index=1),
        make_descriptor(
            selector="#c", label="Name on card", name="c", declared="name", document_index=2
        ),
    )
    report = run(page)
    for finding in report.findings:  # type: ignore[attr-defined]
        assert finding.signals, finding.code
        assert finding.confidence_display, finding.code
        if finding.code in CLASSIFICATION_DRIVEN:
            assert finding.confidence is not None, finding.code


def test_the_answer_key_never_changes_a_user_facing_finding() -> None:
    """Corpus mode is a test, not an oracle the product depends on."""
    descriptor = make_descriptor(selector="#a", label="Postcode", name="a")
    page = make_result(descriptor)
    plain = run(page)
    with_key = run(page, answer_key={"#a": Label.ADDRESS_LEVEL2.value})
    assert [f.code for f in plain.findings] == [f.code for f in with_key.findings]  # type: ignore[attr-defined]
    assert [f.code for f in with_key.evaluation] == [FindingCode.KEY_MISMATCH]  # type: ignore[attr-defined]
    assert with_key.evaluation[0].fix.startswith("answer key says address-level2")  # type: ignore[attr-defined]
