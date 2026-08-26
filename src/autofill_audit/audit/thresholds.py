"""Threshold policy, loaded from a committed JSON rather than hardcoded.

Spec section 11.3. Two numbers decide whether an inference is confident enough to
accuse a page of a defect, and they are **never** literals in ``engine.py``. They
live in ``thresholds.json`` beside this module, they travel in the wheel, and the
file records what produced them.

**One block per engine, because one number cannot serve two scales.** The rule
baseline's confidences are four ordered tiers that are not probabilities and are
not measured; the n-gram engine's are calibrated probabilities derived on the dev
split against a pre-registered precision target. A single pair of thresholds
across both would mean that moving the measured boundary silently reclassified
every rule-engine finding on every page, which is precisely the baseline drift
ground rule 12 exists to prevent. So the document carries a block per engine,
load_thresholds takes the engine name, and an engine with no block is an
error rather than an inheritance.

At P3 the file held one set of numbers and its basis was the documented rule-tier
band mapping. At P4 it grew the schema above and the derived block beside it. The
rule block is byte-identical to what P3 committed, which is why no golden
snapshot moved.

**Changing a threshold is a CHANGELOG entry and a re-run** (ground rule 12). It
moves every finding on every page, and a change that quiet deserves to be as
visible as a change to the finding text, which the golden snapshots already make
unmissable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Final, Self

__all__ = [
    "DEFAULT_ENGINE",
    "THRESHOLDS_RESOURCE",
    "Thresholds",
    "ThresholdsError",
    "available_engines",
    "load_document",
    "load_thresholds",
]

THRESHOLDS_RESOURCE: Final[str] = "thresholds.json"
"""The committed file, read from the installed package rather than from a path
relative to the source tree, so that a wheel and a checkout behave identically."""

_SCHEMA_VERSION: Final[int] = 2
"""Bumped at P4, when the document grew a block per engine. A build reading the
old shape would silently apply the rule tiers to calibrated probabilities."""

DEFAULT_ENGINE: Final[str] = "rules"
"""The block used when a caller names no engine. The rule baseline, because it is
the engine that always loads and the permanent fallback of spec section 10.1."""


class ThresholdsError(ValueError):
    """The threshold file is missing, unreadable, or internally inconsistent.

    A ``ValueError`` so that the CLI can map it to the usage exit code of spec
    section 11.5 without importing this module to catch it. It is raised eagerly
    and loudly: a tool that fell back to a default threshold because it could not
    read the real one would be quietly running a different policy from the one
    its report claims.
    """


@dataclass(frozen=True, slots=True)
class Thresholds:
    """The two decision boundaries, and where they came from.

    ``basis`` is the honest label. While it reads ``rule-tier-band-mapping`` the
    numbers are a mapping rather than a measurement, and everything that displays
    them says so. ``engine`` names the block these came from, because at P4 there
    is more than one and a reader of a run manifest has to be able to tell which
    scale the two numbers are on.
    """

    tau_high: float
    tau_low: float
    basis: str
    engine: str = DEFAULT_ENGINE
    source: str = THRESHOLDS_RESOURCE
    target_precision: float | None = None
    dev_precision: float | None = None
    dev_recall: float | None = None
    corpus_manifest_sha: str | None = None
    derived_on: str | None = None

    @property
    def measured(self) -> bool:
        """Whether these thresholds were derived from a measurement.

        False at P3. A renderer that prints the thresholds uses this to decide
        whether to label them as an estimate at the point of display, which is
        what law 4 requires.
        """
        return self.dev_precision is not None

    def with_low(self, tau_low: float) -> Thresholds:
        """Return a copy with ``tau_low`` overridden, as ``--min-confidence`` does.

        The basis is rewritten as well, because an overridden threshold did not
        come from the file any more and a report that still claimed it did would
        be wrong about its own configuration.

        Raises:
            ThresholdsError: if the override would put the low threshold above
                the high one, which would make the low-confidence band empty and
                silently delete every note the run would have produced.
        """
        if not 0.0 <= tau_low <= 1.0:
            raise ThresholdsError(f"--min-confidence must be between 0 and 1, got {tau_low}")
        if tau_low > self.tau_high:
            raise ThresholdsError(
                f"--min-confidence {tau_low} is above the high threshold {self.tau_high}; "
                "that would empty the low-confidence band rather than widen it"
            )
        return Thresholds(
            tau_high=self.tau_high,
            tau_low=tau_low,
            basis=f"{self.basis}, low threshold overridden on the command line",
            engine=self.engine,
            source=self.source,
            target_precision=self.target_precision,
            dev_precision=self.dev_precision,
            dev_recall=self.dev_recall,
            corpus_manifest_sha=self.corpus_manifest_sha,
            derived_on=self.derived_on,
        )

    def describe(self) -> dict[str, str]:
        """Return the identity a report and a run manifest copy verbatim."""
        return {
            "tau_high": repr(self.tau_high),
            "tau_low": repr(self.tau_low),
            "basis": self.basis,
            "source": self.source,
            "measured": "true" if self.measured else "false",
        }

    @classmethod
    def from_json(
        cls,
        payload: Any,
        *,
        engine: str = DEFAULT_ENGINE,
        source: str = THRESHOLDS_RESOURCE,
    ) -> Self:
        """Rebuild one engine's block out of the committed document.

        Raises:
            ThresholdsError: the document is malformed, or it carries no block
                for ``engine``. The second of those is deliberately an error and
                not a fallback: an engine's decision boundary is a recorded
                choice, and inheriting another engine's would apply one
                confidence scale to numbers produced on a different one.
        """
        document = _require_object(payload, source=source)
        version = document.get("schema_version")
        if version != _SCHEMA_VERSION:
            raise ThresholdsError(
                f"{source}: this build reads schema version {_SCHEMA_VERSION}, found {version!r}"
            )
        engines = document.get("engines")
        if not isinstance(engines, dict) or not engines:
            raise ThresholdsError(f"{source}: engines must be an object naming at least one engine")
        block = engines.get(engine)
        if block is None:
            known = ", ".join(sorted(engines))
            raise ThresholdsError(
                f"{source}: no threshold block for the {engine} engine. Known blocks: {known}. "
                "Every engine's decision boundary is a deliberate, recorded choice, so a "
                "missing one is an error rather than an inheritance."
            )
        return cls._from_block(block, engine=engine, source=source)

    @classmethod
    def _from_block(cls, block: Any, *, engine: str, source: str) -> Self:
        """Rebuild from one engine's block, validating as it goes."""
        payload = _require_object(block, source=f"{source}: engines.{engine}")
        source = f"{source}: engines.{engine}"
        tau_high = _number(payload, "tau_high", source=source)
        tau_low = _number(payload, "tau_low", source=source)
        if not 0.0 <= tau_low <= tau_high <= 1.0:
            raise ThresholdsError(
                f"{source}: thresholds must satisfy 0 <= tau_low <= tau_high <= 1, "
                f"found tau_low={tau_low} and tau_high={tau_high}"
            )
        basis = payload.get("basis")
        if not isinstance(basis, str) or not basis:
            raise ThresholdsError(f"{source}: basis must say where these numbers came from")
        return cls(
            tau_high=tau_high,
            tau_low=tau_low,
            basis=basis,
            engine=engine,
            source=THRESHOLDS_RESOURCE,
            target_precision=_optional_number(payload, "target_precision", source=source),
            dev_precision=_optional_number(payload, "dev_precision", source=source),
            dev_recall=_optional_number(payload, "dev_recall", source=source),
            corpus_manifest_sha=_optional_str(payload, "corpus_manifest_sha", source=source),
            derived_on=_optional_str(payload, "derived_on", source=source),
        )


