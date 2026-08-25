"""Threshold policy, loaded from a committed JSON rather than hardcoded.

Spec section 11.3. Two numbers decide whether an inference is confident enough to
accuse a page of a defect, and they are **never** literals in ``engine.py``. They
live in ``thresholds.json`` beside this module, they travel in the wheel, and the
file records what produced them.

At P3 what produced them is the documented rule-tier band mapping, and the file
says so in its ``basis`` key and at length in its ``note``. At P4 they are chosen
on the dev split against a precision target committed before the measurement, and
the file grows the keys that record the target, the achieved precision and recall,
and the corpus manifest sha. Nothing in this module changes when that happens,
which is the point of loading rather than hardcoding.

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
    "THRESHOLDS_RESOURCE",
    "Thresholds",
    "ThresholdsError",
    "load_thresholds",
]

THRESHOLDS_RESOURCE: Final[str] = "thresholds.json"
"""The committed file, read from the installed package rather than from a path
relative to the source tree, so that a wheel and a checkout behave identically."""

_SCHEMA_VERSION: Final[int] = 1


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
    them says so.
    """

    tau_high: float
    tau_low: float
    basis: str
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
    def from_json(cls, payload: Any, *, source: str = THRESHOLDS_RESOURCE) -> Self:
        """Rebuild from the committed document, validating as it goes."""
        if not isinstance(payload, dict):
            raise ThresholdsError(f"{source}: expected an object")
        version = payload.get("schema_version")
        if version != _SCHEMA_VERSION:
            raise ThresholdsError(
                f"{source}: this build reads schema version {_SCHEMA_VERSION}, found {version!r}"
            )
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
            source=source,
            target_precision=_optional_number(payload, "target_precision", source=source),
            dev_precision=_optional_number(payload, "dev_precision", source=source),
            dev_recall=_optional_number(payload, "dev_recall", source=source),
            corpus_manifest_sha=_optional_str(payload, "corpus_manifest_sha", source=source),
            derived_on=_optional_str(payload, "derived_on", source=source),
        )


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
def load_thresholds() -> Thresholds:
    """Load and validate the committed thresholds.

    Cached because it is read once per run and the file cannot change underneath
    a running process. Tests that need a different policy build a ``Thresholds``
    directly rather than patching this, which keeps the cache honest.
    """
    text = resources.files("autofill_audit.audit").joinpath(THRESHOLDS_RESOURCE).read_text("utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ThresholdsError(f"{THRESHOLDS_RESOURCE}: not valid JSON ({error})") from error
    return Thresholds.from_json(payload)
