"""Threshold policy: loading, validation, and the override.

Spec section 11.3 forbids the two numbers being literals in ``engine.py``, so the
first thing asserted here is that the committed file is the only place they come
from and that a build which cannot read it says so rather than falling back to
something plausible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autofill_audit.audit.thresholds import (
    THRESHOLDS_RESOURCE,
    Thresholds,
    ThresholdsError,
    load_thresholds,
)
from autofill_audit.classify.base import TIER_CONFIDENCE, ConfidenceTier


def _document(root: Path) -> dict[str, object]:
    """The committed thresholds document, read from the source tree."""
    path = root / "src" / "autofill_audit" / "audit" / THRESHOLDS_RESOURCE
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_committed_file_loads_and_says_where_its_numbers_came_from() -> None:
    thresholds = load_thresholds()
    assert thresholds.basis == "rule-tier-band-mapping"
    assert thresholds.source == THRESHOLDS_RESOURCE
    assert 0.0 <= thresholds.tau_low <= thresholds.tau_high <= 1.0


def test_nothing_is_claimed_to_be_measured_yet() -> None:
    """Law 4: an estimate is labeled as an estimate at the point of display, and
    a number nobody has measured is null rather than plausible."""
    thresholds = load_thresholds()
    assert thresholds.measured is False
    assert thresholds.dev_precision is None
    assert thresholds.target_precision is None
    assert thresholds.corpus_manifest_sha is None
    assert thresholds.describe()["measured"] == "false"


def test_the_band_mapping_is_the_one_the_file_documents(repo_root: Path) -> None:
    """HIGH and MEDIUM are confident, LOW is a note, NONE says nothing."""
    thresholds = load_thresholds()
    document = _document(repo_root)
    assert document["tier_bands"] == {
        "HIGH": "confident",
        "MEDIUM": "confident",
        "LOW": "low",
        "NONE": "silent",
    }
    assert TIER_CONFIDENCE[ConfidenceTier.HIGH] >= thresholds.tau_high
    assert TIER_CONFIDENCE[ConfidenceTier.MEDIUM] >= thresholds.tau_high
    assert thresholds.tau_low <= TIER_CONFIDENCE[ConfidenceTier.LOW] < thresholds.tau_high
    assert TIER_CONFIDENCE[ConfidenceTier.NONE] < thresholds.tau_low


def test_the_file_and_the_tier_constants_agree(repo_root: Path) -> None:
    """Two copies of one number is one copy too many, so they are checked equal."""
    document = _document(repo_root)
    recorded = document["tier_values"]
    assert isinstance(recorded, dict)
    for tier, value in TIER_CONFIDENCE.items():
        assert recorded[tier.value] == value


def test_a_wrong_schema_version_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="schema version"):
        Thresholds.from_json({"schema_version": 99, "tau_high": 0.7, "tau_low": 0.4})


def test_thresholds_out_of_order_are_refused() -> None:
    with pytest.raises(ThresholdsError, match="tau_low <= tau_high"):
        Thresholds.from_json(
            {"schema_version": 1, "tau_high": 0.2, "tau_low": 0.8, "basis": "test"}
        )


def test_a_missing_basis_is_refused() -> None:
    """A threshold that cannot say where it came from is folklore."""
    with pytest.raises(ThresholdsError, match="basis"):
        Thresholds.from_json({"schema_version": 1, "tau_high": 0.7, "tau_low": 0.4})


def test_a_non_numeric_threshold_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="must be a number"):
        Thresholds.from_json(
            {"schema_version": 1, "tau_high": "high", "tau_low": 0.4, "basis": "test"}
        )


def test_a_non_object_document_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="expected an object"):
        Thresholds.from_json([1, 2, 3])


def test_an_optional_number_of_the_wrong_type_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="dev_precision"):
        Thresholds.from_json(
            {
                "schema_version": 1,
                "tau_high": 0.7,
                "tau_low": 0.4,
                "basis": "test",
                "dev_precision": "high",
            }
        )


def test_an_optional_string_of_the_wrong_type_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="corpus_manifest_sha"):
        Thresholds.from_json(
            {
                "schema_version": 1,
                "tau_high": 0.7,
                "tau_low": 0.4,
                "basis": "test",
                "corpus_manifest_sha": 7,
            }
        )


def test_an_override_rewrites_the_basis_as_well_as_the_number() -> None:
    """A report that still claimed the file's basis would be wrong about itself."""
    overridden = load_thresholds().with_low(0.1)
    assert overridden.tau_low == 0.1
    assert "overridden on the command line" in overridden.basis
    assert overridden.tau_high == load_thresholds().tau_high


def test_an_override_that_would_empty_the_low_band_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="above the high threshold"):
        load_thresholds().with_low(0.95)


def test_the_loader_is_cached_so_a_run_reads_one_policy() -> None:
    assert load_thresholds() is load_thresholds()


def test_describe_carries_the_numbers_verbatim_for_the_run_log() -> None:
    described = load_thresholds().describe()
    assert described["tau_high"] == repr(load_thresholds().tau_high)
    assert described["source"] == THRESHOLDS_RESOURCE


def test_measured_becomes_true_once_a_dev_precision_exists() -> None:
    """What P4 will produce, asserted now so the display branch has a test."""
    derived = Thresholds(tau_high=0.8, tau_low=0.4, basis="dev-split", dev_precision=0.97)
    assert derived.measured is True
    assert derived.describe()["measured"] == "true"