def _require_object(payload: Any, *, source: str) -> dict[str, Any]:
    """Return ``payload`` as a JSON object, or raise."""
    if not isinstance(payload, dict):
        raise ThresholdsError(f"{source}: expected an object")
    return payload


def _number(payload: dict[str, Any], key: str, *, source: str) -> float:
    """Read a required number."""
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ThresholdsError(f"{source}: {key} must be a number, found {value!r}")
    return float(value)


def _optional_number(payload: dict[str, Any], key: str, *, source: str) -> float | None:
    """Read a number that is null until a measurement fills it in."""
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ThresholdsError(f"{source}: {key} must be a number or null, found {value!r}")
    return float(value)


def _optional_str(payload: dict[str, Any], key: str, *, source: str) -> str | None:
    """Read a string that is null until a measurement fills it in."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ThresholdsError(f"{source}: {key} must be a string or null, found {value!r}")
    return value


@cache
def load_document() -> dict[str, Any]:
    """Read the committed document, once per process."""
    text = resources.files("autofill_audit.audit").joinpath(THRESHOLDS_RESOURCE).read_text("utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ThresholdsError(f"{THRESHOLDS_RESOURCE}: not valid JSON ({error})") from error
    return _require_object(payload, source=THRESHOLDS_RESOURCE)


def available_engines() -> tuple[str, ...]:
    """The engines the committed document carries a block for, sorted."""
    engines = load_document().get("engines")
    if not isinstance(engines, dict):
        return ()
    return tuple(sorted(str(name) for name in engines))


@cache
def load_thresholds(engine: str = DEFAULT_ENGINE) -> Thresholds:
    """Load and validate one engine's committed thresholds.

    Cached per engine because it is read once per run and the file cannot change
    underneath a running process. Tests that need a different policy build a
    ``Thresholds`` directly rather than patching this, which keeps the cache
    honest.
    """
    return Thresholds.from_json(load_document(), engine=engine)
