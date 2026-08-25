"""Selector generation, from ancestor chains, with no browser.

Spec section 9.3 makes selector generation part of the corpus contract: every
committed answer key references its fields by selector, so a change here
invalidates them all. That makes it worth testing preference by preference,
against hand-built chains, rather than only through a page where a failure could
be blamed on the markup.

The chains in this module are the shapes the corpus actually emits, transcribed
from the P1 handoff, so a divergence shows up here before it shows up as three
hundred failing answer keys.
"""

from __future__ import annotations

import pytest

from autofill_audit.corpus.selectors import SHADOW_SEPARATOR
from autofill_audit.extract.selector import (
    DOCUMENT_ANCHOR,
    FRAME_SEPARATOR,
    ChainStep,
    frame_token,
    join_frames,
    join_shadow_path,
    selector_for_chain,
)


def _corpus_chain(tag: str = "input", nth: int = 1, **kwargs: object) -> list[ChainStep]:
    """The ancestor chain the generator's document shape produces.

    ``body > main > form[name=f1] > div.block > div.row > div.field > control``,
    which is what every hostile-tier control sits at the bottom of.
    """
    return [
        ChainStep(tag="body", nth=1),
        ChainStep(tag="main", nth=1),
        ChainStep(tag="form", nth=1, form_name="f1"),
        ChainStep(tag="div", nth=int(kwargs.get("block", 1))),
        ChainStep(tag="div", nth=int(kwargs.get("row", 1))),
        ChainStep(tag="div", nth=int(kwargs.get("cell", 1))),
        ChainStep(
            tag=tag,
            nth=nth,
            element_id=kwargs.get("element_id"),  # type: ignore[arg-type]
            id_unique=bool(kwargs.get("id_unique", False)),
        ),
    ]


class TestFirstPreference:
    """``#id`` when the id is usable."""

    def test_a_plain_id_wins(self) -> None:
        """The common case, and the one a human can read."""
        chain = _corpus_chain(element_id="input4", id_unique=True)
        choice = selector_for_chain(chain, name=None)
        assert choice.selector == "#input4"
        assert choice.strategy == "id"

    def test_a_duplicated_id_is_refused(self) -> None:
        """``#email`` would resolve to the first of two and name the wrong one."""
        chain = _corpus_chain(element_id="email", id_unique=False)
        choice = selector_for_chain(chain, name="signup_email", name_unique_in_form=True)
        assert choice.selector == 'form[name="f1"] [name="signup_email"]'

    def test_a_hex_suffixed_id_is_refused(self) -> None:
        """The P1 handoff's headline case.

        ``ctl00_txt3_0a9f4c21`` HAS an id and is still not addressable by it. An
        extractor that only checked for the presence of an id would produce a
        selector that disagrees with every answer key on the hostile tier.
        """
        chain = _corpus_chain(element_id="ctl00_txt3_0a9f4c21", id_unique=True)
        choice = selector_for_chain(chain, name="ctl00$txt3", name_unique_in_form=True)
        assert choice.selector == 'form[name="f1"] [name="ctl00$txt3"]'
        assert choice.strategy == "form_name"

    def test_the_same_id_without_the_hex_suffix_is_kept(self) -> None:
        """The suffix is the discriminator, not the ``ctl00`` prefix."""
        chain = _corpus_chain(element_id="ctl00_txt3", id_unique=True)
        assert selector_for_chain(chain, name="ctl00$txt3").selector == "#ctl00_txt3"

    @pytest.mark.parametrize("identifier", ["input1", "field_7", "shipping-postcode", "ce-1"])
    def test_hand_written_ids_are_kept(self, identifier: str) -> None:
        """From the P1 handoff's kept list. A wider rule would push every
        hostile-tier control onto a positional path and stop exercising this
        branch at all."""
        chain = _corpus_chain(element_id=identifier, id_unique=True)
        assert selector_for_chain(chain).selector == f"#{identifier}"

    @pytest.mark.parametrize("identifier", ["ctl00_txt3_0a9f4c21", "mat-input-1234", "ember14235"])
    def test_generated_looking_ids_are_refused(self, identifier: str) -> None:
        """From the P1 handoff's rejected list."""
        chain = _corpus_chain(element_id=identifier, id_unique=True)
        assert selector_for_chain(chain).strategy != "id"


