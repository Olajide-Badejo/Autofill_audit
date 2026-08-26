"""The command surface (spec section 14).

``audit`` is the only command a typical user runs. ``corpus`` generates and
checks the synthetic corpus. ``train``, ``eval``, and ``bench`` arrive with the
phases that implement them.

The exit-code contract (spec section 11.5)
------------------------------------------

| 0 | completed, nothing at or above the failure threshold |
| 1 | completed, at least one finding at or above it |
| 2 | usage error: bad arguments, unreadable file, unparseable config |
| 3 | the page could not be loaded, or extraction failed entirely |
| 4 | internal error, which is a bug; prints a traceback and asks for an issue |

**Code 3 is deliberately distinct from code 1.** A pipeline has to be able to
tell "your form has problems" from "the auditor could not reach the page", and
collapsing them produces exactly the flaky red build that gets the check deleted.

Configuration precedence
------------------------

CLI flag, then environment variable, then config file, then default. Click
reports where each parameter's value came from, so the config file is consulted
only for parameters whose value is still the built-in default. Environment
variables are read by click itself under the ``AUTOFILL_AUDIT_`` prefix, which
puts them above the file and below the flag with no code of its own.

The flags that are deliberately absent
--------------------------------------

``--crawl``, ``--depth``, ``--fill``, ``--fix``, and ``--write`` are the
boundaries of spec section 0.4, and somebody will try each of them. Click's
default answer to an unknown option is "no such option", which reads like an
oversight. So they are intercepted before parsing and answered with the boundary
they name and the reason it is a boundary. Interception happens in ``main`` on
the raw argument list rather than as hidden options on one command, because the
boundary holds for every command and a hidden option would have to be repeated
on each of them.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import tomllib
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, NoReturn
from urllib.parse import urlparse

import click

from autofill_audit import __version__
from autofill_audit.audit.engine import AuditOptions, AuditReport, Suppression
from autofill_audit.audit.engine import audit as run_audit
from autofill_audit.audit.findings import FindingCode, Severity
from autofill_audit.audit.thresholds import (
    Thresholds,
    ThresholdsError,
    available_engines,
    load_thresholds,
)
from autofill_audit.classify import EngineChoice, UnavailableEngineError, load_engine
from autofill_audit.corpus.families import Family
from autofill_audit.corpus.generator import grid_from
from autofill_audit.corpus.manifest import write_corpus
from autofill_audit.corpus.profiles import LOCALE_IDS
from autofill_audit.corpus.tiers import Tier
from autofill_audit.corpus.validate import validate_corpus
from autofill_audit.extract.walker import MAX_FRAME_DEPTH, ExtractOptions, extract_result
from autofill_audit.loader import (
    LoadBudget,
    LoaderError,
    NavigationFailedError,
    NavigationTimeoutError,
    NotHtmlError,
    TargetNotFoundError,
    UnsupportedSchemeError,
    load_page,
)
from autofill_audit.report import html_report, json_report, terminal
from autofill_audit.taxonomy import GROUP_ORDER, GROUPS

__all__ = ["BOUNDARY_FLAGS", "cli", "main"]

EXIT_OK: Final[int] = 0
EXIT_FINDINGS: Final[int] = 1
EXIT_USAGE: Final[int] = 2
EXIT_UNREACHABLE: Final[int] = 3
EXIT_INTERNAL: Final[int] = 4

_CONFIG_NAME: Final[str] = "autofill-audit.toml"
_ENV_PREFIX: Final[str] = "AUTOFILL_AUDIT"

_NEVER: Final[str] = "never"
"""The ``--fail-on`` value that means no finding makes the run fail."""

BOUNDARY_FLAGS: Final[dict[str, str]] = {
    "--crawl": (
        "there is no crawl mode. This tool audits one page per invocation, plus the "
        "frames that page loads. That is a safety boundary rather than a missing "
        "feature: a tool that walks a site from one command is a tool that can be "
        "pointed at somebody else's site by accident."
    ),
    "--depth": (
        "there is no crawl depth, because there is no crawl. One page per invocation, "
        "plus the frames that page loads."
    ),
    "--fill": (
        "this is an auditor, not a form filler. It reads the DOM and reports; it never "
        "types into a field, never submits, and holds no profile of values to fill "
        "with. A form-filling agent is a genuinely interesting successor project and it "
        "is deliberately a separate one."
    ),
    "--fix": (
        "findings carry a fix as text and nothing writes it for you. Rewriting a "
        "production template from a classifier's output is exactly the failure this "
        "project's first law exists to prevent."
    ),
    "--write": (
        "there is no mode that edits your HTML. Findings carry a fix as text; applying "
        "it is a decision a person makes."
    ),
}
"""The five flags of spec section 0.4, and why each one is not here.

