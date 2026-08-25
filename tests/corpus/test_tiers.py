"""Tier transforms: what each markup-quality tier actually does (spec 8.4)."""

from __future__ import annotations

import numpy as np
import pytest

from autofill_audit.corpus.families import TEMPLATES, Family
from autofill_audit.corpus.generator import build_form, render
from autofill_audit.corpus.tiers import (
    INJECTED_FIELD_DELAY_MS,
    PARTIAL_CORRECT_DECLARATION_FRACTION,
    PARTIAL_WRONG_DECLARATION_FRACTION,
    Declaration,
    Delivery,
    IdentifierStyle,
    Tier,
    partial_declaration,
    wrong_declaration_value,
)
from autofill_audit.taxonomy import Label

SEED = 20260825
BASE_YEAR = 2026


def _form(template_id: str, tier: Tier, locale: str = "en-US"):  # type: ignore[no-untyped-def]
    form = build_form(TEMPLATES[template_id], locale, tier, 0, seed=SEED, base_year=BASE_YEAR)
    return form, render(form)


class TestCleanTier:
    def test_every_control_has_a_label_element(self) -> None:
        form, html = _form("checkout-01", Tier.CLEAN)
        for control in form.fields:
            assert control.label_text, control.slot_key
            assert control.element_id is not None
        assert "<label for=" in html

    def test_every_autofillable_control_declares_correctly(self) -> None:
        form, _ = _form("checkout-01", Tier.CLEAN)
        for control in form.fields:
            if control.label in {Label.NOT_AUTOFILLABLE, Label.UNKNOWN}:
                assert control.declared is None
            else:
                assert control.declared is not None, control.slot_key

    def test_identifiers_are_semantic(self) -> None:
        form, _ = _form("checkout-01", Tier.CLEAN)
        for control in form.fields:
            assert control.identifier_style is IdentifierStyle.SEMANTIC

    def test_no_hostile_features(self) -> None:
        form, html = _form("checkout-01", Tier.CLEAN)
        assert form.injected_fields == []
        assert form.shadow_fields == []
        assert form.canvas_selectors == []
        assert "af-field" not in html
        assert "<canvas" not in html


class TestPartialTier:
    def test_labels_stay_but_declarations_vary(self) -> None:
        """Spec 8.4: labels present, declarations present on some, absent on
        others, and wrong on a stated fraction."""
        outcomes = {"correct": 0, "wrong": 0, "absent": 0}
        for template_id in TEMPLATES:
            form, _ = _form(template_id, Tier.PARTIAL)
            for control in form.fields:
                assert control.label_text, control.slot_key
                if "wrong_declaration" in control.transforms:
                    outcomes["wrong"] += 1
                elif "declaration_absent" in control.transforms:
                    outcomes["absent"] += 1
                elif control.declared is not None:
                    outcomes["correct"] += 1
        assert outcomes["wrong"] > 0
        assert outcomes["absent"] > 0
        assert outcomes["correct"] > 0

    def test_the_wrong_fraction_is_near_its_constant(self) -> None:
        """Not an assertion about a measured rate: an assertion that the draw
        uses the constant rather than a literal somewhere else."""
        rng = np.random.default_rng(0)
        draws = [partial_declaration(rng) for _ in range(20000)]
        wrong = draws.count(Declaration.WRONG) / len(draws)
        correct = draws.count(Declaration.CORRECT) / len(draws)
        assert abs(wrong - PARTIAL_WRONG_DECLARATION_FRACTION) < 0.02
        assert abs(correct - PARTIAL_CORRECT_DECLARATION_FRACTION) < 0.02

    def test_wrong_values_are_wrong(self) -> None:
        rng = np.random.default_rng(1)
        for _ in range(200):
            value = wrong_declaration_value(rng, Label.GIVEN_NAME)
            assert value != Label.GIVEN_NAME.value

    def test_wrong_value_without_a_confusable_is_off_spec(self) -> None:
        rng = np.random.default_rng(2)
        value = wrong_declaration_value(rng, None)
        assert value not in {label.value for label in Label}


