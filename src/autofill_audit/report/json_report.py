"""The machine-readable report at a versioned schema (spec section 11.4).

This is the CI-consumable artefact, and it is the only renderer whose shape is a
promise to a program rather than to a person. Two properties follow from that and
both are enforced by tests.

**It is a pure function of the page, the engine, and the configuration.** Two
runs over one page produce byte-identical JSON, so a diff in a pipeline means
something about the page changed. The one exception is ``timing_ms``, which is a
measurement of the run rather than a fact about the page, and the golden
snapshots pin fixed values into it for that reason.

**Suppressed findings appear, with their reasons.** A finding that vanished
without trace would make a config file a way to lie to your own CI (spec section
14), so ``suppressed`` carries the whole finding plus the rule that hid it, and a
reader can see exactly what was decided not to matter.

Descriptors are included and are **pruned of geometry**: the bounding box is the
one member that depends on the fonts a machine has and the window a browser
opened, so committing it would commit a flake. ``is_visible``, which is what the
box is *for*, stays.

``--json-schema`` prints ``report_schema()``, which is built from the same enums
the renderer uses. A schema maintained by hand beside a renderer is a schema that
describes last month's renderer.
"""

from __future__ import annotations

import json
from typing import Any, Final

from autofill_audit import __version__
from autofill_audit.audit.engine import AuditReport
from autofill_audit.audit.findings import (
    FINDING_SPECS,
    SEVERITY_ORDER,
    Finding,
    FindingCode,
    Severity,
)
from autofill_audit.descriptors import FieldDescriptor

__all__ = [
    "REPORT_SCHEMA_ID",
    "REPORT_SCHEMA_VERSION",
    "TOOL_NAME",
    "build",
    "render",
    "report_schema",
]

REPORT_SCHEMA_VERSION: Final[int] = 1
"""Bumped when a consumer written against the previous version would break.

Adding a key does not bump it. Removing one, renaming one, or changing what one
means does, and every bump is a CHANGELOG entry."""

REPORT_SCHEMA_ID: Final[str] = "https://github.com/Olajide-Badejo/autofill-audit/report/v1"
"""The ``$id`` of the printed schema. It is a name, not a URL to fetch: nothing in
this tool ever resolves it, because a report renderer that made a network request
at render time would be a report renderer that fails offline."""

TOOL_NAME: Final[str] = "autofill-audit"

_GEOMETRY_KEY: Final[str] = "bbox"
"""The one descriptor member pruned from the report (spec section 11.4)."""


def _descriptor(descriptor: FieldDescriptor) -> dict[str, Any]:
    """One descriptor, pruned of geometry."""
    payload = descriptor.to_json()
    payload.pop(_GEOMETRY_KEY, None)
    return payload


def _findings(findings: tuple[Finding, ...]) -> list[dict[str, Any]]:
    """A finding list in report order."""
    return [finding.to_json() for finding in findings]


def build(report: AuditReport) -> dict[str, Any]:
    """Assemble the report document."""
    counts = report.counts()
    declared, audited = report.readiness()
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool": {"name": TOOL_NAME, "version": __version__},
        "target": report.url,
        "engine": dict(report.engine),
        "thresholds": {} if report.thresholds is None else report.thresholds.describe(),
        "summary": {
            "counts": {severity.value: counts[severity] for severity in SEVERITY_ORDER},
            "findings": len(report.findings),
            "suppressed": len(report.suppressed),
            "controls_audited": audited,
            "controls_declaring_autocomplete": declared,
            "controls_seen": report.controls_seen,
            "honeypots_excluded": len(report.honeypots),
            "frames": report.frame_count,
            "truncated": report.truncated,
        },
        "findings": _findings(report.findings),
        "suppressed": _findings(report.suppressed),
        "page_notes": list(report.page_notes),
        "canvas_regions": [region.to_json() for region in report.canvas_regions],
        "descriptors": [_descriptor(item) for item in report.fields],
        "honeypots": [_descriptor(item) for item in report.honeypots],
        "timing_ms": dict(report.timing_ms),
    }


