"""The JSONL run-log writer at the schema of spec section 13.1.

Run logs are written in the schema the external harness consumes directly; they
are never reshaped at the last moment to fit it (spec section 0.5). That
sentence is the whole design constraint, and P5 found out what it costs: the
harness's own log parser cannot read this schema, because it expects a training
curve and this is not one. The cost is recorded in `docs/cross-repo-tasks.md`
and paid there rather than paid here by bending the schema, which is what
"never post-processes them into a harness-specific shape" means once it stops
being free.

One object per classified field
-------------------------------

The row is the unit of analysis. Everything that varies per field is on the
row; everything that is constant for a run is in the sibling manifest, and
nothing is in both. Two keys on the row look like exceptions and are not.
``corpus_manifest_sha`` and ``engine_describe`` are repeated on every row
because spec section 13.1 puts them there, and because a run log that has been
separated from its manifest, which is what happens the moment somebody
concatenates two of them, still has to say what produced each row.

``template_id`` is the field the statistics need and the one nothing upstream
knows about
------------------------------------------------------------------------------

Fields inside one template share an author, so they are not independent, and
spec section 13.3 resamples at the template level because of it. The template id
lives on the answer key document, not on the descriptor, so it reaches this
module only because the evaluation loader carries it alongside. A row without it
is a row the clustered permutation test cannot use, so it is a required field
here and an empty one is an error rather than a blank.
"""

from __future__ import annotations

import json
import platform
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Self

__all__ = [
    "CONFIDENCE_KINDS",
    "CONFUSION_FILENAME",
    "MANIFEST_FILENAME",
    "METRICS_FILENAME",
    "RUNLOG_FILENAME",
    "SCHEMA_VERSION",
    "Manifest",
    "RunLogError",
    "RunLogRow",
    "confidence_kind_for",
    "machine_descriptor",
    "make_run_id",
    "read_manifest",
    "read_rows",
    "resolved_versions",
    "sha256_of",
    "utc_now",
    "write_manifest",
    "write_rows",
]

SCHEMA_VERSION: Final[str] = "1.0.0"
"""The run-log schema version of spec section 13.1, written on every row.

A string rather than an integer because spec section 13.1 writes it as one, and
because a consumer deciding whether it can read a file wants to know whether the
change was additive."""

MANIFEST_SCHEMA_VERSION: Final[str] = "1.0.0"
"""The sibling manifest's own version (spec section 18), separate from the row
schema's, because the two documents change for different reasons."""

RUNLOG_FILENAME: Final[str] = "run.jsonl"
MANIFEST_FILENAME: Final[str] = "manifest.json"
METRICS_FILENAME: Final[str] = "metrics.json"
CONFUSION_FILENAME: Final[str] = "confusion.json"

CONFIDENCE_KIND_CALIBRATED: Final[str] = "calibrated"
CONFIDENCE_KIND_RULE_TIER: Final[str] = "rule_tier"
CONFIDENCE_KIND_SELF_REPORTED: Final[str] = "self_reported"

CONFIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        CONFIDENCE_KIND_CALIBRATED,
        CONFIDENCE_KIND_RULE_TIER,
        CONFIDENCE_KIND_SELF_REPORTED,
    }
)
"""The three values spec section 13.1 allows, and no fourth.

The point of the key is that no downstream analysis can average a regex tier
together with a calibrated probability, and a key with an open vocabulary would
not achieve that: the first engine to invent a fourth word would be pooled with
whichever of the three a reader guessed it resembled."""

_DESCRIBE_TO_KIND: Final[dict[str, str]] = {
    "calibrated-probability": CONFIDENCE_KIND_CALIBRATED,
    "tier": CONFIDENCE_KIND_RULE_TIER,
    "self-reported": CONFIDENCE_KIND_SELF_REPORTED,
}
"""How an engine's own ``describe()`` word maps onto the schema's three.

The engines say ``calibrated-probability`` and ``tier`` because those are the
words their renderers branch on: P3 and P4 fixed them and
``audit/engine.py::_confidence_display`` is the single place that reads them.
Spec section 13.1's vocabulary is different and shorter. Rather than change
either, the mapping is written down once, here, and it is total. An engine whose
word is not in it is an error, not a default, and P6's language-model engine
adds its word to this table deliberately, which is the point."""