Written as prose rather than as "unsupported" because the reader has just typed
something reasonable. Telling them the boundary and the reason for it is the
difference between a tool that looks unfinished and a tool that has an opinion."""


# ---------------------------------------------------------------------------
# Configuration.
# ---------------------------------------------------------------------------


class ConfigError(ValueError):
    """The config file is missing, unreadable, or says something impossible."""


@dataclass(frozen=True, slots=True)
class Config:
    """What a config file can set (spec section 14)."""

    source: Path | None = None
    values: Mapping[str, Any] = field(default_factory=dict)
    suppressions: tuple[Suppression, ...] = ()

    def get(self, key: str) -> Any:
        """Return a top-level setting, or None."""
        return self.values.get(key)


_EMPTY_CONFIG: Final[Config] = Config()


def find_config(start: Path) -> Path | None:
    """Search ``start`` and its ancestors for the config file.

    Upward from the working directory, which is what makes a repository-level
    config apply to every subdirectory a developer runs the tool from. It stops
    at the filesystem root and never reads a home directory: a config that
    applied to every project on the machine would make one project's suppressions
    silently apply to another's audit.
    """
    for directory in (start, *start.parents):
        candidate = directory / _CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path | None) -> Config:
    """Read and validate a config file. A missing file is not an error."""
    if path is None:
        return _EMPTY_CONFIG
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"{path}: {error}") from error

    suppressions: list[Suppression] = []
    for name in payload.get("ignore", []):
        if not isinstance(name, str):
            raise ConfigError(f"{path}: ignore must be a list of finding codes")
        suppressions.append(Suppression(code=_finding_code(path, name), reason=f"ignore = {name}"))

    entries = payload.get("suppress", [])
    if not isinstance(entries, list):
        raise ConfigError(f"{path}: suppress must be a list of tables")
    for entry in entries:
        if not isinstance(entry, dict) or "code" not in entry:
            raise ConfigError(f"{path}: every [[suppress]] entry needs a code")
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason:
            raise ConfigError(
                f"{path}: every [[suppress]] entry needs a reason. A suppression with no "
                "stated reason is a suppression nobody can review."
            )
        selector = entry.get("selector")
        if selector is not None and not isinstance(selector, str):
            raise ConfigError(f"{path}: a [[suppress]] selector must be a string")
        suppressions.append(
            Suppression(
                code=_finding_code(path, str(entry["code"])),
                selector=selector,
                reason=reason,
            )
        )
    return Config(source=path, values=payload, suppressions=tuple(suppressions))


def _finding_code(path: Path, name: str) -> FindingCode:
    """Turn a configured code name into a code, or explain why it is not one."""
    try:
        return FindingCode(name)
    except ValueError as error:
        known = ", ".join(code.value for code in FindingCode)
        raise ConfigError(
            f"{path}: {name!r} is not a finding code. Known codes: {known}"
        ) from error


def _from_config(ctx: click.Context, name: str, config: Config, current: Any) -> Any:
    """Apply the config file only where the flag and the environment were silent."""
    source = ctx.get_parameter_source(name)
    if source is not None and source is not click.core.ParameterSource.DEFAULT:
        return current
    configured = config.get(name)
    return current if configured is None else configured


# ---------------------------------------------------------------------------
# The command group.
# ---------------------------------------------------------------------------


@click.group(
    context_settings={
        "help_option_names": ["-h", "--help"],
        "auto_envvar_prefix": _ENV_PREFIX,
    }
)
@click.version_option(__version__, "-V", "--version", package_name="autofill-audit")
def cli() -> None:
    """Audit HTML forms for browser autofill readiness."""


@cli.command()
def version() -> None:
    """Print the version and the resolved engine identities."""
    click.echo(f"autofill-audit {__version__}")
    for key, value in load_engine(EngineChoice.RULES).classifier.describe().items():
        click.echo(f"  {key}: {value}")
    try:
        engines = available_engines()
        for name in engines:
            for key, value in load_thresholds(name).describe().items():
                click.echo(f"  {name} threshold {key}: {value}")
    except ThresholdsError as error:  # pragma: no cover - a corrupt install
        click.echo(f"  thresholds: unreadable ({error})", err=True)


def _print_schema(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    """Print the JSON report schema and exit, before anything else happens."""
    if not value or ctx.resilient_parsing:
        return
    click.echo(json.dumps(json_report.report_schema(), indent=2))
    ctx.exit(EXIT_OK)


@cli.command()
@click.argument("target", metavar="URL_OR_PATH", required=False)
@click.option(
    "--engine",
    type=click.Choice([choice.value for choice in EngineChoice]),
    default=EngineChoice.AUTO.value,
    show_default=True,
    help="auto uses the strongest engine that loads, and says so when it falls back",
)
@click.option(
    "--llm-endpoint",
    type=str,
    default=None,
    help="research layer only: the OpenAI-compatible base URL, above the config file",
)
@click.option("--llm-model", type=str, default=None, help="research layer only: the model tag")
@click.option("--llm-batch", type=int, default=None, help="research layer only: fields per request")
@click.option(
    "--format",
    "formats",
    type=click.Choice(["terminal", "json", "html"]),
    multiple=True,
    help="repeatable; default terminal. html and json need --out unless one of them "
    "is the only format",
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="write the report here; required when more than one format is asked for",
)
@click.option(
    "--fail-on",
    type=click.Choice(
        [Severity.CRITICAL.value, Severity.WARNING.value, Severity.INFO.value, _NEVER]
    ),
    default=Severity.CRITICAL.value,
    show_default=True,
    help="the severity at which the exit code becomes 1",
)
@click.option("--timeout", type=int, default=None, help="navigation budget in milliseconds")
@click.option("--settle", type=int, default=None, help="post-load DOM-quiet budget in milliseconds")
@click.option(
    "--include-hidden",
    is_flag=True,
    default=False,
    help="audit the controls a user cannot see instead of setting them aside",
)
@click.option(
    "--frames/--no-frames",
    default=True,
    show_default=True,
    help="traverse same-origin frames",
)
@click.option(
    "--min-confidence",
    type=float,
    default=None,
    help="override the low threshold for this run; the report says a non-default "
    "threshold was in force",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=f"a {_CONFIG_NAME} to use instead of the one discovered upward from here",
)
@click.option(
    "--json-schema",
    is_flag=True,
    callback=_print_schema,
    expose_value=False,
    is_eager=True,
    help="print the JSON report schema and exit",
)
@click.option("-v", "--verbose", count=True, help="say more about what is happening")
@click.option("-q", "--quiet", is_flag=True, default=False, help="print findings and nothing else")
@click.pass_context
def audit(
    ctx: click.Context,
    target: str | None,
    engine: str,
    llm_endpoint: str | None,
    llm_model: str | None,
    llm_batch: int | None,
    formats: tuple[str, ...],
    out: Path | None,
    fail_on: str,
    timeout: int | None,
    settle: int | None,
    include_hidden: bool,
    frames: bool,
    min_confidence: float | None,
    config_path: Path | None,
    verbose: int,
    quiet: bool,
) -> None:
    """Audit a page or a local HTML file for autofill readiness.

    TARGET is a URL, or a path to a local file which is opened through file://.
    One page per invocation, plus the frames that page loads.
    """
    if target is None:
        raise click.UsageError("give me a URL or a path to audit, or pass --json-schema")

    try:
        config = load_config(config_path if config_path is not None else find_config(Path.cwd()))
    except ConfigError as error:
        _fail(str(error), EXIT_USAGE)

    engine = str(_from_config(ctx, "engine", config, engine))
    fail_on = str(_from_config(ctx, "fail_on", config, fail_on))
    chosen = tuple(formats) or _configured_formats(config)
    timeout = _from_config(ctx, "timeout", config, timeout)
    settle = _from_config(ctx, "settle", config, settle)
    min_confidence = _from_config(ctx, "min_confidence", config, min_confidence)

    if len(chosen) > 1 and out is None:
        _fail("--out is required when more than one --format is asked for", EXIT_USAGE)
    if "html" in chosen and out is None:
        _fail("--out is required for the html format", EXIT_USAGE)

    try:
        loaded = load_engine(
            EngineChoice(engine),
            llm_config=_llm_config(ctx, config, engine, llm_endpoint, llm_model, llm_batch),
        )
    except UnavailableEngineError as error:
        _fail(str(error), EXIT_USAGE)

    # The engine is resolved first, and then its thresholds. ``auto`` may have
    # become either engine, and the two are on different confidence scales: the
    # rule tiers are ordered placeholders and the n-gram engine's are calibrated
    # probabilities. Loading one policy for whichever engine was asked for, rather
    # than for whichever one ran, would silently apply one scale to the other.
    try:
        thresholds = _thresholds(loaded.classifier.name, min_confidence)
    except ThresholdsError as error:
        _fail(str(error), EXIT_USAGE)

    if loaded.notice is not None and not quiet:
        click.echo(f"autofill-audit: {loaded.notice}", err=True)
    if min_confidence is not None and not quiet:
        click.echo(
            f"autofill-audit: a non-default low threshold of {min_confidence} is in force "
            "for this run",
            err=True,
        )
    if config.source is not None and verbose:
        click.echo(f"autofill-audit: configuration from {config.source}", err=True)

    report = _run(
        target,
        classifier=loaded.classifier,
        thresholds=thresholds,
        suppressions=config.suppressions,
        include_hidden=include_hidden,
        frames=frames,
        timeout=timeout,
        settle=settle,
    )

    _emit(report, chosen, out, quiet=quiet)
    threshold = None if fail_on == _NEVER else Severity(fail_on)
    ctx.exit(report.exit_code(threshold))


def _llm_config(
    ctx: click.Context,
    config: Config,
    engine: str,
    endpoint_flag: str | None = None,
    model_flag: str | None = None,
    batch_flag: int | None = None,
) -> Any:
    """Build the LLM configuration from flags and the config file's ``[llm]`` block.

    Spec section 14 puts the endpoint, model tag, batch size and timeout in the
    config file, and puts a CLI flag above it and an environment variable between
    them. That precedence is click's, applied by ``_from_config`` exactly as it is
    for every other setting.

    Returns None for every engine but ``llm``, so that auditing a page with the
    rule baseline never imports the research layer (ground rule 11) and never
    resolves a configuration it has no use for.
    """
    if engine != EngineChoice.LLM.value:
        return None
    from autofill_audit.llm.client import LLMConfig

    block = config.get("llm") or {}
    defaults = LLMConfig()
    endpoint = _from_config(ctx, "llm_endpoint", config, endpoint_flag) or block.get("endpoint")
    model_tag = _from_config(ctx, "llm_model", config, model_flag) or block.get("model")
    batch = _from_config(ctx, "llm_batch", config, batch_flag) or block.get("batch")
    timeout_s = block.get("timeout_s")
    return LLMConfig(
        endpoint=str(endpoint or defaults.endpoint),
        model_tag=str(model_tag or defaults.model_tag),
        batch=int(batch or defaults.batch),
        timeout_s=float(timeout_s or defaults.timeout_s),
    )


def _configured_formats(config: Config) -> tuple[str, ...]:
    """The formats a config file asked for, or the default."""
    configured = config.get("format")
    if configured is None:
        return ("terminal",)
    if isinstance(configured, str):
        return (configured,)
    return tuple(str(item) for item in configured)


def _thresholds(engine: str, min_confidence: float | None) -> Thresholds:
    """Load one engine's committed thresholds, with any override applied."""
    thresholds = load_thresholds(engine)
    if min_confidence is None:
        return thresholds
    return thresholds.with_low(float(min_confidence))


