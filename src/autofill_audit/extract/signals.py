"""Per-control signal collection: label, ARIA, placeholder, name, id, class, context.

Collects signals only; it never classifies (spec sections 5.1 and 9.2).

The division of labour with the traversal script is deliberate. The script reads
the DOM and returns records of plain JSON; every decision made *about* those
records happens here, in Python, where it is unit-testable without a browser.
That is why ``RawControl`` exists: it is the typed boundary between "what the
page said" and "what the extractor concluded", and it means the honeypot rule,
the label-source preference, the option truncation, and the autocomplete grammar
are all covered by tests that never launch Chromium.

Two rules from spec section 9.2 are load bearing and easy to lose:

**Missing is ``None``, absent is not empty.** ``placeholder=""`` means somebody
wrote the attribute and left it blank, which is a different fact about the page
from not having written it, and both are different from a placeholder with text
in it. The traversal script returns ``null`` only for an absent attribute.

**``data-*`` contributes keys, never values.** A generated corpus that embedded
truth in a data attribute would leak into training (spec section 5.6), and this
rule makes the leak impossible even if a future template regresses. The
framework attributes beside them are *not* covered by that rule and do carry
their values, because ``formcontrolname="postalCode"`` is an identifier in
exactly the way ``name="postalCode"`` is; the difference is written down here so
that nobody later "fixes" one to match the other.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from autofill_audit.descriptors import DeclaredAutocomplete, NormalizedSignals, TextSignals
from autofill_audit.extract.normalize import normalize_identifier_tokens, normalize_tokens
from autofill_audit.extract.selector import ChainStep
from autofill_audit.taxonomy import SPEC_TOKENS

__all__ = [
    "ADDRESS_MODIFIERS",
    "CONTACT_MODIFIERS",
    "LABEL_SOURCE_ORDER",
    "MAX_OPTIONS",
    "WHATWG_FIELD_NAMES",
    "RawControl",
    "is_honeypot",
    "normalized_signals_for",
    "parse_autocomplete",
    "raw_control_from_json",
    "text_signals_of",
]

MAX_OPTIONS: Final[int] = 24
"""How many option labels and values a ``<select>`` contributes (spec 9.2's N).

Twice the largest option list this project reasons about. Spec section 9.4 gives
the descriptor no field for the *total* option count, so the only way a consumer
can tell a complete list of twelve months from the first twelve of five thousand
is for the cut to fall somewhere a meaningful list never reaches. Twelve months
and eleven expiry years both fit inside twenty four with room to spare, so a
collected list of exactly twelve is always a real twelve."""

ADDRESS_MODIFIERS: Final[frozenset[str]] = frozenset({"shipping", "billing"})
CONTACT_MODIFIERS: Final[frozenset[str]] = frozenset({"home", "work", "mobile", "fax", "pager"})
_TRAILING_MODIFIERS: Final[frozenset[str]] = frozenset({"webauthn"})
_ALL_MODIFIERS: Final[frozenset[str]] = ADDRESS_MODIFIERS | CONTACT_MODIFIERS | _TRAILING_MODIFIERS

_SECTION_PREFIX: Final[str] = "section-"
_OFF: Final[str] = "off"
_ON: Final[str] = "on"

_TAXONOMY_TOKENS: Final[frozenset[str]] = frozenset(label.value for label in SPEC_TOKENS)

_ADDITIONAL_WHATWG_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "organization-title",
        "address-level3",
        "address-level4",
        "cc-given-name",
        "cc-additional-name",
        "cc-family-name",
        "transaction-currency",
        "language",
        "bday-day",
        "bday-month",
        "bday-year",
        "photo",
        "impp",
        "tel-area-code",
        "tel-local",
        "tel-local-prefix",
        "tel-local-suffix",
    }
)
"""The WHATWG field-name tokens this project's taxonomy deliberately leaves out.

Spec section 7.1 excludes them as *labels* because no corpus template emits them
and law 2 would fail them. That is a statement about what the classifier may
predict, not about what HTML permits, so a page declaring ``address-level3`` has
declared something valid and must not be reported as off specification. Keeping
the two sets apart here is what stops the taxonomy's scope from leaking into a
judgement about the page."""

WHATWG_FIELD_NAMES: Final[frozenset[str]] = _TAXONOMY_TOKENS | _ADDITIONAL_WHATWG_TOKENS
"""Every autofill field-name token the HTML specification defines."""

LABEL_SOURCE_ORDER: Final[tuple[str, ...]] = (
    "label_for",
    "label_ancestor",
    "aria_label",
    "aria_labelledby_text",
    "title",
    "placeholder",
)
"""Strongest label source first.

A ``<label for>`` beats an ancestor ``<label>`` because it is explicit; both beat
ARIA, which is a repair rather than markup; ``title`` beats ``placeholder``
because a placeholder is not a label at all and is last precisely so that a
consumer can see when it was pressed into service as one. ``aria-describedby``
is not on this list: a description is context, not a name, and it goes into the
context stream.
"""


# ---------------------------------------------------------------------------
# The autocomplete grammar (spec sections 7.1 and 9.4).
# ---------------------------------------------------------------------------


def parse_autocomplete(raw: str | None) -> DeclaredAutocomplete:
    """Parse an ``autocomplete`` attribute value into its parts.

    The grammar the HTML specification defines is an optional ``section-*``
    token, then an optional address modifier, then an optional contact
    modifier, then the field name, then an optional ``webauthn``. Order is
    **not** enforced here. Real pages get the order wrong and still meant
    something, and refusing to read a value because its tokens are in the wrong
    sequence would turn a reportable mistake into an invisible one.

    ``is_off_spec`` is true when the attribute is present and does not name
    exactly one field-name token the specification defines. That covers four
    cases, all of them worth a finding: a token nobody defines
    (``autocomplete="zipcode"``), modifiers with no field name
    (``autocomplete="shipping"``), an attribute present but empty
    (``autocomplete=""``), and two field names at once.

    ``autocomplete="off"`` and ``autocomplete="on"`` are valid values that name
    no field, so neither is off specification; ``is_off`` separates the first
    from everything else.
    """
    if raw is None:
        return DeclaredAutocomplete()

    tokens = [token.casefold() for token in raw.split()]
    section: str | None = None
    modifiers: list[str] = []
    remaining: list[str] = []
    is_off = False
    is_on = False

    for token in tokens:
        if token.startswith(_SECTION_PREFIX):
            if section is None:
                section = token
            continue
        if token in _ALL_MODIFIERS:
            modifiers.append(token)
            continue
        if token == _OFF:
            is_off = True
            continue
        if token == _ON:
            is_on = True
            continue
        remaining.append(token)

    token_value = remaining[0] if remaining else None
    if is_off or is_on:
        off_spec = bool(remaining)
    else:
        off_spec = len(remaining) != 1 or remaining[0] not in WHATWG_FIELD_NAMES

    return DeclaredAutocomplete(
        raw=raw,
        token=token_value,
        modifiers=tuple(modifiers),
        section=section,
        is_off_spec=off_spec,
        is_off=is_off,
    )


# ---------------------------------------------------------------------------
# The raw record the traversal script returns.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RawControl:
    """One control exactly as the page reported it, before any judgement.

    Five members carry signals spec section 9.2 asks for that spec section 9.4's
    descriptor has no field to hold: ``minlength``, ``multiple``, ``step``,
    ``min``, and ``max``. They are collected because 9.2 says to and because
    group detection reads ``multiple`` (a multi-select with twelve options is a
    list of months to a careless detector and a multiple-choice control to a
    careful one). They stop here, because 9.4 is the fixed downstream contract
    and widening it would be a schema change every golden test inherits.
    """

    tag: str = "input"
    input_type: str | None = None
    inputmode: str | None = None
    pattern: str | None = None
    maxlength: int | None = None
    minlength: int | None = None
    required: bool = False
    readonly: bool = False
    disabled: bool = False
    multiple: bool = False
    step: str | None = None
    min: str | None = None
    max: str | None = None

    autocomplete_raw: str | None = None

    name: str | None = None
    element_id: str | None = None
    name_unique_in_form: bool = False
    css_classes: tuple[str, ...] = ()
    data_keys: tuple[str, ...] = ()
    framework_attrs: tuple[tuple[str, str], ...] = ()

    label_for: str | None = None
    label_ancestor: str | None = None
    aria_label: str | None = None
    aria_labelledby_text: str | None = None
    aria_describedby_text: str | None = None
    title: str | None = None
    placeholder: str | None = None
    preceding_text: str | None = None
    legend: str | None = None
    section_heading: str | None = None
    form_accessible_name: str | None = None

    option_labels: tuple[str, ...] = ()
    option_values: tuple[str, ...] = ()
    option_count: int = 0

    form_key: str | None = None
    form_index: int | None = None
    fieldset_key: str | None = None
    fieldset_index: int | None = None
    sibling_control_count: int = 0
    parent_key: str = ""

    chain: tuple[ChainStep, ...] = ()
    shadow_host_chains: tuple[tuple[ChainStep, ...], ...] = ()

    bbox: tuple[float, float, float, float] | None = None
    style_hidden: bool = False
    zero_size: bool = False
    offscreen: bool = False


def _opt_str(payload: Mapping[str, Any], key: str) -> str | None:
    """Read an optional string from a JSON record."""
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _opt_int(payload: Mapping[str, Any], key: str) -> int | None:
    """Read an optional integer from a JSON record."""
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _flag(payload: Mapping[str, Any], key: str) -> bool:
    """Read a boolean from a JSON record, defaulting to False."""
    return payload.get(key) is True


def _strings(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """Read a list of strings from a JSON record."""
    value = payload.get(key)
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _chain(value: object) -> tuple[ChainStep, ...]:
    """Rebuild one ancestor chain from the JSON the traversal script returns."""
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    steps: list[ChainStep] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        tag = item.get("tag")
        nth = item.get("nth")
        if not isinstance(tag, str) or isinstance(nth, bool) or not isinstance(nth, int):
            continue
        steps.append(
            ChainStep(
                tag=tag,
                nth=nth,
                element_id=_opt_str(item, "id"),
                id_unique=_flag(item, "idUnique"),
                form_name=_opt_str(item, "formName"),
            )
        )
    return tuple(steps)


def _bbox(value: object) -> tuple[float, float, float, float] | None:
    """Rebuild a bounding box from the JSON the traversal script returns."""
    if not isinstance(value, Sequence) or isinstance(value, str) or len(value) != 4:
        return None
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float):
            return None
        numbers.append(float(item))
    return (numbers[0], numbers[1], numbers[2], numbers[3])


def raw_control_from_json(payload: Mapping[str, Any]) -> RawControl:
    """Rebuild a ``RawControl`` from one traversal-script record.

    Unreadable members fall back to their defaults rather than raising. The
    script and this function ship together, so a mismatch is a bug in one of
    them, but a page is allowed to be strange and an extractor that aborted a
    whole walk over one odd attribute would be useless on the pages that most
    need auditing.
    """
    pairs: list[tuple[str, str]] = []
    framework = payload.get("frameworkAttrs")
    if isinstance(framework, Sequence) and not isinstance(framework, str):
        for item in framework:
            if (
                isinstance(item, Sequence)
                and not isinstance(item, str)
                and len(item) == 2
                and isinstance(item[0], str)
                and isinstance(item[1], str)
            ):
                pairs.append((item[0], item[1]))

    shadow_chains = payload.get("shadowHostChains")
    host_chains: tuple[tuple[ChainStep, ...], ...] = ()
    if isinstance(shadow_chains, Sequence) and not isinstance(shadow_chains, str):
        host_chains = tuple(_chain(item) for item in shadow_chains)

    return RawControl(
        tag=_opt_str(payload, "tag") or "input",
        input_type=_opt_str(payload, "inputType"),
        inputmode=_opt_str(payload, "inputmode"),
        pattern=_opt_str(payload, "pattern"),
        maxlength=_opt_int(payload, "maxlength"),
        minlength=_opt_int(payload, "minlength"),
        required=_flag(payload, "required"),
        readonly=_flag(payload, "readonly"),
        disabled=_flag(payload, "disabled"),
        multiple=_flag(payload, "multiple"),
        step=_opt_str(payload, "step"),
        min=_opt_str(payload, "min"),
        max=_opt_str(payload, "max"),
        autocomplete_raw=_opt_str(payload, "autocompleteRaw"),
        name=_opt_str(payload, "name"),
        element_id=_opt_str(payload, "elementId"),
        name_unique_in_form=_flag(payload, "nameUniqueInForm"),
        css_classes=_strings(payload, "cssClasses"),
        data_keys=_strings(payload, "dataKeys"),
        framework_attrs=tuple(pairs),
        label_for=_opt_str(payload, "labelFor"),
        label_ancestor=_opt_str(payload, "labelAncestor"),
        aria_label=_opt_str(payload, "ariaLabel"),
        aria_labelledby_text=_opt_str(payload, "ariaLabelledbyText"),
        aria_describedby_text=_opt_str(payload, "ariaDescribedbyText"),
        title=_opt_str(payload, "title"),
        placeholder=_opt_str(payload, "placeholder"),
        preceding_text=_opt_str(payload, "precedingText"),
        legend=_opt_str(payload, "legend"),
        section_heading=_opt_str(payload, "sectionHeading"),
        form_accessible_name=_opt_str(payload, "formAccessibleName"),
        option_labels=_strings(payload, "optionLabels"),
        option_values=_strings(payload, "optionValues"),
        option_count=_opt_int(payload, "optionCount") or 0,
        form_key=_opt_str(payload, "formKey"),
        form_index=_opt_int(payload, "formIndex"),
        fieldset_key=_opt_str(payload, "fieldsetKey"),
        fieldset_index=_opt_int(payload, "fieldsetIndex"),
        sibling_control_count=_opt_int(payload, "siblingControlCount") or 0,
        parent_key=_opt_str(payload, "parentKey") or "",
        chain=_chain(payload.get("chain")),
        shadow_host_chains=host_chains,
        bbox=_bbox(payload.get("bbox")),
        style_hidden=_flag(payload, "styleHidden"),
        zero_size=_flag(payload, "zeroSize"),
        offscreen=_flag(payload, "offscreen"),
    )


# ---------------------------------------------------------------------------
# Derived signals.
# ---------------------------------------------------------------------------


def is_honeypot(raw: RawControl) -> bool:
    """Whether a control is invisible to a user, and so excluded from the audit.

    Spec section 9.6 names three shapes and this implements exactly those: a
    style that hides the element, a zero-size bounding box, and a position
    entirely off the top or left of the document, which is what
    ``position:absolute; left:-9999px`` produces.

    Deliberately **not** included: a control that is simply below the fold. A
    long form is not a page full of honeypots, and a rule that compared against
    the viewport rather than the document would say it was.

    A control excluded here is retained on ``ExtractionResult.honeypots`` rather
    than dropped, because a report whose field count disagrees with the count a
    developer sees in their own markup is a report they stop trusting.
    """
    return raw.style_hidden or raw.zero_size or raw.offscreen


def text_signals_of(raw: RawControl) -> TextSignals:
    """Assemble the raw text signals, preserving absent versus empty."""
    return TextSignals(
        label_for=raw.label_for,
        label_ancestor=raw.label_ancestor,
        aria_label=raw.aria_label,
        aria_labelledby_text=raw.aria_labelledby_text,
        aria_describedby_text=raw.aria_describedby_text,
        title=raw.title,
        placeholder=raw.placeholder,
        preceding_text=raw.preceding_text,
        legend=raw.legend,
        section_heading=raw.section_heading,
        form_accessible_name=raw.form_accessible_name,
    )


def _strongest_label(text: TextSignals) -> tuple[tuple[str, ...], str | None]:
    """Return the tokens of the strongest available label source, and its name.

    A source that is present but blank still wins its place in the order and
    still contributes no tokens. That is the honest answer: the page did label
    the field, with nothing.
    """
    for source in LABEL_SOURCE_ORDER:
        value = getattr(text, source)
        if value is None:
            continue
        return normalize_tokens(value), source
    return (), None


def normalized_signals_for(raw: RawControl, text: TextSignals) -> NormalizedSignals:
    """Derive the normalised token streams (spec sections 9.4 and 9.7).

    Duplicates are kept. An id and a name that say the same thing are two
    pieces of evidence that the page says it twice, and removing one would make
    a strongly identified control indistinguishable from a weakly identified
    one in the feature space.

    The declared ``autocomplete`` token is **not** folded into any stream. It is
    the thing the audit engine compares an inference *against* (spec section
    11.2), and a classifier that had been fed it would agree with the page by
    construction and find nothing.
    """
    label_tokens, label_source = _strongest_label(text)

    identifier_sources: list[str] = []
    if raw.name is not None:
        identifier_sources.append(raw.name)
    if raw.element_id is not None:
        identifier_sources.append(raw.element_id)
    identifier_sources.extend(raw.css_classes)
    identifier_sources.extend(raw.data_keys)
    identifier_sources.extend(value for _, value in raw.framework_attrs)
    identifier_tokens: list[str] = []
    for source in identifier_sources:
        identifier_tokens.extend(normalize_identifier_tokens(source))

    context_sources: list[str | None] = [
        text.preceding_text,
        text.legend,
        text.section_heading,
        text.form_accessible_name,
        text.aria_describedby_text,
    ]
    context_tokens: list[str] = []
    for context in context_sources:
        if context is None:
            continue
        context_tokens.extend(normalize_tokens(context))

    all_tokens = (*label_tokens, *identifier_tokens, *context_tokens)
    blob = " ".join(
        [
            *(f"L:{token}" for token in label_tokens),
            *(f"I:{token}" for token in identifier_tokens),
            *(f"C:{token}" for token in context_tokens),
        ]
    )
    return NormalizedSignals(
        label_tokens=label_tokens,
        label_source=label_source,
        identifier_tokens=tuple(identifier_tokens),
        context_tokens=tuple(context_tokens),
        all_tokens=all_tokens,
        text_blob=blob,
    )
