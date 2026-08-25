"""Result assembly from root records: the whole extractor minus the browser.

``descriptors_from_roots`` is the seam spec section 5.1's stage contract makes
possible. Everything after the traversal script is pure Python over plain
records, so the page-level behaviours that matter most, the ones that decide
what a report says about a blind spot, are tested here in milliseconds rather
than only through a browser.
"""

from __future__ import annotations

from typing import Any

from autofill_audit.descriptors import ExtractionWarningCode, UndetectableReason
from autofill_audit.extract.walker import ExtractOptions, RootRecords, descriptors_from_roots

FROZEN_YEAR = 2026


def _step(tag: str, nth: int = 1, **extra: Any) -> dict[str, Any]:
    """One ancestor chain step in the shape the traversal script emits."""
    return {"tag": tag, "nth": nth, "id": None, "idUnique": False, "formName": None, **extra}


def _control(
    *,
    element_id: str | None = None,
    tag: str = "input",
    chain: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """One control record.

    An id lands on the record *and* on the last step of the ancestor chain,
    because that is what the traversal script emits: the chain is the tree, and
    the control is the bottom of it.
    """
    if chain is None:
        chain = [_step("body"), _step(tag, id=element_id, idUnique=element_id is not None)]
    return {
        "kind": "control",
        "tag": tag,
        "inputType": extra.pop("inputType", "text"),
        "elementId": element_id,
        "chain": chain,
        **extra,
    }


def _root(*nodes: dict[str, Any], frame_path: tuple[str, ...] = (), **extra: Any) -> RootRecords:
    """One root's worth of records."""
    return RootRecords(
        frame_path=frame_path,
        nodes=tuple(nodes),
        seen=extra.get("seen", len([n for n in nodes if n.get("kind") == "control"])),
        truncated=bool(extra.get("truncated", False)),
    )


OPTIONS = ExtractOptions(now_year=FROZEN_YEAR)


class TestDocumentOrder:
    """Spec section 9.1 step 7, and what ``document_index`` counts."""

    def test_indices_follow_the_emitted_sequence(self) -> None:
        """Simple, and the thing every report ordering rests on."""
        result = descriptors_from_roots(
            [_root(_control(element_id="a"), _control(element_id="b"))],
            options=OPTIONS,
        )
        assert [item.document_index for item in result.fields] == [0, 1]

    def test_a_honeypot_still_consumes_an_index(self) -> None:
        """So excluding one does not renumber the controls around it.

        A developer comparing a report against their own markup counts controls
        in the order they wrote them, and a gap is easier to explain than a
        silent renumbering.
        """
        result = descriptors_from_roots(
            [
                _root(
                    _control(element_id="a"),
                    _control(element_id="trap", zeroSize=True),
                    _control(element_id="b"),
                )
            ],
            options=OPTIONS,
        )
        assert [item.document_index for item in result.fields] == [0, 2]
        assert [item.document_index for item in result.honeypots] == [1]

    def test_frames_follow_the_main_root(self) -> None:
        """Spec section 9.1 walks each root in turn, not interleaved."""
        result = descriptors_from_roots(
            [
                _root(_control(element_id="outer")),
                _root(_control(element_id="inner"), frame_path=("frame[#pay]",)),
            ],
            options=OPTIONS,
        )
        assert [item.selector for item in result.fields] == ["#outer", "frame[#pay] >> #inner"]
        assert result.frame_count == 2


class TestUndetectables:
    """The three blind spots spec section 9.6 requires be named."""

    def test_a_closed_shadow_root(self) -> None:
        """The walk continues past it, and the gap is on the record."""
        result = descriptors_from_roots(
            [
                _root(
                    _control(element_id="a"),
                    {
                        "kind": "closedShadow",
                        "tag": "vault-field",
                        "chain": [_step("body"), _step("vault-field", id="ce-2", idUnique=True)],
                    },
                    _control(element_id="b"),
                )
            ],
            options=OPTIONS,
        )
        assert [item.undetectable_reason for item in result.fields] == [
            None,
            UndetectableReason.CLOSED_SHADOW_ROOT.value,
            None,
        ]
        assert result.fields[1].selector == "#ce-2"

    def test_an_unreadable_frame(self) -> None:
        """One synthetic descriptor and a page-level warning naming it."""
        result = descriptors_from_roots(
            [
                _root(
                    {
                        "kind": "frame",
                        "tag": "iframe",
                        "accessible": False,
                        "chain": [_step("body"), _step("iframe", id="pay", idUnique=True)],
                    }
                )
            ],
            options=OPTIONS,
        )
        assert result.fields[0].undetectable_reason == UndetectableReason.CROSS_ORIGIN_FRAME.value
        assert result.fields[0].selector == "frame[#pay]"
        warning = result.warning(ExtractionWarningCode.FRAME_UNREADABLE)
        assert warning is not None
        assert "frame[#pay]" in warning.detail

    def test_a_readable_frame_produces_no_synthetic_descriptor(self) -> None:
        """It was read, so there is no blind spot to name."""
        result = descriptors_from_roots(
            [
                _root(
                    {
                        "kind": "frame",
                        "tag": "iframe",
                        "accessible": True,
                        "chain": [_step("body"), _step("iframe", id="pay", idUnique=True)],
                    }
                )
            ],
            options=OPTIONS,
        )
        assert result.fields == ()
        assert result.warning(ExtractionWarningCode.FRAME_UNREADABLE) is None

    def test_undetectable_is_a_view_over_the_fields(self) -> None:
        """P3 reads this rather than filtering the list itself."""
        result = descriptors_from_roots(
            [
                _root(
                    _control(element_id="a"),
                    {"kind": "closedShadow", "tag": "x-y", "chain": [_step("x-y")]},
                )
            ],
            options=OPTIONS,
        )
        assert len(result.undetectable) == 1


class TestCanvasRule:
    """Spec section 9.6's canvas case, and the decision P1 left to P2."""

    def test_a_canvas_beside_real_controls_is_recorded_and_nothing_more(self) -> None:
        """This is what the corpus contains: plenty of controls AND a canvas.

        Emitting a synthetic descriptor here would make every hostile checkout
        report one more field than its answer key holds, and the reconciliation
        the P2 gate asks for would never balance. The canvas is recorded, which
        is the form the answer keys record it in, and P3 decides what to say.
        """
        result = descriptors_from_roots(
            [
                _root(
                    _control(element_id="a"),
                    {
                        "kind": "canvas",
                        "width": 320,
                        "height": 120,
                        "chain": [_step("canvas", id="canvas-order", idUnique=True)],
                    },
                )
            ],
            options=OPTIONS,
        )
        assert len(result.fields) == 1
        assert result.fields[0].undetectable_reason is None
        assert [region.selector for region in result.canvas_regions] == ["#canvas-order"]

    def test_a_canvas_with_no_controls_yields_one_page_level_descriptor(self) -> None:
        """Spec section 9.6's actual trigger: zero controls, one large canvas."""
        result = descriptors_from_roots(
            [
                _root(
                    {
                        "kind": "canvas",
                        "width": 360,
                        "height": 140,
                        "chain": [_step("canvas", id="canvas-card", idUnique=True)],
                    }
                )
            ],
            options=OPTIONS,
        )
        assert len(result.fields) == 1
        assert result.fields[0].undetectable_reason == UndetectableReason.CANVAS_REGION.value

    def test_the_largest_canvas_is_the_one_named(self) -> None:
        """A page with a form canvas and a chart canvas has one story to tell."""
        result = descriptors_from_roots(
            [
                _root(
                    {
                        "kind": "canvas",
                        "width": 120,
                        "height": 100,
                        "chain": [_step("canvas", 1, id="small", idUnique=True)],
                    },
                    {
                        "kind": "canvas",
                        "width": 360,
                        "height": 140,
                        "chain": [_step("canvas", 2, id="big", idUnique=True)],
                    },
                )
            ],
            options=OPTIONS,
        )
        assert result.fields[0].selector == "#big"

    def test_a_page_with_neither_yields_nothing(self) -> None:
        """An empty page is an empty result, not an error and not a finding."""
        result = descriptors_from_roots([_root()], options=OPTIONS)
        assert result.fields == ()
        assert result.canvas_regions == ()


class TestTruncation:
    """The bound of spec section 9.6 on a very large page."""

    def test_truncation_is_reported(self) -> None:
        """Reaching the limit is reported, never silent."""
        result = descriptors_from_roots(
            [_root(_control(element_id="a"), truncated=True, seen=900)],
            options=ExtractOptions(now_year=FROZEN_YEAR, max_controls=1),
        )
        assert result.truncated is True
        warning = result.warning(ExtractionWarningCode.TRUNCATED)
        assert warning is not None
        assert "1 controls" in warning.detail

    def test_controls_seen_counts_past_the_limit(self) -> None:
        """So a report can say how much of the page it did not look at."""
        result = descriptors_from_roots(
            [_root(_control(element_id="a"), truncated=True, seen=900)],
            options=OPTIONS,
        )
        assert result.controls_seen == 900

    def test_an_untruncated_page_carries_no_warning(self) -> None:
        """The common case says nothing, which is what makes the warning mean
        something when it appears."""
        result = descriptors_from_roots([_root(_control(element_id="a"))], options=OPTIONS)
        assert result.warnings == ()


class TestGroupsRunOverTheWholeResult:
    """Group detection is part of assembly, not part of the browser side."""

    def test_an_expiry_pair_from_records(self) -> None:
        """The same detector the fixtures exercise, reached with no page."""
        months = [f"{month:02d}" for month in range(1, 13)]
        years = [str(year) for year in range(FROZEN_YEAR, FROZEN_YEAR + 5)]
        result = descriptors_from_roots(
            [
                _root(
                    _control(
                        tag="select",
                        inputType=None,
                        element_id="m",
                        optionValues=months,
                        parentKey="cell1",
                    ),
                    _control(
                        tag="select",
                        inputType=None,
                        element_id="y",
                        optionValues=years,
                        parentKey="cell1",
                    ),
                )
            ],
            options=OPTIONS,
        )
        assert result.fields[0].group_id == result.fields[1].group_id
        assert result.fields[0].group_id is not None


def test_the_url_is_carried_onto_the_result() -> None:
    """A report has to be able to say what it audited."""
    result = descriptors_from_roots([_root()], options=OPTIONS, url="file:///tmp/page.html")
    assert result.url == "file:///tmp/page.html"


def test_options_default_to_the_clock() -> None:
    """No year passed means the current one, read once rather than per control."""
    assert ExtractOptions().resolved_year() >= 2026
    assert ExtractOptions(now_year=1999).resolved_year() == 1999