def _fail(message: str, code: int) -> NoReturn:
    """Print a diagnostic and exit with a documented code. Never a traceback."""
    click.echo(f"autofill-audit: {message}", err=True)
    raise SystemExit(code)


def _run(
    target: str,
    *,
    classifier: Any,
    thresholds: Thresholds,
    suppressions: tuple[Suppression, ...],
    include_hidden: bool,
    frames: bool,
    timeout: int | None,
    settle: int | None,
) -> AuditReport:
    """Load, extract, and audit one page, mapping every failure to its code."""
    as_file = urlparse(target).scheme == ""
    budget = LoadBudget()
    if timeout is not None:
        budget = LoadBudget(
            load_timeout_ms=timeout,
            network_idle_ms=budget.network_idle_ms,
            quiet_ms=budget.quiet_ms,
            settle_budget_ms=budget.settle_budget_ms,
        )
    if settle is not None:
        budget = LoadBudget(
            load_timeout_ms=budget.load_timeout_ms,
            network_idle_ms=budget.network_idle_ms,
            quiet_ms=budget.quiet_ms,
            settle_budget_ms=settle,
        )
    options = ExtractOptions(max_frame_depth=MAX_FRAME_DEPTH if frames else 0)

    started = time.perf_counter()
    try:
        with load_page(target, as_file=as_file, budget=budget) as page:
            loaded_at = time.perf_counter()
            result = extract_result(page.page, options=options, settle=page.settle)
    except (UnsupportedSchemeError, TargetNotFoundError, NotHtmlError) as error:
        _fail(str(error), EXIT_USAGE)
    except (NavigationTimeoutError, NavigationFailedError) as error:
        _fail(str(error), EXIT_UNREACHABLE)
    except LoaderError as error:  # pragma: no cover - every subclass is handled above
        _fail(str(error), EXIT_UNREACHABLE)
    extracted_at = time.perf_counter()

    report = run_audit(
        result,
        classifier,
        AuditOptions(
            thresholds=thresholds,
            suppressions=suppressions,
            include_hidden=include_hidden,
        ),
    )
    finished = time.perf_counter()
    return _with_timing(
        report,
        {
            "load_ms": (loaded_at - started) * 1000,
            "extract_ms": (extracted_at - loaded_at) * 1000,
            "audit_ms": (finished - extracted_at) * 1000,
        },
    )


