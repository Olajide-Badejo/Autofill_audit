"""The single self-contained HTML report (spec section 11.4).

One file. No external stylesheet, no font, no script, no image, no CDN link, and
no network fetch at view time. The most likely reader is somebody who was emailed
the file or who found it in a CI artefact, and a report that renders as unstyled
text on an air-gapped machine is a report that gets ignored.

That constraint is why the CSS is a string in this module rather than a resource
loaded from anywhere: there is exactly one copy, it is inlined into every report,
and there is no path by which a report can be produced that refers to a file it
did not carry with it. A test asserts that the rendered document contains no
``http`` reference and no ``<script>``.

Everything is escaped through ``html.escape``. A report about somebody else's
page contains their label text, their selectors, and their attribute values
verbatim, and any of those can contain a bracket. An auditor that could be made
to render markup from the page it audited would be an auditor with a cross-site
scripting hole in its own output.
"""

from __future__ import annotations

from html import escape
from typing import Final

from autofill_audit import __version__
from autofill_audit.audit.engine import AuditReport
from autofill_audit.audit.findings import SEVERITY_ORDER, Finding, Severity

__all__ = ["render"]

_STYLE: Final[str] = """
:root {
  color-scheme: light dark;
  --ink: #1b1b1b;
  --paper: #ffffff;
  --rule: #d9d9d9;
  --muted: #5c5c5c;
  --critical: #a4143c;
  --warning: #8a5a00;
  --info: #12566b;
  --note: #5c5c5c;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ink: #ececec;
    --paper: #16181c;
    --rule: #35383e;
    --muted: #a6a6a6;
    --critical: #ff8095;
    --warning: #e5b25d;
    --info: #7cc7dd;
    --note: #a6a6a6;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0 auto;
  padding: 2rem 1.25rem 4rem;
  max-width: 60rem;
  background: var(--paper);
  color: var(--ink);
  font: 15px/1.55 ui-sans-serif, system-ui, "Segoe UI", Helvetica, Arial, sans-serif;
}
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .5rem; }
p.target { margin: 0 0 1.5rem; color: var(--muted); word-break: break-all; }
table { border-collapse: collapse; width: 100%; margin: 0 0 1rem; }
th, td {
  text-align: left;
  vertical-align: top;
  padding: .5rem .6rem;
  border-bottom: 1px solid var(--rule);
}
th { font-weight: 600; }
td.control { width: 38%; word-break: break-all; }
code, .sel {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .92em;
}
.code { font-weight: 600; }
.evidence { color: var(--muted); font-size: .88em; margin-top: .35rem; word-break: break-word; }
.critical .code { color: var(--critical); }
.warning .code { color: var(--warning); }
.info .code { color: var(--info); }
.note .code { color: var(--note); }
dl.summary {
  display: grid;
  grid-template-columns: max-content auto;
  gap: .3rem 1.25rem;
  margin: 0;
}
dl.summary dt { color: var(--muted); }
dl.summary dd { margin: 0; }
ul.notes { color: var(--muted); padding-left: 1.1rem; }
footer {
  margin-top: 2.5rem;
  color: var(--muted);
  font-size: .85em;
  border-top: 1px solid var(--rule);
  padding-top: .75rem;
}
.empty { color: var(--muted); }
"""

_SIGNAL_LIMIT: Final[int] = 12
"""How many signals one evidence line shows. Higher than the terminal's, because
an HTML report wraps gracefully and its reader is usually the one debugging."""


def _evidence(finding: Finding) -> str:
    """The evidence line for one finding."""
    signals = list(finding.signals)
    shown = ", ".join(signals[:_SIGNAL_LIMIT])
    if len(signals) > _SIGNAL_LIMIT:
        shown += f", and {len(signals) - _SIGNAL_LIMIT} more"
    return f"evidence: {shown} [{finding.confidence_display}]"


def _rows(findings: list[Finding], severity: Severity) -> str:
    """One table of findings at one severity."""
    lines = [
        f"<h2>{escape(severity.value)} ({len(findings)})</h2>",
        f'<table class="{escape(severity.value)}">',
        "<thead><tr><th>control</th><th>finding and fix</th></tr></thead>",
        "<tbody>",
    ]
    for finding in findings:
        lines.append(
            "<tr>"
            f'<td class="control"><span class="sel">{escape(finding.selector)}</span></td>'
            "<td>"
            f'<div class="code">{escape(finding.code.value)}</div>'
            f"<div>{escape(finding.fix)}</div>"
            f'<div class="evidence">{escape(_evidence(finding))}</div>'
            "</td>"
            "</tr>"
        )
    lines.extend(["</tbody>", "</table>"])
    return "\n".join(lines)


def _summary(report: AuditReport) -> str:
    """The counts block. Counts only, never a score."""
    counts = report.counts()
    declared, audited = report.readiness()
    items: list[tuple[str, str]] = [
        (severity.value, str(counts[severity])) for severity in SEVERITY_ORDER
    ]
    items.append(("autofill readiness", f"{declared} of {audited} controls declare autocomplete"))
    items.append(("controls audited", str(audited)))
    if report.honeypots:
        items.append(("set aside as not visible", str(len(report.honeypots))))
    if report.suppressed:
        items.append(("suppressed by configuration", str(len(report.suppressed))))
    body = "".join(f"<dt>{escape(key)}</dt><dd>{escape(value)}</dd>" for key, value in items)
    return f'<h2>summary</h2><dl class="summary">{body}</dl>'


def render(report: AuditReport) -> str:
    """Render the whole report as one self-contained HTML document."""
    grouped: dict[Severity, list[Finding]] = {severity: [] for severity in SEVERITY_ORDER}
    for finding in report.findings:
        grouped[finding.severity].append(finding)

    parts: list[str] = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>autofill-audit report: {escape(report.url)}</title>",
        f"<style>{_STYLE}</style>",
        "</head>",
        "<body>",
        "<h1>autofill-audit report</h1>",
        f'<p class="target"><span class="sel">{escape(report.url)}</span></p>',
        _summary(report),
    ]

    if not report.findings:
        parts.append(
            '<p class="empty">No findings. Every control this tool could read is declared.</p>'
        )
    for severity in SEVERITY_ORDER:
        rows = grouped[severity]
        if rows:
            parts.append(_rows(rows, severity))

    if report.page_notes:
        notes = "".join(f"<li>{escape(note)}</li>" for note in report.page_notes)
        parts.append(f'<h2>page notes</h2><ul class="notes">{notes}</ul>')

    if report.suppressed:
        hidden = "".join(
            f'<li><span class="sel">{escape(item.selector)}</span> '
            f"{escape(item.code.value)}: {escape(item.suppressed_by or '')}</li>"
            for item in report.suppressed
        )
        parts.append(f'<h2>suppressed by configuration</h2><ul class="notes">{hidden}</ul>')

    engine = ", ".join(f"{key}={value}" for key, value in sorted(report.engine.items()))
    footer = f"{escape(engine)}"
    if report.thresholds is not None and not report.thresholds.measured:
        footer += (
            "<br>Confidences are rule tiers, not probabilities, and the thresholds behind "
            f"them are a documented mapping rather than a measurement "
            f"({escape(report.thresholds.basis)})."
        )
    parts.extend(
        [
            f"<footer>autofill-audit {escape(__version__)}<br>{footer}</footer>",
            "</body>",
            "</html>",
            "",
        ]
    )
    return "\n".join(parts)
