"""DOM traversal including same-origin frames and open shadow roots.

The public entry point takes a ``Page`` and returns ``list[FieldDescriptor]``
(spec sections 5.1 and 5.5). ``extract_result`` returns the same descriptors
together with the page-level surface spec section 9.6 requires, and ``extract``
is a thin wrapper over it, so there is one implementation and two shapes of
answer.

Closed shadow roots and cross-origin frames are reported as undetectable rather
than guessed at (spec section 9.6). Reporting the blind spot is the correct
behaviour; pretending the field is absent is not.

Where the work happens
----------------------

``traverse.js`` reads the DOM and returns plain JSON. Everything after that is
Python, and ``descriptors_from_roots`` is the seam: it takes the same records
the browser would have produced and does the rest with no browser at all. Every
selector, every group, every honeypot decision, and every normalised token is
therefore covered by tests that run in milliseconds, and the browser-marked
tests are left to prove the one thing only a browser can, which is that the page
really does say what the records claim.

Frame order
-----------

Spec section 9.1 walks the main frame first and then each same-origin frame as a
root of its own, so that one unreadable frame costs exactly that frame instead
of aborting a partially built walk. Frames are visited depth first in the order
their elements appear, which is what makes ``frame_path`` read as a path rather
than as an index into a flat list.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from typing import Any, Final

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame, JSHandle, Page

from autofill_audit.descriptors import (
    CanvasRegion,
    ExtractionResult,
    ExtractionWarning,
    ExtractionWarningCode,
    FieldDescriptor,
    SettleReport,
    UndetectableReason,
)
from autofill_audit.extract.groups import detect_groups
from autofill_audit.extract.selector import (
    DOCUMENT_ANCHOR,
    ChainStep,
    frame_token,
    join_frames,
    join_shadow_path,
    selector_for_chain,
)
from autofill_audit.extract.signals import (
    MAX_OPTIONS,
    RawControl,
    is_honeypot,
    normalized_signals_for,
    parse_autocomplete,
    raw_control_from_json,
    text_signals_of,
)

__all__ = [
    "CANVAS_MIN_AREA",
    "FRAMEWORK_ATTRIBUTES",
    "MAX_CONTROLS",
    "MAX_FRAME_DEPTH",
    "ExtractOptions",
    "RootRecords",
    "descriptors_from_roots",
    "extract",
    "extract_result",
    "traversal_script",
]

MAX_CONTROLS: Final[int] = 500
"""The bound of spec section 9.6 on a very large page.

Generous on purpose. The largest form in this project's corpus has fewer than
thirty controls, the largest checkout page anybody has reported in the wild is
well under two hundred, and a page above five hundred is either a data grid or
an attempt to exhaust the tool. Reaching it is reported, never silent."""

CANVAS_MIN_AREA: Final[float] = 10_000.0
"""How large a canvas has to be before it might be hiding a form control.

A hundred pixels square. Smaller canvases on real pages are sparklines, icons,
and chart legends, and reporting those as possible form controls would train a
reader to ignore the finding."""

MAX_FRAME_DEPTH: Final[int] = 8
"""How deep frame nesting may go before the walk stops descending.

An advertising stack three frames deep is ordinary; eight is pathological, and
a page that nests further is not one this tool can usefully audit anyway."""

FRAMEWORK_ATTRIBUTES: Final[tuple[str, ...]] = (
    "formcontrolname",
    "ng-reflect-name",
    "ng-model",
    "v-model",
    "x-model",
    "wire:model",
)
"""Attributes that carry a field identifier for a component framework.

