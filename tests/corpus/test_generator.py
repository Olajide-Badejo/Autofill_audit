"""Generator behaviour that is not a tier transform or a selector rule."""

from __future__ import annotations

from pathlib import Path

import pytest

from autofill_audit.corpus.families import TEMPLATES, Family, ItemKind, SectionItem, Template
from autofill_audit.corpus.generator import (
    GENERATOR_VERSION,
    build_form,
    default_base_year,
    grid_from,
    iter_forms,
    render,
)
from autofill_audit.corpus.manifest import label_coverage, write_corpus
from autofill_audit.corpus.profiles import LOCALE_IDS, load_profile
from autofill_audit.corpus.roles import ROLE_SPECS, Control, SlotRole, spec_for
from autofill_audit.corpus.tiers import Tier
from autofill_audit.corpus.values import TEST_CARD_NUMBERS, ValueProvider
from autofill_audit.taxonomy import ALL_LABELS, Label, declaration_for


def test_grid_from_defaults_to_the_whole_grid() -> None:
    grid = grid_from(seed=1, base_year=2026)
    assert grid.families == tuple(Family)
    assert grid.locales == LOCALE_IDS
    assert grid.tiers == tuple(Tier)
    assert len(grid.template_ids()) == len(TEMPLATES)
    assert len(list(grid.cells())) == len(TEMPLATES) * len(LOCALE_IDS) * len(Tier)


def test_grid_from_rejects_an_unknown_locale() -> None:
    with pytest.raises(ValueError, match="unknown locale"):
        grid_from(seed=1, locales=["xx-XX"])


def test_grid_from_rejects_zero_variants() -> None:
    with pytest.raises(ValueError, match="at least one"):
        grid_from(seed=1, variants=0)


def test_variants_multiply_the_grid() -> None:
    templates = 5
    grid = grid_from(seed=1, families=["login"], locales=["en-US"], tiers=["clean"], variants=3)
    assert len(list(grid.cells())) == templates * 3
    forms = [form for form, _ in iter_forms(grid)]
    assert len({form.form_id for form in forms}) == templates * 3
    # Variants of one cell must actually differ, or the flag is a lie.
    one_cell = [form for form in forms if form.template_id == "login-01"]
    assert len(one_cell) == 3
    assert len({form.form_id for form in one_cell}) == 3


def test_default_base_year_is_the_current_year() -> None:
    import datetime as dt

    assert default_base_year() == dt.date.today().year


def test_expiry_years_start_at_the_base_year() -> None:
    form = build_form(TEMPLATES["payment-01"], "en-US", Tier.CLEAN, 0, seed=1, base_year=2031)
    years = next(
        control.options for control in form.fields if control.label is Label.CC_EXP_SPLIT_YEAR
    )
    assert years[0][0] == "2031"
    assert [value for value, _ in years] == [str(2031 + offset) for offset in range(11)]


def test_month_options_are_twelve_with_no_blank() -> None:
    """Spec section 9.5 detects the pair by counting twelve month-shaped
    options, so a blank first option would break detection corpus wide."""
    form = build_form(TEMPLATES["payment-01"], "de-DE", Tier.CLEAN, 0, seed=1, base_year=2026)
    months = next(
        control.options for control in form.fields if control.label is Label.CC_EXP_SPLIT_MONTH
    )
    assert len(months) == 12
    assert months[0] == ("01", "Januar")


def test_country_selects_carry_a_blank_first_option() -> None:
    form = build_form(TEMPLATES["address-01"], "en-US", Tier.CLEAN, 0, seed=1, base_year=2026)
    countries = next(control.options for control in form.fields if control.label is Label.COUNTRY)
    assert countries[0] == ("", "")


def test_composite_roles_declare_the_token_the_composite_stands_for() -> None:
    """``COMPOSITE_UNSPLIT`` is one label covering two different correct
    declarations, which is why the role and not the label decides it."""
    assert spec_for(SlotRole.CARD_EXPIRY_COMPOSITE).declaration is Label.CC_EXP
    assert spec_for(SlotRole.FULL_ADDRESS_COMPOSITE).declaration is Label.STREET_ADDRESS
    assert declaration_for(Label.COMPOSITE_UNSPLIT) is None


def test_split_expiry_roles_declare_the_specification_tokens() -> None:
    assert spec_for(SlotRole.CARD_EXPIRY_SPLIT_MONTH).declaration is Label.CC_EXP_MONTH
    assert spec_for(SlotRole.CARD_EXPIRY_SPLIT_YEAR).declaration is Label.CC_EXP_YEAR


def test_non_autofillable_roles_declare_nothing() -> None:
    for role in (SlotRole.SEARCH, SlotRole.CONSENT, SlotRole.UNDETERMINABLE):
        assert spec_for(role).declaration is None


def test_every_role_has_a_specification() -> None:
    assert set(ROLE_SPECS) == set(SlotRole)


def test_every_label_is_reachable_from_some_role() -> None:
    """Law 2 clause (b), stated at the level where it is designed rather than
    where it is measured."""
    assert {spec.label for spec in ROLE_SPECS.values()} == ALL_LABELS