class TestSecondPreference:
    """``form[name] [name]``, with a descendant combinator."""

    def test_descendant_combinator_not_child(self) -> None:
        """P1's committed deviation from the spec section 9.3 sketch.

        A literal child combinator only matches a control that is an immediate
        child of the form element, and every form the generator emits wraps its
        controls in layout containers, so the child form would resolve to
        nothing. The extractor has to match what the answer keys contain.
        """
        chain = _corpus_chain()
        choice = selector_for_chain(chain, name="ctl00$txt2", name_unique_in_form=True)
        assert choice.selector == 'form[name="f1"] [name="ctl00$txt2"]'
        assert " > " not in choice.selector

    def test_a_dollar_sign_survives_inside_the_quoted_attribute(self) -> None:
        """``#ctl00$txt3`` would be invalid CSS; this is why the strategy is safe."""
        chain = _corpus_chain()
        assert (
            "$" in selector_for_chain(chain, name="ctl00$txt3", name_unique_in_form=True).selector
        )

    def test_a_shared_name_falls_through(self) -> None:
        """Every radio in a group shares one name.

        Without the uniqueness condition, a group of four radios would get one
        selector four times and a report would be unable to name any of them.
        """
        chain = _corpus_chain(element_id=None, cell=2)
        choice = selector_for_chain(chain, name="contact_method", name_unique_in_form=False)
        assert choice.strategy == "nth_of_type"

    def test_a_name_with_no_named_form_falls_through(self) -> None:
        """A form with no name attribute cannot anchor the second preference."""
        chain = [ChainStep(tag="body", nth=1), ChainStep(tag="input", nth=1)]
        choice = selector_for_chain(chain, name="email", name_unique_in_form=True)
        assert choice.strategy == "nth_of_type"


class TestThirdPreference:
    """The positional path, and which ancestor anchors it."""

    def test_anchored_at_the_named_form(self) -> None:
        """The exact shape the P1 handoff transcribes from a hostile checkout."""
        chain = _corpus_chain(tag="select", nth=1, block=3, row=4, cell=1)
        choice = selector_for_chain(chain)
        assert choice.selector == (
            'form[name="f1"] > div:nth-of-type(3) > div:nth-of-type(4) '
            "> div:nth-of-type(1) > select:nth-of-type(1)"
        )

    def test_the_second_of_a_pair_sharing_one_cell(self) -> None:
        """The ungrouped split expiry: two selects, one div, indexed apart."""
        chain = _corpus_chain(tag="select", nth=2, block=3, row=4, cell=1)
        assert selector_for_chain(chain).selector.endswith("select:nth-of-type(2)")

    def test_anchored_at_a_section_with_a_stable_id(self) -> None:
        """The nearer anchor wins, which keeps the path short and readable."""
        chain = [
            ChainStep(tag="body", nth=1),
            ChainStep(tag="form", nth=1, form_name="checkout"),
            ChainStep(tag="section", nth=2, element_id="sec-payment", id_unique=True),
            ChainStep(tag="div", nth=1),
            ChainStep(tag="input", nth=1),
        ]
        choice = selector_for_chain(chain)
        assert choice.selector == "#sec-payment > div:nth-of-type(1) > input:nth-of-type(1)"

    def test_a_section_whose_id_looks_generated_is_not_an_anchor(self) -> None:
        """The same rule that rejects a generated control id rejects its ancestor."""
        chain = [
            ChainStep(tag="body", nth=1),
            ChainStep(tag="form", nth=1, form_name="checkout"),
            ChainStep(tag="section", nth=2, element_id="sec-4f9a2c1b8e", id_unique=True),
            ChainStep(tag="input", nth=1),
        ]
        choice = selector_for_chain(chain)
        assert choice.selector == (
            'form[name="checkout"] > section:nth-of-type(2) > input:nth-of-type(1)'
        )

    def test_anchor_of_last_resort(self) -> None:
        """No id, no name, no form. Every document has an ``html``."""
        chain = [
            ChainStep(tag="body", nth=1),
            ChainStep(tag="div", nth=2),
            ChainStep(tag="input", nth=1),
        ]
        choice = selector_for_chain(chain)
        assert choice.selector == (
            "html > body:nth-of-type(1) > div:nth-of-type(2) > input:nth-of-type(1)"
        )
        assert choice.selector.startswith(DOCUMENT_ANCHOR)


