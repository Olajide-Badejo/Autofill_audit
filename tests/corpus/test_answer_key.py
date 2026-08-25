"""Answer-key completeness, schema conformance, and the committed schema file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autofill_audit.corpus.answer_key import (
    answer_key_schema,
    build_answer_key,
    committed_schema,
    validate_answer_key,
    validate_document,
)
from autofill_audit.corpus.domcheck import count_controls, parse
from autofill_audit.corpus.families import TEMPLATES, Family
from autofill_audit.corpus.generator import build_form, grid_from, iter_forms, render
from autofill_audit.corpus.tiers import Delivery, Tier
from autofill_audit.taxonomy import ALL_LABELS, Label


def _grid(**overrides: Any) -> Any:
    options: dict[str, Any] = {
        "seed": 20260825,
        "families": [family.value for family in Family],
        "locales": ["en-US", "ja-JP"],
        "tiers": [tier.value for tier in Tier],
        "variants": 1,
        "base_year": 2026,
    }
    options.update(overrides)
    return grid_from(**options)


def test_committed_schema_matches_the_generated_one() -> None:
    """The committed file is a convenience copy, so it must not drift.

    It exists so an external consumer can read the contract without running
    Python. The moment it disagrees with what the code generates it stops being
    a contract and starts being a decoy.
    """
    assert committed_schema() == answer_key_schema()


def test_schema_enumerates_the_live_taxonomy() -> None:
    schema = answer_key_schema()
    labels = schema["properties"]["fields"]["items"]["properties"]["label"]["enum"]
    assert set(labels) == {label.value for label in ALL_LABELS}


@pytest.mark.parametrize("tier", list(Tier))
def test_every_control_appears_in_the_key_exactly_once(tier: Tier) -> None:
    """Spec section 8.1 step 8, checked from the outside.

    ``render`` asserts this internally. This test asserts it independently, by
    counting controls in the rendered markup rather than trusting the structure
    the generator built, so a defect that corrupted both the structure and its
    own assertion would still be caught here.
    """
    form = build_form(TEMPLATES["checkout-01"], "en-US", tier, 0, seed=20260825, base_year=2026)
    html = render(form)
    document = build_answer_key(form)

    static_in_markup = count_controls(parse(html))
    static_in_key = sum(
        1
        for entry in document["fields"]
        if entry["provenance"]["delivery"] == Delivery.STATIC.value
    )
    assert static_in_markup == static_in_key

    selectors = [entry["selector"] for entry in document["fields"]]
    assert len(selectors) == len(set(selectors))


def test_every_generated_key_validates() -> None:
    for form, _ in iter_forms(_grid(locales=["en-US"], families=[Family.PAYMENT.value])):
        assert validate_answer_key(build_answer_key(form)) == []


def test_keys_carry_expected_modifiers_for_shipping_and_billing() -> None:
    """P3 needs these to tell a correct ``shipping postal-code`` from a mismatch."""
    form = build_form(
        TEMPLATES["checkout-01"], "en-US", Tier.CLEAN, 0, seed=20260825, base_year=2026
    )
    document = build_answer_key(form)
    by_section: dict[str, set[str]] = {}
    for entry in document["fields"]:
        section = entry["provenance"]["section"]
        by_section.setdefault(section, set()).update(entry["expected_modifiers"])
    assert by_section["shipping"] == {"shipping"}
    assert by_section["billing"] == {"billing"}
    assert by_section["contact"] == set()


def test_clean_tier_declares_the_modifier_in_the_markup() -> None:
    form = build_form(
        TEMPLATES["checkout-01"], "en-US", Tier.CLEAN, 0, seed=20260825, base_year=2026
    )
    document = build_answer_key(form)
    postal = next(
        entry
        for entry in document["fields"]
        if entry["label"] == Label.POSTAL_CODE.value
        and entry["provenance"]["section"] == "shipping"
    )
    declared = postal["provenance"]["declared_autocomplete"]
    assert declared == f"shipping {Label.POSTAL_CODE.value}"


def test_page_notes_record_the_hostile_features() -> None:
    form = build_form(
        TEMPLATES["checkout-02"], "en-US", Tier.HOSTILE, 0, seed=20260825, base_year=2026
    )
    render(form)
    notes = build_answer_key(form)["page_notes"]
    assert len(notes["canvas_pseudo_fields"]) == 1
    assert len(notes["shadow_hosts"]) == 1
    assert len(notes["injected_selectors"]) == 1


def test_validate_rejects_a_duplicate_selector() -> None:
    form = build_form(TEMPLATES["login-01"], "en-US", Tier.CLEAN, 0, seed=20260825, base_year=2026)
    document = build_answer_key(form)
    document["fields"][1]["selector"] = document["fields"][0]["selector"]
    problems = validate_answer_key(document)
    assert any("duplicate selectors" in problem for problem in problems)


def test_validate_rejects_page_notes_that_disagree() -> None:
    form = build_form(
        TEMPLATES["checkout-02"], "en-US", Tier.HOSTILE, 0, seed=20260825, base_year=2026
    )
    render(form)
    document = build_answer_key(form)
    document["page_notes"]["injected_selectors"] = []
    problems = validate_answer_key(document)
    assert any("injected_selectors" in problem for problem in problems)

    document = build_answer_key(form)
    document["page_notes"]["shadow_hosts"] = ["#nope"]
    problems = validate_answer_key(document)
    assert any("shadow_hosts" in problem for problem in problems)


def test_validate_rejects_an_unknown_label() -> None:
    form = build_form(TEMPLATES["login-01"], "en-US", Tier.CLEAN, 0, seed=20260825, base_year=2026)
    document = build_answer_key(form)
    document["fields"][0]["label"] = "not-a-label"
    assert validate_answer_key(document) != []


def test_validate_rejects_a_missing_property() -> None:
    form = build_form(TEMPLATES["login-01"], "en-US", Tier.CLEAN, 0, seed=20260825, base_year=2026)
    document = build_answer_key(form)
    del document["locale"]
    problems = validate_answer_key(document)
    assert any("missing required property" in problem for problem in problems)


def test_validate_rejects_an_unexpected_property() -> None:
    form = build_form(TEMPLATES["login-01"], "en-US", Tier.CLEAN, 0, seed=20260825, base_year=2026)
    document = build_answer_key(form)
    document["surprise"] = 1
    problems = validate_answer_key(document)
    assert any("unexpected property" in problem for problem in problems)


class TestSchemaWalker:
    """The hand-rolled validator has to be worth trusting, so it is tested."""

    def test_type_mismatch(self) -> None:
        assert validate_document(1, {"type": "string"}) != []

    def test_nullable(self) -> None:
        assert validate_document(None, {"type": ["string", "null"]}) == []
        assert validate_document("x", {"type": ["string", "null"]}) == []
        assert validate_document(1, {"type": ["string", "null"]}) != []

    def test_boolean_is_not_an_integer(self) -> None:
        assert validate_document(True, {"type": "integer"}) != []

    def test_const_and_enum(self) -> None:
        assert validate_document(2, {"const": 1}) != []
        assert validate_document("z", {"enum": ["a", "b"]}) != []

    def test_min_length_and_minimum(self) -> None:
        assert validate_document("", {"type": "string", "minLength": 1}) != []
        assert validate_document(-1, {"type": "integer", "minimum": 0}) != []

    def test_min_items_and_item_schema(self) -> None:
        schema = {"type": "array", "items": {"type": "string"}, "minItems": 1}
        assert validate_document([], schema) != []
        assert validate_document([1], schema) != []
        assert validate_document(["a"], schema) == []

    def test_unsupported_keyword_raises(self) -> None:
        """A keyword the walker cannot enforce must not be silently ignored."""
        with pytest.raises(ValueError, match="unsupported schema keywords"):
            validate_document("x", {"type": "string", "pattern": "^x$"})


def test_sample_corpus_keys_are_valid(repo_root: Path) -> None:
    keys = sorted((repo_root / "tests/fixtures/sample_corpus/answer_keys").glob("*.json"))
    assert keys
    for path in keys:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert validate_answer_key(document) == [], path.name