class RunLogError(ValueError):
    """A row or a manifest could not be built or read.

    A ``ValueError`` because every case it covers is a caller handing this
    module something the schema does not describe, and that caller is a script
    that should stop rather than write a row a statistical test will later read
    as a measurement.
    """


def confidence_kind_for(describe: Mapping[str, str]) -> str:
    """Map an engine's ``describe()`` onto the schema's ``confidence_kind``.

    Raises:
        RunLogError: the engine reports a confidence kind this schema has no
            word for. Deliberately an error: an engine whose confidences are on
            an unknown scale must be given a word on purpose, because the whole
            purpose of the key is that nothing downstream pools two scales.
    """
    reported = describe.get("confidence_kind")
    if reported is None:
        raise RunLogError(
            "the engine's describe() carries no confidence_kind; spec section 13.1 "
            "requires one so that no analysis pools a tier with a probability"
        )
    try:
        return _DESCRIBE_TO_KIND[reported]
    except KeyError as error:
        known = ", ".join(sorted(_DESCRIBE_TO_KIND))
        raise RunLogError(
            f"the engine reports confidence_kind {reported!r}, which this schema has no "
            f"word for. Known kinds: {known}. Add the mapping deliberately rather than "
            "defaulting, or the run log will carry two confidence scales under one name."
        ) from error


@dataclass(frozen=True, slots=True)
class RunLogRow:
    """One classified field, at the schema of spec section 13.1.

    A frozen dataclass rather than a dictionary because ground rule 9 forbids
    cross-module dictionaries except where a schema serialises, and this is the
    module where that schema serialises. Everything upstream of ``to_json``
    holds a typed object.
    """

    run_id: str
    engine: str
    engine_describe: Mapping[str, str]
    corpus_manifest_sha: str
    split: str
    form_id: str
    form_family: str
    locale: str
    tier: str
    template_id: str
    selector: str
    true_label: str
    pred_label: str
    confidence: float
    confidence_kind: str
    signals: tuple[str, ...] = ()
    runner_up_label: str | None = None
    runner_up_confidence: float | None = None
    latency_us: float | None = None
    declared_token: str | None = None
    finding_codes: tuple[str, ...] = ()
    extraction_warnings: tuple[str, ...] = ()
    prompt_version: str | None = None

    def __post_init__(self) -> None:
        if self.confidence_kind not in CONFIDENCE_KINDS:
            known = ", ".join(sorted(CONFIDENCE_KINDS))
            raise RunLogError(f"confidence_kind {self.confidence_kind!r} is not one of {known}")
        if not self.template_id:
            raise RunLogError(
                f"{self.selector} on {self.form_id} carries no template_id. Spec section "
                "13.3 clusters the resampling by template, so a row without one is a row "
                "no significance test in this project can use."
            )

    @property
    def correct(self) -> bool:
        """Whether the prediction matched the answer key, as a plain equality.

        Label equality, not the audit engine's equivalence sets. The two answer
        different questions and both are reported: this one is the classifier
        comparison, and the equivalence-aware one is the finding-level metric,
        which reaches this row through ``finding_codes`` instead.
        """
        return self.true_label == self.pred_label

    def to_json(self) -> dict[str, Any]:
        """Emit the row exactly as spec section 13.1 writes it.

        Key order is the specification's order rather than alphabetical, because
        a person reading one line of a run log in a terminal reads it in the
        order the document that defines it uses.
        """
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "engine": self.engine,
            "engine_describe": dict(self.engine_describe),
            "prompt_version": self.prompt_version,
            "corpus_manifest_sha": self.corpus_manifest_sha,
            "split": self.split,
            "form_id": self.form_id,
            "form_family": self.form_family,
            "locale": self.locale,
            "tier": self.tier,
            "template_id": self.template_id,
            "selector": self.selector,
            "true_label": self.true_label,
            "pred_label": self.pred_label,
            "correct": self.correct,
            "confidence": self.confidence,
            "confidence_kind": self.confidence_kind,
            "runner_up_label": self.runner_up_label,
            "runner_up_confidence": self.runner_up_confidence,
            "signals": list(self.signals),
            "latency_us": self.latency_us,
            "declared_token": self.declared_token,
            "finding_codes": list(self.finding_codes),
            "extraction_warnings": list(self.extraction_warnings),
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        """Rebuild one row, refusing a schema version this build cannot read."""
        version = payload.get("schema_version")
        if version != SCHEMA_VERSION:
            raise RunLogError(
                f"this build reads run-log schema {SCHEMA_VERSION}, found {version!r}"
            )
        describe = payload.get("engine_describe")
        if not isinstance(describe, Mapping):
            raise RunLogError("engine_describe must be an object")
        return cls(
            run_id=_string(payload, "run_id"),
            engine=_string(payload, "engine"),
            engine_describe={str(key): str(value) for key, value in describe.items()},
            corpus_manifest_sha=_string(payload, "corpus_manifest_sha"),
            split=_string(payload, "split"),
            form_id=_string(payload, "form_id"),
            form_family=_string(payload, "form_family"),
            locale=_string(payload, "locale"),
            tier=_string(payload, "tier"),
            template_id=_string(payload, "template_id"),
            selector=_string(payload, "selector"),
            true_label=_string(payload, "true_label"),
            pred_label=_string(payload, "pred_label"),
            confidence=_number(payload, "confidence"),
            confidence_kind=_string(payload, "confidence_kind"),
            signals=_strings(payload, "signals"),
            runner_up_label=_optional_string(payload, "runner_up_label"),
            runner_up_confidence=_optional_number(payload, "runner_up_confidence"),
            latency_us=_optional_number(payload, "latency_us"),
            declared_token=_optional_string(payload, "declared_token"),
            finding_codes=_strings(payload, "finding_codes"),
            extraction_warnings=_strings(payload, "extraction_warnings"),
            prompt_version=_optional_string(payload, "prompt_version"),
        )


