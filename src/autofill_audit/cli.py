"""The command surface (spec section 14).

``version`` and the ``corpus`` group do real work. ``audit`` exists so that the
console entry point installed by the wheel is exercised end to end by the build
gate, and it refuses with a clear message rather than pretending to audit
anything. The rest of the command surface (``train``, ``eval``, ``bench``)
arrives with the phases that implement it.

Exit codes here reserve the contract of spec section 11.5: 2 means the tool
could not do the work it was asked to do. A command that is not implemented
yet reports that, and so does a refused overwrite and a corpus that fails
validation.
"""

from __future__ import annotations

from pathlib import Path

import click

from autofill_audit import __version__
from autofill_audit.corpus.families import Family
from autofill_audit.corpus.generator import grid_from
from autofill_audit.corpus.manifest import write_corpus
from autofill_audit.corpus.profiles import LOCALE_IDS
from autofill_audit.corpus.tiers import Tier
from autofill_audit.corpus.validate import validate_corpus
from autofill_audit.taxonomy import GROUP_ORDER, GROUPS

__all__ = ["cli", "main"]

_NOT_IMPLEMENTED_EXIT_CODE = 2
_FAILED_EXIT_CODE = 2


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


@cli.group()
def corpus() -> None:
    """Generate and check the synthetic corpus."""


def _split_option(value: str | None) -> list[str] | None:
    """Parse a comma-separated option into a list, or None when absent."""
    if value is None:
        return None
    items = [part.strip() for part in value.split(",") if part.strip()]
    return items or None


@corpus.command("generate")
@click.option("--seed", type=int, required=True, help="the one seed, propagated everywhere")
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="output directory",
)
@click.option(
    "--families",
    default=None,
    help=f"comma separated; default all of {', '.join(family.value for family in Family)}",
)
@click.option(
    "--locales", default=None, help=f"comma separated; default all of {', '.join(LOCALE_IDS)}"
)
@click.option(
    "--tiers",
    default=None,
    help=f"comma separated; default all of {', '.join(tier.value for tier in Tier)}",
)
@click.option("--variants", type=int, default=1, show_default=True, help="forms per grid cell")
@click.option(
    "--base-year",
    type=int,
    default=None,
    help="the first year offered by an expiry select; defaults to the current year "
    "and is recorded in the manifest, so a corpus stays reproducible after the year turns",
)
@click.option("--force", is_flag=True, help="overwrite a non-empty output directory")
def corpus_generate(
    seed: int,
    out: Path,
    families: str | None,
    locales: str | None,
    tiers: str | None,
    variants: int,
    base_year: int | None,
    force: bool,
) -> None:
    """Generate the corpus, deterministically, from a seed.

    Refuses a non-empty output directory without ``--force``. That refusal is
    worth the friction: the corpus is regenerable, but the directory the user
    typed might not be a corpus directory at all, and a generator that empties
    whatever it is pointed at is one typo away from being a disaster.
    """
    if out.exists() and any(out.iterdir()) and not force:
        click.echo(
            f"{out} is not empty. Pass --force to overwrite it.",
            err=True,
        )
        raise SystemExit(_FAILED_EXIT_CODE)

    try:
        grid = grid_from(
            seed=seed,
            families=_split_option(families),
            locales=_split_option(locales),
            tiers=_split_option(tiers),
            variants=variants,
            base_year=base_year,
        )
    except ValueError as error:
        click.echo(str(error), err=True)
        raise SystemExit(_FAILED_EXIT_CODE) from error

    result = write_corpus(grid, out)
    version = result.manifest["generator_version"]
    click.echo(f"seed {seed}, base year {grid.base_year}, generator {version}")
    click.echo(
        f"wrote {result.form_count} forms and {result.manifest['field_count']} fields to {out}"
    )
    click.echo(f"manifest sha256 {result.manifest_sha}")
    missing = result.missing_labels()
    if missing:
        click.echo(f"labels emitted by no answer key: {', '.join(missing)}", err=True)


@corpus.command("validate")
@click.option(
    "--corpus-dir",
    "corpus_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("corpus"),
    show_default=True,
    help="the corpus directory to check",
)
@click.option("--quiet", is_flag=True, help="print only the verdict and any problems")
def corpus_validate(corpus_dir: Path, quiet: bool) -> None:
    """Check every answer key, the manifest, the split, and label coverage."""
    report = validate_corpus(corpus_dir)

    if not quiet:
        click.echo(f"corpus: {corpus_dir}")
        click.echo(f"forms: {report.form_count}, fields: {report.field_count}")
        click.echo("label coverage by group:")
        for group in GROUP_ORDER:
            members = sorted(label.value for label in GROUPS[group])
            click.echo(f"  {group}")
            for name in members:
                count = report.coverage.get(name, 0)
                mark = "  " if count else "!!"
                click.echo(f"    {mark} {name:<20} {count}")

    missing = report.missing_labels()
    click.echo(f"labels emitted: {len(report.coverage) - len(missing)} of {len(report.coverage)}")
    if missing:
        click.echo(f"missing: {', '.join(missing)}")

    for problem in report.problems:
        click.echo(problem, err=True)
    if not report.ok:
        click.echo(f"corpus validate: {len(report.problems)} problem(s)", err=True)
        raise SystemExit(_FAILED_EXIT_CODE)
    click.echo("corpus validate: green")


def main() -> None:
    """Console script entry point."""
    cli()
