"""Browser-free descriptor and extraction-result builders for the audit tests.

Everything downstream of the DOM traversal is pure Python over plain records
(P2's handoff calls ``descriptors_from_roots`` the browser-free seam), so an
audit test that wants a control with a particular label and no declaration has
no business launching Chromium to get one.

The builders here go through the extractor's **own** ``text_signals_of``,
``normalized_signals_for``, and ``parse_autocomplete`` rather than filling a
``NormalizedSignals`` in by hand. That is the point: a test that hand-wrote its
token streams would pass while the real normalisation disagreed with it, and the
first thing anybody would learn from the failure is that the test was lying.
"""

from __future__ import annotations

from autofill_audit.descriptors import (
    ExtractionResult,
    FieldDescriptor,
    GroupRole,
    SettleReport,
)
from autofill_audit.extract.signals import (
    RawControl,
    normalized_signals_for,
    parse_autocomplete,
    text_signals_of,
)

__all__ = ["make_descriptor", "make_result"]


def make_descriptor(
    selector: str = "#field",
    *,
    label: str | None = None,
    aria_label: str | None = None,
    title: str | None = None,
    placeholder: str | None = None,
    context: str | None = None,
    legend: str | None = None,
    name: str | None = None,
    element_id: str | None = None,
    css_classes: tuple[str, ...] = (),
    tag: str = "input",
    input_type: str | None = "text",
    inputmode: str | None = None,
    maxlength: int | None = None,
    declared: str | None = None,
    option_labels: tuple[str, ...] = (),
    option_values: tuple[str, ...] = (),
    group_role: GroupRole = GroupRole.NONE,
    group_id: str | None = None,
    form_index: int | None = 0,
    document_index: int = 0,
    undetectable_reason: str | None = None,
    is_visible: bool = True,
) -> FieldDescriptor:
    """Build one descriptor the way the extractor would have built it."""
    raw = RawControl(
        tag=tag,
        input_type=input_type,
        inputmode=inputmode,
        maxlength=maxlength,
        autocomplete_raw=declared,
        name=name,
        element_id=element_id,
        css_classes=css_classes,
        label_for=label,
        aria_label=aria_label,
        title=title,
        placeholder=placeholder,
        section_heading=context,
        legend=legend,
        option_labels=option_labels,
        option_values=option_values,
        form_index=form_index,
    )
    text = text_signals_of(raw)
    return FieldDescriptor(
        selector=selector,
        document_index=document_index,
        tag=tag,
        input_type=input_type,
        inputmode=inputmode,
        maxlength=maxlength,
        name=name,
        element_id=element_id,
        css_classes=css_classes,
        option_labels=option_labels,
        option_values=option_values,
        declared=parse_autocomplete(declared),
        text=text,
        norm=normalized_signals_for(raw, text),
        form_index=form_index,
        group_role=group_role,
        group_id=group_id,
        is_visible=is_visible,
        undetectable_reason=undetectable_reason,
    )


def make_result(
    *descriptors: FieldDescriptor,
    url: str = "fixture://built.html",
    honeypots: tuple[FieldDescriptor, ...] = (),
) -> ExtractionResult:
    """Wrap descriptors in the page-level surface the audit engine consumes."""
    return ExtractionResult(
        fields=tuple(descriptors),
        honeypots=honeypots,
        settle=SettleReport(),
        controls_seen=len(descriptors) + len(honeypots),
        url=url,
    )
