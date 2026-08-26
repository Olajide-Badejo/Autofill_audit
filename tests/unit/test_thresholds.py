"""Threshold policy: loading, validation, the per-engine blocks, and the override.

Spec section 11.3 forbids the two numbers being literals in ``engine.py``, so the
first thing asserted here is that the committed file is the only place they come
from and that a build which cannot read it says so rather than falling back to
something plausible.

P4 gave the document a block per engine. The rule tiers and a calibrated
probability are different scales, and a single pair of thresholds across both
would mean that deriving the measured boundary silently reclassified every
rule-engine finding on every page. So the block is chosen by engine, a missing
block is an error rather than an inheritance, and both halves are asserted here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autofill_audit.audit.thresholds import (
    DEFAULT_ENGINE,
    THRESHOLDS_RESOURCE,
    Thresholds,
    ThresholdsError,
    available_engines,
    load_thresholds,
)
from autofill_audit.classify.base import TIER_CONFIDENCE, ConfidenceTier

NGRAM_ENGINE = "ngram"


def _document(root: Path) -> dict[str, object]:
    """The committed thresholds document, read from the source tree."""
    path = root / "src" / "autofill_audit" / "audit" / THRESHOLDS_RESOURCE
    loaded: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _block(basis: str = "test", **overrides: object) -> dict[str, object]:
    """A minimal one-engine document, for the validation cases."""
    block: dict[str, object] = {"tau_high": 0.7, "tau_low": 0.4, "basis": basis}
    block.update(overrides)
    return {"schema_version": 2, "engines": {DEFAULT_ENGINE: block}}


# ---------------------------------------------------------------------------
# The committed document.
# ---------------------------------------------------------------------------


def test_the_committed_file_loads_and_says_where_its_numbers_came_from() -> None:
    thresholds = load_thresholds()
    assert thresholds.basis == "rule-tier-band-mapping"
    assert thresholds.source == THRESHOLDS_RESOURCE
    assert thresholds.engine == DEFAULT_ENGINE
    assert 0.0 <= thresholds.tau_low <= thresholds.tau_high <= 1.0


def test_the_rule_block_claims_no_measurement_and_never_will() -> None:
    """Law 4: a number nobody has measured is null rather than plausible.

    The rule tiers are ordered placeholders. There is no measurement that could
    fill these keys in, so they stay null, and the reports keep saying in words
    that the thresholds behind a rule-engine confidence are a mapping.
    """
    thresholds = load_thresholds(DEFAULT_ENGINE)
    assert thresholds.measured is False
    assert thresholds.dev_precision is None
    assert thresholds.target_precision is None
    assert thresholds.corpus_manifest_sha is None
    assert thresholds.describe()["measured"] == "false"


def test_the_band_mapping_is_the_one_the_file_documents(repo_root: Path) -> None:
    """HIGH and MEDIUM are confident, LOW is a note, NONE says nothing."""
    thresholds = load_thresholds(DEFAULT_ENGINE)
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


def test_the_rule_engine_keeps_its_own_block(repo_root: Path) -> None:
    """P4 derived a measured boundary and left the rule tiers exactly alone.

    The rule block's numbers are the ones P3 committed, which is why no golden
    snapshot moved when the n-gram engine arrived. A phase that retuned the rule
    boundary while adding a new engine would have churned every snapshot and
    every reported finding for a reason that had nothing to do with the rules.
    """
    engines = _document(repo_root)["engines"]
    assert isinstance(engines, dict)
    rules = engines[DEFAULT_ENGINE]
    assert isinstance(rules, dict)
    assert rules["tau_high"] == 0.7
    assert rules["tau_low"] == 0.4
    assert rules["basis"] == "rule-tier-band-mapping"


# ---------------------------------------------------------------------------
# Per-engine selection.
# ---------------------------------------------------------------------------


def test_an_engine_with_no_block_is_an_error_and_not_an_inheritance() -> None:
    """Applying one engine's boundary to another's confidences would be silent."""
    with pytest.raises(ThresholdsError, match="no threshold block"):
        load_thresholds("tarot")


def test_available_engines_lists_the_blocks_that_exist() -> None:
    engines = available_engines()
    assert DEFAULT_ENGINE in engines
    assert engines == tuple(sorted(engines))


def test_a_document_with_no_engines_object_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="engines must be an object"):
        Thresholds.from_json({"schema_version": 2, "engines": {}})


# ---------------------------------------------------------------------------
# Validation.
# ---------------------------------------------------------------------------


def test_a_wrong_schema_version_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="schema version"):
        Thresholds.from_json({"schema_version": 99, "engines": {DEFAULT_ENGINE: {}}})


def test_thresholds_out_of_order_are_refused() -> None:
    with pytest.raises(ThresholdsError, match="tau_low <= tau_high"):
        Thresholds.from_json(_block(tau_high=0.2, tau_low=0.8))


def test_a_missing_basis_is_refused() -> None:
    """A threshold that cannot say where it came from is folklore."""
    document = _block()
    del document["engines"][DEFAULT_ENGINE]["basis"]  # type: ignore[index]
    with pytest.raises(ThresholdsError, match="basis"):
        Thresholds.from_json(document)


def test_a_non_numeric_threshold_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="must be a number"):
        Thresholds.from_json(_block(tau_high="high"))


def test_a_non_object_document_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="expected an object"):
        Thresholds.from_json([1, 2, 3])


def test_a_non_object_engine_block_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="expected an object"):
        Thresholds.from_json({"schema_version": 2, "engines": {DEFAULT_ENGINE: "0.7"}})


def test_an_optional_number_of_the_wrong_type_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="dev_precision"):
        Thresholds.from_json(_block(dev_precision="high"))


def test_an_optional_string_of_the_wrong_type_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="corpus_manifest_sha"):
        Thresholds.from_json(_block(corpus_manifest_sha=7))


# ---------------------------------------------------------------------------
# The override and the run log.
# ---------------------------------------------------------------------------


def test_an_override_rewrites_the_basis_as_well_as_the_number() -> None:
    """A report that still claimed the file's basis would be wrong about itself."""
    overridden = load_thresholds().with_low(0.1)
    assert overridden.tau_low == 0.1
    assert "overridden on the command line" in overridden.basis
    assert overridden.tau_high == load_thresholds().tau_high
    assert overridden.engine == load_thresholds().engine


def test_an_override_that_would_empty_the_low_band_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="above the high threshold"):
        load_thresholds().with_low(0.95)


def test_an_override_outside_the_unit_interval_is_refused() -> None:
    with pytest.raises(ThresholdsError, match="between 0 and 1"):
        load_thresholds().with_low(-0.1)


def test_the_loader_is_cached_so_a_run_reads_one_policy() -> None:
    assert load_thresholds() is load_thresholds()


def test_describe_carries_the_numbers_verbatim_for_the_run_log() -> None:
    described = load_thresholds().describe()
    assert described["tau_high"] == repr(load_thresholds().tau_high)
    assert described["source"] == THRESHOLDS_RESOURCE


def test_measured_becomes_true_once_a_dev_precision_exists() -> None:
    """The display branch law 4 requires, asserted on a constructed value."""
    derived = Thresholds(tau_high=0.8, tau_low=0.4, basis="dev-split", dev_precision=0.97)
    assert derived.measured is True
    assert derived.describe()["measured"] == "true"