def _string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise RunLogError(f"{key} must be a string, found {value!r}")
    return value


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RunLogError(f"{key} must be a string or null, found {value!r}")
    return value


def _number(payload: Mapping[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RunLogError(f"{key} must be a number, found {value!r}")
    return float(value)


def _optional_number(payload: Mapping[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RunLogError(f"{key} must be a number or null, found {value!r}")
    return float(value)


def _strings(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key, [])
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise RunLogError(f"{key} must be a list of strings, found {value!r}")
    return tuple(str(item) for item in value)


def write_rows(path: Path, rows: Sequence[RunLogRow]) -> int:
    """Write a run log, refusing to overwrite one that already exists.

    Result files are append-only history (spec section 18): a wrong result gets
    a new run id and the old one stays. Refusing here is what makes that a
    property of the code rather than a habit, since the cheapest way to make an
    inconvenient number disappear is to run the same command again.
    """
    if path.exists():
        raise RunLogError(
            f"{path} already exists. Result files are append-only history (spec section "
            "18): a wrong result gets a new run id, never a regeneration."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_json(), ensure_ascii=False, sort_keys=False))
            handle.write("\n")
    return len(rows)


def read_rows(path: Path) -> list[RunLogRow]:
    """Read a run log back, one object per line, in file order."""
    rows: list[RunLogRow] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as error:
                raise RunLogError(f"{path}:{number}: not valid JSON ({error})") from error
            if not isinstance(payload, Mapping):
                raise RunLogError(f"{path}:{number}: each line must be an object")
            rows.append(RunLogRow.from_json(payload))
    return rows


# ---------------------------------------------------------------------------
# The sibling manifest (spec section 18).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Manifest:
    """Everything spec section 18 requires beside a result file.

    The ``git_dirty`` flag is load bearing rather than informational: a result
    produced from a dirty tree is marked dirty and is *not citable*, so law 3's
    chain from a README number to a commit stops at this field when it is true.
    """

    run_id: str
    command_line: str
    split: str
    engine: str
    engine_describe: Mapping[str, str]
    threshold_describe: Mapping[str, str]
    artefact_sha256: Mapping[str, str]
    corpus_manifest_sha: str
    split_file_sha: str
    seed: int
    git_commit: str
    git_dirty: bool
    dependency_versions: Mapping[str, str]
    machine: Mapping[str, str]
    started_at: str
    finished_at: str
    row_count: int
    form_count: int
    notes: tuple[str, ...] = ()
    schema_version: str = MANIFEST_SCHEMA_VERSION

    def to_json(self) -> dict[str, Any]:
        """Emit the manifest document."""
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "command_line": self.command_line,
            "split": self.split,
            "engine": self.engine,
            "engine_describe": dict(self.engine_describe),
            "threshold_describe": dict(self.threshold_describe),
            "artefact_sha256": dict(self.artefact_sha256),
            "corpus_manifest_sha": self.corpus_manifest_sha,
            "split_file_sha": self.split_file_sha,
            "seed": self.seed,
            "git": {"commit": self.git_commit, "dirty": self.git_dirty},
            "dependency_versions": dict(self.dependency_versions),
            "machine": dict(self.machine),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "row_count": self.row_count,
            "form_count": self.form_count,
            "notes": list(self.notes),
        }

    @property
    def citable(self) -> bool:
        """Whether law 3 permits a number from this run to appear in prose."""
        return not self.git_dirty and bool(self.git_commit)


def utc_now() -> str:
    """An ISO 8601 timestamp in UTC, to the second."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_run_id(engine: str, commit: str, *, moment: datetime | None = None) -> str:
    """Build the run id of spec section 13.1: timestamp, engine, short commit.

    The commit goes in the id so that two runs of the same engine on the same
    day are distinguishable by the thing that actually differed between them.
    """
    stamp = (moment or datetime.now(UTC)).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{stamp}_{engine}_{commit[:7] or 'unknown'}"


def machine_descriptor() -> dict[str, str]:
    """The machine this ran on, at the detail spec section 18 asks for.

    The CPU model comes from ``/proc/cpuinfo`` where it exists, because
    ``platform.processor()`` returns the architecture on Linux and a latency
    table whose hardware column said ``x86_64`` would be saying nothing.
    """
    return {
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "cpu_model": _cpu_model(),
        "cpu_count": str(_cpu_count()),
        "gpu_present": _gpu_present(),
    }


def _cpu_model() -> str:
    """The CPU's marketing name, or the architecture when nothing better exists."""
    path = Path("/proc/cpuinfo")
    if path.is_file():
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:  # pragma: no cover - an unreadable procfs is not worth a branch
            return platform.machine()
    return platform.processor() or platform.machine()


def _cpu_count() -> int:
    """Logical core count, which is what a latency figure has to be read against."""
    import os

    return os.cpu_count() or 0


def _gpu_present() -> str:
    """Whether a GPU is visible, as a word rather than a guess at which one.

    Spec section 18 asks for GPU presence. Inference in this project is CPU only
    by pinned assumption, so the answer is recorded to show the GPU was not used
    rather than to describe what it is.
    """
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except OSError, subprocess.SubprocessError:
        return "none detected"
    lines = completed.stdout.strip().splitlines()
    if completed.returncode != 0 or not lines:
        return "none detected"
    return lines[0].strip()


def resolved_versions(names: Sequence[str]) -> dict[str, str]:
    """The installed version of every named distribution, plus the interpreter."""
    from importlib.metadata import PackageNotFoundError, version

    resolved: dict[str, str] = {"python": platform.python_version()}
    for name in names:
        try:
            resolved[name] = version(name)
        except PackageNotFoundError:
            resolved[name] = "absent"
    return resolved


def sha256_of(path: Path) -> str:
    """The sha256 of a file, for the manifest's content addressing."""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(path: Path, manifest: Manifest) -> None:
    """Write the sibling manifest, refusing to overwrite an existing one."""
    if path.exists():
        raise RunLogError(f"{path} already exists; result files are append-only")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.to_json(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_manifest(path: Path) -> dict[str, Any]:
    """Read a manifest document, as a plain mapping for a checker to inspect."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RunLogError(f"{path}: a manifest must be an object")
    return payload