Their **values** are collected, unlike ``data-*`` keys, because
``formcontrolname="postalCode"`` is an identifier in exactly the way
``name="postalCode"`` is. The rule that data attribute values never leave the
page exists to make answer-key leakage impossible (spec section 9.2); these are
not data attributes and no generator emits them."""

_SCRIPT_RESOURCE: Final[str] = "traverse.js"


def traversal_script() -> str:
    """Return the in-page traversal script.

    Read from a file rather than held as a string constant so that it is
    editable as JavaScript, with JavaScript syntax highlighting and a linter
    that understands it, instead of as a very long Python literal.
    """
    return resources.files("autofill_audit.extract").joinpath(_SCRIPT_RESOURCE).read_text("utf-8")


@dataclass(frozen=True, slots=True)
class ExtractOptions:
    """The knobs that change what a walk collects.

    ``now_year`` is separated out because spec section 9.5 requires the expiry
    year window to be relative to the current year and testable with a frozen
    clock. Leaving it None reads the clock once, here, rather than once per
    control somewhere deep in a detector.
    """

    max_controls: int = MAX_CONTROLS
    max_options: int = MAX_OPTIONS
    canvas_min_area: float = CANVAS_MIN_AREA
    max_frame_depth: int = MAX_FRAME_DEPTH
    now_year: int | None = None

    def resolved_year(self) -> int:
        """The year the expiry window is measured against."""
        return self.now_year if self.now_year is not None else datetime.now(UTC).year


@dataclass(frozen=True, slots=True)
class RootRecords:
    """One root's worth of traversal output, already decoded from JSON.

    A root is the main document, or a same-origin frame's document. Shadow roots
    are **not** roots: they are walked in place inside their own document, which
    is what keeps a control inside a custom element positioned between the
    fields around it (spec section 9.1).
    """

    frame_path: tuple[str, ...] = ()
    nodes: tuple[Mapping[str, Any], ...] = ()
    seen: int = 0
    truncated: bool = False


# ---------------------------------------------------------------------------
# Assembly: records to descriptors. No browser beyond this point.
# ---------------------------------------------------------------------------


def _host_selectors(host_chains: Sequence[Sequence[ChainStep]]) -> list[str]:
    """Build the selector of each shadow host on the way in."""
    return [selector_for_chain(chain).selector for chain in host_chains if chain]


def _selector_for(raw: RawControl, frame_path: Sequence[str]) -> str:
    """Build the full selector for one control, boundaries included."""
    inner_anchor = DOCUMENT_ANCHOR if not raw.shadow_host_chains else ""
    choice = selector_for_chain(
        raw.chain,
        name=raw.name,
        name_unique_in_form=raw.name_unique_in_form,
        root_anchor=inner_anchor,
    )
    hosts = _host_selectors(raw.shadow_host_chains)
    return join_frames(frame_path, join_shadow_path(hosts, choice.selector))


def _descriptor_for(
    raw: RawControl, *, frame_path: Sequence[str], document_index: int
) -> FieldDescriptor:
    """Turn one raw record into a finished descriptor, minus its group."""
    declared = parse_autocomplete(raw.autocomplete_raw)
    text = text_signals_of(raw)
    return FieldDescriptor(
        selector=_selector_for(raw, frame_path),
        frame_path=tuple(frame_path),
        shadow_path=tuple(_host_selectors(raw.shadow_host_chains)),
        document_index=document_index,
        tag=raw.tag,
        input_type=raw.input_type,
        inputmode=raw.inputmode,
        pattern=raw.pattern,
        maxlength=raw.maxlength,
        required=raw.required,
        readonly=raw.readonly,
        disabled=raw.disabled,
        option_labels=raw.option_labels,
        option_values=raw.option_values,
        name=raw.name,
        element_id=raw.element_id,
        css_classes=raw.css_classes,
        data_keys=raw.data_keys,
        framework_attrs=raw.framework_attrs,
        declared=declared,
        text=text,
        norm=normalized_signals_for(raw, text),
        form_index=raw.form_index,
        fieldset_index=raw.fieldset_index,
        sibling_control_count=raw.sibling_control_count,
        is_visible=not is_honeypot(raw),
        bbox=raw.bbox,
    )


def _synthetic(
    *,
    selector: str,
    frame_path: Sequence[str],
    shadow_path: Sequence[str],
    document_index: int,
    tag: str,
    reason: UndetectableReason,
) -> FieldDescriptor:
    """Build the descriptor that names a blind spot (spec section 9.6)."""
    return FieldDescriptor(
        selector=selector,
        frame_path=tuple(frame_path),
        shadow_path=tuple(shadow_path),
        document_index=document_index,
        tag=tag,
        undetectable_reason=reason.value,
    )


def _node_chain(node: Mapping[str, Any]) -> tuple[ChainStep, ...]:
    """Decode the ancestor chain of a frame, canvas, or closed-shadow node."""
    return raw_control_from_json(node).chain


def _node_hosts(node: Mapping[str, Any]) -> list[str]:
    """Decode the shadow host chain of a frame, canvas, or closed-shadow node."""
    return _host_selectors(raw_control_from_json(node).shadow_host_chains)


def _node_selector(node: Mapping[str, Any], frame_path: Sequence[str]) -> str:
    """Build the selector of a non-control node, boundaries included."""
    hosts = _node_hosts(node)
    anchor = DOCUMENT_ANCHOR if not hosts else ""
    choice = selector_for_chain(_node_chain(node), root_anchor=anchor)
    return join_frames(frame_path, join_shadow_path(hosts, choice.selector))


def descriptors_from_roots(
    roots: Sequence[RootRecords], *, options: ExtractOptions | None = None, url: str = ""
) -> ExtractionResult:
    """Assemble an extraction result from already-collected root records.

    This is the whole extractor minus the browser. A test that wants to assert
    a selector, a group, or a honeypot decision builds records and calls this;
    only the tests that assert what a page actually says need Chromium.
    """
    resolved = options if options is not None else ExtractOptions()
    now_year = resolved.resolved_year()

    ordered: list[FieldDescriptor] = []
    raws: list[RawControl | None] = []
    canvases: list[CanvasRegion] = []
    controls_seen = 0
    truncated = False
    unreadable_frames: list[str] = []

    for root in roots:
        controls_seen += root.seen
        truncated = truncated or root.truncated
        for node in root.nodes:
            kind = node.get("kind")
            index = len(ordered)
            if kind == "control":
                raw = raw_control_from_json(node)
                ordered.append(
                    _descriptor_for(raw, frame_path=root.frame_path, document_index=index)
                )
                raws.append(raw)
            elif kind == "closedShadow":
                ordered.append(
                    _synthetic(
                        selector=_node_selector(node, root.frame_path),
                        frame_path=root.frame_path,
                        shadow_path=_node_hosts(node),
                        document_index=index,
                        tag=str(node.get("tag", "div")),
                        reason=UndetectableReason.CLOSED_SHADOW_ROOT,
                    )
                )
                raws.append(None)
            elif kind == "frame" and not node.get("accessible", False):
                selector = frame_token(_node_selector(node, root.frame_path))
                unreadable_frames.append(selector)
                ordered.append(
                    _synthetic(
                        selector=selector,
                        frame_path=root.frame_path,
                        shadow_path=_node_hosts(node),
                        document_index=index,
                        tag=str(node.get("tag", "iframe")),
                        reason=UndetectableReason.CROSS_ORIGIN_FRAME,
                    )
                )
                raws.append(None)
            elif kind == "canvas":
                canvases.append(
                    CanvasRegion(
                        selector=_node_selector(node, root.frame_path),
                        width=float(node.get("width", 0.0)),
                        height=float(node.get("height", 0.0)),
                        frame_path=tuple(root.frame_path),
                    )
                )

    placeholder = RawControl()
    grouped = detect_groups(
        ordered, [raw if raw is not None else placeholder for raw in raws], now_year=now_year
    )

    fields: list[FieldDescriptor] = []
    honeypots: list[FieldDescriptor] = []
    for descriptor in grouped:
        if descriptor.undetectable_reason is None and not descriptor.is_visible:
            honeypots.append(descriptor)
        else:
            fields.append(descriptor)

    if not fields and canvases:
        # Spec section 9.6: a form-ish page that yields zero controls but holds a
        # large canvas gets exactly one page-level descriptor. A page that has
        # controls *and* a canvas records the canvas and emits nothing extra,
        # which is what keeps a descriptor count comparable to an answer key.
        largest = max(canvases, key=lambda region: region.area)
        fields.append(
            _synthetic(
                selector=largest.selector,
                frame_path=largest.frame_path,
                shadow_path=(),
                document_index=len(ordered),
                tag="canvas",
                reason=UndetectableReason.CANVAS_REGION,
            )
        )

    warnings: list[ExtractionWarning] = []
    if truncated:
        warnings.append(
            ExtractionWarning(
                ExtractionWarningCode.TRUNCATED,
                f"stopped after {resolved.max_controls} controls; the page has more",
            )
        )
    if unreadable_frames:
        listed = ", ".join(unreadable_frames)
        warnings.append(
            ExtractionWarning(
                ExtractionWarningCode.FRAME_UNREADABLE,
                f"could not read {len(unreadable_frames)} frame(s): {listed}",
            )
        )

    return ExtractionResult(
        fields=tuple(fields),
        honeypots=tuple(honeypots),
        canvas_regions=tuple(canvases),
        warnings=tuple(warnings),
        controls_seen=controls_seen,
        truncated=truncated,
        frame_count=len(roots),
        url=url,
    )


# ---------------------------------------------------------------------------
# The browser side.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RootPayload:
    """What one evaluation of the traversal script returned."""

    nodes: tuple[Mapping[str, Any], ...]
    children: tuple[Frame | None, ...]
    seen: int
    truncated: bool


@dataclass(slots=True)
class _Walk:
    """The mutable state one page-wide walk carries between roots."""

    script: str
    options: ExtractOptions
    remaining: int
    roots: list[RootRecords]


def _evaluate_root(frame: Frame, walk: _Walk) -> _RootPayload:
    """Run the traversal in one frame and decode what it returned.

    ``frameElements`` comes back as a handle rather than as JSON because a DOM
    element cannot be serialised. Reading it as a parallel array is what lets a
    frame node in the record list be matched to its ``Frame`` exactly, instead
    of by querying the document again and trusting the two orders to agree.
    """
    handle: JSHandle = frame.evaluate_handle(
        walk.script,
        {
            "maxOptions": walk.options.max_options,
            "maxControls": max(walk.remaining, 0),
            "minCanvasArea": walk.options.canvas_min_area,
            "frameworkAttrs": list(FRAMEWORK_ATTRIBUTES),
        },
    )
    try:
        payload = handle.get_property("nodes").json_value()
        seen = int(handle.get_property("seen").json_value())
        truncated = bool(handle.get_property("truncated").json_value())
        elements = handle.get_property("frameElements")
        children: list[Frame | None] = []
        try:
            count = int(elements.get_property("length").json_value())
            for position in range(count):
                item = elements.get_property(str(position))
                element = item.as_element()
                children.append(element.content_frame() if element is not None else None)
        finally:
            elements.dispose()
    finally:
        handle.dispose()

    nodes = (
        tuple(item for item in payload if isinstance(item, Mapping))
        if isinstance(payload, list)
        else ()
    )
    return _RootPayload(nodes=nodes, children=tuple(children), seen=seen, truncated=truncated)


def _walk_frame(frame: Frame, walk: _Walk, *, frame_path: tuple[str, ...], depth: int) -> None:
    """Walk one root and then, depth first, each readable frame inside it."""
    try:
        payload = _evaluate_root(frame, walk)
    except PlaywrightError:
        # A frame that navigated or detached mid-walk costs exactly that frame,
        # which is the whole reason spec section 9.1 treats frames as roots.
        return

    walk.remaining -= sum(1 for node in payload.nodes if node.get("kind") == "control")
    walk.roots.append(
        RootRecords(
            frame_path=frame_path,
            nodes=payload.nodes,
            seen=payload.seen,
            truncated=payload.truncated,
        )
    )
    if depth >= walk.options.max_frame_depth:
        return

    for node in payload.nodes:
        if node.get("kind") != "frame" or not node.get("accessible", False):
            continue
        position = node.get("frameIndex")
        if not isinstance(position, int) or position >= len(payload.children):
            continue
        child = payload.children[position]
        if child is None or child.is_detached():
            continue
        token = frame_token(_node_selector(node, frame_path))
        _walk_frame(child, walk, frame_path=(*frame_path, token), depth=depth + 1)


def extract_result(
    page: Page,
    *,
    options: ExtractOptions | None = None,
    settle: SettleReport | None = None,
) -> ExtractionResult:
    """Extract every control on ``page``, page-level surface included.

    Args:
        page: an already-loaded page. Loading is the loader's job, and keeping
            the two apart is what lets the whole extractor be tested against
            hand-built records with no browser at all.
        options: the collection bounds; the documented defaults otherwise.
        settle: what the loader's bounded wait observed. Passing it is what puts
            the ``INCOMPLETE`` warning on the result, so a caller that loaded
            the page itself does not lose the one fact the extractor cannot
            re-derive.
    """
    resolved = options if options is not None else ExtractOptions()
    walk = _Walk(
        script=traversal_script(),
        options=resolved,
        remaining=resolved.max_controls,
        roots=[],
    )
    _walk_frame(page.main_frame, walk, frame_path=(), depth=0)
    result = descriptors_from_roots(walk.roots, options=resolved, url=page.url)

    if settle is None:
        return result
    warnings = list(result.warnings)
    if not settle.reached_quiet:
        warnings.append(
            ExtractionWarning(
                ExtractionWarningCode.INCOMPLETE,
                f"the page was still changing after {settle.waited_ms:.0f} ms; "
                f"{settle.controls_added_after_load} control(s) appeared after load "
                f"and more may follow",
            )
        )
    return ExtractionResult(
        fields=result.fields,
        honeypots=result.honeypots,
        canvas_regions=result.canvas_regions,
        warnings=tuple(warnings),
        settle=settle,
        controls_seen=result.controls_seen,
        truncated=result.truncated,
        frame_count=result.frame_count,
        url=result.url,
    )


def extract(page: Page, *, options: ExtractOptions | None = None) -> list[FieldDescriptor]:
    """Extract every control on ``page`` (spec sections 5.1 and 9.1).

    The public entry point. Takes a ``Page`` and returns
    ``list[FieldDescriptor]``, which is the only interface anything downstream
    sees. ``extract_result`` is the same walk with the page-level surface
    attached, for a caller that needs the honeypots, the canvases, or the
    warnings.
    """
    return list(extract_result(page, options=options).fields)