class TestHostileTier:
    def test_no_label_elements_at_all(self) -> None:
        for template_id in TEMPLATES:
            form, html = _form(template_id, Tier.HOSTILE)
            assert "<label" not in html, template_id
            for control in form.fields:
                assert control.label_text is None

    def test_no_declarations_at_all(self) -> None:
        for template_id in TEMPLATES:
            form, html = _form(template_id, Tier.HOSTILE)
            assert "autocomplete=" not in html, template_id
            for control in form.fields:
                assert control.declared is None

    def test_identifiers_are_generic(self) -> None:
        form, _ = _form("checkout-01", Tier.HOSTILE)
        for control in form.fields:
            assert control.identifier_style is not IdentifierStyle.SEMANTIC

    def test_exactly_one_injected_field_per_form(self) -> None:
        for template_id in TEMPLATES:
            form, html = _form(template_id, Tier.HOSTILE)
            assert len(form.injected_fields) == 1, template_id
            assert f"}}, {INJECTED_FIELD_DELAY_MS});" in html
            injected = form.injected_fields[0]
            assert injected.delivery is Delivery.INJECTED
            # The control must not be in the static markup: that is the whole
            # point of it, and a template regression that rendered it anyway
            # would make P2's settle policy untestable.
            assert f'id="{injected.element_id}"' not in html

    def test_exactly_one_shadow_root_per_form(self) -> None:
        for template_id in TEMPLATES:
            form, html = _form(template_id, Tier.HOSTILE)
            assert len(form.shadow_fields) == 1, template_id
            assert "customElements.define('af-field'" in html
            assert html.count("<af-field ") == 1

    def test_exactly_one_undeterminable_control_per_form(self) -> None:
        for template_id in TEMPLATES:
            form, _ = _form(template_id, Tier.HOSTILE)
            unknown = [c for c in form.fields if c.label is Label.UNKNOWN]
            assert len(unknown) == 1, template_id
            control = unknown[0]
            assert control.label_text is None
            assert control.placeholder is None
            assert control.declared is None

    def test_canvas_appears_only_on_hostile_checkout(self) -> None:
        for template_id, template in TEMPLATES.items():
            form, html = _form(template_id, Tier.HOSTILE)
            expected = 1 if template.family is Family.CHECKOUT else 0
            assert len(form.canvas_selectors) == expected, template_id
            assert html.count("<canvas") == expected

    def test_split_expiry_pair_is_ungrouped(self) -> None:
        form, html = _form("payment-01", Tier.HOSTILE)
        assert "<fieldset" not in html
        pair = [
            control
            for control in form.fields
            if control.label in {Label.CC_EXP_SPLIT_MONTH, Label.CC_EXP_SPLIT_YEAR}
        ]
        assert len(pair) == 2
        # Both selects share one container, so their positional selectors differ
        # only in the nth-of-type index.
        assert pair[0].selector != pair[1].selector

    def test_placeholder_only_and_fully_unlabeled_fields_both_exist(self) -> None:
        form, _ = _form("checkout-01", Tier.HOSTILE)
        with_placeholder = [c for c in form.fields if c.placeholder]
        without = [c for c in form.fields if not c.placeholder]
        assert with_placeholder
        assert without

    def test_input_types_are_degraded_but_passwords_survive(self) -> None:
        form, _ = _form("signup-01", Tier.HOSTILE)
        emails = [c for c in form.fields if c.label is Label.EMAIL]
        assert emails and all(c.input_type == "text" for c in emails)
        passwords = [c for c in form.fields if c.label is Label.NEW_PASSWORD]
        assert passwords and all(c.input_type == "password" for c in passwords)


class TestMixedTier:
    @pytest.mark.parametrize("template_id", list(TEMPLATES))
    def test_a_mixed_form_carries_at_least_one_clean_and_one_hostile_section(
        self, template_id: str
    ) -> None:
        form, _ = _form(template_id, Tier.MIXED)
        tiers = {section.tier for section in form.sections}
        assert Tier.CLEAN in tiers
        assert Tier.HOSTILE in tiers

    def test_mixed_forms_still_carry_the_hostile_features(self) -> None:
        form, _ = _form("checkout-01", Tier.MIXED)
        assert len(form.injected_fields) == 1
        assert len(form.shadow_fields) == 1

    def test_clean_sections_of_a_mixed_form_keep_their_labels(self) -> None:
        form, _ = _form("checkout-01", Tier.MIXED)
        for section in form.sections:
            if section.tier is not Tier.CLEAN:
                continue
            for row in section.rows:
                for cell in row.cells:
                    for control in cell.fields:
                        assert control.label_text