def _with_timing(report: AuditReport, timing: dict[str, float]) -> AuditReport:
    """Return the report carrying the run's timings."""
    return replace(report, timing_ms=timing)


def _emit(report: AuditReport, formats: Sequence[str], out: Path | None, *, quiet: bool) -> None:
    """Render every requested format, to the file or to standard output."""
    for name in formats:
        if name == "terminal":
            if out is not None and len(formats) == 1:
                out.write_text(terminal.render(report), encoding="utf-8")
            else:
                terminal.print_report(report, quiet=quiet)
            continue
        text = json_report.render(report) if name == "json" else html_report.render(report)
        if out is None:
            click.echo(text, nl=False)
            continue
        path = out if len(formats) == 1 else out.with_suffix(f".{name}")
        path.write_text(text, encoding="utf-8")
        if not quiet:
            click.echo(f"autofill-audit: wrote {name} to {path}", err=True)


# ---------------------------------------------------------------------------
# The corpus commands (P1).
# ---------------------------------------------------------------------------


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
        raise SystemExit(EXIT_USAGE)

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
        raise SystemExit(EXIT_USAGE) from error

    result = write_corpus(grid, out)
    generator = result.manifest["generator_version"]
    click.echo(f"seed {seed}, base year {grid.base_year}, generator {generator}")
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
        raise SystemExit(EXIT_USAGE)
    click.echo("corpus validate: green")