def render(report: AuditReport, *, indent: int = 2) -> str:
    """Render the report as JSON text, newline terminated.

    ``sort_keys`` is deliberately off. The key order here is the order a person
    reads the document in, summary before detail, and a program does not care
    either way. ``ensure_ascii`` is off too: a report about a Japanese form that
    escaped every label into a backslash-u sequence would be unreadable in
    exactly the case where reading it matters most.
    """
    return json.dumps(build(report), indent=indent, ensure_ascii=False) + "\n"


def report_schema() -> dict[str, Any]:
    """Return the JSON Schema of the report, for ``--json-schema``.

    Built from the same enums the renderer uses, so the schema cannot describe a
    report this build does not produce.
    """
    finding = {
        "type": "object",
        "required": ["code", "severity", "selector", "fix", "signals"],
        "properties": {
            "code": {"enum": [code.value for code in FindingCode]},
            "severity": {"enum": [severity.value for severity in Severity]},
            "selector": {"type": "string"},
            "fix": {"type": "string"},
            "signals": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": ["number", "null"]},
            "confidence_display": {"type": "string"},
            "label": {"type": ["string", "null"]},
            "declared": {"type": ["string", "null"]},
            "group_id": {"type": ["string", "null"]},
            "suppressed_by": {"type": "string"},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": REPORT_SCHEMA_ID,
        "title": f"{TOOL_NAME} report",
        "description": (
            "One audited page. Every finding names the evidence that produced it and "
            "either a calibrated confidence or a documented rule tier."
        ),
        "type": "object",
        "required": ["schema_version", "tool", "target", "engine", "summary", "findings"],
        "properties": {
            "schema_version": {"const": REPORT_SCHEMA_VERSION},
            "tool": {
                "type": "object",
                "required": ["name", "version"],
                "properties": {
                    "name": {"const": TOOL_NAME},
                    "version": {"type": "string"},
                },
            },
            "target": {"type": "string", "description": "the URL or file that was audited"},
            "engine": {
                "type": "object",
                "description": "the classifier's own describe() output, verbatim",
                "additionalProperties": {"type": "string"},
            },
            "thresholds": {
                "type": "object",
                "description": "the decision thresholds in force and where they came from",
                "additionalProperties": {"type": "string"},
            },
            "summary": {
                "type": "object",
                "description": (
                    "counts only. There is deliberately no composite score, no grade, "
                    "and no index: a single number for page quality would have no "
                    "reproducible definition."
                ),
                "properties": {
                    "counts": {
                        "type": "object",
                        "properties": {
                            severity.value: {"type": "integer"} for severity in SEVERITY_ORDER
                        },
                    },
                    "findings": {"type": "integer"},
                    "suppressed": {"type": "integer"},
                    "controls_audited": {"type": "integer"},
                    "controls_declaring_autocomplete": {"type": "integer"},
                    "controls_seen": {"type": "integer"},
                    "honeypots_excluded": {"type": "integer"},
                    "frames": {"type": "integer"},
                    "truncated": {"type": "boolean"},
                },
            },
            "findings": {"type": "array", "items": finding},
            "suppressed": {
                "type": "array",
                "items": finding,
                "description": (
                    "findings configuration hid, each carrying the reason. A suppressed "
                    "finding is never dropped."
                ),
            },
            "page_notes": {"type": "array", "items": {"type": "string"}},
            "canvas_regions": {"type": "array", "items": {"type": "object"}},
            "descriptors": {
                "type": "array",
                "items": {"type": "object"},
                "description": "the field descriptors, pruned of geometry",
            },
            "honeypots": {
                "type": "array",
                "items": {"type": "object"},
                "description": "controls excluded from the audit because a user cannot see them",
            },
            "timing_ms": {
                "type": "object",
                "additionalProperties": {"type": "number"},
                "description": "the only part of this document that is not reproducible",
            },
        },
        "$defs": {
            "findingCodes": {code.value: FINDING_SPECS[code].trigger for code in FindingCode}
        },
    }
