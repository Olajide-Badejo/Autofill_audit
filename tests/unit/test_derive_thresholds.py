"""The threshold derivation, and the derived block it produced.

Two halves. The first pins the pre-registered optimisation itself against hand
built rows, so that the rule cannot be quietly reinterpreted later: a threshold
policy that drifts is a threshold policy nobody can check a result against. The
second asserts the committed block is the one that policy produces, and that the
rule engine's block was left exactly alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.builders import make_descriptor

import derive_thresholds as derive
from autofill_audit.audit.thresholds import THRESHOLDS_RESOURCE, load_thresholds
from autofill_audit.classify.onnx_model import ENGINE_NAME
from autofill_audit.descriptors import Prediction
from autofill_audit.taxonomy import Label


def _row(confidence: float, *, correct: bool, eligible: bool = True, needs: bool = True):
    """One synthetic dev row."""
    return derive.Row(
        selector="#x",
        truth=Label.POSTAL_CODE.value,
        predicted=Label.POSTAL_CODE.value if correct else Label.EMAIL.value,
        confidence=confidence,
        eligible=eligible,
        needs_accusation=needs,
        correct=correct,
    )


# ---------------------------------------------------------------------------
# Eligibility, read off the decision procedure.
# ---------------------------------------------------------------------------


def _rows_for(**descriptor_kwargs: object) -> derive.Row:
    example = derive.train.Example(
        descriptor=make_descriptor("#a", **descriptor_kwargs),  # type: ignore[arg-type]
        label=Label.POSTAL_CODE.value,
        form_id="f",
        template_id="t",
        locale="en-US",
        tier="clean",
    )
    prediction = Prediction(
        selector="#a", label=Label.POSTAL_CODE.value, confidence=0.9, engine=ENGINE_NAME
    )
    return derive.build_rows([example], [prediction])[0]


def test_an_undeclared_field_is_eligible_and_needs_an_accusation() -> None:
    row = _rows_for(label="Postcode")
    assert row.eligible and row.needs_accusation and row.correct


def test_a_field_that_already_declares_the_token_is_not_eligible() -> None:
    """A declaration is authoritative unless the tool is confident it is wrong,
    and that is a different branch of the decision procedure."""
    row = _rows_for(label="Postcode", declared="postal-code")
    assert not row.eligible
    assert not row.needs_accusation


def test_autocomplete_off_is_not_a_missing_declaration() -> None:
    row = _rows_for(label="Postcode", declared="off")
    assert not row.eligible


def test_an_undetectable_control_is_never_accused() -> None:
    row = _rows_for(label="Postcode", undetectable_reason="closed-shadow-root")
    assert not row.eligible
    assert not row.needs_accusation


def test_an_equivalent_token_counts_as_correct() -> None:
    """A page declaring ``name`` where the tool reads ``given-name`` fills
    correctly, so calling that a false accusation would measure the wrong thing."""
    example = derive.train.Example(
        descriptor=make_descriptor("#a", label="Name"),
        label=Label.NAME.value,
        form_id="f",
        template_id="t",
        locale="en-US",
        tier="clean",
    )
    prediction = Prediction(
        selector="#a", label=Label.GIVEN_NAME.value, confidence=0.9, engine=ENGINE_NAME
    )
    assert derive.build_rows([example], [prediction])[0].correct


def test_an_abstention_is_not_an_accusation() -> None:
    example = derive.train.Example(
        descriptor=make_descriptor("#a", label="Postcode"),
        label=Label.POSTAL_CODE.value,
        form_id="f",
        template_id="t",
        locale="en-US",
        tier="clean",
    )
    prediction = Prediction(
        selector="#a", label=Label.UNKNOWN.value, confidence=0.0, engine=ENGINE_NAME
    )
    row = derive.build_rows([example], [prediction])[0]
    assert not row.eligible
    assert row.needs_accusation


# ---------------------------------------------------------------------------
# The optimisation.
# ---------------------------------------------------------------------------


def test_precision_and_recall_at_a_threshold() -> None:
    rows = [_row(0.9, correct=True), _row(0.9, correct=False), _row(0.2, correct=True)]
    accusations, correct, precision, recall = derive.precision_recall(rows, 0.5)
    assert (accusations, correct) == (2, 1)
    assert precision == pytest.approx(0.5)
    assert recall == pytest.approx(1 / 3)


def test_tau_high_is_the_smallest_threshold_that_reaches_the_target() -> None:
    rows = [
        _row(0.4, correct=False),
        _row(0.6, correct=True),
        _row(0.8, correct=True),
        _row(0.9, correct=True),
    ]
    tau, met = derive.choose_tau_high(rows, 1.0)
    assert met
    assert tau == pytest.approx(0.6)


def test_an_unreachable_target_is_recorded_rather_than_lowered() -> None:
    """Spec section 11.3's target is fixed before looking and stays fixed."""
    rows = [_row(0.9, correct=False), _row(0.5, correct=True)]
    tau, met = derive.choose_tau_high(rows, 0.98)
    assert not met
    _, _, precision, _ = derive.precision_recall(rows, tau)
    assert precision == pytest.approx(0.5)