# ---------------------------------------------------------------------------
# Training (P4).
# ---------------------------------------------------------------------------

_TRAIN_SCRIPT: Final[str] = "train.py"

_TRAIN_ABSENT: Final[str] = (
    "training needs a source checkout: scripts/train.py is not in this "
    "installation, and neither are scikit-learn and skl2onnx, which it fits and "
    "exports with. Clone the repository and install the dev extra. An installed "
    "wheel audits pages; it does not train models, which is a minutes-long "
    "offline job with a different dependency set."
)


def find_script(start: Path, name: str) -> Path | None:
    """Locate a script under ``scripts/``, upward from ``start`` and this package.

    Spec section 14 makes ``train`` and ``eval`` wrappers around their scripts
    rather than second implementations of them, and a script is a development
    artefact rather than package data. Searching both roots means a source
    checkout and an editable install both find it without configuring anything.
    """
    roots = [start, Path(__file__).resolve()]
    for root in roots:
        for directory in (root, *root.parents):
            candidate = directory / "scripts" / name
            if candidate.is_file():
                return candidate
    return None


def find_train_script(start: Path) -> Path | None:
    """Locate ``scripts/train.py``. Kept as a name the P4 tests already use."""
    return find_script(start, _TRAIN_SCRIPT)


@cli.command(
    context_settings={"ignore_unknown_options": True},
    help="Train the n-gram model. Wraps scripts/train.py; needs a source checkout.",
)
@click.option("--corpus", "corpus_dir", type=click.Path(path_type=Path), default=Path("corpus"))
@click.option("--split-file", type=click.Path(path_type=Path), default=None)
@click.option("--seed", type=int, required=True, help="the one seed, propagated everywhere")
@click.option("--out", type=click.Path(file_okay=False, path_type=Path), required=True)
@click.option(
    "--sweep/--no-sweep",
    default=True,
    show_default=True,
    help="choose the regularisation strength on the dev split",
)
@click.option(
    "--cache",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="reuse extracted descriptors from here, and write them here",
)
def train(
    corpus_dir: Path,
    split_file: Path | None,
    seed: int,
    out: Path,
    sweep: bool,
    cache: Path | None,
) -> None:
    """Train, calibrate, and export the n-gram model.

    There is no ``--test`` flag and there will not be one (spec section 14).
    The script this wraps enforces the same thing from the other end, with a
    guard that raises if a test-partition path is opened at all.
    """
    script = find_train_script(Path.cwd())
    if script is None:
        _fail(_TRAIN_ABSENT, EXIT_USAGE)
    arguments = [
        sys.executable,
        str(script),
        "--corpus",
        str(corpus_dir),
        "--seed",
        str(seed),
        "--out",
        str(out),
        "--sweep" if sweep else "--no-sweep",
    ]
    if split_file is not None:
        arguments.extend(["--split-file", str(split_file)])
    if cache is not None:
        arguments.extend(["--cache", str(cache)])
    raise SystemExit(subprocess.call(arguments))


