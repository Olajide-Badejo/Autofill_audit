"""Selector construction and the minimal resolver that checks it.

Spec section 9.3 makes selector generation part of the corpus contract: answer
keys reference fields by selector, so a change here invalidates every committed
key. These tests pin the preference order and the two documented separators, and
they are the specification P2's extractor has to reproduce.
"""

from __future__ import annotations

import pytest

from autofill_audit.corpus import domcheck
from autofill_audit.corpus.families import TEMPLATES
from autofill_audit.corpus.generator import build_form, render
from autofill_audit.corpus.selectors import (
    SHADOW_SEPARATOR,
    form_name_selector,
    id_selector,
    join_shadow,
    looks_generated,
    nth_of_type_path,
)
from autofill_audit.corpus.tiers import Tier


class TestLooksGenerated:
    @pytest.mark.parametrize(
        "identifier",
        ["input1", "field_7", "shipping-postcode", "sec-contact", "ce-1", "ctl00_txt3"],
    )
    def test_authored_identifiers_are_kept(self, identifier: str) -> None:
        assert not looks_generated(identifier)

    @pytest.mark.parametrize(
        "identifier",
        ["ctl00_txt3_0a9f4c21", "mat-input-1234", "ember14235", "x-deadbeef"],
    )
    def test_machine_identifiers_are_rejected(self, identifier: str) -> None:
        assert looks_generated(identifier)


def test_selector_builders_render_the_documented_forms() -> None:
    assert id_selector("a-b") == "#a-b"
    assert form_name_selector("f1", "ctl00$txt3") == 'form[name="f1"] [name="ctl00$txt3"]'
    assert nth_of_type_path("#sec", (("div", 2), ("input", 1))) == (
        "#sec > div:nth-of-type(2) > input:nth-of-type(1)"
    )
    assert join_shadow("#ce-1", "input:nth-of-type(1)") == "#ce-1 >>> input:nth-of-type(1)"
    assert SHADOW_SEPARATOR == " >>> "


def test_a_positional_path_needs_a_step() -> None:
    with pytest.raises(ValueError, match="at least one step"):
        nth_of_type_path("#sec", ())


def test_every_selector_strategy_is_exercised_by_the_corpus() -> None:
    """A branch of the preference order that only unit tests reach is a branch
    P2 will meet for the first time in production."""
    strategies: set[str] = set()
    for template_id in TEMPLATES:
        for tier in Tier:
            form = build_form(
                TEMPLATES[template_id], "en-US", tier, 0, seed=20260825, base_year=2026
            )
            render(form)
            strategies.update(control.selector_strategy for control in form.fields)
    assert strategies == {"id", "form_name", "nth_of_type", "shadow"}


@pytest.mark.parametrize("template_id", list(TEMPLATES))
@pytest.mark.parametrize("tier", list(Tier))
def test_every_static_selector_resolves_to_exactly_one_element(
    template_id: str, tier: Tier
) -> None:
    form = build_form(TEMPLATES[template_id], "de-DE", tier, 0, seed=20260825, base_year=2026)
    html = render(form)
    tree = domcheck.parse(html)
    for control in form.fields:
        if control.selector_strategy in {"shadow"} or control.delivery.value == "injected":
            continue
        assert len(domcheck.resolve(tree, control.selector)) == 1, control.selector


def test_selectors_are_unique_within_a_form() -> None:
    for template_id in TEMPLATES:
        for tier in Tier:
            form = build_form(
                TEMPLATES[template_id], "ja-JP", tier, 0, seed=20260825, base_year=2026
            )
            render(form)
            selectors = [control.selector for control in form.fields]
            assert len(selectors) == len(set(selectors)), template_id


def test_hex_identifiers_fall_back_off_the_id_branch() -> None:
    """A control can carry an id and still not be addressable by it."""
    found = False
    for template_id in TEMPLATES:
        form = build_form(
            TEMPLATES[template_id], "en-US", Tier.HOSTILE, 0, seed=20260825, base_year=2026
        )
        render(form)
        for control in form.fields:
            if control.element_id and looks_generated(control.element_id):
                assert control.selector_strategy != "id"
                found = True
    assert found


class TestResolver:
    """The resolver is the thing that proves the selectors, so it is tested too."""

    HTML = (
        "<html><body><form name='f1'>"
        "<div id='a'><p>x</p><input name='one'><input name='two'></div>"
        "<div><span></span><input name='three'></div>"
        "</form></body></html>"
    )

    def test_id_and_attribute_and_nth(self) -> None:
        tree = domcheck.parse(self.HTML)
        assert len(domcheck.resolve(tree, "#a")) == 1
        assert len(domcheck.resolve(tree, '[name="two"]')) == 1
        assert len(domcheck.resolve(tree, "#a > input:nth-of-type(2)")) == 1
        assert domcheck.resolve(tree, "#a > input:nth-of-type(2)")[0].attrs["name"] == "two"

    def test_descendant_combinator(self) -> None:
        tree = domcheck.parse(self.HTML)
        assert len(domcheck.resolve(tree, 'form[name="f1"] [name="three"]')) == 1

    def test_child_combinator_is_not_a_descendant(self) -> None:
        tree = domcheck.parse(self.HTML)
        assert domcheck.resolve(tree, 'form[name="f1"] > input') == []

    def test_unsupported_syntax_raises(self) -> None:
        """A resolver that returned nothing for syntax it did not understand
        would be a checker that passes when it should fail."""
        tree = domcheck.parse(self.HTML)
        with pytest.raises(ValueError, match="unsupported selector step"):
            domcheck.resolve(tree, ".a-class")

    def test_empty_selector_raises(self) -> None:
        tree = domcheck.parse(self.HTML)
        with pytest.raises(ValueError, match="empty selector"):
            domcheck.resolve(tree, "   ")

    def test_control_counting_skips_non_controls(self) -> None:
        html = (
            "<form><input type='hidden' name='h'><input type='submit'>"
            "<input type='button'><input name='real'><select></select>"
            "<textarea></textarea><canvas></canvas></form>"
        )
        assert domcheck.count_controls(domcheck.parse(html)) == 3

    def test_self_closing_tags_are_handled(self) -> None:
        tree = domcheck.parse("<div><input name='a'/><br/></div>")
        assert len(domcheck.resolve(tree, '[name="a"]')) == 1

    def test_text_is_captured(self) -> None:
        tree = domcheck.parse("<div><label>Postcode</label></div>")
        assert domcheck.resolve(tree, "label")[0].text == "Postcode"

    def test_nth_of_type_at_the_root_has_no_parent(self) -> None:
        tree = domcheck.parse("<div></div>")
        assert domcheck.resolve(tree, "html:nth-of-type(1)") == []