def test_select_roles_have_an_option_kind() -> None:
    for spec in ROLE_SPECS.values():
        if spec.control is Control.SELECT:
            assert spec.option_kind.value != "none", spec.role


def test_the_full_grid_covers_every_label() -> None:
    grid = grid_from(seed=20260825, locales=["en-US"], base_year=2026)
    from autofill_audit.corpus.answer_key import build_answer_key

    documents = [build_answer_key(form) for form, _ in iter_forms(grid)]
    coverage = label_coverage(documents)
    assert [name for name, count in coverage.items() if count == 0] == []


def test_write_corpus_records_the_realised_grid(tmp_path: Path) -> None:
    grid = grid_from(seed=20260825, families=["login"], locales=["en-US", "de-DE"], base_year=2026)
    result = write_corpus(grid, tmp_path)
    manifest = result.manifest
    assert manifest["generator_version"] == GENERATOR_VERSION
    assert manifest["seed"] == 20260825
    assert manifest["base_year"] == 2026
    assert manifest["form_count"] == result.form_count == 5 * 2 * len(Tier)
    assert manifest["cells"]
    assert sum(cell["forms"] for cell in manifest["cells"]) == manifest["form_count"]
    assert manifest["split_sha256"]
    for entry in manifest["forms"].values():
        assert len(entry["html_sha256"]) == 64
        assert len(entry["answer_key_sha256"]) == 64


def test_manifest_carries_no_timestamp(tmp_path: Path) -> None:
    """A timestamp would fail the determinism gate on every run."""
    grid = grid_from(seed=1, families=["login"], locales=["en-US"], tiers=["clean"])
    result = write_corpus(grid, tmp_path)
    serialised = repr(result.manifest).casefold()
    for word in ("timestamp", "generated_at", "created"):
        assert word not in serialised


def test_missing_labels_is_empty_for_a_full_run(tmp_path: Path) -> None:
    grid = grid_from(seed=20260825, locales=["en-US"], base_year=2026)
    result = write_corpus(grid, tmp_path)
    assert result.missing_labels() == []


def test_a_template_needs_two_sections() -> None:
    with pytest.raises(ValueError, match="at least two sections"):
        Template("bad-01", Family.LOGIN, ())


def test_a_field_item_needs_a_role() -> None:
    with pytest.raises(ValueError, match="must name a role"):
        SectionItem(kind=ItemKind.FIELD)


def test_a_block_item_needs_a_style() -> None:
    with pytest.raises(ValueError, match="must name a style"):
        SectionItem(kind=ItemKind.NAME_BLOCK)


class TestValues:
    def test_pattern_expansion(self) -> None:
        provider = ValueProvider(load_profile("en-GB"), 5)
        value = provider.pattern("@@# #@@")
        assert len(value) == 7
        assert value[2].isdigit()
        assert value[0].isalpha() and value[0].isupper()
        assert value[3] == " "

    def test_card_numbers_come_from_the_published_test_set(self) -> None:
        provider = ValueProvider(load_profile("en-US"), 5)
        for _ in range(20):
            assert provider.card_number() in TEST_CARD_NUMBERS

    def test_every_value_kind_resolves(self) -> None:
        from autofill_audit.corpus.roles import ValueKind

        provider = ValueProvider(load_profile("ja-JP"), 5)
        for kind in ValueKind:
            provider.value_for(kind)

    def test_values_are_seeded(self) -> None:
        from autofill_audit.corpus.roles import ValueKind

        first = ValueProvider(load_profile("fr-FR"), 11)
        second = ValueProvider(load_profile("fr-FR"), 11)
        assert first.value_for(ValueKind.FULL_NAME) == second.value_for(ValueKind.FULL_NAME)

    def test_summary_is_a_whole_invented_person(self) -> None:
        provider = ValueProvider(load_profile("en-US"), 5)
        summary = provider.summary()
        assert set(summary) == {"name", "street", "city", "postal_code", "phone", "country"}


def test_only_checkout_and_address_pages_show_a_summary() -> None:
    for template_id, template in TEMPLATES.items():
        form = build_form(TEMPLATES[template_id], "en-US", Tier.CLEAN, 0, seed=1, base_year=2026)
        expected = template.family in {Family.CHECKOUT, Family.ADDRESS}
        assert (form.summary is not None) == expected


def test_rendered_pages_declare_their_locale() -> None:
    for locale in LOCALE_IDS:
        form = build_form(TEMPLATES["address-01"], locale, Tier.CLEAN, 0, seed=1, base_year=2026)
        html = render(form)
        assert f'<html lang="{load_profile(locale).html_lang}">' in html


def test_no_answer_appears_in_the_markup_as_a_data_attribute() -> None:
    """Spec section 5.6: physical separation, so a data-* sweep cannot leak."""
    for tier in Tier:
        form = build_form(TEMPLATES["checkout-01"], "en-US", tier, 0, seed=1, base_year=2026)
        html = render(form)
        assert "data-truth" not in html
        assert "data-label" not in html
