"""The three renderers, on reports built without a browser.

The golden snapshots pin the exact bytes for a fixed fixture set. These are the
properties that hold for *any* report, and they are the ones worth stating as
sentences rather than as a diff: no percentages from a regex table, no composite
score, no external asset, no unescaped page text.
"""

from __future__ import annotations

import json

import pytest

from autofill_audit.audit.engine import AuditOptions, AuditReport, audit
from autofill_audit.audit.findings import FindingCode, Severity
from autofill_audit.audit.thresholds import load_thresholds
from autofill_audit.classify.rules import RuleClassifier
from autofill_audit.report import html_report, json_report, terminal
from builders import make_descriptor, make_result


def build(*descriptors: object, **kwargs: object) -> AuditReport:
    """Audit a page built out of descriptors."""
    result = make_result(*descriptors)  # type: ignore[arg-type]
    return audit(result, RuleClassifier(), AuditOptions(thresholds=load_thresholds(), **kwargs))  # type: ignore[arg-type]


@pytest.fixture
def report() -> AuditReport:
    """A report with something at every severity."""
    return build(
        make_descriptor(selector="#a", label="Email address", name="a", input_type="text"),
        make_descriptor(selector="#b", element_id="input7", document_index=1),
        make_descriptor(
            selector="#c", label="Name on card", name="c", declared="name", document_index=2
        ),
        make_descriptor(selector="#d", name="d1", context="Company", document_index=3),
    )


@pytest.fixture
def empty() -> AuditReport:
    """A report on a page that is correctly built."""
    return build(make_descriptor(selector="#a", label="Postcode", name="a", declared="postal-code"))


# ---------------------------------------------------------------------------
# JSON.
# ---------------------------------------------------------------------------


def test_the_json_report_is_versioned_and_names_its_engine(report: AuditReport) -> None:
    document = json.loads(json_report.render(report))
    assert document["schema_version"] == json_report.REPORT_SCHEMA_VERSION
    assert document["engine"]["engine"] == "rules"
    assert document["engine"]["confidence_kind"] == "tier"
    assert document["thresholds"]["basis"] == "rule-tier-band-mapping"


def test_the_json_descriptors_are_pruned_of_geometry(report: AuditReport) -> None:
    document = json.loads(json_report.render(report))
    assert document["descriptors"]
    assert all("bbox" not in item for item in document["descriptors"])
    assert all("is_visible" in item for item in document["descriptors"])


def test_the_json_summary_is_counts_and_never_a_score(report: AuditReport) -> None:
    summary = json.loads(json_report.render(report))["summary"]
    assert set(summary["counts"]) == {severity.value for severity in Severity}
    assert "score" not in summary
    assert "grade" not in summary
    assert summary["controls_declaring_autocomplete"] <= summary["controls_audited"]


def test_the_json_report_is_byte_identical_across_renders(report: AuditReport) -> None:
    assert json_report.render(report) == json_report.render(report)


def test_honeypots_travel_under_their_own_key() -> None:
    """A field count that disagrees with the developer's own markup is a report
    they stop trusting (spec section 9.6)."""
    hidden = make_descriptor(selector="#hp", name="hp", is_visible=False)
    result = make_result(
        make_descriptor(selector="#a", label="Postcode", name="a", declared="postal-code"),
        honeypots=(hidden,),
    )
    report = audit(result, RuleClassifier(), AuditOptions(thresholds=load_thresholds()))
    document = json.loads(json_report.render(report))
    assert [item["selector"] for item in document["honeypots"]] == ["#hp"]
    assert document["summary"]["honeypots_excluded"] == 1


def test_the_schema_describes_the_document_this_build_produces(report: AuditReport) -> None:
    schema = json_report.report_schema()
    document = json.loads(json_report.render(report))
    for key in schema["required"]:
        assert key in document
    assert set(schema["$defs"]["findingCodes"]) == {code.value for code in FindingCode}
    assert schema["properties"]["schema_version"]["const"] == document["schema_version"]


def test_the_schema_id_is_a_name_and_nothing_resolves_it() -> None:
    assert json_report.REPORT_SCHEMA_ID.endswith("/report/v1")


# ---------------------------------------------------------------------------
# Terminal.
# ---------------------------------------------------------------------------


def test_the_terminal_report_never_prints_a_percentage(report: AuditReport) -> None:
    """Printing "83%" from a regex table is a law 1 and a law 4 violation."""
    text = terminal.render(report)
    assert "%" not in text
    assert "rule tier" in text


def test_the_terminal_report_shows_counts_and_a_readiness_line(report: AuditReport) -> None:
    text = terminal.render(report)
    assert "autofill readiness" in text
    assert "controls declare autocomplete" in text
    for severity in Severity:
        assert severity.value in text


def test_the_terminal_report_says_the_thresholds_are_not_a_measurement(
    report: AuditReport,
) -> None:
    """Law 4: an estimate is labeled at the point of display."""
    assert "not probabilities" in terminal.render(report)


def test_the_terminal_report_is_deterministic_at_a_fixed_width(
    report: AuditReport,
) -> None:
    assert terminal.render(report, width=100) == terminal.render(report, width=100)
    assert terminal.render(report, width=60) != terminal.render(report, width=100)


def test_a_clean_page_is_told_so_rather_than_shown_an_empty_table(
    empty: AuditReport,
) -> None:
    text = terminal.render(empty)
    assert "No findings" in text


def test_every_finding_line_carries_its_evidence(report: AuditReport) -> None:
    text = terminal.render(report)
    assert text.count("evidence:") == len(report.findings)


# ---------------------------------------------------------------------------
# HTML.
# ---------------------------------------------------------------------------


def test_the_html_report_is_one_self_contained_file(report: AuditReport) -> None:
    document = html_report.render(report)
    assert document.startswith("<!doctype html>")
    assert "<style>" in document
    assert "<script" not in document.lower()
    assert "http://" not in document
    assert "https://" not in document
    assert "<link" not in document.lower()


def test_the_html_report_escapes_page_text() -> None:
    """An auditor that rendered markup from the page it audited would have a
    cross-site scripting hole in its own output."""
    nasty = make_descriptor(
        selector='#a"><img src=x onerror=alert(1)>',
        label="Postcode",
        name="a",
        declared="<script>alert(1)</script>",
    )
    document = html_report.render(build(nasty))
    # The dangerous characters are gone, so the payload survives only as inert
    # text. That is the correct outcome: the report has to quote what the page
    # said, and quoting it safely is the whole job.
    assert "<script>alert(1)</script>" not in document
    assert "<img" not in document
    assert "&lt;script&gt;" in document
    assert "&quot;&gt;&lt;img" in document


def test_the_html_report_names_the_engine_in_its_footer(report: AuditReport) -> None:
    document = html_report.render(report)
    assert "rule_table_version" in document
    assert "not probabilities" in document


def test_the_html_report_lists_suppressed_findings_with_their_reasons() -> None:
    from autofill_audit.audit.engine import Suppression

    report = build(
        make_descriptor(selector="#a", element_id="input7"),
        suppressions=(Suppression(code=FindingCode.GENERIC_IDENTIFIER, reason="vendor widget"),),
    )
    document = html_report.render(report)
    assert "suppressed by configuration" in document
    assert "vendor widget" in document


def test_all_three_renderers_agree_about_the_counts(report: AuditReport) -> None:
    """They format the same findings and never decide anything of their own."""
    document = json.loads(json_report.render(report))
    text = terminal.render(report)
    markup = html_report.render(report)
    critical = document["summary"]["counts"]["critical"]
    assert f"critical ({critical})" in text
    assert f"critical ({critical})" in markup