class TestShadowScope:
    """Inside a shadow root the root itself is the anchor."""

    def test_a_control_inside_a_shadow_root(self) -> None:
        """The exact selector every hostile-tier answer key carries."""
        inner = selector_for_chain(
            [ChainStep(tag="input", nth=1)], name="ctl00$txt9", root_anchor=""
        )
        assert inner.selector == "input:nth-of-type(1)"
        assert join_shadow_path(["#ce-1"], inner.selector) == "#ce-1 >>> input:nth-of-type(1)"

    def test_the_form_preference_cannot_reach_out_of_the_root(self) -> None:
        """There is no form inside the shadow root, and CSS cannot cross the
        boundary anyway, so a name that is unique in the outer form is no help."""
        inner = selector_for_chain(
            [ChainStep(tag="input", nth=1)],
            name="ctl00$txt9",
            name_unique_in_form=True,
            root_anchor="",
        )
        assert inner.strategy == "nth_of_type"

    def test_an_id_inside_a_shadow_root_is_usable_within_it(self) -> None:
        """Ids are scoped to their root, and inside the root one is addressable."""
        inner = selector_for_chain(
            [ChainStep(tag="input", nth=1, element_id="pan", id_unique=True)], root_anchor=""
        )
        assert inner.selector == "#pan"

    def test_nested_shadow_roots_chain(self) -> None:
        """Two boundaries, two separators, one selector."""
        assert join_shadow_path(["#outer", "#inner"], "input:nth-of-type(1)") == (
            "#outer >>> #inner >>> input:nth-of-type(1)"
        )

    def test_the_separator_is_the_one_the_corpus_defines(self) -> None:
        """Imported, never respelled, because a second spelling would drift."""
        assert SHADOW_SEPARATOR == " >>> "


class TestFrameScope:
    """Frame boundaries and their documented separator."""

    def test_a_frame_token_wraps_the_frames_own_selector(self) -> None:
        """So a reader can find the frame element as well as the field in it."""
        assert frame_token("#pay-frame") == "frame[#pay-frame]"

    def test_joining_one_frame(self) -> None:
        """The shape spec section 9.3 names."""
        assert join_frames(["frame[#pay]"], "#card") == "frame[#pay] >> #card"

    def test_joining_nested_frames(self) -> None:
        """Each boundary gets its own token, in the order they are crossed."""
        assert join_frames(["frame[#a]", "frame[#b]"], "#card") == (
            "frame[#a] >> frame[#b] >> #card"
        )

    def test_no_frame_leaves_the_selector_alone(self) -> None:
        """The main frame is not a frame boundary and must not read as one."""
        assert join_frames([], "#card") == "#card"

    def test_the_separator_is_stated_once(self) -> None:
        """Same reason as the shadow separator."""
        assert FRAME_SEPARATOR == " >> "


def test_an_empty_chain_is_refused() -> None:
    """A control always has at least itself, so an empty chain is a bug."""
    with pytest.raises(ValueError, match="at least one chain step"):
        selector_for_chain([])