# ---------------------------------------------------------------------------
# Evaluation (P5).
# ---------------------------------------------------------------------------

_EVAL_SCRIPT: Final[str] = "eval.py"

_EVAL_ABSENT: Final[str] = (
    "evaluation needs a source checkout: scripts/eval.py is not in this "
    "installation, and neither is the corpus it measures against. Clone the "
    "repository and install the dev extra. An installed wheel audits pages; "
    "measuring a classifier against an answer key is a different job with a "
    "different input."
)

_MEASURING_FLAG: Final[str] = "--i-am-measuring"


@cli.command(
    "eval",
    context_settings={"ignore_unknown_options": True},
    help="Evaluate an engine on a split. Wraps scripts/eval.py; needs a source checkout.",
)
@click.option("--corpus", "corpus_dir", type=click.Path(path_type=Path), default=Path("corpus"))
@click.option("--split-file", type=click.Path(path_type=Path), default=None)
@click.option(
    "--split",
    type=click.Choice(["dev", "test"]),
    required=True,
    help="which partition to measure on",
)
@click.option(
    "--engine",
    type=click.Choice(["rules", "ngram", "llm"]),
    required=True,
    help="the engine to measure; never auto, because a benchmark must say what ran",
)
@click.option("--llm-endpoint", type=str, default=None, help="OpenAI-compatible base URL")
@click.option("--llm-model", type=str, default=None, help="model tag, recorded in every row")
@click.option("--llm-batch", type=int, default=None, help="fields per request")
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("experiments/results"),
    show_default=True,
)
@click.option("--run-id", type=str, default=None, help="default is timestamp, engine, commit")
@click.option("--model", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--cache", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--seed", type=int, default=None, help="the one seed, recorded in the manifest")
@click.option(
    _MEASURING_FLAG,
    "measuring",
    is_flag=True,
    default=False,
    help="required for --split test; the test split is spent the first time it is read",
)
@click.option("--note", multiple=True, help="a note recorded in the run manifest")
def evaluate(
    corpus_dir: Path,
    split_file: Path | None,
    split: str,
    engine: str,
    llm_endpoint: str | None,
    llm_model: str | None,
    llm_batch: int | None,
    out: Path,
    run_id: str | None,
    model: Path | None,
    cache: Path | None,
    seed: int | None,
    measuring: bool,
    note: tuple[str, ...],
) -> None:
    """Write a run log at the spec section 13.1 schema, plus its manifest.

    ``--engine auto`` is deliberately not offered. ``auto`` is the right default
    for a person auditing a page and the wrong one for a measurement, because a
    result file whose engine column said ``auto`` would not say which engine
    produced the number in it.
    """
    script = find_script(Path.cwd(), _EVAL_SCRIPT)
    if script is None:
        _fail(_EVAL_ABSENT, EXIT_USAGE)
    arguments = [
        sys.executable,
        str(script),
        "--corpus",
        str(corpus_dir),
        "--split",
        split,
        "--engine",
        engine,
        "--out",
        str(out),
    ]
    if split_file is not None:
        arguments.extend(["--split-file", str(split_file)])
    if run_id is not None:
        arguments.extend(["--run-id", run_id])
    if model is not None:
        arguments.extend(["--model", str(model)])
    if cache is not None:
        arguments.extend(["--cache", str(cache)])
    if seed is not None:
        arguments.extend(["--seed", str(seed)])
    if measuring:
        arguments.append(_MEASURING_FLAG)
    if llm_endpoint is not None:
        arguments.extend(["--llm-endpoint", llm_endpoint])
    if llm_model is not None:
        arguments.extend(["--llm-model", llm_model])
    if llm_batch is not None:
        arguments.extend(["--llm-batch", str(llm_batch)])
    for item in note:
        arguments.extend(["--note", item])
    raise SystemExit(subprocess.call(arguments))


