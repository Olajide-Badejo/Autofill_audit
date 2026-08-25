"""The command surface (spec section 14).

At P0 only ``version`` does real work. ``audit`` exists so that the console
entry point installed by the wheel is exercised end to end by the build gate,
and it refuses with a clear message rather than pretending to audit anything.
The rest of the command surface (``corpus``, ``train``, ``eval``, ``bench``)
arrives with the phases that implement it.

Exit codes here reserve the contract of spec section 11.5: 2 means the tool
could not do the work it was asked to do, which is exactly what a command that
is not implemented yet must report.
"""

from __future__ import annotations

import click

from autofill_audit import __version__

__all__ = ["cli", "main"]

_NOT_IMPLEMENTED_EXIT_CODE = 2


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", package_name="autofill-audit")
def cli() -> None:
    """Audit HTML forms for browser autofill readiness."""


@cli.command()
def version() -> None:
    """Print the version and the resolved engine identities.

    At P0 the only identity that exists is the package version itself. The
    classifier, browser, and report engine identities are appended by the
    phases that introduce them, so that a bug report can name exactly what ran.
    """
    click.echo(f"autofill-audit {__version__}")


@cli.command()
@click.argument("target", metavar="URL_OR_PATH")
def audit(target: str) -> None:
    """Audit a page or local HTML file for autofill readiness.

    Not implemented until P3, which ships the rule baseline, the audit engine,
    and the three renderers together. Until then this command reports that it
    cannot do the work rather than emitting an empty report, because an empty
    report reads like a clean bill of health.
    """
    click.echo(f"autofill-audit cannot audit {target} yet.", err=True)
    click.echo(
        "The audit command is implemented at phase P3, together with the rule "
        "baseline and the audit engine. This build is P0 foundations only.",
        err=True,
    )
    raise SystemExit(_NOT_IMPLEMENTED_EXIT_CODE)


def main() -> None:
    """Console script entry point."""
    cli()
