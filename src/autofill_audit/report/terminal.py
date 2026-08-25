"""The rich terminal renderer (spec section 11.4).

Findings grouped by severity, most severe first; each shows the selector, the
code, the one-line fix, and an evidence line naming the signals. A summary panel
gives counts by severity and an autofill-readiness line that is a **count**.

**There is no score.** No letter grade, no index out of a hundred, no weighted
total. A composite would be a number with no reproducible definition, which is a
law 3 problem in disguise, and the first thing anybody would do with one is quote
it somewhere the report cannot follow. The readiness line says how many controls
carry a usable declaration out of how many were audited, which is a fact a reader
can check against their own markup in a minute.

**Rule confidences are shown as tiers.** The engine's ``describe()`` says which
kind of confidence it produces and the finding carries the already-formatted
string, so this renderer never decides how to print a number; it prints what the
audit engine decided. Printing "83%" from a regex table would be a law 1 and a
law 4 violation in a single number (spec section 10.1).

Determinism, because this output is snapshot tested
---------------------------------------------------

``render`` writes into a console it constructs itself, at a fixed width, with
colour and highlighting off and the terminal detection that would otherwise vary
by environment turned off. The default width is fixed rather than read from the
terminal for the same reason: a snapshot taken at eighty columns and compared at
a hundred and twenty is a snapshot that fails on somebody's laptop and nowhere
else. ``print_report`` is the one that writes to a real terminal and does read
its width.
"""

from __future__ import annotations

from io import StringIO
from typing import Final

from rich.box import SIMPLE
from rich.console import Console
from rich.table import Table
from rich.text import Text

from autofill_audit.audit.engine import AuditReport
from autofill_audit.audit.findings import SEVERITY_ORDER, Finding, Severity

__all__ = ["SNAPSHOT_WIDTH", "print_report", "render"]

SNAPSHOT_WIDTH: Final[int] = 100
"""The width ``render`` uses unless told otherwise, and the width the golden
snapshots are taken at."""

_SEVERITY_STYLE: Final[dict[Severity, str]] = {
    Severity.CRITICAL: "bold red",
    Severity.WARNING: "yellow",
    Severity.INFO: "cyan",
    Severity.NOTE: "dim",
}

_HEADING: Final[str] = "autofill-audit"
_NO_FINDINGS: Final[str] = "No findings. Every control this tool could read is declared."
_EVIDENCE_PREFIX: Final[str] = "evidence: "
_MAX_SIGNALS: Final[int] = 6
"""How many signals an evidence line shows before saying how many it left out.

A tie that fell through every tier can name a dozen rules, and an evidence line
that wrapped four times would be skipped by every reader. The JSON report carries
all of them, which is where a reader who wants all of them should look."""


def _evidence(finding: Finding) -> str:
    """The evidence line for one finding: its signals and its confidence."""
    signals = list(finding.signals)
    shown = signals[:_MAX_SIGNALS]
    text = ", ".join(shown)
    if len(signals) > _MAX_SIGNALS:
        text += f", and {len(signals) - _MAX_SIGNALS} more"
    return f"{_EVIDENCE_PREFIX}{text} [{finding.confidence_display}]"


def _findings_table(findings: list[Finding], severity: Severity) -> Table:
    """One table per severity, in report order."""
    table = Table(
        box=SIMPLE,
        show_header=True,
        header_style="bold",
        title=f"{severity.value} ({len(findings)})",
        title_justify="left",
        title_style=_SEVERITY_STYLE[severity],
        pad_edge=False,
        expand=True,
    )
    table.add_column("control", overflow="fold", ratio=2)
    table.add_column("finding", overflow="fold", ratio=3)
    for finding in findings:
        detail = Text(finding.code.value, style="bold")
        detail.append("\n")
        detail.append(finding.fix)
        detail.append("\n")
        detail.append(_evidence(finding), style="dim")
        table.add_row(Text(finding.selector, style="bold"), detail)
    return table


def _summary(report: AuditReport) -> Table:
    """The counts panel. Counts only, never a score."""
    counts = report.counts()
    declared, audited = report.readiness()
    table = Table(box=SIMPLE, show_header=False, pad_edge=False, expand=False)
    table.add_column("key")
    table.add_column("value", justify="right")
    for severity in SEVERITY_ORDER:
        table.add_row(Text(severity.value, style=_SEVERITY_STYLE[severity]), str(counts[severity]))
    table.add_row("", "")
    table.add_row(
        "autofill readiness",
        f"{declared} of {audited} controls declare autocomplete",
    )
    if report.honeypots:
        table.add_row("set aside as not visible", str(len(report.honeypots)))
    if report.suppressed:
        table.add_row("suppressed by configuration", str(len(report.suppressed)))
    return table


def _write(report: AuditReport, console: Console) -> None:
    """Write the whole report into an already-configured console."""
    console.print(Text(f"{_HEADING}  {report.url}", style="bold"))
    console.print()

    grouped: dict[Severity, list[Finding]] = {severity: [] for severity in SEVERITY_ORDER}
    for finding in report.findings:
        grouped[finding.severity].append(finding)

    if not report.findings:
        console.print(Text(_NO_FINDINGS, style="green"))
        console.print()
    for severity in SEVERITY_ORDER:
        rows = grouped[severity]
        if not rows:
            continue
        console.print(_findings_table(rows, severity))

    for note in report.page_notes:
        console.print(Text(f"note: {note}", style="dim"))
    if report.page_notes:
        console.print()

    for finding in report.suppressed:
        console.print(
            Text(
                f"suppressed: {finding.code.value} on {finding.selector} ({finding.suppressed_by})",
                style="dim",
            )
        )
    if report.suppressed:
        console.print()

    console.print(_summary(report))

    if report.thresholds is not None and not report.thresholds.measured:
        console.print(
            Text(
                "Confidences are rule tiers, not probabilities, and the thresholds "
                f"behind them are a documented mapping rather than a measurement "
                f"({report.thresholds.basis}).",
                style="dim",
            )
        )


def render(report: AuditReport, *, width: int = SNAPSHOT_WIDTH) -> str:
    """Render the report to a string, deterministically.

    Every source of environment dependence a ``Console`` has is pinned here:
    the width, the colour system, the highlighter, and the terminal detection.
    What comes out is a function of the report and nothing else, which is what
    lets spec section 15's layer three snapshot it.
    """
    buffer = StringIO()
    console = Console(
        file=buffer,
        width=width,
        force_terminal=False,
        no_color=True,
        highlight=False,
        soft_wrap=False,
        legacy_windows=False,
    )
    _write(report, console)
    return buffer.getvalue()


def print_report(report: AuditReport, *, quiet: bool = False) -> None:
    """Write the report to the real terminal, in colour where there is one."""
    console = Console(quiet=quiet, highlight=False)
    _write(report, console)