# ---------------------------------------------------------------------------
# The headline benchmark (P6).
# ---------------------------------------------------------------------------

_BENCH_SCRIPT: Final[str] = "bench.py"

_BENCH_ABSENT: Final[str] = (
    "the headline benchmark needs a source checkout: scripts/bench.py is not in "
    "this installation, and neither is the corpus it measures against. Clone the "
    "repository and install the dev extra."
)


@cli.command(
    "bench",
    context_settings={"ignore_unknown_options": True},
    help="The multi-engine headline benchmark. Wraps scripts/bench.py; needs a source checkout.",
)
@click.option("--corpus", "corpus_dir", type=click.Path(path_type=Path), default=Path("corpus"))
@click.option("--split-file", type=click.Path(path_type=Path), default=None)
@click.option("--split", type=click.Choice(["dev", "test"]), default="test", show_default=True)
@click.option(
    "--engines",
    type=str,
    default="rules,ngram,llm",
    show_default=True,
    help="comma separated; every one is checked before any of them runs",
)
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("experiments/results"),
    show_default=True,
)
@click.option("--bench-id", type=str, default=None)
@click.option("--run-id-prefix", type=str, default=None)
@click.option("--model", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--seed", type=int, default=None)
@click.option(
    "--repeats",
    type=int,
    default=None,
    help="time the classifier this many times; the predictions are written once",
)
@click.option(
    "--warmup", type=int, default=None, help="discarded timing passes before the measured one"
)
@click.option("--llm-endpoint", type=str, default=None)
@click.option("--llm-model", type=str, default=None)
@click.option("--llm-batch", type=int, default=None)
@click.option(
    _MEASURING_FLAG,
    "measuring",
    is_flag=True,
    default=False,
    help="required for --split test; the test split is spent the first time it is read",
)
@click.option("--note", multiple=True, help="a note recorded in every run manifest")
@click.option("--skip-analysis", is_flag=True, default=False)
def bench(
    corpus_dir: Path,
    split_file: Path | None,
    split: str,
    engines: str,
    out: Path,
    bench_id: str | None,
    run_id_prefix: str | None,
    model: Path | None,
    seed: int | None,
    repeats: int | None,
    warmup: int | None,
    llm_endpoint: str | None,
    llm_model: str | None,
    llm_batch: int | None,
    measuring: bool,
    note: tuple[str, ...],
    skip_analysis: bool,
) -> None:
    """Run every named engine on one split and assemble the section 13.4 grid.

    Fails fast when an engine's prerequisite is missing, and does it before the
    first page loads rather than after the first engine has run. Spec section 14
    asks for that so a three-engine benchmark cannot quietly report two, and the
    timing matters because the language-model engine takes long enough that
    discovering the problem at the end would waste the run.
    """
    script = find_script(Path.cwd(), _BENCH_SCRIPT)
    if script is None:
        _fail(_BENCH_ABSENT, EXIT_USAGE)
    arguments = [
        sys.executable,
        str(script),
        "--corpus",
        str(corpus_dir),
        "--split",
        split,
        "--engines",
        engines,
        "--out",
        str(out),
    ]
    for flag, value in (
        ("--split-file", split_file),
        ("--bench-id", bench_id),
        ("--run-id-prefix", run_id_prefix),
        ("--model", model),
        ("--seed", seed),
        ("--repeats", repeats),
        ("--warmup", warmup),
        ("--llm-endpoint", llm_endpoint),
        ("--llm-model", llm_model),
        ("--llm-batch", llm_batch),
    ):
        if value is not None:
            arguments.extend([flag, str(value)])
    if measuring:
        arguments.append(_MEASURING_FLAG)
    if skip_analysis:
        arguments.append("--skip-analysis")
    for item in note:
        arguments.extend(["--note", item])
    raise SystemExit(subprocess.call(arguments))


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def check_boundaries(argv: Sequence[str]) -> str | None:
    """Return the boundary message for the first out-of-scope flag in ``argv``.

    Matches ``--flag`` and ``--flag=value`` and nothing else, so a path or a
    value that happens to contain the word is not mistaken for the flag.
    """
    for argument in argv:
        name = argument.split("=", 1)[0]
        message = BOUNDARY_FLAGS.get(name)
        if message is not None:
            return f"{name} does not exist, on purpose: {message}"
    return None


def main() -> None:
    """Console script entry point.

    Owns exit codes 2 and 4. Everything a user can get wrong is answered with a
    sentence and code 2; anything that reaches the last clause is a bug in this
    program, and it says so, prints the traceback a bug report needs, and exits 4
    rather than pretending the audit produced a clean result.
    """
    argv = sys.argv[1:]
    boundary = check_boundaries(argv)
    if boundary is not None:
        click.echo(f"autofill-audit: {boundary}", err=True)
        raise SystemExit(EXIT_USAGE)

    try:
        code = cli.main(args=argv, standalone_mode=False)
    except SystemExit:
        raise
    except click.ClickException as error:
        error.show()
        raise SystemExit(EXIT_USAGE) from error
    except click.exceptions.Abort as error:
        click.echo("autofill-audit: interrupted", err=True)
        raise SystemExit(EXIT_USAGE) from error
    except Exception as error:
        traceback.print_exc()
        click.echo(
            "autofill-audit: that is a bug in autofill-audit, not in your page. "
            "Please open an issue at "
            "https://github.com/Olajide-Badejo/autofill-audit/issues with the "
            "traceback above and the page you were auditing.",
            err=True,
        )
        raise SystemExit(EXIT_INTERNAL) from error
    raise SystemExit(code if isinstance(code, int) else EXIT_OK)


assert set(BOUNDARY_FLAGS) == {"--crawl", "--depth", "--fill", "--fix", "--write"}, (
    "the boundary flags are the five of spec section 0.4, no more and no fewer"
)


if __name__ == "__main__":
    # ``python -m autofill_audit.cli`` runs the same entry point the console
    # script does. The end-to-end tests use it because they have to run the tool
    # in a subprocess, and a second way in that behaved differently from the
    # first would make those tests prove the wrong thing.
    main()