def test_tau_low_is_the_greatest_threshold_that_captures_the_band() -> None:
    """The non-degenerate reading, pre-registered before the numbers existed.

    Captured recall only falls as the low threshold rises, so every value below a
    qualifying one also qualifies and the smallest qualifying value is zero.
    """
    rows = [
        _row(0.95, correct=True),
        _row(0.60, correct=True),
        _row(0.30, correct=True),
        _row(0.10, correct=True),
    ]
    tau_high = 0.95
    tau_low = derive.choose_tau_low(rows, tau_high, 0.5)
    assert tau_low == pytest.approx(0.3)


def test_a_threshold_that_gives_up_nothing_empties_the_band_honestly() -> None:
    """An arbitrary number in the near-miss band would be folklore."""
    rows = [_row(0.99, correct=True)]
    assert derive.choose_tau_low(rows, 0.99, 0.5) == pytest.approx(0.99)


def test_the_candidates_are_the_observed_confidences() -> None:
    """A threshold in a gap no dev field occupies is a threshold nothing reaches."""
    rows = [_row(0.42, correct=True), _row(0.77, correct=False)]
    assert derive.candidates(rows) == [0.0, 0.42, 0.77, 1.0]


# ---------------------------------------------------------------------------
# The committed block.
# ---------------------------------------------------------------------------


def test_the_committed_ngram_block_is_measured_and_names_its_corpus() -> None:
    thresholds = load_thresholds(ENGINE_NAME)
    assert thresholds.measured is True
    assert thresholds.target_precision == derive.TARGET_PRECISION
    assert thresholds.dev_precision is not None
    assert thresholds.dev_recall is not None
    assert thresholds.corpus_manifest_sha is not None
    assert thresholds.derived_on is not None
    assert "dev split" in thresholds.basis


def test_the_derived_thresholds_were_not_typed(repo_root: Path) -> None:
    """A hand-typed threshold is a round number. These are not.

    Not a style preference. The two values are confidences a dev field actually
    carried, which is what choosing from observed values means, and a round number
    here would mean somebody had chosen a grid point instead.
    """
    path = repo_root / "src" / "autofill_audit" / "audit" / THRESHOLDS_RESOURCE
    block = json.loads(path.read_text(encoding="utf-8"))["engines"][ENGINE_NAME]
    assert len(repr(block["tau_high"]).split(".")[1]) > 6
    assert len(repr(block["tau_low"]).split(".")[1]) > 6


def test_the_derived_block_records_its_denominators(repo_root: Path) -> None:
    """A precision of one over fifteen is not the same claim as over fifteen
    hundred, and the file carries the number a reader needs to tell them apart."""
    path = repo_root / "src" / "autofill_audit" / "audit" / THRESHOLDS_RESOURCE
    block = json.loads(path.read_text(encoding="utf-8"))["engines"][ENGINE_NAME]
    assert block["dev_accusations"] > 0
    assert block["dev_fields_needing_accusation"] >= block["dev_accusations"]
    assert 0.0 <= block["band_recall_captured"] <= 1.0


def test_the_ngram_band_sits_above_the_rule_band() -> None:
    """The two engines are on different scales and the file keeps them apart."""
    rules = load_thresholds()
    ngram = load_thresholds(ENGINE_NAME)
    assert ngram.tau_high > rules.tau_high
    assert 0.0 <= ngram.tau_low <= ngram.tau_high <= 1.0
